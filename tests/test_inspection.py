import pytest

from nvda_mcp import inspection

# What NVDA reports for WhatsApp Web's chat list in Brave, shortened.
CHAT_LIST = {
    "object": {"name": "Chat list", "role": "table", "appName": "brave"},
    "roleConstant": "TABLE",
    "api": "IAccessible2",
    "nvdaClass": "NVDAObjects.IAccessible.chromium.Table",
    "attributes": {
        "tag": "div",
        "xml-roles": "grid",
        "name-from": "attribute",
        "rowcount": "357",
        "class": "x1n2onr6 xjb2p0i xk390pu xeuugli",
    },
    "ancestors": [
        {"role": "document", "name": "WhatsApp", "attributes": {"tag": "#document"}},
        {"role": "region", "name": "Chats", "attributes": {"tag": "div", "xml-roles": "region"}},
    ],
    "children": {"count": 16, "first": [{"role": "row", "name": "3 unread messages Rafli 5:47 AM hai hai"}]},
    "table": {"loadedRows": 16, "rowCount": 357},
}


@pytest.mark.parametrize("token", ["x1n2onr6", "xjb2p0i", "xeuugli", "css-1x2y3z", "Button_root__3xk9a"])
def test_build_tool_class_names_look_generated(token):
    assert inspection.looks_generated_class(token)


@pytest.mark.parametrize("token", ["tiptap", "ProseMirror", "h1", "col-12", "mt-4", "message-in"])
def test_hand_written_class_names_do_not(token):
    assert not inspection.looks_generated_class(token)


@pytest.mark.parametrize("value", [":r1:", "«r1»", "_r_f_", "_R_2kd_", "mui-12345", "mount_0_0_VM"])
def test_generated_ids_are_recognized(value):
    assert inspection.looks_generated_id(value)


@pytest.mark.parametrize("value", ["main", "side", "app", "pane-side", "rich_text"])
def test_hand_written_ids_are_not(value):
    assert not inspection.looks_generated_id(value)


def test_state_classes_are_recognized():
    assert inspection.is_state_class("ProseMirror-focused")
    assert not inspection.is_state_class("ProseMirror")


def test_chat_list_is_matched_on_role_aria_role_and_label_not_classes():
    conditions, avoid = inspection.suggest(CHAT_LIST)
    assert [condition.expression for condition in conditions[:3]] == [
        "obj.role == controlTypes.Role.TABLE",
        'obj.IA2Attributes.get("xml-roles") == "grid"',
        'obj.name == "Chat list"',
    ]
    assert not any("class" in condition.expression for condition in conditions)
    assert any("4 class name(s) that look generated" in item for item in avoid)
    # The tag div is listed, but too common to put in the example code next to better conditions.
    assert 'IA2Attributes.get("tag")' not in inspection.overlay_code(conditions, "IAccessible2")


def test_names_made_from_changing_content_are_avoided():
    row = {
        "object": {"name": "3 unread messages Rafli 5:47 AM hai hai", "role": "row"},
        "roleConstant": "TABLEROW",
        "attributes": {"name-from": "contents", "xml-roles": "row"},
    }
    conditions, avoid = inspection.suggest(row)
    assert not any(condition.expression.startswith("obj.name") for condition in conditions)
    assert any("made from the text inside" in item for item in avoid)


def test_markdown_explains_the_virtual_list_and_gives_overlay_code():
    text = inspection.to_markdown(CHAT_LIST)
    assert '- Inside: document "WhatsApp" [<#document>] › region "Chats" [<div>, xml-roles=region]' in text
    assert "- class: x1n2onr6 xjb2p0i xk390pu xeuugli (4 classes, 4 look generated)" in text
    assert "- The application says it has: 357\n- In the accessibility tree now: 16\n" in text
    assert "created only when scrolled into view" in text
    assert "from NVDAObjects.IAccessible import IAccessible" in text
    assert (
        "\t\tif (\n\t\t\tisinstance(obj, IAccessible)\n\t\t\tand obj.role == controlTypes.Role.TABLE\n"
        '\t\t\tand obj.IA2Attributes.get("xml-roles") == "grid"\n'
    ) in text


def test_react_ids_are_avoided():
    # WhatsApp Web's search box, as NVDA reported it.
    search_box = {
        "object": {"name": "Search or start a new chat", "role": "edit"},
        "roleConstant": "EDITABLETEXT",
        "api": "IAccessible2",
        "attributes": {"tag": "input", "id": "_r_f_", "xml-roles": "textbox", "name-from": "attribute"},
    }
    conditions, avoid = inspection.suggest(search_box)
    assert not any("_r_f_" in condition.expression for condition in conditions)
    assert any('the HTML id "_r_f_"' in item for item in avoid)


def test_desktop_controls_use_automation_id_and_window_class():
    button = {
        "object": {"name": "Save", "role": "button", "windowClassName": "Button"},
        "roleConstant": "BUTTON",
        "api": "UIA",
        "uia": {"automationId": "SaveButton"},
    }
    conditions, _ = inspection.suggest(button)
    expressions = [condition.expression for condition in conditions]
    assert 'obj.UIAAutomationId == "SaveButton"' in expressions
    assert 'obj.windowClassName == "Button"' in expressions
    assert "isinstance(obj, UIA)" in inspection.overlay_code(conditions, "UIA")


def test_names_with_spaces_around_them_are_compared_stripped():
    archived = {
        "object": {"name": "Archived ", "role": "button"},
        "roleConstant": "BUTTON",
        "attributes": {"tag": "button", "name-from": "attribute"},
    }
    conditions, _ = inspection.suggest(archived)
    assert conditions[1].expression == '(obj.name or "").strip() == "Archived"'
    assert "spaces around it" in conditions[1].why
