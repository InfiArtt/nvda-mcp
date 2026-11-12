# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Registers the add-on's configuration section, using the API added in NVDA 2026.3.

Registered sections are written to disk and loaded at the next NVDA start,
which is when a newly installed add-on runs for the first time.
Older versions of NVDA have no such API; the plugin then adds the section each time it starts.
"""

import importlib.util
import os


def _loadConfigSpec():
	# Loaded by path so installing does not import the plugin package.
	path = os.path.join(os.path.dirname(__file__), "globalPlugins", "nvdaMcp", "configSpec.py")
	spec = importlib.util.spec_from_file_location("nvdaMcpConfigSpec", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def onInstall() -> None:
	try:
		from config.configSections import registerSection
	except ImportError:
		# NVDA 2025.1 to 2026.2: the plugin adds the section itself when it starts.
		return

	configSpec = _loadConfigSpec()
	# Base only: whether Claude may press keys is a security choice, not something to vary per profile.
	registerSection(configSpec.CONFIG_SECTION, configSpec.CONFIG_SPEC, isBaseOnly=True)


def onUninstall() -> None:
	# This runs early in NVDA's startup; a failure here must not block removing the add-on.
	try:
		from config.configSections import unregisterSection
	except ImportError:
		# NVDA 2025.1 to 2026.2: nothing was registered.
		return
	try:
		unregisterSection(_loadConfigSpec().CONFIG_SECTION)
	except Exception:  # noqa: BLE001 - see comment above
		from logHandler import log

		log.exception("Could not unregister the nvdaMcp configuration section")
