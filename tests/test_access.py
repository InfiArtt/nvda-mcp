"""MCP Access end to end: the add-on's sharing session, a relay, and the server's tools on the helper's side."""

import queue

import accessCrypto
import accessShare
import anyio
import pytest
from bridge import Bridge, BridgeError
from fake_relay import FakeRelay
from mcp import Client

from nvda_mcp import access_crypto, server
from nvda_mcp.access_client import AccessClient, tls_context
from nvda_mcp.bridge_client import SUPPORTED_PROTOCOL_VERSION, NvdaUnavailableError

pytestmark = pytest.mark.anyio


class Sharer:
    """The computer being helped: a bridge's handlers shared through ShareSession."""

    def __init__(self, relay_url, allow=True):
        self.calls = []
        self.events = queue.Queue()
        self.asked = []
        handlers = {
            "getFocus": self.record("getFocus", {"name": "Send", "role": "button", "appName": "whatsapp"}),
            "getStatus": self.record("getStatus", {"nvdaVersion": "2025.1.2", "lastSpeechId": 0}),
            "reloadPlugins": self.record("reloadPlugins", {}),
            "pressKeys": self.refuse_keys,
        }
        bridge = Bridge(handlers, "unused.json", onError=print)

        def approve(name, fingerprint):
            self.asked.append((name, fingerprint))
            return allow

        self.session = accessShare.ShareSession(
            relay_url,
            bridge.dispatch,
            approve,
            lambda event, details: self.events.put((event, details)),
            computerName="Aswar's laptop",
            addonVersion="1.4.0",
            protocolVersion=SUPPORTED_PROTOCOL_VERSION,
        )

    def record(self, method, result):
        def handler(params):
            self.calls.append((method, params))
            return result

        return handler

    def refuse_keys(self, params):
        self.calls.append(("pressKeys", params))
        raise BridgeError("controlDisabled", "Pressing keys is turned off.")

    async def next_event(self, timeout=10):
        return await anyio.to_thread.run_sync(lambda: self.events.get(timeout=timeout))


@pytest.fixture
async def relay():
    fake = FakeRelay()
    async with fake.serve() as served:
        port = served.sockets[0].getsockname()[1]
        fake.url = f"ws://127.0.0.1:{port}/v1"
        yield fake


def text_of(result):
    return result.content[0].text


async def test_a_helper_works_on_the_shared_computer_and_the_relay_sees_only_ciphertext(relay):
    sharer = Sharer(relay.url)
    sharer.session.start()
    event, details = await sharer.next_event()
    assert event == "waiting" and details["minutes"] == 10
    async with Client(server.mcp) as client:
        connected = await client.call_tool(
            "nvda_access_connect", {"code": details["code"], "relay": relay.url}
        )
        assert not connected.is_error, text_of(connected)
        assert (await sharer.next_event())[0] == "connected"
        focus = await client.call_tool("nvda_get_focus", {})
        status = await client.call_tool("nvda_get_status", {})
        refused = await client.call_tool("nvda_reload_plugins", {})
        keys = await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
        disconnected = await client.call_tool("nvda_access_disconnect", {})
    assert "Connected to Aswar's laptop through MCP Access" in text_of(connected)
    assert "Focus: Send (button)" in text_of(focus)
    assert "Aswar's laptop" in text_of(status)
    assert refused.is_error and "notAllowedOverAccess" in text_of(refused)
    assert all(method != "reloadPlugins" for method, _params in sharer.calls)
    assert keys.is_error and "controlDisabled" in text_of(keys)
    press = next(params for method, params in sharer.calls if method == "pressKeys")
    assert press["clientName"].endswith("through MCP Access")
    assert press["viaAccess"] == sharer.session.sessionId
    assert "Disconnected from Aswar's laptop" in text_of(disconnected)
    event, details = await sharer.next_event()
    # The relay closes with 4000 when the other side leaves: the sharer hears that the helper ended it.
    assert event == "ended" and details["kind"] == "helperLeft", details
    # After pairing, everything the relay forwarded was binary and none of it was readable.
    forwarded = b"".join(message for message in relay.seen if isinstance(message, bytes))
    assert b"Send" not in forwarded and b"getFocus" not in forwarded and b"Aswar" not in forwarded


async def test_nothing_is_shared_when_the_person_says_no(relay):
    sharer = Sharer(relay.url, allow=False)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
    assert result.is_error and "did not allow" in text_of(result)
    assert sharer.asked and sharer.calls == []
    event, details = await sharer.next_event()
    assert event == "ended" and details["kind"] == "declined" and "did not allow" in details["reason"]


async def test_a_wrong_code_finds_nothing(relay):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "nvda_access_connect", {"code": "K7Q4-9XMC-4TRW-PH3N-AD6F", "relay": relay.url}
        )
    assert result.is_error and "No such room" in text_of(result)


def test_unencrypted_relays_are_only_allowed_on_this_computer():
    with pytest.raises(NvdaUnavailableError, match="wss://"):
        AccessClient("ws://access.example.com/v1")
    with pytest.raises(accessShare.AccessShareError, match="wss://"):
        accessShare.WebSocket("ws://access.example.com/v1")


def test_both_sides_accept_only_tls_1_3_with_verified_certificates():
    for context in (tls_context(), accessShare.tlsContext()):
        assert context.minimum_version.name == "TLSv1_3"
        assert context.check_hostname and context.verify_mode.name == "CERT_REQUIRED"


def test_the_add_on_and_server_copies_of_the_encryption_agree():
    code = accessCrypto.newCode()
    sharer = accessCrypto.Handshake(code, "sharer")
    helper = access_crypto.Handshake(code, "helper")
    sharer_session, helper_session = sharer.finish(helper.publicKey), helper.finish(sharer.publicKey)
    assert helper_session.open(sharer_session.seal(b"add-on to server")) == b"add-on to server"
    assert sharer_session.open(helper_session.seal(b"server to add-on")) == b"server to add-on"


def test_risky_methods_are_not_shared():
    for method in ("reloadPlugins", "runScript", "getLog", "getSettings", "webElementInfo", "captureControl"):
        assert method not in accessShare.ALLOWED_METHODS


def test_large_messages_are_masked_correctly():
    payload = bytes(range(256)) * 40
    mask = b"\x01\x02\x03\x04"
    expected = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    assert accessShare._mask(payload, mask) == expected
