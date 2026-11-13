# Changelog

All notable changes to NVDA MCP are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).
The add-on (`addon/manifest.ini`) and the server (`pyproject.toml`) share one version number;
install them together.

## [Unreleased]

### Added

- MCP Access works both ways. The person being helped has one window, opened with a new NVDA command, with
  the session's status, their conversation, a field to answer (Enter sends) and a button to stop sharing.
  Messages from the helper play a sound and are spoken as messages from them, so they are never taken for
  NVDA's own. The helper's assistant sends messages with `nvda_access_send_message` and reads answers with
  `nvda_access_messages`, which can wait for one; a message that arrives meanwhile comes with the result of
  its next tool, so it is not missed.
  Messages are end-to-end encrypted like the rest of the session, at most 2000 characters, and a helper may
  send at most 20 a minute.

### Fixed

- `nvda_list_windows` also lists windows that belong to another window, such as REAPER's FX windows, with the
  handle of the window they belong to. Like Alt+Tab, it used to leave them out.

## [1.3.0] - 2026-11-13

### Added

- **MCP Access**: someone you trust helps you from their own computer, with their AI assistant working through
  your NVDA. A command in Input Gestures shares this computer and copies a one-time code that works for
  10 minutes; the helper's assistant connects with `nvda_access_connect`, and every NVDA tool then works on
  your computer until `nvda_access_disconnect`. The person being helped needs no AI assistant.
  - End-to-end encrypted (X25519 and AES-256-GCM, keys made from the code and fresh random keys); the relay,
    run by InfiArtt at `wss://infiartt.com/mcp-access/v1`, only forwards data it cannot read.
    Strict TLS 1.3 to the relay.
  - NVDA asks before a helper connects, and again before their first key press and their first picture of the
    screen in each session, even if those are off in the settings. *Never let MCP Access helpers press keys* and
    *Never let MCP Access helpers take pictures of the screen* refuse them altogether.
  - Reloading add-ons, running NVDA commands, NVDA's log and settings, and web pages' HTML are never available
    through MCP Access. Connections and actions are written to the action log.
  - The ready-made prompt `help_someone` connects with the code the person sent and helps them safely.
  - NVDA says when a helper connects and why sharing ended, in your language.

- **Set up now**, in NVDA's Settings, NVDA MCP category: sets up the chosen assistant without editing files
  by hand. For Claude Desktop, Antigravity and Cursor it adds NVDA MCP to the assistant's settings file,
  keeping the rest of the file and a copy of the old one (`.bak`); for Claude Code and Codex CLI it runs their
  own setup command. NVDA asks before changing anything. Antigravity and Cursor are new in the list of clients.
- `nvda_recognize_text`: reads the text on the screen in a window or control with Windows' text recognition,
  as NVDA+R does, line by line with where each line is. For applications NVDA can read nothing in.
  Every use is written to the action log.
- `nvda_get_addon_paths`, for add-on developers: where NVDA's developer scratchpad is, whether NVDA loads code
  from it, and the add-ons running.
- Ready-made prompts for everyone: `make_accessible` finds what stops NVDA in an application, writes a small
  add-on that fixes it, tests it in the running NVDA and packages it; `explain_screen` says where you are and
  what you can do there; `report_problem` writes a bug report for the application's developer, for you to send.
- A command, in Input Gestures, NVDA MCP category, that copies what NVDA sees where you are, to paste into a
  chat with any AI assistant, even one without MCP: the application, the focused control, the controls in the
  window and what NVDA said last.

### Changed

- When `nvda_get_object_tree` cuts a long list with `max_children`, it shows the items around the focus
  if the focus is in the list, and otherwise the last items of lists and tables, such as the newest messages
  of a chat, instead of always the first ones. It says how many items it left out before and after them.
- The bridge protocol version is now 8. Update the add-on and the server together.

## [1.2.0] - 2026-11-13

### Changed

- The add-on now works with NVDA 2025.1 and later, not only 2026.3 and later.
  On NVDA before 2026.3, which cannot register an add-on's settings at installation,
  the add-on adds its settings when NVDA starts, and its settings can be saved in a configuration profile.

## [1.1.0] - 2026-11-05

### Added

- `nvda_find_objects` takes `within`, an id from the previous search, to search only inside that control.
  On large web pages such as WhatsApp Web, a search of the whole window can stop after 3 seconds
  before it reaches the part that matters.
- `nvda_inspect_object`, for add-on developers: a control's IAccessible2 attributes (HTML tag, id, class,
  ARIA role, where its name comes from) or UIA properties, the containers above it, its first children,
  and for tables and lists how many rows exist now compared with how many the application reports.
  It ranks the conditions an add-on could match the control on, from most to least stable, warns about class
  names that look generated by a build tool, and gives example `chooseNVDAObjectOverlayClasses` code.
