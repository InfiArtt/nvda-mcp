# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Text given to a control through its accessibility API.

This module does not import NVDA, so it can be unit tested on its own.
"""


def appendedValue(current: str | None, text: str) -> str:
	"""A control's text with text added at the end, its line breaks written the way the control writes them.

	Notepad's edit field gives its text back with \\r\\n; text added with bare \\n would mix the two.
	"""
	current = current or ""
	if "\r\n" in current:
		text = text.replace("\r\n", "\n").replace("\n", "\r\n")
	return current + text
