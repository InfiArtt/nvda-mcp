# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""MCP Access, the side of the computer being helped: share this NVDA with a helper's nvda-mcp server.

The add-on connects out to a relay over TLS 1.3, waits for the helper who has the code, agrees on
end-to-end keys with them (accessCrypto), asks the user, and then answers the helper's requests with the
same handlers the local bridge uses. Only methods in ALLOWED_METHODS are answered; the rest are refused.

NVDA ships no WebSocket library, so a small client (RFC 6455) is written here on the standard socket and ssl
modules. This module does not import NVDA, so it can be unit tested on its own.
"""

import base64
import hashlib
import json
import os
import queue
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

try:
	from . import accessCrypto
except ImportError:  # Unit tests import the add-on modules directly.
	import accessCrypto

RELAY_PROTOCOL_VERSION = 1
DEFAULT_RELAY = "wss://infiartt.com/mcp-access/v1"
# How long a code waits for a helper; the relay forgets it after this too.
CODE_LIFETIME_SECONDS = 10 * 60
# A session ends after this long. The user can share again with a new code.
MAX_SESSION_SECONDS = 2 * 60 * 60
CONNECT_TIMEOUT_SECONDS = 15
MAX_FRAME_BYTES = 9 * 1024 * 1024

# What a helper may ask for: reading, and, after the user says yes for the session, pressing keys and taking
# pictures of the screen. Left out: reloading or running add-on code, NVDA's log and settings, and the browser's
# remote debugging, which reach beyond what NVDA says.
ALLOWED_METHODS = frozenset(
	{
		"getStatus",
		"getFocus",
		"getNavigator",
		"getTree",
		"getText",
		"getSpeech",
		"speak",
		"pressKeys",
		"typeText",
		"listWindows",
		"activateWindow",
		"waitForSpeech",
		"findObjects",
		"focusObject",
		"activateObject",
		"inspectObject",
		"setValue",
		"getActionLog",
		"setDocumentMode",
		"findInPage",
		"listElements",
		"moveToElement",
		"previewSpeech",
		"getDevInfo",
		"listScripts",
		"lookupApi",
		"recognizeText",
		"traceEvents",
		"getOutput",
		"captureControl",
	}
)

_OP_CONTINUATION, _OP_TEXT, _OP_BINARY, _OP_CLOSE, _OP_PING, _OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# Why a sharing session ended, so NVDA can say it in the user's language.
CLOSE_PEER_LEFT = 4000


class AccessShareError(Exception):
	"""Sharing could not start or stopped; the message is for the log and the helper, in English.

	:param kind: Why, for NVDA to say in the user's language: "helperLeft", "declined", "expired",
		"timeLimit", "relayClosed" or "error".
	"""

	def __init__(self, message: str, kind: str = "error") -> None:
		super().__init__(message)
		self.kind = kind


def isLocalHost(host: str) -> bool:
	return host in ("127.0.0.1", "localhost", "::1")


def tlsContext() -> ssl.SSLContext:
	"""Strict TLS: the relay's certificate must be valid for its name, and only TLS 1.3 is accepted."""
	context = ssl.create_default_context()
	context.minimum_version = ssl.TLSVersion.TLSv1_3
	return context