- `nvda_find_objects` and `nvda_get_object_tree` take `window`, a handle from `nvda_list_windows`,
  to read a window in the background or on another virtual desktop without bringing it to the front.
  Chromium browsers and Electron apps stop exposing their page some time after their window is hidden;
  the result then says so, and that the window needs to come to the front first.
- `nvda_get_object_tree` takes `id` to start from a control found with `nvda_find_objects`.
- `nvda_trace_events` takes `background_window` to ask NVDA for events from a window in the background,
  as an add-on can with `eventHandler.requestEvents`. They are recorded with the control's value and
  the text of live regions and alerts, but NVDA does not act on them.
- `nvda_set_value` (experimental) gives an edit field new text through UI Automation or IAccessible,
  without the keyboard or focus, and reports whether the field took it.
- Recording what an action changed, for add-on developers. Action tools such as `nvda_press_keys`,
  `nvda_activate_object` and `nvda_set_value` take `record` (or `record_within`, an id): the result then also
  says how the accessibility tree around the action changed (controls added, removed, renamed or moved,
  values and states, lists that scrolled) and which events NVDA handled. `nvda_trace_events` takes `tree`
  (or `tree_within`) to do the same for something the user does, from start to stop. The comparison never
  reports a control as removed when it was simply not read, and reads the part around the focus first.
- `nvda_inspect_html` and `nvda_find_html`, for developers of add-ons for web apps: the HTML element behind a
  control in Chrome, Brave or Edge, read through the browser's remote debugging, with the data attributes,
  HTML, styles and event listeners that NVDA cannot see. The control is matched with its element exactly,
  through the DOM node id Chromium gives it. Off until you check the new setting
  **Let MCP clients read the HTML of web pages through the browser's remote debugging**; NVDA says when
  it connects, and the browser asks before every new connection. Only the page you work with is read:
  no scripts are run and your other tabs are never listed.

- `nvda_lookup_api`, for add-on developers: checks a name in the Python code of the NVDA that is running,
  before it goes into an add-on. It says whether the name exists, what it is, its signature, docstring and
  members, where it is defined with a link to NVDA's source for that release, and whether it looks deprecated,
  and suggests close names when it does not exist. With `search` it finds names in NVDA's and add-ons' modules.
  It only reads, and does not run the code it looks at.
- `nvda_capture_control`, for developers: a picture of a control on the screen next to what NVDA says for it,
  to find icons and visible text the accessible name leaves out. Off until you check the new setting
  **Let MCP clients take pictures of controls on the screen**. It captures the way NVDA's own text recognition
  does, so it works with Screen Curtain on, and every picture is written to the action log.
- Ready-made MCP prompts for common developer tasks: `audit_accessibility`, `build_addon`, `why_silent` and
  `check_labels`. Clients that support prompts offer them as commands.

### Changed

- Ids from `nvda_find_objects` stay valid through later searches, until the control disappears,
  so a container's id still works after searching inside it.
- When `nvda_find_objects` searches several parts of a window, such as a web page and then the browser
  around it, they share one 3-second time limit instead of 3 seconds each.
- `nvda_trace_events` no longer records which character a typed-character event carried, so passwords stay
  out of traces (NVDA only says "star" for them). What NVDA speaks as you type in other fields is still recorded.
- The bridge protocol version is now 7. Update the add-on and the server together.

### Fixed

- Your answer to "allow ... to press keys?" now lasts until NVDA restarts, as the question says,
  instead of being forgotten when plugins are reloaded.
- An unanswered "allow ... to press keys?" question closes by itself, with an announcement, before the
  MCP client stops waiting. Before, answering Yes much later still ran the old action, and every other
  action waited behind the open question. An action that cannot start in time fails with `controlBusy`.
- Escape answers No in that question; before, it did nothing.
- Using the id of a web page's control that has disappeared now fails with `staleObject`. Before, NVDA still
  answered for it as an unknown object, so the action failed later with a less helpful error.
- `nvda_get_object_tree` no longer drops a control and everything in it when it is the last one shown
  and its own children were cut short; on WhatsApp Web most of the page went missing this way.
- `nvda_activate_window` now brings NVDA along when Windows switches virtual desktops to reach the window.
  Windows sends no event then, so NVDA kept reading the old window and the result showed the old focus.
  NVDA then says the window title once, as after Alt+Tab; at first it said it twice in browsers.
- `nvda_activate_window` says the window title once when the page in a Chromium browser or Electron app
  is in focus mode, as in WhatsApp Web. These applications send no focus event for their window, so NVDA said
  the title on entering the window and again on switching to focus mode, even on the same virtual desktop.
  The add-on now tells NVDA about the window as soon as it comes to the front. Pages in browse mode
  and other applications are left to NVDA, which says the title once there.

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

[1.2.0]: https://github.com/InfiArtt/nvda-mcp/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/InfiArtt/nvda-mcp/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/InfiArtt/nvda-mcp/releases/tag/v1.0.0
