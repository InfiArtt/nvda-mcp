import random
from dataclasses import dataclass, field

import pytest
import treeWalk
from treeWalk import searchTrees, snapshotTree, walkTree


@dataclass(eq=False)
class Node:
    role: str
    name: str = ""
    children: list["Node"] = field(default_factory=list)
    next: "Node | None" = None
    previous: "Node | None" = None
    parent: "Node | None" = None
    key: str | None = None
    # Callbacks that raise when asked about this node: "firstChild", "nextSibling", "lastChild",
    # "previousSibling", "childCount", "describe", "isLayoutOnly", "isOnFocusPath".
    fail: frozenset[str] = frozenset()
    # What childCount reports; ... means the number of children.
    reported_count: object = ...

    def __post_init__(self):
        for child, following in zip(self.children, self.children[1:]):
            child.next = following
            following.previous = child
        for child in self.children:
            child.parent = self


def walk(root, max_depth=4, max_nodes=100, max_children=None):
    return walkTree(
        root,
        max_depth,
        max_nodes,
        max_children,
        firstChild=lambda node: node.children[0] if node.children else None,
        nextSibling=lambda node: node.next,
        describe=lambda node: {"role": node.role, "name": node.name},
        isLayoutOnly=lambda node: node.role == "section" and not node.name,
        childCount=lambda node: len(node.children),
        timeBudgetSeconds=3.0,
        maxNesting=100,
    )


def test_last_child_with_its_own_children_cut_is_kept():
    # WhatsApp Web: the document's last child visited is a large section whose children are cut.
    big = Node("section", "Chats", [Node("row", str(number)) for number in range(30)])
    root = Node("document", "WhatsApp", [Node("status bar"), big])
    tree = walk(root, max_children=5)["tree"]
    assert [child["role"] for child in tree["children"]] == ["status bar", "section"]
    assert "moreChildren" not in tree
    assert tree["children"][1]["moreChildren"] == 25
    assert len(tree["children"][1]["children"]) == 5


def test_layout_containers_are_flattened_and_cut_lists_still_counted():
    rows = [Node("row", str(number)) for number in range(4)]
    root = Node("table", "Chat list", [Node("section", "", rows)])
    tree = walk(root, max_children=2)["tree"]
    assert [child["name"] for child in tree["children"]] == ["0", "1"]
    assert tree["moreChildren"] is True


def test_node_limit_reports_why_it_stopped():
    root = Node("list", "Scripts", [Node("list item", str(number)) for number in range(10)])
    result = walk(root, max_nodes=4)
    assert result["nodeCount"] == 4
    assert result["truncated"] == "stopped after 4 nodes"
    assert len(result["tree"]["children"]) == 3


def search(roots, name, max_results=10, found=None):
    return searchTrees(
        roots,
        lambda node: name in node.name,
        max_results,
        firstChild=lambda node: node.children[0] if node.children else None,
        nextSibling=lambda node: node.next,
        timeBudgetSeconds=3.0,
        maxVisits=100,
        maxNesting=100,
        found=found,
    )


def test_search_roots_share_one_time_budget(monkeypatch):
    # A web document, then its whole browser window: each object takes a second to look at.
    clock = iter(range(100))
    monkeypatch.setattr(treeWalk.time, "monotonic", lambda: next(clock))
    document = Node("document", "WhatsApp", [Node("text", str(number)) for number in range(10)])
    window = Node("window", "Brave", [Node("button", "Reload")])
    matches, stopped = search([document, window], "Reload")
    assert matches == []
    assert stopped == "stopped after 3.0 seconds"


def test_search_does_not_repeat_controls_found_below_an_earlier_root():
    box = Node("edit", "Search or start a new chat")
    document = Node("document", "WhatsApp", [Node("section", "", [box])])
    window = Node("window", "WhatsApp - Brave", [document])
    matches, stopped = search([document, window], "WhatsApp")
    # Neither root matches itself, but the document matches below the window.
    assert matches == [document]
    assert stopped is None
    matches, _ = search([document, window], "Search")
    assert matches == [box]


def test_controls_already_found_count_towards_the_results():
    focus = Node("edit", "Search or start a new chat")
    root = Node("document", "WhatsApp", [Node("button", "Search"), focus])
    matches, stopped = search([root], "Search", max_results=2, found=[focus])
    assert matches == [focus, root.children[0]]
    assert stopped == "stopped at 2 results"


# snapshotTree


class FakeCOMError(Exception):
    """Stands in for comtypes' COMError, raised when an object has gone or the application fails."""


def is_layout(node):
    return node.role == "section" and not node.name


def on_focus_path(node, focus):
    """Whether node is the focus or one of its ancestors."""
    ancestor = focus
    while ancestor is not None:
        if ancestor is node:
            return True
        ancestor = ancestor.parent
    return False


