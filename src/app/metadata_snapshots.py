"""Durable local-first metadata reads and refresh coordination."""

from __future__ import annotations

import contextlib
import copy
import functools
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, transaction
from django.db.models.signals import post_save
from django.utils import timezone

from app import metadata_utils
from app.models import Item, MediaTypes, MetadataSnapshot, Sources
from app.providers import services

logger = logging.getLogger(__name__)

READ_MODES = frozenset({"local-first", "network-first", "local-only"})
REFRESH_MODES = frozenset({"background", "blocking", "manual"})
PERSIST_MODES = frozenset({"all", "tracked", "off"})
MERGE_MODES = frozenset({"preserve", "replace"})
LOCAL_METADATA_SOURCES = frozenset(
    {
        Sources.MANUAL.value,
        Sources.AUDIOBOOKSHELF.value,
        Sources.STORYTELLER.value,
    },
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|api[_-]?key|authorization|cookie|password|"
    r"refresh[_-]?token|secret|signature)(?:$|[_-])",
    re.IGNORECASE,
)
OVERRIDE_SELECTOR_PATTERN = re.compile(
    r"^(?:\*|[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)?)$",
)
FAILURE_CODE_PATTERN = re.compile(r"[^a-z0-9_-]+")
MAX_METADATA_DEPTH = 24
MAX_METADATA_NODES = 100_000
MAX_SEASON_VARIANTS = 100
SNAPSHOT_SCHEMA_VERSION = 1

_SUPPRESS_ITEM_SNAPSHOT_SYNC: ContextVar[bool] = ContextVar(
    "suppress_item_snapshot_sync",
    default=False,
)

ITEM_METADATA_FIELDS = frozenset(
    {
        "authors",
        "country",
        "creators",
        "edition_id",
        "format",
        "genres",
        "igdb_user_rating",
        "igdb_user_rating_count",
        "image",
        "isbn",
        "languages",
        "library_media_type",
        "local_season_episode_count",
        "manual_metadata",
        "media_id",
        "media_type",
        "metadata_fetched_at",
        "number_of_pages",
        "original_title",
        "platforms",
        "provider_certification",
        "provider_collection_id",
        "provider_collection_name",
        "provider_external_ids",
        "provider_game_lengths",
        "provider_game_lengths_fetched_at",
        "provider_game_lengths_match",
        "provider_game_lengths_source",
        "provider_keywords",
        "provider_metadata_status",
        "provider_popularity",
        "provider_rating",
        "provider_rating_count",
        "publishers",
        "release_datetime",
        "runtime",
        "runtime_minutes",
        "season_number",
        "series_name",
        "series_position",
        "source",
        "source_material",
        "status",
        "studios",
        "synopsis",
        "themes",
        "title",
        "trakt_popularity_fetched_at",
        "trakt_popularity_rank",
        "trakt_popularity_score",
        "trakt_rating",
        "trakt_rating_count",
        "watch_providers",
    },
)


class MetadataSnapshotError(Exception):
    """Base exception for snapshot policy and persistence failures."""


class MetadataSnapshotRejected(MetadataSnapshotError):
    """Report a payload that is unsafe or too large to persist."""

    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


class LocalMetadataUnavailable(services.ProviderAPIError):
    """Report that local-only mode has no durable data for the identity."""

    def __init__(self, provider):
        provider_id = str(provider or "metadata").strip().casefold()
        self.provider = provider_id
        self.response = None
        self.status_code = None
        try:
            self.provider_label = services.Sources(provider_id).label
        except (TypeError, ValueError):
            self.provider_label = provider_id.replace("_", " ").title()
        message = (
            f"No local metadata is available for {self.provider_label}. "
            "Network access is disabled by the metadata read policy."
        )
        Exception.__init__(self, message)

    def __reduce__(self):
        """Reconstruct the exception without serializing request data."""
        return type(self), (self.provider,)


@dataclass(frozen=True)
class MetadataPolicy:
    """Resolved instance policy for metadata reads and writes."""

    read_mode: str
    refresh_mode: str
    persist_mode: str
    merge_mode: str
    fresh_seconds: int
    freshness_overrides: dict[str, int]
    failure_retry_seconds: int
    refresh_lease_seconds: int
    max_payload_bytes: int
    retention_days: int

    def freshness_seconds_for(self, source, media_type):
        """Return the configured freshness window for one metadata identity."""
        source_key = str(source or "").strip().casefold()
        media_type_key = str(media_type or "").strip().casefold()
        return self.freshness_overrides.get(
            f"{source_key}/{media_type_key}",
            self.freshness_overrides.get(
                source_key,
                self.freshness_overrides.get("*", self.fresh_seconds),
            ),
        )

    def public_dict(self, source=None, media_type=None):
        """Return non-secret policy details for web and API responses."""
        payload = asdict(self)
        payload["effective_fresh_seconds"] = self.freshness_seconds_for(
            source,
            media_type,
        )
        return payload


