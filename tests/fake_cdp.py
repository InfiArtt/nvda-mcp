"""A fake Chromium browser for the DevTools tests.

It speaks enough of the DevTools protocol over a real WebSocket on 127.0.0.1 to exercise cdp.py and
dom_inspection.py, and it enforces Blink's preconditions ("Document needs to be requested first", "DOM agent
needs to be enabled first"), so the client is held to the order of calls a real browser needs. Like Blink,
backend node ids are shared by every page of the browser, while node ids belong to one session.
"""

import asyncio
import contextlib
import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request

from nvda_mcp import cdp

ELEMENT = 1
TEXT = 3
COMMENT = 8
DOCUMENT = 9
DOCUMENT_FRAGMENT = 11

BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
BROWSER_PID = 4242
RENDERER_PID = 5555


class FakeNode:
    def __init__(
        self,
        node_type: int,
        name: str,
        *,
        attributes: dict[str, str] | None = None,
        value: str = "",
        children: tuple["FakeNode", ...] | list["FakeNode"] = (),
        box: tuple[float, float, float, float] | None = None,
        ax: dict[str, str] | bool | None = None,
        listeners: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
        styles: dict[str, str] | None = None,
        template_content: "FakeNode | None" = None,
        shadow_roots: tuple["FakeNode", ...] | list["FakeNode"] = (),
        pseudo_elements: tuple["FakeNode", ...] | list["FakeNode"] = (),
        shadow_root_type: str | None = None,
        pseudo_type: str | None = None,
    ) -> None:
        self.node_type = node_type
        self.name = name
        self.attributes = dict(attributes or {})
        self.value = value
        self.children = list(children)
        self.box = box
        """(x, y, width, height) in CSS pixels of the document."""
        self.ax = ax
        """None: an ignored accessibility object; False: no accessibility object; a dict: role and name."""
        self.listeners = list(listeners)
        self.styles = dict(styles or {})
        self.template_content = template_content
        self.shadow_roots = list(shadow_roots)
        self.pseudo_elements = list(pseudo_elements)
        self.shadow_root_type = shadow_root_type
        """For a shadow root: "open", "closed" or "user-agent"."""
        self.pseudo_type = pseudo_type
        """For generated content: "before", "after", "marker"..."""
        self.parent: FakeNode | None = None
        self.backend_id = 0
        # Like Blink, a shadow root's and a pseudo-element's parent is their host element.
        for child in (*self.children, *self.shadow_roots, *self.pseudo_elements):
            child.parent = self

    def walk(self) -> Iterator["FakeNode"]:
        """The node and its descendants in the light DOM, as selectors see them."""
        yield self
        for child in self.children:
            yield from child.walk()

    def walk_all(self) -> Iterator["FakeNode"]:
        """Also the nodes in shadow trees and generated content (not template contents)."""
        yield self
        for child in (*self.pseudo_elements, *self.shadow_roots, *self.children):
            yield from child.walk_all()

    def find(self, **attributes: str) -> "FakeNode":
        for node in self.walk():
            if node.node_type == ELEMENT and all(node.attributes.get(k) == v for k, v in attributes.items()):
                return node
        raise LookupError(attributes)


def element(
    tag: str, attributes: dict[str, str] | None = None, *children: FakeNode, **options: Any
) -> FakeNode:
    return FakeNode(ELEMENT, tag, attributes=attributes, children=children, **options)


def text(value: str, **options: Any) -> FakeNode:
    options.setdefault("ax", False)
    return FakeNode(TEXT, "#text", value=value, **options)


def comment(value: str) -> FakeNode:
    return FakeNode(COMMENT, "#comment", value=value, ax=False)


def shadow_root(*children: FakeNode, mode: str = "open") -> FakeNode:
    return FakeNode(
        DOCUMENT_FRAGMENT, "#document-fragment", children=children, shadow_root_type=mode, ax=False
    )


def pseudo(kind: str = "before", **options: Any) -> FakeNode:
    return FakeNode(ELEMENT, f"::{kind}", pseudo_type=kind, **options)


def listener(
    event_type: str,
    handler: str = "function () {}",
    *,
    capture: bool = False,
    passive: bool = False,
    once: bool = False,
) -> dict[str, Any]:
    return {"type": event_type, "handler": handler, "useCapture": capture, "passive": passive, "once": once}


