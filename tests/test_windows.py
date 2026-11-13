import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="uses the Win32 API")

if sys.platform == "win32":
    import windows
    from windows import WindowInfo


def window(title, hidden=False, handle=1):
    return WindowInfo(handle=handle, title=title, processId=1, isMinimized=False, isHidden=hidden)


def test_match_prefers_exact_titles_then_visible_windows():
    windows_ = [
        window("Notes - mwMod log", hidden=False, handle=1),
        window("mwMod v6", hidden=True, handle=2),
        window("mwmod", hidden=True, handle=3),
        window("Settings", handle=4),
    ]
    assert [w.handle for w in windows.matchWindows(windows_, "MWMOD")] == [3, 1, 2]


def test_unicode_input_uses_surrogate_pairs_for_emoji():
    # "a" is one UTF-16 code unit and the emoji two; each needs a key down and a key up.
    assert len(windows.unicodeInputs("a😀")) == 6


def test_list_windows_describes_real_windows():
    for info in windows.listWindows(includeHidden=True):
        assert info.title
        assert set(info.toDict("app", False)) - {"ownerHandle"} == {
            "handle",
            "title",
            "appName",
            "isForeground",
            "isMinimized",
            "isHidden",
        }


def test_child_windows_have_class_names():
    import ctypes

    desktop = ctypes.windll.user32.GetDesktopWindow()
    children = windows.childWindows(desktop)
    assert children, "Every desktop has top-level windows as children"
    assert all(isinstance(handle, int) and isinstance(name, str) for handle, name in children)
    assert windows.className(desktop) == "#32769"


def test_windows_that_belong_to_another_window_are_listed():
    tool = 0x00000080
    no_activate = 0x08000000
    # A main window, and a floating FX window that REAPER owns, even as a tool window.
    assert windows.isListedWindow(True, 0, 0, 10)
    assert windows.isListedWindow(True, 1234, 0, 10)
    assert windows.isListedWindow(True, 1234, tool, 10)
    # Unowned tool windows, untitled, invisible and "no activate" windows are left out.
    assert not windows.isListedWindow(True, 0, tool, 10)
    assert not windows.isListedWindow(True, 1234, 0, 0)
    assert not windows.isListedWindow(False, 1234, 0, 10)
    assert not windows.isListedWindow(True, 1234, no_activate, 10)


def test_owned_windows_say_which_window_they_belong_to():
    owned = WindowInfo(
        handle=2, title="FX: Track 1", processId=1, isMinimized=False, isHidden=False, ownerHandle=1
    )
    assert owned.toDict("reaper", False)["ownerHandle"] == 1
    assert "ownerHandle" not in window("REAPER").toDict("reaper", False)
