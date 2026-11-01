from actionLog import ActionLog
from configSpec import parseAllowedApps


def test_records_actions_as_json_lines_and_reads_the_newest(tmp_path):
    log = ActionLog(str(tmp_path / "nvdaMcp" / "actions.log"))
    log.record("pressKeys", "Notepad", app="notepad", keys=["tab"])
    log.record("typeText", "Notepad", app="notepad", text="halo 😀")
    entries = log.tail(1)
    assert entries == [
        {
            "time": entries[0]["time"],
            "action": "typeText",
            "window": "Notepad",
            "app": "notepad",
            "text": "halo 😀",
        }
    ]
    assert [entry["action"] for entry in log.tail(10)] == ["pressKeys", "typeText"]


def test_full_log_is_moved_aside(tmp_path):
    path = tmp_path / "actions.log"
    log = ActionLog(str(path), maxBytes=200)
    for index in range(5):
        log.record("pressKeys", "Window", keys=[f"key{index}" * 5])
    assert (tmp_path / "actions.log.1").exists()
    assert path.stat().st_size <= 200


def test_tail_of_missing_log_is_empty(tmp_path):
    assert ActionLog(str(tmp_path / "missing.log")).tail(5) == []


def test_allowed_apps_setting_is_parsed_loosely():
    assert parseAllowedApps(" mwMod.exe, Notepad ,, ") == {"mwmod", "notepad"}
    assert parseAllowedApps("") == set()
