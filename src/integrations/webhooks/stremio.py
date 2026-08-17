"""Stremio scrobbler addon processor.

Stremio has no playback webhook, so Floppy serves a minimal addon whose
``subtitles`` resource is requested when playback starts. The payload built
by the addon views is ``{"id": "tt123" | "tt123:season:episode", "type":
"movie" | "series"}``. That is a start-only signal: media is marked
in-progress here, and the recurring Stremio library sync flips items to
completed from real library state.
"""

import logging

import app.providers.tmdb
from app import live_playback
from app.models import MediaTypes, Sources

from .base import BaseWebhookProcessor

logger = logging.getLogger(__name__)

VIDEO_ID_PARTS = 3


class StremioWebhookProcessor(BaseWebhookProcessor):
    """Processor for Stremio addon playback-start events."""

    MEDIA_TYPE_MAPPING = {
        "series": MediaTypes.TV.value,
        "movie": MediaTypes.MOVIE.value,
    }

    def process_payload(self, payload, user):
        """Process a playback-start event from the Stremio addon."""
        ids = self._extract_external_ids(payload)
        if not ids["imdb_id"]:
            logger.warning(
                "Ignoring Stremio scrobble with unsupported id: %s",
                payload.get("id"),
            )
            return

        self._update_live_playback_state(payload, user, ids)
        self._process_media(payload, user, ids)

    def _update_live_playback_state(self, payload, user, ids):
        """Update the Now Playing card from a playback-start signal.

        Stremio only ever sends a start ping (no pause/stop/progress), so
        this always writes a ``media.play`` state with no offset/duration;
        the card's own stale-after-4h expiry is what clears it.
        """
        imdb_id = ids["imdb_id"]
        media_type = payload.get("type")

        if media_type == "movie":
            self._update_live_playback_movie(user, imdb_id)
        elif media_type == "series":
            self._update_live_playback_episode(payload, user, imdb_id)

    def _update_live_playback_movie(self, user, imdb_id):
        find_response = app.providers.tmdb.find(imdb_id, "imdb_id")
        movie_results = find_response.get("movie_results") or []
        if not movie_results:
            return
        media_id = movie_results[0].get("id")
        if not media_id:
            return

        movie_metadata = app.providers.tmdb.movie(media_id)
        live_playback.apply_playback_event(
            user_id=user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id=str(media_id),
            source=Sources.TMDB.value,
            title=movie_metadata.get("title"),
        )

    def _update_live_playback_episode(self, payload, user, imdb_id):
        season_number, episode_number = self._extract_season_episode_from_payload(
            payload,
        )
        if season_number is None or episode_number is None:
            return

        find_response = app.providers.tmdb.find(imdb_id, "imdb_id")
        episode_results = find_response.get("tv_episode_results") or []
        if episode_results:
            show_id = episode_results[0].get("show_id")
        else:
            tv_results = find_response.get("tv_results") or []
            show_id = tv_results[0].get("id") if tv_results else None
        if not show_id:
            return

        tv_metadata = app.providers.tmdb.tv(show_id)
        live_playback.apply_playback_event(
            user_id=user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.EPISODE.value,
            media_id=str(show_id),
            source=Sources.TMDB.value,
            series_title=tv_metadata.get("title"),
            season_number=season_number,
            episode_number=episode_number,
        )

    def _is_supported_event(self, event_type):
        return True

    def _is_played(self, payload):
        # A normal Stremio subtitles request only proves playback started.
        # The delayed verifier sets this private flag only after correlating
        # the exact video_id, >=90% timeWatched, Stremio completion flags,
        # and lastWatched against the observed playback session.
        return payload.get("_floppy_verified_completion") is True

    def _get_media_type(self, payload):
        return self.MEDIA_TYPE_MAPPING.get(payload.get("type"))

    def _get_media_title(self, payload):
        return payload.get("id")

    def _extract_external_ids(self, payload):
        media_id = payload.get("id", "")
        imdb_id = media_id.split(":")[0] if media_id.startswith("tt") else None
        return {
            "tmdb_id": None,
            "imdb_id": imdb_id,
            "tvdb_id": None,
        }

    def _extract_season_episode_from_payload(self, payload):
        """Extract season and episode from a ``tt123:s:e`` video id."""
        parts = payload.get("id", "").split(":")
        if len(parts) != VIDEO_ID_PARTS:
            return None, None
        try:
            return int(parts[1]), int(parts[2])
        except ValueError:
            return None, None

    def _extract_series_title(self, payload):
        return None
