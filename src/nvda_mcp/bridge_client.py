"""Client for the loopback bridge run by the NVDA MCP add-on."""

import json
import os
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx

SUPPORTED_PROTOCOL_VERSION = 3
DEFAULT_TIMEOUT_SECONDS = 10.0


def default_connection_file() -> Path:
    """The file the add-on writes in NVDA's user configuration directory.

    Set NVDA_MCP_CONNECTION_FILE for portable copies of NVDA, whose configuration lives elsewhere.
    """
    override = os.environ.get("NVDA_MCP_CONNECTION_FILE")
    if override:
        return Path(override)
    return Path(os.environ.get("APPDATA", "")) / "nvda" / "nvdaMcp" / "connection.json"


class NvdaUnavailableError(Exception):
    """NVDA, or the add-on's bridge, cannot be reached."""


class NvdaBridgeError(Exception):
    """The add-on received the request but reported a failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def server_version() -> str:
    try:
        return metadata.version("nvda-mcp")
    except metadata.PackageNotFoundError:
        return "unknown"


def version_mismatch_message(info: dict[str, Any]) -> str:
    """Says which of the add-on and the server is older, and how to update it."""
    addon_protocol = info.get("protocolVersion")
    addon_version = info.get("addonVersion") or "an older version"
    mismatch = (
        f"The NVDA MCP add-on ({addon_version}) and this nvda-mcp server ({server_version()}) do not match: "
        f"the add-on speaks bridge protocol {addon_protocol}, the server {SUPPORTED_PROTOCOL_VERSION}."
    )
    if isinstance(addon_protocol, int) and addon_protocol > SUPPORTED_PROTOCOL_VERSION:
        return (
            f"{mismatch} Update the server: in NVDA, open Settings, NVDA MCP category, choose your client, "
            "press Copy setup command and run what it copies. "
            "If you installed the server with pip or pipx, upgrade it there instead."
        )
    return f"{mismatch} Update the add-on: in NVDA, open Tools, Add-on Store, Updatable add-ons."


_NOT_RUNNING_HINT = (
    "Make sure NVDA is running, the NVDA MCP add-on is installed and enabled "
    "(NVDA Settings, NVDA MCP category), and NVDA was restarted after installing it."
)


class BridgeClient:
    """Calls bridge methods. Reads the connection file on every call, so it survives NVDA restarts."""

    def __init__(
        self, connection_file: Path | None = None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._connection_file = connection_file or default_connection_file()
        self._transport = transport
        self.client_name: str | None = None
        """The MCP client's name, such as "Claude Code"; sent with every call so NVDA can show it."""

    def _read_connection(self) -> dict[str, Any]:
        try:
            info = json.loads(self._connection_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise NvdaUnavailableError(
                f"NVDA is not reachable: {self._connection_file} does not exist. {_NOT_RUNNING_HINT}"
            )
        except (OSError, ValueError) as error:
            raise NvdaUnavailableError(
                f"Could not read {self._connection_file}: {error}. {_NOT_RUNNING_HINT}"
            )
        if info.get("protocolVersion") != SUPPORTED_PROTOCOL_VERSION:
            raise NvdaUnavailableError(version_mismatch_message(info))
        return info

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Any:
        info = self._read_connection()
        url = f"http://127.0.0.1:{info['port']}/rpc"
        headers = {"Authorization": f"Bearer {info['token']}"}
        params = dict(params or {})
        if self.client_name:
            params["clientName"] = self.client_name
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                response = await client.post(url, json={"method": method, "params": params}, headers=headers)
        except httpx.TimeoutException:
            raise NvdaUnavailableError(
                f"NVDA did not answer {method} within {timeout:g} seconds. It may be busy or frozen; try again shortly."
            )
        except httpx.TransportError:
            raise NvdaUnavailableError(f"NVDA is not reachable on port {info['port']}. {_NOT_RUNNING_HINT}")
        try:
            body = response.json()
        except ValueError:
            raise NvdaBridgeError(
                "badResponse", f"The bridge returned HTTP {response.status_code} without JSON."
            )
        if not body.get("ok"):
            error = body.get("error") or {}
            raise NvdaBridgeError(error.get("code", "unknown"), error.get("message", "Unknown bridge error."))
        return body["result"]
