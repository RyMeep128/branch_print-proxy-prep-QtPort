import math

import pytest

import util


def test_unit_conversions_round_trip():
    mm_value = 25.4
    inches = util.mm_to_inch(mm_value)

    assert inches == pytest.approx(1.0)
    assert util.inch_to_mm(inches) == pytest.approx(mm_value)
    assert util.point_to_inch(util.inch_to_point(2.5)) == pytest.approx(2.5)
    assert util.mm_to_point(mm_value) == pytest.approx(72.0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10", True),
        ("10.5", True),
        ("10.5.2", False),
        ("abc", False),
    ],
)
def test_is_number_string(value, expected):
    assert util.is_number_string(value) is expected


def test_cap_bleed_edge_str_caps_values_above_supported_max():
    over_limit = str(util.inch_to_mm(0.2))

    capped = util.cap_bleed_edge_str(over_limit)

    assert float(capped) == pytest.approx(util.inch_to_mm(0.12), abs=0.01)


def test_cap_bleed_edge_str_leaves_invalid_input_unchanged():
    assert util.cap_bleed_edge_str("not-a-number") == "not-a-number"


def test_cap_offset_str_caps_large_values():
    assert util.cap_offset_str("12.345") == "10.00"


def test_cap_offset_str_leaves_small_values_unchanged():
    assert util.cap_offset_str("5.5") == "5.5"

