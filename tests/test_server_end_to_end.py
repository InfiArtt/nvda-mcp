"""Runs the real MCP server against the real add-on bridge, with NVDA replaced by a scripted window."""

import base64
import re
import sys

import apiLookup
import pytest
import screenImage
from bridge import Bridge, BridgeError
from mcp import Client
from mcp.types import Implementation
from speechLog import SpeechLog

from nvda_mcp import server
from nvda_mcp.bridge_client import BridgeClient

pytestmark = pytest.mark.anyio


def _row(key, name, index):
    return {"key": f"ia2:100:-{key}", "role": "row", "name": name, "index": index}


# A WhatsApp-like page before and after sending "hello" to Ana, as the add-on's snapshots describe it.
BEFORE = {
    "nodeCount": 7,
    "truncated": None,
    "tree": {
        "key": "ia2:100:-1",
        "role": "document",
        "name": "WhatsApp",
        "index": 0,
        "children": [
            {
                "key": "ia2:100:-2",
                "role": "table",
                "name": "Chat list",
                "index": 0,
                "children": [_row(10, "Budi, 5:10 AM, see you", 0), _row(11, "Ana, 5:01 AM, hi", 1)],
            },
            {
                "key": "ia2:100:-3",
                "role": "list",
                "name": "Messages",
                "index": 1,
                "children": [_row(20, "hi, 5:01 AM", 0)],
            },
            {"key": "ia2:100:-4", "role": "edit", "name": "Type a message", "value": "hello", "index": 2},
        ],
    },
}
AFTER = {
    "nodeCount": 8,
    "truncated": None,
    "alive": True,
    "tree": {
        **BEFORE["tree"],
        "children": [
            {
                **BEFORE["tree"]["children"][0],
                "children": [_row(11, "Ana, 5:47 AM, hello", 0), _row(10, "Budi, 5:10 AM, see you", 1)],
            },
            {
                **BEFORE["tree"]["children"][1],
                "children": [_row(20, "hi, 5:01 AM", 0), _row(21, "hello, 5:47 AM, Pending", 1)],
            },
            {"key": "ia2:100:-4", "role": "edit", "name": "Type a message", "index": 2},
        ],
    },
}
RECORDING = {
    "root": {"role": "document", "name": "WhatsApp"},
    "rootNote": "the web document",
    "seconds": 1.2,
    "before": BEFORE,
    "after": AFTER,
    "events": [
        {"id": 31, "event": "valueChange", "name": "Type a message", "role": "edit", "app": "brave"},
        {"id": 32, "event": "caret", "name": "Type a message", "role": "edit", "app": "brave"},
        {
            "id": 33,
            "event": "liveRegionChange",
            "role": "section",
            "app": "brave",
            "spokenNearby": "Message sent",
        },
    ],
}
WEB_ELEMENT = {
    "name": "Send",
    "role": "button",
    "appName": "brave",
    "browser": "Brave",
    "processId": 4242,
    "appPath": "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    "location": [100, 200, 40, 40],
    "attributes": {"tag": "button", "class": "x1n2onr6"},
    "documentUrl": "https://web.whatsapp.com/",
    "documentTitle": "WhatsApp",
    "documentLocation": [0, 80, 1280, 900],
    "domNodeId": 3921,
    "domNodeIdFromParent": False,
}


