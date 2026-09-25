"""Shared media-list filtering and next-episode resolution."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace

from django.apps import apps
from django.utils import timezone

from app import helpers
from app.models import (
    BasicMedia,
    CollectionEntry,
    Item,
    MediaTypes,
    Season,
    Status,
)
from app.templatetags.app_tags import media_url
from users.models import MediaSortChoices

MEDIA_LIST_MEDIA_TYPES = tuple(
    media_type
    for media_type in MediaTypes.values
)
MEDIA_LIST_NO_STATUS = "no_status"
MEDIA_LIST_YEAR_LENGTH = 4
MEDIA_LIST_STATUS_BY_CODE = {
    "0": Status.PLANNING.value,
    "1": Status.IN_PROGRESS.value,
    "2": Status.PAUSED.value,
    "3": Status.COMPLETED.value,
    "4": Status.DROPPED.value,
}
MEDIA_LIST_STATUS_VALUES = {
    "all",
    MEDIA_LIST_NO_STATUS,
    *(status.value.lower() for status in Status),
}
MEDIA_LIST_SORTS = {
    choice.value for choice in MediaSortChoices
} | {
    "added",
    "updated",
    "itemid",
    "mediaid",
    "type",
    "source",
    "id",
    "ended",
    "started",
}
MEDIA_LIST_SORT_DEFAULTS_ASC = {
    "author",
    "popularity",
    "runtime",
    "start_date",
    "title",
    "next_episode_air_date",
    "time_left",
    "time_to_beat",
    "platform",
}
MEDIA_LIST_PROVIDER_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.MOVIE.value,
    MediaTypes.ANIME.value,
}
MEDIA_LIST_AUTHOR_TYPES = {
    MediaTypes.BOOK.value,
    MediaTypes.MANGA.value,
    MediaTypes.COMIC.value,
    MediaTypes.COMIC_ISSUE.value,
}
MEDIA_LIST_LANGUAGE_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.MOVIE.value,
    MediaTypes.ANIME.value,
}


class MediaListFilterError(ValueError):
    """Raised when an API media-list query parameter is invalid."""

    def __init__(self, parameter: str, message: str):
        """Store the invalid query parameter alongside the message."""
        super().__init__(message)
        self.parameter = parameter


@dataclass(frozen=True)
class MediaListFilters:
    """Normalized query parameters shared by the API media-list endpoints."""

    statuses: tuple[str, ...] = ()
    include_no_status: bool = False
    search: str = ""
    rating: str = "all"
    collection: str = "all"
    progress: str = "all"
    genre: str = ""
    implied_genre: str = ""
    year: str = ""
    completed_date_from: str = ""
    completed_date_to: str = ""
    release: str = "all"
    source: str = ""
    media_status: str = ""
    language: str = ""
    country: str = ""
    platforms: tuple[str, ...] = ()
    platform_mode: str = "or"
    origin: str = ""
    format: str = ""
    author: str = ""
    provider: str = ""
    provider_region: str = ""
    pinned_providers: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    tag_mode: str = "or"
    sort: str = ""
    direction: str = ""
    exclude: tuple[str, ...] = ()
    media_type: str | None = None


@dataclass
class MediaListEntry:
    """An Item plus its user tracking row, if one exists."""

    item: Item
    media: object | None = None

    @property
    def item_id(self):
        """Return the tracked item's ID, or the underlying item ID."""
        return getattr(self.media, "item_id", None) or self.item.id


def _normalize(value) -> str:
    return str(value or "").strip().lower()


def normalize_completed_date_filter(value) -> str:
    """Return a YYYY-MM-DD string or empty string.

    Shared by the web list view, the API filters, and the SQL manager filter
    so `completed_date_from`/`completed_date_to` validate identically
    everywhere they're accepted.
    """
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        datetime.date.fromisoformat(normalized)
    except ValueError:
        return ""
    return normalized


def _split_values(values) -> list[str]:
    result = []
    for raw_value in values:
        result.extend(
            value.strip()
            for value in str(raw_value or "").split(",")
            if value.strip()
        )
    return result


