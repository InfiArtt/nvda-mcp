# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Walking and searching an accessibility tree within limits.

This module does not import NVDA, so it can be unit tested on its own: the caller says how to
read an object's children, how to describe it, and whether it only exists for layout or matches a search.
"""

import time
from collections import deque
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

# Stands in for children left out by maxChildren. Compared by identity,
# since a real node also says "moreChildren" when its own children were cut.
_MORE_CHILDREN: dict[str, Any] = {"moreChildren": True}


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
