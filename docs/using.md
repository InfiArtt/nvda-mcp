# Using NVDA MCP

A guide for people who use NVDA MCP with an AI assistant, and for the assistant itself.
[README.md](../README.md) covers installing it and lists every tool.

## What the assistant can do

NVDA MCP lets the assistant read what NVDA reads and hear what NVDA says.
If you allow it, it can also press keys and type.

Things to ask for, and the tools the assistant uses:

| You ask | Tools |
|---|---|
| "Where am I?" "What is on screen?" | `nvda_get_focus`, `nvda_get_object_tree`, `nvda_get_text` |
| "What did NVDA just say?" | `nvda_get_speech_history` |
| "Tell me when the reply arrives" | `nvda_wait_for_speech` |
| "Switch to Notepad" | `nvda_list_windows`, `nvda_activate_window` |
| "Press the Send button" | `nvda_find_objects`, `nvda_activate_object` |
| "Go to the comments heading on this page" | `nvda_list_elements`, `nvda_move_to_element`, `nvda_find_in_page` |
| "Type this for me" | `nvda_type_text` |
| "Is this dialog accessible?" | `nvda_audit_focus_order`, `nvda_preview_speech` |
| "Why does NVDA say nothing here?" | `nvda_trace_events`, `nvda_get_dev_info`, `nvda_get_log` |
| "How can my add-on recognize this button?" | `nvda_inspect_object` |
| "What does the chat window say?" (while you work elsewhere) | `nvda_list_windows`, `nvda_find_objects` with a window |
| "Did my add-on change break anything?" | `nvda_reload_plugins`, `nvda_run_scenario` |

## Allowing key presses

Reading is always allowed. Pressing keys, typing, switching windows and activating controls are off by default.
Turn them on in NVDA menu → Preferences → Settings → **NVDA MCP**.

- The first time the assistant presses a key after NVDA starts, NVDA asks you, with **No** focused.
  Answer **Yes** to allow it until NVDA restarts. Reloading plugins (NVDA+Ctrl+F3 or `nvda_reload_plugins`)
  keeps your answer.
- If you answer No or press Escape, the assistant gets `controlDenied` and must not try again unless you ask.
  NVDA asks again the next time it tries.
- If you don't answer within about a minute and a half, NVDA closes the question, says so, and presses nothing.
  The assistant gets `approvalTimedOut`; it can ask again when you are ready.
- Every action is written to `%APPDATA%\nvda\nvdaMcp\actions.log`. Ask "what did you do?",
  and the assistant reads it with `nvda_get_action_log`.

## Updating

The server and the add-on share one version number. **Update both.**
When they don't match, every tool fails with a message saying which one is older and how to update it.

1. **The add-on**: NVDA tells you when an update is ready. Or open Tools, Add-on Store, *Updatable add-ons*.
   Install it and restart NVDA.
2. **The server**: in NVDA's Settings, **NVDA MCP** category, press **Copy setup command** again and run what it
   copies, or paste the settings again. The command names the server version that matches the new add-on.
   - Claude Code may say the `nvda` server already exists. Remove it first with `claude mcp remove nvda --scope user`.
   - If you installed the server with pipx, run `pipx upgrade nvda-mcp`; with pip, `pip install -U nvda-mcp`.
3. **Restart the server** in your assistant (see the next section).
4. Check it worked: ask for NVDA's status. `addonVersion` should be the new version.

## Restarting the server

The assistant starts the server when a session or chat starts and keeps it running until it ends,
so a running server keeps the version it started with. Starting a new session always gets the new one.

**In Claude Code** you can keep the session: stop the server process, and the next NVDA tool call
starts a new one.

```
taskkill /IM nvda-mcp.exe /T /F
```

This stops the server of every open session; each starts again on its next NVDA tool call.
You can also ask the assistant to run it. If the new version adds or removes tools and the assistant does not
see them, start a new session.

In the Claude desktop app, closing a session with Ctrl+W does not stop its server; archiving it (Ctrl+Alt+A) does.
Each open session has its own server.

**In Claude Desktop**, quit it from the system tray and start it again.

## When something does not work

| Symptom | What to do |
|---|---|
| "NVDA is not reachable" | Check NVDA is running and the add-on is enabled. Right after a reload, wait a second and try again. |
| "… do not match" | Update the one it names, as above. |
| "uvx is not recognized" | Install uv (see the README), then open a new command prompt or restart your assistant. |
| `controlDisabled` | Allow key presses in NVDA's NVDA MCP settings. |
| `controlDenied` | You answered No, or the question closed without an answer. Ask the assistant to try again and answer Yes. |
| `appNotAllowed` | Add the application to "Only let MCP clients control these applications", or empty that setting. |
| A tool behaves like an old version | The server was not restarted; see above. |
| You use a portable copy of NVDA | Give the server `NVDA_MCP_CONNECTION_FILE=<portable folder>\userConfig\nvdaMcp\connection.json` as an environment variable, for example with `--env` in `claude mcp add`. |

## For the assistant

The server's instructions and each tool's description say how to use the tools.
In addition:

- The user is likely blind or low vision and hears everything NVDA says.
  Say what you are about to press before pressing it.
- Prefer reading tools. `nvda_preview_speech` shows what NVDA would say without moving focus.
- Never retry after `controlDenied`.
- After an update, check `addonVersion` in `nvda_get_status` before trusting new behaviour.
- Developers changing NVDA MCP itself: see [CONTRIBUTING.md](../CONTRIBUTING.md).
