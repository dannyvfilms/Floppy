import html
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app import live_playback
from app.log_safety import mapping_keys, presence_map
from app.models import TV, Item, ItemProviderLink, MediaTypes, Movie, Sources
from app.providers import services
from app.services import metadata_resolution
from app.services.completion import select_preferred_activity_entry
from app.services.episode_scores import set_episode_score, tracked_episode_plays
from integrations.imports.helpers import find_item_across_buckets
from integrations.source_sync import (
    remove_collection_source_state,
    upsert_collection_source_state,
)

from .base import BaseWebhookProcessor

logger = logging.getLogger(__name__)

JELLYFIN_EVENT_MAP = {
    "Play": "media.play",
    "Pause": "media.pause",
    "Stop": "media.stop",
}
# ItemRemoved is the unofficial Webhooks plugin's name for ItemDeleted.
JELLYFIN_COLLECTION_EVENTS = {"ItemAdded", "ItemDeleted", "ItemRemoved"}
JELLYFIN_COLLECTION_SOURCE = "jellyfin"
JELLYFIN_RATING_EVENT = "UserDataSaved"
JELLYFIN_RATING_MAX = 10
# UserDataSaved fires for every progress save, playback end and our own
# watched-state push; only this reason is the user clicking the checkmark.
JELLYFIN_TOGGLE_PLAYED_REASON = "TogglePlayed"
JELLYFIN_MANUAL_MARK_EVENTS = {"MarkPlayed", "MarkUnplayed"}
# Set while UserDataSaved events arrive without SaveReason, i.e. from the
# template before #1250; the Integrations page tells the user to re-copy it.
JELLYFIN_TEMPLATE_OUTDATED_KEY = "jellyfin_template_outdated:{user_id}"
JELLYFIN_TEMPLATE_OUTDATED_TTL = 30 * 24 * 60 * 60


def jellyfin_template_outdated(user_id) -> bool:
    """Return whether this user's Jellyfin webhook uses the old template."""
    return bool(cache.get(JELLYFIN_TEMPLATE_OUTDATED_KEY.format(user_id=user_id)))


def _note_template_version(payload, user_id):
    key = JELLYFIN_TEMPLATE_OUTDATED_KEY.format(user_id=user_id)
    if "SaveReason" in payload:
        cache.delete(key)
    else:
        cache.set(key, True, JELLYFIN_TEMPLATE_OUTDATED_TTL)


def _decode_item_titles(payload):
    """Undo the HTML escaping the Jellyfin template's ``{{Name}}`` applies.

    Handlebars escapes the double-brace values (é arrives as ``&#233;``), and
    the JSON template cannot use raw ``{{{Name}}}`` because a quote in a title
    would break the JSON.
    """
    item = payload.get("Item")
    if not isinstance(item, dict):
        return payload
    decoded = {
        key: html.unescape(item[key])
        for key in ("Name", "SeriesName")
        if isinstance(item.get(key), str)
    }
    return {**payload, "Item": {**item, **decoded}}


def _ticks_to_seconds(ticks) -> int | None:
    """Convert Jellyfin 100-nanosecond ticks to whole seconds."""
    if ticks is None or isinstance(ticks, bool):
        return None
    if isinstance(ticks, float) and not ticks.is_integer():
        return None
    try:
        ticks = int(ticks)
    except (TypeError, ValueError):
        return None
    if ticks < 0:
        return None
    return ticks // 10_000_000


