"""A small, read-only Chrome DevTools Protocol client for looking at the page behind an NVDA control.

Chromium-based browsers (Brave, Google Chrome, Microsoft Edge, Chromium) let local programs inspect their pages
through the DevTools protocol once the user turns on "Allow remote debugging for this browser instance" at
chrome://inspect/#remote-debugging (brave://inspect/#remote-debugging in Brave). The browser then asks the user
before it accepts each new connection.

This module finds the browser's debugging port, makes sure the port really belongs to that browser, keeps one
connection per browser open between tool calls (so the user is asked once, not on every call), and sends only
commands that read the page.
"""

import asyncio
import contextlib
import ctypes
import itertools
import json
import os
import socket
import sys
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus, InvalidURI

IDLE_SECONDS = 60.0
COMMAND_TIMEOUT_SECONDS = 10.0
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 120.0
# Describing a large subtree can make a long message.
MAX_MESSAGE_BYTES = 64 * 2**20
DEFAULT_BROWSER_PATH = "/devtools/browser"

# Only commands that read the page. send() refuses everything else before writing anything.
ALLOWED_METHODS = frozenset(
    {
        "Target.getTargets",
        "Target.attachToTarget",
        "Target.detachFromTarget",
        "DOM.enable",
        "DOM.disable",
        "DOM.getDocument",
        "DOM.describeNode",
        "DOM.getAttributes",
        "DOM.querySelector",
        "DOM.querySelectorAll",
        "DOM.pushNodesByBackendIdsToFrontend",
        "DOM.getBoxModel",
        "DOM.getNodeForLocation",
        "DOM.resolveNode",
        "CSS.enable",
        "CSS.disable",
        "CSS.getComputedStyleForNode",
        "DOMDebugger.getEventListeners",
        "Runtime.releaseObjectGroup",
        "Accessibility.enable",
        "Accessibility.disable",
        "Accessibility.getAXNodeAndAncestors",
        "Accessibility.queryAXTree",
        "Page.getLayoutMetrics",
    }
)

PAGE_TARGET_TYPES = ("page", "iframe")

Announce = Callable[[str], Awaitable[Any]]


class BrowserInspectionError(Exception):
    """Looking at the page failed. The message says what happened and what to do, for a screen reader user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CdpCommandError(Exception):
    """The browser answered a command with an error, such as "No node with given id found"."""

    def __init__(self, method: str, code: Any, message: str) -> None:
        super().__init__(f"{method}: {message}")
        self.method = method
        self.code = code
        self.message = message


class MethodNotAllowedError(Exception):
    """A command outside ALLOWED_METHODS was about to be sent. It was not sent."""


# Browsers --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Browser:
    name: str
    """What to call the browser in messages, such as "Brave" or "Google Chrome"."""
    user_data_dir: Path | None
    inspect_url: str
    """Where the user turns remote debugging on."""
    google_chrome: bool = False


BRAVE_INSPECT_URL = "brave://inspect/#remote-debugging"
CHROME_INSPECT_URL = "chrome://inspect/#remote-debugging"

# (vendor folder or None, channel folder, name, folder under %LOCALAPPDATA%). The executable lives in
# <...>\<vendor>\<channel>\Application\, under Program Files or under %LOCALAPPDATA% for per-user installs.
_KNOWN_BROWSERS = (
    ("bravesoftware", "brave-browser", "Brave", r"BraveSoftware\Brave-Browser"),
    ("bravesoftware", "brave-browser-beta", "Brave Beta", r"BraveSoftware\Brave-Browser-Beta"),
    ("bravesoftware", "brave-browser-nightly", "Brave Nightly", r"BraveSoftware\Brave-Browser-Nightly"),
    ("google", "chrome", "Google Chrome", r"Google\Chrome"),
    ("google", "chrome beta", "Google Chrome Beta", r"Google\Chrome Beta"),
    ("google", "chrome dev", "Google Chrome Dev", r"Google\Chrome Dev"),
    ("google", "chrome sxs", "Google Chrome Canary", r"Google\Chrome SxS"),
    ("microsoft", "edge", "Microsoft Edge", r"Microsoft\Edge"),
    ("microsoft", "edge beta", "Microsoft Edge Beta", r"Microsoft\Edge Beta"),
    ("microsoft", "edge dev", "Microsoft Edge Dev", r"Microsoft\Edge Dev"),
    ("microsoft", "edge sxs", "Microsoft Edge Canary", r"Microsoft\Edge SxS"),
    (None, "chromium", "Chromium", "Chromium"),
)


def browser_for_app_path(app_path: str | None, local_app_data: str | Path | None = None) -> Browser | None:
    """The known Chromium-based browser whose executable is app_path, with its user data directory."""
    if not app_path:
        return None
    parts = [part.lower() for part in PureWindowsPath(app_path).parts]
    if "application" not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index("application")
    channel = parts[index - 1] if index >= 1 else ""
    vendor = parts[index - 2] if index >= 2 else ""
    base = Path(local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA", ""))
    for known_vendor, known_channel, name, folder in _KNOWN_BROWSERS:
        if channel == known_channel and (known_vendor is None or vendor == known_vendor):
            return Browser(
                name=name,
                user_data_dir=base / folder / "User Data",
                inspect_url=BRAVE_INSPECT_URL if known_vendor == "bravesoftware" else CHROME_INSPECT_URL,
                google_chrome=known_vendor == "google",
            )
    return None


def read_active_port(path: Path) -> tuple[int, str | None] | None:
    """The port and browser WebSocket path in a DevToolsActivePort file, or None if it is missing or unusable.

    The file is only a hint: it outlives the browser, so the port must still be checked.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0].strip())
    except ValueError:
        return None
    if not 0 < port < 65536:
        return None
    ws_path = lines[1].strip() if len(lines) > 1 else ""
    if not _is_browser_path(ws_path):
        ws_path = None
    return port, ws_path


