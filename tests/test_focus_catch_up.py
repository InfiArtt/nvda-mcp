from focusCatchUp import catchUpEvents


def test_window_first_then_the_control_in_it():
    assert catchUpEvents("WhatsApp - Brave", "Archived button") == ["WhatsApp - Brave", "Archived button"]


def test_window_that_has_the_focus_itself_gets_one_event():
    assert catchUpEvents("Notepad", "Notepad") == ["Notepad"]
    assert catchUpEvents("Notepad", None) == ["Notepad"]


def test_without_the_window_only_the_control_gets_focus_as_before():
    assert catchUpEvents(None, "Archived button") == ["Archived button"]
    assert catchUpEvents(None, None) == []
