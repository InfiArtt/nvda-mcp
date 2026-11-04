import copy
import json

import pytest

from nvda_mcp import interaction, scenario
from nvda_mcp.interaction import Change, TreeDiff, changes_markdown, diff_snapshots

CLOCK = r"\d{1,2}:\d{2} [AP]M"


def node(role, name="", key=None, children=None, **extra):
    """One object as the add-on reports it; children get their index from their place."""
    data = {"key": key, "role": role}
    if name:
        data["name"] = name
    if children is not None:
        data["children"] = [
            dict(child, index=child.get("index", index)) for index, child in enumerate(children)
        ]
        data["childCount"] = len(children)
    data.update(extra)
    return data


def long_list(role, name, key, head, tail, child_count):
    """A list read with its middle skipped: head from the start, tail from the end."""
    children = [dict(child, index=index) for index, child in enumerate(head)]
    children += [dict(child, index=index - len(tail)) for index, child in enumerate(tail)]
    return node(role, name, key, cut="gap") | {"children": children, "childCount": child_count}


def count(tree):
    return 1 + sum(count(child) for child in tree.get("children", []))


def snapshot(tree, truncated=None, **extra):
    tree = dict(tree, index=0)
    return {"nodeCount": count(tree), "truncated": truncated, "tree": tree, **extra}


def without_keys(data):
    """The same snapshot as an application without accessible ids would give."""
    data = copy.deepcopy(data)
    stack = [data["tree"]]
    while stack:
        current = stack.pop()
        current["key"] = None
        stack.extend(current.get("children", []))
    return data


def chat_row(number, name):
    """A row of WhatsApp Web's chat list, "Ana, 5:47 AM, hello", with a cell for each part."""
    parts = name.split(", ", 2)
    cells = [node("cell", part, f"ia2:100:-{1000 * number + index}") for index, part in enumerate(parts, 1)]
    return node("row", name, f"ia2:100:-{number}", cells)


def message(number, text):
    return node("list item", text, f"ia2:100:-{500 + number}")


CHATS = [
    (1, "Ana, 5:47 AM, hello"),
    (2, "Bob, 5:40 AM, see you"),
    (3, "Cid, Yesterday, ok"),
    (4, "Dan, Monday, photo"),
]
MESSAGES = [message(number, f"Ana: message {number}") for number in range(1, 4)]
# document, chat list, 4 rows of 3 cells, message list with 3 messages, compose box.
WHATSAPP_OBJECTS = 23


def whatsapp(chats=CHATS, messages=MESSAGES, compose=None, extra=()):
    """WhatsApp Web as the add-on snapshots it: chat list, messages and the compose box."""
    compose_box = node("edit", "Type a message", "ia2:100:-903", **({"value": compose} if compose else {}))
    children = [
        node("table", "Chat list", "ia2:100:-901", [chat_row(number, name) for number, name in chats]),
        node("list", "Messages", "ia2:100:-902", messages),
        compose_box,
        *extra,
    ]
    return snapshot(node("document", "WhatsApp", "ia2:100:-900", children))


def chats(names, first=1):
    return [(number, name) for number, name in enumerate(names, first)]


def numbered_chats(numbers):
    return [(number, f"Chat {number}, 5:47 AM, hello") for number in numbers]


def chat_list(snap):
    return snap["tree"]["children"][0]


def kinds(diff):
    return [change.kind for change in diff.changes]


def summary(diff):
    return [(change.kind, change.subject, change.detail) for change in diff.changes]


def located(diff):
    return [(change.context, change.kind, change.subject, change.detail) for change in diff.changes]


def of_kind(diff, kind):
    return [change for change in diff.changes if change.kind == kind]


# Basics


def test_identical_snapshots_have_no_changes():
    diff = diff_snapshots(whatsapp(), whatsapp())
    assert diff.changes == []
    assert diff.not_compared == []
    assert not diff.root_gone
    assert diff.before_count == diff.after_count == diff.matched == diff.matched_by_key == WHATSAPP_OBJECTS
    assert changes_markdown(diff) == ["No changes in the tree."]


def test_identical_snapshots_without_ids_match_by_structure():
    diff = diff_snapshots(without_keys(whatsapp()), without_keys(whatsapp()))
    assert diff.changes == [] and diff.not_compared == []
    assert diff.matched == WHATSAPP_OBJECTS
    assert diff.matched_by_key == 0