def _parse_status_values(request) -> tuple[tuple[str, ...], bool]:
    raw_values = _split_values(request.query_params.getlist("status"))
    statuses = []
    include_no_status = False
    for raw_value in raw_values:
        normalized = _normalize(raw_value).replace("_", " ")
        if normalized == "all":
            continue
        if normalized == MEDIA_LIST_NO_STATUS.replace("_", " "):
            include_no_status = True
            continue
        status_value = MEDIA_LIST_STATUS_BY_CODE.get(normalized)
        if status_value is None:
            status_value = next(
                (
                    status.value
                    for status in Status
                    if _normalize(status.value) == normalized
                ),
                None,
            )
        if status_value is None:
            parameter = "status"
            message = "status must be a numeric code, status label, all, or no_status"
            raise MediaListFilterError(
                parameter,
                message,
            )
        if status_value not in statuses:
            statuses.append(status_value)
    return tuple(statuses), include_no_status


def _parse_choice(request, name: str, allowed: set[str], default: str) -> str:
    """Parse a lower-case choice query parameter."""
    value = _normalize(request.query_params.get(name, default)) or default
    if value not in allowed:
        raise MediaListFilterError(
            name,
            f"{name} must be one of: {', '.join(sorted(allowed))}",
        )
    return value


def _parse_sort(request) -> tuple[str, str]:
    raw_sort = _normalize(request.query_params.get("sort"))
    direction = _normalize(request.query_params.get("direction"))
    if raw_sort.endswith(("_asc", "_desc")):
        suffix = raw_sort.rsplit("_", 1)[1]
        raw_sort = raw_sort[: -(len(suffix) + 1)]
        if direction and direction != suffix:
            parameter = "direction"
            message = "direction conflicts with the sort suffix"
            raise MediaListFilterError(
                parameter,
                message,
            )
        direction = suffix
    if raw_sort and raw_sort not in MEDIA_LIST_SORTS:
        parameter = "sort"
        message = f"sort must be one of: {', '.join(sorted(MEDIA_LIST_SORTS))}"
        raise MediaListFilterError(
            parameter,
            message,
        )
    if direction and direction not in {"asc", "desc"}:
        parameter = "direction"
        message = "direction must be asc or desc"
        raise MediaListFilterError(parameter, message)
    if not direction:
        direction = "asc" if raw_sort in MEDIA_LIST_SORT_DEFAULTS_ASC else "desc"
    return raw_sort, direction


