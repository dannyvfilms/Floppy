"""Resolve recorded and inferred durations for a single tracking entry."""

from collections import defaultdict
from datetime import UTC, timedelta

RUNTIME_UNKNOWN_AIRED = 999998


def elapsed_minutes(start, end, *, range_start=None, range_end=None):
    """Return elapsed minutes, optionally clipped to a half-open time range.

    Convert to UTC before subtraction: subtraction in a shared local timezone
    otherwise measures wall-clock time across daylight-saving transitions.
    """
    if not start or not end:
        return 0
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if range_start is not None:
        start = max(start, range_start.astimezone(UTC))
    if range_end is not None:
        end = min(end, range_end.astimezone(UTC))
    return max(0, (end - start).total_seconds() / 60)


def play_minutes(start, end, recorded_minutes=0):
    """Prefer recorded activity to the elapsed interval."""
    if recorded_minutes and recorded_minutes > 0:
        return recorded_minutes
    return elapsed_minutes(start, end)


def elapsed_minutes_by_hour(start, end, range_start, range_end, tz):
    """Split an interval by local clock hour, including offset transitions."""
    minutes = defaultdict(float)
    if not start or not end:
        return minutes
    cursor = max(start.astimezone(UTC), range_start.astimezone(UTC))
    end = min(end.astimezone(UTC), range_end.astimezone(UTC))
    while cursor < end:
        local = cursor.astimezone(tz)
        remaining = timedelta(hours=1) - timedelta(
            minutes=local.minute, seconds=local.second, microseconds=local.microsecond
        )
        boundary = min(end, cursor + remaining)
        # An offset can change before the next clock-hour boundary. Locate it
        # on the UTC timeline so skipped and repeated hours receive real time.
        if (boundary - timedelta(microseconds=1)).astimezone(tz).utcoffset() != local.utcoffset():
            lo, hi = cursor, boundary
            while hi - lo > timedelta(microseconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == local.utcoffset():
                    lo = mid
                else:
                    hi = mid
            boundary = hi
        minutes[local.hour] += (boundary - cursor).total_seconds() / 60
        cursor = boundary
    return minutes


def boardgame_recorded_minutes(runtime_minutes, plays):
    """Return a board game's known per-play runtime, excluding sentinels."""
    if runtime_minutes and 0 < runtime_minutes < RUNTIME_UNKNOWN_AIRED and plays:
        return runtime_minutes * plays
    return 0
