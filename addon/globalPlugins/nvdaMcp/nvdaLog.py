# NVDA MCP add-on
# Copyright (C) 2026 audiogaming23
# This file is covered by the GNU General Public License.

"""Reads and filters NVDA's log file (the one the Log Viewer shows).

This module does not import NVDA, so it can be unit tested on its own.
"""

import os
import re
from typing import Any

# NVDA's levels, from logHandler, lowest first.
LEVELS = {
	"DEBUG_UNREDACTED": 5,
	"DEBUG": 10,
	"IO": 12,
	"DEBUGWARNING": 15,
	"INFO": 20,
	"WARNING": 30,
	"ERROR": 40,
	"CRITICAL": 50,
}

# The first line of every entry, for example:
# ERROR - external:globalPlugins.foo.GlobalPlugin.bar (23:43:26.884) - MainThread (16068):
_HEADER = re.compile(
	r"^(?P<level>" + "|".join(LEVELS) + r") - (?P<source>.+?) \((?P<time>\d\d:\d\d:\d\d\.\d+)\)"
	r"(?: - (?P<thread>.+?))?:$"
)

MAX_READ_BYTES = 2 * 1024 * 1024


def parseLog(text: str) -> list[dict[str, Any]]:
	"""Split log text into entries of level, source, time, thread and message.

	Lines before the first header, such as the tail of an entry cut off by reading
	from the middle of the file, are dropped.
	"""
	entries: list[dict[str, Any]] = []
	current: dict[str, Any] | None = None
	lines: list[str] = []
	for line in text.splitlines():
		match = _HEADER.match(line)
		if match is None:
			if current is not None:
				lines.append(line)
			continue
		if current is not None:
			current["message"] = "\n".join(lines).rstrip()
			entries.append(current)
		current = {key: value for key, value in match.groupdict().items() if value is not None}
		lines = []
	if current is not None:
		current["message"] = "\n".join(lines).rstrip()
		entries.append(current)
	return entries


def filterEntries(
	entries: list[dict[str, Any]],
	minLevel: str = "WARNING",
	contains: str | None = None,
	includeIo: bool = False,
	limit: int = 50,
) -> list[dict[str, Any]]:
	"""The newest ``limit`` entries at or above ``minLevel`` whose source or message contains ``contains``.

	IO entries record keys pressed and text spoken, so they are left out unless ``includeIo`` is set,
	even when ``minLevel`` is low enough to include them.
	"""
	threshold = LEVELS[minLevel]
	needle = contains.casefold() if contains else None
	matches = [
		entry
		for entry in entries
		if LEVELS[entry["level"]] >= threshold
		and (includeIo or entry["level"] != "IO")
		and (needle is None or needle in entry["source"].casefold() or needle in entry["message"].casefold())
	]
	return matches[-limit:]


def readTail(path: str, maxBytes: int = MAX_READ_BYTES) -> tuple[str, bool]:
	"""The end of a log file, decoded leniently.

	:return: The text and whether the start of the file was left out.
	"""
	with open(path, "rb") as file:
		file.seek(0, os.SEEK_END)
		size = file.tell()
		file.seek(max(0, size - maxBytes))
		data = file.read()
	return data.decode("utf-8", errors="replace"), size > maxBytes
