"""Runs the real MCP server against the real add-on bridge, with NVDA replaced by a scripted window."""

import pytest
from bridge import Bridge, BridgeError
from mcp import Client
from speechLog import SpeechLog

from nvda_mcp import server
from nvda_mcp.bridge_client import BridgeClient

pytestmark = pytest.mark.anyio


class FakeWindow:
    """A window with a fixed tab order that speaks like NVDA when focus moves."""

    def __init__(self, controls, allow_control=True):
        self.controls = controls
        self.index = 0
        self.allow_control = allow_control
        self.speech = SpeechLog(maxEntries=100)

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
        return result

    def speak_after_action(self, text, params):
        start = self.speech.lastId
        self.speech.add(text)
        return self.result(start, params)

    def type_text(self, params):
        start = self.speech.lastId
        self.typed = params["text"]
        self.speech.add(params["text"])
        return {"speech": [entry.toDict() for entry in self.speech.since(start)], "focus": self.focus()}

    def handlers(self):
        return {
            "typeText": self.type_text,
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
                "objects": [{"id": 1, "name": "Chat in dominion", "role": "edit", "states": ["focusable"]}],
                "truncated": None,
            },
            "getTree": lambda params: {
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
            },
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
            "traceEvents": lambda params: (
                {"afterId": 4, "stopsAfterSeconds": 600}
                if params["action"] == "start"
                else {
                    "tracing": params["action"] != "stop",
                    "lastId": 6,
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
                    ],
                }
            ),
            "getFocus": self.focus,
            "getSpeech": lambda params: {
                "lastId": self.speech.lastId,
                "entries": [
                    e.toDict() for e in self.speech.since(params.get("afterId", 0), params.get("limit"))
                ],
            },
            "pressKeys": self.press_keys,
            "speak": lambda params: self.speech.add(params["text"]) or {"spoken": params["text"]},
        }


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
        empty = await client.call_tool("nvda_find_objects", {})
    assert found == '1. edit "Chat in dominion" [focusable]'
    assert empty.is_error


async def test_tree_says_how_many_children_were_left_out(connect):
    connect(FakeWindow([("OK", "button")]))
    async with Client(server.mcp) as client:
        result = await client.call_tool("nvda_get_object_tree", {})
    assert '- list "Scripts"\n    - list item "a.mws"\n    - … 898 more children not shown' in text_of(result)


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
        "2 events, lastId 6, tracing is off.\n\n"
        "5. nameChange on Status (text) in demo\n   NVDA said nothing\n"
        "6. liveRegionChange on Status (text) in demo\n   NVDA said around then, probably because of this: Saved"
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
