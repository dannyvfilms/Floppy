"""Smart list rule normalization, option building, and item matching."""

from __future__ import annotations

import datetime
from collections.abc import Iterable

from django.apps import apps
from django.db.models import Q
from django.utils import timezone

from app.models import CollectionEntry, Item, ItemTag, MediaTypes, Sources, Status
from app.providers import tmdb

SMART_FILTER_KEYS = (
    "status",
    "rating",
    "rating_min",
    "rating_max",
    "collection",
    "genre",
    "implied_genre",
    "year",
    "release",
    "release_date_from",
    "release_date_to",
    "date_added_from",
    "date_added_to",
    "source",
    "search",
    "sort",
    "sort_direction",
    "language",
    "country",
    "platform",
    "origin",
    "format",
    "author",
    "provider",
    "tag",
    "tag_mode",
)

TAG_MODE_CHOICES = {"and", "or", "not"}

SMART_FILTER_DEFAULTS = {
    "status": [],
    "rating": "all",
    "rating_min": "",
    "rating_max": "",
    "collection": "all",
    "genre": "",
    "implied_genre": "",
    "year": "",
    "release": "all",
    "release_date_from": "",
    "release_date_to": "",
    "date_added_from": "",
    "date_added_to": "",
    "source": "",
    "search": "",
    "sort": "",
    "sort_direction": "",
    "language": "",
    "country": "",
    "platform": "",
    "origin": "",
    "format": "",
    "author": "",
    "provider": "",
    "tag": [],
    "tag_mode": "or",
}

MAX_RATING = 10.0

# Language/country/origin codes at or below this length (e.g. ISO 639-1
# language codes, ISO 3166 country codes) are displayed uppercased.
SHORT_CODE_MAX_LENGTH = 3

RATING_CHOICES = {"all", "rated", "not_rated"}
COLLECTION_CHOICES = {"all", "collected", "not_collected"}
RELEASE_CHOICES = {"all", "released", "not_released"}
SHOW_COLLECTION_MEDIA_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.ANIME.value,
    MediaTypes.SEASON.value,
}
LANGUAGE_MEDIA_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.MOVIE.value,
    MediaTypes.ANIME.value,
    MediaTypes.PODCAST.value,
}
COUNTRY_MEDIA_TYPES = LANGUAGE_MEDIA_TYPES
PLATFORM_MEDIA_TYPES = {MediaTypes.GAME.value}
PROVIDER_MEDIA_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.MOVIE.value,
    MediaTypes.ANIME.value,
}
ORIGIN_MEDIA_TYPES = {MediaTypes.MUSIC.value}
FORMAT_MEDIA_TYPES = {
    MediaTypes.BOOK.value,
    MediaTypes.MANGA.value,
    MediaTypes.COMIC.value,
}
AUTHOR_MEDIA_TYPES = FORMAT_MEDIA_TYPES


def _normalize_filter_value(value) -> str:
    return str(value or "").strip().lower()


def _normalize_decimal_value(value) -> str:
    """Return a rating value string in [0.0, 10.0] or empty string."""
    if not value and value != 0:
        return ""
    try:
        normalized = round(float(str(value).strip()), 1)
    except (TypeError, ValueError):
        return ""
    if 0.0 <= normalized <= MAX_RATING:
        return str(normalized)
    return ""


def _normalize_date_filter(value) -> str:
    """Return a YYYY-MM-DD string or empty string."""
    if not value:
        return ""
    normalized = str(value).strip()
    try:
        datetime.date.fromisoformat(normalized)
    except ValueError:
        return ""
    return normalized


def _release_date_from_value(value):
    if value is None:
        return None
    if isinstance(value, datetime.date) and not hasattr(value, "hour"):
        return value
    if hasattr(value, "date"):
        try:
            if hasattr(value, "utcoffset") and timezone.is_aware(value):
                return timezone.localtime(value).date()
        except Exception:  # noqa: S110  # deliberate best-effort; failure is non-fatal here
            pass
        try:
            return value.date()
        except Exception:
            return None
    return None


def _matches_release_filter_value(release_value, filter_value: str, today):
    if filter_value == "all":
        return True
    release_date = _release_date_from_value(release_value)
    if not release_date:
        return filter_value == "not_released"
    if filter_value == "released":
        return release_date <= today
    if filter_value == "not_released":
        return release_date > today
    return True


def _extract_languages(item: Item) -> list[str]:
    languages = getattr(item, "languages", None) or []
    if isinstance(languages, list):
        return [str(value).strip() for value in languages if str(value).strip()]
    language_value = str(languages).strip()
    return [language_value] if language_value else []


def _extract_country(item: Item) -> str:
    country = getattr(item, "country", "")
    return str(country).strip()


