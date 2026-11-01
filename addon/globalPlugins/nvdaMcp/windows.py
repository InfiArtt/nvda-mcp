# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Top-level windows and raw keyboard input, through the Win32 API.

This module does not import NVDA, so it can be unit tested on its own.
Sending input must still happen inside ``keyboardHandler.ignoreInjection()``
so NVDA does not treat the injected keys as the user's own gestures.
"""

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32")
_dwmapi = ctypes.WinDLL("dwmapi")

# Without these, ctypes would pass and return window handles as 32-bit ints.
for _name, _restype, _argtypes in (
	("GetForegroundWindow", wintypes.HWND, []),
	("GetWindow", wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
	("IsWindowVisible", wintypes.BOOL, [wintypes.HWND]),
	("IsIconic", wintypes.BOOL, [wintypes.HWND]),
	("GetWindowLongW", wintypes.LONG, [wintypes.HWND, ctypes.c_int]),
	("GetWindowTextLengthW", ctypes.c_int, [wintypes.HWND]),
	("GetWindowTextW", ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
	("GetWindowThreadProcessId", wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
	("ShowWindow", wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
	("SetForegroundWindow", wintypes.BOOL, [wintypes.HWND]),
	("BringWindowToTop", wintypes.BOOL, [wintypes.HWND]),
	("AttachThreadInput", wintypes.BOOL, [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]),
	("IsWindow", wintypes.BOOL, [wintypes.HWND]),
):
	_function = getattr(_user32, _name)
	_function.restype = _restype
	_function.argtypes = _argtypes

_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_DWMWA_CLOAKED = 14
_SW_RESTORE = 9

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

# Modifiers that may be held down across several key presses, for example alt while tab cycles windows.
HOLDABLE_KEYS: dict[str, int] = {
	"alt": 0xA4,  # VK_LMENU
	"control": 0xA2,  # VK_LCONTROL
	"shift": 0xA0,  # VK_LSHIFT
	"windows": 0x5B,  # VK_LWIN
}


@dataclass(frozen=True)
class WindowInfo:
	handle: int
	title: str
	processId: int
	isMinimized: bool
	isHidden: bool
	"""Cloaked: on another virtual desktop, or a suspended Store app. Alt+Tab leaves these out."""

	def toDict(self, appName: str | None, isForeground: bool) -> dict[str, object]:
		return {
			"handle": self.handle,
			"title": self.title,
			"appName": appName,
			"isForeground": isForeground,
			"isMinimized": self.isMinimized,
			"isHidden": self.isHidden,
		}


def _isCloaked(hwnd: int) -> bool:
	"""Suspended Store apps and windows on other virtual desktops are cloaked: visible to Windows, not to people."""
	cloaked = wintypes.DWORD()
	result = _dwmapi.DwmGetWindowAttribute(
		wintypes.HWND(hwnd), _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
	)
	return result == 0 and cloaked.value != 0


def _isAppWindow(hwnd: int) -> bool:
	"""Roughly the windows Alt+Tab offers, cloaked or not: visible, titled, unowned, not tool windows."""
	if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, _GW_OWNER):
		return False
	exStyle = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
	if exStyle & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
		return False
	return _user32.GetWindowTextLengthW(hwnd) > 0


def _windowText(hwnd: int) -> str:
	length = _user32.GetWindowTextLengthW(hwnd)
	buffer = ctypes.create_unicode_buffer(length + 1)
	_user32.GetWindowTextW(hwnd, buffer, length + 1)
	return buffer.value


def listWindows(includeHidden: bool = False) -> list[WindowInfo]:
	"""Application windows in Z order (most recently active first).

	:param includeHidden: Also list cloaked windows, which Alt+Tab does not show.
	"""
	windows: list[WindowInfo] = []

	@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
	def onWindow(hwnd: int, lParam: int) -> bool:
		if _isAppWindow(hwnd):
			isHidden = _isCloaked(hwnd)
			if includeHidden or not isHidden:
				processId = wintypes.DWORD()
				_user32.GetWindowThreadProcessId(hwnd, ctypes.byref(processId))
				windows.append(
					WindowInfo(
						hwnd, _windowText(hwnd), processId.value, bool(_user32.IsIconic(hwnd)), isHidden
					)
				)
		return True

	_user32.EnumWindows(onWindow, 0)
	return windows


def foregroundWindow() -> int:
	return _user32.GetForegroundWindow() or 0


def isWindow(hwnd: int) -> bool:
	return bool(_user32.IsWindow(hwnd))


def matchWindows(windows: list[WindowInfo], titleContains: str) -> list[WindowInfo]:
	"""Windows whose title contains the text, ignoring case.

	Exact title matches come first, then windows Alt+Tab would show, each group in Z order.
	"""
	needle = titleContains.casefold()
	matches = [window for window in windows if needle in window.title.casefold()]
	return sorted(matches, key=lambda window: (window.title.casefold() != needle, window.isHidden))


def activateWindow(hwnd: int) -> bool:
	"""Bring a window to the foreground, restoring it if minimised. Returns whether it is now in front.

	Windows only lets the process that received the last input change the foreground window,
	so this briefly attaches to the input queue of the window that is in front now.
	"""
	if _user32.IsIconic(hwnd):
		_user32.ShowWindow(hwnd, _SW_RESTORE)
	if _user32.SetForegroundWindow(hwnd) and foregroundWindow() == hwnd:
		return True
	currentThread = _user32.GetWindowThreadProcessId(foregroundWindow(), None)
	ourThread = _kernel32.GetCurrentThreadId()
	attached = currentThread != ourThread and _user32.AttachThreadInput(ourThread, currentThread, True)
	try:
		_user32.BringWindowToTop(hwnd)
		_user32.SetForegroundWindow(hwnd)
	finally:
		if attached:
			_user32.AttachThreadInput(ourThread, currentThread, False)
	return foregroundWindow() == hwnd


class _KeyboardInput(ctypes.Structure):
	_fields_ = [
		("wVk", wintypes.WORD),
		("wScan", wintypes.WORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ctypes.c_size_t),
	]


class _MouseInput(ctypes.Structure):
	# Only here so the union has the size Windows expects.
	_fields_ = [
		("dx", wintypes.LONG),
		("dy", wintypes.LONG),
		("mouseData", wintypes.DWORD),
		("dwFlags", wintypes.DWORD),
		("time", wintypes.DWORD),
		("dwExtraInfo", ctypes.c_size_t),
	]


class _InputUnion(ctypes.Union):
	_fields_ = [("ki", _KeyboardInput), ("mi", _MouseInput)]


class _Input(ctypes.Structure):
	_fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]


def _keyInput(vk: int, scan: int, flags: int) -> _Input:
	return _Input(_INPUT_KEYBOARD, _InputUnion(ki=_KeyboardInput(vk, scan, flags, 0, 0)))


def _sendInputs(inputs: list[_Input]) -> None:
	array = (_Input * len(inputs))(*inputs)
	sent = _user32.SendInput(len(inputs), array, ctypes.sizeof(_Input))
	if sent != len(inputs):
		raise OSError(
			ctypes.get_last_error(), "SendInput was blocked, possibly by a higher-privilege window."
		)


def setKeyDown(vk: int, isDown: bool) -> None:
	_sendInputs([_keyInput(vk, 0, 0 if isDown else _KEYEVENTF_KEYUP)])


def unicodeInputs(text: str) -> list[_Input]:
	"""Key down and up events that type the text as characters, independent of the keyboard layout.

	Characters outside the Basic Multilingual Plane, such as most emoji, are sent as UTF-16 surrogate pairs.
	"""
	inputs = []
	encoded = text.encode("utf-16-le")
	for index in range(0, len(encoded), 2):
		codeUnit = int.from_bytes(encoded[index : index + 2], "little")
		inputs.append(_keyInput(0, codeUnit, _KEYEVENTF_UNICODE))
		inputs.append(_keyInput(0, codeUnit, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
	return inputs


def typeText(text: str, delayBetweenCharacters: float = 0.0) -> None:
	"""Type the text into whatever has keyboard focus."""
	inputs = unicodeInputs(text)
	if not delayBetweenCharacters:
		_sendInputs(inputs)
		return
	# One character (down and up, or two of each for a surrogate pair) at a time,
	# for applications that drop characters arriving all at once.
	for index in range(0, len(inputs), 2):
		_sendInputs(inputs[index : index + 2])
		time.sleep(delayBetweenCharacters)
