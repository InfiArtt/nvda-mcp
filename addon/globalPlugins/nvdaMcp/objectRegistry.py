# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Ids for the controls clients find, so they can act on them in later calls.

This module does not import NVDA, so it can be unit tested on its own.
"""

from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class ObjectRegistry(Generic[T]):
	"""Gives each object found a new id that stays valid through later searches.

	Ids count up from 1 and are never reused, so an id from an earlier search
	cannot silently point at a different control. Only the newest ``maxObjects`` are kept.
	"""

	def __init__(self, maxObjects: int) -> None:
		self._maxObjects = maxObjects
		self._objects: OrderedDict[int, T] = OrderedDict()
		self._nextId = 1
		self._lastIds: list[int] = []

	def add(self, objects: list[T]) -> list[int]:
		"""Register the results of one search and return their ids, in the same order."""
		ids = []
		for obj in objects:
			self._objects[self._nextId] = obj
			ids.append(self._nextId)
			self._nextId += 1
		while len(self._objects) > self._maxObjects:
			self._objects.popitem(last=False)
		self._lastIds = ids
		return ids

	def get(self, objectId: int) -> T | None:
		"""The object with this id, or None if it was never given out or has been forgotten."""
		return self._objects.get(objectId)

	def isForgotten(self, objectId: int) -> bool:
		"""Whether this id was given out once, but has since made way for newer objects."""
		return 1 <= objectId < self._nextId and objectId not in self._objects

	@property
	def last(self) -> list[tuple[int, T]]:
		"""The ids and objects of the most recent search that are still kept."""
		return [
			(objectId, self._objects[objectId]) for objectId in self._lastIds if objectId in self._objects
		]
