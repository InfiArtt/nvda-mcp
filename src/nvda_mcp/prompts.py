"""Ready-made prompts: the order to use NVDA MCP's tools in for common developer tasks.

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
or an add-on folder. Then call nvda_reload_plugins, check nvda_get_log for errors, and test with \
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
