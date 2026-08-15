"""Pinned Anime-IDs snapshots shared by grouped-anime integrations.

The mapping is an input to persistent library writes, so it must be treated as
versioned data rather than an ordinary read-through cache.  A snapshot contains
the raw mapping and the compiled reverse indexes used by the classifier.  The
compiled form is cached under the approved revision and digest so a worker does
not rebuild the full mapping for every Stremio series or webhook.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.cache import cache

from app.providers import services

logger = logging.getLogger(__name__)

APPROVED_REVISION = "049cd475b567d282886e7ce81f4168dbdec33c14"
APPROVED_DIGEST = "0ba1a83c4512da9c6770c47aa03843f906ad3d607eb077a06b366f64b23865b6"
MAPPING_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Kometa-Team/Anime-IDs/{revision}/"
    "anime_ids.json"
)
SNAPSHOT_CACHE_PREFIX = "anime_mapping_snapshot_v2"
LAST_GOOD_CACHE_KEY = f"{SNAPSHOT_CACHE_PREFIX}:last-good"
SNAPSHOT_CACHE_TIMEOUT = 86400
SNAPSHOT_BUILD_COUNT = 0
MAX_MAPPING_BYTES = 8 * 1024 * 1024
MAX_MAPPING_ENTRIES = 50_000
SUPPORTED_ID_FIELDS = (
    "tmdb_show_id",
    "tmdb_id",
    "tmdb_tv_id",
    "tvdb_id",
    "imdb_id",
)
ALLOWED_ENTRY_FIELDS = frozenset(
    {
        *SUPPORTED_ID_FIELDS,
        "tmdb_movie_id",
        "tvdb_season",
        "tvdb_epoffset",
        "mal_id",
        "anilist_id",
    },
)
TEST_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "tests" / "mock_data" / "anime_mapping.json"
)


@dataclass(frozen=True, slots=True)
class AnimeMappingSnapshot:
    """Immutable mapping data and indexes for one approved input revision."""

    revision: str
    digest: str
    raw_data: Mapping[str, Any]
    indexes: Mapping[str, Mapping[str, tuple[Mapping[str, Any], ...]]]
    groups: Mapping[str, tuple[Mapping[str, Any], ...]]
    entry_count: int
    build_ms: float


def _normalize_ids(value: Any) -> set[str]:
    """Normalize scalar, list, and comma-separated external IDs."""
    if value in (None, ""):
        return set()
    values = value if isinstance(value, (list, tuple, set)) else str(value).split(",")
    return {str(entry).strip() for entry in values if str(entry).strip()}


def _canonical_digest(data: dict[str, Any]) -> str:
    """Return a stable digest independent of source JSON formatting."""
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-shaped values exposed by a snapshot."""
    if isinstance(value, dict):
        from types import MappingProxyType

        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Convert an in-memory frozen snapshot into cache-serializable JSON values."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _validate_mapping_data(data: Any) -> dict[str, Any]:
    """Validate the bounded object shape before it can become active."""
    if not isinstance(data, dict):
        message = "Anime-IDs mapping must be a JSON object"
        raise TypeError(message)
    if len(data) > MAX_MAPPING_ENTRIES:
        message = (
            f"Anime-IDs mapping has too many entries: {len(data)} > "
            f"{MAX_MAPPING_ENTRIES}"
        )
        raise ValueError(message)

    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_MAPPING_BYTES:
        message = f"Anime-IDs mapping is too large: {len(encoded)} > {MAX_MAPPING_BYTES} bytes"
        raise ValueError(message)

    for mapping_key, raw_entry in data.items():
        if not isinstance(mapping_key, str) or not mapping_key.strip():
            message = "Anime-IDs mapping keys must be non-empty strings"
            raise ValueError(message)
        if not isinstance(raw_entry, dict):
            message = f"Anime-IDs entry {mapping_key!r} must be an object"
            raise TypeError(message)
        unknown_fields = set(raw_entry) - ALLOWED_ENTRY_FIELDS
        if unknown_fields:
            message = (
                f"Anime-IDs entry {mapping_key!r} has unsupported fields: "
                f"{sorted(unknown_fields)}"
            )
            raise ValueError(message)
        for field, value in raw_entry.items():
            if value is not None and not isinstance(value, (str, int, float, list)):
                message = (
                    f"Anime-IDs entry {mapping_key!r} field {field!r} has an "
                    f"unsupported value type: {type(value).__name__}"
                )
                raise ValueError(message)
            if isinstance(value, list) and any(
                not isinstance(member, (str, int, float)) for member in value
            ):
                message = (
                    f"Anime-IDs entry {mapping_key!r} field {field!r} contains "
                    "a non-scalar list member"
                )
                raise ValueError(message)

    return data