class WebSocket:
	"""A minimal WebSocket client: one connection, whole messages, pings answered by the reader."""

	def __init__(self, url: str, timeout: float = CONNECT_TIMEOUT_SECONDS) -> None:
		parts = urlsplit(url)
		if parts.scheme not in ("wss", "ws") or not parts.hostname:
			raise AccessShareError(f"The relay address must start with wss://, not {url!r}.")
		if parts.scheme == "ws" and not isLocalHost(parts.hostname):
			# Unencrypted connections are for a relay on this computer only, such as in tests.
			raise AccessShareError("The relay must use wss:// (TLS), except on this computer.")
		port = parts.port or (443 if parts.scheme == "wss" else 80)
		try:
			raw = socket.create_connection((parts.hostname, port), timeout=timeout)
			self._socket = (
				tlsContext().wrap_socket(raw, server_hostname=parts.hostname)
				if parts.scheme == "wss"
				else raw
			)
		except ssl.SSLError as error:
			raise AccessShareError(f"The relay's secure connection could not be verified ({error.reason}).")
		except OSError as error:
			raise AccessShareError(
				f"Could not reach the relay at {parts.hostname}: {error.strerror or error}."
			)
		self._sendLock = threading.Lock()
		self._buffer = b""
		self._handshake(
			parts.hostname, port, (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
		)
		self._socket.settimeout(None)

	def _handshake(self, host: str, port: int, path: str) -> None:
		key = base64.b64encode(os.urandom(16)).decode("ascii")
		request = (
			f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
			f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
		)
		self._socket.sendall(request.encode("ascii"))
		while b"\r\n\r\n" not in self._buffer:
			chunk = self._socket.recv(4096)
			if not chunk or len(self._buffer) > 16384:
				raise AccessShareError("The relay did not accept the connection.")
			self._buffer += chunk
		head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
		lines = head.decode("latin-1").split("\r\n")
		expected = base64.b64encode(hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()).decode()
		headers = {
			name.strip().lower(): value.strip()
			for name, _sep, value in (line.partition(":") for line in lines[1:])
		}
		if " 101 " not in lines[0] + " " or headers.get("sec-websocket-accept") != expected:
			raise AccessShareError("The relay did not accept the connection.")

	def _read(self, count: int) -> bytes:
		while len(self._buffer) < count:
			chunk = self._socket.recv(max(65536, count - len(self._buffer)))
			if not chunk:
				raise AccessShareError("The relay closed the connection.", "relayClosed")
			self._buffer += chunk
		data, self._buffer = self._buffer[:count], self._buffer[count:]
		return data

	def send(self, payload: bytes | str) -> None:
		opcode = _OP_TEXT if isinstance(payload, str) else _OP_BINARY
		self._sendFrame(opcode, payload.encode("utf-8") if isinstance(payload, str) else payload)

	def _sendFrame(self, opcode: int, payload: bytes) -> None:
		length = len(payload)
		header = bytes([0x80 | opcode])
		if length < 126:
			header += bytes([0x80 | length])
		elif length < 65536:
			header += bytes([0x80 | 126]) + struct.pack(">H", length)
		else:
			header += bytes([0x80 | 127]) + struct.pack(">Q", length)
		mask = os.urandom(4)
		masked = (
			bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
			if length < 4096
			else _mask(payload, mask)
		)
		with self._sendLock:
			self._socket.sendall(header + mask + masked)

	def receive(self) -> bytes | str:
		"""The next whole message: str for text, bytes for binary. Answers pings on the way."""
		parts: list[bytes] = []
		messageOpcode = None
		while True:
			first, second = self._read(2)
			opcode = first & 0x0F
			length = second & 0x7F
			if second & 0x80:
				raise AccessShareError("The relay sent a masked frame.")
			if length == 126:
				(length,) = struct.unpack(">H", self._read(2))
			elif length == 127:
				(length,) = struct.unpack(">Q", self._read(8))
			if length > MAX_FRAME_BYTES:
				raise AccessShareError("The relay sent a message that is too large.")
			payload = self._read(length)
			if opcode == _OP_PING:
				self._sendFrame(_OP_PONG, payload)
				continue
			if opcode == _OP_PONG:
				continue
			if opcode == _OP_CLOSE:
				status = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
				if status == CLOSE_PEER_LEFT:
					raise AccessShareError("The helper ended the session.", "helperLeft")
				raise AccessShareError("The relay closed the connection.", "relayClosed")
			if opcode in (_OP_TEXT, _OP_BINARY):
				messageOpcode = opcode
				parts = [payload]
			elif opcode == _OP_CONTINUATION and messageOpcode is not None:
				parts.append(payload)
			else:
				raise AccessShareError("The relay sent an unexpected frame.")
			if sum(len(part) for part in parts) > MAX_FRAME_BYTES:
				raise AccessShareError("The relay sent a message that is too large.")
			if first & 0x80:
				message = b"".join(parts)
				return message.decode("utf-8") if messageOpcode == _OP_TEXT else message

	def close(self) -> None:
		try:
			self._sendFrame(_OP_CLOSE, struct.pack(">H", 1000))
		except OSError:
			pass
		try:
			self._socket.close()
		except OSError:
			pass


def _mask(payload: bytes, mask: bytes) -> bytes:
	"""XOR a large payload with the mask, a word at a time."""
	repeated = (mask * (len(payload) // 4 + 1))[: len(payload)]
	return (int.from_bytes(payload, "big") ^ int.from_bytes(repeated, "big")).to_bytes(len(payload), "big")


class ShareSession:
	"""One sharing of this computer: a code, a wait for the helper, the user's answer, then requests.

	Runs on a thread of its own. Every callback may be called from that thread.
	:param dispatch: Answers a request like the local bridge: returns {"ok": ..., "result" | "error": ...}.
	:param approve: Asks the user whether this helper may read the computer; called with the name the helper
		gives itself and the session fingerprint. Returns True only when the user said yes.
	:param onEvent: Told "waiting", "connected", "ended" or "failed", with details, so the user hears them.
	"""

	def __init__(
		self,
		relayUrl: str,
		dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
		approve: Callable[[str, str], bool],
		onEvent: Callable[[str, dict[str, Any]], None],
		computerName: str,
		addonVersion: str,
		protocolVersion: int,
		code: str | None = None,
	) -> None:
		self.code = code or accessCrypto.newCode()
		self.sessionId = os.urandom(16).hex()
		self._relayUrl = relayUrl
		self._dispatch = dispatch
		self._approve = approve
		self._onEvent = onEvent
		self._computerName = computerName
		self._addonVersion = addonVersion
		self._protocolVersion = protocolVersion
		self._socket: WebSocket | None = None
		self._stopped = threading.Event()
		self._thread: threading.Thread | None = None
		self.helperName: str | None = None

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, name="nvdaMcpAccess", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		self._stopped.set()
		if self._socket is not None:
			self._socket.close()

	@property
	def isRunning(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	def _run(self) -> None:
		reason, kind = "stopped", "stopped"
		try:
			self._serve()
		except AccessShareError as error:
			reason, kind = str(error), error.kind
		except accessCrypto.AccessError as error:
			reason, kind = f"The connection was not secure: {error}", "insecure"
		except OSError as error:
			reason, kind = f"The connection was lost: {error.strerror or error}.", "relayClosed"
		finally:
			if self._socket is not None:
				self._socket.close()
		if self._stopped.is_set():
			reason, kind = "stopped", "stopped"
		self._onEvent("ended", {"reason": reason, "kind": kind, "helper": self.helperName})

	def _serve(self) -> None:
		socket_ = self._socket = WebSocket(self._relayUrl)
		socket_.send(
			json.dumps(
				{"v": RELAY_PROTOCOL_VERSION, "role": "sharer", "room": accessCrypto.roomId(self.code)}
			)
		)
		self._expectRelay(socket_, "waiting")
		self._onEvent("waiting", {"code": self.code, "minutes": CODE_LIFETIME_SECONDS // 60})
		self._expectRelay(socket_, "paired")
		handshake = accessCrypto.Handshake(self.code, "sharer")
		socket_.send(handshake.publicKey)
		peerKey = socket_.receive()
		if not isinstance(peerKey, bytes):
			raise AccessShareError("The helper sent an unexpected message.")
		session_ = handshake.finish(peerKey)
		socket_.send(
			session_.seal(
				json.dumps(
					{
						"type": "hello",
						"role": "sharer",
						"name": self._computerName,
						"addonVersion": self._addonVersion,
						"protocolVersion": self._protocolVersion,
					}
				).encode("utf-8")
			)
		)
		hello = self._receiveSealed(socket_, session_)
		if hello.get("type") != "hello" or hello.get("role") != "helper":
			raise AccessShareError("The helper sent an unexpected message.")
		self.helperName = _cleanName(hello.get("name")) or "A helper"
		if not self._approve(self.helperName, session_.fingerprint):
			socket_.send(session_.seal(json.dumps({"type": "refused"}).encode("utf-8")))
			raise AccessShareError("You did not allow the helper to connect.", "declined")
		socket_.send(session_.seal(json.dumps({"type": "approved"}).encode("utf-8")))
		self._onEvent("connected", {"helper": self.helperName, "fingerprint": session_.fingerprint})
		self._answerRequests(socket_, session_)

	def _answerRequests(self, socket_: WebSocket, session: accessCrypto.Session) -> None:
		# The reader answers the relay's pings while a request runs, which can take minutes
		# when the user is asked to allow key presses.
		inbox: queue.Queue = queue.Queue()

		def read() -> None:
			try:
				while True:
					inbox.put(socket_.receive())
			except Exception as error:  # noqa: BLE001 - any failure ends the session
				inbox.put(error)

		threading.Thread(target=read, name="nvdaMcpAccessReader", daemon=True).start()
		deadline = time.monotonic() + MAX_SESSION_SECONDS
		while not self._stopped.is_set():
			try:
				message = inbox.get(timeout=max(deadline - time.monotonic(), 0.1))
			except queue.Empty:
				raise AccessShareError("The session reached its time limit of two hours.", "timeLimit")
			if isinstance(message, Exception):
				raise message if isinstance(message, AccessShareError) else AccessShareError(str(message))
			if not isinstance(message, bytes):
				raise AccessShareError("The helper sent an unexpected message.")
			request = json.loads(session.open(message))
			response = self._answer(request)
			socket_.send(session.seal(json.dumps(response, ensure_ascii=False).encode("utf-8")))

	def _answer(self, request: dict[str, Any]) -> dict[str, Any]:
		requestId = request.get("id")
		method = request.get("method")
		params = request.get("params")
		if not isinstance(method, str) or not isinstance(params, dict):
			return {
				"id": requestId,
				"ok": False,
				"error": {"code": "badRequest", "message": "Malformed request."},
			}
		if method not in ALLOWED_METHODS:
			return {
				"id": requestId,
				"ok": False,
				"error": {
					"code": "notAllowedOverAccess",
					"message": f"{method} is not available through MCP Access, to protect the person being helped.",
				},
			}
		# NVDA names the helper when it asks the user to allow key presses, and asks again for every session,
		# whatever the user answered for MCP clients on this computer.
		params["clientName"] = f"{self.helperName} through MCP Access"
		params["viaAccess"] = self.sessionId
		return {"id": requestId, **self._dispatch(method, params)}

	def _expectRelay(self, socket_: WebSocket, expected: str) -> None:
		message = socket_.receive()
		try:
			reply = json.loads(message) if isinstance(message, str) else {}
		except ValueError:
			reply = {}
		if reply.get("type") == expected:
			return
		if reply.get("type") == "error":
			kind = "expired" if reply.get("code") == "expired" else "error"
			raise AccessShareError(str(reply.get("message") or "The relay refused the connection."), kind)
		raise AccessShareError("The relay sent an unexpected message.")

	@staticmethod
	def _receiveSealed(socket_: WebSocket, session: accessCrypto.Session) -> dict[str, Any]:
		message = socket_.receive()
		if not isinstance(message, bytes):
			raise AccessShareError("The helper sent an unexpected message.")
		try:
			value = json.loads(session.open(message))
		except ValueError:
			raise AccessShareError("The helper sent an unexpected message.")
		if not isinstance(value, dict):
			raise AccessShareError("The helper sent an unexpected message.")
		return value


def _cleanName(name: Any) -> str:
	"""A name the other side gave itself, made safe to speak: printable, single line, at most 60 characters."""
	if not isinstance(name, str):
		return ""
	return " ".join("".join(char if char.isprintable() else " " for char in name).split())[:60]
