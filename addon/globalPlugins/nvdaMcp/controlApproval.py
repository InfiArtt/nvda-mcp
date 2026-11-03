# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Whether the user has allowed MCP clients to press keys, and how long a control action may wait.

This module does not import NVDA, so it can be unit tested on its own.
"""

import sys
import types

# How long the MCP server waits for an answer to a control action (PRESS_KEYS_TIMEOUT_SECONDS there).
CLIENT_WAIT_SECONDS = 120.0
# Time kept for the reply to reach the client after the action has finished.
REPLY_MARGIN_SECONDS = 10.0
# Asking the user is pointless with less time than this left to answer.
MIN_ANSWER_SECONDS = 15.0

# The user's answer lasts until NVDA restarts, as the question says. Reloading plugins imports this
# add-on's modules again, so the answer is kept in a module of its own, registered under a name
# outside the globalPlugins package: NVDA only removes globalPlugins modules from sys.modules then.
_STATE_MODULE = "_nvdaMcpControlApproval"


def _state() -> types.ModuleType:
	state = sys.modules.get(_STATE_MODULE)
	if state is None:
		state = types.ModuleType(_STATE_MODULE, "NVDA MCP's control approval, kept across plugin reloads.")
		state.isApproved = False
		state.wasRevoked = False
		sys.modules[_STATE_MODULE] = state
	return state


def isApproved() -> bool:
	"""Whether the user allowed MCP clients to press keys since NVDA started."""
	return _state().isApproved


def wasRevoked() -> bool:
	"""Whether the user took the permission back, so they must be asked again even if confirmation is off."""
	return _state().wasRevoked


def approve() -> None:
	state = _state()
	state.isApproved = True
	state.wasRevoked = False


def revoke() -> None:
	state = _state()
	state.isApproved = False
	state.wasRevoked = True


def startDeadline(requestTime: float, listenSeconds: float) -> float:
	"""The latest time an action may start, so the client is still waiting when it ends.

	Otherwise an answer given after the client stopped waiting, or a long wait behind another action,
	would press keys that nobody expects any more.
	:param requestTime: When the request arrived, from time.monotonic().
	:param listenSeconds: How long the action listens to NVDA after it is performed.
	"""
	return requestTime + CLIENT_WAIT_SECONDS - REPLY_MARGIN_SECONDS - listenSeconds
