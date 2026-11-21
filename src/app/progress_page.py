"""The Progress page: what a person has left to watch, show by show.

One read answers web and native (``/api/v1/progress/``). It reuses the time-left
order's grouped facts (``app.tv_sort``), so a show's watched count, episodes left
and minutes left agree with the library's "time left" sort and Home. Only the page
being shown loads seasons for the next-episode lookup.
"""

from types import SimpleNamespace

from django.utils.translation import gettext as _

from app import helpers
from app.card_surfaces import card_context
from app.media_list_filters import next_episode_for_media
from app.models import TV, BasicMedia, Item, MediaTypes, Status
from app.templatetags.app_tags import media_url
from app.tv_sort import build_time_left_records, sort_time_left_records

SORTS = ("least_time", "most_time", "least_episodes", "most_episodes")
DEFAULT_SORT = "least_time"
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
_TRACKED_STATUSES = (Status.IN_PROGRESS.value, Status.COMPLETED.value)
# The two groups the Status filter offers: shows with episodes left, and caught up.
GROUPS = ("in_progress", "finished")
DEFAULT_GROUPS = ("in_progress",)


def normalize_sort(value):
    """Return a known sort, or the default."""
    return value if value in SORTS else DEFAULT_SORT


def normalize_groups(value):
    """Return the requested groups from a comma list, or the default."""
    wanted = [part for part in str(value or "").split(",") if part in GROUPS]
    return tuple(wanted) or DEFAULT_GROUPS


def _ranked_records(user, groups):
    """Every show with something to show, as time-left records."""
    trackers = list(
        BasicMedia.objects.get_media_list(
            user=user,
            media_type=MediaTypes.TV.value,
            status_filter=list(_TRACKED_STATUSES),
            sort_filter="title",
            prefetch_graph=False,
        ),
    )
    entries = [SimpleNamespace(item=media.item, media=media) for media in trackers]
    records = sort_time_left_records(build_time_left_records(user, entries))
    return [
        record
        for record in records
        if record.media_pk
        and record.effective_max
        and (
            ("in_progress" in groups and record.episodes_left_display > 0)
            or ("finished" in groups and record.episodes_left_display == 0)
        )
    ]


def _episodes_key(record):
    return (record.episodes_left_display, record.title.lower())


def _time_key(record):
    return (record.minutes_left is None, record.minutes_left or 0, record.title.lower())


def _order(records, sort):
    """Order records; shows without a time estimate go last in a time sort."""
    key = _episodes_key if sort.endswith("episodes") else _time_key
    return sorted(records, key=key, reverse=sort.startswith("most"))


def _episode_card(user, tracker):
    """Return the next episode as a media card model (still, title, S01 E04)."""
    episode = next_episode_for_media(tracker)
    if not episode:
        return None
    item = Item.objects.filter(
        source=tracker.item.source,
        media_id=tracker.item.media_id,
        media_type=MediaTypes.EPISODE.value,
        season_number=episode.get("season_number"),
        episode_number=episode.get("episode_number"),
    ).first()
    if item is None:
        return None
    context = card_context(
        {"user": user, "request": None, "csrf_token": ""},
        "list",
        {
            "item": item,
            "media": None,
            "title": item,
            "card_media_type": MediaTypes.EPISODE.value,
            "image_override": item.image,
            "image_source": "primary",
        },
    )
    model = (context.get("react_props") or {}).get("model")
    if model is None:
        return None
    # A horizontal (16:9) still with the title over it, read-only, and the S04 E03
    # subtitle always showing instead of on hover.
    model["shape"] = "landscape"
    model["aspectRatio"] = 16 / 9
    model["subtitleAlways"] = True
    model.pop("actions", None)
    return model


def _row(user, record, tracker):
    item = record.entry.item if record.entry else tracker.item
    watched = min(record.progress or 0, record.effective_max)
    return {
        "id": record.media_pk,
        "title": item.title,
        "media_id": item.media_id,
        "source": item.source,
        "image": item.image,
        "url": media_url(item) or None,
        "year": item.release_datetime.year
        if getattr(item, "release_datetime", None)
        else None,
        "watched": watched,
        "total": record.effective_max,
        "left": record.episodes_left_display,
        "percent": round(watched * 100 / record.effective_max)
        if record.effective_max
        else 0,
        "minutes_left": record.minutes_left or 0,
        "time_left": record.time_left_display,
        "next_episode_card": _episode_card(user, tracker),
    }


def _hydrate(user, records):
    """Trackers for one page, with the seasons the next-episode lookup reads."""
    queryset = TV.objects.filter(
        user=user,
        pk__in=[record.media_pk for record in records],
    ).select_related("item")
    queryset = BasicMedia.objects._apply_prefetch_related(
        queryset,
        MediaTypes.TV.value,
        list_mode=True,
    )
    return {tracker.pk: tracker for tracker in queryset}


def _minutes_label(minutes):
    return helpers.minutes_to_hm(minutes) if minutes else "0m"


def build_progress_page(
    user, *, sort=DEFAULT_SORT, groups=DEFAULT_GROUPS, offset=0, limit=DEFAULT_LIMIT
):
    """Return the summary line and one page of shows."""
    sort = normalize_sort(sort)
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    records = _order(_ranked_records(user, groups), sort)
    page = records[offset : offset + limit]
    trackers = _hydrate(user, page)
    results = [
        _row(user, record, trackers[record.media_pk])
        for record in page
        if record.media_pk in trackers
    ]
    left = sum(record.episodes_left_display for record in records)
    minutes = sum(record.minutes_left or 0 for record in records)
    return {
        "summary": {
            "shows": len(records),
            "left": left,
            "minutes_left": minutes,
            "text": _("%(left)s remaining (%(time)s)")
            % {"left": left, "time": _minutes_label(minutes)},
        },
        "sort": sort,
        "statuses": list(groups),
        "results": results,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < len(records),
        },
    }
