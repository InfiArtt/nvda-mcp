# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Which focus events make NVDA catch up with a window it missed coming to the front.

This module does not import NVDA, so it can be unit tested on its own.
"""

from typing import TypeVar

T = TypeVar("T")


def catchUpEvents(foreground: T | None, focus: T | None, announced: T | None = None) -> list[T]:
	"""The objects to send gainFocus for, in order, so that NVDA speaks the change as after Alt+Tab.

	After Alt+Tab, NVDA first focuses the window itself, which says its title, and then the control in it.
	A focus event for the control alone leaves the window a newly entered container: NVDA then says its
	title as it enters it, and in browse mode documents says it again when it replays the containers it held back.
	:param foreground: The control's container just below the desktop, the window NVDA compares with, if known.
	:param focus: The control focused in the window, if known.
	:param announced: The window, if NVDA was already sent a focus event for it (see :func:`earlyWindowEvent`).
	"""
	if foreground is None:
		return [focus] if focus is not None else []
	events = [foreground] if focus is None or focus == foreground else [foreground, focus]
	if announced is not None and announced == foreground:
		return events[1:]
	return events


def earlyWindowEvent(foreground: T | None, focus: T | None, inFocusMode: bool) -> T | None:
	"""The window to send gainFocus for as soon as it comes to the front, before the application's own events.

	Chromium browsers send no focus event for their window, only for the control in the page. When that page is
	in focus mode, NVDA says the window's title as it enters the window, then again when browse mode replays
	the containers it held back. A focus event for the window first makes it the previous focus, so NVDA says
	the title once, as for a window that sends its own focus event.
	Only in focus mode: in browse mode NVDA says the title once anyway, and a focus that turns focus mode on
	cancels speech, which would cut off the title said for the window.
	:param foreground: The control's container just below the desktop, the window NVDA compares with, if known.
	:param focus: The control focused in the window, if known.
	:param inFocusMode: Whether the focus is in a browse mode document that is in focus mode.
	"""
	if not inFocusMode or foreground is None or focus is None or focus == foreground:
		return None
	return foreground
