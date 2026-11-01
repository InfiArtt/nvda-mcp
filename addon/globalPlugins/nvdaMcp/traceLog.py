# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""A thread-safe ring buffer of things NVDA did besides speaking: events, beeps, sounds and braille.

This module does not import NVDA, so it can be unit tested on its own.
"""

import threading
import time
from collections import deque
from collections.abc import Iterable
from typing import Any


class TraceLog:
	"""Records entries of different kinds, each a dict with an id, a timestamp and a kind."""

	def __init__(self, maxEntries: int) -> None:
		self._entries: deque[dict[str, Any]] = deque(maxlen=maxEntries)
		self._nextId = 1
		self._lock = threading.Lock()

	@property
	def lastId(self) -> int:
		"""The id of the newest entry, or 0 when nothing has been recorded yet."""
		with self._lock:
			return self._nextId - 1

	def add(self, kind: str, **fields: Any) -> int:
		"""Record an entry and return its id."""
		with self._lock:
			entryId = self._nextId
			self._entries.append({"id": entryId, "timestamp": time.time(), "kind": kind, **fields})
			self._nextId += 1
			return entryId

	def since(
		self, afterId: int, limit: int | None = None, kinds: Iterable[str] | None = None
	) -> list[dict[str, Any]]:
		"""Entries newer than ``afterId``, oldest first.

		:param limit: When given, only the newest ``limit`` matching entries are returned.
		:param kinds: When given, only entries of these kinds are returned.
		"""
		kindSet = set(kinds) if kinds else None
		with self._lock:
			entries = [
				entry
				for entry in self._entries
				if entry["id"] > afterId and (kindSet is None or entry["kind"] in kindSet)
			]
		if limit is not None:
			entries = entries[-limit:]
		return entries


# Events NVDA often speaks outside their own handling, just before or after it.
LIVE_EVENTS = frozenset({"liveRegionChange", "UIA_notification", "alert"})


def attributeNearbySpeech(
	events: list[dict[str, Any]],
	utterances: list[dict[str, Any]],
	afterSeconds: float,
	beforeSeconds: float,
) -> list[dict[str, Any]]:
	"""Add ``spokenNearby`` to events: what NVDA said around an event, but not while handling it.

	NVDA speaks some events outside their handling: browsers' live regions are spoken through
	other notifications, sometimes just before the live region event arrives, sometimes after it.
	Each such utterance goes to the nearest live region, notification or alert event
	from ``beforeSeconds`` after it to ``afterSeconds`` before it; failing that,
	to the latest event up to ``afterSeconds`` before it.

	:param events: Event entries with ``event``, ``timestamp`` (when handling ended),
		``speechBeforeId`` and ``speechAfterId``.
	:param utterances: Speech entries with ``id``, ``timestamp`` and ``text``, oldest first.
	:return: Copies of the events, in the same order.
	"""
	result = [dict(event) for event in events]
	ordered = sorted(
		(event for event in result if "speechAfterId" in event), key=lambda event: event["timestamp"]
	)
	spokenDuringEvents = [(event.get("speechBeforeId", 0), event["speechAfterId"]) for event in ordered]
	for utterance in utterances:
		if any(before < utterance["id"] <= after for before, after in spokenDuringEvents):
			continue
		liveEvents = [
			event
			for event in ordered
			if event.get("event") in LIVE_EVENTS
			and -beforeSeconds <= utterance["timestamp"] - event["timestamp"] <= afterSeconds
		]
		if liveEvents:
			chosen = min(liveEvents, key=lambda event: abs(utterance["timestamp"] - event["timestamp"]))
		else:
			earlier = [
				event
				for event in ordered
				if 0 <= utterance["timestamp"] - event["timestamp"] <= afterSeconds
				and utterance["id"] > event["speechAfterId"]
			]
			if not earlier:
				continue
			chosen = earlier[-1]
		chosen.setdefault("spokenNearby", []).append(utterance["text"])
	for event in result:
		if "spokenNearby" in event:
			event["spokenNearby"] = " / ".join(event["spokenNearby"])
	return result