def _is_browser_path(path: str) -> bool:
    return path.startswith(DEFAULT_BROWSER_PATH) and all(char.isalnum() or char in "/-_" for char in path)


def normalise_path(path: str | None) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


# Who owns a port --------------------------------------------------------------------------------------------

_TCP_TABLE_OWNER_PID_LISTENER = 3
_ERROR_INSUFFICIENT_BUFFER = 122
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# Listeners that receive connections made to loopback: bound to loopback itself or to every address.
_LOOPBACK_OR_ANY = frozenset({"127.0.0.1", "0.0.0.0", "::1", "::"})


class _TcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("localAddr", wintypes.DWORD),
        ("localPort", wintypes.DWORD),
        ("remoteAddr", wintypes.DWORD),
        ("remotePort", wintypes.DWORD),
        ("owningPid", wintypes.DWORD),
    ]


class _Tcp6RowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("localAddr", ctypes.c_ubyte * 16),
        ("localScopeId", wintypes.DWORD),
        ("localPort", wintypes.DWORD),
        ("remoteAddr", ctypes.c_ubyte * 16),
        ("remoteScopeId", wintypes.DWORD),
        ("remotePort", wintypes.DWORD),
        ("state", wintypes.DWORD),
        ("owningPid", wintypes.DWORD),
    ]


def _tcp_listeners(family: int) -> list[tuple[str, int, int]]:
    """(local address, port, owning process id) of every TCP listener of one address family."""
    iphlpapi = ctypes.WinDLL("iphlpapi")
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    buffer = ctypes.create_string_buffer(4)
    for _ in range(8):
        result = get_table(buffer, ctypes.byref(size), False, family, _TCP_TABLE_OWNER_PID_LISTENER, 0)
        if result == 0:
            break
        if result != _ERROR_INSUFFICIENT_BUFFER:
            return []
        # The table can grow between calls; leave room.
        buffer = ctypes.create_string_buffer(size.value + 1024)
    else:
        return []
    row_type = _TcpRowOwnerPid if family == socket.AF_INET else _Tcp6RowOwnerPid
    count = wintypes.DWORD.from_buffer(buffer).value
    offset = ctypes.sizeof(wintypes.DWORD)
    if offset + count * ctypes.sizeof(row_type) > len(buffer):
        return []
    rows = (row_type * count).from_buffer(buffer, offset)
    listeners = []
    for row in rows:
        if family == socket.AF_INET:
            address = socket.inet_ntoa(int(row.localAddr).to_bytes(4, "little"))
        else:
            address = socket.inet_ntop(socket.AF_INET6, bytes(row.localAddr))
        port = socket.ntohs(row.localPort & 0xFFFF)
        listeners.append((address, port, int(row.owningPid)))
    return listeners


