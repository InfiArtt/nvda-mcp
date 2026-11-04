# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Records what an action changed: part of the accessibility tree before and after it, and the events
NVDA handled meanwhile. The MCP server compares the two snapshots.

Functions in this module touch NVDAObjects, so the snapshots are taken on NVDA's main thread.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import api
import controlTypes
from gui.guiHelper import wxCallOnMain
from logHandler import log
from NVDAObjects import NVDAObject
from NVDAObjects.IAccessible import IAccessible
from NVDAObjects.UIA import UIA
from NVDAObjects.window import Window

from .bridge import BridgeError
from .nvdaActions import _isLayoutOnly, _isWebPageUnavailable, _safeGet, _windowRoots, isObjectAlive
from .treeWalk import snapshotTree

# A snapshot holds the main thread, so NVDA is silent while it runs: keep it small and short.
SNAPSHOT_MAX_NODES = 400
SNAPSHOT_MAX_DEPTH = 15
SNAPSHOT_HEAD_CHILDREN = 15
SNAPSHOT_TAIL_CHILDREN = 25
SNAPSHOT_TIME_BUDGET_SECONDS = 2.5
SNAPSHOT_MAX_NESTING = 100
MAX_SNAPSHOT_TEXT = 400
# Long names keep their end too: chat rows end with the time or a delivery status.
SNAPSHOT_TEXT_TAIL = 99
MAX_RECORDED_EVENTS = 200
MAX_FOCUS_PATH = 60
# How much longer a control action with recording may take, for the two snapshots.
RECORDING_EXTRA_SECONDS = 2 * SNAPSHOT_TIME_BUDGET_SECONDS + 1


def clipText(text: str) -> str:
	if len(text) <= MAX_SNAPSHOT_TEXT:
		return text
	return text[: MAX_SNAPSHOT_TEXT - SNAPSHOT_TEXT_TAIL - 1] + "…" + text[-SNAPSHOT_TEXT_TAIL:]


def objectKey(obj: NVDAObject) -> str | None:
	"""A stable identity for an object, so the same control can be found in a later snapshot.

	IAccessible2 objects (web pages in Chromium and Firefox) have a unique id per window,
	the identity NVDA's browse mode uses too; UI Automation elements have a runtime id.
	"""
	try:
		if isinstance(obj, IAccessible):
			uniqueId = obj.IA2UniqueID
			if uniqueId is not None:
				return f"ia2:{obj.windowHandle}:{uniqueId}"
			if obj.event_childID == 0 and obj.event_objectID == -4:  # OBJID_CLIENT of a window
				return f"hwnd:{obj.windowHandle}"
			return None
		if isinstance(obj, UIA):
			return "uia:" + ".".join(str(part) for part in obj.UIAElement.GetRuntimeId())
		if isinstance(obj, Window):
			return f"hwnd:{obj.windowHandle}"
	except Exception:  # noqa: BLE001 - applications raise COMError and others
		return None
	return None


def _snapshotNode(obj: NVDAObject) -> dict[str, Any]:
	role = _safeGet(obj, "role")
	node: dict[str, Any] = {
		"key": objectKey(obj),
		"role": role.displayString if role is not None else "unknown",
		# The same in every language, for the server's rules about lists.
		"roleId": role.name if role is not None else "UNKNOWN",
	}
	for name in ("name", "value", "description"):
		text = _safeGet(obj, name)
		if isinstance(text, str) and text.strip():
			node[name] = clipText(text)
	states = _safeGet(obj, "states") or set()
	shown = sorted(state.displayString for state in states if state != controlTypes.State.FOCUSED)
	if shown:
		node["states"] = shown
	if controlTypes.State.FOCUSED in states:
		node["focused"] = True
	return node


def takeSnapshot(root: NVDAObject, focusPath: set[str], maxNodes: int = SNAPSHOT_MAX_NODES) -> dict[str, Any]:
	"""Snapshot the tree below root, the focus branch first. Must run on the main thread."""
	return snapshotTree(
		root,
		firstChild=lambda obj: obj.firstChild,
		nextSibling=lambda obj: obj.next,
		lastChild=lambda obj: obj.lastChild,
		previousSibling=lambda obj: obj.previous,
		childCount=lambda obj: obj.childCount,
		describe=_snapshotNode,
		isLayoutOnly=_isLayoutOnly,
		isOnFocusPath=lambda obj: bool(focusPath) and objectKey(obj) in focusPath,
		maxNodes=maxNodes,
		maxDepth=SNAPSHOT_MAX_DEPTH,
		headChildren=SNAPSHOT_HEAD_CHILDREN,
		tailChildren=SNAPSHOT_TAIL_CHILDREN,
		timeBudgetSeconds=SNAPSHOT_TIME_BUDGET_SECONDS,
		maxNesting=SNAPSHOT_MAX_NESTING,
	)


def _focusPathKeys(obj: NVDAObject | None) -> set[str]:
	"""Keys of obj and its containers, so a snapshot reads that branch first."""
	keys: set[str] = set()
	current = obj
	desktop = api.getDesktopObject()
	for _step in range(MAX_FOCUS_PATH):
		if current is None or current == desktop:
			break
		key = objectKey(current)
		if key:
			keys.add(key)
		current = _safeGet(current, "parent")
	return keys


