from nvda_mcp.audit import FocusOrderAuditor


def control(name, role="button", app="notepad", x=0):
    return {"name": name, "role": role, "appName": app, "location": [x, 0, 10, 10]}


def test_stops_when_focus_returns_to_start():
    auditor = FocusOrderAuditor("tab", control("OK", x=1))
    assert auditor.add_step(control("Cancel", x=2), "Cancel button") is None
    assert auditor.add_step(control("OK", x=1), "OK button") == "focus returned to where the audit started"
    assert auditor.finish("max").issue_count == 0


def test_flags_unlabeled_controls_and_silence():
    auditor = FocusOrderAuditor("tab", control("OK", x=1))
    auditor.add_step(control("", x=2), "")
    issues = auditor.report.steps[1].issues
    assert "Unlabeled button: it has no accessible name" in issues
    assert "NVDA said nothing when this control got focus" in issues


def test_flags_duplicate_names_on_different_controls():
    auditor = FocusOrderAuditor("tab", control("Start", x=1))
    auditor.add_step(control("Delete", x=2), "Delete button")
    auditor.add_step(control("Delete", x=3), "Delete button")
    assert auditor.report.steps[2].issues == ["Same name and role as step 1: users cannot tell them apart"]


def test_stops_when_focus_is_stuck():
    auditor = FocusOrderAuditor("tab", control("A", x=1))
    auditor.add_step(control("B", x=2), "B button")
    assert auditor.add_step(control("B", x=2), "") is None
    assert auditor.add_step(control("B", x=2), "") == "focus stopped moving"


def test_stops_when_focus_leaves_the_app():
    auditor = FocusOrderAuditor("tab", control("A", x=1))
    assert (
        auditor.add_step(control("Start", app="explorer", x=2), "Start button")
        == "focus left the application"
    )


def test_markdown_escapes_table_cells():
    auditor = FocusOrderAuditor("tab", control("A|B", x=1), "A|B button")
    markdown = auditor.finish("max").to_markdown()
    assert "A\\|B" in markdown
    assert "Stopped because: max." in markdown
