# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""The operations the bridge exposes, implemented with NVDA's API.

Functions in this module touch NVDAObjects, speech and input,
so they must run on NVDA's main thread; :class:`NvdaActions` takes care of that.
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import addonHandler
import api
import appModuleHandler
import config
import controlTypes
import eventHandler
import inputCore
import keyboardHandler
import queueHandler
import speech
import synthDriverHandler
import textInfos
import treeInterceptorHandler
import ui
import versionInfo
import winUser
from browseMode import BrowseModeTreeInterceptor, reportPassThrough
from comInterfaces import IAccessible2Lib as IA2
from cursorManager import CursorManager
from gui.guiHelper import wxCallOnMain
from keyboardHandler import KeyboardInputGesture, ignoreInjection
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.IAccessible import IAccessible, getNVDAObjectFromEvent
from NVDAObjects.UIA import UIA
from NVDAObjects.window import Window
from treeInterceptorHandler import TreeInterceptor
from utils.security import isLockScreenModeActive

from . import controlApproval, windows
from .actionLog import ActionLog
from .bridge import BridgeError, Handler
from .configSpec import CONFIG_SECTION, parseAllowedApps
from .objectRegistry import ObjectRegistry
from .speechLog import SpeechLog
from .treeWalk import searchTrees, walkTree

addonHandler.initTranslation()

MAX_TEXT_CHARS = 20000
MAX_KEYS_PER_CALL = 50
MAX_TREE_NODES = 500
TREE_TIME_BUDGET_SECONDS = 3.0
# Guards against cycles in broken accessibility trees, since layout containers do not count towards depth.
MAX_TREE_NESTING = 100
MAX_TEXT_LINES = 5000
DELAY_BETWEEN_KEYS_SECONDS = 0.05
FOCUS_RETURN_DELAY_SECONDS = 0.5
# How long NVDA gets to notice a window brought to the front before it is told.
FOREGROUND_CATCH_UP_SECONDS = 1.0
# Lets NVDA's keyboard hook see injected keys while it is still told to ignore them.
HOLD_KEY_DELAY_SECONDS = 0.05
# How long to wait for an NVDA command run by a key press before pressing the next key.
SCRIPT_WAIT_SECONDS = 5.0
MAX_TYPE_CHARS = 2000
MAX_TYPE_DELAY_MS = 200
MAX_WAIT_FOR_SPEECH_SECONDS = 120.0
MAX_FIND_RESULTS = 50
MAX_FIND_VISITS = 5000
# Found controls keep their ids through later searches; only this many of the newest are remembered.
MAX_KEPT_OBJECTS = 500
MAX_INSPECT_CHILDREN = 10
MAX_INSPECT_ANCESTORS = 40
# Bounds counting the rows a table or list has loaded, which web apps limit to those near the screen.
MAX_ROW_COUNT_VISITS = 3000
ROW_COUNT_DEPTH = 3
MAX_ELEMENTS = 200
# Browse mode quick navigation types, as NVDA names them.
ELEMENT_TYPES = (
	"heading",
	"link",
	"landmark",
	"formField",
	"button",
	"edit",
	"comboBox",
	"checkBox",
	"radioButton",
	"table",
	"list",
	"listItem",
	"graphic",
	"frame",
	"article",
	"grouping",
	"figure",
	"tab",
	"separator",
	"blockQuote",
	"embeddedObject",
	"annotation",
	"error",
)


def _safeGet(obj: NVDAObject, attribute: str) -> Any:
	"""Read an NVDAObject property, returning None if the application fails to answer."""
	try:
		return getattr(obj, attribute)
	except Exception:  # noqa: BLE001 - applications raise COMError and others; treat all as "unknown"
		log.debugWarning(f"Could not get {attribute}", exc_info=True)
		return None


def _usesNvdaKey(gesture: KeyboardInputGesture) -> bool:
	return any(keyboardHandler.isNVDAModifierKey(vk, extended) for vk, extended in gesture.modifiers)


def _pressGesture(gesture: KeyboardInputGesture) -> None:
	"""Press a key as the user would: NVDA runs its command for the key, if it has one,
	and otherwise the key goes to the application.

	``gesture.send()`` alone bypasses NVDA, since NVDA ignores injected keys:
	NVDA+t would type t, and browse mode quick navigation keys would go to the page.
	"""
	try:
		inputCore.manager.executeGesture(gesture)
	except inputCore.NoInputGestureAction:
		if _usesNvdaKey(gesture):
			# Sending it would type the key without the NVDA key into the application.
			log.debugWarning(f"No NVDA command for {gesture.identifiers}; not sending it")
			return
		gesture.send()


def describeObject(obj: NVDAObject) -> dict[str, Any]:
	"""A compact, JSON-serialisable description of an NVDAObject. Empty fields are omitted."""
	role = _safeGet(obj, "role")
	states = _safeGet(obj, "states") or set()
	location = _safeGet(obj, "location")
	appModule = _safeGet(obj, "appModule")
	positionInfo = _safeGet(obj, "positionInfo") or {}
	description = {
		"name": _safeGet(obj, "name"),
		"role": role.displayString if role is not None else None,
		"states": sorted(state.displayString for state in states),
		"value": _safeGet(obj, "value"),
		"description": _safeGet(obj, "description"),
		"keyboardShortcut": _safeGet(obj, "keyboardShortcut"),
		"position": {
			key: positionInfo[key]
			for key in ("level", "indexInGroup", "similarItemsInGroup")
			if key in positionInfo
		},
		"appName": appModule.appName if appModule else None,
		"windowClassName": _safeGet(obj, "windowClassName"),
		"location": list(location) if location else None,
		"isFocusable": controlTypes.State.FOCUSABLE in states,
	}
	return {key: value for key, value in description.items() if value not in (None, "", [], {})}


# Roles that, without a name, only exist for layout: web pages wrap content in many of these.
_LAYOUT_ROLES = frozenset(
	{
		controlTypes.Role.SECTION,
		controlTypes.Role.PANEL,
		controlTypes.Role.GROUPING,
		controlTypes.Role.UNKNOWN,
		controlTypes.Role.FILLER,
		controlTypes.Role.PANE,
		controlTypes.Role.WINDOW,
	}
)


def _isLayoutOnly(obj: NVDAObject) -> bool:
	"""Whether an object is an unnamed layout container that tells a user nothing."""
	return (
		_safeGet(obj, "role") in _LAYOUT_ROLES
		and not _safeGet(obj, "name")
		and not _safeGet(obj, "value")
		and controlTypes.State.FOCUSABLE not in (_safeGet(obj, "states") or set())
	)


def _describeWithAncestors(obj: NVDAObject, ancestors: list[NVDAObject]) -> dict[str, Any]:
	result = describeObject(obj)
	result["ancestors"] = [
		f"{_safeGet(ancestor, 'name') or ''} ({role.displayString if (role := _safeGet(ancestor, 'role')) is not None else '?'})".strip()
		for ancestor in ancestors
		if not _isLayoutOnly(ancestor)
	]
	return result