class Callbacks:
    """snapshotTree's callbacks over Node trees: records every call and raises where a node says so."""

    def __init__(self, focus=None):
        self.focus = focus
        self.calls = []

    def _call(self, name, node):
        self.calls.append((name, node))
        if name in node.fail:
            raise FakeCOMError(f"{name} failed on {node.role} {node.name!r}")

    def first_child(self, node):
        self._call("firstChild", node)
        return node.children[0] if node.children else None

    def next_sibling(self, node):
        self._call("nextSibling", node)
        return node.next

    def last_child(self, node):
        self._call("lastChild", node)
        return node.children[-1] if node.children else None

    def previous_sibling(self, node):
        self._call("previousSibling", node)
        return node.previous

    def child_count(self, node):
        self._call("childCount", node)
        return len(node.children) if node.reported_count is ... else node.reported_count

    def describe(self, node):
        self._call("describe", node)
        description = {"key": node.key, "role": node.role}
        if node.name:
            description["name"] = node.name
        if node is self.focus:
            description["focused"] = True
        return description

    def is_layout_only(self, node):
        self._call("isLayoutOnly", node)
        return is_layout(node)

    def is_on_focus_path(self, node):
        self._call("isOnFocusPath", node)
        return on_focus_path(node, self.focus)

    def asked(self, name):
        """The nodes a callback was asked about, in order."""
        return [node for call, node in self.calls if call == name]

    def touched(self):
        """The ids of every node any callback was asked about."""
        return {id(node) for _, node in self.calls}

    def described_names(self):
        return [node.name for node in self.asked("describe")]


CUTS = {"depth", "nodes", "time", "nesting", "error", "gap"}


def snapshot(root, callbacks=None, **limits):
    callbacks = callbacks or Callbacks()
    settings = {
        "maxNodes": 100,
        "maxDepth": 10,
        "headChildren": 5,
        "tailChildren": 5,
        "timeBudgetSeconds": 3.0,
        "maxNesting": 100,
    }
    settings.update(limits)
    result = snapshotTree(
        root,
        firstChild=callbacks.first_child,
        nextSibling=callbacks.next_sibling,
        lastChild=callbacks.last_child,
        previousSibling=callbacks.previous_sibling,
        childCount=callbacks.child_count,
        describe=callbacks.describe,
        isLayoutOnly=callbacks.is_layout_only,
        isOnFocusPath=callbacks.is_on_focus_path,
        **settings,
    )
    check_snapshot(result, settings)
    return result


def check_snapshot(result, settings):
    """What holds for every snapshot, whatever the tree and its failures."""
    assert set(result) == {"nodeCount", "truncated", "tree"}
    tree = result["tree"]
    assert tree["index"] == 0
    assert result["nodeCount"] == count_nodes(tree)
    assert result["nodeCount"] <= max(settings["maxNodes"], 1)
    most_children = max(settings["headChildren"], 0) + max(settings["tailChildren"], 0) + 1
    stop_cuts = set()

    def check(node, depth):
        assert depth <= settings["maxDepth"]
        if "cut" in node:
            assert node["cut"] in CUTS
            if node["cut"] in ("nodes", "time", "nesting"):
                stop_cuts.add(node["cut"])
        if "childCount" in node:
            assert type(node["childCount"]) is int and node["childCount"] >= 0
            assert "cut" in node
        children = node.get("children", [])
        assert "children" not in node or children
        if depth == settings["maxDepth"]:
            assert not children
        indexes = [child["index"] for child in children]
        # Document order: read from the start first, then from the end; no index twice.
        assert indexes == sorted(indexes, key=lambda index: (index < 0, index))
        assert len(set(indexes)) == len(indexes)
        assert len(children) <= most_children
        if any(index < 0 for index in indexes):
            assert "cut" in node
        for child in children:
            check(child, depth + 1)

    check(tree, 0)
    assert (result["truncated"] is None) == (not stop_cuts)
    if "nodes" in stop_cuts:
        assert result["truncated"] == f"stopped after {settings['maxNodes']} nodes"
    if "time" in stop_cuts:
        assert result["truncated"] == f"stopped after {settings['timeBudgetSeconds']} seconds"


def count_nodes(node):
    return 1 + sum(count_nodes(child) for child in node.get("children", []))


def child_names(node):
    return [child.get("name") for child in node.get("children", [])]


def child_indexes(node):
    return [child["index"] for child in node.get("children", [])]


def rows(count, role="row"):
    return [Node(role, str(number)) for number in range(count)]


def whatsapp(focus_name="Citra"):
    chats = Node("list", "Chat list", [Node("row", name) for name in ("Ana", "Budi", "Citra")])
    root = Node(
        "document",
        "WhatsApp",
        [
            Node("toolbar", "Chats", [Node("button", "New chat"), Node("button", "Menu")]),
            chats,
            Node("region", "Conversation", [Node("edit", "Type a message")]),
        ],
    )
    focus = next(row for row in chats.children if row.name == focus_name)
    return root, focus


def test_snapshot_reads_the_whole_tree_with_indexes():
    root, _ = whatsapp()
    callbacks = Callbacks()
    result = snapshot(root, callbacks)
    tree = result["tree"]
    assert result["nodeCount"] == 10
    assert result["truncated"] is None
    assert tree["role"] == "document" and tree["name"] == "WhatsApp" and tree["key"] is None
    assert child_names(tree) == ["Chats", "Chat list", "Conversation"]
    assert child_indexes(tree) == [0, 1, 2]
    assert child_indexes(tree["children"][1]) == [0, 1, 2]
    assert "cut" not in str(tree)
    # describe is called once per kept node; nothing is counted when everything was read.
    assert len(callbacks.asked("describe")) == 10
    assert callbacks.asked("childCount") == []
    assert callbacks.asked("lastChild") == []


