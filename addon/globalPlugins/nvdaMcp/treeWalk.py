# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Walking, snapshotting and searching an accessibility tree within limits.

This module does not import NVDA, so it can be unit tested on its own: the caller says how to
read an object's children, how to describe it, and whether it only exists for layout or matches a search.
"""

import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

T = TypeVar("T")

# Stands in for children left out by maxChildren. Compared by identity,
# since a real node also says "moreChildren" when its own children were cut.
_MORE_CHILDREN: dict[str, Any] = {"moreChildren": True}

# A child on the focus path that lies in the unread middle of a long list is still kept
# when it is among this many children from the start.
_FOCUS_SEARCH_CHILDREN = 500

# Reading an object's children stops when this many navigation steps through layout containers find no child.
# Going into and out of 100 levels of them takes about 200; a loop among sibling containers never ends otherwise.
_MAX_STEPS_WITHOUT_CHILD = 3000

# When several reasons apply to one snapshot node, "cut" keeps the one that says most about what is missing.
_CUT_RANK = {"gap": 1, "error": 2, "nesting": 3, "nodes": 4, "time": 4}


def walkTree(
	root: T,
	maxDepth: int,
	maxNodes: int,
	maxChildren: int | None,
	*,
	firstChild: Callable[[T], T | None],
	nextSibling: Callable[[T], T | None],
	describe: Callable[[T], dict[str, Any]],
	isLayoutOnly: Callable[[T], bool],
	childCount: Callable[[T], Any],
	timeBudgetSeconds: float,
	maxNesting: int,
) -> dict[str, Any]:
	"""Depth-first walk using firstChild/next, bounded by depth, node count and time.

	Unnamed layout containers below the root are left out and their children shown in their place,
	so depth and node limits are spent on objects a user would actually meet.
	:param maxChildren: Show at most this many children of any object, so one long list
		does not use up the node limit. The node says how many were left out.
	:param maxNesting: Guards against cycles in broken trees, since layout containers do not count towards depth.
	"""
	deadline = time.monotonic() + timeBudgetSeconds
	nodeCount = 0
	truncatedReason: str | None = None

	def childrenOf(obj: T, depth: int, nesting: int) -> list[dict[str, Any]]:
		nonlocal nodeCount, truncatedReason
		children: list[dict[str, Any]] = []
		child = firstChild(obj)
		while child is not None:
			if maxChildren is not None and len(children) >= maxChildren:
				children.append(_MORE_CHILDREN)
				break
			if nodeCount >= maxNodes:
				truncatedReason = f"stopped after {maxNodes} nodes"
				break
			if time.monotonic() > deadline:
				truncatedReason = f"stopped after {timeBudgetSeconds} seconds"
				break
			if nesting >= maxNesting:
				truncatedReason = f"stopped at {maxNesting} levels of nesting"
				break
			if isLayoutOnly(child):
				children.extend(childrenOf(child, depth, nesting + 1))
			else:
				children.append(visit(child, depth + 1, nesting + 1))
			child = nextSibling(child)
		return children

	def visit(obj: T, depth: int, nesting: int) -> dict[str, Any]:
		nonlocal nodeCount
		nodeCount += 1
		node = describe(obj)
		if depth < maxDepth:
			children = childrenOf(obj, depth, nesting)
			# A flattened layout container may have been cut short too, so look through the whole list.
			wasCut = any(child is _MORE_CHILDREN for child in children)
			children = [child for child in children if child is not _MORE_CHILDREN]
			if wasCut:
				count = childCount(obj)
				# childCount also counts layout containers, so the number is only a guide when children were flattened.
				hasCount = isinstance(count, int) and count > len(children)
				node["moreChildren"] = count - len(children) if hasCount else True
			if children:
				node["children"] = children
		return node

	tree = visit(root, 0, 0)
	return {"nodeCount": nodeCount, "truncated": truncatedReason, "tree": tree}


class _Reading:
	"""Why reading an object's children in one direction stopped before the last one, if it did."""

	__slots__ = ("cut", "note")

	def __init__(self) -> None:
		self.cut: str | None = None
		# For a "nesting" cut: what the snapshot says about it in "truncated".
		self.note: str | None = None


def _addCut(node: dict[str, Any], cut: str | None) -> None:
	"""Say why a node's children were not all read, keeping the more telling reason when there are several."""
	if cut is not None and _CUT_RANK[cut] > _CUT_RANK.get(node.get("cut"), 0):
		node["cut"] = cut


def _subtreeSize(node: dict[str, Any]) -> int:
	return 1 + sum(_subtreeSize(child) for child in node.get("children", ()))