def test_renamed_row_keeps_its_place():
    after = whatsapp([CHATS[0], (2, "Bob, 6:02 AM, on my way"), *CHATS[2:]])
    diff = diff_snapshots(whatsapp(), after)
    assert located(diff) == [
        ('table "Chat list"', "renamed", 'row "Bob, 5:40 AM, see you"', 'to "Bob, 6:02 AM, on my way"'),
        ('row "Bob, 6:02 AM, on my way"', "renamed", 'cell "5:40 AM"', 'to "6:02 AM"'),
        ('row "Bob, 6:02 AM, on my way"', "renamed", 'cell "see you"', 'to "on my way"'),
    ]


def test_renamed_row_without_ids_is_paired_by_a_similar_name():
    after = whatsapp([CHATS[0], (2, "Bob, 6:02 AM, see you!"), *CHATS[2:]])
    diff = diff_snapshots(without_keys(whatsapp()), without_keys(after))
    assert kinds(diff) == ["renamed", "renamed", "renamed"]
    assert not of_kind(diff, "added") and not of_kind(diff, "removed")


def test_chat_moving_to_the_top_is_one_move():
    after = whatsapp([(4, "Dan, 6:10 AM, hi"), *CHATS[:3]])
    diff = diff_snapshots(whatsapp(), after)
    moves = of_kind(diff, "moved")
    assert [(move.subject, move.detail) for move in moves] == [
        ('row "Dan, 6:10 AM, hi"', "from position 4 to 1")
    ]
    assert not of_kind(diff, "added") and not of_kind(diff, "removed")


def test_new_row_at_the_top_is_added_without_moves():
    after = whatsapp([(5, "Eve, 6:00 AM, hey"), *CHATS])
    diff = diff_snapshots(whatsapp(), after)
    assert summary(diff) == [
        ("added", 'row "Eve, 6:00 AM, hey"', '(3 objects inside, such as "Eve", "6:00 AM", "hey")')
    ]
    assert diff.changes[0].context == 'table "Chat list"'


def test_removed_subtree_is_reported_once_with_its_size():
    diff = diff_snapshots(whatsapp(), whatsapp(CHATS[:3]))
    assert summary(diff) == [
        ("removed", 'row "Dan, Monday, photo"', '(3 objects inside, such as "Dan", "Monday", "photo")')
    ]


def test_removing_an_object_whose_contents_were_not_read_says_so():
    before = whatsapp()
    row = chat_list(before)["children"][3]
    del row["children"]
    row["cut"] = "depth"
    diff = diff_snapshots(before, whatsapp(CHATS[:3]))
    assert summary(diff) == [("removed", 'row "Dan, Monday, photo"', "(contents not read)")]


def test_value_change():
    diff = diff_snapshots(whatsapp(), whatsapp(compose="hello"))
    assert located(diff) == [
        ('document "WhatsApp"', "value", 'edit "Type a message"', 'from (empty) to "hello"')
    ]


def test_description_and_role_changes():
    before = snapshot(node("group", "Main", None, [node("link", "Send", "ia2:1:-1", description="old hint")]))
    after = snapshot(
        node("group", "Main", None, [node("button", "Send", "ia2:1:-1", description="new hint")])
    )
    assert summary(diff_snapshots(before, after)) == [
        ("role", 'link "Send"', "changed to button"),
        ("description", 'button "Send"', 'from "old hint" to "new hint"'),
    ]


# States


def test_states_gained_and_lost():
    before = whatsapp()
    chat_list(before)["children"][0]["states"] = ["selected"]
    after = whatsapp()
    chat_list(after)["children"][1]["states"] = ["selected"]
    assert summary(diff_snapshots(before, after)) == [
        ("states", 'row "Ana, 5:47 AM, hello"', "no longer selected"),
        ("states", 'row "Bob, 5:40 AM, see you"', "now selected"),
    ]


