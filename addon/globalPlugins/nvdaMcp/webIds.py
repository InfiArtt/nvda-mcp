# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Identifiers that connect a web page's accessible objects with its HTML elements.

This module does not import NVDA, so it can be unit tested on its own.
"""

from collections.abc import Sequence

# Chromium builds its runtime ids with UiaAppendRuntimeId (3), two ids for the frame,
# and Blink's id of the DOM node, which the Chrome DevTools Protocol calls backendNodeId.
_UIA_APPEND_RUNTIME_ID = 3


def domNodeIdFromRuntimeId(runtimeId: Sequence[int] | None) -> int | None:
	"""Blink's DOM node id from a Chromium accessible object's runtime id, such as [3, 7, 4, 3921]."""
	if not runtimeId or len(runtimeId) != 4 or runtimeId[0] != _UIA_APPEND_RUNTIME_ID:
		return None
	nodeId = runtimeId[3]
	return nodeId if isinstance(nodeId, int) and nodeId > 0 else None