def _walkTree(root: NVDAObject, maxDepth: int, maxNodes: int, maxChildren: int | None) -> dict[str, Any]:
	"""Walk the tree below root within limits, as :func:`treeWalk.walkTree` describes."""
	return walkTree(
		root,
		maxDepth,
		maxNodes,
		maxChildren,
		firstChild=lambda obj: _safeGet(obj, "firstChild"),
		nextSibling=lambda obj: _safeGet(obj, "next"),
		describe=describeObject,
		isLayoutOnly=_isLayoutOnly,
		childCount=lambda obj: _safeGet(obj, "childCount"),
		timeBudgetSeconds=TREE_TIME_BUDGET_SECONDS,
		maxNesting=MAX_TREE_NESTING,
	)


def _readLines(info: textInfos.TextInfo) -> tuple[str, bool]:
	"""Read a document line by line, as NVDA presents it in browse mode.

	Reading all text at once runs neighbouring elements together ("MenuHide sidebar"),
	because separate elements on the same line have no separator in the raw text.
	:return: The text and whether it was cut short.
	"""
	lines: list[str] = []
	length = 0
	cursor = info.copy()
	cursor.collapse()
	for _ in range(MAX_TEXT_LINES):
		line = cursor.copy()
		line.expand(textInfos.UNIT_LINE)
		text = line.text.rstrip("\r\n")
		lines.append(text)
		length += len(text) + 1
		if length > MAX_TEXT_CHARS:
			return "\n".join(lines)[:MAX_TEXT_CHARS], True
		if cursor.move(textInfos.UNIT_LINE, 1) == 0:
			return "\n".join(lines), False
	return "\n".join(lines), True


def _roleMatches(obj: NVDAObject, role: str) -> bool:
	"""Match NVDA's internal role name ("editableText") or the spoken one ("edit"), ignoring case."""
	objRole = _safeGet(obj, "role")
	if objRole is None:
		return False
	return role.casefold() in (objRole.name.casefold(), objRole.displayString.casefold())


def _objectMatches(
	obj: NVDAObject,
	nameContains: str | None,
	role: str | None,
	predicate: Callable[[NVDAObject], bool] | None,
) -> bool:
	name = _safeGet(obj, "name") or ""
	return (
		(nameContains is None or nameContains.casefold() in name.casefold())
		and (role is None or _roleMatches(obj, role))
		and (predicate is None or predicate(obj))
	)


def findObjects(
	root: NVDAObject,
	nameContains: str | None,
	role: str | None,
	maxResults: int,
	predicate: Callable[[NVDAObject], bool] | None = None,
) -> tuple[list[NVDAObject], str | None]:
	"""Breadth-first search below root, bounded by results, visits and time.

	:param predicate: When given, objects must also satisfy it.
	:return: The matches, nearest the root first, and why the search stopped early, if it did.
	"""
	return _searchRoots([root], nameContains, role, maxResults, predicate)


def _searchRoots(
	roots: list[NVDAObject],
	nameContains: str | None,
	role: str | None,
	maxResults: int,
	predicate: Callable[[NVDAObject], bool] | None = None,
	matches: list[NVDAObject] | None = None,
) -> tuple[list[NVDAObject], str | None]:
	"""Search several roots in turn within one time budget, as :func:`treeWalk.searchTrees` describes.

	:param matches: Controls already found, such as the focus, that count towards maxResults.
	"""
	return searchTrees(
		roots,
		lambda obj: _objectMatches(obj, nameContains, role, predicate),
		maxResults,
		firstChild=lambda obj: _safeGet(obj, "firstChild"),
		nextSibling=lambda obj: _safeGet(obj, "next"),
		timeBudgetSeconds=TREE_TIME_BUDGET_SECONDS,
		maxVisits=MAX_FIND_VISITS,
		maxNesting=MAX_TREE_NESTING,
		found=matches,
	)


# The child window that holds a web document's accessibility tree, in Chromium browsers and Electron apps.
# Chromium removes it while the window is hidden, and creates it again when the window is shown.
CHROMIUM_DOCUMENT_WINDOW_CLASS = "Chrome_RenderWidgetHostHWND"


def _windowRoots(handle: Any) -> list[NVDAObject]:
	"""Where to search a window that may be in the background: the web documents in it, then the window.

	NVDA's focus and browse mode only cover the foreground window,
	so documents are also found through the child windows that hold them.
	"""
	if not isinstance(handle, int) or not windows.isWindow(handle):
		raise BridgeError("noSuchWindow", "That window no longer exists. Call listWindows again.")
	roots: list[NVDAObject] = []
	for treeInterceptor in list(treeInterceptorHandler.runningTable):
		document = _safeGet(treeInterceptor, "rootNVDAObject")
		documentWindow = _safeGet(document, "windowHandle")
		if documentWindow and winUser.getAncestor(documentWindow, winUser.GA_ROOT) == handle:
			roots.append(document)
	for child, className in windows.childWindows(handle):
		if className != CHROMIUM_DOCUMENT_WINDOW_CLASS:
			continue
		document = getNVDAObjectFromEvent(child, winUser.OBJID_CLIENT, winUser.CHILDID_SELF)
		if document is not None and document not in roots:
			roots.append(document)
	roots.append(Window(windowHandle=handle))
	return roots


def _isWebPageUnavailable(handle: int, roots: list[NVDAObject]) -> bool:
	"""Whether a Chromium browser or Electron app window offers only the browser around its page.

	Chromium removes the child window that holds a page some time after its window is hidden,
	and NVDA then drops its browse mode document, so neither leads to the page any more.
	"""
	return len(roots) == 1 and windows.className(handle).startswith("Chrome_WidgetWin")


def _apiName(obj: NVDAObject) -> str:
	if isinstance(obj, UIA):
		return "UIA"
	if isinstance(obj, IAccessible):
		return (
			"IAccessible2"
			if isinstance(_safeGet(obj, "IAccessibleObject"), IA2.IAccessible2)
			else "IAccessible"
		)
	return type(obj).__mro__[1].__name__ if len(type(obj).__mro__) > 1 else type(obj).__name__


def _ia2Attributes(obj: NVDAObject) -> dict[str, str]:
	"""The IAccessible2 object attributes: for web content, the HTML tag, id, class, ARIA role and more."""
	if not isinstance(obj, IAccessible):
		return {}
	return dict(_safeGet(obj, "IA2Attributes") or {})


# The IAccessible2 attributes that identify a container in an ancestor path.
_PATH_ATTRIBUTES = ("tag", "xml-roles", "id")


def _pathEntry(obj: NVDAObject) -> dict[str, Any]:
	role = _safeGet(obj, "role")
	attributes = _ia2Attributes(obj)
	entry = {
		"role": role.displayString if role is not None else None,
		"name": _safeGet(obj, "name"),
		"attributes": {key: attributes[key] for key in _PATH_ATTRIBUTES if attributes.get(key)},
	}
	return {key: value for key, value in entry.items() if value not in (None, "", {})}


