"""Compares two snapshots of the accessibility tree, taken before and after an interaction.

The add-on reads part of the tree twice (treeWalk.snapshotTree). Web apps such as WhatsApp Web rebuild, scroll
and recycle their rows all the time, and a walk with a budget reads only part of a long list, so something is
reported as added or removed only when the place where it was, or would be, was read both times. Everything
else is listed as not compared.
"""

import difflib
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from nvda_mcp.scenario import text_normaliser

# Roles whose children scroll, so that rows leaving at one end and arriving at the other are one change.
LIST_ROLES = frozenset(
    {
        "list",
        "table",
        "grid",
        "tree",
        "treeview",
        "tree view",
        "tree grid",
        "treegrid",
        "listbox",
        "list box",
        "menu",
        "tab control",
        "data grid",
    }
)
# Names in context labels and subjects are cut to this many characters.
MAX_LABEL_NAME = 50
# Longer texts show only the part that changed, with this many characters around it.
LONG_TEXT = 60
TEXT_CONTEXT = 15
# More changes than this of the same kind and role in one place are merged into one line.
MERGE_ABOVE = 5
MAX_EXAMPLES = 3
# Unnamed objects are recognized by the names of their first few named descendants.
CONTENT_LABEL_NAMES = 3
SIMILAR_NAME_RATIO = 0.6
# How many objects ahead an object without an id looks for one with a similar name.
SIMILAR_LOOKAHEAD = 8
# How many positions an object recreated with a new accessible id may have moved.
RECREATED_MAX_SHIFT = 5
# Changes about an object's children as a whole; one per object, so never merged.
_CONTAINER_KINDS = frozenset({"scrolled", "replaced", "reused", "child count"})
# Kinds whose examples in a merged line need only the subject.
_SUBJECT_ONLY_KINDS = frozenset({"states", "added", "removed", "recreated", "exposed", "unexposed"})

ROOT_GONE_NOTE = (
    "The root object is gone or was replaced (for example by a page reload), so nothing was compared."
)
ROOT_GONE_LINE = (
    "The recorded object no longer exists (it is gone or was replaced, for example by a page reload), "
    "so nothing was compared."
)


@dataclass
class Change:
    """One change, or several of the same kind merged into one line when count is more than 1."""

    kind: str
    context: str
    subject: str
    detail: str = ""
    count: int = 1
    examples: list[str] = field(default_factory=list)


@dataclass
class TreeDiff:
    changes: list[Change]
    before_count: int
    after_count: int
    matched: int
    matched_by_key: int
    # Human-readable notes about parts that could not be compared.
    not_compared: list[str] = field(default_factory=list)
    root_gone: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [asdict(change) for change in self.changes],
            "beforeCount": self.before_count,
            "afterCount": self.after_count,
            "matched": self.matched,
            "matchedByKey": self.matched_by_key,
            "notCompared": list(self.not_compared),
            "rootGone": self.root_gone,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TreeDiff":
        return cls(
            changes=[Change(**change) for change in data["changes"]],
            before_count=data["beforeCount"],
            after_count=data["afterCount"],
            matched=data["matched"],
            matched_by_key=data["matchedByKey"],
            not_compared=list(data["notCompared"]),
            root_gone=data["rootGone"],
        )


def diff_snapshots(before: dict, after: dict, ignore: str | None = None) -> TreeDiff:
    """What changed between two snapshots of the same part of the tree.

    :param before: A snapshot taken before the interaction.
    :param after: A snapshot of the same root taken after it.
    :param ignore: A regular expression, already validated, for text that changes by itself such as clocks;
        matches are replaced by "…" before names, values and descriptions are compared.
    """
    return _Differ(before, after, ignore).run()


def changes_markdown(diff: TreeDiff, max_changes: int = 40) -> list[str]:
    """The diff as lines of markdown: a summary, the changes grouped by where they happened, then notes."""
    if diff.root_gone:
        return [ROOT_GONE_LINE]
    notes = [f"Not compared: {note}" for note in diff.not_compared]
    if not diff.changes:
        if notes:
            return ["No changes found in the parts that could be compared.", *notes]
        return ["No changes in the tree."]
    total = sum(change.count for change in diff.changes)
    header = (
        f"{_plural(total, 'change')}; {_plural(diff.before_count, 'object')} before, {diff.after_count} after; "
        f"{diff.matched} matched, {diff.matched_by_key} by accessible id."
    )
    lines = [header]
    context = None
    shown = 0
    explained_positions = False
    for change in diff.changes:
        if shown >= max_changes:
            break
        if change.context != context:
            context = change.context
            lines.append(f"In {context}:")
        line = _change_line(change)
        if change.kind == "moved" and not explained_positions:
            # Positions count objects in the accessibility tree, as browse mode shows them; said once.
            line += " (positions in browse mode order)"
            explained_positions = True
        lines.append(f"- {line}")
        shown += 1
    if shown < len(diff.changes):
        more = sum(change.count for change in diff.changes[shown:])
        lines.append(
            f"…and {more} more {'change' if more == 1 else 'changes'}; "
            "raise max_changes or record a smaller part with id."
        )
    return lines + notes