def _extract_platforms(item: Item) -> list[str]:
    platforms = getattr(item, "platforms", None) or []
    if isinstance(platforms, list):
        return [str(value).strip() for value in platforms if str(value).strip()]
    platform_value = str(platforms).strip()
    return [platform_value] if platform_value else []


def _extract_item_providers(item: Item, region) -> list[str] | None:
    """Return watch-provider names for an item, or None if region is unset."""
    return tmdb.item_watch_provider_names(item, region)


def _extract_authors(item: Item) -> list[str]:
    authors = getattr(item, "authors", None) or []
    if not isinstance(authors, list):
        authors = [authors]

    normalized: list[str] = []
    for raw_author in authors:
        if isinstance(raw_author, dict):
            author_name = (
                raw_author.get("name")
                or raw_author.get("person")
                or raw_author.get("author")
            )
        else:
            author_name = raw_author
        author_value = str(author_name).strip() if author_name else ""
        if author_value:
            normalized.append(author_value)
    return normalized


def _payload_get(payload, key: str, default=""):
    if hasattr(payload, "get"):
        return payload.get(key, default)
    if isinstance(payload, dict):
        return payload.get(key, default)
    return default


def _payload_getlist(payload, key: str) -> list[str]:
    if hasattr(payload, "getlist"):
        return [str(value) for value in payload.getlist(key)]

    if isinstance(payload, dict):
        value = payload.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable):
            return [str(entry) for entry in value]
        return [str(value)]

    return []


def get_available_media_types(owner) -> list[str]:
    """Return enabled media types that can participate in smart rules."""
    if owner and hasattr(owner, "get_enabled_media_types"):
        enabled = list(owner.get_enabled_media_types())
    else:
        enabled = [
            media_type
            for media_type in MediaTypes.values
            if media_type != MediaTypes.EPISODE.value
        ]

    # Keep list smart rules at show/media granularity.
    enabled = [
        media_type for media_type in enabled if media_type != MediaTypes.EPISODE.value
    ]

    # Remove duplicates while preserving order.
    deduped = []
    seen = set()
    for media_type in enabled:
        if media_type not in MediaTypes.values:
            continue
        if media_type in seen:
            continue
        seen.add(media_type)
        deduped.append(media_type)
    return deduped


def normalize_rule_payload(payload, owner):
    """Normalize and validate smart-rule payload for persistence/matching."""
    available_media_types = get_available_media_types(owner)

    selected_media_types = _payload_getlist(payload, "media_types") or _payload_getlist(
        payload,
        "type",
    )
    normalized_media_types = []
    seen = set()
    for media_type in selected_media_types:
        value = str(media_type).strip().lower()
        if value not in available_media_types:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized_media_types.append(value)

    status_values = _payload_getlist(payload, "status")
    if not status_values:
        legacy_status = str(_payload_get(payload, "status", "") or "").strip()
        if legacy_status and legacy_status.lower() != "all":
            status_values = [legacy_status]
    normalized_statuses = []
    seen_statuses = set()
    for value in status_values:
        value = str(value).strip()  # noqa: PLW2901  # deliberate in-loop normalisation
        if not value or value.lower() == "all" or value not in Status.values:
            continue
        if value in seen_statuses:
            continue
        seen_statuses.add(value)
        normalized_statuses.append(value)

    rating = str(_payload_get(payload, "rating", "all") or "all").strip().lower()
    if rating not in RATING_CHOICES:
        rating = "all"
    rating_min = _normalize_decimal_value(_payload_get(payload, "rating_min", ""))
    rating_max = _normalize_decimal_value(_payload_get(payload, "rating_max", ""))

    collection = (
        str(_payload_get(payload, "collection", "all") or "all").strip().lower()
    )
    if collection not in COLLECTION_CHOICES:
        collection = "all"

    release = str(_payload_get(payload, "release", "all") or "all").strip().lower()
    if release not in RELEASE_CHOICES:
        release = "all"
    release_date_from = _normalize_date_filter(
        _payload_get(payload, "release_date_from", "")
    )
    release_date_to = _normalize_date_filter(
        _payload_get(payload, "release_date_to", "")
    )
    date_added_from = _normalize_date_filter(
        _payload_get(payload, "date_added_from", "")
    )
    date_added_to = _normalize_date_filter(_payload_get(payload, "date_added_to", ""))

    year = str(_payload_get(payload, "year", "") or "").strip().lower()
    if year and year != "unknown" and not year.isdigit():
        year = ""

    source = str(_payload_get(payload, "source", "") or "").strip().lower()
    if source and source not in Sources.values:
        source = ""
    sort = str(_payload_get(payload, "sort", "") or "").strip()
    sort_direction = (
        str(_payload_get(payload, "sort_direction", "") or "").strip().lower()
    )
    if sort_direction not in {"asc", "desc"}:
        sort_direction = ""

    tag_values = [
        str(value).strip()
        for value in _payload_getlist(payload, "tag")
        if str(value).strip()
    ]
    tag_mode = str(_payload_get(payload, "tag_mode", "") or "").strip().lower()
    if not tag_values:
        legacy_tag_exclude = str(_payload_get(payload, "tag_exclude", "") or "").strip()
        if legacy_tag_exclude:
            tag_values = [legacy_tag_exclude]
            tag_mode = "not"
    if tag_mode not in TAG_MODE_CHOICES:
        tag_mode = "or"
    seen_tags = set()
    deduped_tags = []
    for value in tag_values:
        key = value.lower()
        if key in seen_tags:
            continue
        seen_tags.add(key)
        deduped_tags.append(value)

    return {
        "media_types": normalized_media_types,
        "status": normalized_statuses,
        "rating": rating,
        "rating_min": rating_min,
        "rating_max": rating_max,
        "collection": collection,
        "genre": str(_payload_get(payload, "genre", "") or "").strip(),
        "implied_genre": str(_payload_get(payload, "implied_genre", "") or "").strip(),
        "year": year,
        "release": release,
        "release_date_from": release_date_from,
        "release_date_to": release_date_to,
        "date_added_from": date_added_from,
        "date_added_to": date_added_to,
        "source": source,
        "search": str(_payload_get(payload, "search", "") or "").strip(),
        "sort": sort,
        "sort_direction": sort_direction,
        "language": str(_payload_get(payload, "language", "") or "").strip(),
        "country": str(_payload_get(payload, "country", "") or "").strip(),
        "platform": str(_payload_get(payload, "platform", "") or "").strip(),
        "origin": str(_payload_get(payload, "origin", "") or "").strip(),
        "format": str(_payload_get(payload, "format", "") or "").strip(),
        "author": str(_payload_get(payload, "author", "") or "").strip(),
        "provider": str(_payload_get(payload, "provider", "") or "").strip(),
        "tag": deduped_tags,
        "tag_mode": tag_mode,
    }


