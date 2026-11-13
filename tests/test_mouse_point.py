import pytest
from mousePoint import PointError, dragSteps, resolvePoint

SCREEN = (0, 0, 1920, 1080)


def test_a_control_without_a_point_is_clicked_in_its_middle():
    assert resolvePoint({}, (100, 200, 40, 20), SCREEN) == (120, 210)


def test_a_point_is_counted_from_the_controls_top_left_corner():
    # A knob drawn at 30, 12 inside a plugin's canvas.
    assert resolvePoint({"x": 30, "y": 12}, (500, 300, 800, 600), SCREEN) == (530, 312)


def test_points_outside_the_control_are_refused():
    with pytest.raises(PointError, match="outside it: it is 40 by 20 pixels"):
        resolvePoint({"x": 40, "y": 5}, (100, 200, 40, 20), SCREEN)
    with pytest.raises(PointError, match="outside"):
        resolvePoint({"x": -1, "y": 5}, (100, 200, 40, 20), SCREEN)


def test_screen_points_must_be_given_and_on_the_screen():
    assert resolvePoint({"x": 10, "y": 20}, None, SCREEN) == (10, 20)
    with pytest.raises(PointError, match="Pass a control"):
        resolvePoint({}, None, SCREEN)
    with pytest.raises(PointError, match="off the screen"):
        resolvePoint({"x": 1920, "y": 20}, None, SCREEN)
    # A second monitor to the left has negative coordinates.
    assert resolvePoint({"x": -500, "y": 20}, None, (-1920, 0, 3840, 1080)) == (-500, 20)


def test_malformed_points_are_refused():
    with pytest.raises(PointError, match="both x and y"):
        resolvePoint({"x": 10}, None, SCREEN)
    with pytest.raises(PointError, match="whole numbers"):
        resolvePoint({"x": "10", "y": 2}, None, SCREEN)
    with pytest.raises(PointError, match="no size"):
        resolvePoint({}, (0, 0, 0, 0), SCREEN)


def test_other_keys_can_name_the_point():
    assert resolvePoint({"toX": 5, "toY": 6}, (100, 100, 50, 50), SCREEN, "toX", "toY") == (105, 106)


def test_a_drag_moves_in_steps_and_ends_on_the_target():
    steps = dragSteps((100, 100), (100, 160), steps=6)
    assert steps == [(100, 110), (100, 120), (100, 130), (100, 140), (100, 150), (100, 160)]