def loopback_listeners(port: int) -> list[tuple[str, int]]:
    """(local address, owning process id) of the TCP listeners on port that loopback connections can reach."""
    if sys.platform != "win32":
        return []
    found = []
    for family in (socket.AF_INET, socket.AF_INET6):
        for address, local_port, pid in _tcp_listeners(family):
            if local_port == port and address in _LOOPBACK_OR_ANY:
                found.append((address, pid))
    return found


def process_image_path(pid: int) -> str | None:
    """The full path of a process's executable, or None if it cannot be read."""
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


# Messages ---------------------------------------------------------------------------------------------------


def _turn_on_steps(browser: Browser) -> str:
    steps = (
        f"To turn it on: in {browser.name}, open a new tab with Control+T, type {browser.inspect_url} "
        'in the address bar and press Enter, then check "Allow remote debugging for this browser instance".'
    )
    if browser.google_chrome:
        steps += (
            " If Google Chrome was started with --remote-debugging-port, for example from a shortcut, "
            "remove that flag and restart Chrome: Chrome ignores it for your usual profile, and while it is "
            "there this setting does not work."
        )
    return steps


def connecting_message(browser: Browser) -> str:
    return (
        f"NVDA MCP is connecting to {browser.name}. "
        f"{browser.name} will ask whether to allow remote debugging: choose Allow."
    )


def debugging_off(browser: Browser, detail: str = "") -> BrowserInspectionError:
    return BrowserInspectionError(
        "debuggingOff",
        f"Remote debugging is not turned on in {browser.name}, so NVDA MCP cannot look at the page's HTML. "
        f"{detail}{_turn_on_steps(browser)} Then ask again: {browser.name} will ask whether to allow "
        "the connection; choose Allow.",
    )


def approval_timed_out(browser: Browser, seconds: float) -> BrowserInspectionError:
    return BrowserInspectionError(
        "approvalTimedOut",
        f'{browser.name}\'s "Allow remote debugging?" dialog was not answered within {seconds:g} seconds, '
        "so NVDA MCP stopped waiting and will not try again by itself. That dialog may still be open, and "
        "answering it now does nothing: choose Cancel in it, and in any older ones left from earlier attempts. "
        "When you are ready, ask again. When the new dialog appears, Cancel has focus: press Tab to move to "
        "Allow, then press Space.",
    )


def refused(browser: Browser, status: int | None = 403) -> BrowserInspectionError:
    if status == 403:
        reason = (
            f'{browser.name} refused the connection (HTTP 403): Cancel or "Turn off in settings" was chosen in '
            f'its "Allow remote debugging?" dialog, or {browser.name} does not accept connections from other '
            "programs."
        )
    elif status:
        reason = f"{browser.name} did not accept the connection (HTTP {status})."
    else:
        reason = f"{browser.name} did not complete the connection."
    return BrowserInspectionError(
        "refused",
        f"{reason} NVDA MCP will not try again by itself. To allow it, ask again and choose Allow when the "
        "dialog appears (Cancel has focus: press Tab to move to Allow). If remote debugging was turned off, "
        f"turn it on again first. {_turn_on_steps(browser)}",
    )


def port_not_owned(browser: Browser, port: int, given: bool) -> BrowserInspectionError:
    message = (
        f"Port {port} does not belong to {browser.name}, so NVDA MCP did not connect to it: another program "
        "is listening there, and it could pretend to be the browser."
    )
    if given:
        message += (
            " Check the port number you gave, or leave it out so NVDA MCP finds the browser's port by itself."
        )
    else:
        message += (
            f" {browser.name}'s note of its debugging port is probably left over from an earlier session. "
            f"Restart {browser.name}, or turn remote debugging off and on again at {browser.inspect_url}."
        )
    return BrowserInspectionError("portNotOwned", message)