def _change_line(change: Change) -> str:
    if change.count > 1:
        text = f"{change.kind}: {change.subject}"
        if change.detail:
            text += f" {change.detail}"
        if change.examples:
            text += ", such as " + "; ".join(change.examples)
        return text
    return f"{change.kind}: " + " ".join(part for part in (change.subject, change.detail) if part)


class _Node:
    """One object of a snapshot, with what the diff learns about it."""

    def __init__(self, raw: dict[str, Any], parent: "_Node | None", normal: Callable[[str], str]) -> None:
        self.raw = raw
        self.parent = parent
        key = raw.get("key")
        self.key = key if isinstance(key, str) and key else None
        self.role = _text(raw.get("role")) or "object"
        self.name = _text(raw.get("name"))
        self.value = _text(raw.get("value"))
        self.description = _text(raw.get("description"))
        self.norm_name = normal(self.name)
        self.norm_value = normal(self.value)
        self.norm_description = normal(self.description)
        states = raw.get("states")
        self.states = frozenset(
            str(state) for state in (states if isinstance(states, list) else ()) if state != "focused"
        )
        self.index = _integer(raw.get("index"))
        self.cut = str(raw["cut"]) if raw.get("cut") else None
        self.child_count = _integer(raw.get("childCount"))
        self.children: list[_Node] = []
        self.match: _Node | None = None
        # How it was matched: "root", "key", "structure" or "recreated".
        self.how = ""
        # Position in the snapshot's document order, and how many objects its subtree holds.
        self.order = 0
        self.size = 1
        # Whether this object, or one inside it, was not read completely.
        self.cut_inside = False
        # Position among the parent's children counted from the start (0, 1, ...) or from the end (-1 is last);
        # None when it is not known, such as from the end of a list whose end was not read.
        self.head_pos: int | None = None
        self.tail_pos: int | None = None
        self._content: tuple[str, str] | None = None

    def content(self) -> tuple[str, str]:
        """The names of the first named objects inside it, normalised and as shown."""
        if self._content is None:
            normal: list[str] = []
            shown: list[str] = []
            for node in _descendants(self):
                if node.name:
                    normal.append(node.norm_name)
                    shown.append(node.name)
                    if len(shown) == CONTENT_LABEL_NAMES:
                        break
            self._content = (", ".join(normal), ", ".join(shown))
        return self._content

    @property
    def label_norm(self) -> str:
        return self.norm_name or self.content()[0]

    @property
    def signature(self) -> tuple[str, str, str]:
        if self.norm_name:
            return (self.role, "name", self.norm_name)
        return (self.role, "content", self.content()[0])


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _descendants(node: _Node) -> Iterator[_Node]:
    """The objects inside node, in document order."""
    stack = node.children[::-1]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children[::-1])


