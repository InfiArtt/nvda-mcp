# Using NVDA MCP

A guide for people who use NVDA MCP with an AI assistant such as Claude, and for the assistant itself.
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
| "Did my add-on change break anything?" | `nvda_reload_plugins`, `nvda_run_scenario` |

## Allowing key presses

Reading is always allowed. Pressing keys, typing, switching windows and activating controls are off by default.
Turn them on in NVDA menu → Preferences → Settings → **NVDA MCP**.

- The first time the assistant presses a key after NVDA starts, NVDA asks you, with **No** focused.
  Answer **Yes** to allow it until NVDA restarts.
- `nvda_reload_plugins` restarts the add-on, so NVDA asks again after it.
- If you answer No, the assistant gets `controlDenied` and must not try again unless you ask.
  NVDA asks again the next time it tries.
- Every action is written to `%APPDATA%\nvda\nvdaMcp\actions.log`. Ask "what did you do?",
  and the assistant reads it with `nvda_get_action_log`.

## Updating

The server and the add-on share one version number. **Always update both.**
The server checks the add-on's bridge protocol version and refuses to work with a different one,
and a new tool usually needs new add-on code too.

1. Get the new version of this folder.
2. Update the server. It is installed in editable mode, so this is only needed when dependencies change,
   but it does no harm:

   ```
   .venv\Scripts\python -m pip install -e .
   ```

3. Build the add-on and open it:

   ```
   python build_addon.py
   ```

   Open `dist\nvdaMcp-<version>.nvda-addon`, accept the update and restart NVDA.
4. Restart the server in your assistant (see the next section).
5. Check it worked: ask for `nvda_get_status`. `addonVersion` should be the new version.

If the server and add-on do not match, every tool fails with a message saying
"Update the add-on and the server together."

## Restarting the server after an update

The assistant starts the server when a session starts and keeps it running until the session ends,
so the server keeps running the code it started with.

**In Claude Code (desktop app or terminal)** you do not need a new session.
Stop the server process; the next NVDA tool call starts a new one with the new code:

```
taskkill /IM nvda-mcp.exe /T /F
```

This stops the server of every open Claude session; each one starts again on its next NVDA tool call.
You can also ask the assistant to run it.

If the new version adds or removes tools and the assistant does not see them, start a new session.

Closing a session with Ctrl+W does not stop its server; archiving it (Ctrl+Alt+A) does.
Each open session has its own server, so archive old test sessions to avoid several servers running.

## Developing the add-on

To try changed add-on code without reinstalling it:

1. Copy the changed files from `addon\globalPlugins\nvdaMcp\` to
   `%APPDATA%\nvda\addons\nvdaMcp\globalPlugins\nvdaMcp\`.
2. Press NVDA+Ctrl+F3, or ask the assistant to call `nvda_reload_plugins`.

If you changed the bridge protocol version, restart the server too.

## When something does not work

| Symptom | What to do |
|---|---|
| "NVDA is not reachable" | Check NVDA is running and the add-on is enabled. Right after a reload, wait a second and try again. |
| "bridge protocol … Update the add-on and the server together" | Update both, as above. |
| `controlDisabled` | Allow key presses in NVDA's NVDA MCP settings. |
| `controlDenied` | You answered No, or the question closed without an answer. Ask the assistant to try again and answer Yes. |
| `appNotAllowed` | Add the application to "Only let MCP clients control these applications", or empty that setting. |
| A tool behaves like an old version | The server was not restarted; see above. |

## For the assistant

The server's instructions and each tool's description say how to use the tools.
In addition:

- The user is likely blind or low vision and hears everything NVDA says.
  Say what you are about to press before pressing it.
- Prefer reading tools. `nvda_preview_speech` shows what NVDA would say without moving focus.
- Never retry after `controlDenied`.
- After an update, check `addonVersion` in `nvda_get_status` before trusting new behaviour.
