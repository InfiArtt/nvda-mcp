from nvdaLog import filterEntries, parseLog, readTail

LOG = """\
t of an entry cut off when reading from the middle
INFO - __main__ (23:42:54.966) - MainThread (16068):
Starting NVDA version 2026.3 AMD64
IO - inputCore.InputManager.executeGesture (23:43:01.100) - MainThread (16068):
Input: kb(desktop):p
ERROR - external:globalPlugins.foo.GlobalPlugin.script_bar (23:43:26.884) - MainThread (16068):
Error running script
Traceback (most recent call last):
  File "foo.py", line 3, in script_bar
ZeroDivisionError: division by zero
WARNING - gui.__getattr__ (23:43:12.577) - MainThread (16068):
Importing from gui is deprecated
"""


def test_parse_splits_entries_and_drops_leading_fragment():
    entries = parseLog(LOG)
    assert [entry["level"] for entry in entries] == ["INFO", "IO", "ERROR", "WARNING"]
    assert entries[2]["source"] == "external:globalPlugins.foo.GlobalPlugin.script_bar"
    assert entries[2]["time"] == "23:43:26.884"
    assert entries[2]["thread"] == "MainThread (16068)"
    assert entries[2]["message"].endswith("ZeroDivisionError: division by zero")


def test_filter_by_level_text_and_limit():
    entries = parseLog(LOG)
    assert [entry["level"] for entry in filterEntries(entries)] == ["ERROR", "WARNING"]
    assert [entry["level"] for entry in filterEntries(entries, minLevel="DEBUG")] == [
        "INFO",
        "ERROR",
        "WARNING",
    ]
    assert [entry["level"] for entry in filterEntries(entries, minLevel="DEBUG", includeIo=True)] == [
        "INFO",
        "IO",
        "ERROR",
        "WARNING",
    ]
    assert [entry["level"] for entry in filterEntries(entries, contains="globalplugins.FOO")] == ["ERROR"]
    assert [entry["level"] for entry in filterEntries(entries, limit=1)] == ["WARNING"]


def test_read_tail_reports_when_the_start_was_left_out(tmp_path):
    path = tmp_path / "nvda.log"
    path.write_bytes(LOG.encode("utf-8"))
    assert readTail(str(path)) == (LOG, False)
    text, isCut = readTail(str(path), maxBytes=100)
    assert isCut
    assert LOG.endswith(text)
