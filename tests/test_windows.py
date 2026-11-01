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
        assert set(info.toDict("app", False)) == {
            "handle",
            "title",
            "appName",
            "isForeground",
            "isMinimized",
            "isHidden",
        }