def normalize_list_rules(custom_list) -> dict:
    """Return normalized rules for a smart list, including excluded media types."""
    normalized_rules = normalize_rule_payload(
        {
            "media_types": custom_list.smart_media_types or [],
            **(custom_list.smart_filters or {}),
        },
        custom_list.owner,
    )

    excluded_media_types = {
        media_type
        for media_type in (custom_list.smart_excluded_media_types or [])
        if media_type in MediaTypes.values
    }
    if excluded_media_types:
        if normalized_rules["media_types"]:
            normalized_rules["media_types"] = [
                media_type
                for media_type in normalized_rules["media_types"]
                if media_type not in excluded_media_types
            ]
        else:
            normalized_rules["media_types"] = [
                media_type
                for media_type in get_available_media_types(custom_list.owner)
                if media_type not in excluded_media_types
            ]

    return normalized_rules


def _base_media_queryset(
    owner,
    media_type: str,
    status_filter: list[str] | str = "all",
    search_query: str = "",
    date_added_from: str = "",
    date_added_to: str = "",
):
    if isinstance(status_filter, str):
        status_filters = [] if status_filter in ("", "all") else [status_filter]
    else:
        status_filters = [
            value for value in (status_filter or []) if value and value != "all"
        ]

    model = apps.get_model("app", media_type)
    if media_type == MediaTypes.EPISODE.value:
        queryset = model.objects.filter(related_season__user=owner)
        if status_filters:
            queryset = queryset.filter(related_season__status__in=status_filters)
    else:
        queryset = model.objects.filter(user=owner)
        if status_filters:
            queryset = queryset.filter(status__in=status_filters)

    if search_query:
        queryset = queryset.filter(item__title__icontains=search_query)
    if date_added_from:
        queryset = queryset.filter(created_at__date__gte=date_added_from)
    if date_added_to:
        queryset = queryset.filter(created_at__date__lte=date_added_to)

    return queryset.select_related("item")


def _target_media_types(owner, rules_media_types: list[str]) -> list[str]:
    available = get_available_media_types(owner)
    if rules_media_types:
        return [
            media_type for media_type in rules_media_types if media_type in available
        ]
    return available