def _ancestors(node: _Node) -> Iterator[_Node]:
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _build(tree: Any, normal: Callable[[str], str]) -> list[_Node]:
    """The snapshot's objects in document order; the root first."""
    root = _Node(tree if isinstance(tree, dict) else {}, None, normal)
    root.index = 0
    nodes: list[_Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        node.order = len(nodes)
        nodes.append(node)
        raw_children = node.raw.get("children")
        if not isinstance(raw_children, list):
            continue
        children = [_Node(raw, node, normal) for raw in raw_children if isinstance(raw, dict)]
        for position, child in enumerate(children):
            if child.index is None:
                child.index = position
        children.sort(key=lambda child: (child.index < 0, child.index))
        node.children = children
        _set_positions(node)
        stack.extend(reversed(children))
    for node in reversed(nodes):
        node.size = 1 + sum(child.size for child in node.children)
        node.cut_inside = node.cut is not None or any(child.cut_inside for child in node.children)
    return nodes


def _set_positions(node: _Node) -> None:
    # Children of an object read completely are known from both ends, so a list read whole can be
    # compared with the head and the tail of the same list read with its middle skipped.
    from_both_ends = node.cut is None and all(child.index >= 0 for child in node.children)
    count = len(node.children)
    for position, child in enumerate(node.children):
        if child.index >= 0:
            child.head_pos = child.index
            if from_both_ends:
                child.tail_pos = position - count
        else:
            child.tail_pos = child.index


def _position(node: _Node, region: str) -> int | None:
    return node.head_pos if region == "head" else node.tail_pos


def _compatible(before: _Node, after: _Node) -> bool:
    """Whether two objects may be the same one: objects with different accessible ids never are."""
    return before.key is None or after.key is None or before.key == after.key


def _all_read(parent: _Node, region: str, low: int, high: int) -> bool:
    """Whether every child of parent between positions low and high (both excluded) was read."""
    if low >= high or high - low - 1 > len(parent.children):
        return False
    read = {_position(child, region) for child in parent.children}
    return all(position in read for position in range(low + 1, high))


def _reads_to_end(node: _Node) -> bool:
    return node.cut is None or (node.cut == "gap" and any(child.index < 0 for child in node.children))


def _longest_increasing(values: list[int]) -> set[int]:
    """Indexes into values of one longest strictly increasing subsequence."""
    tails: list[int] = []
    previous = [-1] * len(values)
    for index, value in enumerate(values):
        place = bisect_left(tails, value, key=lambda tail: values[tail])
        if place:
            previous[index] = tails[place - 1]
        if place == len(tails):
            tails.append(index)
        else:
            tails[place] = index
    result = set()
    index = tails[-1] if tails else -1
    while index >= 0:
        result.add(index)
        index = previous[index]
    return result


def _similar(first: str, second: str) -> bool:
    matcher = difflib.SequenceMatcher(None, first, second, autojunk=False)
    # The quick upper bounds first, as difflib.get_close_matches does: long lists compare many pairs.
    return (
        matcher.real_quick_ratio() >= SIMILAR_NAME_RATIO
        and matcher.quick_ratio() >= SIMILAR_NAME_RATIO
        and matcher.ratio() >= SIMILAR_NAME_RATIO
    )


def _clip(text: str, limit: int = MAX_LABEL_NAME) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _quoted(text: str, empty: str) -> str:
    return f'"{text}"' if text else empty


def _label(node: _Node, contents: bool = True) -> str:
    """How a change names the object: role "name", or what is inside when it has no name."""
    if node.name:
        return f'{node.role} "{_clip(node.name)}"'
    shown = node.content()[1] if contents else ""
    return f'{node.role} (no name) containing "{_clip(shown)}"' if shown else f"{node.role} (no name)"


def _context_label(node: _Node) -> str:
    """Where a change happened: role "name" of the object, or of its nearest named ancestor."""
    if node.name:
        return f'{node.role} "{_clip(node.name)}"'
    ancestor = next((ancestor for ancestor in _ancestors(node) if ancestor.name), None)
    if ancestor is None:
        return f"{node.role} (no name)"
    return f'{node.role} (no name) in {ancestor.role} "{_clip(ancestor.name)}"'


def _short_name(node: _Node) -> str:
    shown = node.name or node.content()[1]
    return f'"{_clip(shown, 40)}"' if shown else node.role


def _span(nodes: list[_Node]) -> str:
    if len(nodes) == 1:
        return _short_name(nodes[0])
    return f"{_short_name(nodes[0])} to {_short_name(nodes[-1])}"


def _excerpts(old: str, new: str) -> tuple[str, str]:
    """Both texts, or for long ones only the part that changed with some context around it."""
    if len(old) <= LONG_TEXT and len(new) <= LONG_TEXT:
        return old, new
    shortest = min(len(old), len(new))
    prefix = 0
    while prefix < shortest and old[prefix] == new[prefix]:
        prefix += 1
    suffix = 0
    while suffix < shortest - prefix and old[-1 - suffix] == new[-1 - suffix]:
        suffix += 1

    def excerpt(text: str) -> str:
        start = max(0, prefix - TEXT_CONTEXT)
        end = min(len(text), len(text) - suffix + TEXT_CONTEXT)
        return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")

    return excerpt(old), excerpt(new)


def _inside(node: _Node) -> str:
    """How many objects a removed or added object holds, and some of their names."""
    inside = node.size - 1
    if not inside:
        return "(contents not read)" if node.cut_inside else ""
    names = []
    for descendant in _descendants(node):
        if descendant.name:
            names.append(f'"{_clip(descendant.name, 40)}"')
            if len(names) == MAX_EXAMPLES:
                break
    text = ("at least " if node.cut_inside else "") + _plural(inside, "object") + " inside"
    if names:
        text += ", such as " + ", ".join(names)
    return f"({text})"


def _examples(subjects: list[str]) -> str:
    text = ", ".join(subjects[:MAX_EXAMPLES])
    if len(subjects) > MAX_EXAMPLES:
        text += f" and {len(subjects) - MAX_EXAMPLES} more"
    return text


class _Differ:
    def __init__(self, before: dict, after: dict, ignore: str | None) -> None:
        normal = text_normaliser(ignore, collapse_whitespace=True)
        self.before = before
        self.after = after
        self.before_nodes = _build(before.get("tree"), normal)
        self.after_nodes = _build(after.get("tree"), normal)
        self.matched = 0
        self.matched_by_key = 0
        # (document order, role, change); sorted and grouped at the end.
        self.entries: list[tuple[tuple[int, int, int], str, Change]] = []
        # Unmatched objects that could not be compared: (reason, context, subject, document order).
        self.pending: list[tuple[str, str, str, tuple[int, int, int]]] = []
        # Reused rows: what is inside them is other content, so it is not compared.
        self.suppressed: set[_Node] = set()
        # Objects reported as exposed or unexposed; the items they wrap did not move.
        self.wrappers: set[_Node] = set()

    def run(self) -> TreeDiff:
        before_root = self.before_nodes[0]
        after_root = self.after_nodes[0]
        before_count, after_count = len(self.before_nodes), len(self.after_nodes)
        if self._root_gone(before_root, after_root):
            return TreeDiff([], before_count, after_count, 0, 0, [ROOT_GONE_NOTE], root_gone=True)
        self._match_keys(before_root, after_root)
        # Parents come before their children, so objects matched here have their own children aligned later.
        for node in self.before_nodes:
            if node.match is not None and node.children and node.match.children:
                self._align_children(node, node.match)
        for node in self.after_nodes:
            if node.match is not None and not self._suppressed(node):
                self._report_pair(node.match, node)
                self._report_children(node.match, node)
        return TreeDiff(
            self._grouped_changes(),
            before_count,
            after_count,
            self.matched,
            self.matched_by_key,
            self._notes(),
        )

    def _root_gone(self, before_root: _Node, after_root: _Node) -> bool:
        if self.after.get("alive") is False:
            return True
        if before_root.key and after_root.key and before_root.key != after_root.key:
            return True
        # An object that died reads as an unknown object with nothing inside, often without its id;
        # comparing it would report everything as removed.
        return (
            after_root.role == "unknown"
            and before_root.role != "unknown"
            and not after_root.name
            and not after_root.children
        )

    # Matching

    def _pair(self, before: _Node, after: _Node, how: str) -> None:
        before.match, after.match = after, before
        before.how = after.how = how
        self.matched += 1
        if how == "key":
            self.matched_by_key += 1

    def _match_keys(self, before_root: _Node, after_root: _Node) -> None:
        same_key = before_root.key is not None and before_root.key == after_root.key
        self._pair(before_root, after_root, "key" if same_key else "root")
        before_keys = Counter(node.key for node in self.before_nodes if node.key)
        after_keys = Counter(node.key for node in self.after_nodes if node.key)
        after_by_key = {node.key: node for node in self.after_nodes if node.key and after_keys[node.key] == 1}
        for node in self.before_nodes:
            if node.match is None and node.key and before_keys[node.key] == 1:
                other = after_by_key.get(node.key)
                if other is not None and other.match is None:
                    self._pair(node, other, "key")

    def _align_children(self, before: _Node, after: _Node) -> None:
        self._align(
            [child for child in before.children if child.head_pos is not None],
            [child for child in after.children if child.head_pos is not None],
        )
        if before.cut is not None or after.cut is not None:
            # Children read from the end of a long list are aligned from the end.
            self._align(
                [child for child in reversed(before.children) if child.tail_pos is not None],
                [child for child in reversed(after.children) if child.tail_pos is not None],
            )
        self._pair_recreated(before, after)
        self._pair_wrapped(before, after)

    def _align(self, before: list[_Node], after: list[_Node]) -> None:
        if not any(node.match is None for node in before) or not any(node.match is None for node in after):
            return

        def token(node: _Node, other: _Node | None) -> tuple:
            # Children already matched align only with their own counterpart.
            return ("=", id(other)) if other is not None else ("~", *node.signature)

        matcher = difflib.SequenceMatcher(
            None,
            [token(node, node if node.match is not None else None) for node in before],
            [token(node, node.match) for node in after],
            autojunk=False,
        )
        for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
            if tag == "equal":
                for old, new in zip(before[before_start:before_end], after[after_start:after_end]):
                    if old.match is None and new.match is None and _compatible(old, new):
                        self._pair(old, new, "structure")
            elif tag == "replace":
                self._pair_similar(before[before_start:before_end], after[after_start:after_end])

    def _pair_similar(self, before: list[_Node], after: list[_Node]) -> None:
        """Pairs objects of the same role whose names are similar, keeping their order.

        Each takes the first similar one left, so that rows renamed in place pair up one to one even when
        their names are all alike, as "Chat 1" and "Chat 10" are. Only the next few are tried, which keeps
        a long list whose items all changed quick to compare.
        """
        start = 0
        for old in before:
            if old.match is not None:
                continue
            for index in range(start, min(len(after), start + SIMILAR_LOOKAHEAD)):
                new = after[index]
                if new.match is not None or new.role != old.role or not _compatible(old, new):
                    continue
                if _similar(old.label_norm, new.label_norm):
                    self._pair(old, new, "structure")
                    start = index + 1
                    break

    def _pair_recreated(self, before: _Node, after: _Node) -> None:
        """Pairs objects that got a new accessible id but have the same role and name in about the same place."""
        old_children = [child for child in before.children if child.match is None and child.key]
        new_children = [child for child in after.children if child.match is None and child.key]
        if not old_children or not new_children:
            return
        for old in old_children:
            # Without a name or content to go by, only the very same position will do.
            limit = RECREATED_MAX_SHIFT if old.label_norm else 0
            best, best_shift = None, limit + 1
            for new in new_children:
                if new.match is not None or new.key == old.key or new.signature != old.signature:
                    continue
                shift = self._shift(old, new)
                if shift is not None and shift < best_shift:
                    best, best_shift = new, shift
            if best is not None:
                self._pair(old, best, "recreated")

    @staticmethod
    def _shift(old: _Node, new: _Node) -> int | None:
        for region in ("head", "tail"):
            old_position, new_position = _position(old, region), _position(new, region)
            if old_position is not None and new_position is not None:
                return abs(old_position - new_position)
        return None

    def _pair_wrapped(self, before: _Node, after: _Node) -> None:
        """Pairs children that moved into a new wrapper object, or out of one that went away, without ids."""
        for wrapper in after.children:
            if wrapper.match is None and wrapper.children:
                candidates = [child for child in before.children if child.match is None]
                self._pair_wrapper_children(wrapper, candidates, before, wrapper_is_new=True)
        for wrapper in before.children:
            if wrapper.match is None and wrapper.children:
                candidates = [child for child in after.children if child.match is None]
                self._pair_wrapper_children(wrapper, candidates, after, wrapper_is_new=False)

    def _pair_wrapper_children(
        self, wrapper: _Node, candidates: list[_Node], counterpart: _Node, wrapper_is_new: bool
    ) -> None:
        inner = [child for child in wrapper.children if child.match is None]
        if not inner or not candidates:
            return
        if any(
            child.match is not None and child.match.parent is not counterpart for child in wrapper.children
        ):
            return
        signatures = {node.signature for node in candidates}
        if any(child.signature not in signatures for child in inner):
            return
        old, new = (candidates, inner) if wrapper_is_new else (inner, candidates)
        matcher = difflib.SequenceMatcher(
            None, [node.signature for node in old], [node.signature for node in new], autojunk=False
        )
        pairs = []
        for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
            if tag == "equal":
                pairs += [
                    (first, second)
                    for first, second in zip(old[old_start:old_end], new[new_start:new_end])
                    if _compatible(first, second)
                ]
        # All or nothing: a wrapper only some of whose children were here before is a new object.
        if len(pairs) == len(inner):
            for first, second in pairs:
                self._pair(first, second, "structure")

    # Reporting

    def _add(
        self, kind: str, context: str, subject: str, detail: str, order: tuple[int, int, int], role: str
    ) -> None:
        self.entries.append((order, role, Change(kind, context, subject, detail)))

    def _suppressed(self, node: _Node) -> bool:
        return node in self.suppressed or any(ancestor in self.suppressed for ancestor in _ancestors(node))

    def _report_pair(self, before: _Node, after: _Node) -> None:
        context = _context_label(after.parent) if after.parent is not None else _context_label(after)
        order = (after.order, 0, 0)
        if after.how == "recreated" and not any(
            ancestor.how == "recreated" for ancestor in _ancestors(after)
        ):
            inside = after.size - 1
            detail = "as a new accessible object"
            if inside:
                detail += f", with {_plural(inside, 'object')} inside"
            self._add("recreated", context, _label(after), detail, order, after.role)
        if (
            after.parent is not None
            and before.parent is not None
            and before.parent.match is not after.parent
            and not self._wrapped(before, after)
        ):
            self._add(
                "moved here",
                context,
                _label(after),
                f"from {_context_label(before.parent)}",
                order,
                after.role,
            )
        if before.role != after.role:
            self._add("role", context, _label(before), f"changed to {after.role}", order, after.role)
        if before.norm_name != after.norm_name:
            old, new = _excerpts(before.name, after.name)
            subject = f"{after.role} {_quoted(old, '(no name)')}"
            self._add("renamed", context, subject, f"to {_quoted(new, '(no name)')}", order, after.role)
        for kind, old, new, old_normal, new_normal in (
            ("value", before.value, after.value, before.norm_value, after.norm_value),
            (
                "description",
                before.description,
                after.description,
                before.norm_description,
                after.norm_description,
            ),
        ):
            if old_normal != new_normal:
                old, new = _excerpts(old, new)
                detail = f"from {_quoted(old, '(empty)')} to {_quoted(new, '(empty)')}"
                self._add(kind, context, _label(after), detail, order, after.role)
        gained, lost = after.states - before.states, before.states - after.states
        if (gained or lost) and not self._inherited(after, gained, lost):
            parts = []
            if gained:
                parts.append("now " + ", ".join(sorted(gained)))
            if lost:
                parts.append("no longer " + ", ".join(sorted(lost)))
            self._add("states", context, _label(after), "; ".join(parts), order, after.role)

    def _wrapped(self, before: _Node, after: _Node) -> bool:
        """Whether the pair only went into a wrapper that appeared, or out of one that went away."""
        # Wrappers are always children of a matched parent.
        new_parent, old_parent = after.parent, before.parent
        went_in = new_parent in self.wrappers and old_parent.match is new_parent.parent
        came_out = old_parent in self.wrappers and old_parent.parent.match is new_parent
        return went_in or came_out

    @staticmethod
    def _inherited(after: _Node, gained: frozenset, lost: frozenset) -> bool:
        """Whether the parent's states changed the same way, as when a whole row goes off screen."""
        parent = after.parent
        if parent is None or parent.match is None:
            return False
        return (parent.states - parent.match.states, parent.match.states - parent.states) == (gained, lost)

    def _report_children(self, before: _Node, after: _Node) -> None:
        context = _context_label(after)
        if before.cut == "depth" or after.cut == "depth":
            self.pending.append(("depth", context, _label(after), (after.order, 0, 2)))
            self._report_child_count(before, after, context, 0)
            return
        gone = [child for child in before.children if child.match is None]
        new = [child for child in after.children if child.match is None]
        for wrapper in new:
            if wrapper.children and all(
                child.match is not None and child.match.parent is before for child in wrapper.children
            ):
                self.wrappers.add(wrapper)
                detail = f"now wraps its {_plural(len(wrapper.children), 'item')}"
                self._add("exposed", context, _label(wrapper), detail, (wrapper.order, 0, 0), wrapper.role)
        for wrapper in gone:
            if wrapper.children and all(
                child.match is not None and child.match.parent is after for child in wrapper.children
            ):
                self.wrappers.add(wrapper)
                detail = f"no longer wraps its {_plural(len(wrapper.children), 'item')}"
                order = self._removed_order(wrapper, before, after)
                self._add("unexposed", context, _label(wrapper), detail, order, wrapper.role)
        gone = [child for child in gone if child not in self.wrappers]
        new = [child for child in new if child not in self.wrappers]
        if before.role.lower() in LIST_ROLES or after.role.lower() in LIST_ROLES:
            self._report_reuse(before, after, context)
            if self._report_scroll(before, after, gone, new, context):
                gone, new = [], []
        self._report_moves(before, after, context)
        removed = added = 0
        for child in gone:
            order = self._removed_order(child, before, after)
            if after.cut is None or self._between_matched(child, before, after):
                self._add(
                    "removed", context, _label(child, contents=False), _inside(child), order, child.role
                )
                removed += 1
            else:
                self.pending.append(("before only", context, _label(child), order))
        for child in new:
            order = (child.order, 0, 0)
            if (
                before.cut is None
                or self._between_matched(child, after, before)
                or self._appended(child, after, before)
            ):
                self._add("added", context, _label(child, contents=False), _inside(child), order, child.role)
                added += 1
            else:
                self.pending.append(("after only", context, _label(child), order))
        self._report_child_count(before, after, context, added - removed)

    @staticmethod
    def _removed_order(child: _Node, before: _Node, after: _Node) -> tuple[int, int, int]:
        """Where a before-only child goes in the after document order: after its previous matched sibling."""
        anchor = after.order
        for sibling in before.children:
            if sibling is child:
                break
            if sibling.match is not None and sibling.match.parent is after:
                anchor = sibling.match.order + sibling.match.size - 1
        return (anchor, 1, child.order)

    @staticmethod
    def _between_matched(child: _Node, parent: _Node, other: _Node) -> bool:
        """Whether child lies between two siblings matched to children of other, all read between those."""
        for region in ("head", "tail"):
            position = _position(child, region)
            if position is None:
                continue
            left = right = None
            for sibling in parent.children:
                partner = sibling.match
                if partner is None or partner.parent is not other:
                    continue
                mine, theirs = _position(sibling, region), _position(partner, region)
                if mine is None or theirs is None:
                    continue
                if mine < position and (left is None or mine > _position(left, region)):
                    left = sibling
                if mine > position and (right is None or mine < _position(right, region)):
                    right = sibling
            if (
                left is not None
                and right is not None
                and _all_read(other, region, _position(left.match, region), _position(right.match, region))
            ):
                return True
        return False

    @staticmethod
    def _appended(child: _Node, after: _Node, before: _Node) -> bool:
        """Whether child comes after the last matched child read from the end, as a message added to a chat."""
        if child.tail_pos is None:
            return False
        last = None
        for sibling in after.children:
            partner = sibling.match
            if partner is None or partner.parent is not before or sibling.tail_pos is None:
                continue
            if partner.tail_pos is None:
                continue
            if sibling.tail_pos > child.tail_pos:
                return False
            if last is None or sibling.tail_pos > last.tail_pos:
                last = sibling
        # Before, everything from that sibling to the end of the list must have been read.
        return last is not None and _all_read(before, "tail", last.match.tail_pos, 0)

    def _report_scroll(
        self, before: _Node, after: _Node, gone: list[_Node], new: list[_Node], context: str
    ) -> bool:
        if not gone or not new:
            return False
        old_children, new_children = before.children, after.children
        order = (after.order, 0, 1)
        if not any(child.match is not None and child.match.parent is after for child in old_children):
            if len(gone) != len(old_children) or len(new) != len(new_children):
                return False
            if len(old_children) == len(new_children):
                detail = f"all {len(old_children)} read items are different (scrolled or reloaded)"
            else:
                detail = (
                    f"all read items are different, {len(old_children)} before and {len(new_children)} after "
                    "(scrolled or reloaded)"
                )
            detail += f"; before {_span(gone)}, after {_span(new)}"
            self._add("replaced", context, "", detail, order, after.role)
            return True
        left, came = len(gone), len(new)
        # Items can be said to have come in at an end only if that end was read before.
        if old_children[:left] == gone and new_children[-came:] == new and _reads_to_end(before):
            detail = f"{left} left at the start ({_span(gone)}), {came} came in at the end ({_span(new)})"
        elif old_children[-left:] == gone and new_children[:came] == new and _reads_to_end(after):
            detail = f"{left} left at the end ({_span(gone)}), {came} came in at the start ({_span(new)})"
        else:
            return False
        self._add("scrolled", context, "", detail, order, after.role)
        return True

    def _report_reuse(self, before: _Node, after: _Node, context: str) -> None:
        """Virtual lists keep their row objects and give them other content when they scroll."""
        changed = [
            (child, child.match)
            for child in before.children
            if child.how == "key"
            and child.match.parent is after
            and child.label_norm != child.match.label_norm
        ]
        if len(changed) < 3:
            return
        position = {child: index for index, child in enumerate(before.children)}
        by_label: dict[str, list[_Node]] = {}
        for child in before.children:
            by_label.setdefault(child.label_norm, []).append(child)
        offsets = []
        for old, new in changed:
            others = [child for child in by_label.get(new.label_norm, ()) if child is not old]
            if new.label_norm and others:
                nearest = min(others, key=lambda child: abs(position[child] - position[old]))
                offsets.append(position[nearest] - position[old])
        if len(offsets) * 2 < len(changed):
            return
        shift = Counter(offsets).most_common(1)[0][0]
        direction = "toward the end" if shift > 0 else "toward the start"
        role = Counter(new.role for _, new in changed).most_common(1)[0][0]
        self.suppressed.update(new for _, new in changed)
        subject = _plural(len(changed), f"{role} object")
        detail = f"now show other content, likely scrolled by {abs(shift)} {direction}"
        self._add("reused", context, subject, detail, (after.order, 0, 1), role)

    def _report_moves(self, before: _Node, after: _Node, context: str) -> None:
        pairs = [
            (child, child.match)
            for child in before.children
            if child.how == "key" and child.match.parent is after
        ]
        done: set[_Node] = set()
        for region in ("head", "tail"):
            chosen = [
                (old, new)
                for old, new in pairs
                if old not in done
                and _position(old, region) is not None
                and _position(new, region) is not None
            ]
            chosen.sort(key=lambda pair: _position(pair[0], region))
            # The longest run that kept its order stayed; the others moved. A chat jumping to the top is one move.
            kept = _longest_increasing([_position(new, region) for _, new in chosen])
            for index, (old, new) in enumerate(chosen):
                done.add(old)
                if index not in kept:
                    if region == "head":
                        detail = f"from position {old.head_pos + 1} to {new.head_pos + 1}"
                    else:
                        detail = f"from position {-old.tail_pos} from the end to {-new.tail_pos} from the end"
                    self._add("moved", context, _label(new), detail, (new.order, 0, 0), new.role)

    def _report_child_count(self, before: _Node, after: _Node, context: str, explained: int) -> None:
        if before.cut is None and after.cut is None:
            return
        if before.child_count is None or after.child_count is None:
            return
        difference = after.child_count - before.child_count
        # What was not explained by children reported as added or removed.
        rest = difference - explained
        if difference and rest:
            more = "more" if rest > 0 else "fewer"
            children = "child" if abs(rest) == 1 else "children"
            detail = f"{abs(rest)} {more} {children} than before (not read)"
            self._add("child count", context, "", detail, (after.order, 0, 1), after.role)

    # Results

    def _grouped_changes(self) -> list[Change]:
        groups: dict[str, list[tuple[str, Change]]] = {}
        for _, role, change in sorted(self.entries, key=lambda entry: entry[0]):
            groups.setdefault(change.context, []).append((role, change))
        changes: list[Change] = []
        for items in groups.values():
            changes.extend(_merge(items))
        return changes

    def _notes(self) -> list[str]:
        notes = []
        for side, other, snapshot in (("before", "after", self.before), ("after", "before", self.after)):
            truncated = snapshot.get("truncated")
            if truncated:
                notes.append(
                    f"The {side} walk stopped early ({truncated}); parts read only {other} were not compared."
                )
        pending = sorted(self.pending, key=lambda entry: entry[3])
        depth = [subject for reason, _, subject, _ in pending if reason == "depth"]
        if len(depth) == 1:
            notes.append(f"What is inside {depth[0]} (the depth limit was reached there).")
        elif depth:
            notes.append(
                f"What is inside {len(depth)} objects at the depth limit, such as {_examples(depth)}."
            )
        groups: dict[tuple[str, str], list[str]] = {}
        for reason, context, subject, _ in pending:
            if reason != "depth":
                groups.setdefault((reason, context), []).append(subject)
        for (reason, context), subjects in groups.items():
            count = len(subjects)
            pronoun = "it" if count == 1 else "they"
            if reason == "before only":
                ending = f"that part was not read completely after, so {pronoun} may still be there"
            else:
                ending = f"that part was not read completely before, so {pronoun} may have been there already"
            notes.append(
                f"{_plural(count, 'object')} in {context} read only {reason.split()[0]} ({_examples(subjects)}): "
                f"{ending}."
            )
        return notes


def _merge(items: list[tuple[str, Change]]) -> list[Change]:
    """Merges more than MERGE_ABOVE changes of the same kind and role (and states) in one place into one line."""

    def key(role: str, change: Change) -> tuple | None:
        if change.kind in _CONTAINER_KINDS:
            return None
        return (change.kind, role, change.detail if change.kind == "states" else None)

    counts = Counter(key(role, change) for role, change in items)
    merged: dict[tuple, Change] = {}
    result = []
    for role, change in items:
        group = key(role, change)
        if group is None or counts[group] <= MERGE_ABOVE:
            result.append(change)
            continue
        line = merged.get(group)
        if line is None:
            line = Change(
                change.kind,
                change.context,
                _plural(counts[group], f"{role} object"),
                change.detail if change.kind == "states" else "",
                count=counts[group],
            )
            merged[group] = line
            result.append(line)
        if len(line.examples) < MAX_EXAMPLES:
            if change.kind in _SUBJECT_ONLY_KINDS:
                line.examples.append(change.subject)
            else:
                line.examples.append(" ".join(part for part in (change.subject, change.detail) if part))
    return result
