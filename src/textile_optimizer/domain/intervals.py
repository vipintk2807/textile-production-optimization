"""Half-open interval helpers, ``[start, end)`` in integer minutes.

The start is included and the end is excluded, so an operation may finish at the exact
minute another begins without overlapping (textile_scheduling_rules 9.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

Interval = tuple[int, int]


def overlaps(a: Interval, b: Interval) -> bool:
    """True when the two half-open intervals genuinely intersect (adjacent ones do not)."""
    return a[0] < b[1] and b[0] < a[1]


def contained_in(inner: Interval, outer: Interval) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def length(interval: Interval) -> int:
    return interval[1] - interval[0]


def sorted_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    return sorted(intervals)


def find_overlapping_pairs(intervals: Sequence[Interval]) -> list[tuple[Interval, Interval]]:
    """Return every pair of intervals that overlap (after sorting by start)."""
    ordered = sorted_intervals(intervals)
    pairs: list[tuple[Interval, Interval]] = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            if second[0] >= first[1]:
                break
            pairs.append((first, second))
    return pairs


def subtract(windows: Sequence[Interval], blocked: Sequence[Interval]) -> list[Interval]:
    """Remove ``blocked`` intervals from ``windows``; result is sorted and disjoint."""
    result: list[Interval] = []
    blocked_sorted = sorted_intervals(blocked)
    for start, end in sorted_intervals(windows):
        cursor = start
        for b_start, b_end in blocked_sorted:
            if b_end <= cursor or b_start >= end:
                continue
            if b_start > cursor:
                result.append((cursor, b_start))
            cursor = max(cursor, b_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def total_length(intervals: Iterable[Interval]) -> int:
    return sum(length(i) for i in intervals)


def clip(interval: Interval, lower: int, upper: int) -> Interval | None:
    """Clip to ``[lower, upper)``; ``None`` if nothing remains."""
    start, end = max(interval[0], lower), min(interval[1], upper)
    return (start, end) if start < end else None