def _matches_item_filters(item: Item, rules: dict, today, region=None) -> bool:
    genre_filter = _normalize_filter_value(rules.get("genre"))
    implied_genre_filter = _normalize_filter_value(rules.get("implied_genre"))
    year_filter = _normalize_filter_value(rules.get("year"))
    source_filter = _normalize_filter_value(rules.get("source"))
    language_filter = _normalize_filter_value(rules.get("language"))
    country_filter = _normalize_filter_value(rules.get("country"))
    platform_filter = _normalize_filter_value(rules.get("platform"))
    origin_filter = _normalize_filter_value(rules.get("origin"))
    release_filter = _normalize_filter_value(rules.get("release") or "all")

    if genre_filter:
        item_genres = getattr(item, "genres", None) or []
        if not any(
            _normalize_filter_value(genre) == genre_filter for genre in item_genres
        ):
            return False
    if implied_genre_filter:
        item_implied_genres = getattr(item, "implied_genres", None) or []
        if not any(
            _normalize_filter_value(genre) == implied_genre_filter
            for genre in item_implied_genres
        ):
            return False

    if year_filter == "unknown":
        if getattr(item, "release_datetime", None):
            return False
    elif year_filter.isdigit():
        release_value = getattr(item, "release_datetime", None)
        release_year = getattr(release_value, "year", None) if release_value else None
        if release_year != int(year_filter):
            return False

    if (
        source_filter
        and _normalize_filter_value(getattr(item, "source", "")) != source_filter
    ):
        return False

    release_date_from = rules.get("release_date_from")
    release_date_to = rules.get("release_date_to")
    if release_date_from or release_date_to:
        item_release = _release_date_from_value(getattr(item, "release_datetime", None))
        if item_release is None:
            return False
        if release_date_from:
            try:
                if item_release < datetime.date.fromisoformat(release_date_from):
                    return False
            except ValueError:
                pass
        if release_date_to:
            try:
                if item_release > datetime.date.fromisoformat(release_date_to):
                    return False
            except ValueError:
                pass

    if release_filter and not _matches_release_filter_value(
        getattr(item, "release_datetime", None),
        release_filter,
        today,
    ):
        return False

    if language_filter:
        languages = _extract_languages(item)
        if not any(
            _normalize_filter_value(language) == language_filter
            for language in languages
        ):
            return False

    if country_filter:
        country = _extract_country(item)
        if _normalize_filter_value(country) != country_filter:
            return False

    if origin_filter:
        origin = _extract_country(item)
        if _normalize_filter_value(origin) != origin_filter:
            return False

    if platform_filter:
        platforms = _extract_platforms(item)
        if not any(
            _normalize_filter_value(platform) == platform_filter
            for platform in platforms
        ):
            return False

    format_filter = _normalize_filter_value(rules.get("format"))
    if format_filter:
        item_format = _normalize_filter_value(getattr(item, "format", "") or "")
        if item_format != format_filter:
            return False

    author_filter = _normalize_filter_value(rules.get("author"))
    if author_filter:
        authors = _extract_authors(item)
        if not any(
            _normalize_filter_value(author) == author_filter for author in authors
        ):
            return False

    provider_filter = _normalize_filter_value(rules.get("provider"))
    if provider_filter:
        providers = _extract_item_providers(item, region)
        if not providers or not any(
            _normalize_filter_value(provider) == provider_filter
            for provider in providers
        ):
            return False

    return True


def _rules_require_item_scan(normalized_rules: dict) -> bool:
    """Return whether matching requires per-item inspection beyond the base queryset."""
    if _normalize_filter_value(normalized_rules.get("release") or "all") != "all":
        return True

    if normalized_rules.get("collection", "all") != "all":
        return True

    if normalized_rules.get("rating", "all") != "all":
        return True
    if _normalize_decimal_value(
        normalized_rules.get("rating_min")
    ) or _normalize_decimal_value(normalized_rules.get("rating_max")):
        return True

    if normalized_rules.get("tag"):
        return True

    for key in (
        "genre",
        "implied_genre",
        "year",
        "release_date_from",
        "release_date_to",
        "source",
        "language",
        "country",
        "platform",
        "origin",
        "format",
        "author",
        "provider",
    ):
        if _normalize_filter_value(normalized_rules.get(key)):
            return True

    return False


def _matches_collection_filter(
    entry,
    media_type: str,
    collection_filter: str,
    collected_item_ids: set[int],
    collected_episode_pairs: set[tuple[str, str]],
) -> bool:
    if collection_filter == "all":
        return True

    item = getattr(entry, "item", None)
    if not item:
        return False

    has_collection = item.id in collected_item_ids
    if not has_collection and media_type in SHOW_COLLECTION_MEDIA_TYPES:
        has_collection = (
            str(item.media_id),
            str(item.source),
        ) in collected_episode_pairs

    if collection_filter == "collected":
        return has_collection
    if collection_filter == "not_collected":
        return not has_collection
    return True


def _collection_filter_context(owner) -> tuple[set[int], set[tuple[str, str]]]:
    """Return collection lookup sets for smart list collection filtering."""
    collected_item_ids = set(
        CollectionEntry.objects.filter(user=owner).values_list("item_id", flat=True),
    )
    collected_episode_pairs = set(
        Item.objects.filter(
            id__in=collected_item_ids,
            media_type=MediaTypes.EPISODE.value,
        ).values_list("media_id", "source"),
    )
    return collected_item_ids, collected_episode_pairs


