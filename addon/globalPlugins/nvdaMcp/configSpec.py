# NVDA MCP add-on
# Copyright (C) 2026 audiogaming23
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