@dataclass(frozen=True)
class MetadataIdentity:
    """Canonical identity for one metadata payload variant."""

    media_type: str
    media_id: str
    source: str
    season_numbers: tuple[object, ...] = ()
    episode_number: int | None = None
    language: str = ""
    edition_id: str = ""

    @property
    def cache_key(self):
        """Return a stable key that contains no credentials or request URLs."""
        canonical = json.dumps(
            {
                "edition_id": self.edition_id,
                "episode_number": self.episode_number,
                "language": self.language,
                "media_id": self.media_id,
                "media_type": self.media_type,
                "season_numbers": self.season_numbers,
                "source": self.source,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def task_kwargs(self):
        """Return JSON-safe arguments for a background refresh task."""
        return {
            "edition_id": self.edition_id or None,
            "episode_number": self.episode_number,
            "language": self.language or None,
            "media_id": self.media_id,
            "media_type": self.media_type,
            "season_numbers": list(self.season_numbers) or None,
            "source": self.source,
        }


def _configured_value(name, default=None):
    """Return a Django setting, then an environment value, then the default."""
    value = getattr(settings, name, None)
    if value is not None:
        return value
    legacy_name = name.replace("FLOPPY_", "YAMTRACK_", 1)
    return os.environ.get(name, os.environ.get(legacy_name, default))


def _choice(value, *, name, allowed, default):
    """Return one configured choice or fail closed."""
    normalized = str(value if value is not None else default).strip().casefold()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        msg = f"{name} must be one of: {choices}."
        raise ImproperlyConfigured(msg)
    return normalized


def _bounded_integer(value, *, name, default, minimum=0, maximum=315_360_000):
    """Return one bounded integer setting or fail closed."""
    raw_value = default if value in (None, "") else value
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError) as error:
        msg = f"{name} must be an integer."
        raise ImproperlyConfigured(msg) from error
    if parsed < minimum or parsed > maximum:
        msg = f"{name} must be between {minimum} and {maximum}."
        raise ImproperlyConfigured(msg)
    return parsed


def _freshness_overrides(value):
    """Return exact provider and provider/media-type freshness overrides."""
    if value in (None, ""):
        return {}
    if isinstance(value, Mapping):
        entries = value.items()
    elif isinstance(value, str):
        pairs = []
        for raw_entry in value.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            separator = "=" if "=" in entry else ":"
            if separator not in entry:
                msg = (
                    "FLOPPY_METADATA_FRESH_OVERRIDES entries must use "
                    "selector=seconds."
                )
                raise ImproperlyConfigured(msg)
            selector, seconds = entry.split(separator, 1)
            pairs.append((selector, seconds))
        entries = pairs
    else:
        msg = (
            "FLOPPY_METADATA_FRESH_OVERRIDES must be a mapping or "
            "comma-separated string."
        )
        raise ImproperlyConfigured(msg)

    overrides = {}
    for selector, seconds in entries:
        normalized_selector = str(selector or "").strip().casefold()
        if not OVERRIDE_SELECTOR_PATTERN.fullmatch(normalized_selector):
            msg = (
                "Metadata freshness selectors must be '*', a provider, or "
                "provider/media_type."
            )
            raise ImproperlyConfigured(msg)
        overrides[normalized_selector] = _bounded_integer(
            seconds,
            name=f"metadata freshness override {normalized_selector}",
            default=0,
        )
    return overrides


def get_metadata_policy():
    """Return the effective local-first metadata policy."""
    return MetadataPolicy(
        read_mode=_choice(
            _configured_value("FLOPPY_METADATA_READ_MODE", "local-first"),
            name="FLOPPY_METADATA_READ_MODE",
            allowed=READ_MODES,
            default="local-first",
        ),
        refresh_mode=_choice(
            _configured_value("FLOPPY_METADATA_REFRESH_MODE", "background"),
            name="FLOPPY_METADATA_REFRESH_MODE",
            allowed=REFRESH_MODES,
            default="background",
        ),
        persist_mode=_choice(
            _configured_value("FLOPPY_METADATA_PERSIST_MODE", "all"),
            name="FLOPPY_METADATA_PERSIST_MODE",
            allowed=PERSIST_MODES,
            default="all",
        ),
        merge_mode=_choice(
            _configured_value("FLOPPY_METADATA_MERGE_MODE", "preserve"),
            name="FLOPPY_METADATA_MERGE_MODE",
            allowed=MERGE_MODES,
            default="preserve",
        ),
        fresh_seconds=_bounded_integer(
            _configured_value("FLOPPY_METADATA_FRESH_SECONDS", 86_400),
            name="FLOPPY_METADATA_FRESH_SECONDS",
            default=86_400,
        ),
        freshness_overrides=_freshness_overrides(
            _configured_value("FLOPPY_METADATA_FRESH_OVERRIDES", ""),
        ),
        failure_retry_seconds=_bounded_integer(
            _configured_value("FLOPPY_METADATA_FAILURE_RETRY_SECONDS", 300),
            name="FLOPPY_METADATA_FAILURE_RETRY_SECONDS",
            default=300,
        ),
        refresh_lease_seconds=_bounded_integer(
            _configured_value("FLOPPY_METADATA_REFRESH_LEASE_SECONDS", 120),
            name="FLOPPY_METADATA_REFRESH_LEASE_SECONDS",
            default=120,
            minimum=1,
        ),
        max_payload_bytes=_bounded_integer(
            _configured_value("FLOPPY_METADATA_MAX_PAYLOAD_BYTES", 2_097_152),
            name="FLOPPY_METADATA_MAX_PAYLOAD_BYTES",
            default=2_097_152,
            minimum=1024,
            maximum=104_857_600,
        ),
        retention_days=_bounded_integer(
            _configured_value("FLOPPY_METADATA_RETENTION_DAYS", 0),
            name="FLOPPY_METADATA_RETENTION_DAYS",
            default=0,
            maximum=36_500,
        ),
    )


def _normalize_season_numbers(value):
    """Return a bounded tuple for one season-specific metadata variant."""
    if value in (None, ""):
        return ()
    values = [value] if isinstance(value, (str, int)) else list(value)
    if len(values) > MAX_SEASON_VARIANTS:
        msg = "A metadata request contains too many season variants."
        raise MetadataSnapshotRejected("too_many_seasons") from ValueError(msg)

    normalized = []
    for season in values:
        if season in (None, ""):
            continue
        try:
            normalized.append(int(season))
        except (TypeError, ValueError):
            normalized.append(str(season).strip())
    return tuple(normalized)


def build_metadata_identity(
    media_type,
    media_id,
    source,
    season_numbers=None,
    episode_number=None,
    language=None,
    edition_id=None,
):
    """Build one validated metadata identity from service arguments."""
    normalized_media_type = str(media_type or "").strip().casefold()
    normalized_media_id = str(media_id or "").strip()
    normalized_source = str(source or "").strip().casefold()
    normalized_language = str(language or "").strip().replace("_", "-").casefold()
    normalized_edition = str(edition_id or "").strip()

    if not normalized_media_type or len(normalized_media_type) > 32:
        raise MetadataSnapshotRejected("invalid_media_type")
    if not normalized_media_id or len(normalized_media_id) > 500:
        raise MetadataSnapshotRejected("invalid_media_id")
    if not normalized_source or len(normalized_source) > 20:
        raise MetadataSnapshotRejected("invalid_source")
    if len(normalized_language) > 35:
        raise MetadataSnapshotRejected("invalid_language")
    if len(normalized_edition) > 128:
        raise MetadataSnapshotRejected("invalid_edition")

    normalized_episode = None
    if episode_number not in (None, ""):
        try:
            normalized_episode = int(episode_number)
        except (TypeError, ValueError) as error:
            raise MetadataSnapshotRejected("invalid_episode") from error
        if normalized_episode < 0:
            raise MetadataSnapshotRejected("invalid_episode")

    return MetadataIdentity(
        media_type=normalized_media_type,
        media_id=normalized_media_id,
        source=normalized_source,
        season_numbers=_normalize_season_numbers(season_numbers),
        episode_number=normalized_episode,
        language=normalized_language,
        edition_id=normalized_edition,
    )


def _redact_sensitive_values(value, *, depth=0, node_count=None):
    """Return JSON data with secret-shaped keys removed and size bounded."""
    if node_count is None:
        node_count = [0]
    node_count[0] += 1
    if node_count[0] > MAX_METADATA_NODES:
        raise MetadataSnapshotRejected("too_many_values")
    if depth > MAX_METADATA_DEPTH:
        raise MetadataSnapshotRejected("too_deep")

    if isinstance(value, dict):
        sanitized = {}
        for raw_key, nested_value in value.items():
            key = str(raw_key)
            if key == "_floppy_cache" or SENSITIVE_KEY_PATTERN.search(key):
                continue
            sanitized[key] = _redact_sensitive_values(
                nested_value,
                depth=depth + 1,
                node_count=node_count,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _redact_sensitive_values(
                nested_value,
                depth=depth + 1,
                node_count=node_count,
            )
            for nested_value in value
        ]
    return value


def sanitize_metadata_payload(payload, *, max_payload_bytes):
    """Return safe JSON metadata, its hash, and byte size."""
    if not isinstance(payload, dict):
        raise MetadataSnapshotRejected("not_a_mapping")
    try:
        encoded = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False)
        json_payload = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise MetadataSnapshotRejected("not_json_serializable") from error

    sanitized = _redact_sensitive_values(json_payload)
    canonical = json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_size = len(canonical)
    if payload_size > max_payload_bytes:
        raise MetadataSnapshotRejected("payload_too_large")
    return sanitized, hashlib.sha256(canonical).hexdigest(), payload_size


