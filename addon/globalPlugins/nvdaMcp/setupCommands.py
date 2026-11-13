# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""What to give each MCP client so it starts the nvda-mcp server, and setting clients up directly.

The server is pinned to this add-on's version, since the two must match.
This module does not import NVDA, so it can be unit tested on its own.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Mapping

PACKAGE = "nvda-mcp"
SERVER_NAME = "nvda"
# Clients set up with a command in a terminal.
COMMAND_CLIENTS = ("claudeCode", "codex")
# Clients set up with a JSON settings file whose place NVDA MCP knows.
FILE_CLIENTS = ("claudeDesktop", "antigravity", "cursor")
# Then "json": the settings to paste into any other client's file.
CLIENTS = (*COMMAND_CLIENTS, *FILE_CLIENTS, "json")
# Programs a command client's setup runs, found on the PATH.
_PROGRAMS = {"claudeCode": "claude", "codex": "codex"}
# How long a client's own setup command may take.
COMMAND_TIMEOUT_SECONDS = 60
_CREATE_NO_WINDOW = 0x08000000


class SetupError(Exception):
	"""Setting up a client failed; the message says why and what to do, for the user."""


def serverPackage(addonVersion: str) -> str:
	return f"{PACKAGE}=={addonVersion}"


def serverEntry(addonVersion: str) -> dict:
	"""The server's entry in a client's mcpServers settings."""
	return {"command": "uvx", "args": [serverPackage(addonVersion)]}


def setupText(client: str, addonVersion: str) -> str:
	"""The command, or the JSON settings, that make ``client`` run the server matching ``addonVersion``."""
	package = serverPackage(addonVersion)
	if client == "claudeCode":
		return f"claude mcp add --scope user {SERVER_NAME} -- uvx {package}"
	if client == "codex":
		return f"codex mcp add {SERVER_NAME} -- uvx {package}"
	if client in FILE_CLIENTS or client == "json":
		return json.dumps({"mcpServers": {SERVER_NAME: serverEntry(addonVersion)}}, indent=2)
	raise ValueError(f"Unknown client {client!r}")


def configFilePath(client: str, env: Mapping[str, str] | None = None) -> str:
	"""Where ``client`` keeps its MCP settings, whether or not the file exists yet."""
	env = os.environ if env is None else env
	home = env.get("USERPROFILE") or os.path.expanduser("~")
	if client == "claudeDesktop":
		# Claude Desktop installed as a Windows app package keeps its files inside the package's folder.
		packages = os.path.join(env.get("LOCALAPPDATA", ""), "Packages")
		if env.get("LOCALAPPDATA") and os.path.isdir(packages):
			for name in sorted(os.listdir(packages)):
				if name.startswith("Claude_"):
					return os.path.join(
						packages, name, "LocalCache", "Roaming", "Claude", "claude_desktop_config.json"
					)
		return os.path.join(env.get("APPDATA", ""), "Claude", "claude_desktop_config.json")
	if client == "antigravity":
		gemini = os.path.join(home, ".gemini")
		candidates = [
			os.path.join(gemini, "config", "mcp_config.json"),
			os.path.join(gemini, "antigravity", "mcp_config.json"),
		]
		for candidate in candidates:
			if os.path.isfile(candidate):
				return candidate
		# Antigravity moved its settings to .gemini\config; older versions read .gemini\antigravity.
		return candidates[0] if os.path.isdir(os.path.dirname(candidates[0])) else candidates[1]
	if client == "cursor":
		return os.path.join(home, ".cursor", "mcp.json")
	raise ValueError(f"{client!r} is not set up with a settings file")


def addServerToSettings(text: str, addonVersion: str) -> tuple[str, dict | None]:
	"""Add the server to a client's settings, keeping everything else in them.

	:param text: The settings file's contents; empty for a new file.
	:returns: The new contents, and the server's previous entry, if there was one.
	:raises SetupError: When the file is not JSON settings that can be changed safely.
	"""
	if text.strip():
		try:
			settings = json.loads(text)
		except ValueError as error:
			raise SetupError(
				f"The settings file is not valid JSON ({error}). Nothing was changed. "
				"Fix the file, or copy the settings and add them by hand."
			)
	else:
		settings = {}
	if not isinstance(settings, dict):
		raise SetupError("The settings file does not hold JSON settings. Nothing was changed.")
	servers = settings.setdefault("mcpServers", {})
	if not isinstance(servers, dict):
		raise SetupError('The settings file\'s "mcpServers" is not a list of servers. Nothing was changed.')
	previous = servers.get(SERVER_NAME)
	servers[SERVER_NAME] = serverEntry(addonVersion)
	return json.dumps(settings, indent=2, ensure_ascii=False) + "\n", previous


def installInFile(path: str, addonVersion: str) -> dict | None:
	"""Add the server to the settings file at ``path``, keeping a copy of the old file next to it.

	:returns: The server's previous entry, if there was one.
	:raises SetupError: When the file cannot be read, changed or written.
	"""
	try:
		with open(path, encoding="utf-8-sig") as file:
			old = file.read()
	except FileNotFoundError:
		old = ""
	except OSError as error:
		raise SetupError(f"Could not read {path}: {error.strerror or error}.")
	new, previous = addServerToSettings(old, addonVersion)
	try:
		os.makedirs(os.path.dirname(path), exist_ok=True)
		if old:
			shutil.copyfile(path, path + ".bak")
		temporary = path + ".tmp"
		with open(temporary, "w", encoding="utf-8", newline="\n") as file:
			file.write(new)
		os.replace(temporary, path)
	except OSError as error:
		raise SetupError(f"Could not write {path}: {error.strerror or error}.")
	return previous


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
	return subprocess.run(
		arguments,
		check=False,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=COMMAND_TIMEOUT_SECONDS,
		creationflags=_CREATE_NO_WINDOW,
		stdin=subprocess.DEVNULL,
	)


def runSetupCommand(client: str, addonVersion: str, which=shutil.which, run=_run) -> bool:
	"""Set up a command client by running its own command. Takes a while: call it off NVDA's main thread.

	:returns: Whether an earlier NVDA MCP entry was replaced.
	:raises SetupError: When the client's program is missing or its command fails.
	"""
	program = which(_PROGRAMS[client])
	if program is None:
		raise SetupError(
			f"The {_PROGRAMS[client]} command was not found. Install the client first, "
			"or copy the setup command and run it where the client works."
		)
	scope = ["--scope", "user"] if client == "claudeCode" else []
	add = [program, "mcp", "add", *scope, SERVER_NAME, "--", "uvx", serverPackage(addonVersion)]
	try:
		result = run(add)
		replaced = False
		if result.returncode != 0 and "already exists" in (result.stdout + result.stderr):
			# Claude Code refuses to add a server under a name it already has: replace the old entry.
			run([program, "mcp", "remove", *scope, SERVER_NAME])
			result = run(add)
			replaced = True
	except (OSError, subprocess.TimeoutExpired) as error:
		raise SetupError(f"Could not run {_PROGRAMS[client]}: {error}.")
	if result.returncode != 0:
		output = (result.stderr or result.stdout).strip().splitlines()
		raise SetupError(
			f"{_PROGRAMS[client]} reported an error: {output[-1] if output else result.returncode}."
		)
	return replaced