def _resolve_collection_context(
    owner,
    collection_context: tuple[set[int], set[tuple[str, str]]] | None,
    collection_context_cache: dict | None,
) -> tuple[set[int], set[tuple[str, str]]]:
    """Return a collection context, reusing a caller-supplied value or cache.

    `collection_context_cache` lets callers that resolve many rows/media types
    for the same owner in one request (e.g. building the Home page) share a
    single `CollectionEntry` scan instead of repeating it per row/media type.
    The cache is expected to be a plain dict scoped to a single request/call.
    """
    if collection_context is not None:
        return collection_context
    if collection_context_cache is None:
        return _collection_filter_context(owner)
    cache_key = getattr(owner, "id", None)
    if cache_key not in collection_context_cache:
        collection_context_cache[cache_key] = _collection_filter_context(owner)
    return collection_context_cache[cache_key]


def _collection_only_item_ids(
    owner,
    media_type: str,
    tracked_item_ids: set[int] | None = None,
    *,
    search_query: str = "",
    collection_context_cache: dict | None = None,
) -> set[int]:
    """Return collected item ids that do not already have a tracker row."""
    tracked_item_ids = tracked_item_ids or set()
    collected_item_ids, _collected_episode_pairs = _resolve_collection_context(
        owner, None, collection_context_cache,
    )
    if not collected_item_ids:
        return set()

    direct_type_match = Q(media_type=media_type) | Q(library_media_type=media_type)
    candidate_item_ids = set(
        Item.objects.filter(id__in=collected_item_ids)
        .filter(direct_type_match)
        .exclude(media_type=MediaTypes.EPISODE.value)
        .values_list("id", flat=True),
    )

    if media_type in {MediaTypes.TV.value, MediaTypes.ANIME.value}:
        episode_pairs = {
            (str(media_id), str(source))
            for media_id, source in Item.objects.filter(
                id__in=collected_item_ids,
                media_type=MediaTypes.EPISODE.value,
            ).values_list("media_id", "source")
        }
        if episode_pairs:
            show_media_ids = {media_id for media_id, _source in episode_pairs}
            show_sources = {source for _media_id, source in episode_pairs}
            show_queryset = Item.objects.filter(
                media_type__in=(MediaTypes.TV.value, MediaTypes.ANIME.value),
                media_id__in=show_media_ids,
                source__in=show_sources,
            ).filter(direct_type_match)
            for item in show_queryset.only("id", "media_id", "source"):
                if (str(item.media_id), str(item.source)) in episode_pairs:
                    candidate_item_ids.add(item.id)

    candidate_item_ids -= tracked_item_ids
    if not candidate_item_ids:
        return set()

    candidate_queryset = Item.objects.filter(id__in=candidate_item_ids)
    if search_query:
        candidate_queryset = candidate_queryset.filter(
            Q(title__icontains=search_query) | Q(media_id__icontains=search_query),
        )
    return set(candidate_queryset.values_list("id", flat=True))


def _filter_item_ids_by_rating(
    owner,
    media_type: str,
    item_ids: Iterable[int],
    rating_filter: str,
    rating_min: str = "",
    rating_max: str = "",
) -> set[int]:
    """Filter candidate item ids using the same rated/unrated semantics as media lists."""
    candidate_item_ids = {item_id for item_id in item_ids if item_id}
    if not candidate_item_ids or (
        rating_filter == "all" and not rating_min and not rating_max
    ):
        return candidate_item_ids

    model = apps.get_model("app", media_type)
    queryset = model.objects.filter(
        user=owner,
        item_id__in=candidate_item_ids,
        score__isnull=False,
    )
    if rating_min:
        queryset = queryset.filter(score__gte=float(rating_min))
    if rating_max:
        queryset = queryset.filter(score__lte=float(rating_max))
    rated_item_ids = set(queryset.values_list("item_id", flat=True))

    if rating_filter == "not_rated":
        return candidate_item_ids - rated_item_ids
    if rating_filter == "rated":
        return candidate_item_ids & rated_item_ids
    if rating_min or rating_max:
        return candidate_item_ids & rated_item_ids
    return candidate_item_ids


def _resolve_tag_id_sets(
    owner,
    tag_values: list[str],
    tag_mode: str,
) -> tuple[set[int] | None, set[int] | None]:
    """Return (matching_ids_or_None, excluded_ids_or_None) for a mode-aware tag filter."""
    if not tag_values:
        return None, None

    per_tag_id_sets = [
        set(
            ItemTag.objects.filter(
                tag__user=owner,
                tag__name__iexact=value,
            ).values_list("item_id", flat=True),
        )
        for value in tag_values
    ]

    if tag_mode == "and":
        return set.intersection(*per_tag_id_sets), None
    if tag_mode == "not":
        return None, set().union(*per_tag_id_sets)
    return set().union(*per_tag_id_sets), None


