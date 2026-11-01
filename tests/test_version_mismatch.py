import json

import pytest

from nvda_mcp.bridge_client import SUPPORTED_PROTOCOL_VERSION, BridgeClient, NvdaUnavailableError


def connection_file(tmp_path, protocol, addon_version="9.9.9"):
    path = tmp_path / "connection.json"
    info = {"protocolVersion": protocol, "port": 1, "token": "t", "addonVersion": addon_version}
    path.write_text(json.dumps(info), encoding="utf-8")
    return path


@pytest.mark.anyio
async def test_a_newer_addon_asks_to_update_the_server(tmp_path):
    client = BridgeClient(connection_file(tmp_path, SUPPORTED_PROTOCOL_VERSION + 1))
    with pytest.raises(NvdaUnavailableError) as error:
        await client.call("getStatus")
    assert "add-on (9.9.9)" in str(error.value)
    assert "Update the server" in str(error.value)
    assert "Copy setup command" in str(error.value)


@pytest.mark.anyio
async def test_an_older_addon_asks_to_update_the_addon(tmp_path):
    client = BridgeClient(connection_file(tmp_path, SUPPORTED_PROTOCOL_VERSION - 1, addon_version=None))
    with pytest.raises(NvdaUnavailableError) as error:
        await client.call("getStatus")
    assert "add-on (an older version)" in str(error.value)
    assert "Update the add-on" in str(error.value)
