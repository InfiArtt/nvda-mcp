from contextText import INTRODUCTION, contextText, speechInWindow, treeLines


def test_context_describes_where_the_user_is_for_any_ai_chat():
    status = {"foregroundApp": "protonvpn", "foregroundWindow": "Proton VPN", "documentMode": None}
    focus = {
        "name": "",
        "role": "button",
        "states": ["focusable", "focused"],
        "ancestors": ["Proton VPN (window)"],
    }
    tree = {
        "tree": {
            "role": "window",
            "name": "Proton VPN",
            "children": [{"role": "button"}, {"role": "edit", "name": "Search", "value": "Japan"}],
        }
    }
    text = contextText(status, focus, tree, ["", "button", "Search edit Japan"])
    assert text.startswith(INTRODUCTION)
    assert 'Application: protonvpn, window "Proton VPN"' in text
    assert "Focus is on: button [focusable, focused]" in text
    assert "Inside: Proton VPN (window)" in text
    assert '  - edit "Search" value: Japan' in text
    assert text.endswith("What NVDA said in this window, oldest first:\n- button\n- Search edit Japan")


def test_context_without_a_tree_or_speech_still_says_where_focus_is():
    text = contextText({}, {"role": "pane", "name": "NYK"}, None, [])
    assert 'Focus is on: pane "NYK"' in text
    assert "Controls in this window" not in text and "What NVDA said" not in text


def test_long_trees_are_cut_with_a_note():
    tree = {
        "role": "list",
        "children": [{"role": "list item", "name": str(n)} for n in range(10)],
        "moreChildren": 90,
    }
    lines = treeLines(tree, maxLines=4)
    assert lines[-1] == "(The list was cut short here.)"
    assert len(lines) == 6 and lines[-2] == "  - ... and 90 more"


def test_common_states_can_be_left_out():
    focus = {"role": "edit", "name": "Chat", "states": ["focusable", "focused", "multi line"]}
    tree = {
        "tree": {"role": "list item", "name": "a.mws", "states": ["focusable", "selectable", "off screen"]}
    }
    text = contextText({}, focus, tree, [], frozenset({"focusable", "selectable", "off screen"}))
    assert 'Focus is on: edit "Chat" [focused, multi line]' in text
    assert '- list item "a.mws"' in text and "selectable" not in text


def test_speech_starts_where_nvda_announced_the_window():
    speech = [
        "Input gestures dialog",
        "OK button",
        "mwMod v6 window",
        "",
        "Chat edit",
        "mwMod v6 window",
        "list",
    ]
    assert speechInWindow(speech, "mwMod v6") == ["mwMod v6 window", "list"]
    assert speechInWindow(speech, "Notepad") == [text for text in speech if text]


def test_lists_of_unknown_length_say_only_that_more_were_left_out():
    tree = {"role": "list", "children": [{"role": "list item", "name": "a"}], "moreChildren": True}
    assert treeLines(tree)[-1] == "  - ... and more"


def test_lists_say_how_many_earlier_children_were_left_out():
    tree = {
        "role": "list",
        "name": "Chat",
        "childrenBefore": 655,
        "children": [{"role": "list item", "name": "hi"}],
    }
    assert treeLines(tree) == ['- list "Chat"', "  - ... 655 earlier not shown", '  - list item "hi"']


def test_application_falls_back_to_the_focus_when_nvda_does_not_know_it_yet():
    text = contextText({"foregroundWindow": "mwMod"}, {"role": "edit", "appName": "mwmod"}, None, [])
    assert 'Application: mwmod, window "mwMod"' in text
