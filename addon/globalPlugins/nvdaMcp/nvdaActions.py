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
from collections.abc import Callable
from typing import Any

import addonHandler
import api
import appModuleHandler
import config
import controlTypes
import inputCore
import keyboardHandler
import queueHandler
import speech
import synthDriverHandler
import textInfos
import ui
import versionInfo
from browseMode import BrowseModeTreeInterceptor, reportPassThrough
from cursorManager import CursorManager
from gui.guiHelper import wxCallOnMain
from keyboardHandler import KeyboardInputGesture, ignoreInjection
from logHandler import log
from NVDAObjects import NVDAObject
from treeInterceptorHandler import TreeInterceptor
from utils.security import isLockScreenModeActive

from . import windows
from .actionLog import ActionLog
from .bridge import BridgeError, Handler
from .configSpec import CONFIG_SECTION, parseAllowedApps
from .speechLog import SpeechLog

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
# Lets NVDA's keyboard hook see injected keys while it is still told to ignore them.
HOLD_KEY_DELAY_SECONDS = 0.05
# How long to wait for an NVDA command run by a key press before pressing the next key.
SCRIPT_WAIT_SECONDS = 5.0
MAX_TYPE_CHARS = 2000
MAX_TYPE_DELAY_MS = 200
MAX_WAIT_FOR_SPEECH_SECONDS = 120.0
MAX_FIND_RESULTS = 50
MAX_FIND_VISITS = 5000
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
	"""Depth-first walk using firstChild/next, bounded by depth, node count and time.

	Unnamed layout containers below the root are left out and their children shown in their place,
	so depth and node limits are spent on objects a user would actually meet.
	:param maxChildren: Show at most this many children of any object, so one long list
		does not use up the node limit. The node says how many were left out.
	"""
	deadline = time.monotonic() + TREE_TIME_BUDGET_SECONDS
	nodeCount = 0
	truncatedReason: str | None = None

	def childrenOf(obj: NVDAObject, depth: int, nesting: int) -> list[dict[str, Any]]:
		nonlocal nodeCount, truncatedReason
		children: list[dict[str, Any]] = []
		child = _safeGet(obj, "firstChild")
		while child is not None:
			if maxChildren is not None and len(children) >= maxChildren:
				children.append({"moreChildren": True})
				break
			if nodeCount >= maxNodes:
				truncatedReason = f"stopped after {maxNodes} nodes"
				break
			if time.monotonic() > deadline:
				truncatedReason = f"stopped after {TREE_TIME_BUDGET_SECONDS} seconds"
				break
			if nesting >= MAX_TREE_NESTING:
				truncatedReason = f"stopped at {MAX_TREE_NESTING} levels of nesting"
				break
			if _isLayoutOnly(child):
				children.extend(childrenOf(child, depth, nesting + 1))
			else:
				children.append(visit(child, depth + 1, nesting + 1))
			child = _safeGet(child, "next")
		return children

	def visit(obj: NVDAObject, depth: int, nesting: int) -> dict[str, Any]:
		nonlocal nodeCount
		nodeCount += 1
		node = describeObject(obj)
		if depth < maxDepth:
			children = childrenOf(obj, depth, nesting)
			if children and children[-1].get("moreChildren"):
				children.pop()
				childCount = _safeGet(obj, "childCount")
				# childCount also counts layout containers, so the number is only a guide when children were flattened.
				hasCount = isinstance(childCount, int) and childCount > len(children)
				node["moreChildren"] = childCount - len(children) if hasCount else True
			if children:
				node["children"] = children
		return node

	tree = visit(root, 0, 0)
	return {"nodeCount": nodeCount, "truncated": truncatedReason, "tree": tree}


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
	deadline = time.monotonic() + TREE_TIME_BUDGET_SECONDS
	matches: list[NVDAObject] = []
	queue: deque[tuple[NVDAObject, int]] = deque([(root, 0)])
	visits = 0
	while queue:
		obj, nesting = queue.popleft()
		visits += 1
		if visits > MAX_FIND_VISITS:
			return matches, f"stopped after looking at {MAX_FIND_VISITS} objects"
		if time.monotonic() > deadline:
			return matches, f"stopped after {TREE_TIME_BUDGET_SECONDS} seconds"
		if obj is not root and _objectMatches(obj, nameContains, role, predicate):
			matches.append(obj)
			if len(matches) >= maxResults:
				return matches, f"stopped at {maxResults} results"
		if nesting < MAX_TREE_NESTING:
			child = _safeGet(obj, "firstChild")
			while child is not None:
				queue.append((child, nesting + 1))
				child = _safeGet(child, "next")
	return matches, None


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


