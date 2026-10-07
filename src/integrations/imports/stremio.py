"""Stremio importer for library watch state.

Stremio exposes a small JSON-RPC-style API at ``https://api.strem.io/api``:

- ``POST /api/login``        ``{email, password}`` -> ``{authKey, user}``
- ``POST /api/getUser``      ``{authKey}`` -> user profile
- ``POST /api/datastoreGet`` ``{authKey, collection: "libraryItem", all: true}``
  -> every library item with its watch state.

Library items are keyed by IMDB id (``tt…``). Watched episodes of a series
are stored as a bitfield serialized as ``{anchorVideoId}:{anchorLength}:{base64
(zlib-deflated bytes)}``. Per stremio-core's ``WatchedField``, the anchor is the
**last watched** video and ``anchorLength`` is that video's index plus one, so
bit ``anchorLength - 1`` belongs to the anchor. Bit *i* (LSB-first per byte)
indexes the show's ordered video list from Cinemeta as it stood when the
bitfield was written; locating the anchor in the current list realigns it.
"""

import base64
import logging
import zlib
from collections import defaultdict

import requests
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from simple_history.utils import bulk_update_with_history

import app
import app.providers.mal
import app.providers.trakt
from app.models import MediaTypes, Sources, Status
from app.models.tv import PRODUCTION_STATUS_ENDED, classify_production_status
from app.providers import services
from app.services import grouped_anime
from integrations import (
    anime_mapping,
    connection_health,
    import_progress,
    stremio_events,
)
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.models import StremioAccount

logger = logging.getLogger(__name__)

STREMIO_API_BASE_URL = "https://api.strem.io/api"
STREMIO_INVALID_SESSION_CODE = 1
CINEMETA_VIDEO_IDS_URL = (
    "https://v3-cinemeta.strem.io/catalog/series/video-ids/imdbIds={ids}"
)
CINEMETA_BATCH_SIZE = 100
BITFIELD_MIN_COMPONENTS = 3

KITSU_API_BASE_URL = "https://kitsu.app/api/edge"
ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"

# Stremio library ids are namespaced as "<provider>:<id>", except plain IMDb
# ids which have no namespace prefix (e.g. "tt1234567"). These are the
# provider namespaces the Stremio addon ecosystem is known to emit that this
# importer can resolve into TMDB (movies/TV) or MAL (anime) media.
ANIME_ID_NAMESPACES = frozenset({"kitsu", "mal", "anilist"})
MOVIE_TV_ID_NAMESPACES = frozenset({"tmdb", "tvdb", "trakt"})


def classify_stremio_id(entry_id):
    """Split a Stremio library id into (namespace, raw_id), or None if unsupported."""
    namespace, sep, raw = entry_id.partition(":")
    if not sep:
        return ("imdb", entry_id) if entry_id.startswith("tt") else None
    if namespace in MOVIE_TV_ID_NAMESPACES or namespace in ANIME_ID_NAMESPACES:
        return (namespace, raw)
    return None


# History label for status changes this sync makes (#1133).
STREMIO_IMPORT_REASON = "Stremio import"

# Forward-only status ranking used to decide whether the recurring sync may
# advance an already-tracked Movie/TV/Season's status (see #580: the sync
# must pick up completion the webhook deferred to it, but must never
# override a status it doesn't own, like a user-set Dropped/Paused).
_STATUS_RANK = {
    Status.PLANNING.value: 0,
    Status.IN_PROGRESS.value: 1,
    Status.COMPLETED.value: 2,
}



def _is_invalid_session(error):
    """Return whether a Stremio API error means the auth key is no longer valid."""
    if isinstance(error, dict):
        if error.get("code") == STREMIO_INVALID_SESSION_CODE:
            return True
        error = error.get("message", "")
    return "session does not exist" in str(error).lower()

def _api_call(method, auth_key=None, **params):
    """Call a Stremio API method and unwrap the result envelope."""
    body = dict(params)
    if auth_key is not None:
        body["authKey"] = auth_key

    response = services.api_request(
        "Stremio",
        "POST",
        f"{STREMIO_API_BASE_URL}/{method}",
        params=body,
    )

    error = response.get("error")
    if error:
        if isinstance(error, dict):
            message = error.get("message", str(error))
        else:
            message = str(error)
        msg = f"Stremio API error: {message}"
        # Stremio answers an expired or revoked auth key with code 1,
        # "Session does not exist". Any other envelope error is not about
        # the credentials.
        if _is_invalid_session(error):
            raise helpers.ConnectionAuthError(msg)
        raise MediaImportError(msg)

    result = response.get("result")
    if result is None:
        msg = f"Stremio API returned no result for {method}"
        raise MediaImportError(msg)

    return result


def login(email, password):
    """Log in to Stremio and return the authKey."""
    result = _api_call("login", email=email, password=password)
    auth_key = result.get("authKey")
    if not auth_key:
        msg = "Stremio login did not return an auth key."
        raise MediaImportError(msg)
    return auth_key