class _DisjointSet:
    """Small union-find implementation used while compiling identity groups."""

    def __init__(self, size: int):
        self.parents = list(range(size))

    def find(self, value: int) -> int:
        parent = self.parents[value]
        if parent != value:
            self.parents[value] = self.find(parent)
        return self.parents[value]

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parents[right_root] = left_root


def build_mapping_indexes(
    mapping_data: dict[str, Any],
    *,
    revision: str = "inline",
) -> tuple[
    dict[str, dict[str, tuple[dict[str, Any], ...]]],
    dict[str, tuple[dict[str, Any], ...]],
]:
    """Build exact indexes and connected provider-identity groups."""
    records: list[dict[str, Any]] = []
    field_members: dict[str, dict[str, list[int]]] = {
        field: defaultdict(list) for field in SUPPORTED_ID_FIELDS
    }

    for mapping_key, raw_entry in mapping_data.items():
        mal_ids = tuple(sorted(_normalize_ids(raw_entry.get("mal_id"))))
        if not mal_ids:
            continue
        record = {
            "mapping_key": str(mapping_key),
            "mal_ids": mal_ids,
        }
        for field in SUPPORTED_ID_FIELDS:
            values = tuple(sorted(_normalize_ids(raw_entry.get(field))))
            record[field] = values
        record_index = len(records)
        records.append(record)
        for field in SUPPORTED_ID_FIELDS:
            for external_id in record[field]:
                field_members[field][external_id].append(record_index)

    disjoint_set = _DisjointSet(len(records))
    for members in field_members.values():
        for record_index in members.values():
            for other_index in record_index[1:]:
                disjoint_set.union(record_index[0], other_index)

    group_members: dict[int, list[int]] = defaultdict(list)
    for record_index in range(len(records)):
        group_members[disjoint_set.find(record_index)].append(record_index)

    groups: dict[str, tuple[dict[str, Any], ...]] = {}
    record_groups: dict[int, str] = {}
    for member_indexes in group_members.values():
        member_records = tuple(
            sorted(
                (records[index] for index in member_indexes),
                key=lambda record: record["mapping_key"],
            ),
        )
        group_identity = {
            "revision": revision,
            "mapping_keys": [record["mapping_key"] for record in member_records],
            "provider_ids": {
                field: sorted(
                    {
                        external_id
                        for record in member_records
                        for external_id in record[field]
                    },
                )
                for field in SUPPORTED_ID_FIELDS
            },
        }
        group_key = hashlib.sha256(
            json.dumps(
                group_identity,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        ).hexdigest()
        enriched_records = tuple(
            {**record, "mapping_group_key": group_key} for record in member_records
        )
        groups[group_key] = enriched_records
        for record_index in member_indexes:
            record_groups[record_index] = group_key

    indexes: dict[str, dict[str, tuple[dict[str, Any], ...]]] = {}
    for field, external_ids in field_members.items():
        indexes[field] = {
            external_id: tuple(
                {
                    **records[index],
                    "mapping_group_key": record_groups[index],
                }
                for index in record_indexes
            )
            for external_id, record_indexes in external_ids.items()
        }
    return indexes, groups


def _snapshot_cache_key(revision: str, digest: str) -> str:
    return f"{SNAPSHOT_CACHE_PREFIX}:{revision}:{digest}"


def _build_snapshot(
    data: dict[str, Any],
    *,
    revision: str,
    digest: str,
) -> AnimeMappingSnapshot:
    global SNAPSHOT_BUILD_COUNT  # noqa: PLW0603 - process-local audit counter

    SNAPSHOT_BUILD_COUNT += 1
    started = time.perf_counter()
    validated = _validate_mapping_data(data)
    indexes, groups = build_mapping_indexes(validated, revision=revision)
    build_ms = (time.perf_counter() - started) * 1000
    snapshot = AnimeMappingSnapshot(
        revision=revision,
        digest=digest,
        raw_data=_freeze(validated),
        indexes=_freeze(indexes),
        groups=_freeze(groups),
        entry_count=len(validated),
        build_ms=build_ms,
    )
    logger.info(
        "anime_mapping_snapshot_build revision=%s digest=%s entries=%s "
        "groups=%s build_ms=%.2f build_count=%s",
        revision,
        digest,
        snapshot.entry_count,
        len(snapshot.groups),
        build_ms,
        SNAPSHOT_BUILD_COUNT,
    )
    return snapshot


def _snapshot_payload(snapshot: AnimeMappingSnapshot) -> dict[str, Any]:
    """Return a plain cache payload; MappingProxyType is intentionally not pickled."""
    return {
        "revision": snapshot.revision,
        "digest": snapshot.digest,
        "raw_data": _thaw(snapshot.raw_data),
        "indexes": _thaw(snapshot.indexes),
        "groups": _thaw(snapshot.groups),
        "entry_count": snapshot.entry_count,
        "build_ms": snapshot.build_ms,
    }


def _snapshot_from_cache(cached: dict[str, Any]) -> AnimeMappingSnapshot:
    """Restore and freeze a validated snapshot cache payload."""
    return AnimeMappingSnapshot(
        revision=cached["revision"],
        digest=cached["digest"],
        raw_data=_freeze(cached["raw_data"]),
        indexes=_freeze(cached["indexes"]),
        groups=_freeze(cached["groups"]),
        entry_count=int(cached["entry_count"]),
        build_ms=float(cached["build_ms"]),
    )


def _load_source_data() -> tuple[dict[str, Any], str, str]:
    """Load the approved source or the deterministic test fixture."""
    if settings.TESTING and TEST_FIXTURE_PATH.exists():
        with TEST_FIXTURE_PATH.open(encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return data, "test-fixture", _canonical_digest(data)

    revision = APPROVED_REVISION
    data = services.api_request(
        "ANIME_MAPPING",
        "GET",
        MAPPING_URL_TEMPLATE.format(revision=revision),
    )
    digest = _canonical_digest(data or {})
    if digest != APPROVED_DIGEST:
        message = f"Anime-IDs digest mismatch for revision {revision}: {digest}"
        raise ValueError(message)
    return data or {}, revision, digest


def load_mapping_snapshot(
    mapping_data: dict[str, Any] | None = None,
) -> AnimeMappingSnapshot:
    """Return one compiled mapping snapshot, building it only on cache miss."""
    if mapping_data is not None:
        digest = _canonical_digest(mapping_data)
        return _build_snapshot(mapping_data, revision="inline", digest=digest)

    source_data = None
    if settings.TESTING:
        source_data, revision, digest = _load_source_data()
    else:
        revision, digest = APPROVED_REVISION, APPROVED_DIGEST

    cache_key = _snapshot_cache_key(revision, digest)
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        try:
            return _snapshot_from_cache(cached)
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "anime_mapping_snapshot_cache_invalid revision=%s digest=%s",
                revision,
                digest,
            )

    try:
        if source_data is None:
            data, source_revision, source_digest = _load_source_data()
        else:
            data, source_revision, source_digest = source_data, revision, digest
        snapshot = _build_snapshot(
            data,
            revision=source_revision,
            digest=source_digest,
        )
    except Exception as error:
        fallback = cache.get(LAST_GOOD_CACHE_KEY)
        if isinstance(fallback, dict):
            try:
                snapshot = _snapshot_from_cache(fallback)
            except (KeyError, TypeError, ValueError):
                snapshot = None
            if snapshot is not None:
                logger.warning(
                    "anime_mapping_snapshot_fallback revision=%s digest=%s error=%s",
                    snapshot.revision,
                    snapshot.digest,
                    error,
                )
                return snapshot
        raise

    payload = _snapshot_payload(snapshot)
    cache.set(
        _snapshot_cache_key(snapshot.revision, snapshot.digest),
        payload,
        timeout=SNAPSHOT_CACHE_TIMEOUT,
    )
    # The payload is immutable/versioned and the pointer is a single cache
    # write, so a refresh can never expose a half-built index.
    cache.set(LAST_GOOD_CACHE_KEY, payload, timeout=SNAPSHOT_CACHE_TIMEOUT)
    return snapshot


def refresh_mapping_snapshot(
    revision: str,
    *,
    expected_digest: str | None = None,
    activate: bool = False,
) -> AnimeMappingSnapshot:
    """Fetch, validate, compile, and optionally activate a pinned revision."""
    data = services.api_request(
        "ANIME_MAPPING",
        "GET",
        MAPPING_URL_TEMPLATE.format(revision=revision),
    )
    digest = _canonical_digest(data or {})
    if expected_digest and digest != expected_digest:
        message = f"Anime-IDs digest mismatch for revision {revision}: {digest}"
        raise ValueError(message)
    snapshot = _build_snapshot(data or {}, revision=revision, digest=digest)
    payload = _snapshot_payload(snapshot)
    cache.set(
        _snapshot_cache_key(snapshot.revision, snapshot.digest),
        payload,
        timeout=SNAPSHOT_CACHE_TIMEOUT,
    )
    if activate:
        cache.set(LAST_GOOD_CACHE_KEY, payload, timeout=SNAPSHOT_CACHE_TIMEOUT)
    logger.info(
        "anime_mapping_snapshot_refresh revision=%s digest=%s entries=%s activated=%s",
        snapshot.revision,
        snapshot.digest,
        snapshot.entry_count,
        activate,
    )
    return snapshot


def load_mapping_data() -> dict[str, Any]:
    """Return raw mapping data for legacy anime import helpers."""
    return load_mapping_snapshot().raw_data


def _normalize_mal_ids(mal_value: Any) -> set[str]:
    """Return MAL IDs normalized from scalar or comma-separated values."""
    return _normalize_ids(mal_value)


def find_entries_for_mal_id(mal_id: str | int) -> list[dict[str, Any]]:
    """Return mapping entries that include the MAL ID."""
    normalized = str(mal_id)
    return [
        entry
        for entry in load_mapping_data().values()
        if normalized in _normalize_mal_ids(entry.get("mal_id"))
    ]


def resolve_provider_series_id(mal_id: str | int, provider: str) -> str | None:
    """Resolve a grouped-provider series ID for a MAL title."""
    entries = find_entries_for_mal_id(mal_id)
    if not entries:
        return None

    if provider == "tvdb":
        for entry in entries:
            if entry.get("tvdb_id") not in (None, ""):
                return str(entry["tvdb_id"])
        return None

    if provider == "tmdb":
        for key in ("tmdb_show_id", "tmdb_id", "tmdb_tv_id"):
            for entry in entries:
                if entry.get(key) not in (None, ""):
                    return str(entry[key])
        return None

    return None
