# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""What NVDA sees here, as plain text to paste into a chat with any AI assistant.

For people without an MCP client: the copy carries the same facts the MCP tools give.
This module does not import NVDA, so it can be unit tested on its own.
"""

from typing import Any

# The most spoken messages to include, newest last.
MAX_SPEECH = 20
# Lines of the window's controls to include, so the copy stays a size a chat accepts.
MAX_TREE_LINES = 150
# Items of one list to include: a long list of files must not crowd out the rest of the window.
MAX_LIST_ITEMS = 10

INTRODUCTION = (
	"I use the NVDA screen reader. Below is what NVDA reports about the application I am in. "
	"Help me with it. I use the keyboard, not a mouse, so tell me which keys to press."
)


def describeLine(node: dict[str, Any], hiddenStates: frozenset[str] = frozenset()) -> str:
	"""One control, the way the MCP tools show it: role, "name", value and states.

	:param hiddenStates: States to leave out, such as focusable, that tell an AI nothing useful.
	"""
	parts = [node.get("role") or "object"]
	if node.get("name"):
		parts.append(f'"{node["name"]}"')
	if node.get("value"):
		parts.append(f"value: {node['value']}")
	states = [state for state in node.get("states") or [] if state not in hiddenStates]
	if states:
		parts.append(f"[{', '.join(states)}]")
	return " ".join(parts)


def speechInWindow(speech: list[str], windowTitle: str | None) -> list[str]:
	"""What NVDA said since it last announced the window, or the newest messages if it did not.

	Speech from before the user came to this window, such as another application, would mislead an AI.
	"""
	spoken = [text for text in speech if text.strip()]
	if windowTitle:
		title = windowTitle.casefold()
		for index in range(len(spoken) - 1, -1, -1):
			if title in spoken[index].casefold():
				spoken = spoken[index:]
				break
	return spoken[-MAX_SPEECH:]


def treeLines(
	node: dict[str, Any], maxLines: int = MAX_TREE_LINES, hiddenStates: frozenset[str] = frozenset()
) -> list[str]:
	"""The controls under ``node`` as an indented outline, cut to ``maxLines`` with a note."""
	lines: list[str] = []
	isCut = False

	def walk(current: dict[str, Any], depth: int) -> None:
		nonlocal isCut
		if len(lines) >= maxLines:
			isCut = True
			return
		lines.append("  " * depth + "- " + describeLine(current, hiddenStates))
		before = current.get("childrenBefore")
		if before:
			count = "earlier ones" if before is True else f"{before} earlier"
			lines.append("  " * (depth + 1) + f"- ... {count} not shown")
		for child in current.get("children") or []:
			walk(child, depth + 1)
		more = current.get("moreChildren")
		if more:
			# True when NVDA could not tell how many were left out.
			count = "more" if more is True else f"{more} more"
			lines.append("  " * (depth + 1) + f"- ... and {count}")

	walk(node, 0)
	if isCut:
		lines.append("(The list was cut short here.)")
	return lines


def contextText(
	status: dict[str, Any],
	focus: dict[str, Any],
	tree: dict[str, Any] | None,
	speech: list[str],
	hiddenStates: frozenset[str] = frozenset(),
) -> str:
	"""Plain text describing where the user is, for an AI assistant.

	:param status: The foreground application and window, and the document mode, as getStatus returns them.
	:param focus: The focused control with its containers, as getFocus returns it.
	:param tree: The window's controls, as getTree returns them, if they could be read.
	:param speech: What NVDA said last, oldest first.
	:param hiddenStates: States to leave out, in the language NVDA speaks.
	"""
	lines = [INTRODUCTION, ""]
	# Just after plugins are reloaded, NVDA may not know the foreground window's application yet.
	app = status.get("foregroundApp") or focus.get("appName")
	window = status.get("foregroundWindow")
	if app or window:
		lines.append(f"Application: {app or 'unknown'}" + (f', window "{window}"' if window else ""))
	if status.get("documentMode"):
		lines.append(f"This is a web page or document in NVDA's {status['documentMode']} mode.")
	lines += ["", "Focus is on: " + describeLine(focus, hiddenStates)]
	ancestors = focus.get("ancestors") or []
	if ancestors:
		lines.append("Inside: " + " > ".join(str(ancestor) for ancestor in ancestors))
	if tree and tree.get("tree"):
		lines += ["", "Controls in this window:", *treeLines(tree["tree"], hiddenStates=hiddenStates)]
	recent = speechInWindow(speech, window)
	if recent:
		lines += ["", "What NVDA said in this window, oldest first:", *[f"- {text}" for text in recent]]
	return "\n".join(lines)
