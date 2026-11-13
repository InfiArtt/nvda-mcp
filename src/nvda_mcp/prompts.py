"""Ready-made prompts: the order to use NVDA MCP's tools in for common tasks of users and developers.

MCP clients show them as commands, so someone new to the tools can start from the task instead of the tool list.
"""

COMMON = (
    "The user is likely blind or low vision and hears everything NVDA says. Before any tool that presses keys, "
    "switches windows or moves focus, say what it will do. Talk to the user in their language and plain words."
)


def audit_accessibility(what: str | None) -> str:
    target = what or "the application in front"
    return f"""Audit the accessibility of {target} with NVDA, the way a screen reader user meets it, and report \
what to fix.

1. If it is not in front, find it with nvda_list_windows and bring it forward with nvda_activate_window. \
Then use nvda_get_focus to see where NVDA is and, in a web page, whether it is in browse or focus mode.
2. Scan the whole window without pressing keys: nvda_preview_speech with target "window". \
It flags unlabeled controls and controls NVDA says nothing for.
3. In a web page, list headings, landmarks and links with nvda_list_elements. Look for skipped heading levels, \
a missing main landmark, and links whose text means nothing on its own, such as "click here" or "more".
4. Check the keyboard: ask the user to focus the first control, then run nvda_audit_focus_order. \
It presses Tab and reports focus traps, unlabeled controls and duplicate names.
5. For a control that looks wrong, nvda_capture_control shows its picture next to what NVDA says, \
if the user allowed pictures, and nvda_inspect_object or nvda_inspect_html shows where its name comes from.

Report the problems in order of how much they block a screen reader user. For each one give: where it is, \
what NVDA says now, what it should say, the WCAG success criterion, and how to fix it in the application's code. \
Say what you could not check.

{COMMON}"""


def build_addon(goal: str) -> str:
    return f"""Help me write an NVDA add-on that will: {goal}

Work from the NVDA that is running, not from memory:
1. Study the application: nvda_get_focus, nvda_find_objects and nvda_inspect_object for the controls involved. \
nvda_inspect_object suggests stable conditions for chooseNVDAObjectOverlayClasses. In web apps, nvda_inspect_html \
and nvda_find_html show attributes NVDA cannot see, such as data-testid.
2. For what happens over time, run nvda_trace_events while the user, or nvda_press_keys, does the action: \
with background_window for a window in the background, and with tree to see what changed.
3. Before using any NVDA name in code (modules, functions, classes, roles, events), check it with nvda_lookup_api: \
NVDA changes its API in the first release of each year. Use its search to find the right name.
4. Write the code in NVDA's style: tabs, camelCase, and messages the user hears wrapped in _() with \
a "# Translators:" comment. Use an app module for one application and a global plugin otherwise.
5. Ask the user where to put the files: NVDA's developer scratchpad (allowed in NVDA's Advanced settings) \
or an add-on folder; nvda_get_addon_paths gives both and says whether the scratchpad is on. \
Then call nvda_reload_plugins, check nvda_get_log for errors, and test with \
nvda_preview_speech, nvda_press_keys and nvda_get_speech_history.

Explain each step and why. {COMMON}"""


def why_silent(situation: str | None) -> str:
    where = f"when: {situation}" if situation else "here"
    return f"""Find out why NVDA says nothing {where}

1. Use nvda_get_focus and nvda_get_speech_history to see where NVDA is and what it said last.
2. Start nvda_trace_events, ask the user to do the action again (or do it with nvda_press_keys), then read \
the trace. No event means the application did not tell NVDA; an event with nothing spoken means NVDA or an add-on \
chose to stay quiet.
3. For the control involved: nvda_get_dev_info (like NVDA+F1) and nvda_inspect_object; nvda_get_settings for \
settings that hide information, such as reporting descriptions or dynamic content changes; nvda_get_log for \
errors from add-ons.
4. For content that changes by itself, such as chat messages, trace with background_window, or look for \
liveRegionChange and UIA_notification events.

Explain the cause and who can fix it: the application's developer (with the code change), an NVDA setting \
the user can change, or an add-on. {COMMON}"""


def check_labels(what: str | None) -> str:
    target = what or "the window in front"
    return f"""Compare what is on the screen with what NVDA says for the controls in {target}.

1. nvda_preview_speech with target "window" lists the controls with what NVDA says for each, and gives them ids.
2. For each control that is unlabeled, silent, or vaguely named (such as "button", "icon", an id or a file name), \
call nvda_capture_control with its id to see it. That needs "Let MCP clients take pictures of controls on \
the screen" checked in NVDA's NVDA MCP settings. If it is off, explain why it helps and that the pictures go to \
the AI provider, and let the user decide.
3. Describe what each picture shows (icon, visible text, colour) and compare it with what NVDA says: missing \
names, visible text that is not in the name (WCAG 2.5.3), icons whose meaning is not spoken, and state shown \
only by colour (WCAG 1.4.1).

List each mismatch with what it looks like, what NVDA says, and the label or code change that fixes it. {COMMON}"""


