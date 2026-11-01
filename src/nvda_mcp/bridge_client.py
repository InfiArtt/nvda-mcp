"""Client for the loopback bridge run by the NVDA MCP add-on."""

import json
import os
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
            raise NvdaUnavailableError(
                f"The NVDA MCP add-on speaks bridge protocol {info.get('protocolVersion')}, "
                f"but this server expects {SUPPORTED_PROTOCOL_VERSION}. Update the add-on and the server together."
            )
        return info

    async def call(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Any:
        info = self._read_connection()
        url = f"http://127.0.0.1:{info['port']}/rpc"
        headers = {"Authorization": f"Bearer {info['token']}"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                response = await client.post(
                    url, json={"method": method, "params": params or {}}, headers=headers
                )
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
