"""MCP server exposing the NVDA screen reader through the NVDA MCP add-on's bridge."""

import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import scenario
from .audit import ROLES_NEEDING_NAMES, FocusOrderAuditor
from .bridge_client import BridgeClient, NvdaBridgeError, NvdaUnavailableError

CHARACTER_LIMIT = 25_000
# Pressing keys can wait on the user answering NVDA's permission dialog.
PRESS_KEYS_TIMEOUT_SECONDS = 120.0

INSTRUCTIONS = """\
Tools for working with the NVDA screen reader on the user's Windows computer.
The user is likely blind or low vision and hears everything NVDA says.

- To learn what is on screen, start with nvda_get_focus, then nvda_get_object_tree or nvda_get_text.
- To find a control by name or role, use nvda_find_objects; then nvda_focus_object or nvda_activate_object.
- To switch applications, use nvda_list_windows and nvda_activate_window rather than Alt+Tab.
- In web pages, check documentMode (browse or focus) in nvda_get_focus before pressing keys: in browse mode
  letters move around the page. nvda_set_document_mode switches. nvda_list_elements lists headings, links and
  more; nvda_find_in_page finds text; nvda_get_text with contains searches without moving.
- Action tools take until_speech to wait for an expected announcement ("sent", a dialog title)
  and report whether it came, so you know the action worked.
- nvda_get_speech_history shows exactly what the user heard; use it to answer "what did NVDA just say?".
  nvda_wait_for_speech waits for something to be said, such as a chat reply.
- nvda_speak talks over whatever the user is doing. Use it only for short, useful announcements.
- nvda_press_keys, nvda_type_text, nvda_activate_window, nvda_focus_object, nvda_activate_object and
  nvda_audit_focus_order act on the user's computer. They work only if the user has allowed it in NVDA's
  settings, NVDA may ask the user first, and the user may limit them to some applications (appNotAllowed).
  Say what you are about to do before doing it, and never retry after a controlDenied error.
  Every action is written to a log the user can read; nvda_get_action_log shows it.
- For developers: nvda_preview_speech says what NVDA would announce for controls without moving focus;
  nvda_trace_events shows the events NVDA handles and what it said for each (why NVDA is silent);
  nvda_get_log reads NVDA's log; nvda_get_output_history shows beeps, sounds and braille;
  nvda_get_dev_info is NVDA+F1; nvda_list_scripts shows commands and keys; nvda_run_script runs a command;
  nvda_reload_plugins reloads add-on code; nvda_get_settings reads settings;
  nvda_run_scenario records a scenario and compares it with a baseline file.
"""


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class TreeRoot(str, Enum):
    FOREGROUND = "foreground"
    FOCUS = "focus"
    NAVIGATOR = "navigator"


class TextSource(str, Enum):
    FOCUS = "focus"
    NAVIGATOR = "navigator"
    REVIEW = "review"


FormatParam = Annotated[
    ResponseFormat,
    Field(
        description="'markdown' (default) is easier to read; 'json' keeps every field for further processing."
    ),
]

mcp = MCPServer("nvda_mcp", instructions=INSTRUCTIONS)
_client = BridgeClient()
MAX_CLIENT_NAME_CHARS = 60


def set_bridge_client(client: BridgeClient) -> None:
    """Replace the bridge client; used by tests."""
    global _client
    _client = client


def client_display_name(client_info: Any) -> str | None:
    """The client's name, such as "Claude Code", made safe to show in NVDA.

    :param client_info: The client's ``Implementation`` (its title and name), or None.
    """
    name = getattr(client_info, "title", None) or getattr(client_info, "name", None)
    if not isinstance(name, str):
        return None
    name = " ".join("".join(char if char.isprintable() else " " for char in name).split())
    return name[:MAX_CLIENT_NAME_CHARS] or None


async def _remember_client_name(ctx: Any, call_next: Any) -> Any:
    """Middleware: note who the client is, so NVDA can say who wants to press keys.

    Older clients say it once when they connect, newer ones with every request; the session has it either way.
    """
    client_params = ctx.session.client_params
    if client_params is not None:
        _client.client_name = client_display_name(client_params.client_info)
    return await call_next(ctx)


mcp.middleware.append(_remember_client_name)


async def _call(method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
    """Call the bridge, turning failures into tool errors the model can act on."""
    try:
        if timeout is None:
            return await _client.call(method, params)
        return await _client.call(method, params, timeout=timeout)
    except NvdaUnavailableError as error:
        raise ToolError(str(error))
    except NvdaBridgeError as error:
        raise ToolError(f"{error.code}: {error.message}")


def _truncate(text: str) -> str:
    if len(text) <= CHARACTER_LIMIT:
        return text
    return (
        text[:CHARACTER_LIMIT]
        + f"\n\n[Truncated at {CHARACTER_LIMIT} characters. Narrow the request to see the rest.]"
    )


def _json(data: Any) -> str:
    return _truncate(json.dumps(data, ensure_ascii=False, indent=2))


def _object_markdown(obj: dict[str, Any], heading: str) -> str:
    title = f"{obj.get('name') or '(no name)'} ({obj.get('role', 'unknown role')})"
    lines = [f"## {heading}: {title}"]
    for key, label in (
        ("value", "Value"),
        ("description", "Description"),
        ("states", "States"),
        ("keyboardShortcut", "Shortcut"),
        ("position", "Position"),
        ("appName", "Application"),
        ("windowClassName", "Window class"),
        ("documentMode", "Mode"),
    ):
        if key in obj:
            value = obj[key]
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, dict):
                value = ", ".join(f"{k} {v}" for k, v in value.items())
            lines.append(f"- {label}: {value}")
    if obj.get("ancestors"):
        lines.append(f"- Inside: {' > '.join(obj['ancestors'])}")
    return "\n".join(lines)


def _node_summary(node: dict[str, Any]) -> str:
    parts = [node.get("role", "?")]
    if node.get("name"):
        parts.append(f'"{node["name"]}"')
    if node.get("value"):
        parts.append(f"value {node['value']!r}")
    if node.get("states"):
        parts.append(f"[{', '.join(node['states'])}]")
    return " ".join(parts)


def _tree_markdown(node: dict[str, Any], depth: int = 0) -> list[str]:
    lines = ["  " * depth + "- " + _node_summary(node)]
    for child in node.get("children", []):
        lines.extend(_tree_markdown(child, depth + 1))
    more = node.get("moreChildren")
    if more:
        count = f"{more} more" if more is not True else "more"
        lines.append("  " * (depth + 1) + f"- … {count} children not shown")
    return lines


