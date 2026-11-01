# NVDA MCP

Lets AI assistants such as Claude work with the [NVDA](https://www.nvaccess.org) screen reader
through the [Model Context Protocol](https://modelcontextprotocol.io):
read what NVDA reads, hear what it speaks, and, if you allow it, press keys.

It has two parts:

```
Claude Code ⇄ (stdio) nvda-mcp server ⇄ (HTTP on 127.0.0.1, token) NVDA add-on ⇄ NVDA
```

- **`addon/`**: the NVDA add-on (NVDA 2026.3 or later). It records everything NVDA speaks
  and runs a small bridge that only accepts local, authenticated requests.
- **`src/nvda_mcp/`**: the MCP server, built on the official MCP Python SDK.

## Tools

| Tool | What it does |
|---|---|
| `nvda_get_status` | NVDA version, synthesizer, speech mode, foreground app, permissions |
| `nvda_get_focus` | The focused control: name, role, states, value, position, containers |
| `nvda_get_navigator_object` | The same, for NVDA's navigator object |
| `nvda_get_object_tree` | The accessibility tree of the foreground window, focus or navigator; long lists are shortened |
| `nvda_find_objects` | Find controls in the foreground window by name and/or role |
| `nvda_get_text` | Full text of a document, web page or edit field, plus the caret line; or only the lines containing some text |
| `nvda_get_speech_history` | What NVDA said, with ids for polling and a text filter |
| `nvda_wait_for_speech` | Wait until NVDA says something, such as a chat reply |
| `nvda_list_windows` | Open application windows, including ones on other virtual desktops if asked |
| `nvda_speak` | Say something through NVDA's speech and braille |
| `nvda_press_keys` | Press keys, optionally holding modifiers (alt held while tab cycles Alt+Tab), then report what NVDA said and where focus went |
| `nvda_type_text` | Type a line of text in any language, emoji included, without using the clipboard |
| `nvda_activate_window` | Bring a window to the front by title or handle |
| `nvda_focus_object` | Move focus to a control found with `nvda_find_objects` |
| `nvda_activate_object` | Press, follow or toggle a control found with `nvda_find_objects` |
| `nvda_set_document_mode` | Switch between browse mode and focus mode in a web page, like NVDA+space |
| `nvda_find_in_page` | Move the browse mode cursor to a match on the page, like NVDA's find command |
| `nvda_list_elements` | Headings, links, landmarks, form fields and more, like the Elements List |
| `nvda_move_to_element` | Move to, or activate, an element from `nvda_list_elements` |
| `nvda_get_action_log` | The newest entries of the log of actions clients took |
| `nvda_audit_focus_order` | Tab through a window and report unlabeled controls, silent controls, duplicate names, keyboard traps |

For developers of add-ons and accessible applications:

| Tool | What it does |
|---|---|
| `nvda_preview_speech` | What NVDA would announce when a control gets focus, without moving focus; scan a whole window and flag unlabeled or silent controls |
| `nvda_trace_events` | Record the events NVDA handles (focus, name and value changes, live regions, UIA notifications) and what it said for each one |
| `nvda_get_log` | NVDA's log, filtered by level and text; IO entries (keys typed) only when asked |
| `nvda_get_output_history` | Beeps, sounds, braille output and speech being cut off, optionally merged with speech |
| `nvda_get_dev_info` | Developer info for a control, like NVDA+F1 |
| `nvda_list_scripts` | NVDA commands available where focus is, with their keys; or which command a key runs |
| `nvda_run_script` | Run an NVDA command by name, whatever key it is assigned to |
| `nvda_reload_plugins` | Reload add-ons and app modules from disk, like NVDA+control+F3 |
| `nvda_get_settings` | Read NVDA's settings as they apply now; values that look like secrets are hidden |
| `nvda_run_scenario` | Run keys and typing, record what NVDA said after each step, and compare with a baseline file |

`nvda_press_keys`, `nvda_type_text`, `nvda_activate_window`, `nvda_focus_object`, `nvda_activate_object`,
`nvda_set_document_mode`, `nvda_find_in_page`, `nvda_move_to_element`, `nvda_audit_focus_order`,
`nvda_run_script`, `nvda_reload_plugins` and `nvda_run_scenario` act on your computer. They are off by default.

Every action tool reports what NVDA said afterwards and where focus went. Pass `until_speech` to keep
listening until NVDA says something you expect, such as "sent" or a dialog's title; the result says
whether it was heard. In web pages, `nvda_get_focus` reports `documentMode` (browse or focus).

See [docs/using.md](docs/using.md) for using it day to day: allowing key presses, updating,
restarting the server after an update, and what to do when something does not work.
See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## Install

1. **Build and install the add-on**

   ```
   python build_addon.py
   ```

   Open `dist/nvdaMcp-0.3.0.nvda-addon`, accept the installation, and restart NVDA.

2. **Install the server** (Python 3.11 or later)

   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -e .
   ```

3. **Add it to Claude Code**

   ```
   claude mcp add --scope user nvda -- F:\amusements\nvda-mcp\.venv\Scripts\nvda-mcp.exe
   ```

   For a portable copy of NVDA, also pass
   `--env NVDA_MCP_CONNECTION_FILE=<portable folder>\userConfig\nvdaMcp\connection.json`.

## Settings and safety

NVDA menu → Preferences → Settings → **NVDA MCP**:

- **Let MCP clients such as Claude connect to NVDA** (on by default).
- **Allow MCP clients to press keys** (off by default).
- **Ask before the first key press after NVDA starts** (on by default).
  NVDA shows a Yes/No dialog, with No focused, the first time a client tries to press keys.
- **Only let MCP clients control these applications** (empty by default, meaning all).
  Application names as NVDA reports them, separated by commas, for example `mwmod, notepad`.
  Key presses, typing and activating controls are refused in any other application;
  switching windows is allowed only to these applications.
- **Keep a log of every action MCP clients take** (on by default).
  Each key press, typed text, window switch and activated control is written to
  `%APPDATA%\nvda\nvdaMcp\actions.log` with the time and window. At 1 MB it moves to `actions.log.1`.
- **Number of spoken messages to remember** (500 by default).

Commands in Input Gestures → NVDA MCP (no keys assigned by default):

- *Report whether NVDA MCP is running and whether it may press keys.*
- *Stop MCP clients from pressing keys until you approve again.* Works even when confirmation is turned off.
- *Open the log of actions MCP clients have taken.*

How the bridge is protected:

- It listens on 127.0.0.1 only, on a random port.
- Every request needs a random token, made fresh each time NVDA starts.
  The port and token are in `%APPDATA%\nvda\nvdaMcp\connection.json`, which only your Windows account can read.
- Requests from web pages (with an `Origin` header) or with a non-loopback `Host` are refused.
- Nothing runs on secure screens (sign-in, UAC), and requests are refused while Windows is locked.
- Settings are stored in NVDA's base configuration, so profiles cannot turn key presses on.

## Development

```
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
```

The tests run the real bridge and the real MCP server against a scripted window, so they need no NVDA.
The add-on code follows NVDA's coding standards (tabs, camelCase, translatable strings with translator comments);
the server follows PEP 8.

This project follows these NVDA documents:
the [NVDA Developer Guide](https://www.nvaccess.org/files/nvda/documentation/developerGuide.html),
[What's New](https://www.nvaccess.org/files/nvda/documentation/changes.html),
the community [Add-on Development Guide](https://github.com/nvdaaddons/DevGuide/wiki/NVDA-Add-on-Development-Guide)
and NVDA's [coding standards](https://github.com/nvaccess/nvda/blob/master/projectDocs/dev/codingStandards.md).
Keep local copies in `docs/reference/` if you like; git ignores that folder.

### Translations

User-facing strings are in English and wrapped in `_()`. The Indonesian translation is
`addon/locale/id/LC_MESSAGES/nvda.po`; `build_addon.py` compiles it.
A test fails if a translatable string has no translation.