def _is_empty_metadata_value(value):
    return value is None or value == "" or value == [] or value == {}


def merge_last_known_good(previous, incoming):
    """Merge a refresh without replacing known values with empty placeholders."""
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return copy.deepcopy(incoming)

    merged = copy.deepcopy(previous)
    for key, incoming_value in incoming.items():
        if key == "_floppy_cache":
            continue
        previous_value = merged.get(key)
        if isinstance(previous_value, dict) and isinstance(incoming_value, dict):
            merged[key] = merge_last_known_good(previous_value, incoming_value)
        elif _is_empty_metadata_value(incoming_value) and not _is_empty_metadata_value(
            previous_value,
        ):
            continue
        else:
            merged[key] = copy.deepcopy(incoming_value)
    return merged


def _credit_payload(item):
    """Return locally stored people and studio data for one Item."""
    cast = []
    crew = []
    studios = []
    try:
        credits = item.person_credits.select_related("person").all()
        for credit in credits:
            person = credit.person
            row = {
                "department": credit.department,
                "id": person.source_person_id,
                "image": person.image,
                "name": person.name,
                "role": credit.role,
                "source": person.source,
            }
            if credit.role_type == "cast":
                cast.append(row)
            else:
                crew.append(row)

        studio_credits = item.studio_credits.select_related("studio").all()
        studios = [
            {
                "id": credit.studio.source_studio_id,
                "logo": credit.studio.logo,
                "name": credit.studio.name,
                "source": credit.studio.source,
            }
            for credit in studio_credits
        ]
    except DatabaseError:
        return {"cast": [], "crew": [], "studios_full": []}
    return {"cast": cast, "crew": crew, "studios_full": studios}