def _speech_text(entries: list[dict[str, Any]]) -> str:
    return " / ".join(entry["text"] for entry in entries)


READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


@mcp.tool(name="nvda_get_status", title="NVDA status", annotations=READ_ONLY)
async def nvda_get_status() -> str:
    """Check that NVDA is reachable and report its version, synthesizer, speech mode,
    the foreground application, and whether key presses are allowed.

    Call this first when other tools fail, or before nvda_press_keys to see if control is enabled.
    Returns JSON with nvdaVersion, addonVersion, synthesizer, speechMode, foregroundApp,
    foregroundWindow, isControlAllowed, isControlApprovedThisSession and lastSpeechId.
    """
    return _json(await _call("getStatus"))


@mcp.tool(name="nvda_get_focus", title="Focused control", annotations=READ_ONLY)
async def nvda_get_focus(response_format: FormatParam = ResponseFormat.MARKDOWN) -> str:
    """Describe the control that has keyboard focus, as NVDA sees it: name, role, states, value,
    description, shortcut, position in its group, application, and the containers it is inside.

    Use this to answer "where am I?" or to debug why a control is announced the way it is.
    A missing name on a button or link usually means it is unlabeled.
    """
    focus = await _call("getFocus")
    if response_format == ResponseFormat.JSON:
        return _json(focus)
    return _object_markdown(focus, "Focus")


@mcp.tool(name="nvda_get_navigator_object", title="Navigator object", annotations=READ_ONLY)
async def nvda_get_navigator_object(response_format: FormatParam = ResponseFormat.MARKDOWN) -> str:
    """Describe NVDA's navigator object: the object the user is exploring with object navigation,
    which can differ from the keyboard focus. Same fields as nvda_get_focus.
    """
    navigator = await _call("getNavigator")
    if response_format == ResponseFormat.JSON:
        return _json(navigator)
    return _object_markdown(navigator, "Navigator")


