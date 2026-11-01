# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""A file that records every action an MCP client takes, so the user can check what was done.

Each line is a JSON object with the time, the action, the foreground window and its details.
This module does not import NVDA, so it can be unit tested on its own.
"""

import json
import os
import threading
import time
from typing import Any

MAX_LOG_BYTES = 1024 * 1024


class ActionLog:
	def __init__(self, path: str, maxBytes: int = MAX_LOG_BYTES) -> None:
		"""
		:param path: The log file. When it grows past ``maxBytes`` it is renamed to ``<path>.1``,
			replacing the previous one, and a new file is started.
		"""
		self.path = path
		self._maxBytes = maxBytes
		self._lock = threading.Lock()

	def record(self, action: str, window: str | None, **details: Any) -> None:
		entry = {
			"time": time.strftime("%Y-%m-%d %H:%M:%S"),
			"action": action,
			"window": window,
			**details,
		}
		line = json.dumps(entry, ensure_ascii=False) + "\n"
		with self._lock:
			os.makedirs(os.path.dirname(self.path), exist_ok=True)
			try:
				if os.path.getsize(self.path) + len(line.encode("utf-8")) > self._maxBytes:
					os.replace(self.path, self.path + ".1")
			except FileNotFoundError:
				pass
			with open(self.path, "a", encoding="utf-8") as file:
				file.write(line)

	def tail(self, count: int) -> list[dict[str, Any]]:
		"""The newest ``count`` entries from the current file, oldest first."""
		with self._lock:
			try:
				with open(self.path, encoding="utf-8") as file:
					lines = file.readlines()[-count:]
			except FileNotFoundError:
				return []
		entries = []
		for line in lines:
			try:
				entries.append(json.loads(line))
			except ValueError:
				continue
		return entries
