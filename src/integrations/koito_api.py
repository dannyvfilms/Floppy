"""Koito API client for fetching listening history.

Receive-only: every request here is a GET. Floppy never submits listens to
Koito. Endpoint shapes were read from the Koito source (gabehf/Koito) since the
web API is unversioned and undocumented.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

import requests
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

USER_AGENT = "Floppy/1.0 (https://github.com/dannyvfilms/Floppy)"

# Koito caps `limit` at 500 and silently falls back to its 100 default above it.
MAX_LISTENS_PER_PAGE = 500
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3


class KoitoAPIError(Exception):
    """Base exception for Koito API errors."""


class KoitoAuthError(KoitoAPIError):
    """Raised when the API key is rejected."""


class KoitoRateLimitError(KoitoAPIError):
    """Raised when Koito reports too many requests."""


@dataclass
class KoitoListensResult:
    """Structured response for paginated listen fetches."""

    listens: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    total_pages: int = 0
    complete: bool = True
    interrupted: bool = False
    max_seen_uts: int | None = None


def _api_url(base_url: str, path: str) -> str:
    """Build an absolute Koito API URL."""
    return f"{base_url.rstrip('/')}/apis/web/v1/{path.lstrip('/')}"


def _make_api_request(
    base_url: str,
    api_key: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    stream: bool = False,
) -> Any:
    """GET a Koito endpoint with retry/backoff handling.

    Args:
        base_url: Koito server URL
        api_key: Decrypted Koito API key
        path: Path below /apis/web/v1/
        params: Query parameters
        stream: Return the raw response instead of parsed JSON

    Returns:
        Parsed JSON, or the raw response when stream=True

    Raises:
        KoitoAuthError: When the API key is rejected
        KoitoRateLimitError: When rate limited after retries
        KoitoAPIError: For any other failure
    """
    url = _api_url(base_url, path)
    headers = {
        "Authorization": f"Token {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    retry_delay = 1

    for attempt in range(MAX_RETRIES):
        try:
            start_time = time.time()
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                stream=stream,
            )
            duration = time.time() - start_time

            logger.debug(
                "Koito API request: path=%s, status=%s, duration=%.2fs",
                path,
                response.status_code,
                duration,
            )

            if response.status_code in (401, 403):
                msg = "Koito rejected the API key. Reconnect the integration."
                raise KoitoAuthError(msg)  # noqa: TRY301  # raised for the surrounding handler by design

            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                if attempt < MAX_RETRIES - 1:
                    delay = retry_delay * (2**attempt) + random.uniform(0, 1)  # noqa: S311  # sampling/jitter only, not cryptographic
                    logger.info(
                        "Koito rate limited, retrying after %.2fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    retry_delay = delay
                    continue
                msg = "Koito rate limit exceeded"
                raise KoitoRateLimitError(msg)  # noqa: TRY301  # raised for the surrounding handler by design

            response.raise_for_status()

            if stream:
                return response
            return response.json()

        except (KoitoAuthError, KoitoRateLimitError):
            raise
        except ValueError as e:
            msg = f"Koito returned invalid JSON: {e}"
            raise KoitoAPIError(msg) from e
        except requests.exceptions.RequestException as e:
            logger.warning("Koito API request failed: %s", e)
            if attempt < MAX_RETRIES - 1:
                delay = retry_delay * (2**attempt) + random.uniform(0, 1)  # noqa: S311  # sampling/jitter only, not cryptographic
                time.sleep(delay)
                retry_delay = delay
                continue
            msg = f"Request failed: {e}"
            raise KoitoAPIError(msg) from e

    msg = "Max retries exceeded"
    raise KoitoAPIError(msg)


def get_listens(
    base_url: str,
    api_key: str,
    from_timestamp_uts: int | None = None,
    to_timestamp_uts: int | None = None,
    page: int = 1,
    limit: int = MAX_LISTENS_PER_PAGE,
) -> dict[str, Any]:
    """Fetch one page of listens.

    Returns:
        Dict with `items`, `total_record_count`, `has_next_page`, `current_page`
    """
    params: dict[str, Any] = {
        "limit": min(limit, MAX_LISTENS_PER_PAGE),
        "page": max(page, 1),
    }
    if from_timestamp_uts is not None:
        params["from"] = from_timestamp_uts
    if to_timestamp_uts is not None:
        params["to"] = to_timestamp_uts

    return _make_api_request(base_url, api_key, "listens", params)


def get_track(base_url: str, api_key: str, track_id: int) -> dict[str, Any]:
    """Fetch full track metadata.

    The listens endpoint returns only id/title/artists, so MusicBrainz IDs,
    duration and album id have to be hydrated per track.
    """
    return _make_api_request(base_url, api_key, f"track/{track_id}")


def get_album(base_url: str, api_key: str, album_id: int) -> dict[str, Any]:
    """Fetch album metadata for a hydrated track."""
    return _make_api_request(base_url, api_key, f"album/{album_id}")


def get_export(base_url: str, api_key: str) -> Any:
    """Fetch the full listening-history export.

    Unpaginated; the caller is responsible for streaming/chunking it.
    """
    return _make_api_request(base_url, api_key, "export")


def validate_connection(base_url: str, api_key: str) -> bool:
    """Confirm the URL and key work by requesting a single listen.

    Raises:
        KoitoAuthError: When the API key is rejected
        KoitoAPIError: When the server is unreachable or misbehaving
    """
    get_listens(base_url, api_key, limit=1)
    return True


def get_listens_window(
    base_url: str,
    api_key: str,
    from_timestamp_uts: int | None = None,
    to_timestamp_uts: int | None = None,
    page_start: int = 1,
    max_pages: int | None = None,
) -> KoitoListensResult:
    """Fetch a window of listens, handling pagination.

    Mirrors `lastfm_api.get_recent_tracks_window`: on a mid-pagination failure
    the partial result is returned with `interrupted=True` so the caller knows
    not to advance its cursor.
    """
    result = KoitoListensResult()
    page = max(page_start, 1)

    while True:
        try:
            data = get_listens(
                base_url,
                api_key,
                from_timestamp_uts=from_timestamp_uts,
                to_timestamp_uts=to_timestamp_uts,
                page=page,
            )
        except KoitoAPIError:
            if result.listens:
                # Keep what we have but flag it so the cursor stays put.
                result.complete = False
                result.interrupted = True
                return result
            raise

        items = data.get("items") or []
        result.listens.extend(items)
        result.pages_fetched += 1

        for item in items:
            uts = listen_timestamp_uts(item)
            if uts is None:
                continue
            if result.max_seen_uts is None or uts > result.max_seen_uts:
                result.max_seen_uts = uts

        total_count = data.get("total_record_count") or 0
        per_page = data.get("items_per_page") or MAX_LISTENS_PER_PAGE
        result.total_pages = (
            -(-total_count // per_page) if per_page else result.pages_fetched
        )

        if not data.get("has_next_page"):
            return result

        page += 1

        if max_pages is not None and result.pages_fetched >= max_pages:
            result.complete = False
            return result

        # Be gentle with self-hosted instances.
        time.sleep(0.2)


def listen_timestamp_uts(listen: dict[str, Any]) -> int | None:
    """Return a listen's play time as a Unix timestamp in seconds.

    Koito serialises `time` as RFC3339 with an offset, unlike Last.fm's bare
    integer, so it has to be parsed rather than cast.
    """
    raw = listen.get("time")
    if not raw:
        return None
    try:
        parsed = parse_datetime(raw)
    except (ValueError, TypeError):
        return None
    if parsed is None:
        return None
    return int(parsed.timestamp())