def parse_media_list_filters(request) -> MediaListFilters:
    """Parse the shared media-list query contract."""
    statuses, include_no_status = _parse_status_values(request)
    rating = _parse_choice(request, "rating", {"all", "rated", "not_rated"}, "all")
    collection = _parse_choice(
        request,
        "collection",
        {"all", "collected", "not_collected"},
        "all",
    )
    progress = _parse_choice(
        request,
        "progress",
        {"all", "caught_up", "not_caught_up"},
        "all",
    )
    release = _parse_choice(
        request,
        "release",
        {"all", "released", "not_released"},
        "all",
    )
    platform_mode = _parse_choice(
        request,
        "platform_mode",
        {"and", "or", "not"},
        "or",
    )
    tag_mode = _parse_choice(
        request,
        "tag_mode",
        {"and", "or", "not"},
        "or",
    )
    sort, direction = _parse_sort(request)
    tags = tuple(_split_values(request.query_params.getlist("tag")))
    tag_mode_value = tag_mode
    if not tags:
        legacy_tag_exclude = str(
            request.query_params.get("tag_exclude", "") or ""
        ).strip()
        if legacy_tag_exclude:
            tags = tuple(_split_values([legacy_tag_exclude]))
            tag_mode_value = "not"
    year = str(request.query_params.get("year", "") or "").strip()
    if (
        year
        and year != "unknown"
        and (not year.isdigit() or len(year) != MEDIA_LIST_YEAR_LENGTH)
    ):
        parameter = "year"
        message = "year must be a four-digit year or unknown"
        raise MediaListFilterError(parameter, message)
    completed_date_from_raw = str(
        request.query_params.get("completed_date_from", "") or ""
    ).strip()
    if completed_date_from_raw and not normalize_completed_date_filter(
        completed_date_from_raw,
    ):
        parameter = "completed_date_from"
        message = "completed_date_from must be a YYYY-MM-DD date"
        raise MediaListFilterError(parameter, message)
    completed_date_to_raw = str(
        request.query_params.get("completed_date_to", "") or ""
    ).strip()
    if completed_date_to_raw and not normalize_completed_date_filter(
        completed_date_to_raw,
    ):
        parameter = "completed_date_to"
        message = "completed_date_to must be a YYYY-MM-DD date"
        raise MediaListFilterError(parameter, message)
    return MediaListFilters(
        statuses=statuses,
        include_no_status=include_no_status,
        search=str(request.query_params.get("search", "") or "").strip(),
        rating=rating,
        collection=collection,
        progress=progress,
        genre=str(request.query_params.get("genre", "") or "").strip(),
        implied_genre=str(
            request.query_params.get("implied_genre", "") or ""
        ).strip(),
        year=year,
        completed_date_from=completed_date_from_raw,
        completed_date_to=completed_date_to_raw,
        release=release,
        source=str(request.query_params.get("source", "") or "").strip(),
        media_status=str(
            request.query_params.get("media_status", "") or ""
        ).strip(),
        language=str(request.query_params.get("language", "") or "").strip(),
        country=str(request.query_params.get("country", "") or "").strip(),
        platforms=tuple(_split_values(request.query_params.getlist("platform"))),
        platform_mode=platform_mode,
        origin=str(request.query_params.get("origin", "") or "").strip(),
        format=str(request.query_params.get("format", "") or "").strip(),
        author=str(request.query_params.get("author", "") or "").strip(),
        provider=str(request.query_params.get("provider", "") or "").strip(),
        provider_region=str(
            getattr(getattr(request, "user", None), "watch_provider_region", "")
            or ""
        ).strip(),
        pinned_providers=tuple(
            getattr(getattr(request, "user", None), "pinned_watch_providers", None)
            or ()
        ),
        tags=tags,
        tag_mode=tag_mode_value,
        sort=sort,
        direction=direction,
        exclude=tuple(_split_values(request.query_params.getlist("exclude"))),
    )


def _item_authors(item) -> list[str]:
    authors = getattr(item, "authors", None) or []
    if not isinstance(authors, list):
        authors = [authors]
    result = []
    for author_value in authors:
        selected_author = author_value
        if isinstance(selected_author, dict):
            selected_author = (
                selected_author.get("name")
                or selected_author.get("person")
                or selected_author.get("author")
            )
        if selected_author:
            result.append(str(selected_author).strip())
    return [author for author in result if author]


def _show_has_episode_collection(user, item, collected_ids) -> bool:
    if item.media_type not in {MediaTypes.TV.value, MediaTypes.ANIME.value}:
        return False
    return Item.objects.filter(
        media_type=MediaTypes.EPISODE.value,
        media_id=item.media_id,
        source=item.source,
        id__in=collected_ids,
    ).exists()


def _apply_status_filter(entries, filters):
    if not filters.statuses and not filters.include_no_status:
        return entries
    filtered = []
    for entry in entries:
        status = getattr(entry.media, "aggregated_status", None) or getattr(
            entry.media, "status", None
        )
        if (filters.include_no_status and status is None) or status in filters.statuses:
            filtered.append(entry)
    return filtered


def _apply_rating_filter(entries, rating):
    if rating == "all":
        return entries
    result = []
    for entry in entries:
        score = getattr(entry.media, "aggregated_score", None)
        if score is None:
            score = getattr(entry.media, "score", None)
        if (score is not None) == (rating == "rated"):
            result.append(entry)
    return result


