"""Conversion between calendar timestamps and integer minutes from the planning origin.

Internal scheduling time is always integer minutes relative to the planning origin
(technical_specification 6.1). Calendar times are naive local datetimes: the application
does not perform time-zone arithmetic, and one clock minute is one scheduling minute
(shifts/breaks must be modelled through machine availability, never assumed).
"""

from __future__ import annotations

from datetime import datetime, timedelta


def to_minutes(moment: datetime, origin: datetime) -> int:
    """Convert a calendar timestamp to whole minutes after ``origin``.

    Raises ValueError for sub-minute precision rather than rounding silently
    (textile_scheduling_rules 11.3: rounding must not silently change feasibility).
    """
    if moment.tzinfo is not None or origin.tzinfo is not None:
        raise ValueError("Time-zone aware datetimes are not supported; use naive local times.")
    delta = moment - origin
    seconds = delta.total_seconds()
    if seconds % 60 != 0:
        raise ValueError("Timestamp must fall on a whole minute relative to the planning origin.")
    return int(seconds // 60)


def to_datetime(minutes: int, origin: datetime) -> datetime:
    return origin + timedelta(minutes=int(minutes))


def format_minutes(minutes: int | float | None, origin: datetime | None = None) -> str:
    """Display helper: ``540`` -> ``540 (2026-01-05 17:00)``; unknown -> ``unavailable``."""
    if minutes is None:
        return "unavailable"
    minutes = int(minutes)
    if origin is None:
        return str(minutes)
    return f"{minutes} ({to_datetime(minutes, origin):%Y-%m-%d %H:%M})"


def format_duration(minutes: int | float | None) -> str:
    if minutes is None:
        return "unavailable"
    return f"{int(minutes)} min"