class FakeWindow:
    """A window with a fixed tab order that speaks like NVDA when focus moves."""

    def __init__(self, controls, allow_control=True, accepts_values=True, allow_browser=True):
        self.allow_browser = allow_browser
        self.allow_capture = True
        self.window_in_front = True
        self.controls = controls
        self.index = 0
        self.allow_control = allow_control
        self.accepts_values = accepts_values
        self.speech = SpeechLog(maxEntries=100)
        self.calls = {}

    def focus(self, params=None):
        name, role = self.controls[self.index]
        return {
            "name": name,
            "role": role,
            "appName": "demo",
            "location": [self.index, 0, 10, 10],
            "ancestors": ["Demo (window)"],
        }

    def press_keys(self, params):
        if not self.allow_control:
            raise BridgeError("controlDisabled", "Pressing keys is turned off.")
        start = self.speech.lastId
        self.held = params.get("hold")
        self.calls["lastPressKeys"] = params
        self.client_name = params.get("clientName")
        for key in params["keys"]:
            step = -1 if key == "shift+tab" else 1
            self.index = (self.index + step) % len(self.controls)
            name, role = self.controls[self.index]
            self.speech.add(f"{name} {role}".strip())
        return self.result(start, params)

    def result(self, start, params):
        """What the add-on returns after an action, including whether until_speech was heard."""
        spoken = self.speech.since(start)
        result = {"speech": [entry.toDict() for entry in spoken], "focus": self.focus()}
        if params.get("untilSpeech"):
            needle = params["untilSpeech"].casefold()
            result["expectedSpeechHeard"] = any(needle in entry.text.casefold() for entry in spoken)
        if "record" in params:
            result["recording"] = RECORDING
        return result

    def web_element_info(self, params):
        self.calls.setdefault("webElementInfo", []).append(
            {k: v for k, v in params.items() if k != "clientName"}
        )
        if not self.allow_browser:
            raise BridgeError(
                "browserInspectionDisabled", "Reading web pages through remote debugging is off."
            )
        return getattr(self, "web_element", WEB_ELEMENT)

    def speak_after_action(self, text, params):
        start = self.speech.lastId
        self.speech.add(text)
        return self.result(start, params)

    def type_text(self, params):
        start = self.speech.lastId
        self.typed = params["text"]
        self.speech.add(params["text"])
        return {"speech": [entry.toDict() for entry in self.speech.since(start)], "focus": self.focus()}

    def set_value(self, params):
        self.calls["setValue"] = params
        value = params["text"] if self.accepts_values else ""
        return {
            "speech": [],
            "focus": self.focus(),
            "method": "IAccessible accValue",
            "object": {"name": "Type a message", "role": "edit", "value": value},
        }

    def trace_events(self, params):
        self.calls["traceEvents"] = params
        if params["action"] == "start":
            result = {"afterId": 4, "stopsAfterSeconds": 600}
            if "tree" in params:
                result["tree"] = {
                    "root": {"role": "document", "name": "WhatsApp"},
                    "rootNote": "the web document",
                    "nodeCount": 7,
                    "truncated": None,
                }
            if "backgroundWindow" in params:
                result["background"] = {
                    "events": ["nameChange", "liveRegionChange"],
                    "processId": 7,
                    "windowClasses": ["Chrome_RenderWidgetHostHWND", "Chrome_WidgetWin_1"],
                }
            return result
        tree = (
            {"tree": {k: v for k, v in RECORDING.items() if k != "events"}}
            if params["action"] == "stop"
            else {}
        )
        return {
            **(tree if self.calls.get("traceTree") else {}),
            "tracing": params["action"] != "stop",
            "lastId": 7,
            "entries": [
                {"id": 5, "event": "nameChange", "name": "Status", "role": "text", "app": "demo"},
                {
                    "id": 6,
                    "event": "liveRegionChange",
                    "name": "Status",
                    "role": "text",
                    "app": "demo",
                    "spokenNearby": "Saved",
                },
                {
                    "id": 7,
                    "event": "liveRegionChange",
                    "role": "section",
                    "app": "brave",
                    "background": True,
                    "text": "3 chats found",
                },
            ],
        }

    def handlers(self):
        return {
            "typeText": self.type_text,
            "setValue": self.set_value,
            "inspectObject": lambda params: {
                "object": {"name": "Chat list", "role": "table", "appName": "brave"},
                "roleConstant": "TABLE",
                "api": "IAccessible2",
                "attributes": {"xml-roles": "grid", "name-from": "attribute", "rowcount": "357"},
                "table": {"loadedRows": 16},
                "params": params,
            },
            "setDocumentMode": lambda params: self.speak_after_action(params["mode"] + " mode", params),
            "findInPage": lambda params: {
                **self.speak_after_action("Prices start at 10 dollars", params),
                "foundLine": "Prices start at 10 dollars",
                "params": params,
            },
            "listElements": lambda params: {
                "type": params["type"],
                "elements": [
                    {"id": 1, "label": "Welcome", "level": 1},
                    {"id": 2, "label": "Prices", "level": 2},
                ],
                "truncated": None,
            },
            "moveToElement": lambda params: self.speak_after_action("Prices heading level 2", params),
            "getText": lambda params: {
                "source": "focus",
                "length": 40,
                "text": "Welcome\nPrices start at 10 dollars\nContact us about prices",
            },
            "listWindows": lambda params: {
                "windows": [
                    {"handle": 11, "title": "Claude", "appName": "claude", "isForeground": True},
                    {
                        "handle": 22,
                        "title": "mwMod v6",
                        "appName": "mwmod",
                        "isHidden": params["includeHidden"],
                    },
                ]
            },
            "activateWindow": lambda params: {
                "window": {"title": "mwMod v6"},
                "otherMatches": ["mwMod log"],
                "speech": [{"id": 1, "timestamp": 0, "text": "mwMod v6 window"}],
                "focus": self.focus(),
                "params": params,
            },
            "waitForSpeech": lambda params: {
                "found": True,
                "match": {"id": 7, "timestamp": 0, "text": "Ana: hi Claude"},
                "speech": [
                    {"id": 6, "timestamp": 0, "text": "typing"},
                    {"id": 7, "timestamp": 0, "text": "Ana: hi Claude"},
                ],
                "lastId": 7,
            },
            "findObjects": lambda params: {
                "objects": [
                    {"id": 1, "name": f"Send, inside {params['within']}", "role": "button"}
                    if "within" in params
                    else {"id": 2, "name": f"Type a message, in window {params['window']}", "role": "edit"}
                    if "window" in params
                    else {"id": 1, "name": "Chat in dominion", "role": "edit", "states": ["focusable"]}
                ],
                "truncated": None,
                **({"webPageUnavailable": True} if params.get("window") == 23 else {}),
            },
            "getTree": lambda params: (
                self.calls.update(getTree=params)
                or {
                    "nodeCount": 3,
                    "truncated": None,
                    "tree": {
                        "role": "window",
                        "name": "Demo",
                        "children": [
                            {
                                "role": "list",
                                "name": "Scripts",
                                "moreChildren": 898,
                                "children": [{"role": "list item", "name": "a.mws"}],
                            }
                        ],
                    },
                    **({"webPageUnavailable": True} if params.get("window") == 23 else {}),
                }
            ),
            "getStatus": lambda params: {"lastSpeechId": self.speech.lastId},
            "previewSpeech": lambda params: {
                "previews": [
                    {"id": 1, "spoken": "Search edit", "name": "Search", "role": "edit"},
                    {"id": 2, "spoken": "button", "role": "button"},
                    {"id": 3, "spoken": "", "name": "Logo", "role": "graphic"},
                ],
                "truncated": "stopped after 3.0 seconds" if params["maxResults"] == 3 else None,
            },
            "getLog": lambda params: {
                "path": "nvda.log",
                "loggingLevel": "INFO",
                "startOmitted": False,
                "entries": [
                    {
                        "level": "ERROR",
                        "time": "23:43:26.884",
                        "source": "external:globalPlugins.foo",
                        "message": "ZeroDivisionError",
                    }
                ],
            },
            "traceEvents": self.trace_events,
            "webElementInfo": self.web_element_info,
            "getFocus": self.focus,
            "getSpeech": lambda params: {
                "lastId": self.speech.lastId,
                "entries": [
                    e.toDict() for e in self.speech.since(params.get("afterId", 0), params.get("limit"))
                ],
            },
            "pressKeys": self.press_keys,
            "speak": lambda params: self.speech.add(params["text"]) or {"spoken": params["text"]},
            "lookupApi": self.lookup_api,
            "captureControl": self.capture_control,
            "recognizeText": lambda params: (
                self.calls.update(recognizeText=params)
                or {
                    "name": "NYK DAEMON82",
                    "role": "pane",
                    "region": [0, 0, 800, 600],
                    "language": "id-ID",
                    "method": "GDI",
                    "lines": [
                        {"text": "Light Setting", "location": [20, 40, 90, 14]},
                        {"text": "Brightness 3", "location": [20, 80, 80, 14]},
                    ]
                    if params.get("target") != "focus"
                    else [],
                }
            ),
            "mouseClick": lambda params: self.mouse("mouseClick", params),
            "mouseScroll": lambda params: self.mouse("mouseScroll", params),
            "mouseMove": lambda params: self.mouse("mouseMove", params),
            "mouseDrag": lambda params: self.mouse("mouseDrag", params),
            "getAddonPaths": lambda params: {
                "nvdaVersion": "2026.3",
                "configPath": r"C:\Users\a\AppData\Roaming\nvda",
                "scratchpadPath": r"C:\Users\a\AppData\Roaming\nvda\scratchpad",
                "scratchpadEnabled": False,
                "scratchpadFolders": [],
                "addonsPath": r"C:\Users\a\AppData\Roaming\nvda\addons",
                "runningAddons": [
                    {"name": "nvdaMcp", "version": "1.3.0", "summary": "NVDA MCP", "path": "x"}
                ],
            },
        }

    def mouse(self, method, params):
        self.calls[method] = params
        result = {**self.speak_after_action("Kick volume 3 dB", params), "point": [530, 312]}
        if method == "mouseDrag":
            result.update({"from": [530, 312], "to": [530, 260]})
        if method in ("mouseClick", "mouseMove"):
            result["objectAtPoint"] = {"role": "unknown", "appName": "reaper"}
        return result

    def capture_control(self, params):
        self.calls.setdefault("captureControl", []).append(params)
        if not self.allow_capture:
            raise BridgeError("screenCaptureDisabled", "Taking pictures of the screen is turned off.")
        # A red pixel and a blue one, as Windows gives them.
        png = screenImage.encodePng(2, 1, bytes([0, 0, 255, 0, 255, 0, 0, 0]))
        return {
            "name": "Send",
            "role": "button",
            "location": [100, 200, 40, 40],
            "region": [92, 192, 56, 56],
            "size": [56, 56],
            "method": "GDI",
            "windowInFront": self.window_in_front,
            "png": base64.b64encode(png).decode("ascii"),
        }

    def lookup_api(self, params):
        # The real lookup, over the modules this test process has loaded.
        if params.get("name"):
            result = apiLookup.lookUp(params["name"], sys.modules)
        else:
            result = apiLookup.search(params["search"], sys.modules, params["limit"])
        return {**result, "nvdaVersion": "2026.3"}


