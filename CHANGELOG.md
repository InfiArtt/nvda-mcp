# Changelog

All notable changes to NVDA MCP are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).
The add-on (`addon/manifest.ini`) and the server (`pyproject.toml`) share one version number;
install them together.

## [0.4.0] - Unreleased

The first release for the NV Access Add-on Store and PyPI.

### Added

- The server is published on PyPI as `nvda-mcp`, so it runs with `uvx nvda-mcp`, `pipx install nvda-mcp`
  or `python -m nvda_mcp`; no copy of the source code is needed.
- NVDA MCP settings: *Set up this MCP client* and **Copy setup command** copy the command (Claude Code, Codex CLI)
  or the JSON settings (Claude Desktop, Cursor and others) that start the server version matching the add-on.
- The add-on has help pages in English and Indonesian, opened from the Add-on Store or the add-ons manager.
- The add-on includes its license (GNU GPL v2), and its manifest links to the source code.
- [docs/using.md](docs/using.md): day-to-day use, updating, and restarting the server after an update.
- [CONTRIBUTING.md](CONTRIBUTING.md): building, testing and releasing.
- Ways to support the project with a donation: a **Donate** button in the NVDA MCP settings, and links on
  GitHub, PyPI and in the README.

### Changed

- The dialog asking to allow key presses names the MCP client asking, as the client calls itself,
  instead of always saying Claude. The action log records the client too.
- When the add-on and the server don't match, the error says which one is older and how to update it.
- The README is written for people installing the add-on, and explains what it is for and who it is for.

### Fixed

- `nvda_press_keys` and `nvda_run_scenario` now press keys as the user would: NVDA runs its command for
  the key first. NVDA+t used to type "t" into the application, and browse mode quick navigation keys
  went to the page. A key with the NVDA key and no command is refused before anything is pressed.
- `nvda_trace_events` reports speech that comes just before or after an event rather than while NVDA handles it,
  such as a browser's live region, as "NVDA said around then", instead of "NVDA said nothing".
- `nvda_preview_speech` with `target: "window"` always includes the focused control, searches the web document
  first, and says in its first line when the search stopped before checking every control.

## [0.3.0] - 2026-11-02

### Added

Tools for developers of NVDA add-ons and accessible applications:

- `nvda_preview_speech` says what NVDA would announce when a control gets focus, without moving focus.
  With `target: "window"` it scans every focusable control in the foreground window and flags unlabeled
  and silent ones; the controls get ids for the other object tools.
- `nvda_trace_events` records the events NVDA handles and what NVDA said while handling each one,
  filtered by event and application. It stops by itself after 10 minutes.
- `nvda_get_log` reads NVDA's log, filtered by level and text. IO entries, which record keys typed,
  are left out unless asked for.
- `nvda_get_output_history` shows beeps, sounds, braille output and speech being cut off.
- `nvda_get_dev_info` shows NVDA's developer info for a control, like NVDA+F1.
- `nvda_list_scripts` lists the NVDA commands available where focus is, with their keys,
  or says which command a key runs.
- `nvda_run_script` runs an NVDA command by name; `nvda_reload_plugins` reloads add-ons and app modules,
  like NVDA+control+F3. Both need key presses to be allowed.
- `nvda_get_settings` reads NVDA's settings as they apply now. Values whose names suggest secrets are hidden.
- `nvda_run_scenario` runs a list of key presses and typing, records what NVDA said and where focus went
  after each step, and saves it as a baseline file or compares it with one.

### Changed

- The bridge protocol is now version 3. Update the add-on and the server together.

### Notes

- Event tracing wraps `eventHandler.executeEvent`, since NVDA has no extension point for events.
  The wrapper does nothing while tracing is off.
- Reloading plugins restarts this add-on too: speech history starts again, and key presses need
  approving again if NVDA asks before the first one.

## [0.2.0] - 2026-11-01

### Added

- Windows: `nvda_list_windows` lists open application windows, optionally including ones on other
  virtual desktops; `nvda_activate_window` brings one to the front by title or handle.
- Keys: `nvda_press_keys` takes `hold`, to keep alt, control, shift or windows down across several keys
  (for example alt held while tab moves through the Alt+Tab switcher).
- Typing: `nvda_type_text` types a line of text in any language, emoji included, without using the clipboard.
- Controls: `nvda_find_objects` finds controls by name and role; `nvda_focus_object` and
  `nvda_activate_object` focus or press them.
- Speech: `nvda_wait_for_speech` waits until NVDA says something, such as a chat reply.
- Expected results: every action tool takes `until_speech`, keeps listening until NVDA says that text,
  and reports whether it was heard, so a client knows whether pressing something had the effect it wanted.
- Web pages and documents:
  - `documentMode` (browse or focus) in `nvda_get_focus` and `nvda_get_status`.
  - `nvda_set_document_mode` switches between browse and focus mode, like NVDA+space.
  - `nvda_find_in_page` moves the browse mode cursor to a match, like NVDA's find command but without
    its dialogs; NVDA+F3 continues the search.
  - `nvda_get_text` takes `contains`, to search a page without moving the cursor.
  - `nvda_list_elements` lists headings, links, landmarks, form fields and more, like the Elements List;
    `nvda_move_to_element` moves to or activates one.
- Long lists: `nvda_get_object_tree` shows at most `max_children` children of each object (25 by default)
  and says how many it left out.
- Safety:
  - A setting to let MCP clients control only some applications.
  - A log of every action clients take (`%APPDATA%\nvda\nvdaMcp\actions.log`), with a setting to turn it off,
    an NVDA command to open it and the `nvda_get_action_log` tool.

### Changed

- The bridge protocol is now version 2. A 0.2.0 server refuses to talk to a 0.1.x add-on, and the
  other way round, with a message saying to update both.
- `nvda_get_focus` reports `documentMode` ("browse" or "focus") instead of `browseMode` (true or false).

## [0.1.1] - 2026-11-01

First release.

### Added

- NVDA add-on with a loopback bridge protected by a per-start token, and an MCP server.
- Tools: `nvda_get_status`, `nvda_get_focus`, `nvda_get_navigator_object`, `nvda_get_object_tree`,
  `nvda_get_text`, `nvda_get_speech_history`, `nvda_speak`, `nvda_press_keys`, `nvda_audit_focus_order`.
- Settings for connecting, pressing keys (off by default), asking before the first key press and speech history size.
- Indonesian translation.

[0.4.0]: https://github.com/InfiArtt/nvda-mcp/releases/tag/v0.4.0
[0.3.0]: #030---2026-11-02
[0.2.0]: #020---2026-11-01
[0.1.1]: #011---2026-11-01