def collect_matching_item_ids(
    owner,
    normalized_rules: dict,
    *,
    include_collection_only_untracked: bool = False,
    collection_context_cache: dict | None = None,
) -> set[int]:
    """Return matching Item IDs for a normalized smart-rule definition.

    `collection_context_cache`, when passed a plain dict by the caller, lets
    repeated calls for the same owner within one request (e.g. one Home page
    build iterating several rows/media types) reuse a single collection scan
    instead of re-querying `CollectionEntry` for every row.
    """
    target_media_types = _target_media_types(
        owner, normalized_rules.get("media_types", [])
    )
    if not target_media_types:
        return set()

    collection_filter = normalized_rules.get("collection", "all")
    rating_filter = normalized_rules.get("rating", "all")
    rating_min = normalized_rules.get("rating_min", "")
    rating_max = normalized_rules.get("rating_max", "")
    has_rating_constraints = (
        rating_filter != "all" or bool(rating_min) or bool(rating_max)
    )
    today = timezone.localdate()
    item_scan_required = _rules_require_item_scan(normalized_rules)
    region = getattr(owner, "watch_provider_region", None)

    collected_item_ids: set[int] = set()
    collected_episode_pairs: set[tuple[str, str]] = set()
    if collection_filter != "all":
        collected_item_ids, collected_episode_pairs = _resolve_collection_context(
            owner, None, collection_context_cache,
        )

    tag_match_ids, tag_excluded_ids = _resolve_tag_id_sets(
        owner,
        normalized_rules.get("tag") or [],
        normalized_rules.get("tag_mode", "or"),
    )

    def _tag_filter_excludes(item_id: int) -> bool:
        if tag_match_ids is not None and item_id not in tag_match_ids:
            return True
        return bool(tag_excluded_ids is not None and item_id in tag_excluded_ids)

    matched_ids = set()
    for media_type in target_media_types:
        queryset = _base_media_queryset(
            owner=owner,
            media_type=media_type,
            status_filter=normalized_rules.get("status") or [],
            search_query=normalized_rules.get("search", ""),
            date_added_from=normalized_rules.get("date_added_from", ""),
            date_added_to=normalized_rules.get("date_added_to", ""),
        )
        queryset_item_ids = set(queryset.values_list("item_id", flat=True))

        if not item_scan_required:
            matched_ids.update(queryset_item_ids)
            if (
                include_collection_only_untracked
                and not normalized_rules.get("status")
                and collection_filter != "not_collected"
                and not has_rating_constraints
            ):
                matched_ids.update(
                    _collection_only_item_ids(
                        owner,
                        media_type,
                        queryset_item_ids,
                        search_query=normalized_rules.get("search", ""),
                        collection_context_cache=collection_context_cache,
                    ),
                )
            continue

        if has_rating_constraints:
            candidate_item_ids = _filter_item_ids_by_rating(
                owner,
                media_type,
                queryset_item_ids,
                rating_filter,
                rating_min,
                rating_max,
            )
            if not candidate_item_ids:
                continue
            queryset = queryset.filter(item_id__in=candidate_item_ids)

        for entry in queryset.iterator():
            item = getattr(entry, "item", None)
            if not item:
                continue

            if not _matches_item_filters(item, normalized_rules, today, region):
                continue

            if collection_filter != "all" and not _matches_collection_filter(
                entry=entry,
                media_type=media_type,
                collection_filter=collection_filter,
                collected_item_ids=collected_item_ids,
                collected_episode_pairs=collected_episode_pairs,
            ):
                continue

            if _tag_filter_excludes(item.id):
                continue

            matched_ids.add(item.id)

        if (
            include_collection_only_untracked
            and not normalized_rules.get("status")
            and collection_filter != "not_collected"
            and not has_rating_constraints
        ):
            collection_only_ids = _collection_only_item_ids(
                owner,
                media_type,
                queryset_item_ids,
                search_query=normalized_rules.get("search", ""),
                collection_context_cache=collection_context_cache,
            )
            if collection_only_ids:
                for item in Item.objects.filter(id__in=collection_only_ids).iterator():
                    if not _matches_item_filters(item, normalized_rules, today, region):
                        continue
                    if _tag_filter_excludes(item.id):
                        continue
                    matched_ids.add(item.id)

    return matched_ids


