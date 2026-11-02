"""Serialize and deserialize history day/entry dicts for cache storage."""

from datetime import datetime

from django.utils import timezone

from app.history_entry_builders import (
    _serialize_album,
    _serialize_item,
    _serialize_show,
)

# played_at_local drives ordering; the other three feed the card properties.
_ENTRY_DATETIME_KEYS = ("played_at_local", "created_at", "start_date", "end_date")


def _serialize_history_entry(entry):
    data = dict(entry)
    data["item"] = _serialize_item(data.get("item"))
    data["album"] = _serialize_album(data.get("album"))
    data["show"] = _serialize_show(data.get("show"))
    data.pop("episode_modal", None)
    for key in _ENTRY_DATETIME_KEYS:
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def _deserialize_history_entry(entry):
    data = dict(entry)
    for key in _ENTRY_DATETIME_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(
                        parsed, timezone.get_current_timezone()
                    )
                data[key] = parsed
            except ValueError:
                data[key] = None
    return data


def _serialize_history_day(day):
    date_value = day.get("date")
    if hasattr(date_value, "isoformat"):
        date_value = date_value.isoformat()
    return {
        "date": date_value,
        "weekday": day.get("weekday", ""),
        "date_display": day.get("date_display", ""),
        "entries": [
            _serialize_history_entry(entry) for entry in day.get("entries", [])
        ],
        "total_minutes": day.get("total_minutes", 0),
        "total_runtime_display": day.get("total_runtime_display", "0min"),
    }


def _deserialize_history_day(
    day,
    *,
    entry_offset=0,
    max_entries=None,
    media_types=None,
    entry_filter=None,
):
    """Deserialize one day while materializing only the requested entry window."""
    date_value = day.get("date")
    if isinstance(date_value, str):
        try:
            date_value = datetime.strptime(date_value, "%Y-%m-%d").date()  # noqa: DTZ007  # date-only value; no timezone applies
        except ValueError:
            date_value = None
    raw_entries = day.get("entries", [])
    entry_offset = max(int(entry_offset or 0), 0)
    stop = None if max_entries is None else entry_offset + max(int(max_entries), 0)
    selected_entries = []
    entry_count = 0
    filtered_minutes = 0
    filtering = media_types is not None or entry_filter is not None
    for entry in raw_entries:
        if media_types is not None and entry.get("media_type") not in media_types:
            continue
        if entry_filter is not None and not entry_filter(entry):
            continue
        if filtering:
            filtered_minutes += entry.get("runtime_minutes") or 0
        if entry_count >= entry_offset and (stop is None or entry_count < stop):
            selected_entries.append(_deserialize_history_entry(entry))
        entry_count += 1

    result = {
        "date": date_value,
        "weekday": day.get("weekday", ""),
        "date_display": day.get("date_display", ""),
        "entries": selected_entries,
        "total_minutes": (
            filtered_minutes if filtering else day.get("total_minutes", 0)
        ),
        "total_runtime_display": day.get("total_runtime_display", "0min"),
    }
    if max_entries is not None or entry_offset or filtering:
        result.update(
            {
                "entry_count": entry_count,
                "entries_truncated": len(selected_entries) < entry_count,
                "_entry_window_offset": entry_offset,
                "_entries_filtered": filtering,
            }
        )
    return result
