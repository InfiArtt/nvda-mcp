# Changelog

All notable changes to NVDA MCP are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).
The add-on (`addon/manifest.ini`) and the server (`pyproject.toml`) share one version number;
install them together.

## [Unreleased]

### Fixed

- `nvda_activate_window` now brings NVDA along when Windows switches virtual desktops to reach the window.
  Windows sends no event then, so NVDA kept reading the old window and the result showed the old focus.

## [1.0.0] - 2026-11-02

First release, on the NV Access Add-on Store and PyPI.

### Added

- An NVDA add-on with a loopback bridge protected by a per-start token, and an MCP server published on PyPI
  as `nvda-mcp`. It runs with `uvx nvda-mcp`, `pipx install nvda-mcp` or `python -m nvda_mcp`.
- NVDA MCP settings: *Set up this MCP client* and **Copy setup command** copy the command (Claude Code, Codex CLI)
  or the JSON settings (Claude Desktop, Cursor and others) that start the server version matching the add-on.
- Reading: `nvda_get_status`, `nvda_get_focus` (with `documentMode`, browse or focus), `nvda_get_navigator_object`,
  `nvda_get_object_tree` (at most `max_children` children of each object), `nvda_get_text` (with `contains`
  to search without moving the cursor) and `nvda_get_speech_history`.
- Speech: `nvda_speak`, and `nvda_wait_for_speech` to wait until NVDA says something, such as a chat reply.
- Keys and typing: `nvda_press_keys` presses keys as the user would, so NVDA runs its command for a key first,
  and takes `hold` to keep alt, control, shift or windows down across several keys. `nvda_type_text` types
  a line of text in any language, emoji included, without using the clipboard.
- Windows: `nvda_list_windows`, optionally including other virtual desktops, and `nvda_activate_window`.
- Controls: `nvda_find_objects`, `nvda_focus_object` and `nvda_activate_object`; `nvda_audit_focus_order`.
- Web pages and documents: `nvda_set_document_mode`, `nvda_find_in_page`, and `nvda_list_elements` and
  `nvda_move_to_element`, like the Elements List.
- Expected results: every action tool takes `until_speech`, keeps listening until NVDA says that text,
  and reports whether it was heard.
- Tools for developers of NVDA add-ons and accessible applications:
  - `nvda_preview_speech` says what NVDA would announce when a control gets focus, without moving focus.
    With `target: "window"` it checks the focused control and the controls of the foreground window,
    and flags unlabeled and silent ones.
  - `nvda_trace_events` records the events NVDA handles and what NVDA said for each, including speech that comes
    just before or after an event, such as a browser's live region. It stops by itself after 10 minutes.
  - `nvda_get_log` reads NVDA's log; IO entries, which record keys typed, are left out unless asked for.
  - `nvda_get_output_history` shows beeps, sounds, braille output and speech being cut off.
  - `nvda_get_dev_info` shows NVDA's developer info for a control, like NVDA+F1.
  - `nvda_list_scripts` lists the NVDA commands available where focus is, or says which command a key runs.
  - `nvda_run_script` runs an NVDA command by name; `nvda_reload_plugins` reloads add-ons and app modules.
  - `nvda_get_settings` reads NVDA's settings as they apply now. Values whose names suggest secrets are hidden.
  - `nvda_run_scenario` runs key presses and typing, records what NVDA said after each step, and saves it
    as a baseline file or compares it with one.
- Safety:
  - Pressing keys is off by default. NVDA asks before the first key press after it starts, in a dialog whose
    title names the MCP client asking.
  - A setting to let MCP clients control only some applications.
  - A log of every action clients take (`%APPDATA%\nvda\nvdaMcp\actions.log`), with a setting to turn it off,
    an NVDA command to open it and the `nvda_get_action_log` tool.
  - When the add-on and the server don't match, the error says which one is older and how to update it.
- A **Donate** button in the NVDA MCP settings, and donation links on GitHub, PyPI and in the README.
- Help pages and translation in English and Indonesian.
- [docs/using.md](docs/using.md), [CONTRIBUTING.md](CONTRIBUTING.md) and
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

[1.0.0]: https://github.com/InfiArtt/nvda-mcp/releases/tag/v1.0.0