def test_focus_child_is_read_first_so_a_tight_budget_leaves_out_the_far_side():
    root, focus = whatsapp("Citra")
    callbacks = Callbacks(focus)
    result = snapshot(root, callbacks, maxNodes=5)
    tree = result["tree"]
    # The chat list (on the focus path) and its focused row come first, then the row's siblings.
    assert callbacks.described_names() == ["WhatsApp", "Chat list", "Citra", "Ana", "Budi"]
    assert result["nodeCount"] == 5
    assert result["truncated"] == "stopped after 5 nodes"
    # The output stays in document order, with the toolbar and the conversation left out.
    assert child_names(tree) == ["Chat list"]
    assert child_indexes(tree) == [1]
    assert tree["cut"] == "nodes"
    chats = tree["children"][0]
    assert child_names(chats) == ["Ana", "Budi", "Citra"]
    assert chats["children"][2]["focused"] is True
    # Every child of the chat list was read before the budget ran out.
    assert "cut" not in chats


def test_node_budget_marks_every_parent_whose_children_were_not_finished():
    root, focus = whatsapp("Budi")
    result = snapshot(root, Callbacks(focus), maxNodes=3)
    tree = result["tree"]
    assert tree["cut"] == "nodes"
    chats = tree["children"][0]
    assert chats["name"] == "Chat list" and chats["cut"] == "nodes"
    assert child_names(chats) == ["Budi"]
    assert child_indexes(chats) == [1]
    # How many children the cut parents report, so a later snapshot can tell the list grew.
    assert tree["childCount"] == 3
    assert chats["childCount"] == 3


def test_node_budget_does_not_mark_a_parent_whose_last_child_was_read():
    inner = Node("list", "Inner", [Node("row", "x"), Node("row", "y")])
    first = Node("group", "A", [Node("row", "a1"), inner])
    root = Node("document", "Page", [first, Node("button", "B")])
    result = snapshot(root, maxNodes=4)
    tree = result["tree"]
    assert result["nodeCount"] == 4
    assert tree["cut"] == "nodes"
    group = tree["children"][0]
    # Its last child, Inner, was read; only Inner's own children were not.
    assert "cut" not in group
    assert group["children"][1]["cut"] == "nodes"
    assert group["children"][1]["childCount"] == 2


def test_a_tree_that_exactly_fits_the_budget_is_not_truncated():
    root, _ = whatsapp()
    result = snapshot(root, maxNodes=10)
    assert result["truncated"] is None
    assert "cut" not in str(result["tree"])


def test_last_object_the_node_budget_allows_only_checks_that_it_has_children():
    items = rows(700)
    chats = Node("list", "Chats", items)
    root = Node("document", "Page", [chats])
    callbacks = Callbacks(items[600])
    result = snapshot(root, callbacks, maxNodes=2, headChildren=3, tailChildren=2)
    tree = result["tree"]
    assert result["truncated"] == "stopped after 2 nodes"
    chats_node = tree["children"][0]
    assert chats_node["cut"] == "nodes"
    assert chats_node["childCount"] == 700
    assert "children" not in chats_node
    assert "cut" not in tree
    # No row can be described, so the rows are not counted, read from the end or scanned for the focus:
    # reaching the first one is enough to know that some were left out.
    assert callbacks.asked("firstChild") == [root, chats]
    assert callbacks.asked("nextSibling") == [chats]
    assert callbacks.asked("lastChild") == []
    assert [node.name for node in callbacks.asked("isOnFocusPath")] == ["Page", "Chats"]
    touched = callbacks.touched()
    assert not any(id(item) in touched for item in items[1:])
    # The last object allowed has no children: it says nothing more.
    root = Node("document", "Page", [Node("button", "Send"), Node("button", "Menu")])
    result = snapshot(root, maxNodes=2)
    assert result["tree"]["children"][0] == {"key": None, "role": "button", "name": "Send", "index": 0}
    assert result["tree"]["cut"] == "nodes"