class NvdaActions:
	"""Implements bridge methods and owns the per-session control approval."""

	def __init__(self, speechLog: SpeechLog, actionLog: ActionLog) -> None:
		self._speechLog = speechLog
		self._actionLog = actionLog
		self._isControlApprovedThisSession = False
		self._wasControlRevoked = False
		# One action at a time, so concurrent requests cannot interleave keys or steal each other's speech.
		self._controlLock = threading.Lock()
		# Results of the last findObjects call, addressed by 1-based id in focusObject and activateObject.
		self._foundObjects: list[NVDAObject] = []
		# Results of the last listElements call, addressed by 1-based id in moveToElement.
		self._foundElements: list[Any] = []

	def revokeControlApproval(self) -> None:
		"""Require the user to approve again before the next key press, even if confirmation is turned off."""
		self._isControlApprovedThisSession = False
		self._wasControlRevoked = True

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
			"isControlApprovedThisSession": self._isControlApprovedThisSession,
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
		maxDepth = int(params.get("maxDepth", 4))
		maxNodes = min(int(params.get("maxNodes", 150)), MAX_TREE_NODES)
		maxChildren = int(params["maxChildren"]) if params.get("maxChildren") else None
		root = roots[rootName]()
		rootNote = None
		if rootName == "foreground":
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
		matches, stoppedReason = self.searchForeground(nameContains, role, maxResults)
		return {
			"objects": [{"id": index, **describeObject(obj)} for index, obj in enumerate(matches, 1)],
			"truncated": stoppedReason,
		}

	def searchForeground(
		self,
		nameContains: str | None,
		role: str | None,
		maxResults: int,
		predicate: Callable[[NVDAObject], bool] | None = None,
	) -> tuple[list[NVDAObject], str | None]:
		"""Search the foreground window, and the web document in it if any, on the main thread.

		The matches become the objects that ids in focusObject, activateObject and other tools refer to.
		The focused control comes first when it matches, so a search cut short never misses it,
		then the web document focus is in, if any, then the rest of the window.
		"""
		focus = api.getFocusObject()
		matches = [focus] if _objectMatches(focus, nameContains, role, predicate) else []
		treeInterceptor = _safeGet(focus, "treeInterceptor")
		document = _safeGet(treeInterceptor, "rootNVDAObject") if treeInterceptor else None
		# Browsers and Electron apps keep their content in a document the window's own children may not lead to.
		roots = [root for root in (document, api.getForegroundObject()) if root is not None]
		stoppedReasons = []
		for root in roots:
			if len(matches) >= maxResults:
				break
			moreMatches, stoppedReason = findObjects(
				root, nameContains, role, maxResults - len(matches), predicate
			)
			matches += [match for match in moreMatches if match not in matches]
			if stoppedReason:
				stoppedReasons.append(stoppedReason)
		if len(matches) >= maxResults:
			stoppedReason = f"stopped at {maxResults} results"
		else:
			stoppedReason = "; ".join(stoppedReasons) or None
		self._foundObjects = matches
		return matches, stoppedReason

	@property
	def foundObjects(self) -> list[NVDAObject]:
		return list(self._foundObjects)

	def foundObjectOnMain(self, objectId: Any) -> NVDAObject:
		"""The object with this id from the last search. Must be called on the main thread."""
		if not isinstance(objectId, int) or not 1 <= objectId <= len(self._foundObjects):
			raise BridgeError("badParams", "id must be one of the ids from the last findObjects call.")
		obj = self._foundObjects[objectId - 1]
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
		with self._controlLock:
			self._ensureControlAllowed(clientName)
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

	def _ensureControlAllowed(self, clientName: str | None = None) -> None:
		"""
		:param clientName: The name the MCP client gave itself, such as "Claude Code", to show the user.
		"""
		sectionConfig = config.conf[CONFIG_SECTION]
		if not sectionConfig["allowControl"]:
			raise BridgeError(
				"controlDisabled",
				"Pressing keys is turned off. Ask the user to enable it in NVDA Settings, NVDA MCP category.",
			)
		if self._isControlApprovedThisSession:
			return
		if not (sectionConfig["confirmControl"] or self._wasControlRevoked):
			return
		if not wxCallOnMain(self._askForControlApproval, clientName):
			raise BridgeError(
				"controlDenied",
				"The user declined to let this client press keys. Do not retry unless they ask.",
			)
		self._isControlApprovedThisSession = True
		self._wasControlRevoked = False
		# Give Windows time to hand focus back to the user's window before keys are sent.
		time.sleep(FOCUS_RETURN_DELAY_SECONDS)

	@staticmethod
	def _askForControlApproval(clientName: str | None) -> bool:
		from gui import mainFrame
		from gui.message import DefaultButtonSet, DialogType, MessageDialog, ReturnCode

		if clientName:
			# Translators: Says who wants to press keys, in the dialog asking to allow it.
			# {client} is the name the program gives itself, such as Claude Code; NVDA cannot verify it.
			who = _("An MCP client calling itself {client}").format(client=clientName)
		else:
			# Translators: Says who wants to press keys, when the program gave no name.
			who = _("An MCP client, such as an AI assistant,")
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
			# Translators: Title of the dialog asking to allow an AI assistant to press keys.
			_("NVDA MCP: allow key presses?"),
			dialogType=DialogType.WARNING,
			buttons=DefaultButtonSet.YES_NO,
		)
		dialog.setDefaultFocus(ReturnCode.NO)
		# prePopup/postPopup return focus to the user's window after the dialog closes.
		mainFrame.prePopup()
		try:
			return dialog.ShowModal() == ReturnCode.YES
		finally:
			mainFrame.postPopup()