def test_states_inherited_from_the_parent_are_dropped():
    after = whatsapp()
    row = chat_list(after)["children"][1]
    row["states"] = ["off screen"]
    for cell in row["children"]:
        cell["states"] = ["off screen"]
    row["children"][2]["states"] = ["off screen", "selected"]
    assert summary(diff_snapshots(whatsapp(), after)) == [
        ("states", 'row "Bob, 5:40 AM, see you"', "now off screen"),
        ("states", 'cell "see you"', "now off screen, selected"),
    ]


def test_focused_is_not_a_state_change():
    after = whatsapp()
    after["tree"]["children"][2]["focused"] = True
    after["tree"]["children"][2]["states"] = ["focused"]
    assert diff_snapshots(whatsapp(), after).changes == []


# Text normalisation


def test_ignore_pattern_hides_clock_changes():
    # WhatsApp writes a narrow no-break space before AM; the pattern has a plain space.
    after = whatsapp([(1, "Ana, 5:48\u202fAM, hello"), *CHATS[1:]])
    assert kinds(diff_snapshots(whatsapp(), after)) == ["renamed", "renamed"]
    assert diff_snapshots(whatsapp(), after, ignore=CLOCK).changes == []


def test_ignore_pattern_still_shows_other_changes_with_the_real_text():
    after = whatsapp([(1, "Ana, 5:48 AM, bye"), *CHATS[1:]])
    diff = diff_snapshots(whatsapp(), after, ignore=CLOCK)
    assert summary(diff) == [
        ("renamed", 'row "Ana, 5:47 AM, hello"', 'to "Ana, 5:48 AM, bye"'),
        ("renamed", 'cell "hello"', 'to "bye"'),
    ]


def test_whitespace_differences_are_not_changes():
    after = whatsapp([(1, "Ana,  5:47 AM,\nhello "), *CHATS[1:]])
    chat_list(after)["children"][0]["children"] = chat_list(whatsapp())["children"][0]["children"]
    assert diff_snapshots(whatsapp(), after).changes == []


def test_shared_normaliser_collapses_whitespace_only_when_asked():
    # Scenarios keep comparing text exactly as before.
    assert scenario.text_normaliser(r"\d+:\d+")("at  10:30") == "at  …"
    assert scenario.text_normaliser(None)("a  b") == "a  b"
    assert scenario.text_normaliser(r"\d AM", collapse_whitespace=True)(" 5\u202fAM \n hi ") == "… hi"


def test_long_names_show_only_the_changed_part():
    old = "Ana: " + "a long message about the weekend plans " * 3 + "see you at 5 tomorrow"
    new = old.replace("at 5", "at 6")
    before = snapshot(node("list", "Messages", None, [node("list item", old, "ia2:100:-1")]))
    after = snapshot(node("list", "Messages", None, [node("list item", new, "ia2:100:-1")]))
    assert summary(diff_snapshots(before, after)) == [
        ("renamed", 'list item "…ans see you at 5 tomorrow"', 'to "…ans see you at 6 tomorrow"')
    ]


def test_long_values_show_the_changed_part_with_context_on_both_sides():
    old = "x" * 40 + " the middle part " + "y" * 40
    new = old.replace("middle", "centre")
    before = snapshot(node("edit", "Message", "ia2:1:-1", value=old))
    after = snapshot(node("edit", "Message", "ia2:1:-1", value=new))
    (change,) = diff_snapshots(before, after).changes
    # 15 characters on each side of what changed; "middle" and "centre" both end in "e".
    assert (
        change.detail
        == 'from "…xxxxxxxxxx the middle part yyyyyyyy…" to "…xxxxxxxxxx the centre part yyyyyyyy…"'
    )


# Long lists read with their middle skipped


def chat_pane(head, tail, child_count, keyed=True):
    def item(number):
        return message(number, f"message {number}") if keyed else node("list item", f"message {number}")

    messages = long_list(
        "list", "Messages", "ia2:100:-902", [item(n) for n in head], [item(n) for n in tail], child_count
    )
    return snapshot(node("document", "WhatsApp", "ia2:100:-900", [messages, node("edit", "Type a message")]))


@pytest.mark.parametrize("keyed", [True, False])
def test_message_appended_to_a_long_list_is_added(keyed):
    before = chat_pane([1, 2, 3], [48, 49, 50], 50, keyed)
    after = chat_pane([1, 2, 3], [49, 50, 51], 51, keyed)
    diff = diff_snapshots(before, after)
    assert summary(diff) == [("added", 'list item "message 51"', "")]
    # Message 48 is now in the part that was not read: it may still be there.
    assert diff.not_compared == [
        (
            '1 object in list "Messages" read only before (list item "message 48"): '
            "that part was not read completely after, so it may still be there."
        )
    ]


