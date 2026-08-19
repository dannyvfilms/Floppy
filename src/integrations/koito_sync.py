"""Shared helpers for Koito incremental sync and history backfills."""

import logging

from integrations import koito_api
from integrations.imports import helpers
from integrations.webhooks.koito import KoitoScrobbleProcessor

logger = logging.getLogger(__name__)

KOITO_HISTORY_IMPORT_LOCK_PREFIX = "koito_history_import_lock:"


def get_koito_history_import_lock_key(user_id: int) -> str:
    """Return the cache lock key for a user's Koito history import."""
    return f"{KOITO_HISTORY_IMPORT_LOCK_PREFIX}{user_id}"


def get_account_credentials(account) -> tuple[str, str]:
    """Return the account's base URL and decrypted API key.

    Raises:
        MediaImportError: When the stored key cannot be decrypted.
    """
    return account.base_url, helpers.decrypt_or_raise(account.api_key)


def _listen_timestamp(listen: dict) -> int:
    """Return the listen timestamp for stable oldest-first processing."""
    return koito_api.listen_timestamp_uts(listen) or 0


def sync_koito_account(
    account,
    *,
    from_timestamp_uts: int | None = None,
    to_timestamp_uts: int | None = None,
    page_start: int = 1,
    max_pages: int | None = None,
) -> dict:
    """Fetch and process Koito listens for a single account."""
    base_url, api_key = get_account_credentials(account)

    fetch_result = koito_api.get_listens_window(
        base_url,
        api_key,
        from_timestamp_uts=from_timestamp_uts,
        to_timestamp_uts=to_timestamp_uts,
        page_start=page_start,
        max_pages=max_pages,
    )

    listens = sorted(fetch_result.listens, key=_listen_timestamp)
    processor = KoitoScrobbleProcessor(base_url, api_key, account_id=account.id)
    stats = processor.process_listens(listens, account.user)

    result = {
        "listens": listens,
        "pages_fetched": fetch_result.pages_fetched,
        "total_pages": fetch_result.total_pages,
        "complete": fetch_result.complete,
        "interrupted": fetch_result.interrupted,
        "max_seen_uts": fetch_result.max_seen_uts,
        **stats,
    }
    logger.debug(
        (
            "Koito sync result for user %s: pages=%s/%s "
            "complete=%s processed=%s skipped=%s errors=%s"
        ),
        account.user.username,
        fetch_result.pages_fetched,
        fetch_result.total_pages,
        fetch_result.complete,
        stats["processed"],
        stats["skipped"],
        stats["errors"],
    )
    return result


def _primary_alias(entity: dict) -> str:
    """Return an entity's display name from its Koito alias list.

    The export identifies tracks/albums/artists by alias rather than a title
    field, flagging one entry with `is_primary`.
    """
    aliases = (entity or {}).get("aliases") or []
    for alias in aliases:
        if isinstance(alias, dict) and alias.get("is_primary") and alias.get("alias"):
            return alias["alias"]
    for alias in aliases:
        if isinstance(alias, dict) and alias.get("alias"):
            return alias["alias"]
    return ""


def export_to_listens(export_payload) -> list[dict]:
    """Normalize a Koito export into the shape the processor expects.

    The export carries richer metadata than `/listens` (track/album/artist
    MBIDs and duration), so details are attached inline and the processor skips
    its per-track hydration calls entirely.
    """
    items = export_payload
    if isinstance(export_payload, dict):
        items = export_payload.get("listens") or []

    listens = []
    for item in items or []:
        track = item.get("track") or {}
        album = item.get("album") or {}
        artists = item.get("artists") or []

        # Prefer the artist Koito marks primary, else the first with a name.
        primary_artist = next(
            (a for a in artists if isinstance(a, dict) and a.get("is_primary")),
            artists[0] if artists else {},
        )
        artist_name = _primary_alias(primary_artist)

        duration_s = track.get("duration") or 0

        listens.append(
            {
                "time": item.get("listened_at"),
                "track": {
                    "id": None,
                    "title": _primary_alias(track),
                    "artists": [{"name": artist_name}] if artist_name else [],
                },
                # Pre-hydrated, so the processor skips /track/{id}.
                "_details": {
                    "musicbrainz_recording": track.get("mbid") or "",
                    "musicbrainz_release": album.get("mbid") or "",
                    "musicbrainz_artist": primary_artist.get("mbid") or "",
                    "album_title": _primary_alias(album),
                    "duration_ms": int(duration_s) * 1000 if duration_s else None,
                    "track_number": None,
                },
            },
        )
    return listens
