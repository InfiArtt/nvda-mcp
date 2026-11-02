import json

import pytest
from setupCommands import CLIENTS, setupText


def test_commands_pin_the_server_to_the_addon_version():
    assert setupText("claudeCode", "1.0.0") == "claude mcp add --scope user nvda -- uvx nvda-mcp==1.0.0"
    assert setupText("codex", "1.0.0") == "codex mcp add nvda -- uvx nvda-mcp==1.0.0"


def test_json_settings_run_the_same_server():
    settings = json.loads(setupText("json", "1.0.0"))
    assert settings == {"mcpServers": {"nvda": {"command": "uvx", "args": ["nvda-mcp==1.0.0"]}}}


def test_every_client_has_setup_text_and_unknown_ones_fail():
    assert all(setupText(client, "1.0.0") for client in CLIENTS)
    with pytest.raises(ValueError):
        setupText("notepad", "1.0.0")
