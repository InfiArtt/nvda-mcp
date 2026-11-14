from valueText import appendedValue


def test_appended_text_follows_the_fields_line_breaks():
    assert appendedValue("Line one\r\n", "Line two\nLine three") == "Line one\r\nLine two\r\nLine three"
    assert appendedValue("Line one\n", "Line two\r\n") == "Line one\nLine two\r\n"


def test_appending_to_an_empty_or_unreadable_field_gives_the_text():
    assert appendedValue(None, "Halo") == "Halo"
    assert appendedValue("", "a\nb") == "a\nb"