def _ancestorPath(obj: NVDAObject) -> list[dict[str, Any]]:
	"""The containers from the web document, or else the window, down to obj's parent.

	Unnamed layout containers are left out unless their ARIA role or id could identify them.
	"""
	desktop = api.getDesktopObject()
	path = []
	parent = _safeGet(obj, "parent")
	while parent is not None and parent != desktop and len(path) < MAX_INSPECT_ANCESTORS:
		attributes = _ia2Attributes(parent)
		if not _isLayoutOnly(parent) or attributes.get("xml-roles") or attributes.get("id"):
			path.insert(0, _pathEntry(parent))
		# The browser's own windows above a web page tell an add-on nothing about the page.
		if _safeGet(parent, "role") == controlTypes.Role.DOCUMENT:
			break
		parent = _safeGet(parent, "parent")
	return path


_ROW_ROLES = frozenset(
	{controlTypes.Role.TABLEROW, controlTypes.Role.LISTITEM, controlTypes.Role.TREEVIEWITEM}
)
_ROW_CONTAINER_ROLES = frozenset(
	{controlTypes.Role.TABLE, controlTypes.Role.DATAGRID, controlTypes.Role.LIST, controlTypes.Role.TREEVIEW}
)


def _countLoadedRows(container: NVDAObject) -> tuple[int, bool]:
	"""Count the rows or items of a table, list or tree that exist in the accessibility tree now.

	Web apps often create only the rows near the screen, while saying how many there are in total.
	:return: The count, and whether counting stopped before looking everywhere.
	"""
	count = 0
	visits = 0
	queue: deque[tuple[NVDAObject, int]] = deque([(container, 0)])
	while queue:
		obj, depth = queue.popleft()
		child = _safeGet(obj, "firstChild")
		while child is not None:
			visits += 1
			if visits > MAX_ROW_COUNT_VISITS:
				return count, True
			if _safeGet(child, "role") in _ROW_ROLES:
				count += 1
			elif depth + 1 < ROW_COUNT_DEPTH:
				queue.append((child, depth + 1))
			child = _safeGet(child, "next")
	return count, False


def _tableInfo(obj: NVDAObject) -> dict[str, Any] | None:
	if _safeGet(obj, "role") not in _ROW_CONTAINER_ROLES:
		return None
	loaded, isCut = _countLoadedRows(obj)
	info: dict[str, Any] = {"loadedRows": loaded}
	if isCut:
		info["loadedRowsIsCut"] = True
	for key in ("rowCount", "columnCount"):
		value = _safeGet(obj, key)
		if isinstance(value, int) and value >= 0:
			info[key] = value
	return info


def _meaningfulChildren(obj: NVDAObject, limit: int, nesting: int = 0) -> list[NVDAObject]:
	"""The first children of obj, with unnamed layout containers replaced by what is inside them."""
	found: list[NVDAObject] = []
	child = _safeGet(obj, "firstChild")
	while child is not None and len(found) < limit:
		if _isLayoutOnly(child) and nesting < ROW_COUNT_DEPTH * 2:
			found += _meaningfulChildren(child, limit - len(found), nesting + 1)
		else:
			found.append(child)
		child = _safeGet(child, "next")
	return found


def inspectObject(obj: NVDAObject) -> dict[str, Any]:
	"""What an add-on developer needs to recognize a control: its API, attributes, containers and children."""
	role = _safeGet(obj, "role")
	result: dict[str, Any] = {
		"object": describeObject(obj),
		"roleConstant": role.name if role is not None else None,
		"api": _apiName(obj),
		"nvdaClass": f"{type(obj).__module__}.{type(obj).__qualname__}",
		"attributes": _ia2Attributes(obj),
		"ancestors": _ancestorPath(obj),
	}
	if isinstance(obj, UIA):
		element = _safeGet(obj, "UIAElement")
		result["uia"] = {
			key: value
			for key, value in (
				("automationId", _safeGet(obj, "UIAAutomationId")),
				("className", _safeGet(element, "CurrentClassName") if element is not None else None),
				("frameworkId", _safeGet(obj, "UIAFrameworkId")),
			)
			if value
		}
	children = [_pathEntry(child) for child in _meaningfulChildren(obj, MAX_INSPECT_CHILDREN)]
	childCount = _safeGet(obj, "childCount")
	result["children"] = {
		"count": childCount if isinstance(childCount, int) else len(children),
		"first": children,
	}
	table = _tableInfo(obj)
	if table is not None:
		result["table"] = table
	return {key: value for key, value in result.items() if value not in (None, "", {}, [])}


def _setObjectValue(obj: NVDAObject, text: str) -> str:
	"""Give a control new text through its accessibility API, without keyboard input or focus.

	:return: The API that was used.
	"""
	if isinstance(obj, UIA):
		valuePattern = _safeGet(obj, "UIAValuePattern")
		if valuePattern is not None:
			try:
				valuePattern.SetValue(text)
			except Exception as error:  # noqa: BLE001 - COMError, or the control refusing
				raise BridgeError(
					"setValueFailed",
					f"The control refused the text through UI Automation ({error}). "
					"Focus it and use typeText instead.",
				)
			return "UI Automation ValuePattern"
	if isinstance(obj, IAccessible):
		try:
			obj.IAccessibleObject.accValue[obj.IAccessibleChildID] = text
		except Exception as error:  # noqa: BLE001 - COMError, or the control refusing
			raise BridgeError(
				"setValueFailed",
				f"The control refused the text through IAccessible ({error}). Focus it and use typeText instead.",
			)
		return "IAccessible accValue"
	raise BridgeError(
		"noValue",
		"This control cannot take text through its accessibility API. Focus it and use typeText instead.",
	)


def _browseModeDocument() -> BrowseModeTreeInterceptor | None:
	"""The web page or document the focus is in, if NVDA offers browse mode there."""
	treeInterceptor = _safeGet(api.getFocusObject(), "treeInterceptor")
	return treeInterceptor if isinstance(treeInterceptor, BrowseModeTreeInterceptor) else None


def _documentMode() -> str | None:
	"""'browse' or 'focus' inside a document with browse mode, None elsewhere."""
	document = _browseModeDocument()
	if document is None:
		return None
	return "focus" if document.passThrough else "browse"


def _requireBrowseModeDocument() -> BrowseModeTreeInterceptor:
	document = _browseModeDocument()
	if document is None:
		raise BridgeError(
			"noDocument",
			"Focus is not in a web page or document with browse mode. Use getFocus to see where it is.",
		)
	return document


def _appNameOf(obj: NVDAObject | None) -> str | None:
	appModule = _safeGet(obj, "appModule") if obj is not None else None
	return appModule.appName if appModule else None


def _isNvdaForeground(hwnd: int) -> bool:
	return _safeGet(api.getForegroundObject(), "windowHandle") == hwnd