def _apply_collection_filter(user, entries, collection):
    if collection == "all":
        return entries
    collected_ids = set(
        CollectionEntry.objects.filter(user=user).values_list("item_id", flat=True)
    )
    result = []
    for entry in entries:
        collected = entry.item.id in collected_ids or _show_has_episode_collection(
            user, entry.item, collected_ids
        )
        if (collection == "collected") == collected:
            result.append(entry)
    return result


def _apply_progress_filter(entries, progress, media_type):
    if progress == "all" or media_type not in {
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
    }:
        return entries
    tracked = [entry.media for entry in entries if entry.media is not None]
    if tracked:
        BasicMedia.objects.annotate_max_progress(tracked, media_type)
    return [
        entry
        for entry in entries
        if entry.media is not None
        and (
            helpers.is_caught_up_media(entry.media) == (progress == "caught_up")
        )
    ]


def apply_media_list_status_filter(entries, status_values):
    """Apply the shared latest-status and statusless-item semantics."""
    status_values = tuple(status_values or ())
    return _apply_status_filter(
        entries,
        MediaListFilters(
            statuses=tuple(
                value for value in status_values if value != MEDIA_LIST_NO_STATUS
            ),
            include_no_status=MEDIA_LIST_NO_STATUS in status_values,
        ),
    )


def apply_media_list_rating_filter(entries, rating):
    """Apply the shared rating filter to web or API list entries."""
    return _apply_rating_filter(entries, rating)


def apply_media_list_collection_filter(user, entries, collection):
    """Apply the shared collection filter to web or API list entries."""
    return _apply_collection_filter(user, entries, collection)


def apply_media_list_progress_filter(entries, progress, media_type):
    """Apply the shared released-progress filter to web or API entries."""
    return _apply_progress_filter(entries, progress, media_type)


def _episode_air_date(season, episode_number):
    events = getattr(getattr(season, "item", None), "prefetched_events", None)
    if events is None:
        from events.models import Event

        events = Event.objects.filter(
            item=season.item,
            content_number=episode_number,
        ).order_by("datetime")
    event = next(
        (
            event
            for event in events
            if getattr(event, "content_number", None) == episode_number
        ),
        None,
    )
    if event is not None and event.datetime:
        return event.datetime
    episodes = getattr(season, "episodes", None)
    if episodes is not None:
        episode = next(
            (
                episode
                for episode in episodes.all()
                if getattr(getattr(episode, "item", None), "episode_number", None)
                == episode_number
            ),
            None,
        )
        if episode is not None:
            return getattr(episode.item, "release_datetime", None)
    return None


def _enrich_next_episode(base, *, source, media_id):
    """Attach title/image/ids/url to a next_episode dict from a matching Item."""
    if base is None:
        return None
    episode_item = None
    if base.get("episode_number") is not None:
        episode_item = Item.objects.filter(
            source=source,
            media_id=media_id,
            media_type=MediaTypes.EPISODE.value,
            season_number=base.get("season_number"),
            episode_number=base.get("episode_number"),
        ).first()
    return {
        **base,
        "title": episode_item.title if episode_item else None,
        "image": episode_item.image if episode_item else None,
        "ids": helpers.build_provider_ids(episode_item) if episode_item else {},
        "url": (media_url(episode_item) or None) if episode_item else None,
    }


