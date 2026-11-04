import struct
import zlib

import pytest
from screenImage import PNG_SIGNATURE, captureRegion, encodePng, scaleFor

SCREEN = (0, 0, 1920, 1080)


def test_region_adds_padding_around_the_control():
    assert captureRegion((100, 200, 40, 30), 8, SCREEN) == (92, 192, 56, 46)


def test_region_is_cut_to_the_screen_including_monitors_left_of_the_main_one():
    assert captureRegion((-5, 1070, 40, 30), 8, SCREEN) == (0, 1062, 43, 18)
    assert captureRegion((-1900, 10, 40, 30), 0, (-1920, 0, 3840, 1080)) == (-1900, 10, 40, 30)


def test_no_region_for_controls_off_the_screen_or_without_size():
    assert captureRegion((2000, 10, 40, 30), 8, SCREEN) is None
    assert captureRegion((10, 10, 0, 30), 8, SCREEN) is None


def test_large_pictures_are_shrunk():
    assert scaleFor((0, 0, 800, 600), 1600) == 1.0
    assert scaleFor((0, 0, 3200, 900), 1600) == 0.5


def test_small_pictures_are_enlarged_up_to_a_limit():
    assert scaleFor((0, 0, 52, 52), 1600, 208, 4.0) == 4.0
    assert scaleFor((0, 0, 100, 40), 1600, 200, 4.0) == 2.0
    assert scaleFor((0, 0, 10, 10), 1600, 200, 4.0) == 4.0
    assert scaleFor((0, 0, 300, 40), 1600, 200, 4.0) == 1.0


def _decode(png):
    assert png.startswith(PNG_SIGNATURE)
    chunks, offset = {}, len(PNG_SIGNATURE)
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        kind = png[offset + 4 : offset + 8]
        data = png[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])
        assert crc == zlib.crc32(kind + data) & 0xFFFFFFFF
        chunks[kind] = data
        offset += 12 + length
    return chunks


def test_png_has_the_pixels_in_rgb_order():
    # Two pixels as Windows gives them: blue, green, red, unused. Red then blue.
    bgra = bytes([0, 0, 255, 0, 255, 0, 0, 0])
    chunks = _decode(encodePng(2, 1, bgra))
    assert struct.unpack(">IIBBBBB", chunks[b"IHDR"]) == (2, 1, 8, 2, 0, 0, 0)
    assert zlib.decompress(chunks[b"IDAT"]) == bytes([0, 255, 0, 0, 0, 0, 255])
    assert chunks[b"IEND"] == b""


def test_png_rows_each_start_with_a_filter_byte():
    bgra = bytes(range(16))  # 2×2 pixels
    rows = zlib.decompress(_decode(encodePng(2, 2, bgra))[b"IDAT"])
    assert rows == bytes([0, 2, 1, 0, 6, 5, 4, 0, 10, 9, 8, 14, 13, 12])


def test_png_refuses_pixels_that_do_not_match_the_size():
    with pytest.raises(ValueError):
        encodePng(2, 2, bytes(12))