def test_long_list_keeps_the_first_and_last_children_with_negative_indexes():
    items = rows(20)
    chats = Node("list", "Chats", items)
    callbacks = Callbacks()
    result = snapshot(chats, callbacks, headChildren=3, tailChildren=2)
    tree = result["tree"]
    assert child_names(tree) == ["0", "1", "2", "18", "19"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert tree["cut"] == "gap"
    assert tree["childCount"] == 20
    assert result["truncated"] is None
    assert result["nodeCount"] == 6
    # Counting stopped at head + tail + 1 children, without describing the ones past the head.
    assert callbacks.asked("nextSibling") == items[:5]
    assert callbacks.described_names() == ["Chats", "0", "1", "2", "18", "19"]
    touched = callbacks.touched()
    assert not any(id(item) in touched for item in items[6:18])


def test_short_list_is_read_completely_without_a_gap():
    chats = Node("list", "Chats", rows(5))
    callbacks = Callbacks()
    tree = snapshot(chats, callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 2, 3, 4]
    assert "cut" not in tree and "childCount" not in tree
    assert callbacks.asked("lastChild") == []
    assert callbacks.asked("childCount") == []


def test_one_child_more_than_head_and_tail_makes_a_gap():
    tree = snapshot(Node("list", "Chats", rows(6)), headChildren=3, tailChildren=2)["tree"]
    assert child_names(tree) == ["0", "1", "2", "4", "5"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert tree["cut"] == "gap"


def test_an_object_without_children_has_no_children_or_cut():
    tree = snapshot(Node("button", "Send"))["tree"]
    assert tree == {"key": None, "role": "button", "name": "Send", "index": 0}


def test_head_only_and_tail_only():
    callbacks = Callbacks()
    tree = snapshot(Node("list", "Chats", rows(10)), callbacks, headChildren=2, tailChildren=0)["tree"]
    assert child_indexes(tree) == [0, 1]
    assert tree["cut"] == "gap"
    assert callbacks.asked("lastChild") == []
    tree = snapshot(Node("list", "Messages", rows(10)), headChildren=0, tailChildren=2)["tree"]
    assert child_names(tree) == ["8", "9"]
    assert child_indexes(tree) == [-2, -1]
    assert tree["cut"] == "gap"


def test_focus_child_in_the_gap_is_kept_with_its_index_from_the_start():
    items = rows(50)
    chats = Node("list", "Chats", items)
    callbacks = Callbacks(items[30])
    tree = snapshot(chats, callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_names(tree) == ["0", "1", "2", "30", "48", "49"]
    assert child_indexes(tree) == [0, 1, 2, 30, -2, -1]
    assert tree["cut"] == "gap"
    # The focused row is described first, and its neighbours in the gap are not described at all.
    assert callbacks.described_names() == ["Chats", "30", "0", "1", "2", "48", "49"]


def test_focus_child_found_while_counting_keeps_its_index_from_the_start():
    items = rows(50)
    callbacks = Callbacks(items[4])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 2, 4, -2, -1]
    # Found while counting the first head + tail + 1 children: no further scan was needed.
    assert callbacks.asked("nextSibling") == items[:5]


def test_focus_child_among_the_last_children_is_kept_once_with_its_negative_index():
    items = rows(50)
    callbacks = Callbacks(items[48])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_names(tree) == ["0", "1", "2", "48", "49"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert callbacks.described_names() == ["Chats", "48", "0", "1", "2", "49"]


def test_focus_child_counted_from_the_start_and_read_from_the_end_is_kept_once():
    # Six rows, three from the start and two from the end: the last row is counted (position 5)
    # and also read from the end (-1). It must appear once, with the index it has among the last children.
    items = rows(6)
    callbacks = Callbacks(items[5])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_names(tree) == ["0", "1", "2", "4", "5"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert callbacks.described_names().count("5") == 1


def test_object_read_from_the_start_and_again_from_the_end_is_kept_once():
    # The list loses rows between counting from the start and reading from the end. The rows read
    # from the end are new objects, as NVDA hands out, so the one read twice is known by its key.
    def row(number):
        return Node("row", str(number), key=f"ia2:1:{number}")

    chats = Node("list", "Chats", [row(number) for number in range(8)])

    class Shrinking(Callbacks):
        def last_child(self, node):
            if node is chats:
                chats.children = Node("list", "Chats", [row(number) for number in range(4)]).children
            return super().last_child(node)

    result = snapshot(chats, Shrinking(), headChildren=3, tailChildren=2)
    tree = result["tree"]
    assert [child["key"] for child in tree["children"]] == ["ia2:1:0", "ia2:1:1", "ia2:1:2", "ia2:1:3"]
    assert child_indexes(tree) == [0, 1, 2, -1]
    assert tree["cut"] == "gap"
    # The copy left out does not count as a node.
    assert result["nodeCount"] == 5


def test_focus_child_past_the_first_500_children_is_left_out():
    items = rows(700)
    callbacks = Callbacks(items[600])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert "600" not in callbacks.described_names()
    # The scan looked at the first 500 children and no further.
    touched = callbacks.touched()
    assert id(items[499]) in touched
    assert not any(id(item) in touched for item in items[500:698])


def test_focus_child_within_the_first_500_children_is_found_by_scanning():
    items = rows(700)
    callbacks = Callbacks(items[499])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 2, 499, -2, -1]


def test_focus_is_only_asked_about_children_of_objects_on_the_focus_path():
    root, focus = whatsapp("Ana")
    callbacks = Callbacks(focus)
    snapshot(root, callbacks)
    asked = [node.name for node in callbacks.asked("isOnFocusPath")]
    # The root, its children until the chat list, then the chat list's children until Ana.
    assert asked == ["WhatsApp", "Chats", "Chat list", "Ana"]
    callbacks = Callbacks(focus=None)
    snapshot(root, callbacks)
    assert [node.name for node in callbacks.asked("isOnFocusPath")] == ["WhatsApp"]


def test_children_of_the_focus_are_not_searched_for_the_focus_path():
    items = rows(700)
    files = Node("list", "Files", items)
    root = Node("document", "Page", [Node("button", "Menu"), files])
    callbacks = Callbacks(files)
    tree = snapshot(root, callbacks, headChildren=3, tailChildren=2)["tree"]
    files_node = tree["children"][1]
    assert files_node["focused"] is True
    assert child_indexes(files_node) == [0, 1, 2, -2, -1]
    # The list is the focus, so none of its rows is on the way to it: no row is asked,
    # and counting stops at head + tail + 1 rows instead of scanning the first 500.
    assert [node.name for node in callbacks.asked("isOnFocusPath")] == ["Page", "Menu", "Files"]
    assert len([node for node in callbacks.asked("nextSibling") if node in items]) <= 3 + 2 + 1
    # The same when the focus is the root.
    callbacks = Callbacks(files)
    snapshot(files, callbacks, headChildren=3, tailChildren=2)
    assert callbacks.asked("isOnFocusPath") == []
    assert len(callbacks.asked("nextSibling")) <= 3 + 2 + 1


def test_depth_limit_uses_child_count_without_reading_children():
    chats = Node("list", "Chats", [Node("row", "Ana", [Node("text", "hello")]), Node("row", "Budi")])
    root = Node("document", "WhatsApp", [Node("section", "", [chats]), Node("button", "Menu")])
    callbacks = Callbacks()
    tree = snapshot(root, callbacks, maxDepth=1)["tree"]
    # The unnamed section is flattened and does not count as a level.
    assert child_names(tree) == ["Chats", "Menu"]
    chats_node, menu = tree["children"]
    assert chats_node["cut"] == "depth"
    assert chats_node["childCount"] == 2
    assert "children" not in chats_node
    # At the limit, children are counted, never read.
    assert chats not in callbacks.asked("firstChild")
    assert chats not in callbacks.asked("lastChild")
    assert callbacks.asked("childCount") == [chats, root.children[1]]
    # A leaf at the limit says nothing more.
    assert "cut" not in menu and "childCount" not in menu
    assert "cut" not in tree


def test_depth_zero_snapshots_only_the_root():
    callbacks = Callbacks()
    result = snapshot(Node("list", "Chats", rows(3)), callbacks, maxDepth=0)
    assert result["tree"] == {
        "key": None,
        "role": "list",
        "name": "Chats",
        "index": 0,
        "childCount": 3,
        "cut": "depth",
    }
    assert callbacks.asked("firstChild") == []


def test_depth_limit_trusts_only_a_positive_child_count():
    for reported in (0, None, -1, True, "3"):
        node = Node("list", "Chats", rows(3), reported_count=reported)
        tree = snapshot(Node("document", "Page", [node]), maxDepth=1)["tree"]
        assert tree["children"][0] == {"key": None, "role": "list", "name": "Chats", "index": 0}


def test_child_count_failing_at_the_depth_limit_is_an_error():
    node = Node("list", "Chats", rows(3), fail=frozenset({"childCount"}))
    tree = snapshot(Node("document", "Page", [node]), maxDepth=1)["tree"]
    assert tree["children"][0]["cut"] == "error"
    assert "childCount" not in tree["children"][0]


def test_child_count_failing_after_a_cut_keeps_the_cut():
    chats = Node("list", "Chats", rows(20), fail=frozenset({"childCount"}))
    tree = snapshot(chats, headChildren=3, tailChildren=2)["tree"]
    assert tree["cut"] == "gap"
    assert "childCount" not in tree


def test_error_while_reading_children_keeps_earlier_children_and_carries_on():
    items = rows(10)
    items[3].fail = frozenset({"nextSibling"})
    chats = Node("list", "Chats", items)
    root = Node("document", "WhatsApp", [chats, Node("button", "Send")])
    callbacks = Callbacks()
    result = snapshot(root, callbacks)
    tree = result["tree"]
    chats_node = tree["children"][0]
    assert child_names(chats_node) == ["0", "1", "2", "3"]
    assert child_indexes(chats_node) == [0, 1, 2, 3]
    assert chats_node["cut"] == "error"
    assert chats_node["childCount"] == 10
    # The rest of the walk carried on: an error does not stop the walk.
    assert child_names(tree) == ["Chats", "Send"]
    assert "cut" not in tree
    assert result["truncated"] is None
    # Without knowing whether the list is long, nothing was read from the end.
    assert callbacks.asked("lastChild") == []


def test_first_child_failing_is_an_error_without_children():
    broken = Node("list", "Chats", rows(3), fail=frozenset({"firstChild"}))
    tree = snapshot(Node("document", "Page", [broken, Node("button", "Send")]))["tree"]
    assert child_names(tree) == ["Chats", "Send"]
    assert tree["children"][0]["cut"] == "error"
    assert "children" not in tree["children"][0]


def test_error_inside_a_layout_container_is_an_error_of_the_kept_parent():
    items = rows(4)
    items[1].fail = frozenset({"nextSibling"})
    root = Node("list", "Messages", [Node("section", "", items), Node("row", "after")])
    tree = snapshot(root)["tree"]
    assert child_names(tree) == ["0", "1"]
    assert tree["cut"] == "error"


def test_error_while_reading_from_the_end_keeps_what_was_read():
    items = rows(20)
    items[18].fail = frozenset({"previousSibling"})
    tree = snapshot(Node("list", "Chats", items), headChildren=3, tailChildren=3)["tree"]
    assert child_names(tree) == ["0", "1", "2", "18", "19"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    # An error says more than the gap: the end was not read as far as it should have been.
    assert tree["cut"] == "error"
    broken = Node("list", "Chats", rows(20), fail=frozenset({"lastChild"}))
    tree = snapshot(broken, headChildren=3, tailChildren=3)["tree"]
    assert child_indexes(tree) == [0, 1, 2]
    assert tree["cut"] == "error"


def test_error_while_scanning_for_the_focus_is_an_error():
    items = rows(50)
    items[10].fail = frozenset({"nextSibling"})
    callbacks = Callbacks(items[30])
    tree = snapshot(Node("list", "Chats", items), callbacks, headChildren=3, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 2, -2, -1]
    assert tree["cut"] == "error"


def test_description_failing_leaves_the_object_out_but_keeps_the_others_indexes():
    items = rows(5)
    items[2].fail = frozenset({"describe"})
    result = snapshot(Node("list", "Chats", items))
    tree = result["tree"]
    assert child_indexes(tree) == [0, 1, 3, 4]
    assert tree["cut"] == "error"
    assert result["nodeCount"] == 5


def test_root_description_failing_gives_an_unknown_root():
    root = Node("document", "Gone", rows(3), fail=frozenset({"describe"}))
    callbacks = Callbacks()
    result = snapshot(root, callbacks)
    assert result == {
        "nodeCount": 1,
        "truncated": None,
        "tree": {"key": None, "role": "unknown", "index": 0, "cut": "error"},
    }
    assert callbacks.asked("firstChild") == []


def test_failing_predicates_count_as_false():
    # A container whose layout check fails is kept; a focus check that fails only loses focus-first order.
    wrapper = Node("section", "", [Node("row", "inside")], fail=frozenset({"isLayoutOnly"}))
    items = [Node("row", "0"), wrapper, Node("row", "2", fail=frozenset({"isOnFocusPath"}))]
    root = Node("list", "Chats", items)
    callbacks = Callbacks(items[2])
    tree = snapshot(root, callbacks)["tree"]
    assert [child["role"] for child in tree["children"]] == ["row", "section", "row"]
    assert child_names(tree["children"][1]) == ["inside"]
    assert callbacks.described_names() == ["Chats", "0", "", "inside", "2"]


def test_everything_failing_raises_nothing():
    everything = frozenset(
        {
            "firstChild",
            "nextSibling",
            "lastChild",
            "previousSibling",
            "childCount",
            "describe",
            "isLayoutOnly",
            "isOnFocusPath",
        }
    )
    for depth in (0, 1):
        root = Node("document", "Page", rows(3), fail=everything)
        assert snapshot(root, Callbacks(root), maxDepth=depth)["tree"]["role"] == "unknown"
    items = [Node("row", str(number), fail=everything - {"describe"}) for number in range(20)]
    root = Node("list", "Chats", items, fail=everything - {"describe"})
    result = snapshot(root, Callbacks(items[10]), headChildren=2, tailChildren=2)
    assert result["tree"]["cut"] == "error"
    assert "children" not in result["tree"]


def test_describe_result_is_copied():
    shared = {"key": None, "role": "row"}
    callbacks = Callbacks()
    callbacks.describe = lambda node: shared
    result = snapshot(Node("list", "Chats", rows(2)), callbacks)
    assert shared == {"key": None, "role": "row"}
    assert child_indexes(result["tree"]) == [0, 1]


def test_layout_containers_are_flattened_with_indexes_from_both_ends():
    r = rows(12)
    root = Node(
        "list",
        "Messages",
        [
            Node("section", "", [r[0], r[1]]),
            Node("section", ""),
            r[2],
            Node("section", "", [r[3], Node("section", "", [r[4], r[5]])]),
            r[6],
            r[7],
            Node("section", "", [r[8], Node("section", "", [r[9], r[10]])]),
            Node("section", "", [r[11]]),
        ],
    )
    tree = snapshot(root, headChildren=3, tailChildren=3)["tree"]
    assert child_names(tree) == ["0", "1", "2", "9", "10", "11"]
    assert child_indexes(tree) == [0, 1, 2, -3, -2, -1]
    assert tree["cut"] == "gap"
    # Read completely, the indexes count the flattened sequence; the empty section takes no place.
    tree = snapshot(root, headChildren=10, tailChildren=10)["tree"]
    assert child_names(tree) == [str(number) for number in range(12)]
    assert child_indexes(tree) == list(range(12))
    assert "cut" not in tree


def test_focus_inside_a_layout_container_is_found_from_both_ends():
    r = rows(30)
    root = Node("list", "Messages", [Node("section", "", r[:15]), Node("section", "", r[15:])])
    tree = snapshot(root, Callbacks(r[20]), headChildren=2, tailChildren=2)["tree"]
    assert child_indexes(tree) == [0, 1, 20, -2, -1]
    tree = snapshot(root, Callbacks(r[28]), headChildren=2, tailChildren=2)["tree"]
    assert child_names(tree) == ["0", "1", "28", "29"]
    assert child_indexes(tree) == [0, 1, -2, -1]


def test_layout_cycle_is_stopped_by_the_nesting_guard():
    loop = Node("section", "")
    loop.children = [loop]
    root = Node("document", "Page", [Node("list", "Broken", [loop]), Node("button", "Send")])
    result = snapshot(root, maxNesting=5)
    tree = result["tree"]
    assert result["truncated"] == "stopped at 5 levels of nesting"
    assert child_names(tree) == ["Broken", "Send"]
    assert tree["children"][0]["cut"] == "nesting"
    assert "cut" not in tree


def test_nesting_limit_on_kept_objects():
    root = Node("document", "Page", [Node("list", "Chats", [Node("row", "Ana", [Node("text", "hi")])])])
    result = snapshot(root, maxNesting=2)
    chats = result["tree"]["children"][0]
    assert child_names(chats) == ["Ana"]
    assert chats["children"][0]["cut"] == "nesting"
    assert result["truncated"] == "stopped at 2 levels of nesting"


def test_nesting_counts_every_level_including_layout_containers():
    # As in walkTree: the row sits at nesting 3 (two sections and itself), its text at 4.
    def page():
        ana = Node("row", "Ana", [Node("text", "hi")])
        return Node("document", "Page", [Node("section", "", [Node("section", "", [ana])])])

    result = snapshot(page(), maxNesting=4)
    assert result["truncated"] is None
    assert child_names(result["tree"]["children"][0]) == ["hi"]
    result = snapshot(page(), maxNesting=3)
    ana = result["tree"]["children"][0]
    assert ana["cut"] == "nesting"
    assert "children" not in ana
    assert result["truncated"] == "stopped at 3 levels of nesting"


def test_sibling_cycle_ends():
    items = rows(3)
    items[2].next = items[0]
    tree = snapshot(Node("list", "Chats", items), headChildren=2, tailChildren=2)["tree"]
    # Counting sees 0, 1, 2, 0, 1 and finds the list long; the walk ends all the same.
    # Row 1, read from the start and again from the end, is kept once.
    assert child_names(tree) == ["0", "1", "2"]
    assert child_indexes(tree) == [0, 1, -1]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class SlowCallbacks(Callbacks):
    """Every description takes a second."""

    def __init__(self, clock, focus=None):
        super().__init__(focus)
        self.clock = clock

    def describe(self, node):
        self.clock.now += 1
        return super().describe(node)


def test_time_budget_marks_unfinished_parents(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(treeWalk.time, "monotonic", clock)
    first = Node("group", "A", [Node("row", "a1"), Node("row", "a2")])
    root = Node("document", "Page", [first, Node("button", "B")])
    callbacks = SlowCallbacks(clock)
    result = snapshot(root, callbacks, timeBudgetSeconds=2.5)
    tree = result["tree"]
    assert result["truncated"] == "stopped after 2.5 seconds"
    assert callbacks.described_names() == ["Page", "A", "a1"]
    assert tree["cut"] == "time"
    assert tree["children"][0]["cut"] == "time"
    assert child_names(tree["children"][0]) == ["a1"]
    # Once time has run out, nothing more is asked, not even how many children there are.
    assert callbacks.asked("childCount") == []
    assert "childCount" not in str(tree)


def test_time_running_out_while_counting_children(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(treeWalk.time, "monotonic", clock)

    class SlowNavigation(Callbacks):
        def next_sibling(self, node):
            clock.now += 1
            return super().next_sibling(node)

    callbacks = SlowNavigation()
    result = snapshot(Node("list", "Chats", rows(10)), callbacks, timeBudgetSeconds=2.5)
    assert result["truncated"] == "stopped after 2.5 seconds"
    assert result["tree"]["cut"] == "time"
    assert "children" not in result["tree"]
    assert callbacks.described_names() == ["Chats"]


class StillClock(Callbacks):
    """Time stands still, unless the walk goes round far more often than any guard allows:
    then it runs out, so a missing guard fails the test instead of hanging it."""

    def __init__(self, clock, focus=None):
        super().__init__(focus)
        self.clock = clock

    def _call(self, name, node):
        super()._call(name, node)
        if len(self.calls) > 100_000:
            self.clock.now = 10.0**9


LAYOUT_LOOP = "stopped after 500 steps through layout containers without finding a child"


def test_loop_among_sibling_layout_containers_is_stopped_and_the_walk_carries_on(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(treeWalk.time, "monotonic", clock)
    loop = Node("section", "")
    broken = Node("list", "Broken", [loop])
    loop.next = loop
    buttons = [Node("button", f"Button {number}") for number in range(30)]
    root = Node("document", "Page", [broken, *buttons])
    callbacks = StillClock(clock)
    result = snapshot(root, callbacks, headChildren=20, tailChildren=20, timeBudgetSeconds=2.5)
    tree = result["tree"]
    assert result["truncated"] == LAYOUT_LOOP
    assert child_names(tree) == ["Broken"] + [button.name for button in buttons]
    assert tree["children"][0]["cut"] == "nesting"
    assert tree["children"][0]["childCount"] == 1
    assert "cut" not in tree
    assert len(callbacks.calls) < 2000


def test_loop_among_layout_containers_read_from_the_end_is_stopped(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(treeWalk.time, "monotonic", clock)
    loop = Node("section", "")
    chats = Node("list", "Chats", [*rows(20), loop])
    loop.previous = loop
    root = Node("document", "Page", [chats, Node("button", "Send")])
    result = snapshot(root, StillClock(clock), headChildren=3, tailChildren=2, timeBudgetSeconds=2.5)
    chats_node = result["tree"]["children"][0]
    assert child_indexes(chats_node) == [0, 1, 2]
    assert chats_node["cut"] == "nesting"
    assert child_names(result["tree"]) == ["Chats", "Send"]
    assert result["truncated"] == LAYOUT_LOOP


def test_layout_containers_around_every_child_do_not_stop_a_long_read():
    # Each row is two layout containers deep: many steps in all, but few between one row and the next.
    items = rows(600)
    root = Node("list", "Messages", [Node("section", "", [Node("section", "", [row])]) for row in items])
    result = snapshot(root, Callbacks(items[499]), headChildren=3, tailChildren=2)
    assert child_indexes(result["tree"]) == [0, 1, 2, 499, -2, -1]
    assert result["tree"]["cut"] == "gap"
    assert result["truncated"] is None


ALL_CALLBACKS = (
    "firstChild",
    "nextSibling",
    "lastChild",
    "previousSibling",
    "childCount",
    "describe",
    "isLayoutOnly",
    "isOnFocusPath",
)


def random_tree(rng, keys, depth=0, cycles=False):
    """A random tree with layout sections, failing callbacks and, if asked, broken links."""
    children = []
    if depth < 4:
        for _ in range(rng.choice([0, 0, 1, 2, 3, 5, 8])):
            children.append(random_tree(rng, keys, depth + 1, cycles))
    key = f"k{next(keys)}"
    name = "" if rng.random() < 0.3 else key
    role = rng.choice(["section", "section", "row", "list", "button"])
    fail = frozenset(call for call in ALL_CALLBACKS if rng.random() < 0.04)
    node = Node(role, name, children, key=key, fail=fail)
    if cycles and children and rng.random() < 0.3:
        rng.choice(children).next = rng.choice(children)
    if cycles and children and rng.random() < 0.1:
        rng.choice(children).children.append(node)
    return node


def all_nodes(root):
    seen = {}
    pending = [root]
    while pending:
        node = pending.pop()
        if id(node) not in seen:
            seen[id(node)] = node
            pending.extend(node.children)
    return list(seen.values())


def reference_children(node):
    """The children snapshotTree should see, with layout containers flattened by the same rule."""
    flat = []
    for child in node.children:
        if is_layout(child) and "isLayoutOnly" not in child.fail:
            flat.extend(reference_children(child))
        else:
            flat.append(child)
    return flat


def random_limits(rng):
    return {
        "maxNodes": rng.randint(0, 30),
        "maxDepth": rng.randint(0, 5),
        "headChildren": rng.randint(0, 3),
        "tailChildren": rng.randint(0, 3),
        "timeBudgetSeconds": rng.choice([0.05, 3.0]),
        "maxNesting": rng.randint(1, 8),
    }


def tick_clock(monkeypatch):
    # Each look at the clock takes a millisecond, so time budgets run out deterministically.
    ticks = iter(range(10**9))
    monkeypatch.setattr(treeWalk.time, "monotonic", lambda: next(ticks) / 1000)


@pytest.mark.parametrize("seed", range(300))
def test_random_trees_with_failures_match_a_reference_walk(seed, monkeypatch):
    tick_clock(monkeypatch)
    rng = random.Random(seed)
    root = random_tree(rng, iter(range(10**6)))
    nodes = all_nodes(root)
    by_key = {node.key: node for node in nodes}
    focus = rng.choice(nodes) if rng.random() < 0.7 else None
    callbacks = Callbacks(focus)
    result = snapshot(root, callbacks, **random_limits(rng))
    describe_order = [node.key for node in callbacks.asked("describe") if "describe" not in node.fail]
    if result["tree"]["role"] == "unknown":
        assert "describe" in root.fail
        return

    def flagged(obj, parent_flagged):
        """Whether the walk knows obj is on the focus path."""
        return parent_flagged and on_focus_path(obj, focus) and "isOnFocusPath" not in obj.fail

    def check(node, obj, is_flagged):
        assert node["key"] == obj.key
        expected = reference_children(obj)
        children = node.get("children", [])
        kept = [by_key[child["key"]] for child in children]
        # Every kept child is the object at its index, counted from the start or from the end, and only once.
        for child, kept_obj in zip(children, kept):
            assert expected[child["index"]] is kept_obj
        assert len({id(kept_obj) for kept_obj in kept}) == len(kept)
        if "cut" not in node:
            # Read completely: every child is there, in order.
            assert child_indexes(node) == list(range(len(expected)))
        focus_children = [kept_obj for kept_obj in kept if flagged(kept_obj, is_flagged)]
        if focus_children:
            # The child on the way to the focus was described before its siblings.
            first = min(describe_order.index(kept_obj.key) for kept_obj in kept)
            assert describe_order.index(focus_children[0].key) == first
        for child, kept_obj in zip(children, kept):
            check(child, kept_obj, flagged(kept_obj, is_flagged))

    root_flagged = on_focus_path(root, focus) and "isOnFocusPath" not in root.fail
    check(result["tree"], root, root_flagged)


@pytest.mark.parametrize("seed", range(200))
def test_random_broken_trees_never_raise(seed, monkeypatch):
    tick_clock(monkeypatch)
    rng = random.Random(seed)
    root = random_tree(rng, iter(range(10**6)), cycles=True)
    nodes = all_nodes(root)
    focus = rng.choice(nodes) if rng.random() < 0.7 else None
    # check_snapshot runs inside snapshot.
    snapshot(root, Callbacks(focus), **random_limits(rng))
