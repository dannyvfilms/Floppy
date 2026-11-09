# Original implementation by sboddy — FuzzyGrim/Yamtrack PR #1506
import logging
from enum import StrEnum

from app.models import MediaTypes
from app.providers import tmdb
from app.providers.services import ProviderAPIError

from .base import BaseWebhookProcessor, _is_transient_provider_error

logger = logging.getLogger(__name__)

PERCENT_COMPLETE_THRESHOLD = 80


class KodiEvent(StrEnum):
    """Kodi event."""

    PLAYBACK_START = "start"
    PLAYBACK_STOP = "stop"
    PLAYBACK_END = "end"


KODI_EVENT_MAP = {
    KodiEvent.PLAYBACK_START: "media.play",
    KodiEvent.PLAYBACK_STOP: "media.stop",
    KodiEvent.PLAYBACK_END: "media.scrobble",
}


class KodiWebhookProcessor(BaseWebhookProcessor):
    """Processor for Kodi webhook events via the HTTP Scrobbler add-on."""

    SOURCE_LABEL = "kodi"

    def process_payload(self, payload, user):
        """Return the process payload."""
        event_type = payload.get("event")
        if not self._is_supported_event(event_type):
            logger.info("Ignoring Kodi webhook event type: %s", event_type)
            return

        ids = self._extract_external_ids(payload)
        logger.info("Extracted IDs from Kodi payload: %s", ids)

        if not any(ids.values()):
            logger.warning("Ignoring Kodi webhook: no external ID found in payload.")
            return

        progress = payload.get("progress") or {}
        position_seconds = progress.get("time")
        duration_seconds = payload.get("duration")
        if not self._should_record(
            KODI_EVENT_MAP[event_type],
            played=self._is_played(payload),
            position_seconds=(
                position_seconds if isinstance(position_seconds, int | float) else None
            ),
            duration_seconds=(
                duration_seconds
                if isinstance(duration_seconds, int | float)
                else None
            ),
        ):
            return

        if (
            event_type == KodiEvent.PLAYBACK_STOP
            and payload.get("mediaType", "").lower() == "episode"
            and not self._is_played(payload)
        ):
            logger.info(
                "Kodi stop event below watched threshold for episode: "
                "percent=%s time=%s",
                progress.get("percent"),
                progress.get("time"),
            )

        self._process_media(payload, user, ids)

    def _is_supported_event(self, event_type):
        return event_type in {
            KodiEvent.PLAYBACK_START,
            KodiEvent.PLAYBACK_STOP,
            KodiEvent.PLAYBACK_END,
        }

    def _is_played(self, payload):
        if payload.get("event") == KodiEvent.PLAYBACK_END:
            return True
        if payload.get("event") == KodiEvent.PLAYBACK_STOP:
            percent = payload.get("progress", {}).get("percent", 0)
            if percent and percent >= PERCENT_COMPLETE_THRESHOLD:
                return True
        return False

    def _get_media_type(self, payload):
        return self.MEDIA_TYPE_MAPPING.get(payload.get("mediaType", "").capitalize())

    def _get_media_title(self, payload):
        if self._get_media_type(payload) == MediaTypes.TV.value:
            series_name = payload.get("tvShowTitle")
            season_number = payload.get("season")
            episode_number = payload.get("episode")
            return f"{series_name} S{season_number:02d}E{episode_number:02d}"

        if self._get_media_type(payload) == MediaTypes.MOVIE.value:
            movie_name = payload.get("title")
            year = payload.get("year")
            return f"{movie_name} ({year})" if movie_name and year else movie_name

        return None

    def _extract_season_episode_from_payload(self, payload):
        return payload.get("season"), payload.get("episode")

    def _extract_series_title(self, payload):
        return payload.get("tvShowTitle")

    def _extract_external_ids(self, payload):
        episode_ids = payload.get("uniqueIds") or {}
        series_ids = payload.get("tvShowUniqueIds") or {}
        if not isinstance(episode_ids, dict):
            episode_ids = {}
        if not isinstance(series_ids, dict):
            series_ids = {}

        fields = (
            ("tmdb", "tmdb_id"),
            ("tvdb", "tvdb_id"),
            ("imdb", "imdb_id"),
            ("tvmaze", "tvmaze_id"),
        )
        if self._get_media_type(payload) == MediaTypes.TV.value and series_ids:
            # Episode and series identifiers have separate namespaces. Pick
            # one show-level identifier rather than combining contradictory
            # episode and show GUIDs in the provider resolver.
            for provider, field in fields:
                if series_ids.get(provider):
                    return {
                        name: str(series_ids[provider]) if name == field else None
                        for _, name in fields
                    }

        return {
            name: episode_ids.get(provider) or series_ids.get(provider)
            for provider, name in fields
        }

    def _process_tv(self, payload, user, ids, season_number=None, episode_number=None):
        """Resolve and verify the series before any episode write."""
        show_ids = payload.get("tvShowUniqueIds")
        has_series_id = isinstance(show_ids, dict) and any(
            show_ids.get(provider) for provider in ("tmdb", "tvdb", "imdb", "tvmaze")
        )
        title = self._extract_series_title(payload)
        if has_series_id:
            # _extract_external_ids has already reduced conflicting identifiers
            # to a single series-level authority.
            media_id = ids.get("tmdb_id")
            if not media_id:
                media_id, _, _ = self._find_tv_media_id(
                    ids,
                    user=user,
                    episode_ids=False,
                    raise_transient=True,
                )
        else:
            # Legacy Kodi sends episode-level IDs with no show GUID. A unique
            # show title is safer than treating an episode's GUID as a series.
            if not title:
                logger.warning("Ignoring legacy Kodi episode without a series title")
                return None
            season = season_number if season_number is not None else payload.get("season")
            media_id = self._resolve_tv_by_title(title, season_number=season)

        if not media_id:
            logger.warning("Ignoring Kodi episode with unresolved show identity")
            return None

        try:
            metadata = tmdb.tv(media_id)
        except ProviderAPIError as exc:
            if _is_transient_provider_error(exc):
                raise
            logger.warning("Ignoring Kodi episode with invalid show ID %s", media_id)
            return None

        if title:
            expected = self._normalize_series_title(title)
            candidate_titles = {
                self._normalize_series_title(metadata.get(field))
                for field in ("title", "original_title", "localized_title")
            } - {None}
            if not expected or expected not in candidate_titles:
                logger.warning(
                    "Ignoring Kodi episode: series title contradicts TMDB show %s",
                    media_id,
                )
                return None

        # Never pass episode GUIDs (or unverified alternate series IDs) into
        # the tracking and fallback stages.
        verified_ids = {
            "tmdb_id": str(media_id),
            "tvdb_id": None,
            "imdb_id": None,
            "tvmaze_id": None,
        }
        return super()._process_tv(
            payload, user, verified_ids,
            season_number=season_number, episode_number=episode_number,
        )