def next_episode_for_media(media):
    """Return the first released, unwatched episode for a TV-like row."""
    if media is None:
        return None
    item = getattr(media, "item", None)
    media_type = getattr(item, "media_type", None)
    if media_type == MediaTypes.TV.value:
        seasons = getattr(media, "seasons", None)
        if seasons is None:
            seasons = Season.objects.filter(related_tv=media).select_related("item")
        seasons = sorted(
            seasons.all() if hasattr(seasons, "all") else seasons,
            key=lambda season: getattr(season.item, "season_number", 0) or 0,
        )
        excluded_season_numbers = {
            season.item.season_number
            for season in seasons
            if getattr(season, "item", None)
            and season.item.season_number not in (None, 0)
        }
        for season in seasons:
            season_number = getattr(season.item, "season_number", None)
            if season_number in (None, 0) or season.status in {
                Status.DROPPED.value,
                Status.PAUSED.value,
            }:
                continue
            episode_number = season.next_episode_number()
            if episode_number is not None:
                return _enrich_next_episode(
                    {
                        "season_number": season_number,
                        "episode_number": episode_number,
                        "air_date": _episode_air_date(season, episode_number),
                    },
                    source=item.source,
                    media_id=item.media_id,
                )
        from events.models import Event

        untracked_events = (
            Event.objects.filter(
                item__media_type=MediaTypes.SEASON.value,
                item__media_id=item.media_id,
                item__source=item.source,
                content_number__isnull=False,
                datetime__lte=timezone.now(),
            )
            .exclude(item__season_number=0)
            .exclude(item__season_number__in=excluded_season_numbers)
            .order_by("item__season_number", "content_number", "datetime")
        )
        event = untracked_events.first()
        if event is not None:
            return _enrich_next_episode(
                {
                    "season_number": event.item.season_number,
                    "episode_number": event.content_number,
                    "air_date": event.datetime,
                },
                source=item.source,
                media_id=item.media_id,
            )
        return None
    if media_type == MediaTypes.SEASON.value and hasattr(media, "next_episode_number"):
        episode_number = media.next_episode_number()
        if episode_number is None:
            return None
        return _enrich_next_episode(
            {
                "season_number": getattr(item, "season_number", None),
                "episode_number": episode_number,
                "air_date": _episode_air_date(media, episode_number),
            },
            source=item.source,
            media_id=item.media_id,
        )
    if media_type == MediaTypes.ANIME.value:
        from events.models import Event

        progress = int(getattr(media, "progress", 0) or 0)
        event = (
            Event.objects.filter(
                item=item,
                content_number__gt=progress,
                datetime__lte=timezone.now(),
            )
            .exclude(datetime__year__lt=1900)
            .order_by("content_number", "datetime")
            .first()
        )
        if event is not None:
            return _enrich_next_episode(
                {
                    "season_number": None,
                    "episode_number": event.content_number,
                    "air_date": event.datetime,
                },
                source=item.source,
                media_id=item.media_id,
            )
    return None


def _sort_value(entry, sort, next_episode):
    media = entry.media
    item = entry.item
    if sort in {"title", ""}:
        return getattr(item, "title", "").lower()
    if sort == "score":
        score = getattr(media, "aggregated_score", None)
        return score if score is not None else getattr(media, "score", None)
    if sort == "critic_rating":
        return getattr(item, "provider_rating", None)
    if sort == "popularity":
        return getattr(item, "trakt_popularity_rank", None)
    if sort in {"progress", "plays"}:
        progress = getattr(media, "aggregated_progress", None)
        return progress if progress is not None else getattr(media, "progress", 0)
    if sort == "runtime":
        return getattr(media, "total_runtime_minutes", None)
    if sort == "time_watched":
        return getattr(media, "time_watched_minutes", None)
    if sort == "time_to_beat":
        return getattr(item, "game_time_to_beat_minutes", None)
    if sort == "platform":
        return _normalize(next(iter(getattr(item, "platforms", None) or []), ""))
    if sort == "author":
        return _normalize(_item_authors(item)[0] if _item_authors(item) else "")
    if sort in {"release_date", "release_datetime"}:
        return getattr(item, "release_datetime", None)
    if sort in {"date_added", "added", "created_at"}:
        return getattr(media, "created_at", None)
    if sort in {"start_date", "started"}:
        return getattr(media, "aggregated_start_date", None) or getattr(
            media, "start_date", None
        )
    if sort in {"end_date", "ended"}:
        return getattr(media, "aggregated_end_date", None) or getattr(
            media, "end_date", None
        )
    if sort in {"updated", "progressed_at"}:
        return getattr(media, "progressed_at", None)
    if sort == "next_episode_air_date":
        return next_episode.get("air_date") if next_episode else None
    if sort == "time_left":
        max_progress = getattr(media, "max_progress", None)
        if max_progress is None:
            return None
        return max_progress - int(getattr(media, "progress", 0) or 0)
    if sort in {"id", "itemid", "mediaid"}:
        return str(getattr(item, "media_id", ""))
    if sort == "source":
        return getattr(item, "source", "")
    if sort == "type":
        return getattr(item, "media_type", "")
    return getattr(item, "title", "").lower()


