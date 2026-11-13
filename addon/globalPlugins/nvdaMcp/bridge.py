# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""A small authenticated JSON-over-HTTP server bound to the loopback interface.

The MCP server (a separate process) talks to NVDA through this bridge.
Requests look like ``POST /rpc`` with a JSON body ``{"method": str, "params": dict}``
and an ``Authorization: Bearer <token>`` header.
Responses are ``{"ok": true, "result": ...}`` or ``{"ok": false, "error": {"code": str, "message": str}}``.

This module does not import NVDA, so it can be unit tested on its own.
"""

import hmac
import json
import os
import secrets
import tempfile
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROTOCOL_VERSION = 8
LOOPBACK_HOST = "127.0.0.1"
MAX_BODY_BYTES = 64 * 1024

Handler = Callable[[dict[str, Any]], Any]


class BridgeError(Exception):
	"""An error that is reported back to the client with a stable code."""

	def __init__(self, code: str, message: str) -> None:
		super().__init__(message)
		self.code = code
		self.message = message


class _RequestHandler(BaseHTTPRequestHandler):
	server: "_BridgeHttpServer"
	protocol_version = "HTTP/1.1"

	def log_message(self, format: str, *args: Any) -> None:
		# Request logging goes through NVDA's log via the bridge's error callback instead of stderr.
		pass

	def do_GET(self) -> None:
		self._sendJson(HTTPStatus.METHOD_NOT_ALLOWED, _errorBody("methodNotAllowed", "Use POST /rpc."))

	def do_POST(self) -> None:
		rejection = self._rejectionFor()
		if rejection is not None:
			status, code, message = rejection
			self._sendJson(status, _errorBody(code, message))
			return
		try:
			length = int(self.headers.get("Content-Length", "0"))
			request = json.loads(self.rfile.read(length))
			method = request["method"]
			params = request.get("params") or {}
			if not isinstance(method, str) or not isinstance(params, dict):
				raise TypeError
		except (ValueError, KeyError, TypeError):
			self._sendJson(
				HTTPStatus.BAD_REQUEST,
				_errorBody("badRequest", 'Expected {"method": str, "params": object}.'),
			)
			return
		self._sendJson(HTTPStatus.OK, self.server.bridge.dispatch(method, params))

	def _rejectionFor(self) -> tuple[HTTPStatus, str, str] | None:
		"""Checks that apply before the body is read. Returns None when the request may proceed."""
		if self.path != "/rpc":
			return HTTPStatus.NOT_FOUND, "notFound", "Use POST /rpc."
		# Browsers always send Origin on cross-site POSTs; local tools do not.
		# Rejecting it, and requiring a loopback Host, blocks web pages and DNS rebinding.
		if self.headers.get("Origin") is not None:
			return HTTPStatus.FORBIDDEN, "forbidden", "Requests from web pages are not accepted."
		host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
		if host not in (LOOPBACK_HOST, "localhost"):
			return HTTPStatus.FORBIDDEN, "forbidden", "Only loopback requests are accepted."
		authorization = self.headers.get("Authorization") or ""
		if not hmac.compare_digest(authorization.encode(), f"Bearer {self.server.bridge.token}".encode()):
			return HTTPStatus.UNAUTHORIZED, "unauthorized", "Missing or wrong bridge token."
		length = self.headers.get("Content-Length")
		if length is None or not length.isdigit() or int(length) > MAX_BODY_BYTES:
			return (
				HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
				"badRequest",
				f"Body must be at most {MAX_BODY_BYTES} bytes.",
			)
		return None

	def _sendJson(self, status: HTTPStatus, body: dict[str, Any]) -> None:
		payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(payload)))
		self.end_headers()
		self.wfile.write(payload)


class _BridgeHttpServer(ThreadingHTTPServer):
	daemon_threads = True

	def __init__(self, bridge: "Bridge", port: int) -> None:
		self.bridge = bridge
		super().__init__((LOOPBACK_HOST, port), _RequestHandler)


def _errorBody(code: str, message: str) -> dict[str, Any]:
	return {"ok": False, "error": {"code": code, "message": message}}


class Bridge:
	"""Owns the HTTP server thread, the access token and the method table."""

	def __init__(
		self,
		handlers: dict[str, Handler],
		connectionFilePath: str,
		onError: Callable[[str], None],
		port: int = 0,
		addonVersion: str | None = None,
	) -> None:
		"""
		:param handlers: Maps method names to callables taking the request params.
			A handler may raise :class:`BridgeError` to report a specific failure.
		:param connectionFilePath: Where to publish the port and token for the MCP server.
		:param onError: Called with a description of unexpected handler exceptions, for logging.
		:param port: TCP port to listen on; 0 picks a free port.
		:param addonVersion: Published too, so a server that does not match can say which one to update.
		"""
		self._handlers = handlers
		self._connectionFilePath = connectionFilePath
		self._onError = onError
		self._requestedPort = port
		self._addonVersion = addonVersion
		self.token = secrets.token_urlsafe(32)
		self._server: _BridgeHttpServer | None = None
		self._thread: threading.Thread | None = None

	@property
	def port(self) -> int | None:
		return self._server.server_address[1] if self._server else None

	def start(self) -> None:
		self._server = _BridgeHttpServer(self, self._requestedPort)
		self._thread = threading.Thread(
			target=self._server.serve_forever,
			name="nvdaMcpBridge",
			daemon=True,
		)
		self._thread.start()
		self._writeConnectionFile()

	def stop(self) -> None:
		if self._server is None:
			return
		self._server.shutdown()
		self._server.server_close()
		self._server = None
		self._thread = None
		try:
			os.remove(self._connectionFilePath)
		except FileNotFoundError:
			pass

	def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
		handler = self._handlers.get(method)
		if handler is None:
			return _errorBody(
				"unknownMethod", f"Unknown method {method!r}. Known: {', '.join(sorted(self._handlers))}."
			)
		try:
			return {"ok": True, "result": handler(params)}
		except BridgeError as error:
			return _errorBody(error.code, error.message)
		except Exception as error:  # noqa: BLE001 - a failing handler must not take down the bridge thread
			self._onError(f"Bridge method {method} failed: {error!r}")
			return _errorBody("internalError", f"NVDA raised {type(error).__name__}: {error}")

	def _writeConnectionFile(self) -> None:
		"""Atomically write the port and token so a reader never sees a partial file."""
		info = {
			"protocolVersion": PROTOCOL_VERSION,
			"port": self.port,
			"token": self.token,
			"pid": os.getpid(),
			"addonVersion": self._addonVersion,
		}
		directory = os.path.dirname(self._connectionFilePath)
		os.makedirs(directory, exist_ok=True)
		fd, tempPath = tempfile.mkstemp(dir=directory, prefix=".connection-", suffix=".tmp")
		with os.fdopen(fd, "w", encoding="utf-8") as file:
			json.dump(info, file)
		os.replace(tempPath, self._connectionFilePath)
