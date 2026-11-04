# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""The area of the screen to take a picture of, and the picture as a PNG file.

This module does not import NVDA, so it can be unit tested on its own.
"""

import struct
import zlib

Region = tuple[int, int, int, int]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def captureRegion(location: Region, padding: int, screen: Region) -> Region | None:
	"""The part of the screen around a control to take a picture of, or None if none of it is on the screen.

	:param location: The control's left, top, width and height.
	:param padding: How many pixels around the control to include, for context.
	:param screen: The left, top, width and height of the whole screen, every monitor included.
	"""
	left, top, width, height = location
	if width <= 0 or height <= 0:
		return None
	screenLeft, screenTop, screenWidth, screenHeight = screen
	newLeft = max(left - padding, screenLeft)
	newTop = max(top - padding, screenTop)
	right = min(left + width + padding, screenLeft + screenWidth)
	bottom = min(top + height + padding, screenTop + screenHeight)
	if right <= newLeft or bottom <= newTop:
		return None
	return (newLeft, newTop, right - newLeft, bottom - newTop)


def scaleFor(region: Region, maxSide: int, minSide: int = 0, maxZoom: float = 1.0) -> float:
	"""How much to resize a picture: shrink it so that its longer side is at most maxSide pixels,
	or enlarge a small one towards minSide pixels, at most maxZoom times, so that icons stay recognizable."""
	longest = max(region[2], region[3])
	if longest > maxSide:
		return maxSide / longest
	if longest < minSide:
		return min(minSide / longest, maxZoom)
	return 1.0


def _chunk(kind: bytes, data: bytes) -> bytes:
	return (
		struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
	)


def encodePng(width: int, height: int, bgra: bytes) -> bytes:
	"""A PNG file of pixels as Windows gives them: blue, green, red and an unused byte, rows top to bottom."""
	if width <= 0 or height <= 0 or len(bgra) != width * height * 4:
		raise ValueError(f"Expected {width}×{height} pixels of 4 bytes, got {len(bgra)} bytes")
	rgb = bytearray(width * height * 3)
	rgb[0::3] = bgra[2::4]
	rgb[1::3] = bgra[1::4]
	rgb[2::3] = bgra[0::4]
	stride = width * 3
	# Each row starts with filter type 0, none.
	rows = b"".join(b"\x00" + rgb[row * stride : (row + 1) * stride] for row in range(height))
	header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
	return (
		PNG_SIGNATURE
		+ _chunk(b"IHDR", header)
		+ _chunk(b"IDAT", zlib.compress(rows, 6))
		+ _chunk(b"IEND", b"")
	)