def media_list_media_types(filters: MediaListFilters, media_type) -> tuple[str, ...]:
    """Return the libraries a media-list request covers.

    The root endpoint spans every list type except seasons and episodes (they
    belong to their shows) and any the client excluded.
    """
    if media_type is not None:
        return (media_type,)
    return tuple(
        current_type
        for current_type in MEDIA_LIST_MEDIA_TYPES
        if current_type not in {MediaTypes.SEASON.value, MediaTypes.EPISODE.value}
        and current_type not in filters.exclude
    )


def media_list_entries_for_items(user, items) -> list[MediaListEntry]:
    """Attach each item's tracker row for a page of items.

    The row shown is the item's newest, with duplicate rows (repeat viewings)
    aggregated onto it and the list prefetches applied - for this page only.
    Items without a row (collected but untracked) have no media.
    """
    item_ids_by_type: dict[str, list[int]] = {}
    for item in items:
        item_ids_by_type.setdefault(item.media_type, []).append(item.pk)
    media_by_item_id = {}
    for media_type, item_ids in item_ids_by_type.items():
        model = apps.get_model("app", media_type)
        if media_type == MediaTypes.EPISODE.value:
            owner = {"related_season__user": user}
            # Episode cards read max_progress and status through their season.
            related = (
                "item",
                "related_season",
                "related_season__item",
                "related_season__related_tv",
                "related_season__related_tv__item",
            )
        else:
            owner = {"user": user}
            related = ("item",)
        rows = model.objects.filter(item_id__in=item_ids, **owner).select_related(*related)
        rows = list(BasicMedia.objects._apply_prefetch_related(rows, media_type, list_mode=True))
        if media_type != MediaTypes.EPISODE.value:
            BasicMedia.objects._aggregate_duplicate_data(rows, user, media_type)
        for media in sorted(rows, key=lambda row: (row.created_at, row.pk)):
            media_by_item_id[media.item_id] = media
    # A tracked entry keeps its row's own item: the prefetches (events, tags)
    # hang off that instance.
    return [
        MediaListEntry(
            item=media.item if media is not None else item,
            media=media,
        )
        for item in items
        for media in [media_by_item_id.get(item.pk)]
    ]


def get_media_list_entries(user, media_type, filters: MediaListFilters, *, limit=None, offset=None):
    """Return ``(entries, total)`` for one page of a media list.

    Evaluated by the shared library-query engine: SQL-capable filters and
    sorts page in the database, anything else in bounded batches; only the
    returned page is hydrated. ``limit=None`` returns every match.
    """
    from app.library_query import LibraryQueryExecutor
    from app.library_query.adapters import from_media_list_filters

    if media_type is not None and media_type not in MEDIA_LIST_MEDIA_TYPES:
        parameter = "media_type"
        message = "Unsupported media type"
        raise MediaListFilterError(parameter, message)
    filters = replace(filters, media_type=media_type)
    query = from_media_list_filters(filters, media_list_media_types(filters, media_type))
    executor = LibraryQueryExecutor(user, query)
    offset = offset or 0
    if limit is None:
        total = executor.count()
        page = executor.page(offset, max(total - offset, 0), total=total)
    else:
        page = executor.page(offset, limit)
    return media_list_entries_for_items(user, page.items), page.total


def get_next_episode_map(entries):
    """Build the next-episode payload map used by media serializers."""
    return {
        entry.item.id: next_episode_for_media(entry.media)
        for entry in entries
        if entry.media is not None
    }