def test_unchanged_long_list_has_no_changes_and_no_notes():
    diff = diff_snapshots(chat_pane([1, 2, 3], [48, 49, 50], 50), chat_pane([1, 2, 3], [48, 49, 50], 50))
    assert diff.changes == [] and diff.not_compared == []


def test_new_children_in_the_unread_middle_are_counted():
    diff = diff_snapshots(chat_pane([1, 2, 3], [48, 49, 50], 50), chat_pane([1, 2, 3], [48, 49, 50], 53))
    assert summary(diff) == [("child count", "", "3 more children than before (not read)")]


def test_objects_next_to_the_unread_middle_are_not_compared():
    # A message was inserted near the start: message 3 moved into the unread middle and message 4 is new there.
    diff = diff_snapshots(chat_pane([1, 2, 3], [48, 49, 50], 50), chat_pane([1, 2, 4], [48, 49, 50], 50))
    assert diff.changes == []
    assert len(diff.not_compared) == 2
    assert 'read only before (list item "message 3")' in diff.not_compared[0]
    assert 'read only after (list item "message 4")' in diff.not_compared[1]


def test_focused_child_kept_in_the_unread_middle_does_not_prove_a_removal():
    def pane(third, focus_index):
        children = [
            dict(message(1, "m1"), index=0),
            dict(message(2, "m2"), index=1),
            dict(third, index=2),
            dict(message(9, "focused message"), index=focus_index, focused=True),
            dict(message(10, "m99"), index=-2),
            dict(message(11, "m100"), index=-1),
        ]
        return snapshot(
            node("list", "Messages", "ia2:100:-902", cut="gap", childCount=100) | {"children": children}
        )

    # Between m2 and the focused message only one of the many messages was read each time.
    diff = diff_snapshots(pane(message(3, "m3"), 30), pane(message(4, "new"), 31))
    assert not of_kind(diff, "removed") and not of_kind(diff, "added")
    assert len(diff.not_compared) == 2


@pytest.mark.parametrize("reverse", [False, True])
def test_list_read_whole_is_compared_with_its_head_and_tail(reverse):
    items = [node("list item", f"message {number}") for number in range(1, 11)]
    with_gap = snapshot(long_list("list", "Messages", None, items[:2], items[-2:], 10))
    whole = snapshot(node("list", "Messages", None, items))
    diff = diff_snapshots(whole, with_gap) if reverse else diff_snapshots(with_gap, whole)
    assert diff.changes == []
    side = "before" if reverse else "after"
    assert diff.not_compared == [
        f'6 objects in list "Messages" read only {side} (list item "message 3", list item "message 4", '
        f'list item "message 5" and 3 more): that part was not read completely {"after" if reverse else "before"}, '
        + ("so they may still be there." if reverse else "so they may have been there already.")
    ]


def test_moves_are_found_from_the_end_of_a_long_list():
    before = chat_pane([1, 2], [47, 48, 49, 50], 50)
    after = chat_pane([1, 2], [48, 49, 50, 47], 50)
    assert summary(diff_snapshots(before, after)) == [
        ("moved", 'list item "message 47"', "from position 4 from the end to 1 from the end")
    ]


# Scrolling and virtual lists


def test_full_page_scroll_with_no_rows_kept_is_one_line():
    before, after = whatsapp(numbered_chats(range(1, 9))), whatsapp(numbered_chats(range(9, 17)))
    diff = diff_snapshots(before, after)
    # The names are similar, but rows with different ids are never taken for renamed ones.
    assert summary(diff) == [
        (
            "replaced",
            "",
            (
                "all 8 read items are different (scrolled or reloaded); "
                'before "Chat 1, 5:47 AM, hello" to "Chat 8, 5:47 AM, hello", '
                'after "Chat 9, 5:47 AM, hello" to "Chat 16, 5:47 AM, hello"'
            ),
        )
    ]
    assert diff.changes[0].context == 'table "Chat list"'


