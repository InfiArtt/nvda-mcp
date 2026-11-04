from dataclasses import dataclass, field

import treeWalk
from treeWalk import searchTrees, walkTree


@dataclass(eq=False)
class Node:
    role: str
    name: str = ""
    children: list["Node"] = field(default_factory=list)
    next: "Node | None" = None

    def __post_init__(self):
        for child, following in zip(self.children, self.children[1:]):
            child.next = following


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
