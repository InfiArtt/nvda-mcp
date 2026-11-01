from nvda_mcp.scenario import Recording, StepRecord, compare, load_baseline, save_baseline


def recording(*spoken):
    return Recording([StepRecord(f"press tab {i}", text, "OK (button)") for i, text in enumerate(spoken)])


def test_baseline_round_trips(tmp_path):
    path = tmp_path / "a11y" / "login.json"
    save_baseline(path, recording("User name edit", "Sign in button"))
    assert load_baseline(path) == recording("User name edit", "Sign in button")


def test_compare_reports_changed_speech_and_ignores_pattern():
    old = recording("User name edit", "Sent at 10:30")
    new = recording("edit", "Sent at 10:31")
    assert compare(old, new, ignore_pattern=r"\d+:\d+") == [
        "Step 1 (press tab 0): NVDA said 'edit', baseline 'User name edit'"
    ]
    assert compare(old, old) == []


def test_compare_refuses_different_steps():
    assert "steps differ" in compare(recording("a"), recording("a", "b"))[0]