def get_user(auth_key):
    """Return the Stremio user profile; validates a pasted authKey."""
    return _api_call("getUser", auth_key=auth_key)


def get_library_items(auth_key):
    """Return every library item with watch state."""
    return _api_call(
        "datastoreGet",
        auth_key=auth_key,
        collection="libraryItem",
        all=True,
    )


def decode_watched_bitfield(watched_str, video_ids):
    """Decode a serialized watched bitfield into a set of watched video ids.

    The serialized form is ``{anchorVideoId}:{anchorLength}:{base64(zlib
    bytes)}``; the anchor video id may itself contain ``:`` so the last two
    components are popped from the right.

    Per stremio-core's ``WatchedField``, the anchor is the **last watched**
    video (``bitfield.last_index_of(true)``) and ``anchorLength`` is that
    video's index plus one — so bit ``anchorLength - 1`` belongs to the anchor,
    not the end of the list. Locating the anchor in the current list therefore
    fixes the whole index mapping: bit *i* is video *i + offset*, where
    ``offset = video_ids.index(anchor) - (anchorLength - 1)``. This is the same
    shift ``WatchedBitField::construct_with_videos`` applies, so a decode here
    agrees with what the Stremio client itself would show.

    Reading bit *i* as video *i* is only correct while the list is unchanged.
    Cinemeta does re-order and extend it — a new special, a re-ordered season —
    and then every index after the change is shifted. That is not rare: of the
    135 series with a bitfield in the live library, 29 have the anchor at a
    different index than recorded (a recoverable offset) and 1 no longer lists
    it at all. Reading them unaligned files watched state against the wrong
    episodes — 129 of the 162 mismatched ids were season 0, landing on specials
    the user never watched.

    Returns ``(watched_ids, anchored)``. ``anchored`` is False only when the
    anchor is absent from the list. stremio-core blanks the whole bitfield in
    that case; this returns the unshifted bits with ``anchored=False`` so the
    caller can fall back to the last-watched video rather than discarding the
    user's history. Bits whose aligned position falls outside the list are
    dropped.
    """
    components = watched_str.split(":")
    if len(components) < BITFIELD_MIN_COMPONENTS:
        msg = f"Invalid watched bitfield: {watched_str[:50]}"
        raise ValueError(msg)

    serialized = components.pop()
    anchor_length = int(components.pop())
    anchor_video_id = ":".join(components)

    buf = zlib.decompress(base64.b64decode(serialized))

    if anchor_video_id in video_ids:
        offset = video_ids.index(anchor_video_id) - (anchor_length - 1)
        anchored = True
    else:
        offset = 0
        anchored = False

    watched = set()
    for bit in range(min(anchor_length, len(buf) * 8)):
        if not buf[bit >> 3] & (1 << (bit & 7)):
            continue
        index = bit + offset
        if 0 <= index < len(video_ids):
            watched.add(video_ids[index])

    return watched, anchored


def parse_video_id(video_id):
    """Parse ``tt123:season:episode`` into (season, episode) or None."""
    parsed = stremio_events.parse_episode_id(video_id)
    if parsed is None:
        return None
    return parsed[1], parsed[2]


def importer(identifier, user, mode):
    """Import movies and TV shows from a connected Stremio account."""
    return StremioImporter(user, mode).import_data()