def item_matches_rules(
    owner,
    item: Item,
    normalized_rules: dict,
    *,
    collection_context: tuple[set[int], set[tuple[str, str]]] | None = None,
) -> bool:
    """Return whether a single item currently matches a normalized rule set for an owner."""
    if not owner or not item:
        return False

    target_media_types = _target_media_types(
        owner, normalized_rules.get("media_types", [])
    )
    if item.media_type not in target_media_types:
        return False

    queryset = _base_media_queryset(
        owner=owner,
        media_type=item.media_type,
        status_filter=normalized_rules.get("status") or [],
        search_query=normalized_rules.get("search", ""),
        date_added_from=normalized_rules.get("date_added_from", ""),
        date_added_to=normalized_rules.get("date_added_to", ""),
    ).filter(item_id=item.id)

    rating_filter = normalized_rules.get("rating", "all")
    rating_min = normalized_rules.get("rating_min", "")
    rating_max = normalized_rules.get("rating_max", "")
    if not _filter_item_ids_by_rating(
        owner,
        item.media_type,
        [item.id],
        rating_filter,
        rating_min,
        rating_max,
    ):
        return False

    today = timezone.localdate()
    if not _matches_item_filters(item, normalized_rules, today):
        return False

    tag_values = normalized_rules.get("tag") or []
    if tag_values:
        tag_mode = normalized_rules.get("tag_mode", "or")
        item_tag_names = {
            name.lower()
            for name in ItemTag.objects.filter(
                tag__user=owner,
                item=item,
            ).values_list("tag__name", flat=True)
        }
        wanted = {value.lower() for value in tag_values}
        if tag_mode == "and":
            if not wanted.issubset(item_tag_names):
                return False
        elif tag_mode == "not":
            if wanted & item_tag_names:
                return False
        elif not (wanted & item_tag_names):
            return False

    collection_filter = normalized_rules.get("collection", "all")
    if collection_filter != "all":
        if collection_context is None:
            collection_context = _collection_filter_context(owner)
        collected_item_ids, collected_episode_pairs = collection_context
    else:
        collected_item_ids = set()
        collected_episode_pairs = set()

    for entry in queryset.iterator():
        if _matches_collection_filter(
            entry=entry,
            media_type=item.media_type,
            collection_filter=collection_filter,
            collected_item_ids=collected_item_ids,
            collected_episode_pairs=collected_episode_pairs,
        ):
            return True

    return False


def sync_smart_lists_for_item(owner, item: Item) -> dict[str, int]:
    """Incrementally sync smart-list membership for one owner/item combination."""
    if not owner or not item or not getattr(item, "id", None):
        return {"checked": 0, "added": 0, "removed": 0}

    from lists.models import CustomList, CustomListItem

    smart_lists = list(
        CustomList.objects.filter(owner=owner, is_smart=True).only(
            "id",
            "owner_id",
            "smart_media_types",
            "smart_excluded_media_types",
            "smart_filters",
        ),
    )
    if not smart_lists:
        return {"checked": 0, "added": 0, "removed": 0}

    smart_list_ids = [custom_list.id for custom_list in smart_lists]
    existing_memberships = set(
        CustomListItem.objects.filter(
            custom_list_id__in=smart_list_ids,
            item_id=item.id,
        ).values_list("custom_list_id", flat=True),
    )

    collection_context = None
    pending_adds = []
    pending_removals = []

    for custom_list in smart_lists:
        normalized_rules = normalize_list_rules(custom_list)
        if (
            normalized_rules.get("collection", "all") != "all"
            and collection_context is None
        ):
            collection_context = _collection_filter_context(owner)

        should_include = item_matches_rules(
            owner=owner,
            item=item,
            normalized_rules=normalized_rules,
            collection_context=collection_context,
        )
        currently_in_list = custom_list.id in existing_memberships

        if should_include and not currently_in_list:
            pending_adds.append(
                CustomListItem(
                    custom_list=custom_list,
                    item=item,
                    added_by=owner,
                ),
            )
        elif not should_include and currently_in_list:
            pending_removals.append(custom_list.id)

    if pending_adds:
        CustomListItem.objects.bulk_create(pending_adds, ignore_conflicts=True)
    if pending_removals:
        CustomListItem.objects.filter(
            custom_list_id__in=pending_removals,
            item_id=item.id,
        ).delete()

    return {
        "checked": len(smart_lists),
        "added": len(pending_adds),
        "removed": len(pending_removals),
    }


