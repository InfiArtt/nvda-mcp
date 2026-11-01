import json
import os

import httpx
import pytest
from bridge import PROTOCOL_VERSION, Bridge, BridgeError


@pytest.fixture
def running_bridge(tmp_path):
    errors: list[str] = []

    def fail(params):
        raise ValueError("boom")

    def refuse(params):
        raise BridgeError("controlDenied", "No.")

    handlers = {"echo": lambda params: params, "fail": fail, "refuse": refuse}
    bridge = Bridge(
        handlers, str(tmp_path / "nvdaMcp" / "connection.json"), onError=errors.append, addonVersion="1.2.3"
    )
    bridge.start()
    yield bridge, errors
    bridge.stop()


def post(bridge, body, **headers):
    headers.setdefault("Authorization", f"Bearer {bridge.token}")
    return httpx.post(f"http://127.0.0.1:{bridge.port}/rpc", json=body, headers=headers, timeout=5)


def test_connection_file_is_published_and_removed(running_bridge, tmp_path):
    bridge, _ = running_bridge
    path = tmp_path / "nvdaMcp" / "connection.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    assert info == {
        "protocolVersion": PROTOCOL_VERSION,
        "port": bridge.port,
        "token": bridge.token,
        "pid": os.getpid(),
        "addonVersion": "1.2.3",
    }
    assert [p.name for p in path.parent.iterdir()] == ["connection.json"]
    bridge.stop()
    assert not path.exists()


def test_dispatches_to_handler(running_bridge):
    bridge, _ = running_bridge
    response = post(bridge, {"method": "echo", "params": {"text": "héllo"}})
    assert response.json() == {"ok": True, "result": {"text": "héllo"}}


def test_bridge_errors_keep_their_code(running_bridge):
    bridge, errors = running_bridge
    assert post(bridge, {"method": "refuse"}).json()["error"]["code"] == "controlDenied"
    assert errors == []


def test_unexpected_exceptions_are_reported_and_logged(running_bridge):
    bridge, errors = running_bridge
    body = post(bridge, {"method": "fail"}).json()
    assert body["error"]["code"] == "internalError"
    assert "boom" in errors[0]


def test_unknown_method_lists_known_ones(running_bridge):
    bridge, _ = running_bridge
    assert "echo" in post(bridge, {"method": "nope"}).json()["error"]["message"]


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Authorization": ""}, 401),
        ({"Origin": "https://example.com"}, 403),
        ({"Host": "evil.example:80"}, 403),
    ],
)
def test_rejects_untrusted_requests(running_bridge, headers, status):
    bridge, _ = running_bridge
    assert post(bridge, {"method": "echo"}, **headers).status_code == status


def test_rejects_malformed_bodies(running_bridge):
    bridge, _ = running_bridge
    response = httpx.post(
        f"http://127.0.0.1:{bridge.port}/rpc",
        content=b"[1, 2]",
        headers={"Authorization": f"Bearer {bridge.token}"},
        timeout=5,
    )
    assert response.status_code == 400


def test_rejects_get(running_bridge):
    bridge, _ = running_bridge
    assert httpx.get(f"http://127.0.0.1:{bridge.port}/rpc", timeout=5).status_code == 405