def test_full_page_scroll_without_ids_looks_like_rows_renamed_in_place():
    # Without accessible ids, rows with similar names in the same places can only be taken for renamed ones.
    before, after = whatsapp(numbered_chats(range(1, 9))), whatsapp(numbered_chats(range(9, 17)))
    diff = diff_snapshots(without_keys(before), without_keys(after))
    assert diff.changes[0] == Change(
        "renamed",
        'table "Chat list"',
        "8 row objects",
        count=8,
        examples=[
            'row "Chat 1, 5:47 AM, hello" to "Chat 9, 5:47 AM, hello"',
            'row "Chat 2, 5:47 AM, hello" to "Chat 10, 5:47 AM, hello"',
            'row "Chat 3, 5:47 AM, hello" to "Chat 11, 5:47 AM, hello"',
        ],
    )
    assert set(kinds(diff)) == {"renamed"}


@pytest.mark.parametrize("keyed", [True, False])
def test_partial_scroll_is_one_line(keyed):
    before, after = whatsapp(numbered_chats(range(1, 9))), whatsapp(numbered_chats(range(3, 11)))
    if not keyed:
        before, after = without_keys(before), without_keys(after)
    assert summary(diff_snapshots(before, after)) == [
        (
            "scrolled",
            "",
            (
                '2 left at the start ("Chat 1, 5:47 AM, hello" to "Chat 2, 5:47 AM, hello"), '
                '2 came in at the end ("Chat 9, 5:47 AM, hello" to "Chat 10, 5:47 AM, hello")'
            ),
        )
    ]
    assert summary(diff_snapshots(after, before)) == [
        (
            "scrolled",
            "",
            (
                '2 left at the end ("Chat 9, 5:47 AM, hello" to "Chat 10, 5:47 AM, hello"), '
                '2 came in at the start ("Chat 1, 5:47 AM, hello" to "Chat 2, 5:47 AM, hello")'
            ),
        )
    ]


def test_scroll_is_not_claimed_when_the_end_was_not_read_before():
    before = whatsapp(numbered_chats(range(1, 9)))
    chat_list(before)["cut"] = "nodes"
    diff = diff_snapshots(before, whatsapp(numbered_chats(range(3, 11))))
    # The list was read whole after, so the first two rows are gone; the last two may have been there unread.
    assert [(change.kind, change.subject) for change in diff.changes] == [
        ("removed", 'row "Chat 1, 5:47 AM, hello"'),
        ("removed", 'row "Chat 2, 5:47 AM, hello"'),
    ]
    assert diff.not_compared == [
        (
            '2 objects in table "Chat list" read only after (row "Chat 9, 5:47 AM, hello", '
            'row "Chat 10, 5:47 AM, hello"): that part was not read completely before, '
            "so they may have been there already."
        )
    ]


def test_recycled_rows_are_one_reused_change():
    names = [f"Chat {number}, 5:47 AM, hello" for number in range(1, 11)]
    before = whatsapp(chats(names[:8]))
    after = whatsapp(chats(names[2:10]))
    diff = diff_snapshots(before, after)
    assert summary(diff) == [
        ("reused", "8 row objects", "now show other content, likely scrolled by 2 toward the end")
    ]
    assert diff.matched_by_key == diff.matched


def test_rows_renamed_with_new_content_are_not_reused():
    before = whatsapp(numbered_chats(range(1, 8)))
    after = whatsapp([(number, f"Chat {number}, 5:47 AM, bye") for number in range(1, 8)])
    diff = diff_snapshots(before, after)
    assert not of_kind(diff, "reused")
    (merged,) = [change for change in diff.changes if change.context == 'table "Chat list"']
    assert (merged.kind, merged.subject, merged.count) == ("renamed", "7 row objects", 7)


# Matching objects without ids, recreated objects and wrappers


def unnamed_row(*cells):
    return node("row", "", None, [node("cell", text) for text in cells])


def test_unnamed_rows_are_matched_by_what_they_contain():
    rows = [
        unnamed_row("Ana", "hello"),
        unnamed_row("Bob", "see you"),
        unnamed_row("Cid", "ok"),
        unnamed_row("Dan", "hi"),
    ]
    before = snapshot(node("table", "Chat list", None, rows))
    after = snapshot(node("table", "Chat list", None, rows[:1] + rows[2:]))
    assert summary(diff_snapshots(before, after)) == [
        ("removed", "row (no name)", '(2 objects inside, such as "Bob", "see you")')
    ]


