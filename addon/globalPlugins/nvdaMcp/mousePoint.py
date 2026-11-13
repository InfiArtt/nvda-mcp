# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Where on the screen a mouse action goes, and the steps of a drag.

This module does not import NVDA, so it can be unit tested on its own.
"""

from typing import Any


class PointError(Exception):
	"""The point is malformed or off the screen; the message says what to pass instead."""


def resolvePoint(
	params: dict[str, Any],
	area: tuple[int, int, int, int] | None,
	screen: tuple[int, int, int, int],
	xKey: str = "x",
	yKey: str = "y",
) -> tuple[int, int]:
	"""The screen point an action goes to.

	:param params: May hold xKey and yKey, in pixels.
	:param area: The left, top, width and height of the control or window the point is relative to;
		None for points on the whole screen.
	:param screen: The left, top, width and height of the area all monitors cover.
	:raises PointError: When the point is missing, outside the control or window, or off the screen.
	"""
	x, y = params.get(xKey), params.get(yKey)
	if (x is None) != (y is None):
		raise PointError(f"Pass both {xKey} and {yKey}, or neither.")
	if x is not None and not (isinstance(x, int) and isinstance(y, int)):
		raise PointError(f"{xKey} and {yKey} must be whole numbers of pixels.")
	if area is None:
		if x is None:
			raise PointError("Pass a control's id, a window, or x and y on the screen.")
		point = (x, y)
	else:
		left, top, width, height = area
		if width <= 0 or height <= 0:
			raise PointError("That control or window has no size on the screen; bring it into view first.")
		if x is None:
			point = (left + width // 2, top + height // 2)
		else:
			if not (0 <= x < width and 0 <= y < height):
				raise PointError(
					f"{xKey}, {yKey} = {x}, {y} is outside it: it is {width} by {height} pixels, "
					"counted from its top left corner."
				)
			point = (left + x, top + y)
	screenLeft, screenTop, screenWidth, screenHeight = screen
	if not (
		screenLeft <= point[0] < screenLeft + screenWidth and screenTop <= point[1] < screenTop + screenHeight
	):
		raise PointError(f"The point {point[0]}, {point[1]} is off the screen.")
	return point


def dragSteps(start: tuple[int, int], end: tuple[int, int], steps: int = 12) -> list[tuple[int, int]]:
	"""Points from start to end, end included, so the application sees the mouse move rather than jump."""
	return [
		(
			round(start[0] + (end[0] - start[0]) * step / steps),
			round(start[1] + (end[1] - start[1]) * step / steps),
		)
		for step in range(1, steps + 1)
	]