def _withoutObjectsReadTwice(
	described: list[tuple[dict[str, Any], bool]],
) -> tuple[list[dict[str, Any]], int]:
	"""Leave out the second copy of an object read both from the start and from the end of its parent.

	NVDA hands out a new object each time one is reached, so a list that changed while it was read can
	give the same object twice; only its key tells. Keys are trusted only where each occurs once among
	the children read from the start and once among those read from the end: some applications, such as
	Java ones, give many objects the same key. The copy on the focus path is kept, else the one from the start.
	:return: The children to keep, and how many described nodes were left out.
	"""
	head = Counter(node.get("key") for node, _isFocus in described if node["index"] >= 0)
	tail = Counter(node.get("key") for node, _isFocus in described if node["index"] < 0)
	readTwice = {
		key for key, count in head.items() if isinstance(key, str) and count == 1 and tail.get(key) == 1
	}
	keepFromEnd = {node.get("key") for node, isFocus in described if isFocus and node["index"] < 0}
	kept: list[dict[str, Any]] = []
	dropped = 0
	for node, _isFocus in described:
		key = node.get("key")
		if key in readTwice and (node["index"] < 0) != (key in keepFromEnd):
			dropped += _subtreeSize(node)
			continue
		kept.append(node)
	return kept, dropped


def _documentOrder(index: int) -> tuple[bool, int]:
	"""Sort key: children read from the start (index >= 0), then those read from the end (-1 is the last)."""
	return index < 0, index


