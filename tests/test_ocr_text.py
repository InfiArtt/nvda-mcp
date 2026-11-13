from ocrText import linesFromWords


def test_lines_join_their_words_and_get_their_place_on_the_screen():
    data = [
        [
            {"x": 40, "y": 80, "width": 100, "height": 20, "text": "Light"},
            {"x": 150, "y": 84, "width": 120, "height": 20, "text": "Setting"},
        ],
        [{"x": 0, "y": 0, "width": 4, "height": 4, "text": " "}],
        [{"x": 40, "y": 160, "width": 80, "height": 20, "text": "Off"}],
    ]
    lines = linesFromWords(data, left=100, top=200, scale=4)
    assert lines == [
        {"text": "Light Setting", "location": [110, 220, 58, 6]},
        {"text": "Off", "location": [110, 240, 20, 5]},
    ]