class StremioImporter:
    """Import library watch state from Stremio."""

    def __init__(self, user, mode):
        """Initialize the importer and validate account access."""
        self.user = user
        self.mode = mode
        self.warnings = []

        try:
            self.account = user.stremio_account
        except StremioAccount.DoesNotExist as error:
            msg = "Connect Stremio before importing"
            raise MediaImportError(msg) from error

        if not self.account.auth_key:
            msg = "Connect Stremio before importing"
            raise MediaImportError(msg)

        try:
            self.auth_key = helpers.decrypt_or_raise(self.account.auth_key)
        except MediaImportError as decrypt_error:
            connection_health.record_failure(self.account, decrypt_error, auth=True)
            raise

        self.existing_media = helpers.get_existing_media(user)
        # Shows/movies the user deleted stay deleted, even though Stremio's
        # library (often fed by Trakt) still lists them (#1133).
        self.deleted_media = helpers.get_deleted_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        self.bulk_season_by_item_id = {}

        logger.info(
            "Initialized Stremio importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all watchable library items from Stremio."""
        try:
            items = get_library_items(self.auth_key)
        except MediaImportError as error:
            connection_health.record_failure(
                self.account,
                error,
                auth=isinstance(error, helpers.ConnectionAuthError),
            )
            raise

        movies, series, anime = self._partition_items(items)

        # Cinemeta only indexes IMDb ids, so only imdb-namespaced series can
        # get an ordered per-episode video list from it. Series resolved via
        # tmdb:/tvdb:/trakt: fall back to last-watched-episode-only import
        # (see _watched_videos), same as when Cinemeta itself is unreachable.
        cinemeta_videos = self._fetch_cinemeta_videos(
            [
                entry["_id"]
                for entry in series
                if entry["_id"].startswith("tt")
            ],
        )

        grouped_anime_snapshot = grouped_anime.UNSET
        if self.user.anime_enabled and series:
            try:
                grouped_anime_snapshot = anime_mapping.load_mapping_snapshot()
            except (OSError, TypeError, ValueError, services.ProviderAPIError) as error:
                # A mapping outage must leave the item in its existing TV path;
                # it must never make a normal Stremio import fail or guess from
                # titles.  The next import retries the pinned snapshot.
                grouped_anime_snapshot = None
                self.warnings.append(
                    "Anime mapping unavailable; series were kept in TV",
                )
                logger.warning(
                    "stremio_anime_mapping_unavailable user_id=%s error=%s",
                    self.user.id,
                    error,
                )

        # One resolver for the whole run: rows are buffered and flushed at the
        # end, so a database lookup alone cannot see a home opened earlier in
        # this same import.
        anime_router = grouped_anime.AnimeRouteResolver(
            self.user,
            snapshot=grouped_anime_snapshot,
        )

        total = len(movies) + len(series) + len(anime)
        current = 0

        for entry in movies:
            current += 1
            import_progress.report(current, total, "Stremio")
            try:
                self._process_movie(entry)
            except Exception as error:
                msg = f"Error processing entry: {entry}"
                raise MediaImportUnexpectedError(msg) from error

        for entry in series:
            current += 1
            import_progress.report(current, total, "Stremio")
            try:
                self._process_series(
                    entry,
                    cinemeta_videos.get(entry["_id"]),
                    anime_router,
                )
            except Exception as error:
                msg = f"Error processing entry: {entry}"
                raise MediaImportUnexpectedError(msg) from error

        for entry in anime:
            current += 1
            import_progress.report(current, total, "Stremio")
            try:
                self._process_anime(entry, anime_router)
            except Exception as error:
                msg = f"Error processing entry: {entry}"
                raise MediaImportUnexpectedError(msg) from error

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        self.account.last_sync_at = timezone.now()
        connection_health.record_success(self.account, extra_fields=["last_sync_at"])

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        return imported_counts, "\n".join(dict.fromkeys(self.warnings))


    def _partition_items(self, items):
        """Split library items into importable movies, series, and anime."""
        movies = []
        series = []
        anime = []

        for entry in items:
            entry_type = entry.get("type")
            if entry_type not in ("movie", "series"):
                continue

            entry_id = entry.get("_id", "")
            has_signal = self._has_watch_signal(entry)

            if not has_signal and (entry.get("removed") or entry.get("temp")):
                continue

            classified = classify_stremio_id(entry_id)
            if classified is None:
                name = entry.get("name", entry_id)
                self.warnings.append(
                    f"{name}: unsupported Stremio id '{entry_id}' - skipped",
                )
                continue

            namespace, _raw_id = classified
            if namespace in ANIME_ID_NAMESPACES:
                anime.append(entry)
            elif entry_type == "movie":
                movies.append(entry)
            else:
                series.append(entry)

        return movies, series, anime

    def _has_watch_signal(self, entry):
        """Return True when the item carries any watch state."""
        state = entry.get("state") or {}
        return bool(
            state.get("timesWatched")
            or state.get("flaggedWatched")
            or state.get("watched")
            or state.get("timeOffset"),
        )

    def _fetch_cinemeta_videos(self, imdb_ids):
        """Fetch ordered video lists for series from Cinemeta, batched."""
        videos_by_id = {}
        unique_ids = list(dict.fromkeys(imdb_ids))

        for start in range(0, len(unique_ids), CINEMETA_BATCH_SIZE):
            batch = unique_ids[start : start + CINEMETA_BATCH_SIZE]
            url = CINEMETA_VIDEO_IDS_URL.format(ids=",".join(batch))
            try:
                response = services.api_request("Stremio", "GET", url)
            except services.ProviderAPIError as error:
                logger.warning("Cinemeta video-ids request failed: %s", error)
                continue

            malformed_meta_count = 0
            for meta in response.get("metasDetailed") or []:
                if not isinstance(meta, dict):
                    malformed_meta_count += 1
                    continue

                meta_id = meta.get("id")
                if not isinstance(meta_id, str) or not meta_id:
                    malformed_meta_count += 1
                    continue

                raw_videos = meta.get("videos")
                if raw_videos is None:
                    raw_videos = []
                elif not isinstance(raw_videos, list):
                    self.warnings.append(
                        f"{meta_id}: Cinemeta returned a malformed video list; skipped.",
                    )
                    videos_by_id[meta_id] = []
                    continue

                video_ids = []
                malformed_video_count = 0
                for video in raw_videos:
                    video_id = video if isinstance(video, str) else None
                    if isinstance(video, dict):
                        video_id = video.get("id")

                    if isinstance(video_id, str) and video_id:
                        video_ids.append(video_id)
                    else:
                        malformed_video_count += 1

                videos_by_id[meta_id] = video_ids
                if malformed_video_count:
                    self.warnings.append(
                        f"{meta_id}: Cinemeta skipped "
                        f"{malformed_video_count} malformed video entries.",
                    )

            if malformed_meta_count:
                self.warnings.append(
                    f"Cinemeta skipped {malformed_meta_count} malformed series entries.",
                )

        return videos_by_id

    def _movie_status(self, state):
        """Compute the Stremio-derived status for a movie entry."""
        watched = bool(state.get("timesWatched") or state.get("flaggedWatched"))
        if watched:
            status = Status.COMPLETED.value
        elif state.get("timeOffset"):
            status = Status.IN_PROGRESS.value
        else:
            status = Status.PLANNING.value
        return status, watched

    @staticmethod
    def _show_has_definitely_ended(tv_instance):
        """Return whether the provider positively reports the show as finished.

        False when the provider is unreachable, carries no status, or reports
        one we don't recognize, so a recurring sync never finalizes a show on
        missing or unfamiliar information.
        """
        production_status = tv_instance.resolve_production_status()
        if production_status is None:
            return False
        return (
            classify_production_status(production_status)
            == PRODUCTION_STATUS_ENDED
        )

    def _advance_status_in_place(self, instance, new_status, **field_updates):
        """Advance an already-tracked instance's status forward-only.

        Only updates when the existing status is one the recurring sync
        legitimately owns (Planning/In progress - states the webhook or a
        prior sync put it in) and the new status represents forward
        progress. A user-finalized status (Completed/Dropped/Paused) is
        left untouched, so a background sync can never override it.
        """
        old_rank = _STATUS_RANK.get(instance.status)
        new_rank = _STATUS_RANK.get(new_status)
        if old_rank is None or new_rank is None or new_rank <= old_rank:
            return False

        if (
            isinstance(instance, app.models.TV)
            and new_status == Status.COMPLETED.value
            and not self._show_has_definitely_ended(instance)
        ):
            # A background sync only ever sees the episodes Cinemeta happens to
            # list, so "everything watched" is not evidence a show is over.
            # Completing it here overwrites a status the user set (#375), so
            # require positive evidence from the provider instead - and require
            # it whether the row is Planning or In progress, so the two can't
            # disagree. Watching still moves a Planning show to In progress.
            new_status = Status.IN_PROGRESS.value
            if _STATUS_RANK[new_status] <= old_rank:
                return False

        instance.status = new_status
        for field, value in field_updates.items():
            setattr(instance, field, value)
        instance._change_reason = STREMIO_IMPORT_REASON
        instance.save()
        return True

    def _process_movie(self, entry):
        """Process a single Stremio movie entry."""
        entry_id = entry["_id"]
        name = entry.get("name", entry_id)
        state = entry.get("state") or {}

        tmdb_id = self._resolve_tmdb_id(entry_id, MediaTypes.MOVIE.value)
        if tmdb_id is None:
            self.warnings.append(
                f"{name}: couldn't find a match in {Sources.TMDB.label}",
            )
            return

        media_id = str(tmdb_id)
        status, watched = self._movie_status(state)
        last_watched = self._parse_date(state.get("lastWatched"))

        existing_movie = self.existing_media[MediaTypes.MOVIE.value][
            Sources.TMDB.value
        ].get(media_id)
        if existing_movie is not None and self.mode == "new":
            self._advance_status_in_place(
                existing_movie,
                status,
                progress=1 if status == Status.COMPLETED.value else existing_movie.progress,
                start_date=last_watched
                if status != Status.PLANNING.value
                else existing_movie.start_date,
                end_date=last_watched if watched else existing_movie.end_date,
            )
            return

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.MOVIE.value,
            Sources.TMDB.value,
            media_id,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        try:
            movie_metadata = app.providers.tmdb.movie(tmdb_id)
        except services.ProviderAPIError as error:
            if error.status_code == requests.codes.not_found:
                self.warnings.append(
                    f"{name}: not found in {Sources.TMDB.label} with ID {tmdb_id}.",
                )
                return
            raise

        movie_item, _ = app.models.Item.objects.get_or_create(
            media_id=tmdb_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={
                **app.models.Item.title_fields_from_metadata(movie_metadata),
                "image": movie_metadata["image"],
            },
        )

        movie_instance = app.models.Movie(
            item=movie_item,
            user=self.user,
            status=status,
            progress=1 if status == Status.COMPLETED.value else 0,
            start_date=last_watched if status != Status.PLANNING.value else None,
            end_date=last_watched if watched else None,
        )
        movie_instance._history_date = self._get_history_date(entry)
        self.bulk_media[MediaTypes.MOVIE.value].append(movie_instance)

    def _process_series(self, entry, video_ids, anime_router=None):
        """Process a single Stremio series entry."""
        entry_id = entry["_id"]
        name = entry.get("name", entry_id)
        state = entry.get("state") or {}

        tmdb_id = self._resolve_tmdb_id(entry_id, MediaTypes.TV.value)
        if tmdb_id is None:
            self.warnings.append(
                f"{name}: couldn't find a match in {Sources.TMDB.label}",
            )
            return

        media_id = str(tmdb_id)

        watched_videos = self._watched_videos(entry, video_ids, name)
        watched_episodes = sorted(
            {
                parsed
                for video_id in watched_videos
                if (parsed := parse_video_id(video_id))
            },
        )

        if watched_episodes:
            all_watched = video_ids and all(
                video_id in watched_videos
                for video_id in video_ids
                if (parsed := parse_video_id(video_id)) and parsed[0] > 0
            )
            tv_status = (
                Status.COMPLETED.value if all_watched else Status.IN_PROGRESS.value
            )
        elif state.get("timeOffset"):
            # An episode was started but nothing is marked watched yet.
            tv_status = Status.IN_PROGRESS.value
        else:
            tv_status = Status.PLANNING.value

        existing_tv = self.existing_media[MediaTypes.TV.value][Sources.TMDB.value].get(
            media_id,
        )
        tv_instance = None
        if existing_tv is not None and self.mode == "new":
            self._advance_status_in_place(existing_tv, tv_status)
            if not watched_episodes:
                return
            tv_instance = existing_tv
        elif not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.TV.value,
            Sources.TMDB.value,
            media_id,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        season_numbers = sorted({season for season, _ in watched_episodes})
        try:
            metadata = app.providers.tmdb.tv_with_seasons(tmdb_id, season_numbers)
        except services.ProviderAPIError as error:
            if error.status_code == requests.codes.not_found:
                self.warnings.append(
                    f"{name}: not found in {Sources.TMDB.label} with ID {tmdb_id}.",
                )
                return
            raise

        library_media_type = ""
        grouped_anime_match = None
        if anime_router is not None:
            route = anime_router.route_for_show(metadata, tmdb_id=tmdb_id)
            if route == "flat":
                # This show's home is a flat MAL row, which a TMDB-identified
                # Stremio series cannot populate. Importing it as TV would
                # track the same show in both libraries, so skip it and say so.
                self.warnings.append(
                    f"{name}: tracked as anime on {Sources.MAL.label}; skipped "
                    "so it is not also imported into TV",
                )
                return
            if route == "grouped":
                grouped_anime_match = grouped_anime.classify(
                    metadata,
                    snapshot=anime_router.snapshot,
                )
                library_media_type = MediaTypes.ANIME.value
                if (
                    tv_instance is not None
                    and grouped_anime_match is not None
                    and not grouped_anime.promote_grouped_anime(
                        tv_instance.item,
                        grouped_anime_match,
                    )
                ):
                    self.warnings.append(
                        f"{name}: exact anime match had a target-bucket collision; "
                        "kept in TV",
                    )
                    library_media_type = ""
                if library_media_type:
                    anime_router.remember(
                        "grouped",
                        tmdb_id=tmdb_id,
                        mal_ids=getattr(grouped_anime_match, "mal_ids", ()),
                    )

        if tv_instance is None:
            tv_item = helpers.find_item_across_buckets(
                preferred_bucket=library_media_type or None,
                media_id=tmdb_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
            )
            if tv_item is None:
                tv_item = app.models.Item.objects.create(
                    media_id=tmdb_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.TV.value,
                    library_media_type=library_media_type,
                    **app.models.Item.title_fields_from_metadata(metadata),
                    image=metadata["image"],
                )

            if (
                library_media_type == MediaTypes.ANIME.value
                and grouped_anime_match is not None
                and not grouped_anime.promote_grouped_anime(
                    tv_item,
                    grouped_anime_match,
                )
            ):
                self.warnings.append(
                    f"{name}: exact anime match had a target-bucket collision; "
                    "kept in TV",
                )
                library_media_type = ""

            tv_instance = app.models.TV(
                item=tv_item,
                user=self.user,
                status=tv_status,
            )
            tv_instance._history_date = self._get_history_date(entry)
            self.bulk_media[MediaTypes.TV.value].append(tv_instance)

        if watched_episodes:
            self._process_seasons_and_episodes(
                entry,
                tv_instance,
                tmdb_id,
                metadata,
                watched_episodes,
                name,
            )

    def _watched_videos(self, entry, video_ids, name):
        """Return the set of watched video ids for a series entry."""
        state = entry.get("state") or {}
        watched_str = state.get("watched")
        video_id = state.get("video_id")

        if watched_str and video_ids:
            try:
                watched, anchored = decode_watched_bitfield(watched_str, video_ids)
            except (ValueError, zlib.error) as error:
                logger.warning(
                    "Could not decode watched bitfield for %s: %s",
                    entry.get("_id"),
                    error,
                )
            else:
                # An aligned decode is only useful when it carries bits. An
                # empty bitfield asserts nothing — Stremio writes one for a
                # series whose state has a `video_id`/`timesWatched` but no
                # per-episode bits — so returning it would drop the
                # last-watched episode the fallback below recovers. Two live
                # series (Dexter, Naked Attraction) have exactly that shape.
                if anchored and watched:
                    return watched
                if not anchored:
                    logger.warning(
                        "Watched bitfield anchor absent from the video list for "
                        "%s; using last watched video only",
                        entry.get("_id"),
                    )

        # Fallback: mark only the last played video as watched.
        if watched_str or state.get("flaggedWatched") or state.get("timesWatched"):
            if watched_str and not video_ids:
                self.warnings.append(
                    f"{name}: episode list unavailable from Cinemeta - only the "
                    "last watched episode was imported",
                )
            if video_id and parse_video_id(video_id):
                return {video_id}

        return set()

    def _child_bucket(self, show_item, default_bucket):
        """Return the library bucket a show's season/episode rows belong in.

        Mirrors Season.get_episode_item: children follow the show's grouping
        bucket (grouped anime lives on TV rows) and otherwise fall back to
        their own media type, never inheriting a container's 'tv' bucket.
        """
        show_bucket = show_item.library_media_type
        if show_bucket and show_bucket != MediaTypes.TV.value:
            return show_bucket
        return default_bucket

    def _process_seasons_and_episodes(
        self,
        entry,
        tv_instance,
        tmdb_id,
        metadata,
        watched_episodes,
        name,
    ):
        """Create season and episode records for watched episodes."""
        episodes_by_season = defaultdict(list)
        for season_number, episode_number in watched_episodes:
            episodes_by_season[season_number].append(episode_number)

        history_date = self._get_history_date(entry)

        for season_number, episode_numbers in sorted(episodes_by_season.items()):
            season_metadata = metadata.get(f"season/{season_number}")
            if not season_metadata:
                self.warnings.append(
                    f"{name}: missing {Sources.TMDB.label} metadata for season "
                    f"{season_number}",
                )
                continue

            season_image = season_metadata.get("image") or metadata.get("image")
            season_bucket = self._child_bucket(tv_instance.item, MediaTypes.SEASON.value)
            season_item = helpers.find_item_across_buckets(
                preferred_bucket=season_bucket,
                media_id=tmdb_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=season_number,
            )
            if season_item is None:
                season_item, _ = app.models.Item.objects.get_or_create(
                    media_id=tmdb_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.SEASON.value,
                    library_media_type=season_bucket,
                    season_number=season_number,
                    defaults={
                        **app.models.Item.title_fields_from_metadata(metadata),
                        "image": season_image,
                    },
                )

            max_progress = int(season_metadata.get("max_progress") or 0)
            watched_episode_numbers = {
                int(number)
                for number in episode_numbers
                if int(number) > 0
            }
            season_complete = (
                max_progress > 0
                and set(range(1, max_progress + 1)).issubset(
                    watched_episode_numbers,
                )
            )
            season_status = (
                Status.COMPLETED.value
                if season_complete
                else Status.IN_PROGRESS.value
            )

            # An already-tracked show reaches here on re-sync (tv_instance may
            # be the existing, saved TV row) - a season already created by a
            # prior sync must be advanced in place, not re-created.
            existing_season = app.models.Season.objects.filter(
                user=self.user,
                item=season_item,
            ).first()
            if existing_season is not None:
                old_rank = _STATUS_RANK.get(existing_season.status)
                new_rank = _STATUS_RANK.get(season_status)
                if (
                    old_rank is not None
                    and new_rank is not None
                    and new_rank > old_rank
                ):
                    # Season.save() treats completion as a manual action and
                    # creates every episode after the latest watched one.
                    # Stremio already supplied the authoritative episode set.
                    existing_season.status = season_status
                    bulk_update_with_history(
                        [existing_season],
                        app.models.Season,
                        ["status"],
                        default_change_reason=STREMIO_IMPORT_REASON,
                    )
                season_instance = existing_season
            elif season_item.id in self.bulk_season_by_item_id:
                # Grouped-anime promotion can unify two Stremio entries onto
                # the same show/season mid-run - reuse the sibling entry's
                # still-unsaved Season instead of queuing a duplicate that
                # would collide on (related_tv, item) at bulk insert time.
                queued_season = self.bulk_season_by_item_id[season_item.id]
                old_rank = _STATUS_RANK.get(queued_season.status)
                new_rank = _STATUS_RANK.get(season_status)
                if (
                    old_rank is not None
                    and new_rank is not None
                    and new_rank > old_rank
                ):
                    queued_season.status = season_status
                season_instance = queued_season
            else:
                season_instance = app.models.Season(
                    item=season_item,
                    user=self.user,
                    related_tv=tv_instance,
                    # A dropped/paused show keeps new seasons off the In
                    # progress shelf; the plays are still recorded.
                    status=(
                        tv_instance.status
                        if tv_instance.status in app.models.USER_HELD_STATUSES
                        else season_status
                    ),
                )
                season_instance._history_date = history_date
                self.bulk_media[MediaTypes.SEASON.value].append(season_instance)
                self.bulk_season_by_item_id[season_item.id] = season_instance

            episode_bucket = self._child_bucket(tv_instance.item, MediaTypes.EPISODE.value)
            for episode_number in episode_numbers:
                episode_item = helpers.find_item_across_buckets(
                    preferred_bucket=episode_bucket,
                    media_id=tmdb_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    season_number=season_number,
                    episode_number=episode_number,
                )
                if episode_item is None:
                    episode_item, _ = app.models.Item.objects.get_or_create(
                        media_id=tmdb_id,
                        source=Sources.TMDB.value,
                        media_type=MediaTypes.EPISODE.value,
                        library_media_type=episode_bucket,
                        season_number=season_number,
                        episode_number=episode_number,
                        defaults={
                            **app.models.Item.title_fields_from_metadata(metadata),
                            "image": self._get_episode_image(
                                episode_number,
                                season_metadata,
                            ),
                        },
                    )

                # Stremio has no per-episode watch dates, so a previously
                # recorded watch for this episode can't be told apart from a
                # re-sync of the same state - skip it to avoid piling up
                # duplicate watch rows every 2 hours (see Episode's
                # one-row-per-watch model in app/models/tv.py).
                if existing_season is not None and app.models.Episode.objects.filter(
                    item=episode_item,
                    related_season=existing_season,
                ).exists():
                    continue

                episode_instance = app.models.Episode(
                    item=episode_item,
                    related_season=season_instance,
                    end_date=history_date,
                )
                episode_instance._history_date = history_date
                self.bulk_media[MediaTypes.EPISODE.value].append(episode_instance)

    def _get_episode_image(self, episode_number, season_metadata):
        """Get the image for an episode from season metadata."""
        for episode_metadata in season_metadata.get("episodes", []):
            if episode_metadata["episode_number"] == episode_number:
                if episode_metadata.get("image"):
                    return episode_metadata["image"]
                still_path = episode_metadata.get("still_path")
                if still_path:
                    return f"https://image.tmdb.org/t/p/w500{still_path}"
                return settings.IMG_NONE
        return settings.IMG_NONE

    def _resolve_tmdb_id(self, entry_id, media_type):
        """Resolve a Stremio movie/series id to a bare TMDB id, or None."""
        classified = classify_stremio_id(entry_id)
        if classified is None:
            return None
        namespace, raw = classified

        if namespace == "imdb":
            return self._tmdb_id_via_find(raw, "imdb_id", media_type)
        if namespace == "tmdb":
            return int(raw) if raw.isdigit() else None
        if namespace == "tvdb":
            return self._tmdb_id_via_find(raw, "tvdb_id", media_type)
        if namespace == "trakt":
            return self._tmdb_id_via_trakt(raw, media_type)
        return None

    def _tmdb_id_via_find(self, external_id, external_source, media_type):
        """Resolve an external id to a TMDB id via TMDB's /find endpoint."""
        if not external_id:
            return None
        try:
            response = app.providers.tmdb.find(external_id, external_source)
        except services.ProviderAPIError as error:
            logger.warning(
                "Error looking up %s %s in TMDB: %s",
                external_source,
                external_id,
                error,
            )
            return None

        key = "movie_results" if media_type == MediaTypes.MOVIE.value else "tv_results"
        results = response.get(key) or []
        return results[0]["id"] if results else None

    def _tmdb_id_via_trakt(self, trakt_id, media_type):
        """Resolve a Trakt id to a TMDB id via Trakt's external-id search."""
        if not app.providers.trakt.is_configured():
            return None
        try:
            result = app.providers.trakt.lookup_by_external_id(
                "trakt",
                trakt_id,
                media_type=media_type,
            )
        except (services.ProviderAPIError, requests.exceptions.RequestException) as error:
            # `services.api_request` re-raises a non-retryable HTTP status (403,
            # 404) as a raw `requests.HTTPError`, not a `ProviderAPIError`, so
            # catching only the latter let one unresolvable id abort the whole
            # import. Trakt answers 403 on its paid tier, and two library
            # entries are `trakt:`-namespaced.
            logger.warning("Error looking up Trakt ID %s: %s", trakt_id, error)
            return None
        if not result:
            return None
        return (result.get("external_ids") or {}).get("tmdb")

    def _resolve_mal_id(self, entry_id):
        """Resolve a Stremio anime id (kitsu:/mal:/anilist:) to a MAL id, or None."""
        classified = classify_stremio_id(entry_id)
        if classified is None:
            return None
        namespace, raw = classified

        if namespace == "mal":
            return int(raw) if raw.isdigit() else None
        if namespace == "kitsu":
            return self._mal_id_via_kitsu(raw)
        if namespace == "anilist":
            return self._mal_id_via_anilist(raw)
        return None

    def _mal_id_via_kitsu(self, kitsu_id):
        """Resolve a Kitsu anime id to a MAL id via Kitsu's mappings."""
        if not kitsu_id:
            return None
        params = {
            "include": "mappings",
            "fields[mappings]": "externalSite,externalId",
        }
        try:
            response = services.api_request(
                "KITSU",
                "GET",
                f"{KITSU_API_BASE_URL}/anime/{kitsu_id}",
                params=params,
            )
        except services.ProviderAPIError as error:
            logger.warning("Error looking up Kitsu ID %s: %s", kitsu_id, error)
            return None

        mappings = {
            mapping["attributes"]["externalSite"]: mapping["attributes"]["externalId"]
            for mapping in response.get("included", [])
            if mapping.get("type") == "mappings"
        }
        return helpers.mal_id_from_kitsu_mappings(mappings, MediaTypes.ANIME.value)

    def _mal_id_via_anilist(self, anilist_id):
        """Resolve an AniList media id to a MAL id via AniList's public GraphQL API."""
        if not anilist_id:
            return None
        query = "query ($id: Int) { Media(id: $id) { idMal } }"
        try:
            response = services.api_request(
                "ANILIST",
                "POST",
                ANILIST_GRAPHQL_URL,
                params={"query": query, "variables": {"id": int(anilist_id)}},
            )
        except (services.ProviderAPIError, ValueError) as error:
            logger.warning("Error looking up AniList ID %s: %s", anilist_id, error)
            return None

        mal_id = (response.get("data") or {}).get("Media", {}).get("idMal")
        return int(mal_id) if mal_id else None

    def _process_anime(self, entry, anime_router=None):
        """Process a single Stremio anime entry (kitsu:/mal:/anilist: ids)."""
        entry_id = entry["_id"]
        name = entry.get("name", entry_id)
        state = entry.get("state") or {}

        mal_id = self._resolve_mal_id(entry_id)
        if mal_id is None:
            self.warnings.append(
                f"{name}: couldn't find a match in {Sources.MAL.label}",
            )
            return

        if anime_router is not None and (
            anime_router.route_for_mal_id(mal_id) == "grouped"
        ):
            # A series entry earlier in this run already imported this show as
            # grouped anime. Opening a flat row now would track it twice.
            self.warnings.append(
                f"{name}: already imported as grouped anime in this run",
            )
            return

        media_id = str(mal_id)
        status, watched = self._movie_status(state)
        last_watched = self._parse_date(state.get("lastWatched"))

        existing_anime = self.existing_media[MediaTypes.ANIME.value][
            Sources.MAL.value
        ].get(media_id)
        if existing_anime is not None and self.mode == "new":
            self._advance_status_in_place(
                existing_anime,
                status,
                progress=1 if status == Status.COMPLETED.value else existing_anime.progress,
                start_date=last_watched
                if status != Status.PLANNING.value
                else existing_anime.start_date,
                end_date=last_watched if watched else existing_anime.end_date,
            )
            return

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.ANIME.value,
            Sources.MAL.value,
            media_id,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        try:
            anime_metadata = app.providers.mal.anime(mal_id)
        except services.ProviderAPIError as error:
            self.warnings.append(
                f"{name}: couldn't fetch MyAnimeList details ({error})",
            )
            return

        anime_item, _ = app.models.Item.objects.get_or_create(
            media_id=mal_id,
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            defaults={
                **app.models.Item.title_fields_from_metadata(anime_metadata),
                "image": anime_metadata["image"],
            },
        )

        anime_instance = app.models.Anime(
            item=anime_item,
            user=self.user,
            status=status,
            progress=1 if status == Status.COMPLETED.value else 0,
            start_date=last_watched if status != Status.PLANNING.value else None,
            end_date=last_watched if watched else None,
        )
        anime_instance._history_date = self._get_history_date(entry)
        self.bulk_media[MediaTypes.ANIME.value].append(anime_instance)

    def _parse_date(self, date_str):
        """Convert a Stremio ISO timestamp to a datetime, or None."""
        if date_str:
            return parse_datetime(date_str)
        return None

    def _get_history_date(self, entry):
        """Get the history date for an entry."""
        state = entry.get("state") or {}
        return (
            self._parse_date(state.get("lastWatched"))
            or self._parse_date(entry.get("_mtime"))
            or timezone.now()
        )
