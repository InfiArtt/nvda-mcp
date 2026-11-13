# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""The add-on's configuration section. Shared by the plugin and installTasks, so it imports nothing."""

CONFIG_SECTION = "nvdaMcp"

CONFIG_SPEC: dict[str, str] = {
	"enabled": "boolean(default=True)",
	"allowControl": "boolean(default=False)",
	"confirmControl": "boolean(default=True)",
	"speechHistorySize": "integer(default=500, min=50, max=5000)",
	# Application names as NVDA reports them (the program file without .exe), separated by commas.
	# Empty means every application may be controlled.
	"allowedApps": "string(default='')",
	"logActions": "boolean(default=True)",
	# Lets MCP clients read web pages through the browser's remote debugging (Chrome DevTools Protocol).
	"allowBrowserInspection": "boolean(default=False)",
	# Lets MCP clients take pictures of controls on the screen; the pictures go to the client's AI provider.
	"allowScreenCapture": "boolean(default=False)",
	# Where MCP Access meets the helper. Only wss:// (TLS) addresses work, except on this computer.
	# MCP Access helpers ask the person being helped before pressing keys, once per session, whatever
	# allowControl says; this turns that off completely.
	"blockAccessControl": "boolean(default=False)",
	# MCP Access helpers ask before taking pictures of the screen, once per session, whatever
	# allowScreenCapture says; this turns that off completely.
	"blockAccessCapture": "boolean(default=False)",
	"accessRelay": "string(default='wss://infiartt.com/mcp-access/v1')",
}


def parseAllowedApps(value: str) -> set[str]:
	"""Turn the allowedApps setting into lower-case application names, ignoring blanks and a trailing .exe."""
	names = set()
	for name in value.split(","):
		name = name.strip().casefold()
		name = name.removesuffix(".exe")
		if name:
			names.add(name)
	return names
