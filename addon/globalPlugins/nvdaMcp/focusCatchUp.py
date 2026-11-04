# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Which focus events make NVDA catch up with a window it missed coming to the front.

This module does not import NVDA, so it can be unit tested on its own.
"""

from typing import TypeVar

T = TypeVar("T")


def catchUpEvents(foreground: T | None, focus: T | None) -> list[T]:
	"""The objects to send gainFocus for, in order, so that NVDA speaks the change as after Alt+Tab.

	After Alt+Tab, NVDA first focuses the window itself, which says its title, and then the control in it.
	A focus event for the control alone leaves the window a newly entered container: NVDA then says its
	title as it enters it, and in browse mode documents says it again when it replays the containers it held back.
	:param foreground: The control's container just below the desktop, the window NVDA compares with, if known.
	:param focus: The control focused in the window, if known.
	"""
	if foreground is None:
		return [focus] if focus is not None else []
	if focus is None or focus == foreground:
		return [foreground]
	return [foreground, focus]
