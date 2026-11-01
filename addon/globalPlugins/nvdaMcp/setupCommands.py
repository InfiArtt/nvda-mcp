# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""What to give each MCP client so it starts the nvda-mcp server.

The server is pinned to this add-on's version, since the two must match.
This module does not import NVDA, so it can be unit tested on its own.
"""

import json

PACKAGE = "nvda-mcp"
SERVER_NAME = "nvda"
# Clients set up with a command in a terminal, then the one set up with a JSON settings file.
CLIENTS = ("claudeCode", "codex", "json")


def serverPackage(addonVersion: str) -> str:
	return f"{PACKAGE}=={addonVersion}"


def setupText(client: str, addonVersion: str) -> str:
	"""The command, or the JSON settings, that make ``client`` run the server matching ``addonVersion``."""
	package = serverPackage(addonVersion)
	if client == "claudeCode":
		return f"claude mcp add --scope user {SERVER_NAME} -- uvx {package}"
	if client == "codex":
		return f"codex mcp add {SERVER_NAME} -- uvx {package}"
	if client == "json":
		return json.dumps(
			{"mcpServers": {SERVER_NAME: {"command": "uvx", "args": [package]}}},
			indent=2,
		)
	raise ValueError(f"Unknown client {client!r}")
