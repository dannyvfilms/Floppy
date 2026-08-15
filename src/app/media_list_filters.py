"""Shared media-list filtering and next-episode resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace

from django.apps import apps
from django.db.models import Q
from django.utils import timezone

from app import helpers
from app.models import (
    BasicMedia,
    CollectionEntry,
    Episode,
    Item,
    ItemTag,
    MediaTypes,
    Season,
    Status,
)
from app.providers import tmdb
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
        tags=tags,
        tag_mode=tag_mode_value,
        sort=sort,
        direction=direction,
        exclude=tuple(_split_values(request.query_params.getlist("exclude"))),
    )


def _item_languages(item) -> list[str]:
    languages = getattr(item, "languages", None) or []
    if not isinstance(languages, list):
        languages = [languages]
    return [str(value).strip() for value in languages if str(value).strip()]


def _item_platforms(item, collection_platforms: dict[int, set[str]]) -> set[str]:
    collected = collection_platforms.get(item.id, set())
    if collected:
        return {_normalize(value) for value in collected}
    platforms = getattr(item, "platforms", None) or []
    if not isinstance(platforms, list):
        platforms = [platforms]
    return {_normalize(value) for value in platforms if str(value).strip()}


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


def _item_formats(item, collection_formats: dict[int, set[str]]) -> set[str]:
    formats = set()
    item_format = getattr(item, "format", None)
    if item_format:
        formats.add(_normalize(item_format))
    formats.update(_normalize(value) for value in collection_formats.get(item.id, set()))
    return formats


def _tag_item_ids(user, tags: tuple[str, ...], mode: str):
    if not tags:
        return None, None
    tag_id_sets = [
        set(
            ItemTag.objects.filter(
                tag__user=user,
                tag__name__iexact=tag,
            ).values_list("item_id", flat=True),
        )
        for tag in tags
    ]
    if mode == "and":
        return set.intersection(*tag_id_sets), None
    if mode == "not":
        return None, set.union(*tag_id_sets)
    return set.union(*tag_id_sets), None


def _collection_context(user, entries):
    item_ids = {entry.item.id for entry in entries}
    collected_ids = set(
        CollectionEntry.objects.filter(
            user=user,
            item_id__in=item_ids,
        ).values_list("item_id", flat=True),
    )
    collection_platforms = {}
    collection_formats = {}
    for item_id, value in CollectionEntry.objects.filter(
        user=user,
        item_id__in=item_ids,
    ).values_list("item_id", "resolution"):
        if value:
            collection_platforms.setdefault(item_id, set()).add(value)
    for item_id, value in CollectionEntry.objects.filter(
        user=user,
        item_id__in=item_ids,
    ).exclude(media_type="").values_list("item_id", "media_type"):
        if value:
            collection_formats.setdefault(item_id, set()).add(value)
    return collected_ids, collection_platforms, collection_formats


def _show_has_episode_collection(user, item, collected_ids) -> bool:
    if item.media_type not in {MediaTypes.TV.value, MediaTypes.ANIME.value}:
        return False
    return Item.objects.filter(
        media_type=MediaTypes.EPISODE.value,
        media_id=item.media_id,
        source=item.source,
        id__in=collected_ids,
    ).exists()


def _matches_metadata(entry, filters, collection_platforms, collection_formats, tag_ids):
    item = entry.item
    if filters.search:
        needle = _normalize(filters.search)
        if needle not in _normalize(item.title) and needle not in _normalize(item.media_id):
            return False
    if filters.genre and not any(
        _normalize(filters.genre) == _normalize(value)
        for value in (getattr(item, "genres", None) or [])
    ):
        return False
    if filters.implied_genre and filters.media_type not in {
        None,
        MediaTypes.MUSIC.value,
    }:
        pass
    elif filters.implied_genre and (
        item.media_type != MediaTypes.MUSIC.value
        or not any(
            _normalize(filters.implied_genre) == _normalize(value)
            for value in (getattr(item, "implied_genres", None) or [])
        )
    ):
        return False
    if filters.year:
        release_datetime = getattr(item, "release_datetime", None)
        if _normalize(filters.year) == "unknown":
            if release_datetime is not None:
                return False
        elif str(getattr(release_datetime, "year", "")) != filters.year:
            return False
    if filters.release != "all":
        release_datetime = getattr(item, "release_datetime", None)
        released = bool(
            release_datetime and release_datetime.date() <= timezone.localdate()
        )
        if filters.release == "released" and not released:
            return False
        if filters.release == "not_released" and released:
            return False
    if filters.source and item.source != filters.source:
        return False
    if filters.media_status and getattr(item, "status", "") != filters.media_status:
        return False
    if filters.language and filters.media_type not in {
        None,
        *MEDIA_LIST_LANGUAGE_TYPES,
    }:
        pass
    elif filters.language and not any(
        _normalize(filters.language) == _normalize(value)
        for value in _item_languages(item)
    ):
        return False
    if filters.country and _normalize(filters.country) != _normalize(
        getattr(item, "country", "")
    ):
        return False
    if filters.platforms and filters.media_type not in {None, MediaTypes.GAME.value}:
        pass
    elif filters.platforms:
        if item.media_type != MediaTypes.GAME.value:
            return False
        platforms = _item_platforms(item, collection_platforms)
        requested = {_normalize(value) for value in filters.platforms}
        if filters.platform_mode == "and" and not requested.issubset(platforms):
            return False
        if filters.platform_mode == "not" and platforms.intersection(requested):
            return False
        if filters.platform_mode == "or" and not platforms.intersection(requested):
            return False
    if filters.origin and _normalize(filters.origin) != _normalize(
        getattr(item, "country", "")
    ):
        return False
    if filters.format and filters.media_type not in {None, *MEDIA_LIST_AUTHOR_TYPES}:
        pass
    elif filters.format and _normalize(filters.format) not in _item_formats(
        item, collection_formats
    ):
        return False
    if filters.author and filters.media_type not in {None, *MEDIA_LIST_AUTHOR_TYPES}:
        pass
    elif filters.author and not any(
        _normalize(filters.author) == _normalize(value) for value in _item_authors(item)
    ):
        return False
    if filters.provider and filters.media_type not in {
        None,
        *MEDIA_LIST_PROVIDER_TYPES,
    }:
        pass
    elif filters.provider:
        providers = (
            tmdb.item_watch_provider_names(item, filters.provider_region)
            if filters.provider_region
            else []
        )
        if not any(_normalize(filters.provider) == _normalize(value) for value in providers):
            return False
    if tag_ids[0] is not None and item.id not in tag_ids[0]:
        return False
    return tag_ids[1] is None or item.id not in tag_ids[1]


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
                return {
                    "season_number": season_number,
                    "episode_number": episode_number,
                    "air_date": _episode_air_date(season, episode_number),
                }
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
            return {
                "season_number": event.item.season_number,
                "episode_number": event.content_number,
                "air_date": event.datetime,
            }
        return None
    if media_type == MediaTypes.SEASON.value and hasattr(media, "next_episode_number"):
        episode_number = media.next_episode_number()
        if episode_number is None:
            return None
        return {
            "season_number": getattr(item, "season_number", None),
            "episode_number": episode_number,
            "air_date": _episode_air_date(media, episode_number),
        }
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
            return {
                "season_number": None,
                "episode_number": event.content_number,
                "air_date": event.datetime,
            }
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


def _sort_entries(entries, filters, media_type):
    if not filters.sort:
        return entries
    if media_type in {MediaTypes.TV.value, MediaTypes.ANIME.value} or filters.sort in {
        "next_episode_air_date",
        "time_left",
    }:
        tracked = [entry.media for entry in entries if entry.media is not None]
        if tracked:
            BasicMedia.objects.annotate_max_progress(tracked, media_type)
    next_episode_by_item_id = {
        entry.item.id: next_episode_for_media(entry.media)
        for entry in entries
        if entry.media is not None
    }
    reverse = filters.direction == "desc"
    with_values = []
    without_values = []
    for entry in entries:
        value = _sort_value(entry, filters.sort, next_episode_by_item_id.get(entry.item.id))
        if value is None:
            without_values.append(entry)
        else:
            with_values.append((value, entry))
    with_values.sort(key=lambda pair: (pair[0], getattr(pair[1].item, "title", "").lower()), reverse=reverse)
    without_values.sort(
        key=lambda entry: getattr(entry.item, "title", "").lower(),
        reverse=reverse,
    )
    return [entry for _, entry in with_values] + without_values


def _statusless_entries(user, media_type, filters, tracked_item_ids):
    if not filters.include_no_status:
        return []
    if media_type == MediaTypes.EPISODE.value:
        return []
    model_names = {media_type}
    if media_type == MediaTypes.ANIME.value:
        model_names.add(MediaTypes.TV.value)
    statusless_ids = set()
    for model_name in model_names:
        model = apps.get_model("app", model_name)
        statusless_ids.update(
            model.objects.filter(user=user, status__isnull=True).values_list(
                "item_id", flat=True
            )
        )
    collected_ids = set(
        CollectionEntry.objects.filter(user=user).values_list("item_id", flat=True)
    )
    candidate_ids = (statusless_ids | collected_ids) - set(tracked_item_ids)
    if media_type in {MediaTypes.TV.value, MediaTypes.ANIME.value}:
        episode_pairs = Item.objects.filter(
            id__in=collected_ids,
            media_type=MediaTypes.EPISODE.value,
        ).values_list("media_id", "source")
        candidate_ids.update(
            Item.objects.filter(
                media_type__in=(MediaTypes.TV.value, MediaTypes.ANIME.value),
                media_id__in={media_id for media_id, _source in episode_pairs},
                source__in={source for _media_id, source in episode_pairs},
            ).values_list("id", flat=True)
        )
        candidate_ids -= set(tracked_item_ids)
    if not candidate_ids:
        return []
    items = Item.objects.filter(id__in=candidate_ids)
    if media_type == MediaTypes.ANIME.value:
        items = items.filter(
            Q(media_type=MediaTypes.ANIME.value)
            | Q(
                media_type=MediaTypes.TV.value,
                library_media_type=MediaTypes.ANIME.value,
            )
        )
        library_mode = getattr(user, "anime_library_mode", MediaTypes.ANIME.value)
        if library_mode not in {MediaTypes.ANIME.value, "both"}:
            items = items.filter(media_type=MediaTypes.ANIME.value)
    elif media_type == MediaTypes.TV.value:
        items = items.filter(media_type=MediaTypes.TV.value)
        library_mode = getattr(user, "anime_library_mode", MediaTypes.ANIME.value)
        if library_mode != "both":
            items = items.exclude(library_media_type=MediaTypes.ANIME.value)
    else:
        items = items.filter(media_type=media_type)
    return [MediaListEntry(item=item) for item in items]


def _get_media_entries_for_type(user, media_type, filters):
    if media_type == MediaTypes.EPISODE.value:
        queryset = Episode.objects.filter(related_season__user=user).select_related("item")
        if filters.statuses:
            queryset = queryset.filter(related_season__status__in=filters.statuses)
        if filters.search:
            queryset = queryset.filter(item__title__icontains=filters.search)
        return [MediaListEntry(item=episode.item, media=episode) for episode in queryset]

    model_media_type = media_type
    queryset = BasicMedia.objects.get_media_list(
        user=user,
        media_type=model_media_type,
        status_filter=filters.statuses,
        sort_filter="",
        search=filters.search,
        list_sql_filters={
            "genre": filters.genre,
            "implied_genre": filters.implied_genre,
            "year": filters.year,
            "release": filters.release,
            "source": filters.source,
            "media_status": filters.media_status,
            "language": filters.language,
            "country": filters.country,
            "platform_values": filters.platforms,
            "platform_mode": filters.platform_mode,
            "tag_included_ids": None,
            "tag_excluded_ids": None,
        },
    )
    entries = [MediaListEntry(item=media.item, media=media) for media in queryset]
    if media_type == MediaTypes.TV.value:
        library_mode = getattr(user, "anime_library_mode", MediaTypes.ANIME.value)
        if library_mode != "both":
            entries = [
                entry
                for entry in entries
                if getattr(entry.item, "library_media_type", None) != MediaTypes.ANIME.value
            ]
    if media_type == MediaTypes.ANIME.value:
        library_mode = getattr(user, "anime_library_mode", MediaTypes.ANIME.value)
        if library_mode in {MediaTypes.ANIME.value, "both"}:
            grouped = BasicMedia.objects.get_media_list(
                user=user,
                media_type=MediaTypes.TV.value,
                status_filter=filters.statuses,
                sort_filter="",
                search=filters.search,
                list_sql_filters={
                    "genre": filters.genre,
                    "implied_genre": filters.implied_genre,
                    "year": filters.year,
                    "release": filters.release,
                    "source": filters.source,
                    "media_status": filters.media_status,
                    "language": filters.language,
                    "country": filters.country,
                    "platform_values": filters.platforms,
                    "platform_mode": filters.platform_mode,
                },
            )
            entries.extend(
                MediaListEntry(item=media.item, media=media)
                for media in grouped
                if getattr(media.item, "library_media_type", None) == MediaTypes.ANIME.value
            )
    tracked_item_ids = {entry.item.id for entry in entries}
    entries.extend(_statusless_entries(user, media_type, filters, tracked_item_ids))
    return entries


def _get_media_entries(user, media_type, filters):
    if media_type is not None:
        return _get_media_entries_for_type(user, media_type, filters)

    entries = []
    for current_type in MEDIA_LIST_MEDIA_TYPES:
        if current_type in {
            MediaTypes.SEASON.value,
            MediaTypes.EPISODE.value,
        } or current_type in filters.exclude:
            continue
        entries.extend(_get_media_entries_for_type(user, current_type, filters))
    return entries


def get_media_list_entries(user, media_type, filters: MediaListFilters):
    """Return API media-list entries with web-compatible filtering and sorting."""
    if media_type is not None and media_type not in MEDIA_LIST_MEDIA_TYPES:
        parameter = "media_type"
        message = "Unsupported media type"
        raise MediaListFilterError(parameter, message)
    filters = replace(filters, media_type=media_type)
    entries = _get_media_entries(user, media_type, filters)
    tag_ids = _tag_item_ids(user, filters.tags, filters.tag_mode)
    _, collection_platforms, collection_formats = _collection_context(user, entries)
    entries = [
        entry
        for entry in entries
        if _matches_metadata(entry, filters, collection_platforms, collection_formats, tag_ids)
    ]
    entries = _apply_status_filter(entries, filters)
    entries = _apply_rating_filter(entries, filters.rating)
    entries = _apply_collection_filter(user, entries, filters.collection)
    entries = _apply_progress_filter(entries, filters.progress, media_type)
    return _sort_entries(entries, filters, media_type)


def get_next_episode_map(entries):
    """Build the next-episode payload map used by media serializers."""
    return {
        entry.item.id: next_episode_for_media(entry.media)
        for entry in entries
        if entry.media is not None
    }