def make_accessible(what: str | None, problem: str | None) -> str:
    target = what or "the application in front"
    complaint = f' The user says: "{problem}".' if problem else ""
    return f"""Make {target} usable with NVDA by writing a small NVDA add-on for it, test it in the NVDA that is \
running, and package it.{complaint}

The user may not be a programmer. Explain each step in plain words, and ask before anything that changes \
their computer.

1. Find where it fails. Bring the application forward (nvda_list_windows, nvda_activate_window), then use \
nvda_get_focus, nvda_preview_speech with target "window" and nvda_get_object_tree. Ask the user what they \
were trying to do and what NVDA said. If NVDA reads nothing at all (only "pane" or "graphic"), \
nvda_recognize_text shows the text on the screen, and nvda_inspect_object shows what the application \
exposes. Tell the user, in a short list, what is wrong.
2. Decide what an add-on can fix: unlabeled controls (give them names), silent changes (announce them), \
missing keyboard commands (add scripts), confusing reading order. Say plainly what it cannot fix: an \
application that exposes nothing to NVDA needs its developer, or a much bigger add-on.
3. Learn the controls: nvda_find_objects and nvda_inspect_object suggest stable conditions to recognize each \
control by; for changes over time, run nvda_trace_events while the user or nvda_press_keys does the action.
4. Write an app module named after the program (nvda_get_status or nvda_get_dev_info gives its name). \
Check every NVDA name with nvda_lookup_api before using it. Follow NVDA's style: tabs, camelCase, and \
messages the user hears wrapped in _() with a "# Translators:" comment.
5. Load it: nvda_get_addon_paths says where NVDA's developer scratchpad is and whether NVDA loads code from \
it. If it is off, ask the user to turn it on, as that tool explains; never change it for them. Write the file \
there (if you cannot write files, give the user the code and the exact path), call nvda_reload_plugins and \
check nvda_get_log for errors.
6. Test like the user: nvda_preview_speech, nvda_press_keys and nvda_get_speech_history. Repeat steps 4 to 6 \
until NVDA says the right thing, then ask the user to try it.
7. Package it: a folder with manifest.ini (name, summary, description, author, version, \
minimumNVDAVersion and lastTestedNVDAVersion from nvda_get_status) and the appModules folder, zipped and \
renamed to .nvda-addon. Tell the user where it is, that installing it is opening the file, and to remove the \
scratchpad copy afterwards so it does not load twice.

{COMMON}"""


def explain_screen(question: str | None) -> str:
    ask = f' The user asks: "{question}".' if question else ""
    return f"""Explain to the user where they are and what they can do here, from what NVDA reads.{ask}

1. nvda_get_status for the application and window, nvda_get_focus for where focus is, and \
nvda_get_speech_history for what NVDA said recently.
2. nvda_get_object_tree for what the window holds. In a web page, nvda_list_elements with headings and \
landmarks gives its layout; nvda_get_text reads its text.
3. If parts have no names or NVDA reads nothing, say so, and use nvda_recognize_text to read the text on \
the screen.

Answer in a few short sentences first: what this window is, where focus is, and the two or three things \
the user most likely wants to do, each with the keys to press from where they are (Tab, arrows, a letter in \
browse mode, an NVDA command from nvda_list_scripts). Then offer more detail. Do not press keys unless the user \
asks you to. {COMMON}"""


def report_problem(problem: str | None) -> str:
    about = f' The user describes it as: "{problem}".' if problem else ""
    return f"""Help the user report an accessibility problem to the developer of the application they are \
using.{about}

1. Find the facts without pressing keys: nvda_get_status (NVDA version and application), nvda_get_focus, \
nvda_preview_speech with target "window", and nvda_get_speech_history for what NVDA said. Ask the user for \
the steps that lead to the problem; if they agree, repeat them with nvda_press_keys and \
nvda_trace_events to see what NVDA received.
2. For the controls involved, nvda_inspect_object (or nvda_inspect_html in a web page, if allowed) shows what \
the application tells NVDA, so the developer knows what to change.

Write the report in the language the developer uses (English if unsure): a short title; the application \
and its version, Windows, and NVDA's version; numbered steps to reproduce; what NVDA says and what it \
should say; who it blocks and how badly; the WCAG success criterion; and a suggested fix in the \
application's code. Leave out private content you saw on the screen. Show the report to the user and let \
them send it: never post it, email it or file it yourself. {COMMON}"""


def help_someone(code: str, problem: str | None) -> str:
    about = f' They need help with: "{problem}".' if problem else ""
    return f"""Help someone through MCP Access with the code they sent: {code}{about}

1. Connect with nvda_access_connect and this code, with helper_name set to the name of the user you work for, \
so they know an AI is talking to them. If you work in Claude Code, start the background monitor its answer \
suggests, so their messages wake you. NVDA on their computer asks them to allow it; tell the user \
you are waiting for that answer. If the code was used already or expired, ask for a new one.
2. Once connected, every NVDA tool works on their computer, not the user's. Start with nvda_get_status, \
nvda_get_focus and nvda_get_object_tree to see where they are, and nvda_get_speech_history for what they heard.
3. Prefer reading and explaining, so they learn and stay in control. Before pressing keys, typing or taking a \
picture of their screen, say what you will do and why: NVDA asks them the first time in the session, and they \
hear every key. If they decline, guide them to do it themselves instead.
4. Never ask for passwords, codes or other secrets, and do not read private content aloud to the user unless \
it is needed for the help.
5. Talk with them: nvda_access_send_message says a message on their computer, and they answer with an NVDA \
command; wait for answers with nvda_access_messages and wait_seconds instead of asking again and again.
6. When done, or when they want to stop, call nvda_access_disconnect.

Always make clear whose computer you are describing. {COMMON}"""