def _documentOrWindowOf(obj: NVDAObject) -> NVDAObject:
	"""The web document holding obj, or else its top-level window."""
	treeInterceptor = _safeGet(obj, "treeInterceptor")
	document = _safeGet(treeInterceptor, "rootNVDAObject") if treeInterceptor else None
	if document is not None:
		return document
	desktop = api.getDesktopObject()
	current = obj
	for _step in range(MAX_FOCUS_PATH):
		parent = _safeGet(current, "parent")
		if parent is None or parent == desktop:
			break
		if _safeGet(parent, "role") == controlTypes.Role.DOCUMENT:
			return parent
		current = parent
	return current


def rootLabel(obj: NVDAObject) -> dict[str, Any]:
	role = _safeGet(obj, "role")
	label = {"role": role.displayString if role is not None else "unknown", "name": _safeGet(obj, "name")}
	return {key: value for key, value in label.items() if value}


@dataclass
class Recording:
	root: NVDAObject
	rootNote: str | None
	focusPath: set[str]
	before: dict[str, Any] | None = None
	eventStartId: int = 0
	startedAt: float = 0.0
	extra: dict[str, Any] = field(default_factory=dict)


class InteractionRecorder:
	"""Takes the snapshots for a recording and collects the events NVDA handled meanwhile.

	:param readEvents: Reads traced events after an id, with what NVDA said for each (DevTools).
	"""

	# How much longer a control action with recording may take, for the two snapshots.
	extraSeconds = RECORDING_EXTRA_SECONDS

	def __init__(self, actions: Any, tracer: Any, readEvents: Callable[[int], list[dict[str, Any]]]) -> None:
		self._actions = actions
		self._tracer = tracer
		self._readEvents = readEvents

	def resolve(self, params: dict[str, Any], target: NVDAObject | None = None) -> Recording:
		"""Choose what to record, before anything happens. Must run on the main thread.

		:param params: ``within`` (an id), ``window`` (a background window handle) or neither.
		:param target: The control the action works on, if any; its document or window is recorded.
		"""
		if params.get("within") is not None and params.get("window") is not None:
			raise BridgeError("badParams", "Record within a control or a window, not both.")
		if params.get("within") is not None:
			root = self._actions.foundObjectOnMain(params["within"])
			return Recording(root, f"control {params['within']}", _focusPathKeys(api.getFocusObject()))
		if params.get("window") is not None:
			roots = _windowRoots(params["window"])
			recording = Recording(roots[0], "that window", set())
			if _isWebPageUnavailable(params["window"], roots):
				recording.extra["webPageUnavailable"] = True
			return recording
		anchor = target if target is not None else api.getFocusObject()
		root = _documentOrWindowOf(anchor)
		note = "the web document" if _safeGet(root, "role") == controlTypes.Role.DOCUMENT else "the window"
		return Recording(root, note, _focusPathKeys(anchor))

	def begin(self, recording: Recording, useTracer: bool = True) -> Recording:
		"""Take the first snapshot and start collecting events. Must run on the main thread.

		:param useTracer: False when the caller traces events itself.
		"""
		recording.before = takeSnapshot(recording.root, recording.focusPath)
		if useTracer:
			recording.eventStartId = self._tracer.beginRecording()
			recording.extra["useTracer"] = True
		recording.startedAt = time.monotonic()
		return recording

	def finish(self, recording: Recording) -> dict[str, Any]:
		"""Take the second snapshot and return what the server needs to compare. Must run on the main thread."""
		try:
			recording.root.invalidateCache()
		except Exception:  # noqa: BLE001
			log.debugWarning("Could not invalidate the recorded root", exc_info=True)
		before = recording.before or {"nodeCount": 0, "truncated": None, "tree": {}}
		if isObjectAlive(recording.root):
			# Read no more than the first snapshot did, so both cover the same part of the tree.
			maxNodes = before["nodeCount"] if before.get("truncated") else SNAPSHOT_MAX_NODES
			after = takeSnapshot(recording.root, recording.focusPath, max(maxNodes, 1))
			after["alive"] = True
		else:
			after = {"nodeCount": 0, "truncated": None, "alive": False, "tree": {}}
		result: dict[str, Any] = {
			"root": rootLabel(recording.root),
			"rootNote": recording.rootNote,
			"seconds": round(time.monotonic() - recording.startedAt, 1),
			"before": before,
			"after": after,
		}
		if recording.extra.get("webPageUnavailable"):
			result["webPageUnavailable"] = True
		if recording.extra.get("useTracer"):
			self._tracer.endRecording()
			result.update(self._events(recording.eventStartId))
		return result

	def cancel(self, recording: Recording) -> None:
		if recording.extra.pop("useTracer", False):
			self._tracer.endRecording()

	def _events(self, startId: int) -> dict[str, Any]:
		entries = self._readEvents(startId)
		result: dict[str, Any] = {}
		if entries and entries[0]["id"] > startId + 1:
			# The trace log is a ring buffer: the oldest events of a long recording may be gone.
			result["eventsDropped"] = entries[0]["id"] - startId - 1
		if len(entries) > MAX_RECORDED_EVENTS:
			half = MAX_RECORDED_EVENTS // 2
			result["eventsOmitted"] = len(entries) - MAX_RECORDED_EVENTS
			entries = entries[:half] + entries[-half:]
		result["events"] = entries
		if self._tracer.isActive and self._tracer.hasFilter:
			result["eventsFiltered"] = True
		return result

	def onMain(self, function: Callable[..., Any], *args: Any) -> Any:
		return wxCallOnMain(function, *args)
