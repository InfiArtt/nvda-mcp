# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Bridge methods for developers: NVDA's log, event tracing, beeps and braille output,
developer info, commands and their keys, speech previews and settings.

Functions in this module touch NVDAObjects and NVDA's internals,
so most of them run on NVDA's main thread through :meth:`NvdaActions.onMain`.
"""

import os
import re
import time
from typing import Any

import api
import config
import controlTypes
import eventHandler
import globalCommands
import globalPluginHandler
import globalVars
import inputCore
import nvwave
import scriptHandler
import speech
import tones
import wx
from braille.extensions import pre_writeCells
from gui.guiHelper import wxCallOnMain
from keyboardHandler import KeyboardInputGesture
from NVDAObjects import NVDAObject
from speech.extensions import speechCanceled

from . import nvdaLog
from .bridge import BridgeError, Handler
from .nvdaActions import _LAYOUT_ROLES, NvdaActions, _appNameOf, _safeGet, describeObject
from .speechLog import SpeechLog, sequenceToText
from .traceLog import TraceLog, attributeNearbySpeech

MAX_OUTPUT_ENTRIES = 1000
MAX_TRACE_ENTRIES = 2000
# Tracing wraps every event NVDA handles, so it switches itself off if a client forgets to stop it.
MAX_TRACE_SECONDS = 10 * 60
MAX_TRACE_WAIT_SECONDS = 60.0
# Speech this close to an event, but not spoken while handling it, is reported as probably caused by it.
# Browsers' live regions can be spoken just before their event arrives.
NEARBY_SPEECH_AFTER_SECONDS = 1.5
NEARBY_SPEECH_BEFORE_SECONDS = 0.5
MAX_DETAIL_CHARS = 200
MAX_PREVIEW_OBJECTS = 100
MAX_SCRIPTS = 300
OUTPUT_KINDS = ("beep", "sound", "braille", "speechCanceled")
# Settings whose names look like they hold secrets, such as an add-on's API key, are never sent.
_SECRET_SETTING = re.compile(r"key|token|password|secret|credential", re.IGNORECASE)


def _short(value: Any) -> str:
	text = value if isinstance(value, str) else repr(value)
	return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS] + "…"


def _roleName(obj: NVDAObject) -> str | None:
	role = _safeGet(obj, "role")
	return role.displayString if role is not None else None


def _gestureText(identifier: str) -> str:
	"""A gesture as the Input Gestures dialog shows it, such as "NVDA+alt+minus (keyboard, all layouts)"."""
	try:
		source, text = inputCore.getDisplayTextForGestureIdentifier(identifier)
	except LookupError:
		return identifier
	return f"{text} ({source})"


def _isPreviewable(obj: NVDAObject) -> bool:
	"""Focusable controls, leaving out the windows and panes that toolkits such as wxWidgets wrap them in."""
	return (
		controlTypes.State.FOCUSABLE in (_safeGet(obj, "states") or set())
		and _safeGet(obj, "role") not in _LAYOUT_ROLES
	)


def _jsonSafe(value: Any) -> Any:
	if isinstance(value, dict) or hasattr(value, "dict"):
		items = value.items() if isinstance(value, dict) else value.dict().items()
		return {
			str(key): "(hidden)" if _SECRET_SETTING.search(str(key)) else _jsonSafe(item)
			for key, item in items
		}
	if isinstance(value, (list, tuple)):
		return [_jsonSafe(item) for item in value]
	if value is None or isinstance(value, (bool, int, float, str)):
		return value
	return str(value)


class EventTracer:
	"""Records the events NVDA handles, and what NVDA said while handling each one.

	NVDA has no extension point for events, so this wraps ``eventHandler.executeEvent``
	while tracing is on. The wrapper stays in place once installed, doing nothing while tracing is off,
	in case another add-on has wrapped it on top of this one.
	"""

	def __init__(self, speechLog: SpeechLog) -> None:
		self.log = TraceLog(MAX_TRACE_ENTRIES)
		self._speechLog = speechLog
		self.isActive = False
		self._eventNames: set[str] | None = None
		self._appName: str | None = None
		self._stopAt = 0.0
		self._original = None
		self._wrapper = None

	def start(self, eventNames: list[str], appName: str | None) -> None:
		"""Start or restart tracing. Must be called on the main thread."""
		self._eventNames = set(eventNames) or None
		self._appName = appName.casefold() if appName else None
		self._stopAt = time.monotonic() + MAX_TRACE_SECONDS
		self._install()
		self.isActive = True

	def stop(self) -> None:
		self.isActive = False

	def uninstall(self) -> None:
		"""Stop tracing and remove the wrapper, unless another add-on has wrapped it since."""
		self.isActive = False
		if self._wrapper is not None and eventHandler.executeEvent is self._wrapper:
			eventHandler.executeEvent = self._original
			self._wrapper = None
			self._original = None

	def _install(self) -> None:
		if self._wrapper is not None:
			return
		original = eventHandler.executeEvent

		def executeEvent(eventName: str, obj: NVDAObject, **kwargs: Any) -> Any:
			if not self.isActive:
				return original(eventName, obj, **kwargs)
			return self._traced(original, eventName, obj, kwargs)

		self._original = original
		self._wrapper = executeEvent
		eventHandler.executeEvent = executeEvent

	def _traced(self, original: Any, eventName: str, obj: NVDAObject, kwargs: dict[str, Any]) -> Any:
		if time.monotonic() > self._stopAt:
			self.isActive = False
			return original(eventName, obj, **kwargs)
		if self._eventNames is not None and eventName not in self._eventNames:
			return original(eventName, obj, **kwargs)
		appName = _appNameOf(obj)
		if self._appName is not None and (appName or "").casefold() != self._appName:
			return original(eventName, obj, **kwargs)
		speechBefore = self._speechLog.lastId
		try:
			return original(eventName, obj, **kwargs)
		finally:
			entry: dict[str, Any] = {
				"event": eventName,
				"name": _safeGet(obj, "name"),
				"role": _roleName(obj),
				"app": appName,
				"windowClassName": _safeGet(obj, "windowClassName"),
			}
			if kwargs:
				entry["details"] = {key: _short(value) for key, value in kwargs.items()}
			spokenEntries = self._speechLog.since(speechBefore)
			spoken = " / ".join(item.text for item in spokenEntries)
			if spoken:
				entry["spoken"] = spoken
			entry["speechBeforeId"] = speechBefore
			entry["speechAfterId"] = spokenEntries[-1].id if spokenEntries else speechBefore
			self.log.add("event", **{key: value for key, value in entry.items() if value not in (None, "")})


class OutputRecorder:
	"""Records beeps, sounds, braille and speech being cut off, which the speech log does not show."""

	def __init__(self) -> None:
		self.log = TraceLog(MAX_OUTPUT_ENTRIES)

	def register(self) -> None:
		tones.decide_beep.register(self._onBeep)
		nvwave.decide_playWaveFile.register(self._onWaveFile)
		pre_writeCells.register(self._onWriteCells)
		speechCanceled.register(self._onSpeechCanceled)

	def unregister(self) -> None:
		tones.decide_beep.unregister(self._onBeep)
		nvwave.decide_playWaveFile.unregister(self._onWaveFile)
		pre_writeCells.unregister(self._onWriteCells)
		speechCanceled.unregister(self._onSpeechCanceled)

	def _onBeep(self, hz: float = 0, length: int = 0, **kwargs: Any) -> bool:
		self.log.add("beep", hz=round(hz), lengthMs=length)
		return True

	def _onWaveFile(self, fileName: str = "", **kwargs: Any) -> bool:
		self.log.add("sound", file=os.path.basename(fileName))
		return True

	def _onWriteCells(self, rawText: str = "", **kwargs: Any) -> None:
		# The braille cursor blinking rewrites the same cells; record each text once.
		previousBraille = self.log.since(0, 1, kinds=("braille",))
		if previousBraille and previousBraille[0]["text"] == rawText:
			return
		self.log.add("braille", text=rawText)

	def _onSpeechCanceled(self) -> None:
		self.log.add("speechCanceled")


class DevTools:
	def __init__(self, speechLog: SpeechLog, actions: NvdaActions) -> None:
		self._speechLog = speechLog
		self._actions = actions
		self.tracer = EventTracer(speechLog)
		self.output = OutputRecorder()

	def register(self) -> None:
		self.output.register()

	def unregister(self) -> None:
		self.output.unregister()
		self.tracer.uninstall()

	def handlers(self) -> dict[str, Handler]:
		onMain = self._actions.onMain
		return {
			"getLog": self._getLog,
			"traceEvents": self._traceEvents,
			"getOutput": self._getOutput,
			"getDevInfo": onMain(self._getDevInfo),
			"listScripts": onMain(self._listScripts),
			"runScript": self._runScript,
			"reloadPlugins": self._reloadPlugins,
			"previewSpeech": onMain(self._previewSpeech),
			"getSettings": onMain(self._getSettings),
		}

	def _getLog(self, params: dict[str, Any]) -> dict[str, Any]:
		minLevel = str(params.get("minLevel", "WARNING")).upper()
		if minLevel not in nvdaLog.LEVELS:
			raise BridgeError("badParams", f"minLevel must be one of {', '.join(nvdaLog.LEVELS)}.")
		path = globalVars.appArgs.logFileName
		if not path or not os.path.exists(path):
			raise BridgeError("noLog", "NVDA is not writing a log file. Logging may be turned off.")
		text, isCut = nvdaLog.readTail(path)
		entries = nvdaLog.filterEntries(
			nvdaLog.parseLog(text),
			minLevel=minLevel,
			contains=params.get("contains") or None,
			includeIo=bool(params.get("includeIo")),
			limit=min(int(params.get("limit", 30)), 200),
		)
		return {
			"path": path,
			"loggingLevel": config.conf["general"]["loggingLevel"],
			"startOmitted": isCut,
			"entries": entries,
		}

	def _traceEvents(self, params: dict[str, Any]) -> dict[str, Any]:
		action = params.get("action", "read")
		if action == "start":
			eventNames = params.get("events") or []
			if not isinstance(eventNames, list) or not all(isinstance(name, str) for name in eventNames):
				raise BridgeError("badParams", 'events must be a list of event names, such as ["gainFocus"].')
			self._actions.ensureUnlocked()
			startId = self.tracer.log.lastId
			wxCallOnMain(self.tracer.start, eventNames, params.get("app") or None)
			return {"tracing": True, "afterId": startId, "stopsAfterSeconds": MAX_TRACE_SECONDS}
		if action not in ("read", "stop"):
			raise BridgeError("badParams", "action must be start, read or stop.")
		waitSeconds = min(float(params.get("waitMs", 0)) / 1000, MAX_TRACE_WAIT_SECONDS)
		if waitSeconds > 0 and self.tracer.isActive:
			time.sleep(waitSeconds)
		if action == "stop":
			self.tracer.stop()
		entries = self.tracer.log.since(
			int(params.get("afterId", 0)), min(int(params.get("limit", 100)), 500)
		)
		if entries:
			firstSpeechId = min(entry.get("speechBeforeId", 0) for entry in entries)
			utterances = [item.toDict() for item in self._speechLog.since(firstSpeechId)]
			entries = attributeNearbySpeech(
				entries, utterances, NEARBY_SPEECH_AFTER_SECONDS, NEARBY_SPEECH_BEFORE_SECONDS
			)
			for entry in entries:
				entry.pop("speechBeforeId", None)
				entry.pop("speechAfterId", None)
		return {"tracing": self.tracer.isActive, "lastId": self.tracer.log.lastId, "entries": entries}

	def _getOutput(self, params: dict[str, Any]) -> dict[str, Any]:
		kinds = params.get("kinds") or None
		if kinds is not None and (
			not isinstance(kinds, list) or any(kind not in OUTPUT_KINDS for kind in kinds)
		):
			raise BridgeError("badParams", f"kinds may only contain {', '.join(OUTPUT_KINDS)}.")
		entries = self.output.log.since(
			int(params.get("afterId", 0)), min(int(params.get("limit", 50)), 500), kinds
		)
		return {"lastId": self.output.log.lastId, "entries": entries}

	def _target(self, params: dict[str, Any]) -> NVDAObject:
		if params.get("id") is not None:
			return self._actions.foundObjectOnMain(params["id"])
		target = params.get("target", "focus")
		if target == "focus":
			return api.getFocusObject()
		if target == "navigator":
			return api.getNavigatorObject()
		raise BridgeError("badParams", "target must be focus or navigator, or pass an id from findObjects.")

	def _getDevInfo(self, params: dict[str, Any]) -> dict[str, Any]:
		obj = self._target(params)
		appModule = _safeGet(obj, "appModule")
		treeInterceptor = _safeGet(obj, "treeInterceptor")
		result = {
			"object": list(_safeGet(obj, "devInfo") or []),
			"classes": [f"{cls.__module__}.{cls.__qualname__}" for cls in type(obj).__mro__],
			"appModule": list(_safeGet(appModule, "devInfo") or []) if appModule else [],
		}
		if treeInterceptor is not None:
			result["treeInterceptor"] = (
				f"{type(treeInterceptor).__module__}.{type(treeInterceptor).__qualname__}"
			)
			result["documentMode"] = "focus" if treeInterceptor.passThrough else "browse"
		return result

	def _listScripts(self, params: dict[str, Any]) -> dict[str, Any]:
		key = params.get("key")
		if key:
			return self._scriptForKey(key)
		needle = (params.get("contains") or "").casefold()
		maxResults = min(int(params.get("maxResults", 50)), MAX_SCRIPTS)
		scripts = []
		truncated = None
		for category, byName in inputCore.manager.getAllGestureMappings().items():
			for displayName, info in byName.items():
				gestures = [_gestureText(identifier) for identifier in getattr(info, "gestures", [])]
				item = {
					"category": category,
					"description": displayName,
					"script": getattr(info, "scriptName", None),
					"class": f"{info.moduleName}.{info.className}" if hasattr(info, "moduleName") else None,
					"gestures": gestures,
				}
				haystack = " ".join([category, displayName, item["script"] or "", *gestures]).casefold()
				if needle and needle not in haystack:
					continue
				if len(scripts) >= maxResults:
					truncated = f"stopped at {maxResults} results"
					break
				scripts.append({name: value for name, value in item.items() if value not in (None, [])})
			if truncated:
				break
		return {"scripts": scripts, "truncated": truncated}

	@staticmethod
	def _scriptForKey(key: str) -> dict[str, Any]:
		try:
			gesture = KeyboardInputGesture.fromName(key)
		except (LookupError, ValueError):
			raise BridgeError(
				"badParams", f"Unknown key {key!r}. Use NVDA key names such as NVDA+f1 or control+home."
			)
		script = scriptHandler.findScript(gesture)
		if script is None:
			return {"key": key, "script": None, "passesThrough": True}
		owner = getattr(script, "__self__", None)
		return {
			"key": key,
			"script": scriptHandler.getScriptName(script),
			"description": getattr(script, "__doc__", None),
			"category": getattr(script, "category", None),
			"class": f"{type(owner).__module__}.{type(owner).__qualname__}" if owner is not None else None,
			"passesThrough": False,
		}

	def _findScript(self, name: str, className: str | None) -> Any:
		"""Look for script_<name> where NVDA would: global plugins, the app module, the document,
		the focus and its ancestors, then NVDA's global commands. Must run on the main thread."""
		focus = api.getFocusObject()
		candidates: list[Any] = list(globalPluginHandler.runningPlugins)
		candidates.append(_safeGet(focus, "appModule"))
		candidates.append(_safeGet(focus, "treeInterceptor"))
		candidates.append(focus)
		candidates.extend(reversed(api.getFocusAncestors()))
		candidates.append(globalCommands.commands)
		for candidate in candidates:
			if candidate is None:
				continue
			if className and not any(cls.__name__ == className for cls in type(candidate).__mro__):
				continue
			script = getattr(candidate, f"script_{name}", None)
			if script is not None:
				return script
		raise BridgeError(
			"noSuchScript",
			f"No command named {name!r} applies here. Use listScripts to see the commands available.",
		)

	def _runScript(self, params: dict[str, Any]) -> dict[str, Any]:
		self._actions.ensureUnlocked()
		name = str(params.get("name") or "").removeprefix("script_")
		if not name:
			raise BridgeError(
				"badParams", "name must be a command name from listScripts, such as reportCurrentFocus."
			)
		script = wxCallOnMain(self._findScript, name, params.get("className") or None)

		def perform() -> None:
			# There is no key press behind this, so commands that pass their key on to the application cannot.
			wxCallOnMain(scriptHandler.executeScript, script, None)

		return self._actions.runControlled("runScript", {"script": name}, perform, params)

	def _reloadPlugins(self, params: dict[str, Any]) -> dict[str, Any]:
		"""Like NVDA+control+F3. This add-on is reloaded too, so its bridge restarts after replying."""
		self._actions.ensureUnlocked()

		def perform() -> None:
			wxCallOnMain(wx.CallLater, 300, globalCommands.commands.script_reloadPlugins, None)

		result = self._actions.runControlled(
			"reloadPlugins",
			{},
			perform,
			{**params, "settleMs": 100, "timeoutMs": 200},
			targetApp="nvda",
			checkApp=False,
		)
		result["reloading"] = True
		return result

	def _previewSpeech(self, params: dict[str, Any]) -> dict[str, Any]:
		target = params.get("target", "focus")
		truncated = None
		if params.get("id") is not None:
			objects = [(params["id"], self._actions.foundObjectOnMain(params["id"]))]
		elif target == "found":
			objects = list(enumerate(self._actions.foundObjects, 1))[:MAX_PREVIEW_OBJECTS]
		elif target == "window":
			maxResults = min(int(params.get("maxResults", 50)), MAX_PREVIEW_OBJECTS)
			matches, truncated = self._actions.searchForeground(
				None,
				None,
				maxResults,
				_isPreviewable,
			)
			objects = list(enumerate(matches, 1))
		elif target in ("focus", "navigator"):
			objects = [(None, self._target({"target": target}))]
		else:
			raise BridgeError("badParams", "target must be focus, navigator, found or window.")
		previews = []
		for objectId, obj in objects:
			preview: dict[str, Any] = {"id": objectId}
			try:
				sequence = speech.getObjectSpeech(obj, reason=controlTypes.OutputReason.FOCUS)
				preview["spoken"] = sequenceToText(sequence)
			except Exception as error:  # noqa: BLE001 - one broken control must not hide the others
				preview["error"] = f"{type(error).__name__}: {error}"
			preview.update(describeObject(obj))
			previews.append({key: value for key, value in preview.items() if value is not None})
		return {"previews": previews, "truncated": truncated}

	def _getSettings(self, params: dict[str, Any]) -> dict[str, Any]:
		profile = config.conf.profiles[-1].name if config.conf.profiles else None
		section = params.get("section")
		if not section:
			return {"profile": profile, "sections": sorted(config.conf.spec.keys())}
		node: Any = config.conf
		for part in str(section).split("."):
			if _SECRET_SETTING.search(part):
				raise BridgeError("badParams", "Settings that may hold secrets are not shared.")
			try:
				node = node[part]
			except KeyError:
				raise BridgeError(
					"badParams", f"No setting {section!r}. Leave section out to list the sections."
				)
		return {"profile": profile, "section": section, "values": _jsonSafe(node)}
