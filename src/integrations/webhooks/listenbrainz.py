"""Processor for ListenBrainz-compatible scrobble submissions.

Handles listens pushed to Floppy by any client that speaks the ListenBrainz
submit protocol (Multi-Scrobbler, Navidrome, Pano Scrobbler, Feishin, ...).
Receive-only: nothing here submits listens anywhere else.
"""

import logging
from datetime import UTC, datetime

from django.utils import timezone

from app.services import music_scrobble

logger = logging.getLogger(__name__)


class ListenBrainzScrobbleProcessor:
    """Processor for ListenBrainz `submit-listens` payloads."""

    def process_listen(self, listen: dict, user) -> music_scrobble.Music | None:
        """Process a single ListenBrainz listen and record it as a scrobble.

        Args:
            listen: A single entry from the submission `payload` list
            user: User instance

        Returns:
            Music instance if created/updated, None otherwise
        """
        metadata = listen.get("track_metadata") or {}

        track_title = (metadata.get("track_name") or "").strip()
        artist_name = (metadata.get("artist_name") or "").strip()
        if not track_title or not artist_name:
            logger.debug("Skipping listen without track_name/artist_name")
            return None

        album_title = (metadata.get("release_name") or "").strip() or None

        additional = metadata.get("additional_info") or {}

        external_ids = {}
        recording_mbid = additional.get("recording_mbid")
        if recording_mbid:
            external_ids["musicbrainz_recording"] = recording_mbid

        release_mbid = additional.get("release_mbid")
        if release_mbid:
            external_ids["musicbrainz_release"] = release_mbid

        artist_mbids = additional.get("artist_mbids")
        if isinstance(artist_mbids, list) and artist_mbids:
            external_ids["musicbrainz_artist"] = artist_mbids[0]
        elif additional.get("artist_mbid"):
            external_ids["musicbrainz_artist"] = additional["artist_mbid"]

        # listened_at is required for a recorded listen; playing_now is filtered
        # out by the view before it reaches here.
        try:
            played_at_uts = int(listen["listened_at"])
            played_at = datetime.fromtimestamp(played_at_uts, tz=UTC)
            played_at = timezone.localtime(played_at)
        except (KeyError, ValueError, TypeError, OSError) as e:
            logger.warning("Invalid listened_at for track %s: %s", track_title, e)
            return None

        if music_scrobble.is_duplicate_scrobble(
            user,
            played_at_uts,
            artist_name,
            track_title,
            album_title,
        ):
            logger.debug(
                "Skipping duplicate listen: %s - %s (%s)",
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
            track_number=_coerce_int(additional.get("track_number")),
            duration_ms=_resolve_duration_ms(additional),
            plex_rating_key=None,
            external_ids=external_ids,
            completed=True,
            played_at=played_at,
        )

        try:
            music_entry = music_scrobble.record_music_playback(event)
        except Exception:
            logger.exception(
                "Error processing ListenBrainz listen for %s: %s - %s",
                user.username,
                artist_name,
                track_title,
            )
            return None

        if music_entry:
            logger.info(
                "Processed ListenBrainz listen for %s: %s - %s "
                "(status=%s, progress=%s)",
                user.username,
                artist_name,
                track_title,
                music_entry.status,
                music_entry.progress,
            )
        return music_entry

    def process_listens(self, listens: list[dict], user) -> dict[str, int | set]:
        """Process a batch of ListenBrainz listens.

        Args:
            listens: List of listen dicts from the submission payload
            user: User instance

        Returns:
            Dict with counts: processed, skipped, errors, and affected_day_keys (set)
        """
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
                logger.exception("Error processing ListenBrainz listen")
                stats["errors"] += 1

        return stats


def _coerce_int(value) -> int | None:
    """Return value as an int, or None when it is missing or unparseable."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _resolve_duration_ms(additional: dict) -> int | None:
    """Return duration in milliseconds from either duration_ms or duration."""
    duration_ms = _coerce_int(additional.get("duration_ms"))
    if duration_ms:
        return duration_ms
    # Some clients send whole seconds as `duration` instead.
    duration_s = _coerce_int(additional.get("duration"))
    if duration_s:
        return duration_s * 1000
    return None