def item_metadata_payload(item):
    """Build a complete local metadata payload from one durable Item."""
    details = {
        "authors": item.authors,
        "country": item.country,
        "format": item.format,
        "isbn": item.isbn,
        "languages": item.languages,
        "number_of_pages": item.number_of_pages,
        "platforms": item.platforms,
        "publisher": item.publishers,
        "release_datetime": item.release_datetime,
        "runtime": item.runtime,
        "source": item.source_material,
        "status": item.status,
        "studios": item.studios,
        "themes": item.themes,
    }
    payload = {
        "creators": item.creators,
        "details": details,
        "external_ids": item.provider_external_ids,
        "genres": item.genres,
        "igdb_user_rating": item.igdb_user_rating,
        "igdb_user_rating_count": item.igdb_user_rating_count,
        "image": item.image,
        "library_media_type": item.library_media_type or item.media_type,
        "max_progress": (
            item.number_of_pages
            if item.media_type == MediaTypes.BOOK.value
            else item.local_season_episode_count
        ),
        "media_id": item.media_id,
        "media_type": item.media_type,
        "original_title": item.original_title,
        "provider_certification": item.provider_certification,
        "provider_collection_id": item.provider_collection_id,
        "provider_collection_name": item.provider_collection_name,
        "provider_external_ids": item.provider_external_ids,
        "provider_game_lengths": item.provider_game_lengths,
        "provider_keywords": item.provider_keywords,
        "provider_popularity": item.provider_popularity,
        "provider_rating": item.provider_rating,
        "provider_rating_count": item.provider_rating_count,
        "providers": item.watch_providers,
        "related": {},
        "release_datetime": item.release_datetime,
        "runtime_minutes": item.runtime_minutes,
        "season_number": item.season_number,
        "series_name": item.series_name,
        "series_position": item.series_position,
        "source": item.source,
        "synopsis": item.synopsis,
        "title": item.title,
        "localized_title": item.localized_title,
        "watch_providers": item.watch_providers,
    }
    payload.update(_credit_payload(item))
    return payload


def _tracking_media_types(identity):
    """Return Item media types that can hold this route identity."""
    if identity.media_type == "tv_with_seasons":
        return [MediaTypes.TV.value]
    if identity.media_type == MediaTypes.ANIME.value and identity.source in {
        Sources.TMDB.value,
        Sources.TVDB.value,
    }:
        return [MediaTypes.ANIME.value, MediaTypes.TV.value]
    return [identity.media_type]


def matching_items(identity):
    """Return durable Items that match one metadata identity."""
    try:
        queryset = Item.objects.filter(
            media_id=identity.media_id,
            source=identity.source,
            media_type__in=_tracking_media_types(identity),
        )
        season_number = identity.season_numbers[0] if identity.season_numbers else None
        if identity.media_type == MediaTypes.SEASON.value:
            queryset = queryset.filter(season_number=season_number)
        elif identity.media_type == MediaTypes.EPISODE.value:
            queryset = queryset.filter(
                season_number=season_number,
                episode_number=identity.episode_number,
            )
        return list(queryset.order_by("library_media_type", "pk")[:20])
    except DatabaseError:
        return []


def _snapshot(identity):
    try:
        return MetadataSnapshot.objects.filter(cache_key=identity.cache_key).first()
    except DatabaseError:
        return None