class JellyfinWebhookProcessor(BaseWebhookProcessor):
    """Processor for Jellyfin webhook events."""

    SOURCE_LABEL = "jellyfin"
    TV_IDS_ARE_EPISODE_LEVEL = True

    MEDIA_TYPE_MAPPING = {
        **BaseWebhookProcessor.MEDIA_TYPE_MAPPING,
        "Series": MediaTypes.TV.value,
    }

    def process_payload(self, payload, user):
        """Process the incoming Jellyfin webhook payload."""
        payload = _decode_item_titles(payload)
        logger.debug(
            "Processing Jellyfin webhook payload keys=%s item_keys=%s",
            mapping_keys(payload),
            mapping_keys(payload.get("Item")),
        )

        event_type = payload.get("Event")
        if not self._is_supported_event(event_type, user):
            logger.debug("Ignoring Jellyfin webhook event type: %s", event_type)
            return

        ids = self._extract_external_ids(payload)
        logger.info(
            "Extracted Jellyfin ID presence from payload: %s",
            presence_map(ids, ("tmdb_id", "imdb_id", "tvdb_id")),
        )

        if event_type in JELLYFIN_COLLECTION_EVENTS:
            self._process_collection_event(event_type, payload, user, ids)
            return

        if event_type == JELLYFIN_RATING_EVENT:
            _note_template_version(payload, user.id)
            self._process_rating(payload, user, ids)
            mark_event = self._manual_mark_event(payload, user)
            if mark_event is None:
                return
            payload = {**payload, "Event": mark_event}
            event_type = mark_event

        # Update live playback state (before media tracking)
        playback_media_type = self._get_live_playback_media_type(payload)
        playback_context = self._update_live_playback_state(
            payload,
            user,
            ids,
            playback_media_type,
        )

        position_seconds, duration_seconds = self._get_playback_progress(payload)
        if not self._should_record(
            "mark" if self._is_manual_mark(payload) else JELLYFIN_EVENT_MAP[event_type],
            played=self._is_played(payload),
            position_seconds=position_seconds,
            duration_seconds=duration_seconds,
        ):
            return

        if not any(ids.values()):
            logger.warning(
                "Ignoring Jellyfin webhook call because no ID was found.",
            )
            return

        processed_item = self._process_media(payload, user, ids)
        if event_type == "Stop" and processed_item and playback_context:
            live_playback.store_playback_progress(
                user.id,
                item=processed_item,
                **playback_context,
            )

    def _is_supported_event(self, event_type, user=None):
        if event_type in (
            "Play",
            "Pause",
            "Stop",
            *JELLYFIN_COLLECTION_EVENTS,
            JELLYFIN_RATING_EVENT,
        ):
            return True

        if user is None:
            return False

        if event_type == "MarkPlayed":
            return user.jellyfin_mark_played_enabled

        if event_type == "MarkUnplayed":
            return user.jellyfin_mark_unplayed_enabled

        return False

    def _is_played(self, payload):
        event_type = payload.get("Event")
        if event_type == "MarkPlayed":
            return True

        if event_type in ("MarkUnplayed", "Play", "Pause"):
            return False

        if event_type == "Stop":
            position_seconds, duration_seconds = self._get_playback_progress(payload)
            if position_seconds is not None and duration_seconds is not None:
                return position_seconds * 5 >= duration_seconds * 4

        item = payload.get("Item") or {}
        if not isinstance(item, dict):
            item = {}
        user_data = item.get("UserData") or {}
        if not isinstance(user_data, dict):
            user_data = {}
        played = user_data.get("Played")
        return played if isinstance(played, bool) else False

    def _playback_rating_key(self, payload):
        item = payload.get("Item") or {}
        return str(item.get("Id") or "").strip() or None

    def _is_unplayed(self, payload):
        return payload["Event"] == "MarkUnplayed"

    def _is_manual_mark(self, payload):
        return payload.get("Event") in JELLYFIN_MANUAL_MARK_EVENTS

    def _manual_mark_event(self, payload, user):
        """Map a UserDataSaved checkmark toggle to MarkPlayed/MarkUnplayed.

        Returns None for every other save reason (progress, playback end,
        ratings) and for templates that do not send SaveReason, so those
        keep leaving watch state alone.
        """
        if payload.get("SaveReason") != JELLYFIN_TOGGLE_PLAYED_REASON:
            return None
        item = payload.get("Item") or {}
        user_data = item.get("UserData") if isinstance(item, dict) else None
        played = user_data.get("Played") if isinstance(user_data, dict) else None
        if played is True and user.jellyfin_mark_played_enabled:
            return "MarkPlayed"
        if played is False and user.jellyfin_mark_unplayed_enabled:
            return "MarkUnplayed"
        return None

    def _get_played_at(self, payload):
        """Extract Jellyfin's completion timestamp when a play finished."""
        played_at = super()._get_played_at(payload)
        if played_at or not self._is_played(payload):
            return played_at

        item = payload.get("Item") or {}
        if not isinstance(item, dict):
            item = {}
        user_data = item.get("UserData") or {}
        if not isinstance(user_data, dict):
            user_data = {}
        position_seconds, duration_seconds = self._get_playback_progress(payload)
        if (
            payload.get("Event") == "Stop"
            and position_seconds is not None
            and duration_seconds is not None
            and user_data.get("Played") is not True
        ):
            return None

        raw_timestamp = user_data.get("LastPlayedDate") or payload.get(
            "LastPlayedDate",
        )
        if not raw_timestamp:
            return None

        played_at = parse_datetime(str(raw_timestamp))
        if played_at is None:
            return None
        if timezone.is_naive(played_at):
            played_at = timezone.make_aware(
                played_at,
                timezone.get_current_timezone(),
            )
        return timezone.localtime(played_at)

    def _get_playback_progress(self, payload):
        """Extract a Jellyfin position and positive duration in seconds."""
        item = payload.get("Item") or {}
        if not isinstance(item, dict):
            item = {}
        position_ticks = payload.get("PlaybackPositionTicks")
        if position_ticks is None:
            position_ticks = item.get("PlaybackPositionTicks")

        position_seconds = _ticks_to_seconds(position_ticks)
        duration_seconds = _ticks_to_seconds(item.get("RunTimeTicks"))
        if duration_seconds is not None and duration_seconds <= 0:
            duration_seconds = None
        return position_seconds, duration_seconds

    def _get_media_type(self, payload):
        return self.MEDIA_TYPE_MAPPING.get((payload.get("Item") or {}).get("Type"))

    def _get_media_title(self, payload):
        """Get media title from payload."""
        item = payload.get("Item") or {}
        media_type = self._get_media_type(payload)

        if media_type == MediaTypes.TV.value:
            series_name = item.get("SeriesName") or item.get("Name")
            if item.get("Type") == "Series":
                return series_name

            try:
                season_number = int(item.get("ParentIndexNumber"))
                episode_number = int(item.get("IndexNumber"))
            except (TypeError, ValueError):
                return series_name
            return f"{series_name} S{season_number:02d}E{episode_number:02d}"

        if media_type == MediaTypes.MOVIE.value:
            movie_name = item.get("Name")
            year = item.get("ProductionYear")

            return f"{movie_name} ({year})" if movie_name and year else movie_name

        return None

    def _extract_external_ids(self, payload):
        provider_ids = (payload.get("Item") or {}).get("ProviderIds") or {}
        return {
            "tmdb_id": provider_ids.get("Tmdb"),
            "imdb_id": provider_ids.get("Imdb"),
            "tvdb_id": provider_ids.get("Tvdb"),
        }

    def _process_collection_event(self, event_type, payload, user, ids):
        """Apply a Jellyfin library item event to source-scoped collection state."""
        item_type = (payload.get("Item") or {}).get("Type")
        if item_type not in ("Movie", "Episode"):
            logger.debug(
                "Ignoring Jellyfin collection event for unsupported item type: %s",
                item_type,
            )
            return

        if not any(ids.values()):
            logger.warning(
                "Ignoring Jellyfin collection event because no provider ID was found.",
            )
            return

        if item_type == "Episode":
            season_number, episode_number = self._extract_season_episode_from_payload(
                payload,
            )
            if season_number is None or episode_number is None:
                logger.warning(
                    "Ignoring Jellyfin collection event because season/episode "
                    "numbers are invalid.",
                )
                return

        item = self._resolve_collection_item(
            payload,
            ids,
            allow_create=event_type == "ItemAdded",
        )
        if item is None:
            logger.info(
                "Could not resolve Jellyfin collection item for event=%s",
                event_type,
            )
            return

        if event_type == "ItemAdded":
            upsert_collection_source_state(
                user=user,
                item=item,
                source=JELLYFIN_COLLECTION_SOURCE,
            )
            logger.info("Added %s to Jellyfin collection ownership", item.title)
        else:
            remove_collection_source_state(
                user=user,
                item=item,
                source=JELLYFIN_COLLECTION_SOURCE,
            )
            logger.info("Removed %s from Jellyfin collection ownership", item.title)

    def _resolve_collection_item(self, payload, ids, *, allow_create):
        """Resolve the canonical Item for a Jellyfin collection event."""
        item_type = (payload.get("Item") or {}).get("Type")
        if item_type == "Movie":
            return self._resolve_collection_movie(
                payload, ids, allow_create=allow_create
            )
        if item_type == "Episode":
            return self._resolve_collection_episode(
                payload,
                ids,
                allow_create=allow_create,
            )
        return None

    def _find_local_collection_item(self, ids, media_type):
        """Find an existing item through provider links without external calls."""
        provider_ids = (
            ("tmdb_id", Sources.TMDB.value),
            ("imdb_id", Sources.IMDB.value),
            ("tvdb_id", Sources.TVDB.value),
        )
        for key, provider in provider_ids:
            provider_id = ids.get(key)
            if not provider_id:
                continue

            linked_item = (
                ItemProviderLink.objects.filter(
                    provider=provider,
                    provider_media_type=media_type,
                    provider_media_id=str(provider_id),
                )
                .select_related("item")
                .order_by("item_id")
                .first()
            )
            if linked_item:
                return linked_item.item

            direct_item = (
                Item.objects.filter(
                    source=provider,
                    media_id=str(provider_id),
                    media_type=media_type,
                )
                .order_by("id")
                .first()
            )
            if direct_item:
                return direct_item

        return None

    def _resolve_collection_movie(self, payload, ids, *, allow_create):
        """Resolve or create a metadata-only movie item for Jellyfin ownership."""
        local_item = self._find_local_collection_item(ids, MediaTypes.MOVIE.value)
        if local_item or not allow_create:
            return local_item

        tmdb_id = ids.get("tmdb_id")
        if not tmdb_id:
            tmdb_id = self._find_tmdb_movie_id(ids)
        if not tmdb_id:
            logger.warning("Could not resolve Jellyfin movie to a TMDB ID")
            return None

        tmdb_id = str(tmdb_id)
        metadata = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            tmdb_id,
            Sources.TMDB.value,
        )
        item = find_item_across_buckets(
            media_id=tmdb_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
        )
        if item is None:
            item, _ = Item.objects.get_or_create(
                media_id=tmdb_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                library_media_type="",
                defaults=self._item_defaults(
                    metadata,
                    fallback_title=(payload.get("Item") or {}).get("Name"),
                ),
            )

        metadata_resolution.upsert_provider_links(
            item,
            self._metadata_with_payload_ids(metadata, ids),
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.MOVIE.value,
        )
        return item

    def _resolve_collection_episode(self, payload, ids, *, allow_create):
        """Resolve or create a metadata-only episode item for Jellyfin ownership."""
        local_item = self._find_local_collection_item(ids, MediaTypes.EPISODE.value)
        season_number, episode_number = self._extract_season_episode_from_payload(
            payload,
        )
        if local_item or not allow_create:
            if local_item and (
                local_item.season_number != season_number
                or local_item.episode_number != episode_number
            ):
                logger.warning(
                    "Ignoring Jellyfin episode provider-link match with mismatched "
                    "season/episode numbers.",
                )
                return None
            return local_item

        media_id, _, _ = self._find_tv_media_id(
            ids,
            series_title=self._extract_series_title(payload),
            allow_title_fallback=True,
            episode_ids=True,
        )
        if not media_id:
            logger.warning("Could not resolve Jellyfin episode to a TMDB show ID")
            return None
        media_id = str(media_id)

        show_item = self._find_local_collection_item(
            {"tmdb_id": media_id},
            MediaTypes.TV.value,
        )
        show_metadata = None
        if show_item is None:
            show_metadata = services.get_media_metadata(
                MediaTypes.TV.value,
                media_id,
                Sources.TMDB.value,
            )
            show_item, _ = Item.objects.get_or_create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                library_media_type="",
                defaults=self._item_defaults(
                    show_metadata,
                    fallback_title=(payload.get("Item") or {}).get("SeriesName"),
                ),
            )

        if show_metadata is not None:
            metadata_resolution.upsert_provider_links(
                show_item,
                show_metadata,
                provider=Sources.TMDB.value,
                provider_media_type=MediaTypes.TV.value,
            )

        episode_metadata = services.get_media_metadata(
            MediaTypes.EPISODE.value,
            media_id,
            Sources.TMDB.value,
            [season_number],
            episode_number=episode_number,
        )
        episode_bucket = (
            show_item.library_media_type
            if show_item.library_media_type
            and show_item.library_media_type != MediaTypes.TV.value
            else MediaTypes.EPISODE.value
        )
        episode_item = find_item_across_buckets(
            preferred_bucket=episode_bucket,
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=season_number,
            episode_number=episode_number,
        )
        if episode_item is None:
            episode_item, _ = Item.objects.get_or_create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                library_media_type=episode_bucket,
                season_number=season_number,
                episode_number=episode_number,
                defaults=self._episode_item_defaults(
                    episode_metadata,
                    show_item=show_item,
                    fallback_title=(payload.get("Item") or {}).get("Name"),
                ),
            )

        metadata_resolution.upsert_provider_links(
            episode_item,
            self._metadata_with_payload_ids(
                {**(episode_metadata or {}), "media_id": media_id},
                ids,
            ),
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.EPISODE.value,
            season_number=season_number,
        )
        return episode_item

    def _find_tmdb_movie_id(self, ids):
        """Resolve an IMDb or TVDB movie ID through TMDB."""
        for provider_id, provider_type in (
            (ids.get("imdb_id"), "imdb_id"),
            (ids.get("tvdb_id"), "tvdb_id"),
        ):
            if not provider_id:
                continue
            response = services.tmdb.find(provider_id, provider_type)
            movie_results = (response or {}).get("movie_results") or []
            if movie_results and movie_results[0].get("id"):
                return movie_results[0]["id"]
        return None

    def _item_defaults(self, metadata, *, fallback_title=None):
        """Build safe metadata-only Item defaults from provider metadata."""
        return {
            **Item.title_fields_from_metadata(metadata, fallback_title=fallback_title),
            "image": (metadata or {}).get("image") or settings.IMG_NONE,
            "synopsis": (metadata or {}).get("synopsis") or "",
            "release_datetime": (metadata or {}).get("release_datetime"),
            "genres": (metadata or {}).get("genres") or [],
            "metadata_fetched_at": timezone.now(),
        }

    def _episode_item_defaults(self, metadata, *, show_item, fallback_title=None):
        """Build metadata-only Item defaults for a Jellyfin episode."""
        return {
            **Item.title_fields_from_episode_metadata(
                metadata,
                fallback_title=fallback_title or show_item.title,
            ),
            "image": (metadata or {}).get("image")
            or show_item.image
            or settings.IMG_NONE,
            "metadata_fetched_at": timezone.now(),
        }

    def _metadata_with_payload_ids(self, metadata, ids):
        """Merge Jellyfin provider IDs into provider metadata before linking."""
        provider_external_ids = dict(
            (metadata or {}).get("provider_external_ids") or {}
        )
        provider_external_ids.update(
            {key: value for key, value in ids.items() if value},
        )
        return {
            **(metadata or {}),
            "provider_external_ids": provider_external_ids,
        }

    def _extract_season_episode_from_payload(self, payload):
        """Extract season and episode numbers from Jellyfin payload."""
        item = payload.get("Item", {}) or {}
        season_number = item.get("ParentIndexNumber")
        episode_number = item.get("IndexNumber")

        # Convert to int if they exist
        if isinstance(season_number, bool) or isinstance(episode_number, bool):
            return None, None
        try:
            season_number = int(season_number) if season_number is not None else None
            episode_number = int(episode_number) if episode_number is not None else None
        except (ValueError, TypeError):
            return None, None

        if (
            (season_number is not None and season_number < 0)
            or (episode_number is not None and episode_number < 0)
        ):
            return None, None

        return season_number, episode_number

    def _extract_series_title(self, payload):
        """Extract TV series title from Jellyfin payload."""
        if self._get_media_type(payload) == MediaTypes.TV.value:
            item = payload.get("Item") or {}
            return item.get("SeriesName") or item.get("Name")
        return None

    def _extract_user_rating(self, payload):
        """Extract a Jellyfin user rating from supported webhook payload shapes."""
        item = payload.get("Item") or {}
        user_data = item.get("UserData") or {}
        if isinstance(user_data, dict) and "Rating" in user_data:
            return user_data["Rating"], "Item.UserData.Rating"

        payload_user_data = payload.get("UserData") or {}
        if isinstance(payload_user_data, dict) and "Rating" in payload_user_data:
            return payload_user_data["Rating"], "UserData.Rating"

        for container, key in (
            (item, "UserRating"),
            (item, "Rating"),
            (payload, "UserRating"),
            (payload, "Rating"),
        ):
            if isinstance(container, dict) and key in container:
                return container[key], key

        return None, None

    def _normalize_user_rating(self, rating):
        """Return a finite Jellyfin rating on Floppy's internal 0-10 scale."""
        if rating is None or isinstance(rating, bool):
            return None
        try:
            rating = Decimal(str(rating))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not rating.is_finite() or rating < 0 or rating > JELLYFIN_RATING_MAX:
            return None
        try:
            return rating.quantize(Decimal("0.1"))
        except InvalidOperation:
            return None

    def _process_rating(self, payload, user, ids):
        """Apply a Jellyfin UserDataSaved rating; watch state is handled apart."""
        raw_rating, rating_source = self._extract_user_rating(payload)
        rating = self._normalize_user_rating(raw_rating)
        if rating is None:
            logger.debug(
                "Ignoring Jellyfin UserDataSaved event without a valid rating "
                "(source=%s)",
                rating_source,
            )
            return None

        media_type = self._get_media_type(payload)
        if media_type == MediaTypes.MOVIE.value:
            item = self._resolve_collection_movie(
                payload,
                ids,
                allow_create=True,
            )
            model = Movie
        elif media_type == MediaTypes.TV.value:
            item = self._resolve_rating_tv_item(payload, ids)
            model = TV
        else:
            logger.debug(
                "Ignoring Jellyfin rating for unsupported media type: %s",
                (payload.get("Item") or {}).get("Type"),
            )
            return None

        if item is None:
            logger.warning("Could not resolve Jellyfin rating target")
            return None

        if (payload.get("Item") or {}).get("Type") == "Episode":
            return self._apply_episode_rating(payload, user, item, rating)

        instances = model.objects.filter(item=item, user=user)
        instance = select_preferred_activity_entry(instances)
        if instance is None:
            model.objects.create(
                item=item,
                user=user,
                status=None,
                score=rating,
            )
            logger.info(
                "Created statusless %s rating from Jellyfin: %s=%s",
                model.__name__,
                item.title,
                rating,
            )
        elif instance.score != rating:
            instance.score = rating
            instance.save(update_fields=["score"])
            logger.info(
                "Updated %s rating from Jellyfin: %s=%s",
                model.__name__,
                item.title,
                rating,
            )
        return rating

    def _apply_episode_rating(self, payload, user, show_item, rating):
        """Rate the episode's plays; an episode rating never rates the show."""
        season_number, episode_number = self._extract_season_episode_from_payload(
            payload,
        )
        if season_number is None or episode_number is None:
            logger.warning(
                "Ignoring Jellyfin episode rating without season/episode numbers",
            )
            return None

        episodes = tracked_episode_plays(
            user,
            show_item.media_id,
            show_item.source,
            season_number,
            episode_number,
        )
        updated = set_episode_score(episodes.exclude(score=rating), rating, user.id)
        if updated:
            logger.info(
                "Updated episode rating from Jellyfin: %s S%sE%s=%s",
                show_item.title,
                season_number,
                episode_number,
                rating,
            )
        elif not episodes.exists():
            # Episode plays are watch records; a rating alone must not create one.
            logger.info(
                "Ignoring Jellyfin rating for untracked episode %s S%sE%s",
                show_item.title,
                season_number,
                episode_number,
            )
            return None
        return rating

    def _resolve_rating_tv_item(self, payload, ids):
        """Resolve a TV item for a Jellyfin rating without creating watch rows."""
        local_item = self._find_local_collection_item(ids, MediaTypes.TV.value)
        if local_item:
            return local_item

        media_id, _, _ = self._find_tv_media_id(
            ids,
            series_title=self._extract_series_title(payload),
            allow_title_fallback=True,
            episode_ids=(payload.get("Item") or {}).get("Type") == "Episode",
        )
        if not media_id:
            logger.warning("Could not resolve Jellyfin TV rating to a TMDB ID")
            return None

        media_id = str(media_id)
        local_item = self._find_local_collection_item(
            {"tmdb_id": media_id},
            MediaTypes.TV.value,
        )
        if local_item:
            return local_item

        metadata = services.get_media_metadata(
            MediaTypes.TV.value,
            media_id,
            Sources.TMDB.value,
        )
        item = find_item_across_buckets(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
        )
        if item is None:
            item, _ = Item.objects.get_or_create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                library_media_type="",
                defaults=self._item_defaults(
                    metadata,
                    fallback_title=self._extract_series_title(payload),
                ),
            )

        metadata_resolution.upsert_provider_links(
            item,
            self._metadata_with_payload_ids(metadata, ids),
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
        )
        return item

    # -- Live playback --------------------------------------------------

    def _get_live_playback_media_type(self, payload):
        """Map Jellyfin item type to a playback card media type."""
        item_type = (payload.get("Item", {}).get("Type") or "").strip()
        if item_type == "Episode":
            return MediaTypes.EPISODE.value
        if item_type == "Movie":
            return MediaTypes.MOVIE.value
        return None

    def _update_live_playback_state(
        self,
        payload,
        user,
        ids,
        playback_media_type,
    ):
        """Update cache-backed live playback state for home-page UI."""
        event_type = JELLYFIN_EVENT_MAP.get(payload.get("Event"))
        if not event_type:
            return None

        if playback_media_type not in (
            MediaTypes.MOVIE.value,
            MediaTypes.EPISODE.value,
        ):
            return None

        item = payload.get("Item", {})
        media_id = None
        season_number = None
        episode_number = None

        if playback_media_type == MediaTypes.MOVIE.value:
            media_id = ids.get("tmdb_id")
        else:
            season_number, episode_number = self._extract_season_episode_from_payload(
                payload
            )
            # Prefer TVDB/IMDB resolution — they reliably return the
            # show-level TMDB ID via the TMDB find API.
            if ids.get("tvdb_id") or ids.get("imdb_id"):
                alt_ids = dict(ids)
                alt_ids["tmdb_id"] = None
                resolved_id, _, _ = super()._find_tv_media_id(
                    alt_ids,
                    episode_ids=True,
                )
                if resolved_id:
                    media_id = str(resolved_id)

            # Fallback: title search then raw tmdb_id
            if media_id is None:
                series_title = self._extract_series_title(payload)
                resolved_id, _, _ = self._find_tv_media_id(
                    ids,
                    series_title=series_title,
                    allow_title_fallback=True,
                    episode_ids=True,
                )
                if resolved_id:
                    media_id = str(resolved_id)

            if media_id is None:
                media_id = ids.get("tmdb_id")

        # Duration / offset from Jellyfin ticks (100 ns units)
        offset_seconds, duration_seconds = self._get_playback_progress(payload)
        provider_completed = self._is_played(payload)

        live_playback.apply_playback_event(
            user_id=user.id,
            event_type=event_type,
            playback_media_type=playback_media_type,
            media_id=media_id,
            source=Sources.TMDB.value,
            rating_key=str(item.get("Id") or "").strip() or None,
            title=item.get("Name"),
            series_title=item.get("SeriesName"),
            episode_title=(
                item.get("Name")
                if playback_media_type == MediaTypes.EPISODE.value
                else None
            ),
            season_number=season_number,
            episode_number=episode_number,
            view_offset_seconds=offset_seconds,
            duration_seconds=duration_seconds,
            store_progress=event_type != "media.stop",
            provider_completed=provider_completed,
            event_ts=getattr(self, "_event_ts", None),
        )
        return {
            "event_type": event_type,
            "playback_media_type": playback_media_type,
            "view_offset_seconds": offset_seconds,
            "duration_seconds": duration_seconds,
            "provider_completed": provider_completed,
        }