def no_page(browser: Browser, document_url: str | None) -> BrowserInspectionError:
    shown = f" ({short_url(document_url)})" if document_url else ""
    return BrowserInspectionError(
        "noPage",
        f"{browser.name} has no tab showing the page NVDA is reading{shown}. Make sure the page is open in "
        f"{browser.name} and has finished loading, move NVDA to it, then try again.",
    )


def browser_gone(browser: Browser) -> BrowserInspectionError:
    return BrowserInspectionError(
        "browserGone",
        f"The connection to {browser.name} closed: {browser.name} may have been closed or restarted, or remote "
        f"debugging was turned off. Ask again to reconnect; {browser.name} will ask whether to allow it.",
    )


def browser_timed_out(browser: Browser, method: str, seconds: float) -> BrowserInspectionError:
    return BrowserInspectionError(
        "browserTimedOut",
        f"{browser.name} did not answer within {seconds:g} seconds ({method}). The page may be busy; "
        "try again in a moment.",
    )


def unsupported_browser(app_name: str | None) -> BrowserInspectionError:
    which = f"{app_name} is" if app_name else "this program is"
    return BrowserInspectionError(
        "unsupportedBrowser",
        "NVDA MCP can look at the HTML only in Brave, Google Chrome, Microsoft Edge and Chromium, and could not "
        f"tell which of them {which} from where it is installed. If it is a Chromium-based browser with remote "
        "debugging turned on, give its debugging port.",
    )


def short_url(url: str, limit: int = 100) -> str:
    """A URL without its query and fragment, which can hold tokens, cut to limit characters."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url[:limit]
    shown = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    if parts.query:
        shown += "?…"
    return shown if len(shown) <= limit else shown[: limit - 1] + "…"


def _url_key(url: str | None) -> tuple[str, str, int | None, str] | None:
    if not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    return parts.scheme.lower(), (parts.hostname or "").lower(), port, parts.path or "/"


def matching_targets(targets: list[dict[str, Any]], document_url: str | None) -> list[dict[str, Any]]:
    """The page and frame targets showing document_url: the same URL, else the same scheme, host and path."""
    pages = [target for target in targets if target.get("type") in PAGE_TARGET_TYPES]
    exact = [target for target in pages if document_url and target.get("url") == document_url]
    if exact:
        return exact
    key = _url_key(document_url)
    if key is None:
        return []
    return [target for target in pages if _url_key(target.get("url")) == key]


# Finding the browser's endpoint -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Endpoint:
    browser: Browser
    host: str
    port: int
    path: str
    executable: str
    """The browser's executable, normalised with normalise_path."""

    @property
    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}{self.path}"


