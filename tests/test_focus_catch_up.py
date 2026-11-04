from focusCatchUp import catchUpEvents, earlyWindowEvent


def test_window_first_then_the_control_in_it():
    assert catchUpEvents("WhatsApp - Brave", "Archived button") == ["WhatsApp - Brave", "Archived button"]


def test_window_that_has_the_focus_itself_gets_one_event():
    assert catchUpEvents("Notepad", "Notepad") == ["Notepad"]
    assert catchUpEvents("Notepad", None) == ["Notepad"]


def test_without_the_window_only_the_control_gets_focus_as_before():
    assert catchUpEvents(None, "Archived button") == ["Archived button"]
    assert catchUpEvents(None, None) == []


def test_window_already_announced_is_not_announced_again():
    assert catchUpEvents("WhatsApp - Brave", "Archived button", "WhatsApp - Brave") == ["Archived button"]
    assert catchUpEvents("WhatsApp - Brave", None, "WhatsApp - Brave") == []
    assert catchUpEvents("WhatsApp - Brave", "WhatsApp - Brave", "WhatsApp - Brave") == []


def test_announced_window_that_is_not_this_one_changes_nothing():
    assert catchUpEvents("Notepad", "Text editor", "WhatsApp - Brave") == ["Notepad", "Text editor"]
    assert catchUpEvents(None, "Text editor", "WhatsApp - Brave") == ["Text editor"]


def test_page_in_focus_mode_gets_its_window_announced_first():
    assert earlyWindowEvent("WhatsApp - Brave", "Chat list cell", inFocusMode=True) == "WhatsApp - Brave"


def test_page_in_browse_mode_is_left_to_nvda():
    # NVDA says the title once there, and a focus that turns focus mode on would cut it off.
    assert earlyWindowEvent("WhatsApp - Brave", "Chat list cell", inFocusMode=False) is None


def test_no_early_event_without_a_window_and_a_control_inside_it():
    assert earlyWindowEvent(None, "Chat list cell", inFocusMode=True) is None
    assert earlyWindowEvent("WhatsApp - Brave", None, inFocusMode=True) is None
    assert earlyWindowEvent("Notepad", "Notepad", inFocusMode=True) is None