def _retained_snapshot(snapshot, *, policy, has_items):
    """Return a retained snapshot or delete one expired untracked record."""
    if snapshot is None or not policy.retention_days or has_items:
        return snapshot
    cutoff = timezone.now() - timedelta(days=policy.retention_days)
    if snapshot.updated_at >= cutoff:
        return snapshot
    try:
        snapshot.delete()
    except DatabaseError:
        return snapshot
    return None


def _snapshot_is_fresh(snapshot, *, policy, identity):
    if snapshot is None or not snapshot.payload or snapshot.fetched_at is None:
        return False
    if snapshot.state == MetadataSnapshot.State.LOCAL:
        return False
    fresh_seconds = policy.freshness_seconds_for(identity.source, identity.media_type)
    return snapshot.fetched_at >= timezone.now() - timedelta(seconds=fresh_seconds)


def _payload_needs_completion(payload, identity):
    """Return whether a provider payload lacks fields existing detail flows repair."""
    if not isinstance(payload, dict) or not payload.get("title"):
        return True
    if identity.media_type in {
        MediaTypes.ANIME.value,
        MediaTypes.SEASON.value,
        MediaTypes.TV.value,
        "tv_with_seasons",
    } and ("cast" not in payload or "crew" not in payload):
        return True
    if (
        identity.source == Sources.TMDB.value
        and identity.media_type
        in {
            MediaTypes.MOVIE.value,
            MediaTypes.SEASON.value,
            MediaTypes.TV.value,
        }
        and not payload.get("original_title")
    ):
        return True
    if identity.media_type == MediaTypes.GAME.value and "studios_full" not in payload:
        return True
    if identity.media_type == MediaTypes.BOOK.value:
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        if "authors_full" not in payload and not (
            details.get("authors") or details.get("author")
        ):
            return True
    return False


def _local_payload(snapshot, items, *, policy):
    payload = copy.deepcopy(snapshot.payload) if snapshot and snapshot.payload else {}
    if items:
        item_payload = item_metadata_payload(items[0])
        payload = (
            merge_last_known_good(payload, item_payload)
            if policy.merge_mode == "preserve"
            else item_payload
        )
    return payload or None


def _failure_code(error):
    status_code = getattr(error, "status_code", None)
    raw_code = type(error).__name__.casefold()
    if status_code:
        raw_code = f"{raw_code}_{status_code}"
    return FAILURE_CODE_PATTERN.sub("_", raw_code).strip("_")[:80] or "refresh_failed"


def _network_allowed(identity):
    if identity.source in LOCAL_METADATA_SOURCES:
        return True
    from app import network_policy

    return network_policy.provider_access_allowed(identity.source)


def _should_persist(policy, items):
    return policy.persist_mode == "all" or (
        policy.persist_mode == "tracked" and bool(items)
    )


def _prepare_persisted_payload(previous, incoming, *, policy):
    payload = (
        merge_last_known_good(previous, incoming)
        if policy.merge_mode == "preserve" and previous
        else copy.deepcopy(incoming)
    )
    return sanitize_metadata_payload(
        payload,
        max_payload_bytes=policy.max_payload_bytes,
    )


def _save_snapshot(
    identity,
    payload,
    *,
    policy,
    state,
    origin,
    fetched_at,
    preserve_status=False,
):
    """Atomically store a safe payload without exposing transient partial writes."""
    with transaction.atomic():
        current = (
            MetadataSnapshot.objects.select_for_update()
            .filter(cache_key=identity.cache_key)
            .first()
        )
        previous_payload = current.payload if current and current.payload else {}
        sanitized, payload_hash, payload_size = _prepare_persisted_payload(
            previous_payload,
            payload,
            policy=policy,
        )
        effective_state = current.state if current and preserve_status else state
        effective_origin = current.origin if current and preserve_status else origin
        effective_fetched_at = (
            current.fetched_at if current and preserve_status else fetched_at
        )
        defaults = {
            "consecutive_failures": (
                current.consecutive_failures if current and preserve_status else 0
            ),
            "edition_id": identity.edition_id,
            "episode_number": identity.episode_number,
            "failure_code": current.failure_code if current and preserve_status else "",
            "fetched_at": effective_fetched_at,
            "language": identity.language,
            "last_attempted_at": (
                current.last_attempted_at if current and preserve_status else fetched_at
            ),
            "last_failure_at": (
                current.last_failure_at if current and preserve_status else None
            ),
            "media_id": identity.media_id,
            "media_type": identity.media_type,
            "origin": effective_origin,
            "payload": sanitized,
            "payload_hash": payload_hash,
            "payload_size": payload_size,
            "refresh_started_at": None,
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "season_numbers": list(identity.season_numbers),
            "source": identity.source,
            "state": effective_state,
        }
        snapshot, _ = MetadataSnapshot.objects.update_or_create(
            cache_key=identity.cache_key,
            defaults=defaults,
        )
        return snapshot