def build_rule_filter_data(
    owner,
    media_types: list[str],
    status: list[str] | str,
    search: str,
    *,
    include_collection_only_untracked: bool = False,
    precomputed_tags: list[str] | None = None,
):
    """Build menu options for smart-rule filters from matched candidate media."""
    target_media_types = _target_media_types(owner, media_types)
    status_is_all = not status or status == "all"

    item_ids = set()
    for media_type in target_media_types:
        queryset = _base_media_queryset(
            owner=owner,
            media_type=media_type,
            status_filter=status,
            search_query=search,
        )
        queryset_item_ids = set(queryset.values_list("item_id", flat=True))
        item_ids.update(queryset_item_ids)
        if include_collection_only_untracked and status_is_all:
            item_ids.update(
                _collection_only_item_ids(
                    owner,
                    media_type,
                    queryset_item_ids,
                    search_query=search,
                ),
            )

    region = getattr(owner, "watch_provider_region", None)

    items = Item.objects.filter(id__in=item_ids).only(
        "genres",
        "implied_genres",
        "release_datetime",
        "source",
        "languages",
        "country",
        "platforms",
        "format",
        "media_type",
        "authors",
        "watch_providers",
    )

    format_labels = {
        "hardcover": "Hardcover",
        "paperback": "Paperback",
        "ebook": "eBook",
        "audiobook": "Audiobook",
    }

    genres_set = set()
    implied_genres_set = set()
    years_set = set()
    sources_set = set()
    languages_set = set()
    countries_set = set()
    platforms_set = set()
    origins_set = set()
    formats_set = set()
    authors_set = set()
    providers_set = set()
    has_unknown_year = False

    for item in items:
        for genre in item.genres or []:
            genre_value = str(genre).strip()
            if genre_value:
                genres_set.add(genre_value)
        for genre in getattr(item, "implied_genres", None) or []:
            genre_value = str(genre).strip()
            if genre_value:
                implied_genres_set.add(genre_value)

        release_datetime = getattr(item, "release_datetime", None)
        if release_datetime and getattr(release_datetime, "year", None):
            years_set.add(release_datetime.year)
        else:
            has_unknown_year = True

        if item.source:
            sources_set.add(item.source)

        languages_set.update(_extract_languages(item))

        country_value = _extract_country(item)
        if country_value:
            countries_set.add(country_value)
            origins_set.add(country_value)

        platforms_set.update(_extract_platforms(item))

        format_value = str(getattr(item, "format", "") or "").strip()
        if format_value:
            formats_set.add(format_value)
        authors_set.update(_extract_authors(item))

        if region and region != "UNSET":
            providers_set.update(_extract_item_providers(item, region) or [])

    source_labels = dict(Sources.choices)
    filter_data = {
        "genres": sorted(genres_set, key=lambda value: value.lower()),
        "implied_genres": sorted(implied_genres_set, key=lambda value: value.lower()),
        "years": [
            {"value": str(year), "label": str(year)}
            for year in sorted(years_set, reverse=True)
        ],
        "sources": [
            {"value": source, "label": source_labels.get(source, source)}
            for source in sorted(sources_set)
        ],
        "languages": [
            {
                "value": value,
                "label": value.upper()
                if len(value) <= SHORT_CODE_MAX_LENGTH
                else value,
            }
            for value in sorted(languages_set)
        ],
        "countries": [
            {
                "value": value,
                "label": value.upper()
                if len(value) <= SHORT_CODE_MAX_LENGTH
                else value,
            }
            for value in sorted(countries_set)
        ],
        "platforms": [
            {"value": value, "label": value}
            for value in sorted(platforms_set, key=lambda value: value.lower())
        ],
        "origins": [
            {
                "value": value,
                "label": value.upper()
                if len(value) <= SHORT_CODE_MAX_LENGTH
                else value,
            }
            for value in sorted(origins_set)
        ],
        "show_languages": any(
            media_type in LANGUAGE_MEDIA_TYPES for media_type in target_media_types
        ),
        "show_countries": any(
            media_type in COUNTRY_MEDIA_TYPES for media_type in target_media_types
        ),
        "show_platforms": any(
            media_type in PLATFORM_MEDIA_TYPES for media_type in target_media_types
        ),
        "show_origins": any(
            media_type in ORIGIN_MEDIA_TYPES for media_type in target_media_types
        ),
        "formats": [
            {"value": value, "label": format_labels.get(value, value.title())}
            for value in sorted(formats_set, key=lambda val: val.lower())
        ],
        "show_formats": any(
            media_type in FORMAT_MEDIA_TYPES for media_type in target_media_types
        ),
        "authors": [
            {"value": value, "label": value}
            for value in sorted(authors_set, key=lambda value: value.lower())
        ],
        "show_authors": any(
            media_type in AUTHOR_MEDIA_TYPES for media_type in target_media_types
        ),
        "providers": [
            {"value": value, "label": value}
            for value in sorted(providers_set, key=lambda value: value.lower())
        ],
        "show_providers": bool(region and region != "UNSET")
        and any(media_type in PROVIDER_MEDIA_TYPES for media_type in target_media_types),
    }

    if has_unknown_year:
        filter_data["years"].append({"value": "unknown", "label": "Unknown"})

    if precomputed_tags is not None:
        filter_data["tags"] = precomputed_tags
    else:
        from app.models import Tag

        filter_data["tags"] = list(
            Tag.objects.filter(user=owner)
            .values_list("name", flat=True)
            .order_by("name")
        )

    return filter_data
