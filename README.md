# NVDA MCP

NVDA MCP connects AI assistants to the [NVDA](https://www.nvaccess.org) screen reader through the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP).
The assistant works from what NVDA knows and says, acts through NVDA, and hears the result. So it can do what
screen reader users need most: make an application that does not work with NVDA usable, find out why NVDA is
silent, and help someone from far away. You hear every step, and you stay in control.

## Why it exists

Many applications still do not work with a screen reader. NVDA says only "button" or "pane", and the person who
needs the application cannot use it. Until now there were two ways out: wait for its developer to fix it, which
often never happens, or write an NVDA add-on, which takes skill and hours of testing by ear, with the blind user
trying every change and reporting what NVDA said.

AI assistants that write code do not solve this on their own, because they cannot hear what a screen reader user
hears. The raw accessibility data of Windows is not what NVDA says: NVDA combines several accessibility
interfaces, browse mode and the add-ons you have installed. And assistants that use a computer by looking at
screenshots leave screen reader users out: they click things you never hear about, and a picture of the screen is
not what you experience.

NVDA MCP gives the assistant NVDA's view and NVDA's voice: the focused control, the accessibility tree, the text
of a document or web page, and exactly what NVDA said. With that, the assistant can close the whole loop itself.
It finds what NVDA cannot read, writes a small add-on that fixes it, loads it into the NVDA that is running, and
hears whether NVDA now says the right thing. The person who needs the fix is no longer the tester: they say
"this does not work", listen, and decide. From user to builder.

When the assistant acts, it uses the keyboard through NVDA, the way you would, only after you allow it, and NVDA
announces every step. With MCP Access, it can also help someone else from far away, through their NVDA and with
their permission.

The add-ons [Proton VPN Accessibility](https://github.com/InfiArtt/protonvpn-nvda) and
[NYK DAEMON82 MKN-09 Access](https://github.com/InfiArtt/nyk-daemon82-nvda) were made this way.

## What it is useful for

For people who use NVDA:

- **Making an application usable.** Tell the assistant "NVDA only says button here". It finds what NVDA
  cannot read, writes a small add-on that fixes it, tests it with NVDA and packages it for you to install.
- **Getting help from far away.** With MCP Access, someone you trust helps you with their AI assistant,
  working through your NVDA, while you stay in control and hear every step.
- **Reading what NVDA cannot.** When an application shows NVDA nothing but a "pane", the assistant can read
  the text on the screen with Windows' text recognition, as NVDA+R does.
- **Getting through confusing applications.** Ask where you are, what a window holds, where a control is or why
  a button has no name, and get an answer based on what NVDA actually sees, with the keys to press.
- **Reporting a problem.** The assistant gathers the facts and writes a bug report for the application's
  developer, for you to send.
- **Doing repetitive tasks.** The assistant can move through an application with the keyboard,
  type text, switch windows, and wait for something to happen, such as a chat reply.
- **Learning.** Ask which NVDA commands work where you are, or what a key does here.
- **Asking any AI, even without MCP.** One NVDA command copies what NVDA sees where you are, ready to paste
  into ChatGPT, Gemini or any chat.
- **Asking about what you heard.** The assistant can read what NVDA said, to repeat something you missed or
  sum up a long dialog.

For developers and testers:

- **See what NVDA announces** for each control without moving focus, and find unlabeled or silent controls.
- **Audit the tab order** of a dialog or page: duplicate names, keyboard traps, controls NVDA says nothing about.
- **Find out why NVDA is silent**: trace the events NVDA handles and what it said for each one.
- **Regression tests**: record what NVDA says through a series of key presses, and compare later runs with it.
- **Develop NVDA add-ons faster**: read NVDA's log, see developer info like NVDA+F1, and reload add-on code.

## Who it is for

- **Blind and low-vision people** who use NVDA and want an AI assistant that works with their screen reader
  instead of around it.
- **NVDA add-on developers**, who can test what their add-on makes NVDA say without doing every step by hand.
- **Developers of Windows applications and websites**, who want to check their work with a real screen reader.
- **Accessibility testers, auditors and QA teams**, who need repeatable checks of what a screen reader announces.
- **Friends, volunteers, trainers and support staff** who help screen reader users, from next to them or,
  with MCP Access, from far away.

## What you need

- Windows with NVDA 2025.1 or later.
- An AI assistant that supports MCP, such as Claude Code, Claude Desktop, Codex CLI, Cursor or VS Code.
- [uv](https://docs.astral.sh/uv/), which downloads and runs the NVDA MCP server for you.
  If you already have Python 3.11 or later, you can use pip or pipx instead.

NVDA MCP has two parts: this add-on, and a small program called the **nvda-mcp server**, which your assistant
starts. The add-on comes from NVDA's Add-on Store; the server comes from the Python Package Index (PyPI).
Both are free and open source.

## Setting it up

1. **Install the add-on.** In NVDA, open Tools, then Add-on Store. Find NVDA MCP, install it and restart NVDA.
2. **Install uv**, if you don't have it. Open a command prompt and run:

   ```
   winget install --id=astral-sh.uv -e
   ```

   Close the command prompt and open a new one, so it finds uv.
3. **Connect your assistant.** In NVDA, open Settings (NVDA+N, Preferences, Settings), then the
   **NVDA MCP** category. Choose your assistant under *Set up this MCP client* and press **Set up now**.
   NVDA asks before it changes anything, then tells you to restart the assistant.
   - For Claude Desktop, Antigravity and Cursor, NVDA MCP adds itself to the assistant's settings file,
     keeps the rest of the file, and saves a copy of the old one with `.bak` added to its name.
   - For Claude Code and Codex CLI, it runs the assistant's own setup command for you.
   - For other assistants, choose *Other clients*, press **Copy setup command** and paste the settings into
     the assistant's MCP settings file. **Copy setup command** also works for every assistant above, if you
     prefer to do it yourself.

   The command is like `claude mcp add --scope user nvda -- uvx nvda-mcp==1.0.0`: it tells your assistant to
   run the server version that matches your add-on.

Start your assistant and ask it something like "what has focus in NVDA?". It answers without pressing anything.

### With pip or pipx instead of uv

```
pipx install nvda-mcp
claude mcp add --scope user nvda -- nvda-mcp
```

Use the same version as the add-on, and upgrade both together. With plain pip, run `python -m nvda_mcp` if the
`nvda-mcp` command is not found.

## Safety

Reading is always allowed. Everything that acts on your computer is **off until you turn it on**:
pressing keys, typing, switching windows, activating controls, moving through web pages,
running NVDA commands and reloading add-ons.

In NVDA's Settings, **NVDA MCP** category:

- **Let MCP clients, such as AI assistants, connect to NVDA** (on by default).
- **Allow MCP clients to press keys** (off by default).
- **Ask before the first key press after NVDA starts** (on by default). NVDA asks you, with **No** focused,
  and names the program asking, as it calls itself.
- **Only let MCP clients control these applications** (empty by default, meaning all).
  For example `notepad, winword`. Anything else is refused.
- **Keep a log of every action MCP clients take** (on by default), in `%APPDATA%\nvda\nvdaMcp\actions.log`.
- **Let MCP clients read the HTML of web pages through the browser's remote debugging** (off by default),
  for developers of add-ons for web apps. The browser also asks you before every new connection.
- **Let MCP clients take pictures of controls on the screen** (off by default), for developers who want
  to compare what a control looks like with what NVDA says for it. It works with Screen Curtain on.
- **Number of spoken messages to remember** (500 by default).
- **Never let MCP Access helpers press keys** (off by default; NVDA asks you once per session instead).
- **Never let MCP Access helpers take pictures of the screen** (off by default; NVDA asks you once per session).
- **MCP Access relay address** (`wss://infiartt.com/mcp-access/v1` by default).

Commands in Input Gestures, NVDA MCP category (no keys assigned by default):

- Report whether NVDA MCP is running and whether it may press keys.
- Stop MCP clients from pressing keys until you approve again.
- Open the log of actions MCP clients have taken.
- Copy what NVDA sees here, to paste into a chat with any AI assistant: the application, the focused control,
  the controls in the window and what NVDA said last. It works without an MCP client.
- Share this computer with a helper through MCP Access, or say who is connected.
- Stop sharing this computer through MCP Access.
- Open the MCP Access window, to talk with your helper.

How the connection is protected:

- The add-on listens only on your own computer (127.0.0.1), on a random port.
- Every request needs a secret token, made new each time NVDA starts, stored where only your Windows account
  can read it.
- Requests from web pages are refused.
- Nothing works on secure screens (sign-in, UAC), and requests are refused while Windows is locked.
- The settings live in NVDA's base configuration, so a configuration profile cannot turn key presses on.

## MCP Access: help from far away

MCP Access lets someone you trust help you from their own computer, with their AI assistant working through
**your** NVDA. They see what NVDA sees on your computer, as if their assistant were next to you, and you hear
everything that happens. The person being helped needs only NVDA and this add-on: no AI assistant, account
or subscription.

**To get help:**

1. In Input Gestures, NVDA MCP category, give a key to *Shares this computer with a helper through MCP Access*.
2. Press it. NVDA copies a code such as `K7Q4-9XMC-4TRW-PH3N-AD6F` to the clipboard. Send it to your helper,
   for example by message. The code works once, for 10 minutes.
3. When your helper connects, NVDA asks whether to let them see this computer, with **No** focused.
   It says the name they gave and a short session check you can compare with them.
4. If they want to press keys, or take pictures of your screen to see what something looks like, NVDA asks you
   again, once for each of these in this session. You hear every key.
5. Talk with your helper while they work: their messages play a sound and are spoken as messages from them.
   *Opens the MCP Access window* shows your conversation, a field to answer (Enter sends), and a button to stop
   sharing. Escape closes the window; sharing goes on.
6. Use *Stops sharing this computer through MCP Access* at any time. Sharing also ends after two hours.

**To help someone:** paste the code they sent into your assistant, for example
"help my friend, the code is K7Q4-9XMC-4TRW-PH3N-AD6F". Your assistant connects with `nvda_access_connect`;
every NVDA tool then works on their computer until `nvda_access_disconnect`. Your assistant can ask them
questions with `nvda_access_send_message` and wait for their answer with `nvda_access_messages`; a message
that arrives while it does something else comes with its next result.
Or choose the ready-made prompt
`help_someone` and paste the code: it also tells the assistant to say before it acts, never to ask for
passwords, and to disconnect when done. The code is safe to paste: it works once and expires after 10 minutes.

How it is protected:

- **End-to-end encrypted.** The two computers agree on keys made from the code and fresh random keys
  (X25519 and AES-256-GCM). The relay in between, which InfiArtt runs at `wss://infiartt.com/mcp-access/v1`
  behind Cloudflare, only forwards data it cannot read, and never sees the code. A code that leaks after
  a session cannot unlock it.
- **Strict TLS 1.3** to the relay, with its certificate always checked.
- **The code works once**, expires after 10 minutes, and the relay limits how often codes can be tried.
- **You allow the helper first**, and again before their first key press and their first picture of the screen
  in each session, even if those are off in NVDA MCP's settings. Check *Never let MCP Access helpers press keys*
  or *Never let MCP Access helpers take pictures of the screen* to refuse them altogether.
- **Some tools never work through MCP Access:** reloading add-ons, running NVDA commands, NVDA's log and
  settings, and reading web pages' HTML.
- **Every connection and action is written** to the action log on your computer.
- Never tell a helper a password, and close private windows before you share.

## Privacy

The add-on itself sends nothing over the internet. But **what your assistant reads goes to the assistant**,
and most assistants send it to their provider's servers. That can include the text on your screen,
what NVDA says, the contents of documents and chat windows, and anything NVDA reads aloud while you type.
It can also read windows you are not looking at, such as a chat window in the background
or on another virtual desktop.

If you let it read web pages' HTML (off by default), note that turning on remote debugging in your browser
lets a program you allow reach every tab and signed-in site in that browser, and lets other programs on
your computer ask to connect too. NVDA MCP only reads the page you are working with, never runs scripts
or reads cookies, and NVDA tells you before it connects. Turn remote debugging off when you are done.

If you let it take pictures of controls (off by default), each picture shows that part of your screen,
whatever is there, and goes to the assistant's provider like everything else it reads.
Every picture is written to the action log.

If you use the command that copies what NVDA sees, read what you paste before you send it:
it holds the controls and text of the window, and what NVDA said last, which can come from other windows.

The assistant can read text on the screen with Windows' text recognition (`nvda_recognize_text`), like NVDA+R.
It reads the window or control it is asked about, whatever is shown there, and every use is written to the action log.

- Before you work with something private, such as banking, passwords or personal messages,
  close your assistant or turn off *Let MCP clients connect* in NVDA's settings.
- NVDA's speech history is kept in memory only, and cleared when NVDA restarts.
- The action log stays on your computer.

## Tools

The assistant sees these tools:

| Tool | What it does |
|---|---|
| `nvda_get_status` | NVDA version, synthesizer, speech mode, foreground app, permissions |
| `nvda_get_focus` | The focused control: name, role, states, value, position, containers |
| `nvda_get_navigator_object` | The same, for NVDA's navigator object |
| `nvda_get_object_tree` | The accessibility tree of the foreground window, focus, navigator, a found control or a window in the background; long lists are shortened |
| `nvda_find_objects` | Find controls by name and/or role, in the foreground window, inside a found control, or in a window in the background |
| `nvda_get_text` | Full text of a document, web page or edit field, plus the caret line; or only the lines containing some text |
| `nvda_get_speech_history` | What NVDA said, with ids for polling and a text filter |
| `nvda_wait_for_speech` | Wait until NVDA says something, such as a chat reply |
| `nvda_list_windows` | Open application windows, including ones that belong to another window, and ones on other virtual desktops if asked |
| `nvda_speak` | Say something through NVDA's speech and braille |
| `nvda_press_keys` | Press keys, optionally holding modifiers, then report what NVDA said and where focus went |
| `nvda_type_text` | Type a line of text in any language, emoji included, without using the clipboard |
| `nvda_set_value` | Experimental: give an edit field new text through the accessibility API, even in a background window |
| `nvda_activate_window` | Bring a window to the front by title or handle |
| `nvda_focus_object` | Move focus to a control found with `nvda_find_objects` |
| `nvda_activate_object` | Press, follow or toggle a control found with `nvda_find_objects` |
| `nvda_set_document_mode` | Switch between browse mode and focus mode in a web page, like NVDA+space |
| `nvda_find_in_page` | Move the browse mode cursor to a match on the page, like NVDA's find command |
| `nvda_list_elements` | Headings, links, landmarks, form fields and more, like the Elements List |
| `nvda_move_to_element` | Move to, or activate, an element from `nvda_list_elements` |
| `nvda_get_action_log` | The newest entries of the log of actions clients took |
| `nvda_audit_focus_order` | Tab through a window and report unlabeled controls, silent controls, duplicate names, keyboard traps |
| `nvda_access_connect` | Help someone through MCP Access: connect to their NVDA with the code they sent, after they allow it |
| `nvda_access_send_message` | Say a message on the computer of the person you help; NVDA keeps it for them to hear again |
| `nvda_access_messages` | Read the messages the person you help sent you, waiting for an answer if asked |
| `nvda_access_disconnect` | End the MCP Access session, so the tools work on this computer again |
| `nvda_recognize_text` | Read the text on the screen in a window or control with Windows' text recognition (OCR), line by line, when NVDA cannot read it |

For developers of add-ons and accessible applications:

| Tool | What it does |
|---|---|
| `nvda_preview_speech` | What NVDA would announce when a control gets focus, without moving focus; scan a whole window and flag unlabeled or silent controls |
| `nvda_inspect_object` | A control's IAccessible2 attributes or UIA properties, its containers and children, loaded and reported rows of virtual lists, and the most stable way for an add-on to recognize it, with example code |
| `nvda_trace_events` | Record the events NVDA handles (focus, name and value changes, live regions, UIA notifications) and what it said for each one; can also ask for events from a window in the background, and say what changed in the accessibility tree meanwhile |
| `nvda_inspect_html` | The HTML element behind a control in Chrome, Brave or Edge, through the browser's remote debugging: data attributes, the HTML around it, styles and event listeners, which NVDA cannot see |
| `nvda_find_html` | Find elements in the web page by CSS selector, through the browser's remote debugging |
| `nvda_get_log` | NVDA's log, filtered by level and text; IO entries (keys typed) only when asked |
| `nvda_get_output_history` | Beeps, sounds, braille output and speech being cut off, optionally merged with speech |
| `nvda_get_dev_info` | Developer info for a control, like NVDA+F1 |
| `nvda_lookup_api` | Check a name in the running NVDA's Python code before using it in an add-on: whether it exists, what it is, its signature, docstring and members, a link to NVDA's source, close names when it does not exist; or search for names |
| `nvda_capture_control` | A picture of a control on the screen next to what NVDA says for it, to find icons and visible text the accessible name leaves out |
| `nvda_list_scripts` | NVDA commands available where focus is, with their keys; or which command a key runs |
| `nvda_run_script` | Run an NVDA command by name, whatever key it is assigned to |
| `nvda_reload_plugins` | Reload add-ons and app modules from disk, like NVDA+control+F3 |
| `nvda_get_addon_paths` | Where add-on code goes: NVDA's developer scratchpad and whether NVDA loads code from it, and the add-ons running |
| `nvda_get_settings` | Read NVDA's settings as they apply now; values that look like secrets are hidden |
| `nvda_run_scenario` | Run keys and typing, record what NVDA said after each step, and compare with a baseline file |

Ready-made prompts walk the assistant through common tasks with these tools, in the right order:

- For everyone: `explain_screen` (where am I and what can I do here), `make_accessible` (find what stops NVDA
  in an application, write a small add-on that fixes it, test it and package it), `report_problem`
  (write a bug report for the application's developer) and `help_someone` (help someone through MCP Access
  with the code they sent).
- For developers: `audit_accessibility`, `build_addon`, `why_silent` and `check_labels`.

Clients that support MCP prompts offer them as commands; in Claude Code, for example, type
`/mcp__nvda__make_accessible`.

Action tools such as `nvda_press_keys` and `nvda_activate_object` take `record`: the result then also says
what the action changed in the accessibility tree (controls added, removed, renamed or moved, values
and states) and which events NVDA handled.

Every action reports what NVDA said afterwards and where focus went, and can wait for an expected announcement,
such as "sent" or a dialog's title.

## Support NVDA MCP

NVDA MCP is free, and made in spare time. If it helps you, you can support its development with a donation
through [PayPal](https://paypal.me/rafli23115). There is also a **Donate** button in NVDA's Settings,
NVDA MCP category.

## More

- [Using NVDA MCP](docs/using.md): updating, restarting the server, and what to do when something does not work.
- [What's new](CHANGELOG.md) in each version.
- [Contributing](CONTRIBUTING.md): building, testing and releasing.
- Questions and bug reports: [GitHub issues](https://github.com/InfiArtt/nvda-mcp/issues).

## License

Copyright (C) 2026 InfiArtt.
NVDA MCP is free software under the [GNU General Public License, version 2](COPYING.txt) or later.
The software it uses and their licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