def _reportForeground(hwnd: int) -> None:
	"""Tell NVDA about the control focused in a window it missed coming to the front.

	Windows sends no foreground event when bringing a window forward also switches virtual desktops.
	NVDA takes the new foreground window from the focus, so a focus event is enough.
	"""
	threadId = winUser.getWindowThreadProcessID(hwnd)[1]
	focusWindow = winUser.getGUIThreadInfo(threadId).hwndFocus or hwnd
	window = getNVDAObjectFromEvent(focusWindow, winUser.OBJID_CLIENT, winUser.CHILDID_SELF)
	if window is None:
		return
	try:
		focus = window.objectWithFocus()
	except Exception:  # noqa: BLE001 - applications raise COMError and others
		log.debugWarning("Could not get the focused control", exc_info=True)
		focus = None
	eventHandler.queueEvent("gainFocus", focus or window)


def _controlBusyError() -> BridgeError:
	return BridgeError(
		"controlBusy",
		"NVDA is busy with another action, or still waiting for the user to answer whether a client may press keys, "
		"so nothing was done. Try again shortly.",
	)


class NvdaActions:
	"""Implements bridge methods and owns the per-session control approval."""

	def __init__(self, speechLog: SpeechLog, actionLog: ActionLog) -> None:
		self._speechLog = speechLog
		self._actionLog = actionLog
		# One action at a time, so concurrent requests cannot interleave keys or steal each other's speech.
		self._controlLock = threading.Lock()
		# Controls found by findObjects and previewSpeech, addressed by id in focusObject, activateObject and others.
		self._objects: ObjectRegistry[NVDAObject] = ObjectRegistry(MAX_KEPT_OBJECTS)
		# Results of the last listElements call, addressed by 1-based id in moveToElement.
		self._foundElements: list[Any] = []

	def revokeControlApproval(self) -> None:
		"""Require the user to approve again before the next key press, even if confirmation is turned off."""
		controlApproval.revoke()

	def handlers(self) -> dict[str, Handler]:
		return {
			"getStatus": self.onMain(self._getStatus),
			"getFocus": self.onMain(self._getFocus),
			"getNavigator": self.onMain(self._getNavigator),
			"getTree": self.onMain(self._getTree),
			"getText": self.onMain(self._getText),
			"getSpeech": self._getSpeech,
			"speak": self.onMain(self._speak),
			"pressKeys": self._pressKeys,
			"typeText": self._typeText,
			"listWindows": self.onMain(self._listWindows),
			"activateWindow": self._activateWindow,
			"waitForSpeech": self._waitForSpeech,
			"findObjects": self.onMain(self._findObjectsHandler),
			"focusObject": self._focusObject,
			"activateObject": self._activateObject,
			"inspectObject": self.onMain(self._inspectObject),
			"setValue": self._setValue,
			"getActionLog": self._getActionLog,
			"setDocumentMode": self._setDocumentMode,
			"findInPage": self._findInPage,
			"listElements": self.onMain(self._listElements),
			"moveToElement": self._moveToElement,
		}

	def onMain(self, function: Callable[[dict[str, Any]], Any]) -> Handler:
		"""Wrap a handler so it runs on the GUI thread, after the lock screen check."""

		def handler(params: dict[str, Any]) -> Any:
			self.ensureUnlocked()
			return wxCallOnMain(function, params)

		return handler

	@staticmethod
	def ensureUnlocked() -> None:
		if isLockScreenModeActive():
			raise BridgeError(
				"locked", "Windows is locked. Ask the user to unlock their computer, then try again."
			)

	def _getStatus(self, params: dict[str, Any]) -> dict[str, Any]:
		addon = addonHandler.getCodeAddon()
		foreground = api.getForegroundObject()
		return {
			"nvdaVersion": versionInfo.version,
			"addonVersion": addon.version,
			"synthesizer": synthDriverHandler.getSynth().name,
			"speechMode": speech.getState().speechMode.name,
			"foregroundApp": foreground.appModule.appName if foreground and foreground.appModule else None,
			"foregroundWindow": _safeGet(foreground, "name") if foreground else None,
			"isControlAllowed": config.conf[CONFIG_SECTION]["allowControl"],
			"isControlApprovedThisSession": controlApproval.isApproved(),
			"allowedApps": sorted(parseAllowedApps(config.conf[CONFIG_SECTION]["allowedApps"])) or "all",
			"documentMode": _documentMode(),
			"lastSpeechId": self._speechLog.lastId,
		}

	def _getFocus(self, params: dict[str, Any]) -> dict[str, Any]:
		focus = api.getFocusObject()
		result = _describeWithAncestors(focus, list(api.getFocusAncestors())[1:])
		mode = _documentMode()
		if mode is not None:
			result["documentMode"] = mode
		return result

	def _getNavigator(self, params: dict[str, Any]) -> dict[str, Any]:
		navigator = api.getNavigatorObject()
		ancestors = []
		parent = _safeGet(navigator, "parent")
		while parent is not None and len(ancestors) < 30:
			ancestors.insert(0, parent)
			parent = _safeGet(parent, "parent")
		return _describeWithAncestors(navigator, ancestors[1:])

	def _getTree(self, params: dict[str, Any]) -> dict[str, Any]:
		roots = {
			"foreground": api.getForegroundObject,
			"focus": api.getFocusObject,
			"navigator": api.getNavigatorObject,
		}
		rootName = params.get("root", "foreground")
		if rootName not in roots:
			raise BridgeError("badParams", f"root must be one of {', '.join(roots)}.")
		if params.get("id") is not None and params.get("window") is not None:
			raise BridgeError("badParams", "Pass id or window, not both.")
		maxDepth = int(params.get("maxDepth", 4))
		maxNodes = min(int(params.get("maxNodes", 150)), MAX_TREE_NODES)
		maxChildren = int(params["maxChildren"]) if params.get("maxChildren") else None
		rootNote = None
		isWebPageUnavailable = False
		if params.get("id") is not None:
			root = self.foundObjectOnMain(params["id"])
		elif params.get("window") is not None:
			windowRoots = _windowRoots(params["window"])
			root = windowRoots[0]
			if len(windowRoots) > 1:
				rootNote = "started from the web document in that window"
			isWebPageUnavailable = _isWebPageUnavailable(params["window"], windowRoots)
		else:
			root = roots[rootName]()
		if rootName == "foreground" and params.get("id") is None and params.get("window") is None:
			# Browsers and Electron apps keep their content in a document that the window's
			# own children do not lead to, so start from the document the user is in.
			treeInterceptor = _safeGet(api.getFocusObject(), "treeInterceptor")
			document = _safeGet(treeInterceptor, "rootNVDAObject") if treeInterceptor else None
			if document is not None:
				root = document
				rootNote = "started from the web document in the foreground window"
		result = _walkTree(root, maxDepth, maxNodes, maxChildren)
		if rootNote:
			result["rootNote"] = rootNote
		if isWebPageUnavailable:
			result["webPageUnavailable"] = True
		return result

	def _getText(self, params: dict[str, Any]) -> dict[str, Any]:
		source = params.get("source", "focus")
		if source == "review":
			position = api.getReviewPosition()
			line = position.copy()
			line.expand(textInfos.UNIT_LINE)
			return {"source": source, "currentLine": line.text}
		if source == "focus":
			obj = api.getFocusObject()
			treeInterceptor = _safeGet(obj, "treeInterceptor")
			if treeInterceptor is not None and not treeInterceptor.passThrough:
				obj = treeInterceptor
		elif source == "navigator":
			obj = api.getNavigatorObject()
		else:
			raise BridgeError("badParams", "source must be one of focus, navigator, review.")
		try:
			allText = obj.makeTextInfo(textInfos.POSITION_ALL)
			if isinstance(obj, TreeInterceptor):
				text, isTruncated = _readLines(allText)
			else:
				text = allText.text
				isTruncated = len(text) > MAX_TEXT_CHARS
				text = text[:MAX_TEXT_CHARS]
		except (NotImplementedError, RuntimeError, LookupError):
			raise BridgeError(
				"noText",
				"This object has no readable text. Use getFocus or getTree to read its name and value instead.",
			)
		result: dict[str, Any] = {"source": source, "length": len(text), "text": text}
		if isTruncated:
			result["truncated"] = f"showing the first {len(text)} characters"
		try:
			caretLine = obj.makeTextInfo(textInfos.POSITION_CARET)
			caretLine.expand(textInfos.UNIT_LINE)
			result["caretLine"] = caretLine.text
		except (NotImplementedError, RuntimeError, LookupError):
			pass
		return result

	def _getSpeech(self, params: dict[str, Any]) -> dict[str, Any]:
		entries = self._speechLog.since(int(params.get("afterId", 0)), int(params.get("limit", 50)))
		return {"lastId": self._speechLog.lastId, "entries": [entry.toDict() for entry in entries]}

	def _speak(self, params: dict[str, Any]) -> dict[str, Any]:
		text = str(params.get("text", "")).strip()
		if not text:
			raise BridgeError("badParams", "text must not be empty.")
		if params.get("interrupt", False):
			speech.cancelSpeech()
		ui.message(text)
		return {"spoken": text}

	def _pressKeys(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Runs on the bridge thread: it sends keys on the main thread, then waits here for speech."""
		self.ensureUnlocked()
		keys = params.get("keys")
		if not isinstance(keys, list) or not keys or not all(isinstance(key, str) for key in keys):
			raise BridgeError(
				"badParams", 'keys must be a non-empty list of key names, such as ["tab", "shift+tab"].'
			)
		if len(keys) > MAX_KEYS_PER_CALL:
			raise BridgeError("badParams", f"At most {MAX_KEYS_PER_CALL} keys per call.")
		hold = params.get("hold") or []
		if not isinstance(hold, list) or any(key not in windows.HOLDABLE_KEYS for key in hold):
			raise BridgeError("badParams", f"hold may only contain {', '.join(windows.HOLDABLE_KEYS)}.")
		gestures = wxCallOnMain(self._parseKeys, keys)
		if hold and any(_usesNvdaKey(gesture) for gesture in gestures):
			raise BridgeError("badParams", "NVDA key commands cannot be combined with hold.")

		def perform() -> None:
			heldKeys: list[int] = []
			try:
				for name in hold:
					self._setKeyDown(windows.HOLDABLE_KEYS[name], True)
					heldKeys.append(windows.HOLDABLE_KEYS[name])
				for gesture in gestures:
					if hold:
						# NVDA would look up the command for the key without the held modifiers.
						wxCallOnMain(gesture.send)
					else:
						wxCallOnMain(_pressGesture, gesture)
						self._waitForQueuedScripts()
					time.sleep(DELAY_BETWEEN_KEYS_SECONDS)
			finally:
				for vk in reversed(heldKeys):
					self._setKeyDown(vk, False)

		details: dict[str, Any] = {"keys": keys}
		if hold:
			details["hold"] = hold
		return self.runControlled("pressKeys", details, perform, params)

	@staticmethod
	def _waitForQueuedScripts() -> None:
		"""NVDA queues the command a key runs; wait for it, so keys and commands happen in order."""
		done = threading.Event()
		wxCallOnMain(queueHandler.queueFunction, queueHandler.eventQueue, done.set)
		done.wait(SCRIPT_WAIT_SECONDS)

	@staticmethod
	def _setKeyDown(vk: int, isDown: bool) -> None:
		with ignoreInjection():
			windows.setKeyDown(vk, isDown)
			time.sleep(HOLD_KEY_DELAY_SECONDS)

	def _typeText(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Runs on the bridge thread, so typing slowly does not freeze NVDA."""
		self.ensureUnlocked()
		text = params.get("text")
		if not isinstance(text, str) or not text:
			raise BridgeError("badParams", "text must be a non-empty string.")
		if len(text) > MAX_TYPE_CHARS:
			raise BridgeError("badParams", f"At most {MAX_TYPE_CHARS} characters per call.")
		if "\r" in text or "\n" in text:
			raise BridgeError(
				"badParams",
				"text must be a single line. Type each line separately and press enter between them.",
			)
		delaySeconds = min(int(params.get("delayMs", 0)), MAX_TYPE_DELAY_MS) / 1000

		def perform() -> None:
			with ignoreInjection():
				windows.typeText(text, delaySeconds)
				# Windows hands injected input to NVDA's keyboard hook asynchronously.
				time.sleep(HOLD_KEY_DELAY_SECONDS)

		return self.runControlled("typeText", {"text": text}, perform, params)

	def _listWindows(self, params: dict[str, Any]) -> dict[str, Any]:
		foreground = windows.foregroundWindow()
		return {
			"windows": [
				window.toDict(self._appNameOfProcess(window.processId), window.handle == foreground)
				for window in windows.listWindows(bool(params.get("includeHidden")))
			]
		}

	@staticmethod
	def _appNameOfProcess(processId: int) -> str | None:
		try:
			return appModuleHandler.getAppNameFromProcessID(processId)
		except Exception:  # noqa: BLE001 - the process may have exited or be inaccessible
			return None

	def _activateWindow(self, params: dict[str, Any]) -> dict[str, Any]:
		self.ensureUnlocked()
		handle = params.get("handle")
		titleContains = params.get("titleContains")
		if handle is not None:
			if not isinstance(handle, int) or not windows.isWindow(handle):
				raise BridgeError("noSuchWindow", "That window no longer exists. Call listWindows again.")
			matches = [
				window for window in windows.listWindows(includeHidden=True) if window.handle == handle
			]
		elif isinstance(titleContains, str) and titleContains.strip():
			matches = windows.matchWindows(windows.listWindows(includeHidden=True), titleContains.strip())
		else:
			raise BridgeError("badParams", "Pass either handle (from listWindows) or titleContains.")
		if not matches:
			raise BridgeError(
				"noSuchWindow",
				f"No window matches {titleContains or handle!r}. Call listWindows to see the titles.",
			)
		target = matches[0]
		targetApp = self._appNameOfProcess(target.processId)

		def perform() -> None:
			if not wxCallOnMain(windows.activateWindow, target.handle):
				raise BridgeError(
					"activationFailed",
					f"Windows did not let NVDA bring {target.title!r} to the front. "
					"It may belong to a program running as administrator.",
				)
			deadline = time.monotonic() + FOREGROUND_CATCH_UP_SECONDS
			while not wxCallOnMain(_isNvdaForeground, target.handle):
				if time.monotonic() >= deadline:
					wxCallOnMain(_reportForeground, target.handle)
					break
				time.sleep(0.05)

		result = self.runControlled(
			"activateWindow", {"title": target.title}, perform, params, targetApp=targetApp
		)
		result["window"] = target.toDict(targetApp, True)
		if len(matches) > 1:
			result["otherMatches"] = [window.title for window in matches[1:6]]
		return result

	def _waitForSpeech(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Runs on the bridge thread, which may block for the whole wait."""
		contains = params.get("contains")
		if contains is not None and (not isinstance(contains, str) or not contains):
			raise BridgeError(
				"badParams", "contains must be non-empty text, or left out to wait for any speech."
			)
		afterId = params.get("afterId")
		afterId = self._speechLog.lastId if afterId is None else int(afterId)
		timeoutSeconds = min(float(params.get("timeoutMs", 10000)) / 1000, MAX_WAIT_FOR_SPEECH_SECONDS)
		needle = contains.casefold() if contains else None
		match = self._speechLog.waitFor(
			afterId, lambda text: needle is None or needle in text.casefold(), timeoutSeconds
		)
		return {
			"found": match is not None,
			"match": match.toDict() if match else None,
			"speech": [entry.toDict() for entry in self._speechLog.since(afterId, 50)],
			"lastId": self._speechLog.lastId,
		}

	def _findObjectsHandler(self, params: dict[str, Any]) -> dict[str, Any]:
		nameContains = params.get("nameContains") or None
		role = params.get("role") or None
		if nameContains is None and role is None:
			raise BridgeError("badParams", "Pass nameContains, role, or both.")
		maxResults = min(int(params.get("maxResults", 20)), MAX_FIND_RESULTS)
		if params.get("within") is not None and params.get("window") is not None:
			raise BridgeError("badParams", "Pass within or window, not both.")
		isWebPageUnavailable = False
		if params.get("within") is not None:
			# A large web page can use up the search budget before the part that matters.
			container = self.foundObjectOnMain(params["within"])
			matches, stoppedReason = findObjects(container, nameContains, role, maxResults)
		elif params.get("window") is not None:
			windowRoots = _windowRoots(params["window"])
			matches, stoppedReason = _searchRoots(windowRoots, nameContains, role, maxResults)
			isWebPageUnavailable = _isWebPageUnavailable(params["window"], windowRoots)
		else:
			matches, stoppedReason = self.searchForeground(nameContains, role, maxResults)
		ids = self.registerObjects(matches)
		result: dict[str, Any] = {
			"objects": [{"id": objectId, **describeObject(obj)} for objectId, obj in zip(ids, matches)],
			"truncated": stoppedReason,
		}
		if isWebPageUnavailable:
			result["webPageUnavailable"] = True
		return result

	def searchForeground(
		self,
		nameContains: str | None,
		role: str | None,
		maxResults: int,
		predicate: Callable[[NVDAObject], bool] | None = None,
	) -> tuple[list[NVDAObject], str | None]:
		"""Search the foreground window, and the web document in it if any, on the main thread.

		The focused control comes first when it matches, so a search cut short never misses it,
		then the web document focus is in, if any, then the rest of the window.
		"""
		focus = api.getFocusObject()
		matches = [focus] if _objectMatches(focus, nameContains, role, predicate) else []
		treeInterceptor = _safeGet(focus, "treeInterceptor")
		document = _safeGet(treeInterceptor, "rootNVDAObject") if treeInterceptor else None
		# Browsers and Electron apps keep their content in a document the window's own children may not lead to.
		roots = [root for root in (document, api.getForegroundObject()) if root is not None]
		return _searchRoots(roots, nameContains, role, maxResults, predicate, matches)

	def registerObjects(self, objects: list[NVDAObject]) -> list[int]:
		"""Give found controls ids that tools such as focusObject and activateObject accept."""
		return self._objects.add(objects)

	@property
	def lastFound(self) -> list[tuple[int, NVDAObject]]:
		"""The ids and controls of the most recent search."""
		return self._objects.last

	def foundObjectOnMain(self, objectId: Any) -> NVDAObject:
		"""The control with this id from findObjects or previewSpeech. Must be called on the main thread."""
		obj = self._objects.get(objectId) if isinstance(objectId, int) else None
		if obj is None:
			if isinstance(objectId, int) and self._objects.isForgotten(objectId):
				raise BridgeError(
					"staleObject",
					f"Id {objectId} is from too many searches ago and was forgotten. Call findObjects again.",
				)
			raise BridgeError("badParams", "id must be an id from findObjects.")
		if _safeGet(obj, "role") is None:
			raise BridgeError("staleObject", "That control is gone. Call findObjects again.")
		return obj

	def foundObject(self, params: dict[str, Any]) -> NVDAObject:
		return wxCallOnMain(self.foundObjectOnMain, params.get("id"))

	def _focusObject(self, params: dict[str, Any]) -> dict[str, Any]:
		self.ensureUnlocked()
		obj = self.foundObject(params)
		return self.runControlled(
			"focusObject",
			{"object": wxCallOnMain(_safeGet, obj, "name")},
			lambda: wxCallOnMain(obj.setFocus),
			params,
			targetApp=wxCallOnMain(_appNameOf, obj),
		)

	def _activateObject(self, params: dict[str, Any]) -> dict[str, Any]:
		self.ensureUnlocked()
		obj = self.foundObject(params)

		def perform() -> None:
			try:
				wxCallOnMain(obj.doAction)
			except NotImplementedError:
				raise BridgeError(
					"noAction", "This control has no default action. Focus it and press keys instead."
				)

		return self.runControlled(
			"activateObject",
			{"object": wxCallOnMain(_safeGet, obj, "name")},
			perform,
			params,
			targetApp=wxCallOnMain(_appNameOf, obj),
		)

	def _inspectObject(self, params: dict[str, Any]) -> dict[str, Any]:
		if params.get("id") is not None:
			return inspectObject(self.foundObjectOnMain(params["id"]))
		target = params.get("target", "focus")
		if target == "focus":
			return inspectObject(api.getFocusObject())
		if target == "navigator":
			return inspectObject(api.getNavigatorObject())
		raise BridgeError("badParams", "target must be focus or navigator, or pass an id from findObjects.")

	def _setValue(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Runs on the bridge thread, like typeText. Works on controls in background windows too."""
		self.ensureUnlocked()
		text = params.get("text")
		if not isinstance(text, str):
			raise BridgeError("badParams", "text must be a string. Pass an empty string to clear the field.")
		if len(text) > MAX_TYPE_CHARS:
			raise BridgeError("badParams", f"At most {MAX_TYPE_CHARS} characters per call.")
		obj = self.foundObject(params) if params.get("id") is not None else wxCallOnMain(api.getFocusObject)
		used: dict[str, str] = {}

		def perform() -> None:
			used["method"] = wxCallOnMain(_setObjectValue, obj, text)

		result = self.runControlled(
			"setValue",
			{"object": wxCallOnMain(_safeGet, obj, "name"), "text": text},
			perform,
			params,
			targetApp=wxCallOnMain(_appNameOf, obj),
		)
		result["method"] = used.get("method")
		result["object"] = wxCallOnMain(describeObject, obj)
		return result

	def _setDocumentMode(self, params: dict[str, Any]) -> dict[str, Any]:
		self.ensureUnlocked()
		mode = params.get("mode")
		if mode not in ("browse", "focus"):
			raise BridgeError("badParams", "mode must be browse or focus.")
		document = wxCallOnMain(_requireBrowseModeDocument)

		def perform() -> None:
			def switch() -> None:
				document.passThrough = mode == "focus"
				# Plays NVDA's mode sound or says the mode, as NVDA+space does.
				reportPassThrough(document, onlyIfChanged=True)

			wxCallOnMain(switch)

		return self.runControlled("setDocumentMode", {"mode": mode}, perform, params)

	def _findInPage(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Like NVDA's find command (NVDA+control+f), without its dialogs: moves the browse mode cursor."""
		self.ensureUnlocked()
		text = params.get("text")
		if not isinstance(text, str) or not text.strip():
			raise BridgeError("badParams", "text must not be empty.")
		reverse = bool(params.get("reverse"))
		caseSensitive = bool(params.get("caseSensitive"))
		fromStart = bool(params.get("fromStart"))
		document = wxCallOnMain(_requireBrowseModeDocument)
		if document.passThrough:
			raise BridgeError("focusMode", "NVDA is in focus mode here. Switch to browse mode first.")
		found: dict[str, Any] = {}

		def perform() -> None:
			def find() -> None:
				start = textInfos.POSITION_LAST if fromStart and reverse else textInfos.POSITION_FIRST
				info = document.makeTextInfo(start if fromStart else textInfos.POSITION_CARET)
				if not info.find(text, caseSensitive=caseSensitive, reverse=reverse):
					raise BridgeError(
						"notFound",
						f"{text!r} was not found {'above' if reverse else 'below'} the cursor. "
						"Search fromStart, or in the other direction.",
					)
				document.selection = info
				# Lets the user continue the same search with NVDA+F3.
				CursorManager._lastFindText = text
				CursorManager._lastCaseSensitivity = caseSensitive
				speech.cancelSpeech()
				info.move(textInfos.UNIT_LINE, 1, endPoint="end")
				found["line"] = info.text.strip()
				speech.speakTextInfo(info, reason=controlTypes.OutputReason.CARET)

			wxCallOnMain(find)

		result = self.runControlled("findInPage", {"text": text}, perform, params)
		result["foundLine"] = found.get("line")
		return result

	def _listElements(self, params: dict[str, Any]) -> dict[str, Any]:
		"""The items NVDA's Elements List (NVDA+F7) shows, such as headings, links or landmarks."""
		elementType = params.get("type", "heading")
		if elementType not in ELEMENT_TYPES:
			raise BridgeError("badParams", f"type must be one of {', '.join(ELEMENT_TYPES)}.")
		maxResults = min(int(params.get("maxResults", 50)), MAX_ELEMENTS)
		document = _requireBrowseModeDocument()
		deadline = time.monotonic() + TREE_TIME_BUDGET_SECONDS
		items = []
		truncated = None
		try:
			for item in document._iterNodesByType(elementType, "next", None):
				if len(items) >= maxResults:
					truncated = f"stopped at {maxResults} results"
					break
				if time.monotonic() > deadline:
					truncated = f"stopped after {TREE_TIME_BUDGET_SECONDS} seconds"
					break
				items.append(item)
		except NotImplementedError:
			raise BridgeError("badParams", f"This document cannot list {elementType} elements.")
		self._foundElements = items
		elements = []
		for index, item in enumerate(items, 1):
			element: dict[str, Any] = {"id": index, "label": _safeGet(item, "label")}
			level = _safeGet(_safeGet(item, "obj"), "positionInfo") or {}
			if elementType == "heading" and "level" in level:
				element["level"] = level["level"]
			elements.append(element)
		return {"type": elementType, "elements": elements, "truncated": truncated}

	def _moveToElement(self, params: dict[str, Any]) -> dict[str, Any]:
		self.ensureUnlocked()
		elementId = params.get("id")
		if not isinstance(elementId, int) or not 1 <= elementId <= len(self._foundElements):
			raise BridgeError("badParams", "id must be one of the ids from the last listElements call.")
		item = self._foundElements[elementId - 1]
		activate = bool(params.get("activate"))

		def perform() -> None:
			def move() -> None:
				item.moveTo()
				if activate:
					item.activate()
				else:
					item.report()

			wxCallOnMain(move)

		return self.runControlled(
			"moveToElement",
			{"element": _safeGet(item, "label"), "activate": activate},
			perform,
			params,
		)

	def _getActionLog(self, params: dict[str, Any]) -> dict[str, Any]:
		return {
			"path": self._actionLog.path,
			"isLogging": config.conf[CONFIG_SECTION]["logActions"],
			"entries": self._actionLog.tail(min(int(params.get("limit", 20)), 200)),
		}

	def runControlled(
		self,
		action: str,
		details: dict[str, Any],
		perform: Callable[[], None],
		params: dict[str, Any],
		targetApp: str | None = None,
		checkApp: bool = True,
	) -> dict[str, Any]:
		"""Check permissions, log the action, run it, then wait for NVDA to finish speaking.

		:param targetApp: The application the action affects; the foreground application when None.
		:param checkApp: False for actions on NVDA itself, which the allowed applications setting does not cover.
		"""
		settleSeconds = float(params.get("settleMs", 400)) / 1000
		timeoutSeconds = float(params.get("timeoutMs", 3000)) / 1000
		clientName = params.get("clientName") if isinstance(params.get("clientName"), str) else None
		deadline = controlApproval.startDeadline(time.monotonic(), timeoutSeconds)
		with self._controlTurn(deadline):
			self._ensureControlAllowed(clientName, deadline)
			foreground = wxCallOnMain(api.getForegroundObject)
			window = wxCallOnMain(_safeGet, foreground, "name") if foreground else None
			if targetApp is None:
				targetApp = wxCallOnMain(_appNameOf, foreground)
			if checkApp:
				self._ensureAppAllowed(targetApp)
			if config.conf[CONFIG_SECTION]["logActions"]:
				try:
					client = {"client": clientName} if clientName else {}
					self._actionLog.record(action, window, app=targetApp, **client, **details)
				except OSError:
					log.error("NVDA MCP could not write its action log", exc_info=True)
			startId = self._speechLog.lastId
			perform()
			result: dict[str, Any] = {}
			untilSpeech = params.get("untilSpeech")
			if untilSpeech:
				# Wait for the expected announcement, which may come after other speech or a pause,
				# then for NVDA to finish what it is saying.
				needle = str(untilSpeech).casefold()
				started = time.monotonic()
				match = self._speechLog.waitFor(
					startId, lambda text: needle in text.casefold(), timeoutSeconds
				)
				result["expectedSpeechHeard"] = match is not None
				timeoutSeconds = max(timeoutSeconds - (time.monotonic() - started), settleSeconds)
			spoken = self._speechLog.waitForQuiet(startId, settleSeconds, timeoutSeconds)
			result["speech"] = [entry.toDict() for entry in spoken]
			result["focus"] = wxCallOnMain(self._getFocus, {})
			return result

	@staticmethod
	def _ensureAppAllowed(appName: str | None) -> None:
		allowedApps = parseAllowedApps(config.conf[CONFIG_SECTION]["allowedApps"])
		if allowedApps and (appName or "").casefold() not in allowedApps:
			raise BridgeError(
				"appNotAllowed",
				f"The user only lets MCP clients control {', '.join(sorted(allowedApps))}, not {appName}. "
				"Ask them to add it in NVDA Settings, NVDA MCP category, if they want to.",
			)

	@staticmethod
	def _parseKeys(keys: list[str]) -> list[KeyboardInputGesture]:
		gestures = []
		for key in keys:
			try:
				gesture = KeyboardInputGesture.fromName(key)
			except (LookupError, ValueError):
				raise BridgeError(
					"badParams",
					f"Unknown key {key!r}. Use NVDA key names such as tab, enter, control+home, alt+f4, downArrow.",
				)
			if _usesNvdaKey(gesture) and gesture.script is None:
				raise BridgeError(
					"badParams",
					f"No NVDA command uses {key!r} where focus is now, so no keys were pressed. "
					"nvda_list_scripts shows the commands and their keys.",
				)
			gestures.append(gesture)
		return gestures

	@contextmanager
	def _controlTurn(self, deadline: float) -> Iterator[None]:
		"""Run one control action at a time, giving up if the previous one does not finish before deadline."""
		if not self._controlLock.acquire(timeout=max(deadline - time.monotonic(), 0)):
			raise _controlBusyError()
		try:
			yield
		finally:
			self._controlLock.release()

	def _ensureControlAllowed(self, clientName: str | None, deadline: float) -> None:
		"""
		:param clientName: The name the MCP client gave itself, such as "Claude Code", to show the user.
		:param deadline: When the user's answer comes too late, from time.monotonic().
		"""
		sectionConfig = config.conf[CONFIG_SECTION]
		if not sectionConfig["allowControl"]:
			raise BridgeError(
				"controlDisabled",
				"Pressing keys is turned off. Ask the user to enable it in NVDA Settings, NVDA MCP category.",
			)
		if controlApproval.isApproved():
			return
		if not (sectionConfig["confirmControl"] or controlApproval.wasRevoked()):
			return
		secondsLeft = deadline - time.monotonic()
		if secondsLeft < controlApproval.MIN_ANSWER_SECONDS:
			raise _controlBusyError()
		answer = wxCallOnMain(self._askForControlApproval, clientName, secondsLeft)
		if answer is None:
			raise BridgeError(
				"approvalTimedOut",
				f"NVDA asked the user to allow key presses, but they did not answer within {round(secondsLeft)} "
				"seconds, so nothing was done. Tell the user, and try again when they are ready to answer.",
			)
		if not answer:
			raise BridgeError(
				"controlDenied",
				"The user declined to let this client press keys. Do not retry unless they ask.",
			)
		controlApproval.approve()
		# Give Windows time to hand focus back to the user's window before keys are sent.
		time.sleep(FOCUS_RETURN_DELAY_SECONDS)

	@staticmethod
	def _askForControlApproval(clientName: str | None, timeoutSeconds: float) -> bool | None:
		"""Ask the user whether the client may press keys.

		:param timeoutSeconds: Close the dialog after this long, since the client stops waiting for the answer.
		:return: The answer, or None if the user did not answer in time.
		"""
		import wx
		from gui import mainFrame
		from gui.message import DefaultButtonSet, DialogType, MessageDialog, ReturnCode

		if clientName:
			# Translators: Says who wants to press keys, in the dialog asking to allow it.
			# {client} is the name the program gives itself, such as Claude Code; NVDA cannot verify it.
			who = _("An MCP client calling itself {client}").format(client=clientName)
			# Translators: Title of the dialog asking to allow an MCP client to press keys.
			# {client} is the name the program gives itself, such as Claude Code.
			title = _("NVDA MCP: allow {client} to press keys?").format(client=clientName)
		else:
			# Translators: Says who wants to press keys, when the program gave no name.
			who = _("An MCP client, such as an AI assistant,")
			# Translators: Title of the dialog asking to allow an MCP client to press keys, when it gave no name.
			title = _("NVDA MCP: allow an MCP client to press keys?")
		# The title says who asks and what for, since NVDA always speaks it;
		# the message is spoken only when reporting object descriptions is on (NVDA+B reads it anyway).
		dialog = MessageDialog(
			mainFrame,
			# Translators: Asks the user whether an AI assistant may press keys through NVDA.
			# {who} is who is asking, such as "An MCP client calling itself Claude Code".
			_(
				"{who} wants to press keys on this computer through NVDA, "
				"for example to move through an application with Tab. "
				"Keys go to whichever window is active.\n\n"
				"Allow this until NVDA restarts?"
			).format(who=who),
			title,
			dialogType=DialogType.WARNING,
			buttons=DefaultButtonSet.YES_NO,
		)
		dialog.setDefaultFocus(ReturnCode.NO)
		# Escape and closing the dialog answer No, and let the timer below close it.
		dialog.setFallbackAction(ReturnCode.NO)
		timedOut = False

		def expire() -> None:
			nonlocal timedOut
			timedOut = True
			dialog.Close()

		timer = wx.CallLater(int(timeoutSeconds * 1000), expire)
		# prePopup/postPopup return focus to the user's window after the dialog closes.
		mainFrame.prePopup()
		try:
			answer = dialog.ShowModal()
		finally:
			timer.Stop()
			mainFrame.postPopup()
		if timedOut:
			# Translators: Reported when the user did not answer in time whether an MCP client may press keys.
			ui.message(_("NVDA MCP stopped waiting for your answer, so no keys were pressed."))
			return None
		return answer == ReturnCode.YES