class Discovery:
    """Finds a browser's debugging port and checks that the browser owns it.

    :param local_app_data: Where browsers keep their user data; %LOCALAPPDATA% when None.
    :param listeners: port -> [(address, process id)] of loopback listeners; replaced in tests.
    :param process_path: process id -> executable path; replaced in tests.
    """

    def __init__(
        self,
        *,
        local_app_data: str | Path | None = None,
        listeners: Callable[[int], list[tuple[str, int]]] | None = None,
        process_path: Callable[[int], str | None] | None = None,
    ) -> None:
        self.local_app_data = local_app_data
        self.listeners = listeners or loopback_listeners
        self.process_path = process_path or process_image_path

    def browser(self, info: dict[str, Any], port: int | None) -> Browser:
        browser = browser_for_app_path(info.get("appPath"), self.local_app_data)
        if browser is not None:
            return browser
        if port is None:
            raise unsupported_browser(info.get("appName"))
        name = str(info.get("appName") or "the browser")
        return Browser(name=name[:1].upper() + name[1:], user_data_dir=None, inspect_url=CHROME_INSPECT_URL)

    def active_port(self, browser: Browser) -> tuple[int, str | None] | None:
        if browser.user_data_dir is None:
            return None
        return read_active_port(browser.user_data_dir / "DevToolsActivePort")

    def port_hint(self, info: dict[str, Any], port: int | None) -> int | None:
        """The port to look for an open connection on, without checking anything; None if unknown."""
        if port is not None:
            return port
        browser = browser_for_app_path(info.get("appPath"), self.local_app_data)
        active = self.active_port(browser) if browser else None
        return active[0] if active else None

    def check_owner(self, browser: Browser, info: dict[str, Any], port: int, given: bool) -> str:
        """The host to connect to, after checking that every loopback listener on port is the browser."""
        listeners = self.listeners(port)
        if not listeners:
            if given:
                raise debugging_off(browser, f"Nothing is listening on port {port}. ")
            raise debugging_off(
                browser,
                f"(Its note of the debugging port names port {port}, but nothing is listening there: "
                "the note is left over from an earlier session.) ",
            )
        expected = normalise_path(info.get("appPath"))
        process_id = info.get("processId")
        for _address, owner in listeners:
            if owner == process_id:
                continue
            # Browsers listen from their main process; NVDA's control may belong to a renderer process.
            path = self.process_path(owner)
            if not (expected and path and normalise_path(path) == expected):
                raise port_not_owned(browser, port, given)
        return "127.0.0.1" if any("." in address for address, _owner in listeners) else "::1"

    async def locate(self, info: dict[str, Any], port: int | None) -> Endpoint:
        browser = self.browser(info, port)
        active = self.active_port(browser)
        if port is None:
            if active is None:
                raise debugging_off(browser)
            chosen, path = active
        else:
            chosen = port
            path = active[1] if active and active[0] == port else None
        host = self.check_owner(browser, info, chosen, given=port is not None)
        if path is None and port is not None:
            path = await _browser_path_from_version(host, chosen)
        return Endpoint(
            browser=browser,
            host=host,
            port=chosen,
            path=path or DEFAULT_BROWSER_PATH,
            executable=normalise_path(info.get("appPath")),
        )


async def _browser_path_from_version(host: str, port: int) -> str | None:
    """The browser WebSocket path from /json/version, which answers 404 when debugging was turned on in the UI."""
    shown_host = f"[{host}]" if ":" in host else host
    try:
        # Never through a proxy: this is a loopback address.
        async with httpx.AsyncClient(trust_env=False, timeout=3.0) as client:
            response = await client.get(f"http://{shown_host}:{port}/json/version")
        if response.status_code != 200:
            return None
        url = response.json().get("webSocketDebuggerUrl") or ""
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    path = urllib.parse.urlsplit(url).path
    return path if _is_browser_path(path) else None


# The connection ---------------------------------------------------------------------------------------------


class PageSession:
    """Commands to one page or frame, through the browser connection (a flattened DevTools session)."""

    def __init__(self, connection: "CdpConnection", session_id: str, target: dict[str, Any]) -> None:
        self.connection = connection
        self.session_id = session_id
        self.url = str(target.get("url") or "")
        self.title = str(target.get("title") or "")

    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.connection.send(method, params, session_id=self.session_id)

    def take_child_nodes(self) -> list[dict[str, Any]]:
        """The DOM.setChildNodes events received for this session since the last call."""
        events = self.connection.child_node_events.get(self.session_id)
        if not events:
            return []
        taken = list(events)
        events.clear()
        return taken


