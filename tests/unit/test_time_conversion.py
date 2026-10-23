from datetime import UTC, datetime

import pytest

from textile_optimizer.domain.timeutil import format_minutes, to_datetime, to_minutes

ORIGIN = datetime(2026, 1, 5, 8, 0)


def test_whole_minute_conversion_and_origin():
    assert to_minutes(ORIGIN, ORIGIN) == 0
    assert to_minutes(datetime(2026, 1, 5, 10, 0), ORIGIN) == 120  # spec example: 120 -> 10:00
    assert to_datetime(120, ORIGIN) == datetime(2026, 1, 5, 10, 0)


def test_crossing_midnight_and_negative_offsets():
    assert to_minutes(datetime(2026, 1, 6, 8, 0), ORIGIN) == 1440
    assert to_minutes(datetime(2026, 1, 5, 7, 0), ORIGIN) == -60


def test_sub_minute_precision_is_rejected_not_rounded():
    with pytest.raises(ValueError):
        to_minutes(datetime(2026, 1, 5, 8, 0, 30), ORIGIN)


def test_timezone_aware_values_rejected():
    with pytest.raises(ValueError):
        to_minutes(datetime(2026, 1, 5, 8, 0, tzinfo=UTC), ORIGIN)


def test_formatting_handles_unknown():
    assert format_minutes(None) == "unavailable"
    assert format_minutes(540, ORIGIN) == "540 (2026-01-05 17:00)"