@contextlib.contextmanager
def suppress_item_snapshot_sync():
    """Prevent provider persistence from recursively creating local snapshots."""
    token = _SUPPRESS_ITEM_SNAPSHOT_SYNC.set(True)
    try:
        yield
    finally:
        _SUPPRESS_ITEM_SNAPSHOT_SYNC.reset(token)


def _apply_provider_payload_to_items(items, payload, *, fetched_at):
    """Persist normalized provider fields immediately after a successful refresh."""
    if not items or not isinstance(payload, dict):
        return
    with suppress_item_snapshot_sync():
        for item in items:
            update_fields = []
            title_fields = Item.title_fields_from_metadata(
                payload,
                fallback_title=item.title,
            )
            for field_name, value in title_fields.items():
                if value and getattr(item, field_name) != value:
                    setattr(item, field_name, value)
                    update_fields.append(field_name)

            image = payload.get("image")
            if image and item.image != image:
                item.image = image
                update_fields.append("image")

            update_fields.extend(metadata_utils.apply_item_metadata(item, payload))
            update_fields.extend(
                metadata_utils.apply_item_genres(
                    item,
                    metadata_utils.extract_metadata_genres(payload),
                ),
            )

            providers = payload.get("watch_providers") or payload.get("providers")
            if isinstance(providers, dict) and providers and item.watch_providers != providers:
                item.watch_providers = providers
                update_fields.append("watch_providers")

            external_ids = payload.get("provider_external_ids") or payload.get(
                "external_ids"
            )
            if (
                isinstance(external_ids, dict)
                and external_ids
                and item.provider_external_ids != external_ids
            ):
                item.provider_external_ids = external_ids
                update_fields.append("provider_external_ids")

            details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
            runtime_minutes = payload.get("runtime_minutes") or details.get(
                "runtime_minutes"
            )
            if runtime_minutes not in (None, ""):
                with contextlib.suppress(TypeError, ValueError):
                    normalized_runtime = int(runtime_minutes)
                    if normalized_runtime >= 0 and item.runtime_minutes != normalized_runtime:
                        item.runtime_minutes = normalized_runtime
                        update_fields.append("runtime_minutes")

            item.metadata_fetched_at = fetched_at
            update_fields.append("metadata_fetched_at")
            try:
                item.save(update_fields=list(dict.fromkeys(update_fields)))
            except DatabaseError:
                logger.warning(
                    "Could not persist refreshed metadata to Item source=%s media_type=%s",
                    item.source,
                    item.media_type,
                )


def _record_failure(snapshot, *, error, blocked=False):
    if snapshot is None:
        return None
    try:
        with transaction.atomic():
            current = MetadataSnapshot.objects.select_for_update().get(pk=snapshot.pk)
            current.state = (
                MetadataSnapshot.State.BLOCKED
                if blocked
                else MetadataSnapshot.State.FAILED
            )
            current.failure_code = _failure_code(error)
            current.last_attempted_at = timezone.now()
            current.last_failure_at = current.last_attempted_at
            current.refresh_started_at = None
            current.consecutive_failures += 1
            current.save(
                update_fields=[
                    "consecutive_failures",
                    "failure_code",
                    "last_attempted_at",
                    "last_failure_at",
                    "refresh_started_at",
                    "state",
                    "updated_at",
                ],
            )
            return current
    except (DatabaseError, MetadataSnapshot.DoesNotExist):
        return snapshot


def _retry_allowed(snapshot, *, policy):
    if snapshot is None or snapshot.last_failure_at is None:
        return True
    return snapshot.last_failure_at <= timezone.now() - timedelta(
        seconds=policy.failure_retry_seconds,
    )


def _claim_refresh(snapshot, *, policy):
    if snapshot is None:
        return True, snapshot
    now = timezone.now()
    lease_cutoff = now - timedelta(seconds=policy.refresh_lease_seconds)
    try:
        with transaction.atomic():
            current = MetadataSnapshot.objects.select_for_update().get(pk=snapshot.pk)
            if (
                current.refresh_started_at is not None
                and current.refresh_started_at > lease_cutoff
            ):
                return False, current
            if not _retry_allowed(current, policy=policy):
                return False, current
            current.state = MetadataSnapshot.State.REFRESHING
            current.refresh_started_at = now
            current.last_attempted_at = now
            current.save(
                update_fields=[
                    "last_attempted_at",
                    "refresh_started_at",
                    "state",
                    "updated_at",
                ],
            )
            return True, current
    except (DatabaseError, MetadataSnapshot.DoesNotExist):
        return True, snapshot


def _queue_refresh(identity, snapshot, *, policy):
    claimed, snapshot = _claim_refresh(snapshot, policy=policy)
    if not claimed:
        return False, snapshot
    try:
        from app.tasks_metadata_snapshots import refresh_metadata_snapshot

        refresh_metadata_snapshot.apply_async(
            kwargs=identity.task_kwargs(),
            priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
        )
    except Exception as error:
        snapshot = _record_failure(snapshot, error=error)
        logger.warning(
            "Could not queue metadata refresh source=%s media_type=%s code=%s",
            identity.source,
            identity.media_type,
            _failure_code(error),
        )
        return False, snapshot
    return True, snapshot


