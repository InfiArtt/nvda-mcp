# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Pictures of part of the screen, taken the way NVDA takes them for its own text recognition (OCR).

With Screen Curtain or the magnifier on, NVDA captures through Windows Graphics Capture,
which sees the screen as it would be without them; otherwise it copies the screen with GDI.
"""

import ctypes

import screenBitmap
from contentRecog import RecogImageInfo, recogUi

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


def virtualScreen() -> tuple[int, int, int, int]:
	"""The left, top, width and height of the area every monitor covers."""
	metrics = ctypes.windll.user32.GetSystemMetrics
	return (
		metrics(_SM_XVIRTUALSCREEN),
		metrics(_SM_YVIRTUALSCREEN),
		metrics(_SM_CXVIRTUALSCREEN),
		metrics(_SM_CYVIRTUALSCREEN),
	)


def capturePixels(
	left: int, top: int, width: int, height: int, scale: float
) -> tuple[RecogImageInfo, object, str]:
	"""Take a picture of part of the screen, in the form NVDA's text recognition takes. Runs on NVDA's main thread.

	Returns the picture's size and position, its pixels as a ctypes array, and how it was taken.
	:raises RuntimeError: When Windows Graphics Capture fails.
	"""
	imageInfo = RecogImageInfo(left, top, width, height, scale)
	# These helpers are private to NVDA's OCR; without them, copy the screen as NVDA did before 2026.
	shouldUseWgc = getattr(recogUi, "_shouldUseWgcCapture", None)
	if shouldUseWgc is not None and shouldUseWgc():
		return imageInfo, recogUi._captureWithWgc(imageInfo), "Windows Graphics Capture"
	bitmap = screenBitmap.ScreenBitmap(imageInfo.recogWidth, imageInfo.recogHeight)
	return imageInfo, bitmap.captureImage(left, top, width, height), "GDI"


def captureRegion(left: int, top: int, width: int, height: int, scale: float) -> tuple[int, int, bytes, str]:
	"""Take a picture of part of the screen. Runs on NVDA's main thread.

	Returns the picture's width and height, its pixels (blue, green, red and an unused byte each,
	rows top to bottom) and how it was taken.
	:raises RuntimeError: When Windows Graphics Capture fails.
	"""
	imageInfo, pixels, method = capturePixels(left, top, width, height, scale)
	return imageInfo.recogWidth, imageInfo.recogHeight, bytes(pixels), method