def test_context_of_an_unnamed_parent_names_its_named_ancestor():
    rows = [
        node("row", "", f"ia2:1:-{number}", [node("cell", name, f"ia2:1:-{number}0")])
        for number, name in CHATS
    ]
    renamed = copy.deepcopy(rows)
    renamed[1]["children"][0]["name"] = "Bob!"
    diff = diff_snapshots(
        snapshot(node("table", "Chat list", None, rows)), snapshot(node("table", "Chat list", None, renamed))
    )
    assert [(change.context, change.subject) for change in diff.changes] == [
        ('row (no name) in table "Chat list"', 'cell "Bob, 5:40 AM, see you"')
    ]


def test_recreated_object_is_reported_once():
    after = whatsapp([CHATS[0], (22, CHATS[1][1]), *CHATS[2:]])
    diff = diff_snapshots(whatsapp(), after)
    assert summary(diff) == [
        ("recreated", 'row "Bob, 5:40 AM, see you"', "as a new accessible object, with 3 objects inside")
    ]


def test_objects_with_different_ids_and_other_names_are_not_recreated():
    after = whatsapp([CHATS[0], (22, "Eve, 6:00 AM, hey"), *CHATS[2:]])
    diff = diff_snapshots(whatsapp(), after)
    assert sorted(kinds(diff)) == ["added", "removed"]


@pytest.mark.parametrize("keyed", [True, False])
def test_wrapper_flip_is_one_exposed_or_unexposed_change(keyed):
    rows = [chat_row(number, name) for number, name in CHATS[:3]]
    flat = snapshot(node("list", "Chats", "ia2:100:-901", rows))
    wrapped = snapshot(
        node("list", "Chats", "ia2:100:-901", [node("grouping", "Pinned", "ia2:100:-950", rows)])
    )
    if not keyed:
        flat, wrapped = without_keys(flat), without_keys(wrapped)
    diff = diff_snapshots(flat, wrapped)
    assert located(diff) == [('list "Chats"', "exposed", 'grouping "Pinned"', "now wraps its 3 items")]
    assert summary(diff_snapshots(wrapped, flat)) == [
        ("unexposed", 'grouping "Pinned"', "no longer wraps its 3 items")
    ]


def test_object_moved_to_another_parent():
    before = whatsapp(extra=[node("list", "Archived", "ia2:100:-904", [])])
    after = whatsapp(CHATS[:3], extra=[node("list", "Archived", "ia2:100:-904", [chat_row(*CHATS[3])])])
    diff = diff_snapshots(before, after)
    assert located(diff) == [
        ('list "Archived"', "moved here", 'row "Dan, Monday, photo"', 'from table "Chat list"')
    ]


def test_duplicate_ids_do_not_pair_by_id_but_still_match():
    before = snapshot(
        node("window", "App", "hwnd:5", [node("pane", "One", "hwnd:7"), node("pane", "Two", "hwnd:7")])
    )
    diff = diff_snapshots(before, copy.deepcopy(before))
    assert diff.changes == []
    assert (diff.matched, diff.matched_by_key) == (3, 1)


# Parts that were not read


def test_dead_root_compares_nothing():
    diff = diff_snapshots(whatsapp(), dict(whatsapp(CHATS[:1]), alive=False))
    assert diff.root_gone
    assert diff.changes == [] and diff.matched == 0
    assert diff.not_compared == [interaction.ROOT_GONE_NOTE]
    assert changes_markdown(diff) == [
        (
            "The recorded object no longer exists (it is gone or was replaced, for example by a page reload), "
            "so nothing was compared."
        )
    ]


def test_replaced_root_with_another_id_compares_nothing():
    diff = diff_snapshots(whatsapp(), snapshot(node("unknown", "", "ia2:100:-77")))
    assert diff.root_gone and diff.changes == []
    assert diff.before_count == WHATSAPP_OBJECTS and diff.after_count == 1