def _annotate_payload(
    payload,
    *,
    identity,
    policy,
    snapshot,
    state,
    source,
    stale,
    refresh_queued=False,
):
    """Add a safe machine-readable cache state for UI and API clients."""
    result = copy.deepcopy(payload)
    result["_floppy_cache"] = {
        "consecutive_failures": (
            snapshot.consecutive_failures if snapshot is not None else 0
        ),
        "failure_code": snapshot.failure_code if snapshot is not None else "",
        "fetched_at": (
            snapshot.fetched_at.isoformat()
            if snapshot is not None and snapshot.fetched_at is not None
            else None
        ),
        "last_attempted_at": (
            snapshot.last_attempted_at.isoformat()
            if snapshot is not None and snapshot.last_attempted_at is not None
            else None
        ),
        "last_failure_at": (
            snapshot.last_failure_at.isoformat()
            if snapshot is not None and snapshot.last_failure_at is not None
            else None
        ),
        "policy": policy.public_dict(identity.source, identity.media_type),
        "refresh_queued": refresh_queued,
        "source": source,
        "stale": stale,
        "state": state,
    }
    return result


def _persist_local_item_snapshot(item, *, origin):
    policy = get_metadata_policy()
    if policy.persist_mode == "off":
        return None
    identity = build_metadata_identity(
        item.media_type,
        item.media_id,
        item.source,
        [item.season_number] if item.season_number is not None else None,
        item.episode_number,
    )
    try:
        return _save_snapshot(
            identity,
            item_metadata_payload(item),
            policy=policy,
            state=MetadataSnapshot.State.LOCAL,
            origin=origin,
            fetched_at=item.metadata_fetched_at,
            preserve_status=True,
        )
    except (DatabaseError, MetadataSnapshotRejected):
        return None


def sync_item_metadata_snapshot(
    sender,
    instance,
    created,
    raw=False,
    update_fields=None,
    **kwargs,
):
    """Keep imports and local Item changes available without a provider call."""
    del sender, kwargs
    if raw or _SUPPRESS_ITEM_SNAPSHOT_SYNC.get():
        return
    if update_fields and ITEM_METADATA_FIELDS.isdisjoint(update_fields):
        return
    origin = (
        MetadataSnapshot.Origin.IMPORT if created else MetadataSnapshot.Origin.ITEM
    )
    _persist_local_item_snapshot(instance, origin=origin)


def _provider_result(
    original,
    args,
    kwargs,
    *,
    identity,
    policy,
    snapshot,
    items,
    local_payload,
    origin,
):
    attempted_at = timezone.now()
    if snapshot is not None:
        try:
            MetadataSnapshot.objects.filter(pk=snapshot.pk).update(
                last_attempted_at=attempted_at,
                refresh_started_at=attempted_at,
                state=MetadataSnapshot.State.REFRESHING,
            )
            snapshot.last_attempted_at = attempted_at
            snapshot.refresh_started_at = attempted_at
            snapshot.state = MetadataSnapshot.State.REFRESHING
        except DatabaseError:
            pass

    try:
        result = original(*args, **kwargs)
    except ImproperlyConfigured:
        raise
    except Exception as error:
        blocked = type(error).__name__ == "ProviderNetworkUnavailable"
        snapshot = _record_failure(snapshot, error=error, blocked=blocked)
        if local_payload is None:
            raise
        logger.warning(
            "Metadata refresh failed source=%s media_type=%s code=%s; using local data",
            identity.source,
            identity.media_type,
            _failure_code(error),
        )
        return _annotate_payload(
            local_payload,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            state="blocked-local-copy" if blocked else "failed-local-copy",
            source="snapshot" if snapshot and snapshot.payload else "item",
            stale=True,
        )

    if not isinstance(result, dict):
        return result

    returned_payload = (
        merge_last_known_good(snapshot.payload, result)
        if policy.merge_mode == "preserve" and snapshot and snapshot.payload
        else copy.deepcopy(result)
    )
    effective_snapshot = snapshot
    if _should_persist(policy, items):
        try:
            effective_snapshot = _save_snapshot(
                identity,
                result,
                policy=policy,
                state=MetadataSnapshot.State.READY,
                origin=origin,
                fetched_at=attempted_at,
            )
            returned_payload = effective_snapshot.payload
            _apply_provider_payload_to_items(
                items,
                returned_payload,
                fetched_at=attempted_at,
            )
        except MetadataSnapshotRejected as error:
            effective_snapshot = _record_failure(snapshot, error=error)
            logger.warning(
                "Metadata payload was not persisted source=%s media_type=%s code=%s",
                identity.source,
                identity.media_type,
                error.code,
            )
            return _annotate_payload(
                result,
                identity=identity,
                policy=policy,
                snapshot=effective_snapshot,
                state="live-not-persisted",
                source="provider",
                stale=False,
            )
        except DatabaseError:
            logger.warning(
                "Metadata snapshot write failed source=%s media_type=%s",
                identity.source,
                identity.media_type,
            )

    return _annotate_payload(
        returned_payload,
        identity=identity,
        policy=policy,
        snapshot=effective_snapshot,
        state="current",
        source="provider",
        stale=False,
    )


