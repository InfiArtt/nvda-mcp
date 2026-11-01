# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""A thread-safe ring buffer of what NVDA has spoken.

This module does not import NVDA, so it can be unit tested on its own.
"""

import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechEntry:
	"""One utterance captured from NVDA's speech pipeline."""

	id: int
	"""Monotonically increasing identifier, starting at 1."""
	timestamp: float
	"""Wall clock time (seconds since the epoch) when the utterance was queued."""
	text: str

	def toDict(self) -> dict[str, int | float | str]:
		return {"id": self.id, "timestamp": self.timestamp, "text": self.text}


def sequenceToText(speechSequence: Iterable[object]) -> str:
	"""Join the text items of a speech sequence, dropping speech commands.

	:param speechSequence: Items as passed to ``speech.extensions.pre_speech``.
	:return: The spoken text, with whitespace normalised.
	"""
	parts = [item for item in speechSequence if isinstance(item, str)]
	return " ".join(" ".join(parts).split())


class SpeechLog:
	"""Records utterances and lets other threads wait for new ones."""

	def __init__(self, maxEntries: int) -> None:
		"""
		:param maxEntries: How many utterances to keep before discarding the oldest.
		"""
		self._entries: deque[SpeechEntry] = deque(maxlen=maxEntries)
		self._nextId = 1
		self._condition = threading.Condition()

	@property
	def lastId(self) -> int:
		"""The id of the newest entry, or 0 when nothing has been spoken yet."""
		with self._condition:
			return self._nextId - 1

	def resize(self, maxEntries: int) -> None:
		with self._condition:
			self._entries = deque(self._entries, maxlen=maxEntries)

	def add(self, text: str) -> None:
		"""Record an utterance. Empty text is ignored."""
		if not text:
			return
		with self._condition:
			self._entries.append(SpeechEntry(self._nextId, time.time(), text))
			self._nextId += 1
			self._condition.notify_all()

	def since(self, afterId: int, limit: int | None = None) -> list[SpeechEntry]:
		"""Entries newer than ``afterId``, oldest first.

		:param limit: When given, only the newest ``limit`` matching entries are returned.
		"""
		with self._condition:
			entries = [entry for entry in self._entries if entry.id > afterId]
		if limit is not None:
			entries = entries[-limit:]
		return entries

	def waitFor(
		self, afterId: int, predicate: Callable[[str], bool], timeoutSeconds: float
	) -> SpeechEntry | None:
		"""Wait for the first utterance after ``afterId`` whose text satisfies ``predicate``.

		Utterances already recorded after ``afterId`` count, so nothing said in between is missed.
		:return: The matching entry, or None if none arrived within ``timeoutSeconds``.
		"""
		deadline = time.monotonic() + timeoutSeconds
		checkedId = afterId
		with self._condition:
			while True:
				for entry in self._entries:
					if entry.id > checkedId:
						if predicate(entry.text):
							return entry
						checkedId = entry.id
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					return None
				self._condition.wait(remaining)

	def waitForQuiet(self, afterId: int, settleSeconds: float, timeoutSeconds: float) -> list[SpeechEntry]:
		"""Wait until speech after ``afterId`` has started and then stopped.

		Returns once no new utterance has arrived for ``settleSeconds``,
		or when ``timeoutSeconds`` has elapsed in total.
		If nothing is spoken at all, this returns an empty list after ``timeoutSeconds``.
		"""
		deadline = time.monotonic() + timeoutSeconds
		with self._condition:
			seenId = afterId
			quietDeadline: float | None = None
			while True:
				newestId = self._nextId - 1
				now = time.monotonic()
				if newestId > seenId:
					seenId = newestId
					quietDeadline = now + settleSeconds
				if now >= deadline or (quietDeadline is not None and now >= quietDeadline):
					break
				wakeAt = deadline if quietDeadline is None else min(deadline, quietDeadline)
				self._condition.wait(wakeAt - now)
		return self.since(afterId)
