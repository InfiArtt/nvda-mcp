"""MCP Access, the helper's side: reach another person's NVDA through a relay, end-to-end encrypted.

The person being helped shares their computer from NVDA and gives the helper a code. This client connects to
the relay over TLS 1.3, agrees on keys with their NVDA using the code (access_crypto), waits for them to say
yes, and then sends bridge requests the same way BridgeClient does, so every tool works on their computer.
"""

import asyncio
import contextlib
import json
import os
import ssl
import time
from typing import Any
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from . import access_crypto
from .bridge_client import SUPPORTED_PROTOCOL_VERSION, NvdaBridgeError, NvdaUnavailableError, server_version

RELAY_PROTOCOL_VERSION = 1
DEFAULT_RELAY = "wss://infiartt.com/mcp-access/v1"
MAX_MESSAGE_BYTES = 9 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 20.0
# The person being helped answers NVDA's question in this time.
APPROVAL_TIMEOUT_SECONDS = 120.0


def default_relay() -> str:
    """The relay to use; NVDA_MCP_ACCESS_RELAY points at another, such as an organisation's own."""
    return os.environ.get("NVDA_MCP_ACCESS_RELAY") or DEFAULT_RELAY


def tls_context() -> ssl.SSLContext:
    """Strict TLS: the relay's certificate must be valid for its name, and only TLS 1.3 is accepted."""
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    return context