def _resolve_metadata_call(original, args, kwargs):
    force_refresh = bool(kwargs.pop("_floppy_refresh", False))
    requested_origin = str(kwargs.pop("_floppy_origin", "provider") or "provider")
    origin = (
        requested_origin
        if requested_origin in MetadataSnapshot.Origin.values
        else MetadataSnapshot.Origin.REFRESH
    )

    def argument(name, position, default=None):
        return kwargs.get(name, args[position] if len(args) > position else default)

    try:
        identity = build_metadata_identity(
            argument("media_type", 0),
            argument("media_id", 1),
            argument("source", 2),
            argument("season_numbers", 3),
            argument("episode_number", 4),
            argument("language", 5),
            argument("edition_id", 6),
        )
    except MetadataSnapshotRejected:
        return original(*args, **kwargs)

    policy = get_metadata_policy()
    items = matching_items(identity)
    snapshot = _retained_snapshot(
        _snapshot(identity),
        policy=policy,
        has_items=bool(items),
    )
    local_payload = _local_payload(snapshot, items, policy=policy)

    if snapshot is None and items and policy.persist_mode != "off":
        snapshot = _persist_local_item_snapshot(
            items[0],
            origin=MetadataSnapshot.Origin.ITEM,
        )
        local_payload = _local_payload(snapshot, items, policy=policy)

    network_allowed = _network_allowed(identity)
    fresh = _snapshot_is_fresh(snapshot, policy=policy, identity=identity)
    incomplete = _payload_needs_completion(local_payload, identity)

    if local_payload is not None and fresh and not incomplete and not force_refresh:
        return _annotate_payload(
            local_payload,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            state="current",
            source="snapshot",
            stale=False,
        )

    if policy.read_mode == "local-only" or not network_allowed:
        if local_payload is None:
            raise LocalMetadataUnavailable(identity.source)
        if snapshot is not None and not network_allowed:
            snapshot = _record_failure(
                snapshot,
                error=LocalMetadataUnavailable(identity.source),
                blocked=True,
            )
        return _annotate_payload(
            local_payload,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            state="local-only" if policy.read_mode == "local-only" else "blocked-local-copy",
            source="snapshot" if snapshot and snapshot.payload else "item",
            stale=not fresh or incomplete,
        )

    if local_payload is None:
        return _provider_result(
            original,
            args,
            kwargs,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            items=items,
            local_payload=None,
            origin=origin,
        )

    should_block = (
        force_refresh
        or policy.read_mode == "network-first"
        or policy.refresh_mode == "blocking"
        or incomplete
    )
    if should_block and _retry_allowed(snapshot, policy=policy):
        return _provider_result(
            original,
            args,
            kwargs,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            items=items,
            local_payload=local_payload,
            origin=origin,
        )

    if policy.refresh_mode == "background" and _retry_allowed(
        snapshot,
        policy=policy,
    ):
        refresh_queued, snapshot = _queue_refresh(
            identity,
            snapshot,
            policy=policy,
        )
        return _annotate_payload(
            local_payload,
            identity=identity,
            policy=policy,
            snapshot=snapshot,
            state="refreshing" if refresh_queued else "stale",
            source="snapshot" if snapshot and snapshot.payload else "item",
            stale=True,
            refresh_queued=refresh_queued,
        )

    return _annotate_payload(
        local_payload,
        identity=identity,
        policy=policy,
        snapshot=snapshot,
        state="stale",
        source="snapshot" if snapshot and snapshot.payload else "item",
        stale=True,
    )


def install_metadata_snapshot_guard():
    """Install one local-first wrapper and register Item synchronization."""
    current_retriever = services.get_media_metadata
    if getattr(current_retriever, "_floppy_metadata_snapshot_guard", False):
        return current_retriever

    @functools.wraps(current_retriever)
    def guarded_retriever(*args, **kwargs):
        return _resolve_metadata_call(current_retriever, args, kwargs)

    guarded_retriever._floppy_metadata_snapshot_guard = True
    guarded_retriever._floppy_metadata_snapshot_original = current_retriever
    services.get_media_metadata = guarded_retriever
    post_save.connect(
        sync_item_metadata_snapshot,
        sender=Item,
        dispatch_uid="app.sync_item_metadata_snapshot",
        weak=False,
    )

    # Celery autodiscovery imports app.tasks only. Import this focused task
    # module here as well so every web and worker process registers the task.
    from app import tasks_metadata_snapshots  # noqa: F401, PLC0415

    return guarded_retriever
