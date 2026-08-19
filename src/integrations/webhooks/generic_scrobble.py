"""Durable-write processor for the generic /api/v1/scrobble/ endpoint.

Unlike vendor webhook processors, third-party API clients already send
normalized ids and media type — there is no vendor payload to parse, so
this processor only needs to bridge that normalized shape into the shared
TMDB-resolution and DB-write logic in ``BaseWebhookProcessor``.
"""

from app.live_playback import (
    PLAYBACK_SCROBBLE_BUFFER_SECONDS,
    PLAYBACK_SCROBBLE_FALLBACK_SECONDS,
)
from app.models import MediaTypes

from .base import BaseWebhookProcessor

# The API speaks "movie"/"episode" (matching apply_playback_event's
# playback_media_type vocabulary); the base processor routes on TV/MOVIE.
_MEDIA_TYPE_MAPPING = {
    "movie": MediaTypes.MOVIE.value,
    "episode": MediaTypes.TV.value,
}


def is_played(payload):
    """Completed if the client says so, else via position/duration.

    Reuses the same buffer/fallback heuristic the live playback card
    already uses to guess completion, so "played" detection is consistent
    across the scrobble, live-card and playback-progress surfaces.
    """
    completed = payload.get("completed")
    if completed is not None:
        return bool(completed)

    position = payload.get("position_seconds")
    if position is None:
        return False

    duration = payload.get("duration_seconds")
    if duration:
        return position >= duration - PLAYBACK_SCROBBLE_BUFFER_SECONDS
    return position >= PLAYBACK_SCROBBLE_FALLBACK_SECONDS


class GenericScrobbleProcessor(BaseWebhookProcessor):
    """Processor for normalized scrobble-stop events from the API."""

    def process_payload(self, payload, user):
        """Resolve and persist a stop/completion event from the API."""
        ids = self._extract_external_ids(payload)
        if not any(ids.values()):
            return
        self._process_media(payload, user, ids)

    def _is_supported_event(self, event_type):
        return True

    def _is_played(self, payload):
        return is_played(payload)

    def _get_media_type(self, payload):
        return _MEDIA_TYPE_MAPPING.get(payload.get("media_type"))

    def _get_media_title(self, payload):
        return payload.get("title") or payload.get("series_title")

    def _extract_external_ids(self, payload):
        ids = payload.get("ids") or {}
        return {
            "tmdb_id": ids.get("tmdb"),
            "imdb_id": ids.get("imdb"),
            "tvdb_id": ids.get("tvdb"),
        }

    def _extract_season_episode_from_payload(self, payload):
        return payload.get("season_number"), payload.get("episode_number")

    def _extract_series_title(self, payload):
        return payload.get("series_title")

    def _get_played_at(self, payload):
        return payload.get("played_at")