class AccessClient:
    """A session with another computer's NVDA. Has the same call() as BridgeClient."""

    def __init__(self, relay_url: str) -> None:
        parts = urlsplit(relay_url)
        if parts.scheme not in ("wss", "ws") or not parts.hostname:
            raise NvdaUnavailableError(f"The relay address must start with wss://, not {relay_url!r}.")
        if parts.scheme == "ws" and parts.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise NvdaUnavailableError("The relay must use wss:// (TLS), except on this computer.")
        self.relay_url = relay_url
        self.client_name: str | None = None
        self.computer_name: str | None = None
        self.fingerprint: str | None = None
        self._connection: ClientConnection | None = None
        self._session: access_crypto.Session | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self.ended: str | None = None
        self.messages: list[dict[str, Any]] = []
        """Messages from the person being helped, oldest first: {"id", "text", "time"}."""
        self.noticed_id = 0
        """The newest message the assistant was already shown, by nvda_access_messages or a notice."""
        self._message_arrived = asyncio.Event()

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self.ended is None

    async def connect(self, code: str) -> None:
        """Pair with the computer sharing this code, and wait until its user allows the connection."""
        room = access_crypto.roomId(code)
        try:
            self._connection = await asyncio.wait_for(
                connect(
                    self.relay_url,
                    ssl=tls_context() if self.relay_url.startswith("wss:") else None,
                    max_size=MAX_MESSAGE_BYTES,
                    compression=None,
                    ping_interval=20,
                    ping_timeout=20,
                ),
                CONNECT_TIMEOUT_SECONDS,
            )
        except ssl.SSLError as error:
            raise NvdaUnavailableError(
                f"The relay's secure connection could not be verified ({error.reason})."
            )
        except (OSError, InvalidHandshake, InvalidURI, TimeoutError) as error:
            raise NvdaUnavailableError(f"Could not reach the MCP Access relay at {self.relay_url}: {error}.")
        try:
            await self._handshake(code, room)
        except BaseException:
            await self.close()
            raise

    async def _handshake(self, code: str, room: str) -> None:
        connection = self._connection
        await connection.send(json.dumps({"v": RELAY_PROTOCOL_VERSION, "role": "helper", "room": room}))
        reply = await self._receive_relay()
        if reply.get("type") != "paired":
            raise NvdaUnavailableError(reply.get("message") or "The relay did not pair this code.")
        handshake = access_crypto.Handshake(code, "helper")
        await connection.send(handshake.publicKey)
        peer_key = await self._receive_binary(CONNECT_TIMEOUT_SECONDS)
        try:
            session = handshake.finish(peer_key)
            await connection.send(
                session.seal(
                    json.dumps(
                        {
                            "type": "hello",
                            "role": "helper",
                            "name": self.client_name or "nvda-mcp",
                            "serverVersion": server_version(),
                            "protocolVersion": SUPPORTED_PROTOCOL_VERSION,
                        }
                    ).encode("utf-8")
                )
            )
            hello = json.loads(session.open(await self._receive_binary(CONNECT_TIMEOUT_SECONDS)))
            if hello.get("type") != "hello" or hello.get("role") != "sharer":
                raise NvdaUnavailableError("The other computer sent an unexpected message.")
            if hello.get("protocolVersion") != SUPPORTED_PROTOCOL_VERSION:
                raise NvdaUnavailableError(
                    f"The other computer's NVDA MCP add-on ({hello.get('addonVersion')}) does not match this "
                    f"nvda-mcp server ({server_version()}). Both need the same version."
                )
            answer = json.loads(session.open(await self._receive_binary(APPROVAL_TIMEOUT_SECONDS)))
        except access_crypto.AccessError as error:
            raise NvdaUnavailableError(f"The connection is not secure, so it was stopped: {error}")
        if answer.get("type") != "approved":
            raise NvdaUnavailableError("The person at the other computer did not allow the connection.")
        self.computer_name = str(hello.get("name") or "the other computer")
        self.fingerprint = session.fingerprint
        self._session = session
        self._reader = asyncio.create_task(self._read())

    async def _receive_relay(self) -> dict[str, Any]:
        try:
            message = await asyncio.wait_for(self._connection.recv(), CONNECT_TIMEOUT_SECONDS)
        except TimeoutError:
            raise NvdaUnavailableError("The relay did not answer.")
        except ConnectionClosed:
            raise NvdaUnavailableError("The relay closed the connection.")
        try:
            reply = json.loads(message) if isinstance(message, str) else {}
        except ValueError:
            reply = {}
        return reply if isinstance(reply, dict) else {}

    async def _receive_binary(self, timeout: float) -> bytes:
        try:
            message = await asyncio.wait_for(self._connection.recv(), timeout)
        except TimeoutError:
            raise NvdaUnavailableError(
                "The other computer did not answer in time. Its user may not have answered NVDA's question."
            )
        except ConnectionClosed:
            raise NvdaUnavailableError(
                "The other computer closed the connection, or its user did not allow it."
            )
        if not isinstance(message, bytes):
            raise NvdaUnavailableError("The other computer sent an unexpected message.")
        return message

    async def _read(self) -> None:
        reason = "The other computer stopped sharing."
        try:
            async for message in self._connection:
                if not isinstance(message, bytes):
                    reason = "The other computer sent an unexpected message."
                    break
                reply = json.loads(self._session.open(message))
                if reply.get("type") == "message" and isinstance(reply.get("text"), str):
                    self.messages.append(
                        {"id": len(self.messages) + 1, "text": reply["text"][:4000], "time": time.time()}
                    )
                    self._message_arrived.set()
                    continue
                future = self._pending.pop(reply.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(reply)
        except access_crypto.AccessError as error:
            reason = f"The connection is not secure, so it was stopped: {error}"
        except (ConnectionClosed, ValueError):
            pass
        self.ended = reason
        self._message_arrived.set()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(NvdaUnavailableError(reason))
        self._pending.clear()

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        if self.ended is not None or self._session is None:
            raise NvdaUnavailableError(
                f"MCP Access ended: {self.ended or 'not connected'} Use nvda_access_connect with a new code."
            )
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        request = {"id": request_id, "method": method, "params": dict(params or {})}
        async with self._send_lock:
            await self._connection.send(self._session.seal(json.dumps(request).encode("utf-8")))
        try:
            # The relay and the internet add a little to the time the add-on may take.
            reply = await asyncio.wait_for(future, timeout + 5)
        except TimeoutError:
            self._pending.pop(request_id, None)
            raise NvdaUnavailableError(f"The other computer did not answer {method} in time.")
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise NvdaBridgeError(error.get("code", "unknown"), error.get("message", "Unknown error."))
        return reply.get("result")

    async def wait_for_messages(self, after_id: int, wait_seconds: float) -> list[dict[str, Any]]:
        """Messages newer than after_id, waiting up to wait_seconds for one if there are none yet."""
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            newer = [message for message in self.messages if message["id"] > after_id]
            remaining = deadline - asyncio.get_running_loop().time()
            if newer or remaining <= 0 or self.ended is not None:
                return newer
            self._message_arrived.clear()
            try:
                await asyncio.wait_for(self._message_arrived.wait(), remaining)
            except TimeoutError:
                pass

    async def close(self) -> None:
        if self.ended is None:
            self.ended = "You disconnected."
        if self._reader is not None:
            self._reader.cancel()
        if self._connection is not None:
            with contextlib.suppress(Exception):
                await self._connection.close()