class CdpConnection:
    """One browser-level WebSocket. A reader task matches replies to commands by id."""

    def __init__(
        self,
        websocket: ClientConnection,
        endpoint: Endpoint,
        *,
        command_timeout: float = COMMAND_TIMEOUT_SECONDS,
        idle_seconds: float = IDLE_SECONDS,
        on_closed: Callable[["CdpConnection"], None] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.command_timeout = command_timeout
        self.idle_seconds = idle_seconds
        self.loop = asyncio.get_running_loop()
        self.closed = False
        self.users = 0
        self.child_node_events: dict[str, list[dict[str, Any]]] = {}
        self._websocket = websocket
        self._on_closed = on_closed
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[asyncio.Future, str | None]] = {}
        self._idle_handle: asyncio.TimerHandle | None = None
        self._close_task: asyncio.Task | None = None
        self._reader = self.loop.create_task(self._read())
        # Closes even if every call that wanted it was cancelled while the user was answering the dialog.
        self._schedule_idle_close()

    @property
    def browser(self) -> Browser:
        return self.endpoint.browser

    async def send(
        self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None
    ) -> dict[str, Any]:
        if method not in ALLOWED_METHODS:
            raise MethodNotAllowedError(f"{method} is not allowed: NVDA MCP only reads pages.")
        if self.closed:
            raise browser_gone(self.browser)
        message_id = next(self._ids)
        message: dict[str, Any] = {"id": message_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        future = self.loop.create_future()
        self._pending[message_id] = (future, session_id)
        try:
            await self._websocket.send(json.dumps(message))
            reply = await asyncio.wait_for(future, self.command_timeout)
        except TimeoutError:
            raise browser_timed_out(self.browser, method, self.command_timeout) from None
        except ConnectionClosed:
            raise browser_gone(self.browser) from None
        finally:
            self._pending.pop(message_id, None)
        if "error" in reply:
            error = reply["error"] or {}
            raise CdpCommandError(method, error.get("code"), str(error.get("message", "")))
        return reply.get("result") or {}

    async def page_targets(self, document_url: str | None) -> list[dict[str, Any]]:
        result = await self.send("Target.getTargets")
        return matching_targets(result.get("targetInfos") or [], document_url)

    @contextlib.asynccontextmanager
    async def attach(self, target: dict[str, Any]) -> AsyncIterator[PageSession]:
        if target.get("type") not in PAGE_TARGET_TYPES:
            raise ValueError("Only pages and frames can be inspected.")
        result = await self.send("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})
        session_id = result["sessionId"]
        self.child_node_events[session_id] = []
        try:
            yield PageSession(self, session_id, target)
        finally:
            self.child_node_events.pop(session_id, None)
            if not self.closed:
                with contextlib.suppress(BrowserInspectionError, CdpCommandError):
                    await self.send("Target.detachFromTarget", {"sessionId": session_id})

    def acquire(self) -> None:
        self.users += 1
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def release(self) -> None:
        self.users = max(0, self.users - 1)
        if self.users == 0:
            self._schedule_idle_close()

    def _schedule_idle_close(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
        self._idle_handle = (
            None if self.closed else self.loop.call_later(self.idle_seconds, self._idle_expired)
        )

    def _idle_expired(self) -> None:
        self._idle_handle = None
        if self.users == 0 and not self.closed:
            self._close_task = self.loop.create_task(self.close())

    async def close(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None
        with contextlib.suppress(ConnectionClosed, OSError):
            await self._websocket.close()
        # The reader ends once the socket has closed.
        await asyncio.wait({self._reader}, timeout=5)
        if not self._reader.done():
            self._reader.cancel()
        self._mark_closed()

    def abandon(self) -> None:
        """Forget a connection whose event loop has ended, as when the server's loop is replaced."""
        self.closed = True
        self._pending.clear()

    async def _read(self) -> None:
        try:
            with contextlib.suppress(ConnectionClosed):
                async for raw in self._websocket:
                    self._dispatch(raw)
        finally:
            self._mark_closed()

    def _dispatch(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        if "id" in message:
            pending = self._pending.get(message["id"])
            if pending and not pending[0].done():
                pending[0].set_result(message)
            return
        method = message.get("method")
        params = message.get("params") or {}
        if method == "DOM.setChildNodes":
            events = self.child_node_events.get(message.get("sessionId"))
            if events is not None:
                events.append(params)
        elif method == "Target.detachedFromTarget":
            session_id = params.get("sessionId")
            gone = BrowserInspectionError(
                "noPage",
                f"The tab closed or stopped being inspectable while NVDA MCP was reading it. Try again "
                f"once the page is open in {self.browser.name}.",
            )
            for future, pending_session in list(self._pending.values()):
                if pending_session == session_id and not future.done():
                    future.set_exception(gone)

    def _mark_closed(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None
        already = self.closed
        self.closed = True
        for future, _session in list(self._pending.values()):
            if not future.done():
                future.set_exception(browser_gone(self.browser))
        if not already and self._on_closed is not None:
            self._on_closed(self)


class ConnectionPool:
    """One connection per browser, reused across tool calls and closed after IDLE_SECONDS unused."""

    def __init__(
        self,
        discovery: Discovery | None = None,
        *,
        idle_seconds: float = IDLE_SECONDS,
        command_timeout: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self.discovery = discovery or Discovery()
        self.idle_seconds = idle_seconds
        self.command_timeout = command_timeout
        self._connections: dict[tuple[int, str], CdpConnection] = {}
        self._opening: dict[tuple[int, str], asyncio.Task] = {}

    def _usable(self, connection: CdpConnection) -> bool:
        if connection.closed:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return not connection.loop.is_closed()
        return connection.loop is loop

    def find(self, info: dict[str, Any], port: int | None = None) -> CdpConnection | None:
        """The open connection to the browser NVDA's control belongs to, if there is one."""
        executable = normalise_path(info.get("appPath"))
        hint = self.discovery.port_hint(info, port)
        if hint is not None:
            connection = self._connections.get((hint, executable))
            return connection if connection is not None and self._usable(connection) else None
        candidates = [
            connection
            for (_port, path), connection in self._connections.items()
            if path == executable and self._usable(connection)
        ]
        return candidates[0] if len(candidates) == 1 else None

    def is_connected(self, info: dict[str, Any], port: int | None = None) -> bool:
        return self.find(info, port) is not None

    @contextlib.asynccontextmanager
    async def browser(
        self,
        info: dict[str, Any],
        *,
        port: int | None = None,
        approval_timeout: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS,
        announce: Announce | None = None,
    ) -> AsyncIterator[CdpConnection]:
        connection = self.find(info, port)
        if connection is None:
            connection = await self._open(info, port, approval_timeout, announce)
        connection.acquire()
        try:
            yield connection
        finally:
            connection.release()

    async def _open(
        self, info: dict[str, Any], port: int | None, approval_timeout: float, announce: Announce | None
    ) -> CdpConnection:
        endpoint = await self.discovery.locate(info, port)
        key = (endpoint.port, endpoint.executable)
        existing = self._connections.get(key)
        if existing is not None and self._usable(existing):
            return existing
        task = self._opening.get(key)
        if task is None:
            # Calls made while the user is still answering the browser's dialog wait for the same answer:
            # a second connection would open a second dialog.
            task = asyncio.ensure_future(self._connect(endpoint, approval_timeout, announce))
            self._opening[key] = task
            task.add_done_callback(lambda done: self._opening_done(key, done))
        return await asyncio.shield(task)

    def _opening_done(self, key: tuple[int, str], task: asyncio.Task) -> None:
        if self._opening.get(key) is task:
            del self._opening[key]
        if not task.cancelled():
            # Marks the exception as seen when every caller has gone away.
            task.exception()

    async def _connect(
        self, endpoint: Endpoint, approval_timeout: float, announce: Announce | None
    ) -> CdpConnection:
        browser = endpoint.browser
        if announce is not None:
            with contextlib.suppress(Exception):
                await announce(connecting_message(browser))
        try:
            # The browser holds the handshake open while it asks the user. Never through a proxy.
            websocket = await connect(
                endpoint.url,
                proxy=None,
                open_timeout=approval_timeout,
                max_size=MAX_MESSAGE_BYTES,
                compression=None,
            )
        except InvalidStatus as error:
            raise refused(browser, error.response.status_code) from None
        except TimeoutError:
            raise approval_timed_out(browser, approval_timeout) from None
        except (InvalidHandshake, InvalidURI):
            raise refused(browser, None) from None
        except OSError:
            raise browser_gone(browser) from None
        connection = CdpConnection(
            websocket,
            endpoint,
            command_timeout=self.command_timeout,
            idle_seconds=self.idle_seconds,
            on_closed=self._forget,
        )
        self._connections[(endpoint.port, endpoint.executable)] = connection
        return connection

    def _forget(self, connection: CdpConnection) -> None:
        for key, known in list(self._connections.items()):
            if known is connection:
                del self._connections[key]

    async def close_all(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in connections:
            if self._usable(connection):
                await connection.close()
            else:
                connection.abandon()


pool = ConnectionPool()
"""The connections the server uses. Tests replace it."""