@mcp.tool(name="nvda_get_object_tree", title="Accessibility tree", annotations=READ_ONLY)
async def nvda_get_object_tree(
    root: Annotated[
        TreeRoot,
        Field(
            description="Where to start: 'foreground' window (default), the 'focus', or the 'navigator' object."
        ),
    ] = TreeRoot.FOREGROUND,
    max_depth: Annotated[
        int, Field(ge=1, le=10, description="How many levels below the root to include.")
    ] = 4,
    max_nodes: Annotated[int, Field(ge=1, le=500, description="Stop after this many objects.")] = 150,
    max_children: Annotated[
        int,
        Field(
            ge=0,
            le=500,
            description="Show at most this many children of each object, so long lists do not crowd out the rest. 0 shows all.",
        ),
    ] = 25,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Return the accessibility tree NVDA sees, as an indented outline of role, name, value and states.

    Use it to survey a window's layout or find controls that keyboard focus cannot reach.
    Unnamed layout containers (sections, panels, groupings) are skipped and their children shown in
    their place. In browsers and Electron apps, 'foreground' starts from the web document.
    Long lists are cut to max_children items with a note saying how many were left out.
    Large windows are cut off at max_nodes or after 3 seconds; the result says so.
    If it is truncated, start from 'focus' or 'navigator' instead, or lower max_depth.
    To look for one control, nvda_find_objects is faster.
    """
    result = await _call(
        "getTree",
        {"root": root.value, "maxDepth": max_depth, "maxNodes": max_nodes, "maxChildren": max_children},
    )
    if response_format == ResponseFormat.JSON:
        return _json(result)
    header = f"{result['nodeCount']} objects"
    if result.get("rootNote"):
        header += f", {result['rootNote']}"
    if result.get("truncated"):
        header += f" (truncated: {result['truncated']})"
    return _truncate("\n".join([header, "", *_tree_markdown(result["tree"])]))


@mcp.tool(name="nvda_get_text", title="Read text", annotations=READ_ONLY)
async def nvda_get_text(
    source: Annotated[
        TextSource,
        Field(
            description=(
                "'focus' (default) reads the focused document or edit field, including web pages in browse mode; "
                "'navigator' reads the navigator object; 'review' returns the line at NVDA's review cursor."
            )
        ),
    ] = TextSource.FOCUS,
    contains: Annotated[
        str | None,
        Field(
            max_length=200,
            description="Only return the lines containing this text (ignoring case), with their line numbers.",
        ),
    ] = None,
) -> str:
    """Read the full text of a document, web page or edit field, plus the line the caret is on.

    Use this instead of nvda_get_object_tree when you need the content rather than the controls.
    With contains, it searches the page without moving NVDA's cursor; nvda_find_in_page moves it.
    Text over 20,000 characters is cut off and the result says so.
    """
    result = await _call("getText", {"source": source.value})
    if "text" not in result:
        return f"Review cursor line: {result.get('currentLine', '')}"
    parts = [f"Length: {result['length']} characters"]
    if result.get("truncated"):
        parts.append(f"Truncated: {result['truncated']}")
    if "caretLine" in result:
        parts.append(f"Caret line: {result['caretLine']}")
    text = result["text"]
    if contains:
        needle = contains.casefold()
        matches = [
            f"{number}: {line}"
            for number, line in enumerate(text.splitlines(), 1)
            if needle in line.casefold()
        ]
        parts.append(f"Lines containing {contains!r}: {len(matches)}")
        text = "\n".join(matches)
    return _truncate("\n".join(parts) + "\n\n" + text)


@mcp.tool(name="nvda_get_speech_history", title="What NVDA said", annotations=READ_ONLY)
async def nvda_get_speech_history(
    after_id: Annotated[
        int,
        Field(
            ge=0,
            description="Only return utterances newer than this id. Use lastId from a previous call to get only new speech.",
        ),
    ] = 0,
    limit: Annotated[
        int, Field(ge=1, le=200, description="Return at most this many of the newest utterances.")
    ] = 30,
    contains: Annotated[
        str | None,
        Field(description="Only return utterances containing this text, ignoring case.", max_length=200),
    ] = None,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Return what NVDA has spoken, newest last, with ids for incremental polling.

    Speech is captured even when the user has speech turned off,
    so this shows exactly what NVDA would tell the user.
    """
    result = await _call("getSpeech", {"afterId": after_id, "limit": 5000 if contains else limit})
    entries = result["entries"]
    if contains:
        needle = contains.casefold()
        entries = [entry for entry in entries if needle in entry["text"].casefold()][-limit:]
    if response_format == ResponseFormat.JSON:
        return _json({"lastId": result["lastId"], "entries": entries})
    if not entries:
        return f"Nothing spoken after id {after_id}. lastId is {result['lastId']}."
    lines = [f"lastId: {result['lastId']}", ""]
    lines += [f"{entry['id']}. {entry['text']}" for entry in entries]
    return _truncate("\n".join(lines))


@mcp.tool(
    name="nvda_speak",
    title="Speak through NVDA",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
async def nvda_speak(
    text: Annotated[
        str, Field(min_length=1, max_length=2000, description="What NVDA should say and show in braille.")
    ],
    interrupt: Annotated[
        bool, Field(description="Stop current speech first. Use only for urgent messages.")
    ] = False,
) -> str:
    """Say a message through NVDA's speech and braille, like an NVDA announcement.

    Good for telling the user that a long task finished. Keep it short: the user hears every word.
    """
    await _call("speak", {"text": text, "interrupt": interrupt})
    return f"NVDA said: {text}"


CONTROL = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True
)


class HoldKey(str, Enum):
    ALT = "alt"
    CONTROL = "control"
    SHIFT = "shift"
    WINDOWS = "windows"


SettleParam = Annotated[
    int, Field(ge=100, le=5000, description="Stop listening once NVDA has been quiet this long.")
]
TimeoutParam = Annotated[
    int,
    Field(
        ge=500, le=60000, description="Stop listening, or waiting for until_speech, after this long in total."
    ),
]
UntilSpeechParam = Annotated[
    str | None,
    Field(
        max_length=200,
        description=(
            "Keep listening until NVDA says something containing this text (ignoring case), such as 'sent' or "
            "a dialog title, instead of stopping at the first pause. The result says whether it was heard."
        ),
    ),
]


def _listen(settle_ms: int, timeout_ms: int, until_speech: str | None) -> dict[str, Any]:
    """Bridge parameters that say how long to listen after an action."""
    params: dict[str, Any] = {"settleMs": settle_ms, "timeoutMs": timeout_ms}
    if until_speech:
        params["untilSpeech"] = until_speech
    return params


def _action_markdown(result: dict[str, Any]) -> str:
    """What NVDA said after an action, and where focus is now."""
    spoken = _speech_text(result["speech"]) or "(nothing)"
    text = f"NVDA said: {spoken}\n"
    if "expectedSpeechHeard" in result:
        heard = "yes" if result["expectedSpeechHeard"] else "no, it timed out"
        text += f"Expected speech heard: {heard}\n"
    return text + "\n" + _object_markdown(result["focus"], "Focus now")


@mcp.tool(name="nvda_press_keys", title="Press keys", annotations=CONTROL)
async def nvda_press_keys(
    keys: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=60)]],
        Field(
            min_length=1,
            max_length=50,
            description=(
                "Keys to press in order, using NVDA key names: 'tab', 'shift+tab', 'enter', 'space', 'escape', "
                "'downArrow', 'control+home', 'alt+f4', 'f6', 'a'."
            ),
        ),
    ],
    hold: Annotated[
        list[HoldKey] | None,
        Field(
            max_length=4,
            description=(
                "Modifiers to hold down while all the keys are pressed, then release. "
                "For example hold ['alt'] with keys ['tab', 'tab'] moves two places in the Alt+Tab switcher."
            ),
        ),
    ] = None,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Press keys in the active window, then report what NVDA said and where focus ended up.

    This sends real input, so it can change or delete things in the user's application.
    Tell the user what you will press first. It fails with controlDisabled if the user has not
    allowed key presses, and with controlDenied if they declined; do not retry after controlDenied.
    To type text, nvda_type_text is faster and does not depend on the keyboard layout.
    """
    hold = hold or []
    result = await _call(
        "pressKeys",
        {"keys": keys, "hold": [key.value for key in hold], **_listen(settle_ms, timeout_ms, until_speech)},
        PRESS_KEYS_TIMEOUT_SECONDS,
    )
    held = f" (holding {'+'.join(key.value for key in hold)})" if hold else ""
    return f"Pressed: {', '.join(keys)}{held}\n" + _action_markdown(result)


@mcp.tool(name="nvda_type_text", title="Type text", annotations=CONTROL)
async def nvda_type_text(
    text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="One line of text to type. Any language and emoji work. Press enter separately.",
        ),
    ],
    delay_ms: Annotated[
        int,
        Field(
            ge=0,
            le=200,
            description="Pause between characters. Leave at 0 unless an application drops characters.",
        ),
    ] = 0,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Type text into the focused control, as if typed on the keyboard, without touching the clipboard.

    Focus an edit field first (nvda_find_objects then nvda_focus_object, or nvda_press_keys).
    Characters are sent as Unicode, so the keyboard layout does not matter.
    Some games and remote desktop windows ignore this kind of input; use nvda_press_keys there.
    """
    result = await _call(
        "typeText",
        {"text": text, "delayMs": delay_ms, **_listen(settle_ms, timeout_ms, until_speech)},
        PRESS_KEYS_TIMEOUT_SECONDS + len(text) * delay_ms / 1000,
    )
    return f"Typed {len(text)} characters\n" + _action_markdown(result)


@mcp.tool(name="nvda_list_windows", title="Open windows", annotations=READ_ONLY)
async def nvda_list_windows(
    include_hidden: Annotated[
        bool,
        Field(
            description="Also list windows on other virtual desktops and suspended Store apps, which Alt+Tab leaves out."
        ),
    ] = False,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """List the open application windows, most recently used first, with their application names.

    Use the title or handle with nvda_activate_window to switch to one.
    """
    result = await _call("listWindows", {"includeHidden": include_hidden})
    if response_format == ResponseFormat.JSON:
        return _json(result)
    lines = []
    for window in result["windows"]:
        flags = [
            flag
            for flag, key in (
                ("in front", "isForeground"),
                ("minimized", "isMinimized"),
                ("hidden", "isHidden"),
            )
            if window.get(key)
        ]
        suffix = f" [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"- {window['title']} — {window.get('appName') or '?'} (handle {window['handle']}){suffix}"
        )
    return "\n".join(lines) or "No application windows are open."


