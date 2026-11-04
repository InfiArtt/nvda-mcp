"""The DevTools client: finding the browser's port, checking who owns it, and the connection itself.

Nothing here talks to a real browser: the browser is tests/fake_cdp.py on 127.0.0.1.
"""

import asyncio
import os
import socket
import sys
from pathlib import Path

import pytest
from fake_cdp import (
    BRAVE_PATH,
    BROWSER_PID,
    RENDERER_PID,
    FakeBrowser,
    FakePage,
    brave_info,
    brave_paths,
    browser_listeners,
    element,
    make_pool,
    text,
    write_active_port,
)

from nvda_mcp import cdp
from nvda_mcp.cdp import BrowserInspectionError, MethodNotAllowedError

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def simple_page(url="https://web.whatsapp.com/", title="WhatsApp"):
    return FakePage(url, title, element("html", {}, element("body", {}, element("p", {}, text("hello")))))


def secret_page():
    return FakePage(
        "https://bank.example/accounts?id=42", "Secret Bank statement", element("html", {}, element("body"))
    )


async def eventually(condition, timeout=5.0):
    """Waits until condition() is true, for things that happen after a delay."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "timed out waiting"
        await asyncio.sleep(0.02)


class Announcer:
    def __init__(self):
        self.said = []

    async def __call__(self, text):
        self.said.append(text)


# DevToolsActivePort ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("9333\n/devtools/browser/0b5c-7f2e\n", (9333, "/devtools/browser/0b5c-7f2e")),
        ("9333\r\n/devtools/browser/abc\r\n", (9333, "/devtools/browser/abc")),
        ("9333\n", (9333, None)),
        ("9333\n/json/version\n", (9333, None)),
        ("9333\n/devtools/browser/x?evil=1\n", (9333, None)),
        ("", None),
        ("\n\n", None),
        ("not a port\n/devtools/browser/abc\n", None),
        ("0\n/devtools/browser/abc\n", None),
        ("70000\n/devtools/browser/abc\n", None),
    ],
)
def test_reads_devtools_active_port(tmp_path, content, expected):
    path = tmp_path / "DevToolsActivePort"
    path.write_bytes(content.encode())
    assert cdp.read_active_port(path) == expected


def test_missing_devtools_active_port_is_none(tmp_path):
    assert cdp.read_active_port(tmp_path / "DevToolsActivePort") is None


@pytest.mark.parametrize(
    ("app_path", "name", "folder"),
    [
        (BRAVE_PATH, "Brave", r"BraveSoftware\Brave-Browser"),
        (
            r"C:\Users\ana\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
            "Brave",
            r"BraveSoftware\Brave-Browser",
        ),
        (
            r"C:\Program Files\BraveSoftware\Brave-Browser-Beta\Application\brave.exe",
            "Brave Beta",
            r"BraveSoftware\Brave-Browser-Beta",
        ),
        (
            r"C:\Program Files\BraveSoftware\Brave-Browser-Nightly\Application\brave.exe",
            "Brave Nightly",
            r"BraveSoftware\Brave-Browser-Nightly",
        ),
        (CHROME_PATH, "Google Chrome", r"Google\Chrome"),
        (
            r"C:\Program Files\Google\Chrome Beta\Application\chrome.exe",
            "Google Chrome Beta",
            r"Google\Chrome Beta",
        ),
        (
            r"C:\Program Files\Google\Chrome Dev\Application\chrome.exe",
            "Google Chrome Dev",
            r"Google\Chrome Dev",
        ),
        (
            r"C:\Users\ana\AppData\Local\Google\Chrome SxS\Application\chrome.exe",
            "Google Chrome Canary",
            r"Google\Chrome SxS",
        ),
        (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "Microsoft Edge",
            r"Microsoft\Edge",
        ),
        (
            r"C:\Program Files (x86)\Microsoft\Edge Beta\Application\msedge.exe",
            "Microsoft Edge Beta",
            r"Microsoft\Edge Beta",
        ),
        (
            r"C:\Program Files (x86)\Microsoft\Edge Dev\Application\msedge.exe",
            "Microsoft Edge Dev",
            r"Microsoft\Edge Dev",
        ),
        (
            r"C:\Users\ana\AppData\Local\Microsoft\Edge SxS\Application\msedge.exe",
            "Microsoft Edge Canary",
            r"Microsoft\Edge SxS",
        ),
        (r"C:\Users\ana\AppData\Local\Chromium\Application\chrome.exe", "Chromium", "Chromium"),
        (
            r"c:\program files\bravesoftware\brave-browser\application\BRAVE.EXE",
            "Brave",
            r"BraveSoftware\Brave-Browser",
        ),
    ],
)
def test_user_data_directory_of_each_browser(tmp_path, app_path, name, folder):
    browser = cdp.browser_for_app_path(app_path, tmp_path)
    assert browser.name == name
    assert browser.user_data_dir == tmp_path / folder / "User Data"
    assert browser.inspect_url == (
        "brave://inspect/#remote-debugging"
        if name.startswith("Brave")
        else "chrome://inspect/#remote-debugging"
    )
    assert browser.google_chrome == name.startswith("Google Chrome")


def test_local_app_data_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert cdp.browser_for_app_path(BRAVE_PATH).user_data_dir == (
        tmp_path / "BraveSoftware" / "Brave-Browser" / "User Data"
    )


@pytest.mark.parametrize(
    "app_path",
    [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
        r"C:\Tools\brave.exe",
        "",
        None,
    ],
)
def test_unknown_browsers_have_no_directory(app_path):
    assert cdp.browser_for_app_path(app_path, "C:\\x") is None


# Finding and checking the port -------------------------------------------------------------------------------


def discovery(tmp_path, listeners, process_path=None):
    return cdp.Discovery(
        local_app_data=tmp_path, listeners=listeners, process_path=process_path or brave_paths()
    )


@pytest.mark.anyio
async def test_no_devtools_active_port_means_debugging_off(tmp_path):
    asked = []

    def listeners(port):
        asked.append(port)
        return [("127.0.0.1", BROWSER_PID)]

    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, listeners).locate(brave_info(), None)
    assert raised.value.code == "debuggingOff"
    message = raised.value.message
    assert "brave://inspect/#remote-debugging" in message
    assert "Allow remote debugging for this browser instance" in message
    assert "Control+T" in message and "press Enter" in message
    # Never guesses a port such as 9222.
    assert asked == []


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["", "garbage\n", "-5\n"])
async def test_unusable_devtools_active_port_means_debugging_off(tmp_path, content):
    path = write_active_port(tmp_path, 1, None)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: [("127.0.0.1", BROWSER_PID)]).locate(brave_info(), None)
    assert raised.value.code == "debuggingOff"


@pytest.mark.anyio
async def test_stale_devtools_active_port_means_debugging_off(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/old")
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: []).locate(brave_info(), None)
    assert raised.value.code == "debuggingOff"
    assert "left over from an earlier session" in raised.value.message


@pytest.mark.anyio
async def test_google_chrome_steps_mention_the_command_line_flag(tmp_path):
    with pytest.raises(BrowserInspectionError) as chrome:
        await discovery(tmp_path, lambda port: []).locate(
            brave_info(appPath=CHROME_PATH, appName="chrome"), None
        )
    assert "chrome://inspect/#remote-debugging" in chrome.value.message
    assert "--remote-debugging-port" in chrome.value.message
    with pytest.raises(BrowserInspectionError) as brave:
        await discovery(tmp_path, lambda port: []).locate(brave_info(), None)
    assert "--remote-debugging-port" not in brave.value.message


@pytest.mark.anyio
async def test_port_owned_by_another_program_is_refused(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/abc")
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: [("127.0.0.1", 999)]).locate(brave_info(), None)
    assert raised.value.code == "portNotOwned"
    assert "9333" in raised.value.message


@pytest.mark.anyio
async def test_renderer_process_of_the_same_executable_is_accepted(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/abc")
    # The browser listens from its main process; NVDA's control belongs to a renderer. Paths differ only in case.
    found = cdp.Discovery(
        local_app_data=tmp_path,
        listeners=lambda port: [("127.0.0.1", BROWSER_PID)],
        process_path=lambda pid: BRAVE_PATH.upper() if pid == BROWSER_PID else None,
    )
    endpoint = await found.locate(brave_info(processId=RENDERER_PID), None)
    assert endpoint.url == "ws://127.0.0.1:9333/devtools/browser/abc"
    assert endpoint.browser.name == "Brave"


@pytest.mark.anyio
async def test_listener_owned_by_the_control_process_itself_is_accepted(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/abc")
    found = discovery(tmp_path, lambda port: [("127.0.0.1", RENDERER_PID)], process_path=lambda pid: None)
    assert (await found.locate(brave_info(), None)).port == 9333


@pytest.mark.anyio
async def test_a_second_listener_from_another_program_is_refused(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/abc")
    listeners = [("127.0.0.1", BROWSER_PID), ("0.0.0.0", 999)]
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: listeners).locate(brave_info(), None)
    assert raised.value.code == "portNotOwned"


@pytest.mark.anyio
async def test_ipv6_only_listener_is_reached_over_ipv6(tmp_path):
    write_active_port(tmp_path, 9333, "/devtools/browser/abc")
    endpoint = await discovery(tmp_path, lambda port: [("::1", BROWSER_PID)]).locate(brave_info(), None)
    assert endpoint.url == "ws://[::1]:9333/devtools/browser/abc"


@pytest.mark.anyio
async def test_a_given_port_is_checked_the_same_way(tmp_path):
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: [("127.0.0.1", 999)]).locate(brave_info(), 9444)
    assert raised.value.code == "portNotOwned"
    assert "Check the port number you gave" in raised.value.message
    with pytest.raises(BrowserInspectionError) as nothing:
        await discovery(tmp_path, lambda port: []).locate(brave_info(), 9444)
    assert nothing.value.code == "debuggingOff"
    assert "Nothing is listening on port 9444" in nothing.value.message


@pytest.mark.anyio
async def test_a_given_port_uses_the_path_in_devtools_active_port(tmp_path):
    write_active_port(tmp_path, 9444, "/devtools/browser/from-file")
    endpoint = await discovery(tmp_path, lambda port: [("127.0.0.1", BROWSER_PID)]).locate(brave_info(), 9444)
    assert endpoint.path == "/devtools/browser/from-file"


@pytest.mark.anyio
async def test_unknown_browser_needs_a_port(tmp_path):
    info = brave_info(appPath=r"C:\Program Files\Vivaldi\vivaldi.exe", appName="vivaldi")
    with pytest.raises(BrowserInspectionError) as raised:
        await discovery(tmp_path, lambda port: []).locate(info, None)
    assert raised.value.code == "unsupportedBrowser"
    with pytest.raises(BrowserInspectionError) as with_port:
        await discovery(tmp_path, lambda port: []).locate(info, 9444)
    assert with_port.value.code == "debuggingOff"
    assert "Vivaldi" in with_port.value.message


# The real Windows functions ----------------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_finds_the_owner_of_a_real_loopback_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert ("127.0.0.1", os.getpid()) in cdp.loopback_listeners(port)
    assert cdp.loopback_listeners(port) == []


@pytest.mark.skipif(sys.platform != "win32" or not socket.has_ipv6, reason="Windows with IPv6 only")
def test_finds_the_owner_of_a_real_ipv6_listener():
    try:
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.bind(("::1", 0))
    except OSError:
        pytest.skip("IPv6 loopback is not available")
    with server:
        server.listen()
        assert ("::1", os.getpid()) in cdp.loopback_listeners(server.getsockname()[1])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_reads_a_real_process_path():
    path = cdp.process_image_path(os.getpid())
    # In a virtual environment, the running interpreter can be the base one the venv's launcher started.
    assert cdp.normalise_path(path) in {
        cdp.normalise_path(sys.executable),
        cdp.normalise_path(getattr(sys, "_base_executable", sys.executable)),
    }
    assert cdp.process_image_path(0) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_real_owner_check(tmp_path):
    real = cdp.Discovery(local_app_data=tmp_path)
    own_path = cdp.process_image_path(os.getpid())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        browser = cdp.browser_for_app_path(BRAVE_PATH, tmp_path)
        # A process of the same executable as the listener (here, this test) is accepted...
        assert (
            real.check_owner(browser, {"processId": 1, "appPath": own_path}, port, given=True) == "127.0.0.1"
        )
        # ...another executable is not.
        with pytest.raises(BrowserInspectionError) as raised:
            real.check_owner(browser, {"processId": 1, "appPath": BRAVE_PATH}, port, given=True)
        assert raised.value.code == "portNotOwned"


# Targets -----------------------------------------------------------------------------------------------------


def test_matching_targets_prefers_the_exact_url():
    targets = [
        {"targetId": "1", "type": "page", "url": "https://web.whatsapp.com/?ref=1", "title": "a"},
        {"targetId": "2", "type": "page", "url": "https://web.whatsapp.com/", "title": "b"},
        {"targetId": "3", "type": "service_worker", "url": "https://web.whatsapp.com/", "title": "c"},
        {"targetId": "4", "type": "iframe", "url": "https://web.whatsapp.com/", "title": "d"},
        {"targetId": "5", "type": "page", "url": "https://bank.example/", "title": "e"},
    ]
    assert [t["targetId"] for t in cdp.matching_targets(targets, "https://web.whatsapp.com/")] == ["2", "4"]
    # Otherwise the same scheme, host and path, whatever the query and fragment.
    assert [t["targetId"] for t in cdp.matching_targets(targets, "https://WEB.whatsapp.com/#chat")] == [
        "1",
        "2",
        "4",
    ]
    assert cdp.matching_targets(targets, "http://web.whatsapp.com/") == []
    assert cdp.matching_targets(targets, None) == []


def test_short_url_drops_query_and_fragment():
    assert cdp.short_url("https://example.com/a/b?token=secret#x") == "https://example.com/a/b?…"
    assert cdp.short_url("https://example.com/" + "x" * 200, 50).endswith("…")


# The connection ----------------------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_connects_to_the_path_in_devtools_active_port(tmp_path):
    async with FakeBrowser([simple_page(), secret_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            targets = await connection.page_targets("https://web.whatsapp.com/")
        await pool.close_all()
    assert fake.handshake_requests[0].path == fake.ws_path
    # Browsers refuse connections that send an Origin header.
    assert "Origin" not in fake.handshake_requests[0].headers
    assert [target["title"] for target in targets] == ["WhatsApp"]


@pytest.mark.anyio
async def test_refuses_commands_that_are_not_allowed_before_sending(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            for method in (
                "Runtime.evaluate",
                "Page.navigate",
                "Input.dispatchKeyEvent",
                "DOM.setAttributeValue",
            ):
                with pytest.raises(MethodNotAllowedError):
                    await connection.send(method, {"expression": "alert(1)"})
            async with connection.attach(
                (await connection.page_targets("https://web.whatsapp.com/"))[0]
            ) as page:
                with pytest.raises(MethodNotAllowedError):
                    await page.send("Runtime.evaluate", {"expression": "document.cookie"})
                await page.send("DOM.getDocument", {"depth": 0})
        await pool.close_all()
    assert "Runtime.evaluate" not in fake.methods
    assert set(fake.methods) <= cdp.ALLOWED_METHODS
    assert "DOM.getOuterHTML" not in cdp.ALLOWED_METHODS


@pytest.mark.anyio
async def test_attaches_only_to_pages_and_detaches_after(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            with pytest.raises(ValueError):
                async with connection.attach({"targetId": "WORKER-1", "type": "service_worker"}):
                    pass
            async with connection.attach((await connection.page_targets("https://web.whatsapp.com/"))[0]):
                pass
        await pool.close_all()
    assert fake.methods.count("Target.attachToTarget") == 1
    assert fake.methods.count("Target.detachFromTarget") == 1
    assert fake.sessions == {}


@pytest.mark.anyio
async def test_connection_is_reused_across_calls(tmp_path):
    announce = Announcer()
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        assert not pool.is_connected(brave_info())
        for _ in range(2):
            async with pool.browser(brave_info(), announce=announce) as connection:
                await connection.page_targets("https://web.whatsapp.com/")
        assert pool.is_connected(brave_info())
        assert pool.is_connected(brave_info(), port=fake.port)
        await pool.close_all()
        assert not pool.is_connected(brave_info())
    assert fake.handshakes == 1
    assert announce.said == [
        "NVDA MCP is connecting to Brave. Brave will ask whether to allow remote debugging: choose Allow."
    ]


@pytest.mark.anyio
async def test_calls_waiting_for_approval_share_one_connection(tmp_path):
    announce = Announcer()
    async with FakeBrowser([simple_page()], approval_delay=0.3) as fake:
        pool = make_pool(fake, tmp_path)

        async def call():
            async with pool.browser(brave_info(), announce=announce) as connection:
                return await connection.page_targets("https://web.whatsapp.com/")

        first, second = await asyncio.gather(call(), call())
        await pool.close_all()
    assert first == second
    assert fake.handshakes == 1
    assert len(announce.said) == 1


@pytest.mark.anyio
async def test_idle_connection_closes(tmp_path):
    announce = Announcer()
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path, idle_seconds=0.2)
        async with pool.browser(brave_info(), announce=announce) as connection:
            await asyncio.sleep(0.4)
            # Not while it is in use.
            assert fake.open_connections == 1
            await connection.page_targets("https://web.whatsapp.com/")
        await eventually(lambda: fake.open_connections == 0)
        assert not pool.is_connected(brave_info())
        async with pool.browser(brave_info(), announce=announce) as connection:
            await connection.page_targets("https://web.whatsapp.com/")
        await pool.close_all()
    assert fake.handshakes == 2
    assert len(announce.said) == 2


@pytest.mark.anyio
async def test_connection_approved_after_the_caller_gave_up_still_closes(tmp_path):
    async with FakeBrowser([simple_page()], approval_delay=1.0) as fake:
        pool = make_pool(fake, tmp_path, idle_seconds=1.0)

        async def call():
            async with pool.browser(brave_info()):
                pass

        task = asyncio.ensure_future(call())
        # The dialog is showing.
        await eventually(lambda: fake.handshakes == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The user allowed it after all: kept for the next call...
        await eventually(lambda: pool.is_connected(brave_info()))
        # ...and closed when nobody used it.
        await eventually(lambda: fake.open_connections == 0 and not pool.is_connected(brave_info()))
    assert fake.handshakes == 1


@pytest.mark.anyio
async def test_unanswered_approval_times_out_without_retrying(tmp_path):
    announce = Announcer()
    async with FakeBrowser([simple_page()], approval_delay=30) as fake:
        pool = make_pool(fake, tmp_path)
        with pytest.raises(BrowserInspectionError) as raised:
            async with pool.browser(brave_info(), approval_timeout=0.2, announce=announce):
                pass
        await asyncio.sleep(0.3)
        assert fake.handshakes == 1
        assert not pool.is_connected(brave_info())
    error = raised.value
    assert error.code == "approvalTimedOut"
    assert '"Allow remote debugging?"' in error.message
    assert "0.2 seconds" in error.message
    assert "Cancel has focus: press Tab to move to Allow" in error.message
    assert "older ones" in error.message
    assert "will not try again" in error.message
    assert len(announce.said) == 1


@pytest.mark.anyio
async def test_refused_connection(tmp_path):
    async with FakeBrowser([simple_page()], refuse=True) as fake:
        pool = make_pool(fake, tmp_path)
        with pytest.raises(BrowserInspectionError) as raised:
            async with pool.browser(brave_info()):
                pass
        assert fake.handshakes == 1
    assert raised.value.code == "refused"
    assert "HTTP 403" in raised.value.message
    assert '"Turn off in settings"' in raised.value.message
    assert "brave://inspect/#remote-debugging" in raised.value.message


@pytest.mark.anyio
async def test_proxy_settings_do_not_affect_the_loopback_connection(tmp_path, monkeypatch):
    proxied = []

    async def record(reader, writer):
        proxied.append(await reader.read(200))
        writer.close()

    proxy = await asyncio.start_server(record, "127.0.0.1", 0)
    proxy_url = f"http://127.0.0.1:{proxy.sockets[0].getsockname()[1]}"
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "WS_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, proxy_url)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    try:
        async with FakeBrowser([simple_page()], json_version=True) as fake:
            # Through DevToolsActivePort...
            pool = make_pool(fake, tmp_path)
            async with pool.browser(brave_info()) as connection:
                assert await connection.page_targets("https://web.whatsapp.com/")
            await pool.close_all()
            # ...and through a given port, which also asks /json/version over HTTP.
            other = tmp_path / "other"
            given = cdp.ConnectionPool(
                cdp.Discovery(
                    local_app_data=other, listeners=browser_listeners(fake), process_path=brave_paths()
                )
            )
            async with given.browser(brave_info(), port=fake.port) as connection:
                assert await connection.page_targets("https://web.whatsapp.com/")
            await given.close_all()
    finally:
        proxy.close()
        await proxy.wait_closed()
    assert proxied == []
    assert fake.http_requests == ["/json/version"]
    assert fake.handshakes == 2


@pytest.mark.anyio
async def test_given_port_without_json_version_uses_the_default_path(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = cdp.ConnectionPool(
            cdp.Discovery(
                local_app_data=tmp_path, listeners=browser_listeners(fake), process_path=brave_paths()
            )
        )
        async with pool.browser(brave_info(), port=fake.port) as connection:
            await connection.page_targets("https://web.whatsapp.com/")
        await pool.close_all()
    assert fake.http_requests == ["/json/version"]
    assert fake.handshake_requests[0].path == "/devtools/browser"


@pytest.mark.anyio
async def test_commands_time_out(tmp_path):
    async with FakeBrowser([simple_page()], hang=("Target.getTargets",)) as fake:
        pool = make_pool(fake, tmp_path, command_timeout=0.2)
        async with pool.browser(brave_info()) as connection:
            with pytest.raises(BrowserInspectionError) as raised:
                await connection.page_targets("https://web.whatsapp.com/")
        await pool.close_all()
    assert raised.value.code == "browserTimedOut"
    assert "0.2 seconds" in raised.value.message


@pytest.mark.anyio
async def test_browser_closing_is_reported_and_forgotten(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            await fake.disconnect_all()
            await eventually(lambda: connection.closed)
            with pytest.raises(BrowserInspectionError) as raised:
                await connection.page_targets("https://web.whatsapp.com/")
        assert not pool.is_connected(brave_info())
        async with pool.browser(brave_info()) as connection:
            assert await connection.page_targets("https://web.whatsapp.com/")
        await pool.close_all()
    assert raised.value.code == "browserGone"
    assert fake.handshakes == 2


@pytest.mark.anyio
async def test_close_all_closes_the_socket(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            await connection.page_targets("https://web.whatsapp.com/")
        assert fake.open_connections == 1
        await pool.close_all()
        await eventually(lambda: fake.open_connections == 0)


@pytest.mark.anyio
async def test_close_all_gives_up_on_a_connection_waiting_for_approval(tmp_path):
    async with FakeBrowser([simple_page()], approval_delay=0.5) as fake:
        pool = make_pool(fake, tmp_path)

        async def call():
            async with pool.browser(brave_info()):
                pass

        task = asyncio.ensure_future(call())
        # The dialog is showing when the server closes its connections.
        await eventually(lambda: fake.handshakes == 1)
        await pool.close_all()
        with pytest.raises(BrowserInspectionError) as raised:
            await task
        # The user chooses Allow afterwards: nothing is left open.
        await asyncio.sleep(0.7)
        await eventually(lambda: fake.open_connections == 0)
        assert not pool.is_connected(brave_info())
    assert raised.value.code == "browserGone"
    assert "stopped waiting" in raised.value.message
    assert "choose Cancel" in raised.value.message
    assert fake.handshakes == 1


@pytest.mark.anyio
async def test_connection_from_an_ended_event_loop_is_not_reused(tmp_path):
    async with FakeBrowser([simple_page()]) as fake:
        pool = make_pool(fake, tmp_path)
        async with pool.browser(brave_info()) as connection:
            await connection.page_targets("https://web.whatsapp.com/")
        # As if the server's event loop had been replaced.
        connection.loop = asyncio.new_event_loop()
        connection.loop.close()
        assert not pool.is_connected(brave_info())
        await pool.close_all()


def test_is_connected_needs_no_event_loop(tmp_path):
    pool = cdp.ConnectionPool(cdp.Discovery(local_app_data=tmp_path, listeners=lambda port: []))
    assert not pool.is_connected(brave_info())
    assert not pool.is_connected(brave_info(appPath=r"C:\Program Files\Vivaldi\vivaldi.exe"))


def test_errors_carry_code_and_message():
    error = cdp.browser_gone(cdp.browser_for_app_path(BRAVE_PATH, Path("C:/x")))
    assert error.code == "browserGone"
    assert str(error) == error.message
    assert "Brave" in error.message
