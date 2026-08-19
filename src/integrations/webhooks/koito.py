"""Processor for Koito listens.

Koito's `/listens` endpoint returns only time, track id/title, artist names and
an image — no MusicBrainz IDs, no album, no duration. Those are hydrated per
track via `/track/{id}`, cached because track ids repeat heavily across listens.

Receive-only: nothing here writes back to Koito.
"""

import logging
from datetime import UTC, datetime

from django.core.cache import cache
from django.utils import timezone

from app.services import music_scrobble
from integrations import koito_api
from integrations.imports.helpers import retry_on_lock

logger = logging.getLogger(__name__)

# Koito track metadata is effectively immutable; a long TTL keeps the
# hydration call count near one per distinct track rather than per listen.
TRACK_CACHE_TIMEOUT = 60 * 60 * 24


def _first_artist_name(track: dict) -> str:
    """Return the first named artist credited on a Koito track."""
    for artist in track.get("artists") or []:
        name = (artist.get("name") or "").strip()
        if name:
            return name
    return ""


def _external_ids(details: dict) -> dict:
    """Map hydrated Koito details onto MusicBrainz external ids."""
    keys = ("musicbrainz_recording", "musicbrainz_release", "musicbrainz_artist")
    return {key: details[key] for key in keys if details.get(key)}


class KoitoScrobbleProcessor:
    """Processor for Koito listen data."""

    def __init__(self, base_url: str, api_key: str, account_id: int | None = None):
        """Store connection details and per-run hydration cache."""
        self.base_url = base_url
        self.api_key = api_key
        self.account_id = account_id
        self._track_cache: dict[int, dict] = {}

    def process_listen(self, listen: dict, user) -> music_scrobble.Music | None:
        """Process a single Koito listen and record it as a scrobble."""
        track = listen.get("track") or {}
        track_title = (track.get("title") or "").strip()
        if not track_title:
            logger.debug("Skipping Koito listen without a track title")
            return None

        artist_name = _first_artist_name(track)
        if not artist_name:
            logger.debug("Skipping Koito listen without an artist: %s", track_title)
            return None

        played_at_uts = koito_api.listen_timestamp_uts(listen)
        if played_at_uts is None:
            logger.debug("Skipping Koito listen without a usable time: %s", track_title)
            return None

        try:
            played_at = datetime.fromtimestamp(played_at_uts, tz=UTC)
            played_at = timezone.localtime(played_at)
        except (ValueError, TypeError, OSError) as e:
            logger.warning("Invalid time for Koito listen %s: %s", track_title, e)
            return None

        # Export-sourced listens arrive pre-hydrated; polled listens do not.
        details = listen.get("_details")
        if details is None:
            details = self._hydrate_track(track.get("id"))
        album_title = (details.get("album_title") or "").strip() or None

        external_ids = _external_ids(details)

        if music_scrobble.is_duplicate_scrobble(
            user,
            played_at_uts,
            artist_name,
            track_title,
            album_title,
        ):
            logger.debug(
                "Skipping duplicate Koito listen: %s - %s (%s)",
                artist_name,
                track_title,
                played_at_uts,
            )
            return None

        event = music_scrobble.MusicPlaybackEvent(
            user=user,
            track_title=track_title,
            artist_name=artist_name,
            album_title=album_title,
            track_number=details.get("track_number"),
            duration_ms=details.get("duration_ms"),
            plex_rating_key=None,
            external_ids=external_ids,
            completed=True,
            played_at=played_at,
        )

        try:
            music_entry = retry_on_lock(lambda: music_scrobble.record_music_playback(event))
        except Exception:
            logger.exception(
                "Error processing Koito listen for %s: %s - %s",
                user.username,
                artist_name,
                track_title,
            )
            return None

        if music_entry:
            logger.info(
                "Processed Koito listen for %s: %s - %s (status=%s, progress=%s)",
                user.username,
                artist_name,
                track_title,
                music_entry.status,
                music_entry.progress,
            )
        return music_entry

    def process_listens(self, listens: list[dict], user) -> dict[str, int | set]:
        """Process a batch of Koito listens, oldest first."""
        from app import history_cache

        stats = {"processed": 0, "skipped": 0, "errors": 0, "affected_day_keys": set()}

        for listen in listens:
            try:
                result = self.process_listen(listen, user)
                if result is None:
                    stats["skipped"] += 1
                else:
                    stats["processed"] += 1
                    if result.end_date:
                        day_key = history_cache.history_day_key(result.end_date)
                        if day_key:
                            stats["affected_day_keys"].add(day_key)
            except Exception:
                logger.exception("Error processing Koito listen")
                stats["errors"] += 1

        return stats

    def _hydrate_track(self, track_id) -> dict:
        """Return MBIDs, duration and album title for a Koito track id.

        Falls back to an empty dict when the track cannot be fetched — a listen
        with only artist/title still records, just with weaker matching.
        """
        if not track_id:
            return {}

        if track_id in self._track_cache:
            return self._track_cache[track_id]

        cache_key = f"koito_track:{self.account_id or 'anon'}:{track_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            self._track_cache[track_id] = cached
            return cached

        try:
            data = koito_api.get_track(self.base_url, self.api_key, track_id)
        except koito_api.KoitoAPIError as e:
            logger.debug("Could not hydrate Koito track %s: %s", track_id, e)
            self._track_cache[track_id] = {}
            return {}

        details = self._build_details(data)
        cache.set(cache_key, details, TRACK_CACHE_TIMEOUT)
        self._track_cache[track_id] = details
        return details

    def _build_details(self, data: dict) -> dict:
        """Normalize a Koito track response into playback-event fields."""
        # Koito stores track duration in whole seconds (it divides any
        # submitted duration_ms by 1000 on ingest).
        duration_s = data.get("duration") or 0

        # Koito exposes artists as {id, name} only, so no artist MBID is
        # available here; record_music_playback resolves it via MusicBrainz.
        details = {
            "musicbrainz_recording": data.get("musicbrainz_id") or "",
            "musicbrainz_release": "",
            "album_title": "",
            "duration_ms": int(duration_s) * 1000 if duration_s else None,
            "track_number": None,
        }

        album_id = data.get("album_id")
        if album_id:
            try:
                album = koito_api.get_album(self.base_url, self.api_key, album_id)
            except koito_api.KoitoAPIError as e:
                logger.debug("Could not hydrate Koito album %s: %s", album_id, e)
            else:
                details["album_title"] = album.get("title") or ""
                details["musicbrainz_release"] = album.get("musicbrainz_id") or ""

        return details