def snapshotTree(
	root: T,
	*,
	firstChild: Callable[[T], T | None],
	nextSibling: Callable[[T], T | None],
	lastChild: Callable[[T], T | None],
	previousSibling: Callable[[T], T | None],
	childCount: Callable[[T], Any],
	describe: Callable[[T], dict[str, Any]],
	isLayoutOnly: Callable[[T], bool],
	isOnFocusPath: Callable[[T], bool],
	maxNodes: int,
	maxDepth: int,
	headChildren: int,
	tailChildren: int,
	timeBudgetSeconds: float,
	maxNesting: int,
) -> dict[str, Any]:
	"""Snapshot the tree below root, so that it can be compared with a later snapshot of the same part.

	Each node says where it sits among its parent's children ("index") and, in "cut", why its children
	were not all read, so a comparison can tell an object that went away from one that was not read.
	Unnamed layout containers below the root are flattened as in walkTree, and do not count towards depth.
	The child on the way to the focus is read before its siblings, so when the node limit runs out,
	the parts farthest from the focus are the ones left out. Of a long list, only the first and last
	children are read, plus the child on the focus path when it is among the first 500. An object
	read both from the start and from the end (the list changed while it was read) is kept once.
	The navigation callbacks and childCount may raise: the children read so far are kept, the parent
	says "error" and the walk carries on. A child whose description fails is left out the same way.
	No exception escapes.
	:param childCount: How many children an object reports. Asked only at the depth limit
		and for objects whose children were not all read.
	:param describe: An object's description. "focused": True in it says the object is the focus,
		so its children are not searched for the focus path.
	:param isOnFocusPath: Whether an object is the focus or one of its ancestors. Asked only about
		the root and the children of objects on the focus path that are not the focus themselves.
	:param headChildren: When an object has more than headChildren + tailChildren children, read this many
		from the start (indexes 0 up)...
	:param tailChildren: ...and this many from the end (indexes -tailChildren to -1), and say "gap".
	:param maxNesting: Guards against cycles in broken trees, since layout containers do not count towards depth.
		A loop among sibling layout containers is stopped too, and also says "nesting".
	:return: {"nodeCount", "truncated", "tree"}: how many objects were described, why the walk stopped
		early if it did, and the root's node.
	"""
	deadline = time.monotonic() + timeBudgetSeconds
	head = max(headChildren, 0)
	tail = max(tailChildren, 0)
	nodeCount = 0
	truncated: str | None = None
	# "nodes" or "time" once a budget has run out: nothing more is read after that.
	stopped: str | None = None

	def outOfBudget(describing: bool) -> bool:
		"""Whether a budget has run out. describing: the caller is about to describe one more object."""
		nonlocal stopped, truncated
		if stopped is None:
			if describing and nodeCount >= maxNodes:
				stopped = "nodes"
				truncated = f"stopped after {maxNodes} nodes"
			elif time.monotonic() > deadline:
				stopped = "time"
				truncated = f"stopped after {timeBudgetSeconds} seconds"
		return stopped is not None

	def holds(predicate: Callable[[T], bool], obj: T) -> bool:
		try:
			return bool(predicate(obj))
		except Exception:  # noqa: BLE001 - applications raise COMError and others; treat all as "no"
			return False

	def countChildren(obj: T) -> int | None:
		"""How many children obj reports, or None when that is not a usable number. May raise."""
		count = childCount(obj)
		if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
			return count
		return None

	def flatChildren(
		obj: T,
		nesting: int,
		first: Callable[[T], T | None],
		step: Callable[[T], T | None],
		reading: _Reading,
	) -> Iterator[tuple[T, int]]:
		"""Yield obj's children and their nesting, with layout containers replaced by their own children.

		Reads from the start with firstChild and nextSibling, or from the end with lastChild and previousSibling.
		Nothing is described. When it stops before the last child, reading.cut says why.
		"""
		containers: list[T] = []
		try:
			child = first(obj)
			# Navigation steps since the last child was found: only layout containers make it grow.
			steps = 1
			while True:
				if child is None and not containers:
					return
				if steps >= _MAX_STEPS_WITHOUT_CHILD:
					# Most likely a loop among sibling containers, which never makes them nest deeper.
					reading.cut = "nesting"
					reading.note = f"stopped after {_MAX_STEPS_WITHOUT_CHILD} steps through layout containers without finding a child"
					return
				steps += 1
				if child is None:
					child = step(containers.pop())
					continue
				# The object whose children these are must not be nested too deeply.
				if nesting + len(containers) >= maxNesting:
					reading.cut = "nesting"
					reading.note = f"stopped at {maxNesting} levels of nesting"
					return
				if outOfBudget(False):
					reading.cut = stopped
					return
				if holds(isLayoutOnly, child):
					containers.append(child)
					child = first(child)
					continue
				yield child, nesting + len(containers) + 1
				child = step(child)
				steps = 1
		except Exception:  # noqa: BLE001 - COMError and others: keep the children read so far
			reading.cut = "error"

	def chooseChildren(
		obj: T,
		nesting: int,
		forward: Iterator[tuple[T, int]],
		backwardReading: _Reading,
		onFocusPath: bool,
	) -> tuple[list[tuple[T, int, int]], tuple[T, int, int] | None, bool]:
		"""Pick the children of obj to describe, without describing any.

		:return: The entries (object, nesting, index) to describe, the one on the focus path if it was found,
			and whether obj has more than headChildren + tailChildren children.
		"""
		focus: tuple[T, int, int] | None = None
		# Count from the start without describing anything, just far enough to know whether the list is long.
		limit = head + tail + 1
		counted: list[tuple[T, int, int]] = []
		for child, childNesting in forward:
			counted.append((child, childNesting, len(counted)))
			if onFocusPath and focus is None and holds(isOnFocusPath, child):
				focus = counted[-1]
			if len(counted) >= limit:
				break
		if len(counted) < limit:
			return counted, focus, False
		kept = counted[:head]
		# Found while counting, but past the head: it may also be one of the last children.
		countedFocus = focus if focus is not None and focus[2] >= head else None
		if countedFocus is not None:
			focus = None
		lookForFocus = onFocusPath and focus is None
		fromEnd: list[tuple[T, int, int]] = []
		if tail:
			backward = flatChildren(obj, nesting, lastChild, previousSibling, backwardReading)
			for child, childNesting in backward:
				fromEnd.append((child, childNesting, -1 - len(fromEnd)))
				if lookForFocus and focus is None and holds(isOnFocusPath, child):
					focus = fromEnd[-1]
				if len(fromEnd) >= tail:
					break
		# One object read both from the start and from the end, as in a loop among siblings, is kept once.
		if focus is not None and focus[2] < 0:
			kept = [entry for entry in kept if entry[0] is not focus[0]]
		readFromStart = {id(entry[0]) for entry in kept}
		kept.extend(
			entry for entry in reversed(fromEnd) if entry is focus or id(entry[0]) not in readFromStart
		)
		if focus is None and countedFocus is not None:
			focus = countedFocus
			kept.append(focus)
		elif focus is None and lookForFocus:
			# Look further into the unread middle, still without describing anything.
			for position in range(len(counted), _FOCUS_SEARCH_CHILDREN):
				found = next(forward, None)
				if found is None:
					break
				if holds(isOnFocusPath, found[0]):
					focus = (found[0], found[1], position)
					kept.append(focus)
					break
		return kept, focus, True

	def readChildren(obj: T, node: dict[str, Any], depth: int, nesting: int, onFocusPath: bool) -> None:
		nonlocal nodeCount, truncated
		forwardReading = _Reading()
		backwardReading = _Reading()
		forward = flatChildren(obj, nesting, firstChild, nextSibling, forwardReading)
		# Entries are (object, nesting, index).
		kept: list[tuple[T, int, int]] = []
		focus: tuple[T, int, int] | None = None
		isLong = False
		if nodeCount < maxNodes:
			kept, focus, isLong = chooseChildren(obj, nesting, forward, backwardReading, onFocusPath)
		elif next(forward, None) is not None:
			# Not one more object may be described: knowing that obj has children is enough to say so.
			outOfBudget(True)
			_addCut(node, stopped)
		kept.sort(key=lambda entry: _documentOrder(entry[2]))
		if focus is not None:
			# Compared by identity: comparing accessible objects can mean asking the application.
			kept = [focus] + [entry for entry in kept if entry is not focus]
		described: list[tuple[dict[str, Any], bool]] = []
		for entry in kept:
			if outOfBudget(True):
				_addCut(node, stopped)
				break
			child, childNesting, index = entry
			childNode = describeObject(child, index)
			if childNode is None:
				_addCut(node, "error")
				continue
			readBelow(child, childNode, depth + 1, childNesting, entry is focus)
			described.append((childNode, entry is focus))
		children, dropped = _withoutObjectsReadTwice(described)
		nodeCount -= dropped
		if isLong:
			_addCut(node, "gap")
		for reading in (forwardReading, backwardReading):
			_addCut(node, reading.cut)
			if reading.note is not None and truncated is None:
				truncated = reading.note
		if children:
			children.sort(key=lambda child: _documentOrder(child["index"]))
			node["children"] = children
		# Once time has run out, ask the object nothing more.
		if "cut" in node and stopped != "time":
			try:
				count = countChildren(obj)
			except Exception:  # noqa: BLE001 - COMError and others; the cut already says enough
				count = None
			if count is not None:
				node["childCount"] = count

	def describeObject(obj: T, index: int) -> dict[str, Any] | None:
		"""obj's description with its index, or None when describing it failed."""
		nonlocal nodeCount
		try:
			node = dict(describe(obj))
		except Exception:  # noqa: BLE001 - COMError and others: leave the object out
			return None
		nodeCount += 1
		node["index"] = index
		return node

	def readBelow(obj: T, node: dict[str, Any], depth: int, nesting: int, onFocusPath: bool) -> None:
		"""Read the children of obj, described in node, or only count them at the depth limit."""
		if depth >= maxDepth:
			# Do not read the children at all: their number is enough to say some were left out.
			try:
				count = countChildren(obj)
			except Exception:  # noqa: BLE001 - COMError and others
				node["cut"] = "error"
			else:
				if count:
					node["childCount"] = count
					node["cut"] = "depth"
			return
		# None of the focus's own children is on the way to it.
		readChildren(obj, node, depth, nesting, onFocusPath and not node.get("focused"))

	tree = describeObject(root, 0)
	if tree is None:
		# The root could not be described, most likely because it no longer exists.
		nodeCount = 1
		tree = {"key": None, "role": "unknown", "index": 0, "cut": "error"}
	else:
		readBelow(root, tree, 0, 0, not tree.get("focused") and holds(isOnFocusPath, root))
	return {"nodeCount": nodeCount, "truncated": truncated, "tree": tree}