@mcp.tool(name="nvda_activate_window", title="Switch to window", annotations=CONTROL)
async def nvda_activate_window(
    title_contains: Annotated[
        str | None,
        Field(
            max_length=200,
            description="Part of the window title, ignoring case, such as 'mwMod' or 'Notepad'.",
        ),
    ] = None,
    handle: Annotated[int | None, Field(description="A window handle from nvda_list_windows.")] = None,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Bring a window to the front, restoring it if minimized, then report what NVDA said and the new focus.

    Pass title_contains or handle. If several titles match, the first in nvda_list_windows order wins
    and the others are listed. This counts as controlling the computer, like nvda_press_keys.
    """
    if (title_contains is None) == (handle is None):
        raise ToolError("Pass exactly one of title_contains or handle.")
    params = _listen(settle_ms, timeout_ms, until_speech)
    if handle is not None:
        params["handle"] = handle
    else:
        params["titleContains"] = title_contains
    result = await _call("activateWindow", params, PRESS_KEYS_TIMEOUT_SECONDS)
    text = f"Switched to: {result['window']['title']}\n"
    if result.get("otherMatches"):
        text += f"Other matching windows: {'; '.join(result['otherMatches'])}\n"
    return text + _action_markdown(result)


@mcp.tool(name="nvda_wait_for_speech", title="Wait for NVDA to say something", annotations=READ_ONLY)
async def nvda_wait_for_speech(
    contains: Annotated[
        str | None,
        Field(
            max_length=200,
            description="Wait for an utterance containing this text, ignoring case. Leave out to wait for any speech.",
        ),
    ] = None,
    after_id: Annotated[
        int | None,
        Field(
            ge=0,
            description="Also consider speech newer than this id, so nothing said before the call is missed. Defaults to now.",
        ),
    ] = None,
    timeout_ms: Annotated[int, Field(ge=100, le=120000, description="Give up after this long.")] = 10000,
) -> str:
    """Wait until NVDA says something, such as a chat reply, a download finishing or a dialog opening.

    Returns as soon as a matching utterance arrives, with everything said meanwhile.
    Pass after_id (lastId from an earlier result) to also catch speech that arrived before this call.
    """
    params: dict[str, Any] = {"timeoutMs": timeout_ms}
    if contains:
        params["contains"] = contains
    if after_id is not None:
        params["afterId"] = after_id
    result = await _call("waitForSpeech", params, timeout_ms / 1000 + 10)
    lines = []
    if result["found"]:
        lines.append(f"Heard: {result['match']['text']} (id {result['match']['id']})")
    else:
        lines.append(f"Nothing matching within {timeout_ms} ms.")
    if result["speech"]:
        lines += ["", "Everything said meanwhile:"]
        lines += [f"{entry['id']}. {entry['text']}" for entry in result["speech"]]
    lines += ["", f"lastId: {result['lastId']}"]
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_find_objects", title="Find controls", annotations=READ_ONLY)
async def nvda_find_objects(
    name_contains: Annotated[
        str | None,
        Field(
            max_length=200, description="Part of the control's name, ignoring case, such as 'Chat' or 'Send'."
        ),
    ] = None,
    role: Annotated[
        str | None,
        Field(
            max_length=60,
            description="The role as NVDA says it ('button', 'edit', 'list', 'check box') or NVDA's internal name ('editableText').",
        ),
    ] = None,
    max_results: Annotated[int, Field(ge=1, le=50, description="Stop after this many matches.")] = 20,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Search the foreground window for controls by name and/or role, nearest the top of the window first.

    Each result has an id for nvda_focus_object and nvda_activate_object. Ids are only valid until the
    next search. Faster and more precise than reading the whole tree or tabbing around.
    """
    if not name_contains and not role:
        raise ToolError("Pass name_contains, role, or both.")
    result = await _call(
        "findObjects", {"nameContains": name_contains, "role": role, "maxResults": max_results}
    )
    if response_format == ResponseFormat.JSON:
        return _json(result)
    lines = [f"{obj['id']}. {_node_summary(obj)}" for obj in result["objects"]] or ["No matching controls."]
    if result.get("truncated"):
        lines.append(f"(Search {result['truncated']}.)")
    return _truncate("\n".join(lines))


ObjectIdParam = Annotated[int, Field(ge=1, description="An id from the last nvda_find_objects result.")]


@mcp.tool(name="nvda_focus_object", title="Focus a control", annotations=CONTROL)
async def nvda_focus_object(
    id: ObjectIdParam,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Move keyboard focus to a control found with nvda_find_objects, then report what NVDA said.

    Use this to reach an edit field before nvda_type_text. Some controls cannot take focus.
    """
    result = await _call(
        "focusObject", {"id": id, **_listen(settle_ms, timeout_ms, until_speech)}, PRESS_KEYS_TIMEOUT_SECONDS
    )
    return _action_markdown(result)


@mcp.tool(name="nvda_activate_object", title="Activate a control", annotations=CONTROL)
async def nvda_activate_object(
    id: ObjectIdParam,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Perform a control's default action (press a button, follow a link, toggle a check box),
    like NVDA's activate command, then report what NVDA said.

    The control is found with nvda_find_objects and does not need focus first.
    """
    result = await _call(
        "activateObject",
        {"id": id, **_listen(settle_ms, timeout_ms, until_speech)},
        PRESS_KEYS_TIMEOUT_SECONDS,
    )
    return _action_markdown(result)


class DocumentMode(str, Enum):
    BROWSE = "browse"
    FOCUS = "focus"


@mcp.tool(name="nvda_set_document_mode", title="Switch browse or focus mode", annotations=CONTROL)
async def nvda_set_document_mode(
    mode: Annotated[
        DocumentMode,
        Field(
            description=(
                "'browse' to read and move around a web page with NVDA's keys (h, k, arrows); "
                "'focus' to type into fields and use the page's own keys."
            )
        ),
    ],
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
) -> str:
    """Switch NVDA between browse mode and focus mode in a web page or document, like NVDA+space.

    nvda_get_focus and nvda_get_status report the current mode as documentMode.
    In browse mode single letters move around the page instead of typing, so switch to focus mode
    before nvda_type_text in a web form if NVDA did not switch by itself.
    """
    result = await _call(
        "setDocumentMode",
        {"mode": mode.value, **_listen(settle_ms, timeout_ms, None)},
        PRESS_KEYS_TIMEOUT_SECONDS,
    )
    return f"Mode: {mode.value}\n" + _action_markdown(result)


@mcp.tool(name="nvda_find_in_page", title="Find in page", annotations=CONTROL)
async def nvda_find_in_page(
    text: Annotated[str, Field(min_length=1, max_length=200, description="The text to find.")],
    reverse: Annotated[
        bool, Field(description="Search upwards from the cursor instead of downwards.")
    ] = False,
    from_start: Annotated[
        bool,
        Field(
            description="Search from the top of the page (or the bottom, with reverse) instead of the cursor."
        ),
    ] = False,
    case_sensitive: Annotated[bool, Field(description="Match upper and lower case exactly.")] = False,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
) -> str:
    """Move NVDA's browse mode cursor to the next match on the page and read that line, like NVDA's find
    command (NVDA+control+f) but without its dialogs. The user can continue the search with NVDA+F3.

    Needs a web page or document in browse mode. To search without moving the cursor,
    use nvda_get_text with contains.
    """
    result = await _call(
        "findInPage",
        {
            "text": text,
            "reverse": reverse,
            "fromStart": from_start,
            "caseSensitive": case_sensitive,
            **_listen(settle_ms, timeout_ms, None),
        },
        PRESS_KEYS_TIMEOUT_SECONDS,
    )
    return f"Found on line: {result.get('foundLine')}\n" + _action_markdown(result)


class ElementType(str, Enum):
    HEADING = "heading"
    LINK = "link"
    LANDMARK = "landmark"
    FORM_FIELD = "formField"
    BUTTON = "button"
    EDIT = "edit"
    COMBO_BOX = "comboBox"
    CHECK_BOX = "checkBox"
    RADIO_BUTTON = "radioButton"
    TABLE = "table"
    LIST = "list"
    LIST_ITEM = "listItem"
    GRAPHIC = "graphic"
    FRAME = "frame"
    ARTICLE = "article"
    GROUPING = "grouping"
    FIGURE = "figure"
    TAB = "tab"
    SEPARATOR = "separator"
    BLOCK_QUOTE = "blockQuote"
    EMBEDDED_OBJECT = "embeddedObject"
    ANNOTATION = "annotation"
    ERROR = "error"


@mcp.tool(name="nvda_list_elements", title="List page elements", annotations=READ_ONLY)
async def nvda_list_elements(
    type: Annotated[ElementType, Field(description="Which kind of element to list.")] = ElementType.HEADING,
    max_results: Annotated[int, Field(ge=1, le=200, description="Stop after this many elements.")] = 50,
) -> str:
    """List the headings, links, landmarks, form fields or other elements of the web page or document,
    in page order, like NVDA's Elements List (NVDA+F7).

    Each element has an id for nvda_move_to_element. Ids are only valid until the next list.
    Works in browse mode and focus mode.
    """
    result = await _call("listElements", {"type": type.value, "maxResults": max_results})
    lines = []
    for element in result["elements"]:
        level = f" (level {element['level']})" if element.get("level") else ""
        lines.append(f"{element['id']}. {element.get('label') or '(no label)'}{level}")
    if not lines:
        lines.append(f"No {type.value} elements on this page.")
    if result.get("truncated"):
        lines.append(f"(List {result['truncated']}.)")
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_move_to_element", title="Go to page element", annotations=CONTROL)
async def nvda_move_to_element(
    id: Annotated[int, Field(ge=1, description="An id from the last nvda_list_elements result.")],
    activate: Annotated[
        bool,
        Field(
            description="Also activate it: follow a link or press a button, like Enter in the Elements List."
        ),
    ] = False,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Move NVDA's browse mode cursor to an element from nvda_list_elements and read it, or activate it."""
    result = await _call(
        "moveToElement",
        {"id": id, "activate": activate, **_listen(settle_ms, timeout_ms, until_speech)},
        PRESS_KEYS_TIMEOUT_SECONDS,
    )
    return _action_markdown(result)


@mcp.tool(name="nvda_get_action_log", title="Action log", annotations=READ_ONLY)
async def nvda_get_action_log(
    limit: Annotated[int, Field(ge=1, le=200, description="Show this many of the newest actions.")] = 20,
) -> str:
    """Show the newest entries of the log of actions MCP clients took through NVDA:
    keys pressed, text typed, windows switched and controls activated, with time and window.
    """
    result = await _call("getActionLog", {"limit": limit})
    lines = [f"Log file: {result['path']}"]
    if not result.get("isLogging"):
        lines.append("Logging is turned off in NVDA's settings.")
    for entry in result["entries"]:
        details = {k: v for k, v in entry.items() if k not in ("time", "action", "window")}
        lines.append(
            f"- {entry['time']} {entry['action']} in {entry.get('window')!r}: {json.dumps(details, ensure_ascii=False)}"
        )
    if not result["entries"]:
        lines.append("No actions logged yet.")
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_audit_focus_order", title="Audit keyboard focus order", annotations=CONTROL)
async def nvda_audit_focus_order(
    ctx: Context,
    max_steps: Annotated[int, Field(ge=1, le=100, description="Press the key at most this many times.")] = 30,
    key: Annotated[
        str,
        Field(
            min_length=1,
            max_length=60,
            description="The key that moves focus: 'tab' (default), 'shift+tab', 'downArrow'.",
        ),
    ] = "tab",
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Walk through an application's keyboard focus order and report accessibility problems,
    using what NVDA actually announces.

    Starting from the current focus, this presses `key` repeatedly and records each control and
    what NVDA said. It stops when focus returns to the start, stops moving, or leaves the application.
    It flags unlabeled buttons, links and fields; controls NVDA says nothing for;
    duplicate names that users cannot tell apart; and focus that is stuck or escapes the app.
    Focus is left wherever the walk ends.

    Ask the user to focus the first control of the window to audit before calling this.
    Needs key presses to be allowed, like nvda_press_keys.
    """
    start = await _call("getFocus")
    auditor = FocusOrderAuditor(key, start)
    stop_reason = None
    for step in range(1, max_steps + 1):
        await ctx.report_progress(step, max_steps, f"Pressing {key} ({step} of {max_steps})")
        result = await _call(
            "pressKeys", {"keys": [key], "settleMs": 400, "timeoutMs": 2500}, PRESS_KEYS_TIMEOUT_SECONDS
        )
        stop_reason = auditor.add_step(result["focus"], _speech_text(result["speech"]))
        if stop_reason:
            break
    report = auditor.finish(f"reached max_steps ({max_steps})")
    if response_format == ResponseFormat.JSON:
        return _json(report.to_dict())
    return _truncate(report.to_markdown())


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    IO = "IO"
    DEBUGWARNING = "DEBUGWARNING"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@mcp.tool(name="nvda_get_log", title="NVDA log", annotations=READ_ONLY)
async def nvda_get_log(
    min_level: Annotated[
        LogLevel,
        Field(
            description="Show entries at this level and above. WARNING (default) shows warnings and errors."
        ),
    ] = LogLevel.WARNING,
    contains: Annotated[
        str | None,
        Field(
            max_length=200, description="Only entries whose source or message contains this, ignoring case."
        ),
    ] = None,
    include_io: Annotated[
        bool,
        Field(
            description="Also show IO entries (keys pressed, text spoken). Off by default: they can include what the user typed."
        ),
    ] = False,
    limit: Annotated[int, Field(ge=1, le=200, description="Show this many of the newest entries.")] = 30,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Read NVDA's log, the one its Log Viewer shows, newest entries last.

    Use it to find tracebacks from add-ons, app modules or NVDA itself, for example after a command did nothing.
    Debug entries only exist when NVDA's logging level (General settings) is debug.
    """
    result = await _call(
        "getLog",
        {"minLevel": min_level.value, "contains": contains, "includeIo": include_io, "limit": limit},
    )
    if response_format == ResponseFormat.JSON:
        return _json(result)
    lines = [f"Log file: {result['path']} (logging level {result['loggingLevel']})"]
    if result.get("startOmitted"):
        lines.append("Only the end of the log was read.")
    if not result["entries"]:
        lines.append(
            f"No {min_level.value} or higher entries" + (f" containing {contains!r}." if contains else ".")
        )
    for entry in result["entries"]:
        lines += ["", f"### {entry['level']} {entry['time']} {entry['source']}", entry["message"]]
    return _truncate("\n".join(lines))


class TraceAction(str, Enum):
    START = "start"
    READ = "read"
    STOP = "stop"


def _event_line(entry: dict[str, Any]) -> str:
    target = f"{entry.get('name') or '(no name)'} ({entry.get('role') or '?'})"
    line = f"{entry['id']}. {entry['event']} on {target} in {entry.get('app') or '?'}"
    if entry.get("windowClassName"):
        line += f" [{entry['windowClassName']}]"
    if entry.get("details"):
        line += f" {json.dumps(entry['details'], ensure_ascii=False)}"
    if entry.get("spoken"):
        line += f"\n   NVDA said: {entry['spoken']}"
    elif not entry.get("spokenNearby"):
        line += "\n   NVDA said nothing"
    if entry.get("spokenNearby"):
        line += f"\n   NVDA said around then, probably because of this: {entry['spokenNearby']}"
    return line


@mcp.tool(
    name="nvda_trace_events",
    title="Trace NVDA events",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
async def nvda_trace_events(
    action: Annotated[
        TraceAction,
        Field(
            description="'start' begins recording; 'read' returns what was recorded and keeps going; 'stop' returns it and stops."
        ),
    ],
    events: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=60)]] | None,
        Field(
            max_length=30,
            description="With start: only record these events, such as ['gainFocus', 'nameChange', 'valueChange', 'liveRegionChange', 'UIA_notification']. All events by default.",
        ),
    ] = None,
    app: Annotated[
        str | None,
        Field(
            max_length=100,
            description="With start: only record events from this application, such as 'mwmod'.",
        ),
    ] = None,
    after_id: Annotated[
        int,
        Field(
            ge=0, description="With read or stop: only events after this id (afterId from start, or lastId)."
        ),
    ] = 0,
    wait_ms: Annotated[
        int,
        Field(
            ge=0,
            le=60000,
            description="With read or stop: keep recording this long first, for example while the user tries something.",
        ),
    ] = 0,
    limit: Annotated[
        int, Field(ge=1, le=500, description="Return at most this many of the newest events.")
    ] = 100,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Record the events NVDA handles (focus changes, name and value changes, live regions, UIA
    notifications...) and what NVDA said while handling each one.

    This answers "why did NVDA say nothing?": either the application sent no event,
    or NVDA got one and chose not to speak. Start tracing, act (nvda_press_keys or the user), then read.
    Tracing stops by itself after 10 minutes.
    """
    params: dict[str, Any] = {"action": action.value}
    if action == TraceAction.START:
        params.update({"events": events or [], "app": app})
        result = await _call("traceEvents", params)
        scope = ", ".join(events) if events else "all events"
        if app:
            scope += f" in {app}"
        return (
            f"Tracing {scope}. Read with after_id {result['afterId']}. "
            f"It stops by itself after {result['stopsAfterSeconds'] // 60} minutes."
        )
    params.update({"afterId": after_id, "waitMs": wait_ms, "limit": limit})
    result = await _call("traceEvents", params, timeout=wait_ms / 1000 + 10)
    if response_format == ResponseFormat.JSON:
        return _json(result)
    state = "still tracing" if result["tracing"] else "tracing is off"
    lines = [f"{len(result['entries'])} events, lastId {result['lastId']}, {state}.", ""]
    lines += [_event_line(entry) for entry in result["entries"]]
    return _truncate("\n".join(lines))


class OutputKind(str, Enum):
    BEEP = "beep"
    SOUND = "sound"
    BRAILLE = "braille"
    SPEECH_CANCELED = "speechCanceled"


def _output_line(entry: dict[str, Any]) -> str:
    kind = entry["kind"]
    if kind == "speech":
        return f"speech: {entry['text']}"
    if kind == "beep":
        return f"beep: {entry['hz']} Hz for {entry['lengthMs']} ms"
    if kind == "sound":
        return f"sound: {entry['file']}"
    if kind == "braille":
        return f"braille: {entry['text']}"
    return "speech was cut off"


@mcp.tool(name="nvda_get_output_history", title="Beeps, sounds and braille", annotations=READ_ONLY)
async def nvda_get_output_history(
    after_id: Annotated[
        int, Field(ge=0, description="Only entries newer than this id (lastId from a previous call).")
    ] = 0,
    kinds: Annotated[
        list[OutputKind] | None,
        Field(description="Only these kinds: beep, sound, braille, speechCanceled. All by default."),
    ] = None,
    include_speech: Annotated[
        bool,
        Field(description="Merge in what NVDA said, in time order, to see the whole picture."),
    ] = False,
    limit: Annotated[
        int, Field(ge=1, le=500, description="Return at most this many of the newest entries.")
    ] = 50,
) -> str:
    """Show what NVDA put out besides speech: beeps (progress bars, errors), sounds (browse mode,
    errors), what it wrote to the braille display, and when speech was cut off by newer speech.

    Speech being cut off is a common cause of "NVDA started to say it and then didn't".
    """
    result = await _call(
        "getOutput",
        {"afterId": after_id, "kinds": [kind.value for kind in kinds] if kinds else None, "limit": limit},
    )
    entries = result["entries"]
    if include_speech and entries:
        start = entries[0]["timestamp"]
        speech = await _call("getSpeech", {"afterId": 0, "limit": 500})
        entries = sorted(
            entries
            + [{**entry, "kind": "speech"} for entry in speech["entries"] if entry["timestamp"] >= start],
            key=lambda entry: entry["timestamp"],
        )[-limit:]
    lines = [f"lastId: {result['lastId']}", ""]
    lines += [_output_line(entry) for entry in entries] or ["Nothing recorded."]
    return _truncate("\n".join(lines))


class ObjectTarget(str, Enum):
    FOCUS = "focus"
    NAVIGATOR = "navigator"


@mcp.tool(name="nvda_get_dev_info", title="Developer info", annotations=READ_ONLY)
async def nvda_get_dev_info(
    target: Annotated[
        ObjectTarget, Field(description="'focus' (default) or the 'navigator' object.")
    ] = ObjectTarget.FOCUS,
    id: Annotated[
        int | None, Field(ge=1, description="Instead, a control from the last nvda_find_objects result.")
    ] = None,
) -> str:
    """NVDA's developer info for a control, like NVDA+F1: its accessibility API properties
    (IAccessible, UIA, IA2), window, Python classes including overlay classes, and app module.

    Use it to see which API and NVDAObject class NVDA uses for a control, and why it behaves as it does.
    """
    params: dict[str, Any] = {"target": target.value}
    if id is not None:
        params["id"] = id
    result = await _call("getDevInfo", params)
    lines = ["## Object", *result["object"], "", "## Python classes", *result["classes"]]
    if result.get("treeInterceptor"):
        lines += ["", f"Tree interceptor: {result['treeInterceptor']} ({result['documentMode']} mode)"]
    if result["appModule"]:
        lines += ["", "## App module", *result["appModule"]]
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_list_scripts", title="Commands and keys", annotations=READ_ONLY)
async def nvda_list_scripts(
    contains: Annotated[
        str | None,
        Field(
            max_length=100,
            description="Only commands whose description, name, category or key contains this.",
        ),
    ] = None,
    key: Annotated[
        str | None,
        Field(
            max_length=60,
            description="Instead, say which command this key runs where focus is now, such as 'NVDA+f1' or 'control+home'.",
        ),
    ] = None,
    max_results: Annotated[int, Field(ge=1, le=300, description="Stop after this many commands.")] = 50,
) -> str:
    """List the NVDA commands available where focus is now, with their keys, like the Input Gestures
    dialog: NVDA's own, add-ons', the app module's and the focused control's.

    With key, say which command a key runs here, or that it goes straight to the application.
    """
    if key:
        result = await _call("listScripts", {"key": key})
        if result["passesThrough"]:
            return f"{key} runs no NVDA command here; it goes to the application."
        lines = [f"{key} runs {result['script']}"]
        for label, field_name in (
            ("Description", "description"),
            ("Category", "category"),
            ("Defined in", "class"),
        ):
            if result.get(field_name):
                lines.append(f"- {label}: {result[field_name]}")
        return "\n".join(lines)
    result = await _call("listScripts", {"contains": contains, "maxResults": max_results})
    lines = []
    for item in result["scripts"]:
        keys = ", ".join(item.get("gestures", [])) or "no key"
        lines.append(
            f"- {item['description']} — {item.get('script') or '?'} [{keys}] ({item['category']}; {item.get('class') or '?'})"
        )
    if not lines:
        lines.append("No matching commands.")
    if result.get("truncated"):
        lines.append(f"(List {result['truncated']}.)")
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_run_script", title="Run an NVDA command", annotations=CONTROL)
async def nvda_run_script(
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="The command's script name from nvda_list_scripts, such as 'reportCurrentFocus' or 'dateTime'.",
        ),
    ],
    class_name: Annotated[
        str | None,
        Field(
            max_length=100,
            description="Only the command defined by this class, when several define the same name, such as 'GlobalCommands'.",
        ),
    ] = None,
    settle_ms: SettleParam = 400,
    timeout_ms: TimeoutParam = 3000,
    until_speech: UntilSpeechParam = None,
) -> str:
    """Run an NVDA command by name, as if its key were pressed, then report what NVDA said.

    This works whatever keys the user has assigned. Commands that pass their key on to the
    application cannot do so, since no key was pressed. Needs key presses to be allowed, like nvda_press_keys.
    """
    params = {"name": name, "className": class_name, **_listen(settle_ms, timeout_ms, until_speech)}
    result = await _call("runScript", params, PRESS_KEYS_TIMEOUT_SECONDS)
    return f"Ran {name}\n" + _action_markdown(result)


@mcp.tool(
    name="nvda_reload_plugins",
    title="Reload NVDA plugins",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    ),
)
async def nvda_reload_plugins() -> str:
    """Reload global plugins and app modules from disk, like NVDA+control+F3, to try changed add-on code
    without restarting NVDA.

    This add-on is reloaded too: its bridge restarts with a new port, which the next call picks up.
    Calls made in the next second or so may fail; wait briefly, then use nvda_get_log to look for errors.
    Needs key presses to be allowed, like nvda_press_keys.
    """
    await _call("reloadPlugins", {}, PRESS_KEYS_TIMEOUT_SECONDS)
    return "Reloading plugins. Wait a second before the next call, then check nvda_get_log for errors."


class PreviewTarget(str, Enum):
    FOCUS = "focus"
    NAVIGATOR = "navigator"
    FOUND = "found"
    WINDOW = "window"


def _preview_issues(preview: dict[str, Any]) -> list[str]:
    issues = []
    if preview.get("error"):
        issues.append(f"NVDA could not describe it: {preview['error']}")
    elif not preview.get("spoken"):
        issues.append("NVDA would say nothing")
    role = preview.get("role")
    if role in ROLES_NEEDING_NAMES and not (preview.get("name") or "").strip():
        issues.append(f"Unlabeled {role}")
    return issues


@mcp.tool(name="nvda_preview_speech", title="Preview what NVDA would say", annotations=READ_ONLY)
async def nvda_preview_speech(
    target: Annotated[
        PreviewTarget,
        Field(
            description=(
                "'focus' (default) or 'navigator'; 'found' for every control from the last nvda_find_objects; "
                "'window' for every focusable control in the foreground window."
            )
        ),
    ] = PreviewTarget.FOCUS,
    id: Annotated[
        int | None, Field(ge=1, description="Instead, one control from the last nvda_find_objects result.")
    ] = None,
    max_results: Annotated[
        int, Field(ge=1, le=100, description="With 'window': stop after this many controls.")
    ] = 50,
    response_format: FormatParam = ResponseFormat.MARKDOWN,
) -> str:
    """Say what NVDA would announce when each control gets focus, without moving focus or pressing keys,
    and flag controls that are unlabeled or silent.

    With 'window' this scans a whole window at once, including controls Tab cannot reach; the controls
    get ids for nvda_focus_object, nvda_activate_object and nvda_get_dev_info.
    It shows announcements only: to test what happens when keys are pressed, use nvda_audit_focus_order.
    """
    params: dict[str, Any] = {"target": target.value, "maxResults": max_results}
    if id is not None:
        params["id"] = id
    result = await _call("previewSpeech", params)
    previews = [{**preview, "issues": _preview_issues(preview)} for preview in result["previews"]]
    if response_format == ResponseFormat.JSON:
        return _json({"previews": previews, "truncated": result.get("truncated")})
    issue_count = sum(len(preview["issues"]) for preview in previews)
    summary = f"{len(previews)} control(s), {issue_count} issue(s)."
    if result.get("truncated"):
        # Said up front, so a short list without issues does not read as a clean window.
        summary += f" Not every control was checked: the search {result['truncated']}."
    lines = [
        summary,
        "",
        "| Id | NVDA would say | Issues |",
        "|---|---|---|",
    ]
    for preview in previews:
        cells = [
            str(preview.get("id") or "-"),
            preview.get("spoken") or "(nothing)",
            "; ".join(preview["issues"]),
        ]
        lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    return _truncate("\n".join(lines))


@mcp.tool(name="nvda_get_settings", title="NVDA settings", annotations=READ_ONLY)
async def nvda_get_settings(
    section: Annotated[
        str | None,
        Field(
            max_length=100,
            description="A settings section such as 'speech', 'presentation', 'documentFormatting' or 'keyboard', or a subsection such as 'speech.ibmeci'. Leave out to list the sections.",
        ),
    ] = None,
) -> str:
    """Read NVDA's settings as they apply now, including the active configuration profile,
    for example to explain why something is or is not announced (punctuation level, reporting of
    object descriptions, position information).

    Settings whose names suggest secrets, such as an add-on's API key, are hidden.
    """
    result = await _call("getSettings", {"section": section})
    profile = result.get("profile") or "normal configuration"
    if "sections" in result:
        return f"Active profile: {profile}\nSections: {', '.join(result['sections'])}"
    return f"Active profile: {profile}\n\n" + _json(result["values"])


class ScenarioStep(BaseModel):
    """One step of a scenario: set exactly one of keys, text or wait_ms."""

    keys: list[str] | None = Field(
        default=None, max_length=20, description="Keys to press, as in nvda_press_keys."
    )
    text: str | None = Field(default=None, max_length=500, description="Text to type, as in nvda_type_text.")
    wait_ms: int | None = Field(
        default=None, ge=0, le=30000, description="Just wait, recording what NVDA says."
    )
    until_speech: str | None = Field(
        default=None,
        max_length=200,
        description="Keep listening until NVDA says this, as in nvda_press_keys.",
    )


def _step_label(step: ScenarioStep) -> str:
    if step.keys:
        return "press " + " ".join(step.keys)
    if step.text is not None:
        return f"type {step.text!r}"
    return f"wait {step.wait_ms} ms"


async def _run_step(step: ScenarioStep) -> dict[str, Any]:
    listen = _listen(400, 3000, step.until_speech)
    if step.keys:
        return await _call("pressKeys", {"keys": step.keys, **listen}, PRESS_KEYS_TIMEOUT_SECONDS)
    if step.text is not None:
        return await _call("typeText", {"text": step.text, **listen}, PRESS_KEYS_TIMEOUT_SECONDS)
    status = await _call("getStatus")
    params: dict[str, Any] = {"afterId": status["lastSpeechId"], "timeoutMs": step.wait_ms}
    if step.until_speech:
        params["contains"] = step.until_speech
    waited = await _call("waitForSpeech", params, (step.wait_ms or 0) / 1000 + 10)
    return {"speech": waited["speech"], "focus": await _call("getFocus")}


@mcp.tool(name="nvda_run_scenario", title="Run and compare a scenario", annotations=CONTROL)
async def nvda_run_scenario(
    ctx: Context,
    steps: Annotated[
        list[ScenarioStep],
        Field(
            min_length=1,
            max_length=100,
            description='Steps in order, each with one of keys, text or wait_ms, for example [{"keys": ["tab"]}, {"text": "hello"}, {"keys": ["enter"], "until_speech": "sent"}].',
        ),
    ],
    baseline_file: Annotated[
        str | None,
        Field(
            max_length=500,
            description="A JSON file to compare with. If it does not exist, this run is saved there as the baseline. Keep it in the project, such as tests/a11y/login.json.",
        ),
    ] = None,
    update_baseline: Annotated[
        bool, Field(description="Save this run as the new baseline instead of comparing.")
    ] = False,
    ignore_pattern: Annotated[
        str | None,
        Field(
            max_length=200,
            description=r"A regular expression for text that changes between runs, such as times ('\d+:\d+'); ignored when comparing.",
        ),
    ] = None,
) -> str:
    """Run a scenario of key presses and typing, record what NVDA said and where focus went after each
    step, and compare it with a saved baseline: an accessibility regression test.

    Start from the same place each time (the same window and control), or the results will differ.
    Needs key presses to be allowed, like nvda_press_keys.
    """
    for step in steps:
        if sum(value is not None for value in (step.keys, step.text, step.wait_ms)) != 1:
            raise ToolError(
                f"Each step needs exactly one of keys, text or wait_ms: {step.model_dump(exclude_none=True)}"
            )
    if ignore_pattern:
        try:
            re.compile(ignore_pattern)
        except re.error as error:
            raise ToolError(f"ignore_pattern is not a valid regular expression: {error}")
    recording = scenario.Recording()
    for number, step in enumerate(steps, 1):
        await ctx.report_progress(number, len(steps), _step_label(step))
        result = await _run_step(step)
        recording.steps.append(
            scenario.StepRecord(
                _step_label(step), _speech_text(result["speech"]), scenario.focus_label(result["focus"])
            )
        )
    lines = [recording.to_markdown(), ""]
    if baseline_file is None:
        return "\n".join(lines)
    path = Path(baseline_file).expanduser()
    if update_baseline or not path.exists():
        scenario.save_baseline(path, recording)
        lines.append(f"Saved as the baseline in {path}.")
        return "\n".join(lines)
    try:
        baseline = scenario.load_baseline(path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ToolError(f"Could not read the baseline {path}: {error}")
    differences = scenario.compare(baseline, recording, ignore_pattern)
    if differences:
        lines += [f"**Differs from the baseline** in {path}:", *[f"- {line}" for line in differences]]
    else:
        lines.append(f"Matches the baseline in {path}.")
    return _truncate("\n".join(lines))


def main() -> None:
    # httpx logs every bridge request at INFO, which floods the MCP client's server log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
