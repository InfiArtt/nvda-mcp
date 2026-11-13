import json
import subprocess

import pytest
from setupCommands import (
    CLIENTS,
    SetupError,
    addServerToSettings,
    configFilePath,
    installInFile,
    runSetupCommand,
    setupText,
)


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


def test_file_clients_get_the_same_json_settings():
    for client in ("claudeDesktop", "antigravity", "cursor"):
        assert json.loads(setupText(client, "1.3.0")) == json.loads(setupText("json", "1.3.0"))


def test_claude_desktop_settings_follow_its_install(tmp_path):
    env = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    assert configFilePath("claudeDesktop", env) == str(
        tmp_path / "Roaming" / "Claude" / "claude_desktop_config.json"
    )
    (tmp_path / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc").mkdir(parents=True)
    assert configFilePath("claudeDesktop", env) == str(
        tmp_path / "Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/claude_desktop_config.json"
    )


def test_antigravity_settings_prefer_the_file_it_uses(tmp_path):
    env = {"USERPROFILE": str(tmp_path)}
    gemini = tmp_path / ".gemini"
    assert configFilePath("antigravity", env) == str(gemini / "antigravity" / "mcp_config.json")
    (gemini / "config").mkdir(parents=True)
    assert configFilePath("antigravity", env) == str(gemini / "config" / "mcp_config.json")
    (gemini / "antigravity").mkdir()
    (gemini / "antigravity" / "mcp_config.json").write_text("{}")
    assert configFilePath("antigravity", env) == str(gemini / "antigravity" / "mcp_config.json")
    assert configFilePath("cursor", env) == str(tmp_path / ".cursor" / "mcp.json")


def test_adding_the_server_keeps_other_settings_and_replaces_an_old_entry():
    old = {
        "theme": "dark",
        "mcpServers": {"other": {"command": "x"}, "nvda": {"command": "uvx", "args": ["nvda-mcp>=1.1.0"]}},
    }
    text, previous = addServerToSettings(json.dumps(old), "1.3.0")
    settings = json.loads(text)
    assert previous == {"command": "uvx", "args": ["nvda-mcp>=1.1.0"]}
    assert settings["theme"] == "dark" and settings["mcpServers"]["other"] == {"command": "x"}
    assert settings["mcpServers"]["nvda"] == {"command": "uvx", "args": ["nvda-mcp==1.3.0"]}
    assert addServerToSettings("", "1.3.0")[1] is None


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"mcpServers": []}'])
def test_settings_that_cannot_be_changed_safely_are_left_alone(text):
    with pytest.raises(SetupError, match="Nothing was changed"):
        addServerToSettings(text, "1.3.0")


def test_installing_in_a_file_keeps_a_copy_of_the_old_one(tmp_path):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    assert installInFile(str(path), "1.3.0") is None
    assert json.loads(path.read_text())["mcpServers"]["nvda"]["args"] == ["nvda-mcp==1.3.0"]
    path.write_text('\ufeff{"mcpServers": {}, "keep": 1}', encoding="utf-8")
    installInFile(str(path), "1.3.0")
    assert json.loads(path.read_text())["keep"] == 1
    assert '"keep": 1' in (tmp_path / "Claude" / "claude_desktop_config.json.bak").read_text(
        encoding="utf-8-sig"
    )
    path.write_text("{broken")
    with pytest.raises(SetupError):
        installInFile(str(path), "1.3.0")
    assert path.read_text() == "{broken"


class FakeRun:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, arguments):
        self.calls.append(arguments)
        returncode, output = self.results.pop(0)
        return subprocess.CompletedProcess(arguments, returncode, stdout="", stderr=output)


def test_command_clients_run_their_own_setup_command():
    run = FakeRun((0, ""))
    assert runSetupCommand("claudeCode", "1.3.0", which=lambda name: f"C:/bin/{name}.exe", run=run) is False
    assert run.calls == [
        ["C:/bin/claude.exe", "mcp", "add", "--scope", "user", "nvda", "--", "uvx", "nvda-mcp==1.3.0"]
    ]


def test_an_existing_entry_is_replaced():
    run = FakeRun((1, "MCP server nvda already exists in user config"), (0, ""), (0, ""))
    assert runSetupCommand("claudeCode", "1.3.0", which=lambda name: name, run=run) is True
    assert run.calls[1] == ["claude", "mcp", "remove", "--scope", "user", "nvda"]
    assert run.calls[2] == run.calls[0]


def test_setup_command_failures_say_what_to_do():
    with pytest.raises(SetupError, match="codex command was not found"):
        runSetupCommand("codex", "1.3.0", which=lambda name: None, run=FakeRun())
    with pytest.raises(SetupError, match="reported an error: login required"):
        runSetupCommand(
            "codex", "1.3.0", which=lambda name: name, run=FakeRun((2, "warning\nlogin required"))
        )