def searchTrees(
	roots: list[T],
	isMatch: Callable[[T], bool],
	maxResults: int,
	*,
	firstChild: Callable[[T], T | None],
	nextSibling: Callable[[T], T | None],
	timeBudgetSeconds: float,
	maxVisits: int,
	maxNesting: int,
	found: list[T] | None = None,
) -> tuple[list[T], str | None]:
	"""Breadth-first search below each root in turn, so matches nearest a root come first.

	The roots share one time budget and one visit limit, so searching several parts of a window,
	such as its web document and then the whole window, takes no longer than searching one.
	A root itself never matches, and a control found below an earlier root is not repeated.
	:param found: Matches already known, such as the focus; they count towards maxResults.
	:return: The matches, and why the search stopped early, if it did.
	"""
	deadline = time.monotonic() + timeBudgetSeconds
	matches = list(found or [])
	visits = 0
	for root in roots:
		queue: deque[tuple[T, int]] = deque([(root, 0)])
		while queue:
			if len(matches) >= maxResults:
				return matches, f"stopped at {maxResults} results"
			obj, nesting = queue.popleft()
			visits += 1
			if visits > maxVisits:
				return matches, f"stopped after looking at {maxVisits} objects"
			if time.monotonic() > deadline:
				return matches, f"stopped after {timeBudgetSeconds} seconds"
			if obj is not root and isMatch(obj) and obj not in matches:
				matches.append(obj)
			if nesting < maxNesting:
				child = firstChild(obj)
				while child is not None:
					queue.append((child, nesting + 1))
					child = nextSibling(child)
	if len(matches) >= maxResults:
		return matches, f"stopped at {maxResults} results"
	return matches, None