def test_dead_root_without_an_id_is_not_a_removal_of_everything():
    diff = diff_snapshots(whatsapp(), snapshot(node("unknown")))
    assert diff.root_gone and diff.changes == []
    # An empty root that is still the same object is compared as usual.
    empty = snapshot(node("document", "WhatsApp", "ia2:100:-900", []))
    assert kinds(diff_snapshots(whatsapp(), empty)) == ["removed", "removed", "removed"]


@pytest.mark.parametrize("cut", ["error", "nodes", "time", "nesting"])
def test_incomplete_after_parent_hides_removals(cut):
    after = whatsapp()
    chat_list(after)["children"] = chat_list(after)["children"][:2]
    chat_list(after)["cut"] = cut
    diff = diff_snapshots(whatsapp(), after)
    assert diff.changes == []
    assert diff.not_compared == [
        (
            '2 objects in table "Chat list" read only before (row "Cid, Yesterday, ok", row "Dan, Monday, photo"): '
            "that part was not read completely after, so they may still be there."
        )
    ]


def test_incomplete_before_parent_hides_additions():
    before = whatsapp()
    chat_list(before)["children"] = chat_list(before)["children"][:2]
    chat_list(before)["cut"] = "nodes"
    diff = diff_snapshots(before, whatsapp())
    assert diff.changes == []
    assert "read only after" in diff.not_compared[0]


def test_removal_between_two_read_siblings_is_reported_even_when_the_parent_was_cut():
    five = [*CHATS, (5, "Eve, 6:00 AM, hey")]
    after = whatsapp([CHATS[0], CHATS[2]])
    chat_list(after)["cut"] = "nodes"
    chat_list(after)["childCount"] = 4
    diff = diff_snapshots(whatsapp(five), after)
    assert summary(diff) == [
        ("removed", 'row "Bob, 5:40 AM, see you"', '(3 objects inside, such as "Bob", "5:40 AM", "see you")')
    ]
    assert "Dan, Monday, photo" in diff.not_compared[0] and "Eve, 6:00 AM, hey" in diff.not_compared[0]


def test_depth_cut_compares_nothing_below_it():
    after = whatsapp([(number, name.upper()) for number, name in CHATS])
    for row in chat_list(after)["children"]:
        del row["children"]
        row["cut"] = "depth"
    diff = diff_snapshots(whatsapp(), after)
    # The rows themselves are compared; their cells, read only before, are not.
    assert kinds(diff) == ["renamed"] * 4
    assert diff.not_compared == [
        (
            'What is inside 4 objects at the depth limit, such as row "ANA, 5:47 AM, HELLO", '
            'row "BOB, 5:40 AM, SEE YOU", row "CID, YESTERDAY, OK" and 1 more.'
        )
    ]


def test_child_count_change_below_the_depth_limit():
    before, after = whatsapp(), whatsapp()
    for snap, child_count in ((before, 3), (after, 4)):
        row = chat_list(snap)["children"][0]
        del row["children"]
        row.update(cut="depth", childCount=child_count)
    diff = diff_snapshots(before, after)
    assert located(diff) == [
        ('row "Ana, 5:47 AM, hello"', "child count", "", "1 more child than before (not read)")
    ]
    assert diff.not_compared == [
        'What is inside row "Ana, 5:47 AM, hello" (the depth limit was reached there).'
    ]


def test_truncated_walks_are_noted():
    before = dict(whatsapp(), truncated="stopped after 2.5 seconds")
    after = dict(whatsapp(), truncated="stopped after 400 nodes")
    diff = diff_snapshots(before, after)
    assert diff.not_compared == [
        "The before walk stopped early (stopped after 2.5 seconds); parts read only after were not compared.",
        "The after walk stopped early (stopped after 400 nodes); parts read only before were not compared.",
    ]
    assert changes_markdown(diff) == [
        "No changes found in the parts that could be compared.",
        *[f"Not compared: {note}" for note in diff.not_compared],
    ]


def test_odd_snapshots_never_raise():
    odd = [
        {},
        {"tree": None},
        {"tree": {"children": "none"}},
        {"tree": {"role": 5, "name": 7, "states": "x", "children": [None, {"index": "a"}, {"cut": "gap"}]}},
        {"tree": {"key": "k", "children": [{"index": -1, "key": "k"}, {"index": 10**9}]}, "alive": True},
    ]
    for before in odd:
        for after in odd:
            changes_markdown(diff_snapshots(before, after))