@dataclass
class FakePage:
    url: str
    title: str
    html: FakeNode
    type: str = "page"
    layout: dict[str, float] = field(
        default_factory=lambda: {"pageX": 0, "pageY": 0, "clientWidth": 1000, "clientHeight": 600}
    )
    target_id: str = ""
    document: FakeNode = field(init=False)

    def __post_init__(self) -> None:
        self.document = FakeNode(DOCUMENT, "#document", children=[self.html], ax=None)


class FakeError(Exception):
    def __init__(self, message: str, code: int = -32000) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Session:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.document_requested = False
        self.dom_enabled = False
        self.css_enabled = False
        self.ax_enabled = False
        self.node_ids: dict[int, int] = {}
        self.nodes: dict[int, FakeNode] = {}
        self.children_sent: set[int] = set()
        self.objects: dict[str, tuple[FakeNode, str | None]] = {}
        self._counter = itertools.count(1)

    def bind(self, node: FakeNode) -> int:
        if node.backend_id not in self.node_ids:
            node_id = next(self._counter)
            self.node_ids[node.backend_id] = node_id
            self.nodes[node_id] = node
        return self.node_ids[node.backend_id]

    def holds(self, node: FakeNode) -> bool:
        return any(found is node for found in self.page.document.walk_all())


def _parse_selector(selector: str) -> list[tuple[str | None, list[tuple[str, str, str | None]]]]:
    """A small part of CSS: compound selectors of tag, #id, .class, [attr] and [attr="value"], with commas."""
    invalid = FakeError(
        f"DOMException: Failed to execute 'querySelectorAll' on 'Element': '{selector}' is not a valid selector."
    )
    groups = []
    position = 0
    length = len(selector)

    def ident() -> str:
        nonlocal position
        start = position
        while position < length and (selector[position].isalnum() or selector[position] in "-_"):
            position += 1
        if start == position:
            raise invalid
        return selector[start:position]

    def css_string(quote: str) -> str:
        nonlocal position
        position += 1
        value = []
        while position < length and selector[position] != quote:
            char = selector[position]
            if char == "\\":
                position += 1
                hex_digits = ""
                while (
                    position < length
                    and len(hex_digits) < 6
                    and selector[position] in "0123456789abcdefABCDEF"
                ):
                    hex_digits += selector[position]
                    position += 1
                if hex_digits:
                    value.append(chr(int(hex_digits, 16)))
                    if position < length and selector[position] == " ":
                        position += 1
                    continue
                if position >= length:
                    raise invalid
                value.append(selector[position])
            else:
                value.append(char)
            position += 1
        if position >= length:
            raise invalid
        position += 1
        return "".join(value)

    while True:
        while position < length and selector[position] == " ":
            position += 1
        tag = None
        conditions: list[tuple[str, str, str | None]] = []
        if position < length and selector[position] == "*":
            position += 1
        elif position < length and selector[position].isalpha():
            tag = ident().lower()
        while position < length and selector[position] not in ", ":
            char = selector[position]
            if char == "#":
                position += 1
                conditions.append(("equals", "id", ident()))
            elif char == ".":
                position += 1
                conditions.append(("class", "class", ident()))
            elif char == "[":
                position += 1
                name = ident()
                if position < length and selector[position] == "=":
                    position += 1
                    if position < length and selector[position] in "\"'":
                        value = css_string(selector[position])
                    else:
                        value = ident()
                    conditions.append(("equals", name, value))
                else:
                    conditions.append(("has", name, None))
                if position >= length or selector[position] != "]":
                    raise invalid
                position += 1
            else:
                raise invalid
        if tag is None and not conditions and not selector[:position].rstrip().endswith("*"):
            raise invalid
        groups.append((tag, conditions))
        while position < length and selector[position] == " ":
            position += 1
        if position >= length:
            return groups
        if selector[position] != ",":
            # Combinators are beyond this fake.
            raise invalid
        position += 1