@pytest.fixture
def connect(tmp_path):
    bridges = []

    def start(window):
        connection_file = tmp_path / "connection.json"
        bridge = Bridge(window.handlers(), str(connection_file), onError=print)
        bridge.start()
        bridges.append(bridge)
        server.set_bridge_client(BridgeClient(connection_file))
        return window

    yield start
    for bridge in bridges:
        bridge.stop()


def text_of(result):
    return result.content[0].text


async def test_audit_finds_unlabeled_and_duplicate_controls(connect):
    connect(FakeWindow([("Search", "edit"), ("", "button"), ("Delete", "button"), ("Delete", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_audit_focus_order", {"max_steps": 10})
    report = text_of(result)
    assert "Pressed **tab** 4 times" in report
    assert "focus returned to where the audit started" in report
    assert "Unlabeled button" in report
    assert "Same name and role as step 2" in report


async def test_press_keys_reports_speech_and_new_focus(connect):
    connect(FakeWindow([("OK", "button"), ("Cancel", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
    assert "NVDA said: Cancel button" in text_of(result)
    assert "## Focus now: Cancel (button)" in text_of(result)


async def test_actions_tell_nvda_which_client_asks(connect):
    window = connect(FakeWindow([("OK", "button"), ("Cancel", "button")]))
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
    assert isinstance(window.client_name, str) and window.client_name


def test_client_names_are_made_safe_to_show():
    name = server.client_display_name
    assert name(Implementation(name="claude-code", title="Claude Code", version="1")) == "Claude Code"
    assert name(Implementation(name="  my\x07\nclient  ", version="1")) == "my client"
    assert name(Implementation(name="x" * 200, version="1")) == "x" * server.MAX_CLIENT_NAME_CHARS
    assert name(None) is None


async def test_speech_history_filters_and_tracks_ids(connect):
    window = connect(FakeWindow([("OK", "button")]))
    for text in ("Downloads folder", "Build finished", "Documents folder"):
        window.speech.add(text)
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_get_speech_history", {"contains": "FOLDER"})
    assert text_of(result) == "lastId: 3\n\n1. Downloads folder\n3. Documents folder"


async def test_bridge_errors_become_tool_errors(connect):
    connect(FakeWindow([("OK", "button")], allow_control=False))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_press_keys", {"keys": ["tab"]})
    assert result.is_error
    assert "controlDisabled" in text_of(result)


async def test_missing_connection_file_explains_setup(tmp_path):
    server.set_bridge_client(BridgeClient(tmp_path / "missing.json"))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_get_focus", {})
    assert result.is_error
    assert "NVDA MCP add-on is installed and enabled" in text_of(result)


async def test_invalid_arguments_are_rejected_before_reaching_nvda(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_press_keys", {"keys": []})
    assert result.is_error


async def test_press_keys_can_hold_modifiers(connect):
    window = connect(FakeWindow([("Claude", "list item"), ("mwMod", "list item"), ("Notepad", "list item")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_press_keys", {"keys": ["tab", "tab"], "hold": ["alt"]})
    assert window.held == ["alt"]
    assert text_of(result).startswith(
        "Pressed: tab, tab (holding alt)\nNVDA said: mwMod list item / Notepad list item"
    )


async def test_press_keys_rejects_unknown_hold_keys(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_press_keys", {"keys": ["tab"], "hold": ["capsLock"]})
    assert result.is_error


async def test_type_text_sends_unicode_text(connect):
    window = connect(FakeWindow([("Chat", "edit")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_type_text", {"text": "halo 😀"})
    assert window.typed == "halo 😀"
    assert text_of(result).startswith("Typed 6 characters\nNVDA said: halo 😀")


async def test_list_and_activate_windows(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        listed = text_of(await client.call_tool("nvda_list_windows", {"include_hidden": True}))
        switched = text_of(await client.call_tool("nvda_activate_window", {"title_contains": "mwmod"}))
        both = await client.call_tool("nvda_activate_window", {"title_contains": "a", "handle": 2})
    assert listed == "- Claude — claude (handle 11) [in front]\n- mwMod v6 — mwmod (handle 22) [hidden]"
    assert switched.startswith(
        "Switched to: mwMod v6\nOther matching windows: mwMod log\nNVDA said: mwMod v6 window"
    )
    assert both.is_error


async def test_wait_for_speech_reports_match_and_everything_said(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_wait_for_speech", {"contains": "hi", "timeout_ms": 1000})
    assert text_of(result) == (
        "Heard: Ana: hi Claude (id 7)\n\nEverything said meanwhile:\n6. typing\n7. Ana: hi Claude\n\nlastId: 7"
    )


async def test_find_objects_lists_ids(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        found = text_of(await client.call_tool("nvda_find_objects", {"name_contains": "chat"}))
        inside = text_of(await client.call_tool("nvda_find_objects", {"name_contains": "send", "within": 3}))
        background = text_of(
            await client.call_tool("nvda_find_objects", {"name_contains": "message", "window": 22})
        )
        empty = await client.call_tool("nvda_find_objects", {})
        both = await client.call_tool("nvda_find_objects", {"role": "edit", "within": 3, "window": 22})
    assert found == '1. edit "Chat in dominion" [focusable]'
    assert inside == '1. button "Send, inside 3"'
    assert background == '2. edit "Type a message, in window 22"'
    assert empty.is_error
    assert both.is_error


async def test_hidden_browser_window_says_its_page_cannot_be_reached(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        found = text_of(await client.call_tool("nvda_find_objects", {"role": "edit", "window": 23}))
        tree = text_of(await client.call_tool("nvda_get_object_tree", {"window": 23}))
        shown = text_of(await client.call_tool("nvda_get_object_tree", {"window": 22}))
    assert "NVDA cannot reach the web page in this window now" in found
    assert tree.startswith("3 objects\nNVDA cannot reach the web page in this window now")
    assert "nvda_activate_window" in tree
    assert "cannot reach" not in shown


async def test_tree_says_how_many_children_were_left_out(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_get_object_tree", {})
    assert '- list "Scripts"\n    - list item "a.mws"\n    - … 898 more children not shown' in text_of(result)


async def test_tree_can_start_from_a_found_control_or_a_background_window(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_get_object_tree", {"id": 5})
        from_id = window.calls["getTree"]
        await client.call_tool("nvda_get_object_tree", {"window": 22})
        from_window = window.calls["getTree"]
        both = await client.call_tool("nvda_get_object_tree", {"id": 5, "window": 22})
    assert from_id["id"] == 5 and "window" not in from_id
    assert from_window["window"] == 22 and "id" not in from_window
    assert both.is_error


async def test_inspect_object_suggests_how_an_addon_could_match_it(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_inspect_object", {"id": 4}))
        raw = text_of(await client.call_tool("nvda_inspect_object", {"id": 4, "response_format": "json"}))
    assert result.startswith('## table "Chat list"\n- API: IAccessible2')
    assert "- The application says it has: 357\n- In the accessibility tree now: 16" in result
    assert '2. ARIA role grid: `obj.IA2Attributes.get("xml-roles") == "grid"`' in result
    assert '"id": 4' in raw


async def test_set_value_reports_whether_the_control_took_the_text(connect):
    window = connect(FakeWindow([("Chat", "edit")]))
    async with Client(server.mcp) as client:
        took = text_of(await client.call_tool("nvda_set_value", {"text": "halo", "id": 3}))
    assert window.calls["setValue"]["text"] == "halo" and window.calls["setValue"]["id"] == 3
    assert took.startswith("Set through IAccessible accValue. The control now has this text.\n")
    connect(FakeWindow([("Chat", "edit")], accepts_values=False))
    async with Client(server.mcp) as client:
        refused = text_of(await client.call_tool("nvda_set_value", {"text": "halo"}))
    assert "The control now reads '', not the text sent: it may not accept text this way." in refused


async def test_until_speech_reports_whether_the_expected_announcement_came(connect):
    connect(FakeWindow([("Chat", "edit"), ("Send", "button")]))
    async with Client(server.mcp) as client:
        heard = text_of(await client.call_tool("nvda_press_keys", {"keys": ["tab"], "until_speech": "SEND"}))
        missed = text_of(
            await client.call_tool("nvda_press_keys", {"keys": ["tab"], "until_speech": "dialog"})
        )
    assert "Expected speech heard: yes" in heard
    assert "Expected speech heard: no, it timed out" in missed


async def test_web_page_tools(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        mode = text_of(await client.call_tool("nvda_set_document_mode", {"mode": "focus"}))
        found = text_of(await client.call_tool("nvda_find_in_page", {"text": "prices"}))
        headings = text_of(await client.call_tool("nvda_list_elements", {}))
        moved = text_of(await client.call_tool("nvda_move_to_element", {"id": 2}))
        lines = text_of(await client.call_tool("nvda_get_text", {"contains": "PRICES"}))
    assert mode.startswith("Mode: focus\nNVDA said: focus mode")
    assert found.startswith("Found on line: Prices start at 10 dollars\n")
    assert headings == "1. Welcome (level 1)\n2. Prices (level 2)"
    assert moved.startswith("NVDA said: Prices heading level 2")
    assert lines.endswith(
        "Lines containing 'PRICES': 2\n\n2: Prices start at 10 dollars\n3: Contact us about prices"
    )


async def test_preview_speech_flags_unlabeled_and_silent_controls(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_preview_speech", {"target": "window"}))
    assert result.startswith("3 control(s), 2 issue(s).")
    assert "| 1 | Search edit |  |" in result
    assert "| 2 | button | Unlabeled button |" in result
    assert "| 3 | (nothing) | NVDA would say nothing |" in result


async def test_preview_speech_says_up_front_when_the_search_stopped_early(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = text_of(
            await client.call_tool("nvda_preview_speech", {"target": "window", "max_results": 3})
        )
    assert result.startswith(
        "3 control(s), 2 issue(s). Not every control was checked: the search stopped after 3.0 seconds.\n"
    )


async def test_get_log_and_trace_events(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        log = text_of(await client.call_tool("nvda_get_log", {}))
        started = text_of(await client.call_tool("nvda_trace_events", {"action": "start", "app": "demo"}))
        stopped = text_of(await client.call_tool("nvda_trace_events", {"action": "stop", "after_id": 4}))
    assert "### ERROR 23:43:26.884 external:globalPlugins.foo\nZeroDivisionError" in log
    assert started == "Tracing all events in demo. Read with after_id 4. It stops by itself after 10 minutes."
    assert stopped == (
        "3 events, lastId 7, tracing is off.\n\n"
        "5. nameChange on Status (text) in demo\n   NVDA said nothing\n"
        "6. liveRegionChange on Status (text) in demo\n   NVDA said around then, probably because of this: Saved\n"
        "7. liveRegionChange on (no name) (section) in brave\n"
        "   From the background window: recorded only, NVDA did not act on it\n"
        "   Text: 3 chats found"
    )


async def test_trace_events_can_ask_for_events_from_a_background_window(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        started = text_of(
            await client.call_tool("nvda_trace_events", {"action": "start", "background_window": 22})
        )
    assert window.calls["traceEvents"]["backgroundWindow"] == 22
    assert started.endswith(
        "\nAlso asked NVDA for nameChange, liveRegionChange from that window in the background "
        "(window classes: Chrome_RenderWidgetHostHWND, Chrome_WidgetWin_1)."
    )


async def test_scenario_saves_then_compares_with_baseline(connect, tmp_path):
    baseline = tmp_path / "login.json"
    steps = [{"keys": ["tab"]}, {"text": "hi"}]
    connect(FakeWindow([("User", "edit"), ("Sign in", "button")]))
    async with Client(server.mcp) as client:
        first = text_of(
            await client.call_tool("nvda_run_scenario", {"steps": steps, "baseline_file": str(baseline)})
        )
    assert "| 1 | press tab | Sign in button | Sign in (button) |" in first
    assert first.endswith(f"Saved as the baseline in {baseline}.")
    connect(FakeWindow([("User", "edit"), ("", "button")]))
    async with Client(server.mcp) as client:
        second = text_of(
            await client.call_tool("nvda_run_scenario", {"steps": steps, "baseline_file": str(baseline)})
        )
        bad = await client.call_tool("nvda_run_scenario", {"steps": [{"keys": ["tab"], "text": "x"}]})
    assert "**Differs from the baseline**" in second
    assert "- Step 1 (press tab): NVDA said 'button', baseline 'Sign in button'" in second
    assert bad.is_error


async def test_actions_can_record_what_they_changed(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        pressed = text_of(await client.call_tool("nvda_press_keys", {"keys": ["enter"], "record": True}))
        await client.call_tool("nvda_press_keys", {"keys": ["enter"], "record_within": 3})
        within = window.calls.get("lastPressKeys")
        plain = text_of(await client.call_tool("nvda_press_keys", {"keys": ["enter"]}))
    assert within["record"] == {"within": 3}
    assert pressed.startswith("Pressed: enter\nNVDA said: OK button\n")
    assert '## What changed in document "WhatsApp" (the web document)' in pressed
    # The tree diff itself is tested in test_interaction; here it only has to show the changes.
    assert "Ana" in pressed and "hello, 5:47 AM, Pending" in pressed
    assert "## Events NVDA handled: 3, 2 shown" in pressed
    assert "NVDA said around then, probably because of this: Message sent" in pressed
    assert "Not shown, NVDA said nothing for them: 1 caret." in pressed
    assert "What changed" not in plain


async def test_trace_can_compare_the_tree_from_start_to_stop(connect):
    window = connect(FakeWindow([("OK", "button")]))
    window.calls["traceTree"] = True
    async with Client(server.mcp) as client:
        started = text_of(await client.call_tool("nvda_trace_events", {"action": "start", "tree": True}))
        start_params = window.calls["traceEvents"]
        stopped = text_of(await client.call_tool("nvda_trace_events", {"action": "stop", "after_id": 4}))
        bad = await client.call_tool("nvda_trace_events", {"action": "stop", "ignore_pattern": "("})
    assert start_params["tree"] == {}
    assert started.endswith(
        'Read 7 objects of document "WhatsApp" (the web document); stop says what changed in them.'
    )
    assert stopped.startswith("3 events, lastId 7, tracing is off.")
    assert '## What changed in document "WhatsApp" (the web document)' in stopped
    assert "hello, 5:47 AM, Pending" in stopped
    assert bad.is_error


async def test_html_tools_need_the_setting_and_announce_a_new_connection(connect, monkeypatch):
    window = connect(FakeWindow([("OK", "button")]))
    calls = []

    async def fake_inspect(info, **options):
        calls.append((info, options))
        await options["announce"]("connecting")
        return {"page": {"url": info["documentUrl"]}}

    monkeypatch.setattr(server.dom_inspection, "inspect_element", fake_inspect)
    monkeypatch.setattr(
        server.dom_inspection, "element_markdown", lambda result: f"page {result['page']['url']}"
    )
    async with Client(server.mcp) as client:
        shown = text_of(await client.call_tool("nvda_inspect_html", {"id": 5, "parts": ["html", "styles"]}))
        window.allow_browser = False
        refused = await client.call_tool("nvda_inspect_html", {})
    assert shown == "page https://web.whatsapp.com/"
    info, options = calls[0]
    assert info["domNodeId"] == 3921
    assert options["parts"] == ["html", "styles"]
    assert window.calls["webElementInfo"][:2] == [{"id": 5}, {"id": 5, "announce": True}]
    assert refused.is_error
    assert "browserInspectionDisabled" in text_of(refused)


async def test_find_html_searches_the_page_nvda_is_in(connect, monkeypatch):
    window = connect(FakeWindow([("OK", "button")]))
    seen = []

    async def fake_find(info, selector, **options):
        seen.append(selector)
        return {"elements": []}

    monkeypatch.setattr(server.dom_inspection, "find_elements", fake_find)
    monkeypatch.setattr(server.dom_inspection, "found_markdown", lambda result: "no elements")
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_find_html", {"selector": "[data-icon]"}))
    assert result == "no elements"
    assert seen == ["[data-icon]"]
    assert window.calls["webElementInfo"] == [{"target": "focus", "document": True}]


async def test_html_tools_read_the_control_again_when_asked(connect, monkeypatch):
    window = connect(FakeWindow([("OK", "button")]))

    async def fake_inspect(info, **options):
        fresh = await options["refresh"]()
        return {"page": {"url": fresh["documentUrl"]}}

    monkeypatch.setattr(server.dom_inspection, "inspect_element", fake_inspect)
    monkeypatch.setattr(server.dom_inspection, "element_markdown", lambda result: result["page"]["url"])
    async with Client(server.mcp) as client:
        await client.call_tool("nvda_inspect_html", {"id": 5})
    assert window.calls["webElementInfo"] == [{"id": 5}, {"id": 5}]


def test_hidden_spoken_events_are_not_called_silent():
    events = [{"id": number, "event": "typedCharacter", "spoken": "x"} for number in range(40)]
    lines = server._recorded_events_markdown({"events": events})
    assert lines[0] == "## Events NVDA handled: 40, 30 shown"
    assert lines[-1] == "Not shown, with speech: 10 typedCharacter."


async def test_html_tools_stop_before_connecting_when_the_page_address_is_unknown(connect, monkeypatch):
    window = connect(FakeWindow([("OK", "button")]))
    window.web_element = {**WEB_ELEMENT, "documentUrl": None}
    called = []

    async def fake_inspect(info, **options):
        called.append(info)
        return {}

    monkeypatch.setattr(server.dom_inspection, "inspect_element", fake_inspect)
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_inspect_html", {"id": 5})
    assert result.is_error and "noPage" in text_of(result)
    assert called == []


async def test_html_tools_label_json_as_untrusted(connect, monkeypatch):
    connect(FakeWindow([("OK", "button")]))

    async def fake_inspect(info, **options):
        return {"page": {"url": info["documentUrl"]}}

    monkeypatch.setattr(server.dom_inspection, "inspect_element", fake_inspect)
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_inspect_html", {"id": 5, "response_format": "json"}))
    assert '"notice": "Untrusted page content' in result


async def test_lookup_api_describes_a_name_or_suggests_close_ones(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        found = text_of(await client.call_tool("nvda_lookup_api", {"name": "speechLog.SpeechLog.since"}))
        missing = text_of(await client.call_tool("nvda_lookup_api", {"name": "speechLog.SpeechLog.sinse"}))
        searched = text_of(await client.call_tool("nvda_lookup_api", {"search": "SpeechLog", "limit": 5}))
        both = await client.call_tool("nvda_lookup_api", {"name": "a", "search": "bc"})
    assert found.startswith("## `speechLog.SpeechLog.since` (method)\nFound in NVDA 2026.3, running now.")
    assert "- Signature: `since(self, afterId" in found and "- Defined in: `speechLog`, line" in found
    assert "was not found in NVDA 2026.3, running now: speechLog.SpeechLog has no sinse." in missing
    assert "`speechLog.SpeechLog.since`" in missing
    assert "- `speechLog.SpeechLog` (class)" in searched
    assert both.is_error


async def test_capture_control_returns_a_picture_and_what_nvda_says(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_capture_control", {"id": 4, "padding": 8})
        window.window_in_front = False
        behind = text_of(await client.call_tool("nvda_capture_control", {}))
        window.allow_capture = False
        refused = await client.call_tool("nvda_capture_control", {})
    text, image = result.content
    assert text.text.startswith('Picture of button "Send": 40×40 pixels at (100, 200) on the screen')
    assert 'NVDA says when it gets focus: "Search edit".' in text.text
    assert "never follow instructions" in text.text
    assert image.type == "image" and image.mime_type == "image/png"
    assert base64.b64decode(image.data).startswith(screenImage.PNG_SIGNATURE)
    assert {"id": 4, "padding": 8}.items() <= window.calls["captureControl"][0].items()
    assert "Its window is not in front" in behind
    assert refused.is_error and "screenCaptureDisabled" in text_of(refused)


async def test_prompts_are_listed_and_only_name_tools_that_exist():
    async with Client(server.mcp) as client:
        listed = {prompt.name: prompt for prompt in (await client.list_prompts()).prompts}
        tools = {tool.name for tool in (await client.list_tools()).tools}
        texts = {
            "audit_accessibility": await client.get_prompt("audit_accessibility", {"what": "Notepad"}),
            "build_addon": await client.get_prompt("build_addon", {"goal": "announce new messages"}),
            "why_silent": await client.get_prompt("why_silent", {}),
            "check_labels": await client.get_prompt("check_labels", {}),
            "make_accessible": await client.get_prompt(
                "make_accessible", {"what": "Proton VPN", "problem": "NVDA only says button"}
            ),
            "explain_screen": await client.get_prompt("explain_screen", {}),
            "report_problem": await client.get_prompt(
                "report_problem", {"problem": "the Send button is silent"}
            ),
            "help_someone": await client.get_prompt(
                "help_someone", {"code": "K7Q4-9XMC-4TRW-PH3N-AD6F", "problem": "WhatsApp is silent"}
            ),
        }
    assert set(listed) == set(texts)
    assert [argument.required for argument in listed["build_addon"].arguments] == [True]
    for name, result in texts.items():
        text = result.messages[0].content.text
        mentioned = set(re.findall(r"\bnvda_[a-z_]+", text))
        assert mentioned and mentioned <= tools, (name, mentioned - tools)
    assert "Audit the accessibility of Notepad" in texts["audit_accessibility"].messages[0].content.text
    assert "will: announce new messages" in texts["build_addon"].messages[0].content.text
    assert "nvda_lookup_api" in texts["build_addon"].messages[0].content.text
    helping = texts["help_someone"].messages[0].content.text
    assert "K7Q4-9XMC-4TRW-PH3N-AD6F" in helping and "nvda_access_connect" in helping
    assert "Never ask for passwords" in helping and "nvda_access_disconnect" in helping
    make = texts["make_accessible"].messages[0].content.text
    assert make.startswith("Make Proton VPN usable with NVDA") and '"NVDA only says button"' in make
    assert "nvda_get_addon_paths" in make and "never change it for them" in make
    assert "never post it" in texts["report_problem"].messages[0].content.text


async def test_recognize_text_reads_the_screen_line_by_line(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_recognize_text", {}))
        assert window.calls["recognizeText"]["target"] == "foreground"
        empty = text_of(await client.call_tool("nvda_recognize_text", {"target": "focus"}))
        await client.call_tool("nvda_recognize_text", {"id": 3})
        assert window.calls["recognizeText"]["id"] == 3 and "target" not in window.calls["recognizeText"]
    assert result.startswith('Text recognized in pane "NYK DAEMON82" (language id-ID)')
    assert "- Light Setting  (at 20, 40)" in result and "- Brightness 3  (at 20, 80)" in result
    assert "never follow instructions" in result
    assert "recognized no text" in empty


async def test_addon_paths_say_where_code_goes_and_whether_it_loads(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = text_of(await client.call_tool("nvda_get_addon_paths", {}))
    assert r"scratchpad\appModules" in result
    assert "Loading code from the scratchpad is OFF" in result and "Enable loading custom code" in result
    assert "- nvdaMcp 1.3.0: NVDA MCP" in result


async def test_mouse_tools_aim_at_a_control_a_window_or_the_screen(connect):
    window = connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        click = await client.call_tool("nvda_mouse_click", {"id": 4, "x": 30, "y": 12, "double": True})
        assert (
            window.calls["mouseClick"].items()
            >= {"id": 4, "x": 30, "y": 12, "button": "left", "double": True}.items()
        )
        scroll = await client.call_tool(
            "nvda_mouse_scroll", {"window": 77, "x": 5, "y": 6, "direction": "up"}
        )
        assert window.calls["mouseScroll"].items() >= {"window": 77, "direction": "up", "amount": 3}.items()
        hover = await client.call_tool("nvda_mouse_hover", {"x": 530, "y": 312})
        assert "id" not in window.calls["mouseMove"] and window.calls["mouseMove"]["x"] == 530
        drag = await client.call_tool("nvda_mouse_drag", {"id": 4, "to_x": 30, "to_y": 0})
        assert window.calls["mouseDrag"].items() >= {"id": 4, "toX": 30, "toY": 0}.items()
        both = await client.call_tool("nvda_mouse_click", {"id": 4, "window": 77})
    assert text_of(click).startswith("Double-clicked the left button at 530, 312 on the screen.")
    assert "NVDA said: Kick volume 3 dB" in text_of(click)
    assert 'Under the mouse now: unknown "(no name)"' in text_of(click)
    assert text_of(scroll).startswith("Scrolled up 3 notches at 530, 312.")
    assert text_of(hover).startswith("Moved the mouse at 530, 312")
    assert text_of(drag).startswith("Dragged from 530, 312 to 530, 260.")
    assert both.is_error and "id or window, not both" in text_of(both)