# Grouping and output


def test_more_than_five_changes_of_a_kind_merge_into_one_line():
    names = [f"Chat {number}" for number in range(1, 9)]
    rows = [node("row", name, f"ia2:1:-{number}") for number, name in enumerate(names)]
    changed = copy.deepcopy(rows)
    for row in changed[:6]:
        row["states"] = ["off screen"]
    changed[7]["states"] = ["selected"]
    before = snapshot(node("table", "Chat list", None, rows))
    diff = diff_snapshots(before, snapshot(node("table", "Chat list", None, changed)))
    assert diff.changes == [
        Change(
            "states",
            'table "Chat list"',
            "6 row objects",
            "now off screen",
            count=6,
            examples=['row "Chat 1"', 'row "Chat 2"', 'row "Chat 3"'],
        ),
        Change("states", 'table "Chat list"', 'row "Chat 8"', "now selected"),
    ]
    assert changes_markdown(diff)[2:] == [
        '- states: 6 row objects now off screen, such as row "Chat 1"; row "Chat 2"; row "Chat 3"',
        '- states: row "Chat 8" now selected',
    ]


def test_markdown_groups_changes_by_where_they_happened():
    diff = diff_snapshots(whatsapp(), whatsapp([(4, "Dan, 6:10 AM, hi"), *CHATS[:3]], compose="hi"))
    assert changes_markdown(diff) == [
        (
            f"5 changes; {WHATSAPP_OBJECTS} objects before, {WHATSAPP_OBJECTS} after; "
            f"{WHATSAPP_OBJECTS} matched, {WHATSAPP_OBJECTS} by accessible id."
        ),
        'In table "Chat list":',
        '- moved: row "Dan, 6:10 AM, hi" from position 4 to 1 (positions in browse mode order)',
        '- renamed: row "Dan, Monday, photo" to "Dan, 6:10 AM, hi"',
        'In row "Dan, 6:10 AM, hi":',
        '- renamed: cell "Monday" to "6:10 AM"',
        '- renamed: cell "photo" to "hi"',
        'In document "WhatsApp":',
        '- value: edit "Type a message" from (empty) to "hi"',
    ]


def test_max_changes_stops_with_a_count_of_the_rest():
    after = whatsapp([(number, name + "!") for number, name in CHATS], compose="hi")
    diff = diff_snapshots(whatsapp(), after)
    assert sum(change.count for change in diff.changes) == 9
    lines = changes_markdown(diff, max_changes=3)
    assert len([line for line in lines if line.startswith("- ")]) == 3
    assert lines[-1] == "…and 6 more changes; raise max_changes or record a smaller part with id."
    assert changes_markdown(diff, max_changes=8)[-1] == (
        "…and 1 more change; raise max_changes or record a smaller part with id."
    )


def test_not_compared_lines_come_after_the_changes():
    after = whatsapp(compose="hi")
    after["truncated"] = "stopped after 400 nodes"
    lines = changes_markdown(diff_snapshots(whatsapp(), after))
    assert lines[-1].startswith("Not compared: The after walk stopped early")
    assert lines[-2] == '- value: edit "Type a message" from (empty) to "hi"'


def test_to_dict_round_trip():
    diff = diff_snapshots(whatsapp(), whatsapp([(4, "Dan, 6:10 AM, hi"), *CHATS[:3]], compose="hi"))
    data = json.loads(json.dumps(diff.to_dict()))
    assert set(data) == {
        "changes",
        "beforeCount",
        "afterCount",
        "matched",
        "matchedByKey",
        "notCompared",
        "rootGone",
    }
    assert data["changes"][0] == {
        "kind": "moved",
        "context": 'table "Chat list"',
        "subject": 'row "Dan, 6:10 AM, hi"',
        "detail": "from position 4 to 1",
        "count": 1,
        "examples": [],
    }
    assert TreeDiff.from_dict(data) == diff


def test_longest_increasing_subsequence():
    assert interaction._longest_increasing([1, 2, 3, 0]) == {0, 1, 2}
    assert interaction._longest_increasing([]) == set()
    assert len(interaction._longest_increasing([3, 1, 2, 0, 4])) == 3
