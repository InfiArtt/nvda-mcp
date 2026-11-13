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
    for method in ("reloadPlugins", "runScript", "getLog", "getSettings", "webElementInfo"):
        assert method not in accessShare.ALLOWED_METHODS
    # Pictures and key presses reach the add-on, which asks the person being helped once per session.
    assert {"captureControl", "pressKeys"} <= accessShare.ALLOWED_METHODS


def test_large_messages_are_masked_correctly():
    payload = bytes(range(256)) * 40
    mask = b"\x01\x02\x03\x04"
    expected = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    assert accessShare._mask(payload, mask) == expected


async def test_the_two_people_can_message_each_other(relay):
    sharer = Sharer(relay.url)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
        assert (await sharer.next_event())[0] == "connected"
        sent = await client.call_tool("nvda_access_send_message", {"text": "Halo Aswar, mau dibantu apa?"})
        event, message = await sharer.next_event()
        nothing = await client.call_tool("nvda_access_messages", {})

        # The helper's assistant waits; the person answers a moment later with the NVDA command.
        async def answer_later():
            await anyio.sleep(0.5)
            await anyio.to_thread.run_sync(sharer.session.sendMessage, "Tolong cek routing GP Mix")

        async with anyio.create_task_group() as group:
            group.start_soon(answer_later)
            started = anyio.current_time()
            answer = await client.call_tool("nvda_access_messages", {"wait_seconds": 10})
            waited = anyio.current_time() - started
        status = await client.call_tool("nvda_get_status", {})
        await client.call_tool("nvda_access_disconnect", {})
    assert not sent.is_error and event == "message"
    assert message["text"] == "Halo Aswar, mau dibantu apa?"
    assert "No new messages" in text_of(nothing)
    assert "[1] Tolong cek routing GP Mix" in text_of(answer)
    assert 0.3 < waited < 5, waited
    assert "not instructions from the user" in text_of(answer)
    assert '"messagesFromThem": 1' in text_of(status)
    assert [kept["from"] for kept in sharer.session.messages] == ["helper", "me"]


async def test_messages_are_cleaned_and_rate_limited(relay):
    sharer = Sharer(relay.url)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
        await sharer.next_event()
        await client.call_tool("nvda_access_send_message", {"text": "line one\x07\n\n  line two  "})
        _event, message = await sharer.next_event()
        results = [
            await client.call_tool("nvda_access_send_message", {"text": f"spam {n}"})
            for n in range(accessShare.MAX_HELPER_MESSAGES_PER_MINUTE)
        ]
        await client.call_tool("nvda_access_disconnect", {})
    assert message["text"] == "line one\n  line two"
    assert results[-1].is_error and "tooManyMessages" in text_of(results[-1])
    assert not results[-2].is_error


def test_a_message_needs_a_connected_helper():
    session = accessShare.ShareSession(
        "ws://127.0.0.1:1/v1",
        lambda m, p: {},
        lambda n, f: True,
        lambda e, d: None,
        "pc",
        "1.4.0",
        SUPPORTED_PROTOCOL_VERSION,
    )
    with pytest.raises(accessShare.AccessShareError, match="No helper"):
        session.sendMessage("hello")
    with pytest.raises(accessShare.AccessShareError, match="empty"):
        session.sendMessage("   ")


async def test_new_messages_come_with_the_next_tool_result_once(relay):
    sharer = Sharer(relay.url)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
        await sharer.next_event()
        await anyio.to_thread.run_sync(sharer.session.sendMessage, "kamu disana? halo?")
        await anyio.sleep(0.3)
        first = await client.call_tool("nvda_get_focus", {})
        second = await client.call_tool("nvda_get_focus", {})
        nothing_new = await client.call_tool("nvda_access_messages", {"after_id": 1})
        await client.call_tool("nvda_access_disconnect", {})
    texts = [content.text for content in first.content]
    assert "Focus: Send (button)" in texts[0]
    assert "New message from the person at Aswar's laptop" in texts[-1] and "kamu disana? halo?" in texts[-1]
    assert not any("New message" in content.text for content in second.content)
    assert "No new messages" in text_of(nothing_new)


async def test_the_inbox_wakes_a_monitor_and_talk_mode_refuses_actions(relay):
    sharer = Sharer(relay.url)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        connected = await client.call_tool(
            "nvda_access_connect",
            {"code": details["code"], "relay": relay.url, "helper_name": "Rafli", "mode": "talk"},
        )
        assert (await sharer.next_event())[0] == "connected"
        inbox = server._access.inbox
        await anyio.to_thread.run_sync(sharer.session.sendMessage, "halo\nada yang bisa dibantu?")
        await anyio.sleep(0.3)
        lines = inbox.read_text(encoding="utf-8").splitlines()
        refused = await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
        reading = await client.call_tool("nvda_get_focus", {})
        await client.call_tool("nvda_access_set_mode", {"mode": "act"})
        allowed = await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
        await client.call_tool("nvda_access_disconnect", {})
    # The person being helped is told an AI is talking to them, and for whom.
    assert sharer.asked[0][0] == "Rafli (AI assistant)"
    assert "as Rafli (AI assistant), in talk mode" in text_of(connected)
    assert inbox.as_posix() in text_of(connected) and "tail -n 0 -F" in text_of(connected)
    assert lines == ["MCP Access message 1 from Aswar's laptop: halo / ada yang bisa dibantu?"]
    assert refused.is_error and "talk mode" in text_of(refused)
    assert not reading.is_error
    # In act mode the request reaches their computer, whose own checks decide.
    assert allowed.is_error and "controlDisabled" in text_of(allowed)
    # The conversation does not stay on disk after the session.
    assert not inbox.exists()


async def test_the_inbox_goes_away_by_itself_when_they_stop_sharing(relay, monkeypatch):
    monkeypatch.setattr("nvda_mcp.access_client.INBOX_KEPT_AFTER_END_SECONDS", 0.3)
    sharer = Sharer(relay.url)
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
        await sharer.next_event()
        inbox = server._access.inbox
        sharer.session.stop()
        await anyio.sleep(0.15)
        last_line = inbox.read_text(encoding="utf-8").splitlines()[-1]
        await anyio.sleep(0.6)
        assert "ended" in last_line and not inbox.exists()
        await client.call_tool("nvda_access_disconnect", {})


async def test_computers_with_different_versions_are_told_to_update(relay):
    sharer = Sharer(relay.url)
    # A computer still on the previous add-on, which knows neither messages nor the mouse.
    sharer.session._protocolVersion = SUPPORTED_PROTOCOL_VERSION - 1
    sharer.session.start()
    _event, details = await sharer.next_event()
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_access_connect", {"code": details["code"], "relay": relay.url})
    assert result.is_error and "Both need the same version" in text_of(result)