def _matches(node: FakeNode, groups: list[tuple[str | None, list[tuple[str, str, str | None]]]]) -> bool:
    if node.node_type != ELEMENT:
        return False
    for tag, conditions in groups:
        if tag is not None and node.name.lower() != tag:
            continue
        ok = True
        for kind, name, value in conditions:
            actual = node.attributes.get(name)
            if kind == "has":
                ok = actual is not None
            elif kind == "class":
                ok = value in (actual or "").split()
            else:
                ok = actual == value
            if not ok:
                break
        if ok:
            return True
    return False


class FakeBrowser:
    """A browser endpoint on 127.0.0.1:0.

    :param approval_delay: Seconds the handshake waits, as while the user answers "Allow remote debugging?".
    :param refuse: Answer the handshake with HTTP 403, as when the user chooses Cancel.
    :param json_version: Answer /json/version (browsers started with --remote-debugging-port do); otherwise 404.
    :param hang: Methods never answered.
    """

    def __init__(
        self,
        pages: list[FakePage],
        *,
        approval_delay: float = 0.0,
        refuse: bool = False,
        json_version: bool = False,
        hang: tuple[str, ...] = (),
    ) -> None:
        self.pages = pages
        self.approval_delay = approval_delay
        self.refuse = refuse
        self.json_version = json_version
        self.hang = set(hang)
        self.ws_path = "/devtools/browser/0b5c7f2e-fake-4d1e-9a3b-guid"
        self.port = 0
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.handshakes = 0
        self.handshake_requests: list[Request] = []
        self.open_connections = 0
        self.http_requests: list[str] = []
        self.sessions: dict[str, _Session] = {}
        self.layout_requests = 0
        self.hit_points: list[tuple[Any, Any]] = []
        self.failures: list[tuple[str, str, Callable[[dict[str, Any], _Session | None], bool] | None]] = []
        self._connections: set[ServerConnection] = set()
        self._closing = asyncio.Event()
        self._session_counter = itertools.count(1)
        self._object_counter = itertools.count(1)
        self._nodes_by_backend: dict[int, FakeNode] = {}
        backend_ids = itertools.count(1001)
        for index, page in enumerate(pages, 1):
            page.target_id = page.target_id or f"TARGET-{index:04d}"
            for node in page.document.walk_all():
                node.backend_id = next(backend_ids)
                self._nodes_by_backend[node.backend_id] = node
                if node.template_content is not None:
                    for inner in node.template_content.walk_all():
                        inner.backend_id = next(backend_ids)
                        self._nodes_by_backend[inner.backend_id] = inner

    @property
    def methods(self) -> list[str]:
        return [call[0] for call in self.calls]

    def calls_of(self, method: str) -> list[dict[str, Any]]:
        return [params for name, params, _session in self.calls if name == method]

    async def __aenter__(self) -> Self:
        self._server = await serve(
            self._handle,
            "127.0.0.1",
            0,
            process_request=self._process_request,
            open_timeout=None,
            ping_interval=None,
            max_size=None,
            compression=None,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._closing.set()
        self._server.close()
        await self._server.wait_closed()

    async def disconnect_all(self) -> None:
        """Closes every connection, as when the browser quits."""
        for connection in list(self._connections):
            await connection.close()

    def node(self, backend_id: int) -> FakeNode:
        return self._nodes_by_backend[backend_id]

    def fail(
        self,
        method: str,
        message: str = "Could not find node with given id",
        *,
        when: Callable[[dict[str, Any], "_Session | None"], bool] | None = None,
    ) -> None:
        """Answers method with an error from now on, or only the calls for which when(params, session) is true.

        The session is None for browser-level methods. This is how a page that changes, or a tab that closes,
        between two commands looks to the client.
        """
        self.failures.append((method, message, when))

    # The handshake ---------------------------------------------------------------------------------------------

    async def _process_request(self, connection: ServerConnection, request: Request) -> Any:
        if request.path.startswith("/json"):
            self.http_requests.append(request.path)
            if self.json_version and request.path == "/json/version":
                body = json.dumps(
                    {
                        "Browser": "Fake/1.0",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}{self.ws_path}",
                    }
                )
                response = connection.respond(200, body)
                del response.headers["Content-Type"]
                response.headers["Content-Type"] = "application/json"
                return response
            return connection.respond(404, "Not Found\n")
        self.handshakes += 1
        self.handshake_requests.append(request)
        if self.approval_delay:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._closing.wait(), self.approval_delay)
        if self.refuse or self._closing.is_set():
            return connection.respond(403, "Forbidden\n")
        if request.path not in (self.ws_path, cdp.DEFAULT_BROWSER_PATH):
            return connection.respond(404, "Not Found\n")
        return None

    async def _handle(self, connection: ServerConnection) -> None:
        self.open_connections += 1
        self._connections.add(connection)
        try:
            async for raw in connection:
                await self._answer(connection, json.loads(raw))
        except ConnectionClosed:
            pass
        finally:
            self.open_connections -= 1
            self._connections.discard(connection)

    async def _answer(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        method = message["method"]
        params = message.get("params") or {}
        session_id = message.get("sessionId")
        self.calls.append((method, params, session_id))
        if method in self.hang:
            return
        events: list[dict[str, Any]] = []
        try:
            reply: dict[str, Any] = {
                "id": message["id"],
                "result": self._dispatch(method, params, session_id, events),
            }
        except FakeError as error:
            reply = {"id": message["id"], "error": {"code": error.code, "message": error.message}}
        if session_id is not None:
            reply["sessionId"] = session_id
        for event in events:
            if session_id is not None:
                event["sessionId"] = session_id
            await connection.send(json.dumps(event))
        await connection.send(json.dumps(reply))

    # Commands ------------------------------------------------------------------------------------------------

    def _dispatch(
        self, method: str, params: dict[str, Any], session_id: str | None, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id) if session_id is not None else None
        if session_id is not None and session is None:
            raise FakeError("Session with given id not found.")
        for failing, message, when in self.failures:
            if failing == method and (when is None or when(params, session)):
                raise FakeError(message)
        if session is None:
            handler = getattr(self, "_browser_" + method.replace(".", "_"), None)
            if handler is None:
                raise FakeError(f"'{method}' wasn't found", -32601)
            return handler(params)
        handler = getattr(self, "_page_" + method.replace(".", "_"), None)
        if handler is None:
            raise FakeError(f"'{method}' wasn't found", -32601)
        return handler(session, params, events)

    def _target_info(self, page: FakePage) -> dict[str, Any]:
        return {
            "targetId": page.target_id,
            "type": page.type,
            "title": page.title,
            "url": page.url,
            "attached": False,
            "canAccessOpener": False,
            "browserContextId": "CONTEXT-1",
        }

    def _browser_Target_getTargets(self, params: dict[str, Any]) -> dict[str, Any]:
        infos = [self._target_info(page) for page in self.pages]
        # Targets that are not pages are never attached to, even with the same URL.
        if self.pages:
            infos.append(
                {"targetId": "WORKER-1", "type": "service_worker", "title": "sw", "url": self.pages[0].url}
            )
        return {"targetInfos": infos}

    def _browser_Target_attachToTarget(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("flatten") is not True:
            raise FakeError("Only flattened sessions are supported by this fake.")
        page = next((page for page in self.pages if page.target_id == params.get("targetId")), None)
        if page is None:
            raise FakeError("No target with given id found")
        session_id = f"SESSION-{next(self._session_counter)}"
        self.sessions[session_id] = _Session(page)
        return {"sessionId": session_id}

    def _browser_Target_detachFromTarget(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.sessions.pop(params.get("sessionId"), None) is None:
            raise FakeError("No session with given id")
        return {}

    def _node_json(
        self, session: _Session, node: FakeNode, depth: int, *, bind: bool, pierce: bool = False
    ) -> dict[str, Any]:
        is_element = node.node_type == ELEMENT and not node.pseudo_type
        data: dict[str, Any] = {
            "nodeId": session.bind(node) if bind else 0,
            "backendNodeId": node.backend_id,
            "nodeType": node.node_type,
            "nodeName": node.name.upper() if is_element else node.name,
            "localName": node.name if is_element else "",
            "nodeValue": node.value if node.node_type in (TEXT, COMMENT) else "",
        }
        if node.node_type == ELEMENT:
            data["attributes"] = [part for pair in node.attributes.items() for part in pair]
            data["childNodeCount"] = len(node.children)
        if node.pseudo_type:
            data["pseudoType"] = node.pseudo_type
        if node.node_type == DOCUMENT:
            data["documentURL"] = session.page.url
            data["childNodeCount"] = len(node.children)
        if node.node_type == DOCUMENT_FRAGMENT:
            data["childNodeCount"] = len(node.children)
            if node.shadow_root_type:
                data["shadowRootType"] = node.shadow_root_type
        # Like Blink: shadow roots and pseudo-elements always come with their host, shadow roots read as deep
        # as the host only when piercing.
        if node.shadow_roots:
            data["shadowRoots"] = [
                self._node_json(session, root, depth if pierce else 0, bind=bind, pierce=pierce)
                for root in node.shadow_roots
            ]
        if node.pseudo_elements:
            data["pseudoElements"] = [
                self._node_json(session, generated, 0, bind=bind, pierce=pierce)
                for generated in node.pseudo_elements
            ]
        if node.template_content is not None:
            data["templateContent"] = self._node_json(
                session, node.template_content, depth - 1, bind=bind, pierce=pierce
            )
        if depth != 0 and node.children:
            data["children"] = [
                self._node_json(session, child, depth - 1, bind=bind, pierce=pierce)
                for child in node.children
            ]
            if bind:
                session.children_sent.add(node.backend_id)
        return data

    def _push_path(self, session: _Session, node: FakeNode, events: list[dict[str, Any]]) -> int:
        path = []
        current = node.parent
        while current is not None:
            path.append(current)
            current = current.parent
        for ancestor in reversed(path):
            if ancestor.backend_id in session.children_sent:
                continue
            session.children_sent.add(ancestor.backend_id)
            events.append(
                {
                    "method": "DOM.setChildNodes",
                    "params": {
                        "parentId": session.bind(ancestor),
                        "nodes": [
                            self._node_json(session, child, 0, bind=True) for child in ancestor.children
                        ],
                    },
                }
            )
        return session.bind(node)

    def _need_document(self, session: _Session) -> None:
        if not session.document_requested:
            raise FakeError("Document needs to be requested first")

    def _bound(self, session: _Session, node_id: Any) -> FakeNode:
        node = session.nodes.get(node_id)
        if node is None:
            raise FakeError("Could not find node with given id")
        return node

    def _any_node(self, session: _Session, params: dict[str, Any]) -> FakeNode:
        if params.get("nodeId"):
            return self._bound(session, params["nodeId"])
        if params.get("backendNodeId"):
            node = self._nodes_by_backend.get(params["backendNodeId"])
            if node is None:
                raise FakeError("No node with given id found")
            return node
        if params.get("objectId"):
            found = session.objects.get(params["objectId"])
            if found is None:
                raise FakeError("Could not find object with given id")
            return found[0]
        raise FakeError("Either nodeId, backendNodeId or objectId must be specified")

    def _page_DOM_enable(self, session: _Session, params: dict[str, Any], events: list) -> dict[str, Any]:
        session.dom_enabled = True
        return {}

    def _page_DOM_disable(self, session: _Session, params: dict[str, Any], events: list) -> dict[str, Any]:
        session.dom_enabled = False
        session.document_requested = False
        return {}

    def _page_DOM_getDocument(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        session.dom_enabled = True
        session.document_requested = True
        session.children_sent.clear()
        depth = params.get("depth", 1)
        return {"root": self._node_json(session, session.page.document, depth, bind=True)}

    def _page_DOM_pushNodesByBackendIdsToFrontend(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        self._need_document(session)
        node_ids = []
        for backend_id in params.get("backendNodeIds") or []:
            node = self._nodes_by_backend.get(backend_id)
            # A node of another page in the same process is not pushed: its id is 0.
            node_ids.append(self._push_path(session, node, events) if node and session.holds(node) else 0)
        return {"nodeIds": node_ids}

    def _page_DOM_describeNode(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        node = self._any_node(session, params)
        depth = params.get("depth", 1)
        return {"node": self._node_json(session, node, depth, bind=False, pierce=bool(params.get("pierce")))}

    def _page_DOM_getAttributes(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        node = self._bound(session, params.get("nodeId"))
        return {"attributes": [part for pair in node.attributes.items() for part in pair]}

    def _query(self, session: _Session, params: dict[str, Any], events: list) -> list[int]:
        self._need_document(session)
        root = self._bound(session, params.get("nodeId"))
        groups = _parse_selector(str(params.get("selector") or ""))
        found = [node for node in root.walk() if node is not root and _matches(node, groups)]
        return [self._push_path(session, node, events) for node in found]

    def _page_DOM_querySelectorAll(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        return {"nodeIds": self._query(session, params, events)}

    def _page_DOM_querySelector(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        found = self._query(session, params, events)
        return {"nodeId": found[0] if found else 0}

    def _page_DOM_getNodeForLocation(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        if not session.dom_enabled:
            raise FakeError("DOM agent hasn't been enabled")
        x, y = params.get("x"), params.get("y")
        self.hit_points.append((x, y))
        if not isinstance(x, int) or not isinstance(y, int) or isinstance(x, bool):
            raise FakeError("Invalid parameters", -32602)
        ignore_none = params.get("ignorePointerEventsNone", False)

        def hit(node: FakeNode) -> FakeNode | None:
            found = None
            if node.box is not None and not (ignore_none and node.styles.get("pointer-events") == "none"):
                left, top, width, height = node.box
                if left <= x < left + width and top <= y < top + height:
                    found = node
            for child in node.children:
                deeper = hit(child)
                if deeper is not None:
                    found = deeper
            return found

        node = hit(session.page.document)
        if node is None:
            raise FakeError("No node found at given location")
        result: dict[str, Any] = {"backendNodeId": node.backend_id, "frameId": "FRAME-1"}
        if session.document_requested:
            result["nodeId"] = self._push_path(session, node, events)
        return result

    def _page_DOM_resolveNode(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        node = self._any_node(session, params)
        object_id = f"OBJECT-{next(self._object_counter)}"
        session.objects[object_id] = (node, params.get("objectGroup"))
        return {
            "object": {
                "type": "object",
                "subtype": "node",
                "className": "HTMLElement" if node.node_type == ELEMENT else "HTMLDocument",
                "description": node.name,
                "objectId": object_id,
            }
        }

    def _page_DOMDebugger_getEventListeners(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        found = session.objects.get(params.get("objectId"))
        if found is None:
            raise FakeError("Could not find object with given id")
        node, group = found
        listeners = []
        for item in node.listeners:
            entry = {
                "type": item["type"],
                "useCapture": item["useCapture"],
                "passive": item["passive"],
                "once": item["once"],
                "scriptId": "17",
                "lineNumber": 3,
                "columnNumber": 9,
                "backendNodeId": node.backend_id,
            }
            # Blink includes the handler only when the object was resolved into an object group.
            if group:
                entry["handler"] = {
                    "type": "function",
                    "className": "Function",
                    "description": item["handler"],
                }
            listeners.append(entry)
        return {"listeners": listeners}

    def _page_Runtime_releaseObjectGroup(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        group = params.get("objectGroup")
        session.objects = {key: value for key, value in session.objects.items() if value[1] != group}
        return {}

    def _page_CSS_enable(self, session: _Session, params: dict[str, Any], events: list) -> dict[str, Any]:
        if not session.dom_enabled:
            raise FakeError("DOM agent needs to be enabled first.")
        session.css_enabled = True
        return {}

    def _page_CSS_disable(self, session: _Session, params: dict[str, Any], events: list) -> dict[str, Any]:
        session.css_enabled = False
        return {}

    def _page_CSS_getComputedStyleForNode(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        if not session.css_enabled:
            raise FakeError("CSS agent was not enabled")
        node = self._bound(session, params.get("nodeId"))
        styles = {
            "display": "block",
            "visibility": "visible",
            "opacity": "1",
            "margin-top": "0px",
            "-webkit-locale": "auto",
            "color": "rgb(0, 0, 0)",
        }
        styles.update(node.styles)
        return {"computedStyle": [{"name": name, "value": value} for name, value in styles.items()]}

    def _page_Accessibility_enable(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        session.ax_enabled = True
        return {}

    def _page_Accessibility_disable(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        session.ax_enabled = False
        return {}

    def _ax_json(self, session: _Session, node: FakeNode) -> dict[str, Any]:
        if node.node_type == DOCUMENT:
            role, name, ignored = "RootWebArea", session.page.title, False
        elif isinstance(node.ax, dict):
            role, name, ignored = node.ax.get("role", "generic"), node.ax.get("name", ""), False
        else:
            role, name, ignored = "generic", "", True
        return {
            "nodeId": f"AX-{node.backend_id}",
            "ignored": ignored,
            "role": {"type": "role", "value": role},
            "name": {"type": "computedString", "value": name},
            "backendDOMNodeId": node.backend_id,
        }

    def _page_Accessibility_getAXNodeAndAncestors(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        if not session.ax_enabled:
            raise FakeError("Accessibility agent is not enabled.")
        node = self._any_node(session, params)
        if node.ax is False:
            # Blink's placeholder for a DOM node without an accessibility object.
            return {
                "nodes": [
                    {
                        "nodeId": "0",
                        "ignored": True,
                        "ignoredReasons": [
                            {"name": "notRendered", "value": {"type": "boolean", "value": True}}
                        ],
                        "role": {"type": "role", "value": "none"},
                        "backendDOMNodeId": node.backend_id,
                    }
                ]
            }
        chain = []
        current: FakeNode | None = node
        while current is not None:
            if current.ax is not False:
                chain.append(self._ax_json(session, current))
            current = current.parent
        return {"nodes": chain}

    def _page_Page_getLayoutMetrics(
        self, session: _Session, params: dict[str, Any], events: list
    ) -> dict[str, Any]:
        self.layout_requests += 1
        layout = session.page.layout
        viewport = {
            "pageX": layout["pageX"],
            "pageY": layout["pageY"],
            "clientWidth": layout["clientWidth"],
            "clientHeight": layout["clientHeight"],
        }
        return {
            "layoutViewport": {key: int(value) for key, value in viewport.items()},
            "cssLayoutViewport": viewport,
            "cssVisualViewport": {
                **viewport,
                "offsetX": 0,
                "offsetY": 0,
                "scale": 1,
                "zoom": 1,
            },
            "cssContentSize": {"x": 0, "y": 0, "width": layout["clientWidth"], "height": 5000},
        }


# Helpers for the tests ---------------------------------------------------------------------------------------


def write_active_port(
    local_app_data: Path, port: int, ws_path: str | None, folder: str = r"BraveSoftware\Brave-Browser"
) -> Path:
    path = Path(local_app_data) / folder / "User Data" / "DevToolsActivePort"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{port}\n{ws_path}\n" if ws_path else f"{port}\n", encoding="utf-8")
    return path


def browser_listeners(browser: FakeBrowser, pid: int = BROWSER_PID) -> Any:
    """A listener table in which the fake browser's port belongs to pid."""
    return lambda port: [("127.0.0.1", pid)] if port == browser.port else []


def brave_paths(path: str = BRAVE_PATH) -> Any:
    return lambda pid: path if pid in (BROWSER_PID, RENDERER_PID) else r"C:\Windows\notepad.exe"


def make_pool(browser: FakeBrowser, local_app_data: Path, **options: Any) -> cdp.ConnectionPool:
    """A pool that finds the fake browser as Brave's, with its DevToolsActivePort file in local_app_data."""
    write_active_port(local_app_data, browser.port, browser.ws_path)
    discovery = cdp.Discovery(
        local_app_data=local_app_data, listeners=browser_listeners(browser), process_path=brave_paths()
    )
    return cdp.ConnectionPool(discovery, **options)


def brave_info(**overrides: Any) -> dict[str, Any]:
    """webElementInfo for a control in Brave, rendered by a renderer process."""
    info: dict[str, Any] = {
        "name": "",
        "role": "button",
        "appName": "brave",
        "processId": RENDERER_PID,
        "appPath": BRAVE_PATH,
        "location": None,
        "attributes": {},
        "documentUrl": "https://web.whatsapp.com/",
        "documentTitle": "WhatsApp",
        "documentLocation": None,
        "domNodeId": None,
        "domNodeIdFromParent": False,
    }
    info.update(overrides)
    return info
