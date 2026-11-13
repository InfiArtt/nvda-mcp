# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Turning the words Windows OCR found into lines of text with their place on the screen.

This module does not import NVDA, so it can be unit tested on its own.
"""

from typing import Any


def linesFromWords(
	data: list[list[dict[str, Any]]], left: int, top: int, scale: float
) -> list[dict[str, Any]]:
	"""Lines of recognized text, each with its left, top, width and height on the screen.

	:param data: What NVDA's LinesWordsResult holds: lines of words, each with x, y, width, height and text,
		measured in the enlarged picture that was recognized.
	:param left: The screen position of the picture's left edge.
	:param top: The screen position of the picture's top edge.
	:param scale: How much the picture was enlarged before recognition.
	"""
	lines = []
	for line in data:
		words = [word for word in line if str(word.get("text", "")).strip()]
		if not words:
			continue
		x0 = min(word["x"] for word in words)
		y0 = min(word["y"] for word in words)
		x1 = max(word["x"] + word["width"] for word in words)
		y1 = max(word["y"] + word["height"] for word in words)
		lines.append(
			{
				"text": " ".join(str(word["text"]).strip() for word in words),
				"location": [
					left + round(x0 / scale),
					top + round(y0 / scale),
					round((x1 - x0) / scale),
					round((y1 - y0) / scale),
				],
			}
		)
	return lines
