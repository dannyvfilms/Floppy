import json
import logging
from collections import defaultdict

import requests
from django.conf import settings
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django_celery_beat.models import PeriodicTask
from simple_history.utils import bulk_update_with_history

import app
from app import helpers as app_helpers
from app.models import MediaTypes, Sources, Status
from app.providers import services, tvdb
from app.services import item_merge
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

TRAKT_API_BASE_URL = "https://api.trakt.tv"
BULK_PAGE_SIZE = 1000
TRAKT_UNKNOWN_DATE = "1970-01-01T00:00:00.000Z"


def _parse_watched_at(watched_at: str):
    if watched_at == TRAKT_UNKNOWN_DATE:
        return None
    return parse_datetime(watched_at)


def handle_oauth_callback(
    request,
    redirect_uri=None,
    client_id=None,
    client_secret=None,
):
    """View for getting the Trakt OAuth2 token."""
    code = request.GET["code"]

    url = "https://api.trakt.tv/oauth/token"

    if not redirect_uri:
        redirect_uri = app_helpers.build_absolute_app_url(
            request,
            reverse("import_trakt_private"),
        )
    if not client_id:
        client_id = settings.TRAKT_API
    if not client_secret:
        client_secret = settings.TRAKT_API_SECRET

    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        token_response = app.providers.services.api_request(
            "TRAKT",
            "POST",
            url,
            params=params,
        )
    except services.ProviderAPIError as error:
        if error.status_code == requests.codes.unauthorized:
            msg = "Invalid Trakt secret key."
            raise MediaImportError(msg) from error
        raise

    return {
        "access_token": token_response["access_token"],
        "refresh_token": token_response["refresh_token"],
        "username": get_username_from_oauth(
            token_response["access_token"],
            client_id=client_id,
        ),
    }


def get_username_from_oauth(access_token, client_id=None):
    """View for getting the Trakt OAuth2 username."""
    url = "https://api.trakt.tv/users/me"

    if not client_id:
        client_id = settings.TRAKT_API

    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Floppy/{settings.VERSION}",
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Authorization": f"Bearer {access_token}",
    }

    try:
        request = app.providers.services.api_request(
            "TRAKT",
            "GET",
            url,
            headers=headers,
        )
    except services.ProviderAPIError as error:
        if error.status_code == requests.codes.unauthorized:
            msg = "Invalid Trakt secret key."
            raise MediaImportError(msg) from error
        raise

    return request["username"]


def get_access_token(encrypted_refresh_token):
    """Get access token from encrypted refresh token."""
    url = "https://api.trakt.tv/oauth/token"

    decrypted_token = helpers.decrypt_or_raise(encrypted_refresh_token)

    params = {
        "client_id": settings.TRAKT_API,
        "client_secret": settings.TRAKT_API_SECRET,
        "refresh_token": decrypted_token,
        "grant_type": "refresh_token",
        "redirect_uri": app_helpers.build_absolute_app_url(
            None,
            reverse("import_trakt_private"),
        ),
    }

    try:
        request = app.providers.services.api_request(
            "TRAKT",
            "POST",
            url,
            params=params,
        )
    except services.ProviderAPIError as error:
        if error.status_code == requests.codes.unauthorized:
            msg = "Invalid Trakt secret key."
            raise MediaImportError(msg) from error
        raise

    # refresh tokens are one time use only
    update_refresh_token(encrypted_refresh_token, request["refresh_token"])
    return request["access_token"]


def update_refresh_token(old_token, new_token):
    """Update the refresh token in periodic tasks."""
    periodic_task = PeriodicTask.objects.filter(
        task="Import from Trakt",
        kwargs__contains=f'"token": "{old_token}"',
    ).first()

    if periodic_task:
        task_kwargs = json.loads(periodic_task.kwargs)
        task_kwargs["token"] = helpers.encrypt(new_token)
        periodic_task.kwargs = json.dumps(task_kwargs)
        periodic_task.save()


def importer(token, user, mode, username):
    """Import the user's data from Trakt.

    Can import using either OAuth (token provided) or public username.
    When using OAuth, username should be the authenticated user's username.
    When using public import, username is the Trakt username and token should be None.

    Args:
        token (str, optional): Encrypted OAuth2 refresh token if using OAuth else None
        user: Django user object to import data for
        mode (str): Import mode ("new" or "overwrite")
        username (str): Trakt username to import from
    """
    trakt_importer = TraktImporter(username, user, mode, refresh_token=token)
    return trakt_importer.import_data()


class TraktMetadataResolverMixin:
    """Shared TMDB metadata/Item resolution logic for Trakt-sourced importers.

    Requires the including class to maintain a ``self.warnings`` list.
    """

    def _get_tmdb_id(self, entry_data):
        """Extract TMDB ID from entry data."""
        if (
            "ids" in entry_data
            and "tmdb" in entry_data["ids"]
            and entry_data["ids"]["tmdb"]
        ):
            return str(entry_data["ids"]["tmdb"])

        self.warnings.append(
            f"{entry_data['title']}: No {Sources.TMDB.label} ID found.",
        )
        return None

    def _get_metadata(self, media_type, tmdb_id, title, season_number=None):
        """Get metadata for a media item."""
        try:
            kwargs = {}
            if season_number is not None:
                kwargs["season_numbers"] = [season_number]

            return services.get_media_metadata(
                media_type,
                tmdb_id,
                Sources.TMDB.value,
                **kwargs,
            )
        except services.ProviderAPIError as error:
            if error.status_code == requests.codes.not_found:
                if media_type == MediaTypes.SEASON.value:
                    title = f"{title} S{season_number}"
                self.warnings.append(
                    f"{title}: not found in {Sources.TMDB.label} with ID {tmdb_id}.",
                )
                return None
            if error.status_code == requests.codes.unauthorized:
                msg = f"Invalid {Sources.TMDB.label} API key."
                raise MediaImportError(msg) from error
            raise

    def _get_or_create_item(
        self,
        media_type,
        tmdb_id,
        metadata,
        season_number=None,
        episode_number=None,
    ):
        """Get or create an item in the database.

        The same season/episode can legitimately exist under more than one
        ``library_media_type`` bucket (e.g. grouped anime stored on TV rows, or
        episodes auto-created when a season is marked complete). A plain
        ``get_or_create`` keyed only on the identity fields therefore risks
        ``MultipleObjectsReturned``. Reuse any existing matching item instead of
        failing or creating a divergent duplicate, preferring the bucket this
        importer would normally use.
        """
        item_kwargs = {
            "media_id": tmdb_id,
            "source": Sources.TMDB.value,
            "media_type": media_type,
        }

        if season_number is not None:
            item_kwargs["season_number"] = season_number

        if episode_number is not None:
            item_kwargs["episode_number"] = episode_number

        desired_bucket = metadata.get("library_media_type") or media_type

        existing = list(app.models.Item.objects.filter(**item_kwargs))
        if existing:
            for item in existing:
                if item.library_media_type == desired_bucket:
                    return item
            return existing[0]

        preferred_provider_item = self._find_preferred_provider_item(
            media_type,
            tmdb_id,
            season_number,
            desired_bucket,
        )
        if preferred_provider_item is not None:
            return preferred_provider_item

        return app.models.Item.objects.create(
            **item_kwargs,
            library_media_type=desired_bucket,
            **app.models.Item.title_fields_from_metadata(metadata),
            image=metadata["image"],
        )

    def _find_preferred_provider_item(
        self,
        media_type,
        tmdb_id,
        season_number,
        desired_bucket,
    ):
        """Reuse an existing TVDB item instead of creating a duplicate TMDB one.

        This importer only ever resolves shows/seasons via TMDB, so a
        TVDB-preferring user who already tracks a show gets a second,
        independent ``Item`` tree for it on every import unless we look for
        their existing TVDB item first (#620). Scoped to users who actually
        prefer TVDB, since the lookup costs a TMDB->TVDB id resolution call.
        """
        if getattr(self.user, "tv_metadata_source_default", "") != Sources.TVDB.value:
            return None
        if not tvdb.enabled():
            return None

        return item_merge.find_tvdb_counterpart(
            tmdb_id,
            media_type,
            season_number=season_number,
            library_media_type=desired_bucket,
        )

    def _get_episode_image(self, episode_number, season_metadata):
        """Extract episode image URL from season metadata."""
        for episode in season_metadata["episodes"]:
            if episode["episode_number"] == episode_number:
                if episode.get("still_path"):
                    return f"https://image.tmdb.org/t/p/w500{episode['still_path']}"
                break
        return settings.IMG_NONE


class TraktImporter(TraktMetadataResolverMixin):
    """Class to handle importing user data from Trakt."""

    def __init__(self, username, user, mode, refresh_token=None):
        """Initialize the importer with user details and mode.

        Args:
            username (str): Trakt username to import from
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
            refresh_token (str, optional): Encrypted OAuth2 refresh token if
                using OAuth, None for public import
        """
        self.username = username
        self.user = user
        self.mode = mode
        self.refresh_token = refresh_token
        self.is_oauth_import = bool(refresh_token)
        user_identifier = "me" if self.is_oauth_import else username
        self.user_base_url = f"{TRAKT_API_BASE_URL}/users/{user_identifier}"
        self.warnings = []

        # Track existing media to handle "new" mode correctly
        self.existing_media = helpers.get_existing_media(user)

        # Track media the user explicitly deleted, so it isn't recreated
        self.deleted_media = helpers.get_deleted_media(user)

        # Track previously imported episode plays so rerunning the same sync
        # does not create duplicate episode history rows.
        self.existing_episode_watch_keys = self._get_existing_episode_watch_keys()

        # Track media IDs to delete in overwrite mode
        self.to_delete = defaultdict(lambda: defaultdict(set))

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        # Track media instances being created
        self.media_instances = defaultdict(lambda: defaultdict(list))

        # Track existing DB objects promoted to COMPLETED during import
        self.completed_seasons = []
        self.completed_tvs = []

        # Track TMDB IDs the user has dropped on Trakt (hidden/progress_watched)
        self.dropped_tmdb_ids: set = set()
        self.dropped_tvs: list = []

        # Track TV/Season rows newly created in this run, so completion/dropped
        # status derived from Trakt history is only applied to rows Floppy is
        # seeing for the first time (or on an explicit overwrite re-sync),
        # never silently onto a show/season the user is already tracking
        # locally with a status they set themselves.
        self.tv_created_this_run: set = set()
        self.season_created_this_run: set = set()

        logger.info(
            "Initialized Trakt importer for user %s with mode %s",
            username,
            mode,
        )

    def _get_existing_episode_watch_keys(self):
        """Return exact episode play keys already stored for this user."""
        if self.mode != "new":
            return set()

        return set(
            app.models.Episode.objects.filter(
                related_season__user=self.user,
                end_date__isnull=False,
            ).values_list(
                "item__media_id",
                "item__season_number",
                "item__episode_number",
                "end_date",
            ),
        )

    def _raise_for_user_error(self, error):
        """Translate a Trakt HTTP error about the user into a MediaImportError."""
        if error.response.status_code == requests.codes.not_found:
            msg = (
                f"User slug {self.username} not found. "
                "User slug can be found in your Trakt profile URL."
            )
            raise MediaImportError(msg) from error

        if error.response.status_code == requests.codes.unauthorized:
            msg = "This account is set to private, use OAuth import instead."
            raise MediaImportError(msg) from error

    def _validate_username(self):
        """Fail fast on a bad slug.

        Trakt answers /history and /watchlist for an unknown user with an empty
        200, so without this check the import runs to completion looking like a
        no-op, or dies minutes later on the first endpoint that does 404.
        """
        try:
            self._make_api_request(self.user_base_url)
        except requests.exceptions.HTTPError as error:
            self._raise_for_user_error(error)
            raise

    def import_data(self):
        """Import all user data from Trakt."""
        self._validate_username()
        self.process_dropped()
        self.process_history()
        self.process_watchlist()
        self.process_ratings()
        self.process_notes()
        self.process_comments()
        self.process_collection()

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        if self.completed_seasons:
            bulk_update_with_history(
                self.completed_seasons, app.models.Season, fields=["status"]
            )
        if self.completed_tvs:
            bulk_update_with_history(
                self.completed_tvs, app.models.TV, fields=["status"]
            )
        if self.dropped_tvs:
            bulk_update_with_history(self.dropped_tvs, app.models.TV, fields=["status"])

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))

        return imported_counts, deduplicated_messages

    def _make_api_request(self, url):
        """Make a request to the Trakt API with proper headers."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"Floppy/{settings.VERSION}",
            "trakt-api-version": "2",
            "trakt-api-key": settings.TRAKT_API,
        }
        if self.refresh_token:
            try:
                # already made api_request before, so access_token is set
                headers["Authorization"] = f"Bearer {self.access_token}"
            except AttributeError:
                self.access_token = get_access_token(self.refresh_token)
                headers["Authorization"] = f"Bearer {self.access_token}"
        return services.api_request(
            "TRAKT",
            "GET",
            url,
            headers=headers,
        )

    def _get_paginated_data(self, endpoint, item_type="items"):
        """Get paginated data from Trakt API."""
        page = 1
        all_data = []

        while True:
            url = f"{endpoint}?page={page}&limit={BULK_PAGE_SIZE}"

            try:
                page_data = self._make_api_request(url)
            except requests.exceptions.HTTPError as error:
                self._raise_for_user_error(error)

                if error.response.status_code == requests.codes.method_not_allowed:
                    logger.warning(
                        "Trakt endpoint %s returned 405 (not available for this account), skipping.",
                        endpoint,
                    )
                    return []
                raise

            if not page_data:
                # We've reached the end of the data
                break

            all_data.extend(page_data)
            page += 1
            import_progress.report(
                len(all_data),
                total=None,
                label=f"Trakt: gathering {item_type}…",
            )
            logger.info(
                "Retrieved page %s of %s for user %s (%s items)",
                page - 1,
                item_type,
                self.username,
                len(page_data),
            )

        logger.info(
            "Retrieved %s total %s for user %s",
            len(all_data),
            item_type,
            self.username,
        )
        return all_data

    def process_history(self):
        """Process watch history from Trakt."""
        logger.info("Importing watch history for user %s", self.username)
        history_endpoint = f"{self.user_base_url}/history"
        full_history = self._get_paginated_data(history_endpoint, "history entries")

        # Some private profiles can return empty user history with OAuth.
        # Fallback to the authenticated sync endpoint in that case.
        if self.is_oauth_import and not full_history:
            fallback_endpoint = f"{TRAKT_API_BASE_URL}/sync/history"
            logger.warning(
                "Empty Trakt history for OAuth user %s at %s. Trying %s",
                self.username,
                history_endpoint,
                fallback_endpoint,
            )
            try:
                full_history = self._get_paginated_data(
                    fallback_endpoint,
                    "history entries",
                )
            except Exception:
                logger.exception(
                    "Fallback Trakt history endpoint failed for user %s",
                    self.username,
                )

        # Process in chronological order (oldest first)
        total = len(full_history)
        for i, entry in enumerate(reversed(full_history), start=1):
            import_progress.report(i, total, "Trakt: watch history")
            watched_at = entry["watched_at"]
            try:
                if entry["type"] == "movie":
                    logger.info(
                        "Processing movie %s watched at %s",
                        entry["movie"]["title"],
                        watched_at,
                    )
                    self.process_watched_movie(entry)
                elif entry["type"] == "episode":
                    logger.info(
                        "Processing episode %s S%sE%s watched at %s",
                        entry["show"]["title"],
                        entry["episode"]["season"],
                        entry["episode"]["number"],
                        watched_at,
                    )
                    self.process_watched_episode(entry)
            except MediaImportError:
                # Fatal, importer-level problems (auth, etc.) must still abort.
                raise
            except Exception as e:
                # A single malformed/unexpected entry should not abort the whole
                # import; record it as a warning and continue with the rest.
                logger.exception("Skipping Trakt history entry")
                source_data = entry.get("show") or entry.get("movie") or {}
                title = source_data.get("title", "Unknown title")
                self.warnings.append(
                    f"{title}: skipped a watch entry due to an unexpected error ({e}).",
                )

    def process_watched_movie(self, entry):
        """Process a single movie watch event."""
        movie = entry["movie"]
        tmdb_id = self._get_tmdb_id(movie)
        if not tmdb_id:
            return

        # Check if we should process this movie based on mode
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.MOVIE.value,
            Sources.TMDB.value,
            tmdb_id,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        metadata = self._get_metadata(MediaTypes.MOVIE.value, tmdb_id, movie["title"])
        if not metadata:
            return

        item = self._get_or_create_item(MediaTypes.MOVIE.value, tmdb_id, metadata)
        watched_at = entry["watched_at"]
        watched_at_dt = _parse_watched_at(watched_at)

        key = f"{tmdb_id}"

        movie_obj = app.models.Movie(
            item=item,
            user=self.user,
            end_date=watched_at_dt,
            status=Status.COMPLETED.value,
            progress=1,
        )
        if watched_at_dt is not None:
            movie_obj._history_date = watched_at_dt

        self.media_instances[MediaTypes.MOVIE.value][key].append(movie_obj)
        self.bulk_media[MediaTypes.MOVIE.value].append(movie_obj)

    def process_watched_episode(self, entry):
        """Process a single episode watch event."""
        show = entry["show"]
        tmdb_id = self._get_tmdb_id(show)
        if not tmdb_id:
            return

        if tmdb_id in self.deleted_media[MediaTypes.TV.value][Sources.TMDB.value]:
            logger.debug(
                "Skipping watch history for deleted TV show: %s (deleted locally)",
                tmdb_id,
            )
            return

        # Extract episode data
        season_number = entry["episode"]["season"]
        episode_number = entry["episode"]["number"]
        watched_at = entry["watched_at"]
        watched_at_dt = _parse_watched_at(watched_at)
        episode_watch_key = (tmdb_id, season_number, episode_number, watched_at_dt)

        if episode_watch_key in self.existing_episode_watch_keys:
            logger.debug(
                "Skipping existing episode watch for %s S%sE%s at %s",
                show["title"],
                season_number,
                episode_number,
                watched_at,
            )
            return

        tv_exists = (
            tmdb_id in self.existing_media[MediaTypes.TV.value][Sources.TMDB.value]
        )
        if self.mode == "overwrite" and tv_exists:
            self.to_delete[MediaTypes.TV.value][Sources.TMDB.value].add(tmdb_id)

        # Get TV metadata
        tv_metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, show["title"])
        if not tv_metadata:
            return

        # Get Season metadata
        season_metadata = self._get_metadata(
            MediaTypes.SEASON.value,
            tmdb_id,
            show["title"],
            season_number,
        )
        if not season_metadata:
            return

        # Validate episode number exists in TMDB
        episode_exists = any(
            ep["episode_number"] == episode_number for ep in season_metadata["episodes"]
        )

        if not episode_exists:
            item_identifier = f"{show['title']} S{season_number}E{episode_number}"
            self.warnings.append(
                f"{item_identifier}: not found in {Sources.TMDB.label} "
                f"with ID {tmdb_id}.",
            )
            return

        episode_image = self._get_episode_image(episode_number, season_metadata)
        matched_episode = next(
            (
                ep
                for ep in season_metadata["episodes"]
                if ep["episode_number"] == episode_number
            ),
            None,
        )

        # Create or get TV show
        tv_item = self._get_or_create_item(MediaTypes.TV.value, tmdb_id, tv_metadata)
        tv_key = f"{tmdb_id}"

        if tv_key not in self.media_instances[MediaTypes.TV.value]:
            tv_obj = self.existing_media[MediaTypes.TV.value][Sources.TMDB.value].get(
                tmdb_id,
            )
            tv_marked_for_deletion = (
                tmdb_id in self.to_delete[MediaTypes.TV.value][Sources.TMDB.value]
            )
            if tv_obj is None or tv_marked_for_deletion:
                status = (
                    Status.DROPPED.value
                    if tmdb_id in self.dropped_tmdb_ids
                    else Status.IN_PROGRESS.value
                )
                tv_obj = app.models.TV(
                    item=tv_item,
                    user=self.user,
                    status=status,
                )
                if watched_at_dt is not None:
                    tv_obj._history_date = watched_at_dt
                self.bulk_media[MediaTypes.TV.value].append(tv_obj)
                self.tv_created_this_run.add(tv_key)
            elif (
                self.mode == "overwrite"
                and tmdb_id in self.dropped_tmdb_ids
                and tv_obj.status != Status.DROPPED.value
            ):
                tv_obj.status = Status.DROPPED.value
                self.dropped_tvs.append(tv_obj)
            self.media_instances[MediaTypes.TV.value][tv_key] = [tv_obj]
        else:
            tv_obj = self.media_instances[MediaTypes.TV.value][tv_key][0]

        # Create or get Season
        season_item = self._get_or_create_item(
            MediaTypes.SEASON.value,
            tmdb_id,
            season_metadata,
            season_number,
        )

        season_key = f"{tmdb_id}:{season_number}"
        if season_key not in self.media_instances[MediaTypes.SEASON.value]:
            tv_marked_for_deletion = (
                tmdb_id in self.to_delete[MediaTypes.TV.value][Sources.TMDB.value]
            )
            season_obj = None
            if not tv_marked_for_deletion:
                season_obj = app.models.Season.objects.filter(
                    user=self.user,
                    item=season_item,
                ).first()
            if season_obj is None:
                season_obj = app.models.Season(
                    item=season_item,
                    user=self.user,
                    related_tv=tv_obj,
                    status=Status.IN_PROGRESS.value,
                )
                if watched_at_dt is not None:
                    season_obj._history_date = watched_at_dt
                self.bulk_media[MediaTypes.SEASON.value].append(season_obj)
                self.season_created_this_run.add(season_key)
            self.media_instances[MediaTypes.SEASON.value][season_key] = [season_obj]
        else:
            season_obj = self.media_instances[MediaTypes.SEASON.value][season_key][0]

        # Create Episode item and object
        episode_metadata = {
            **app.models.Item.title_fields_from_episode_metadata(
                matched_episode,
                fallback_title=tv_metadata["title"],
            ),
            "image": episode_image,
        }
        episode_item = self._get_or_create_item(
            MediaTypes.EPISODE.value,
            tmdb_id,
            episode_metadata,
            season_number,
            episode_number,
        )

        ep_key = f"{tmdb_id}:{season_number}:{episode_number}"

        episode_obj = app.models.Episode(
            item=episode_item,
            related_season=season_obj,
            end_date=watched_at_dt,
        )
        if watched_at_dt is not None:
            episode_obj._history_date = watched_at_dt
        self.media_instances[MediaTypes.EPISODE.value][ep_key].append(episode_obj)
        self.bulk_media[MediaTypes.EPISODE.value].append(episode_obj)
        self.existing_episode_watch_keys.add(episode_watch_key)

        # Update status if this is the last episode, but only for rows Floppy
        # just created (or an explicit overwrite re-sync) — never clobber the
        # status of a show/season the user is already tracking locally.
        if self.mode == "overwrite" or season_key in self.season_created_this_run:
            self._update_completion_status(
                season_obj,
                tv_obj,
                season_number,
                episode_number,
                season_metadata,
                tv_metadata,
                tv_key,
            )

    def _update_completion_status(
        self,
        season_obj,
        tv_obj,
        season_number,
        episode_number,
        season_metadata,
        tv_metadata,
        tv_key,
    ):
        """Update completion status for season and TV show if applicable."""
        if episode_number == season_metadata["max_progress"]:
            season_obj.status = Status.COMPLETED.value
            if season_obj.pk:
                self.completed_seasons.append(season_obj)

            last_season = tv_metadata.get("last_episode_season")
            tv_eligible = (
                self.mode == "overwrite" or tv_key in self.tv_created_this_run
            )
            if last_season and last_season == season_number and tv_eligible:
                tv_obj.status = Status.COMPLETED.value
                if tv_obj.pk:
                    self.completed_tvs.append(tv_obj)

    def process_watchlist(self):
        """Process watchlist from Trakt."""
        logger.info("Importing watchlist for user %s", self.username)
        watchlist_endpoint = f"{self.user_base_url}/watchlist"
        watchlist_data = self._get_paginated_data(watchlist_endpoint, "watchlist items")

        total = len(watchlist_data)
        for i, entry in enumerate(watchlist_data, start=1):
            import_progress.report(i, total, "Trakt: watchlist")
            try:
                self._process_generic_entry(
                    entry,
                    "watchlist",
                    {"status": Status.PLANNING.value},
                )
            except MediaImportError:
                # Fatal, importer-level problems (auth, etc.) must still abort.
                raise
            except Exception as e:
                msg = f"Error processing watchlist entry: {entry}"
                raise MediaImportUnexpectedError(msg) from e

    def process_ratings(self):
        """Process ratings from Trakt."""
        logger.info("Importing ratings for user %s", self.username)
        ratings_endpoint = f"{self.user_base_url}/ratings"
        ratings_data = self._get_paginated_data(ratings_endpoint, "ratings")

        total = len(ratings_data)
        for i, entry in enumerate(ratings_data, start=1):
            import_progress.report(i, total, "Trakt: ratings")
            try:
                self._process_generic_entry(
                    entry,
                    "rating",
                    # Trakt rates out of 10, which is already the internal storage
                    # scale, so the score is stored as-is. scale_score_for_storage
                    # converts *display* scores and would double a 5-scale user's.
                    {"score": entry["rating"]},
                )
            except MediaImportError:
                # Fatal, importer-level problems (auth, etc.) must still abort.
                raise
            except Exception as e:
                msg = f"Error processing rating entry: {entry}"
                raise MediaImportUnexpectedError(msg) from e

    def process_notes(self):
        """Process private notes from Trakt."""
        logger.info("Importing notes for user %s", self.username)
        notes_endpoint = f"{self.user_base_url}/notes"
        full_notes = self._get_paginated_data(notes_endpoint, "notes")

        total = len(full_notes)
        for i, entry in enumerate(full_notes, start=1):
            import_progress.report(i, total, "Trakt: notes")
            note_text = entry.get("note", {}).get("notes")
            if not note_text:
                continue
            try:
                self._process_generic_entry(entry, "note", {"notes": note_text})
            except MediaImportError:
                # Fatal, importer-level problems (auth, etc.) must still abort.
                raise
            except Exception as e:
                msg = f"Error processing note entry: {entry}"
                raise MediaImportUnexpectedError(msg) from e

    def process_comments(self):
        """Process comments from Trakt."""
        logger.info("Importing comments for user %s", self.username)
        comments_endpoint = f"{self.user_base_url}/comments"
        full_comments = self._get_paginated_data(comments_endpoint, "comments")

        total = len(full_comments)
        for i, entry in enumerate(full_comments, start=1):
            import_progress.report(i, total, "Trakt: comments")
            try:
                self._process_generic_entry(
                    entry,
                    "comment",
                    {"notes": entry["comment"]["comment"]},
                )
            except MediaImportError:
                # Fatal, importer-level problems (auth, etc.) must still abort.
                raise
            except Exception as e:
                msg = f"Error processing comment entry: {entry}"
                raise MediaImportUnexpectedError(msg) from e

    def process_collection(self):
        """Import owned-copy (collection) data from Trakt."""
        # Imported lazily to avoid a circular import: trakt_collection imports
        # TraktMetadataResolverMixin from this module.
        from integrations.imports import trakt_collection

        logger.info("Importing collection for user %s", self.username)

        movies_endpoint = f"{self.user_base_url}/collection/movies"
        collected_movies = self._get_paginated_data(movies_endpoint, "collected movies")
        movies_total = len(collected_movies)
        for i, entry in enumerate(collected_movies, start=1):
            import_progress.report(i, movies_total, "Trakt: collection (movies)")
            try:
                self._process_collected_movie(entry, trakt_collection)
            except Exception as e:
                logger.exception("Skipping Trakt collection movie entry")
                title = entry.get("movie", {}).get("title", "Unknown title")
                self.warnings.append(
                    f"{title}: skipped a collection entry due to an unexpected "
                    f"error ({e}).",
                )

        shows_endpoint = f"{self.user_base_url}/collection/shows"
        collected_shows = self._get_paginated_data(shows_endpoint, "collected shows")
        shows_total = len(collected_shows)
        for i, entry in enumerate(collected_shows, start=1):
            import_progress.report(i, shows_total, "Trakt: collection (shows)")
            try:
                self._process_collected_show(entry, trakt_collection)
            except Exception as e:
                logger.exception("Skipping Trakt collection show entry")
                title = entry.get("show", {}).get("title", "Unknown title")
                self.warnings.append(
                    f"{title}: skipped a collection entry due to an unexpected "
                    f"error ({e}).",
                )

    def _process_collected_movie(self, entry, trakt_collection):
        """Process a single Trakt collection movie entry."""
        movie = entry["movie"]
        tmdb_id = self._get_tmdb_id(movie)
        if not tmdb_id:
            return

        metadata = self._get_metadata(MediaTypes.MOVIE.value, tmdb_id, movie["title"])
        if not metadata:
            return

        item = self._get_or_create_item(MediaTypes.MOVIE.value, tmdb_id, metadata)
        trakt_collection.upsert_collection_entry(
            self.user,
            item,
            mode=self.mode,
            collected_at=_parse_watched_at(entry.get("collected_at", "")),
            metadata=entry.get("metadata"),
        )

    def _process_collected_show(self, entry, trakt_collection):
        """Process a single Trakt collection show entry, including its episodes."""
        show = entry["show"]
        tmdb_id = self._get_tmdb_id(show)
        if not tmdb_id:
            return

        tv_metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, show["title"])
        if not tv_metadata:
            return
        tv_item = self._get_or_create_item(MediaTypes.TV.value, tmdb_id, tv_metadata)

        for season_entry in entry.get("seasons", []):
            season_number = season_entry["number"]
            season_metadata = self._get_metadata(
                MediaTypes.SEASON.value,
                tmdb_id,
                show["title"],
                season_number,
            )
            if not season_metadata:
                continue
            season_item = self._get_or_create_item(
                MediaTypes.SEASON.value,
                tmdb_id,
                season_metadata,
                season_number,
            )

            for episode_entry in season_entry.get("episodes", []):
                episode_number = episode_entry["number"]
                episode_exists = any(
                    ep["episode_number"] == episode_number
                    for ep in season_metadata["episodes"]
                )
                if not episode_exists:
                    self.warnings.append(
                        f"{show['title']} S{season_number}E{episode_number}: not "
                        f"found in {Sources.TMDB.label} with ID {tmdb_id}.",
                    )
                    continue

                episode_image = self._get_episode_image(
                    episode_number,
                    season_metadata,
                )
                episode_metadata = {
                    "title": tv_metadata["title"],
                    "original_title": tv_metadata.get("original_title"),
                    "localized_title": tv_metadata.get("localized_title"),
                    "image": episode_image,
                }
                episode_item = self._get_or_create_item(
                    MediaTypes.EPISODE.value,
                    tmdb_id,
                    episode_metadata,
                    season_number,
                    episode_number,
                )
                trakt_collection.upsert_collection_entry(
                    self.user,
                    episode_item,
                    mode=self.mode,
                    collected_at=_parse_watched_at(
                        episode_entry.get("collected_at", ""),
                    ),
                    metadata=episode_entry.get("metadata"),
                )

            trakt_collection.apply_season_and_show_rollup(
                self.user,
                self.mode,
                tv_item,
                season_item,
                tv_metadata,
                season_metadata,
            )

    def _supports_hidden_sections(self):
        """Whether the hidden/progress sections are reachable for this import.

        Overridden by the export importer, which reads them from files.
        """
        return bool(self.refresh_token)

    def process_dropped(self):
        """Collect TMDB IDs of shows the user has dropped (hidden from progress).

        Trakt represents dropped shows as hidden items in the progress_watched
        section.  Requires OAuth — public imports skip this silently.
        """
        if not self._supports_hidden_sections():
            return
        logger.info("Importing dropped shows for user %s", self.username)
        for section in ("progress_watched", "progress_watched_reset"):
            endpoint = f"{self.user_base_url}/hidden/{section}"
            hidden_data = self._get_paginated_data(endpoint)
            for entry in hidden_data:
                if entry.get("type") != "show":
                    continue
                tmdb_id = self._get_tmdb_id(entry["show"])
                if tmdb_id:
                    self.dropped_tmdb_ids.add(tmdb_id)

    def _process_generic_entry(self, entry, entry_type, attribute_updates):
        """Process a generic entry (watchlist, rating, or comment)."""
        if entry["type"] == "movie":
            logger.info(
                "Processing movie %s for %s",
                entry["movie"]["title"],
                entry_type,
            )
            # Only an explicit Completed status implies a watch. Ratings and
            # comments carry no status, so they must not fabricate progress.
            if attribute_updates.get("status") == Status.COMPLETED.value:
                attribute_updates["progress"] = 1

            self._process_media_item(
                entry,
                entry["movie"],
                MediaTypes.MOVIE.value,
                app.models.Movie,
                attribute_updates,
                entry_type=entry_type,
            )
        elif entry["type"] == "show":
            logger.info(
                "Processing show %s for %s",
                entry["show"]["title"],
                entry_type,
            )
            self._process_media_item(
                entry,
                entry["show"],
                MediaTypes.TV.value,
                app.models.TV,
                attribute_updates,
                entry_type=entry_type,
            )
        elif entry["type"] == "season":
            logger.info(
                "Processing season %s S%s for %s",
                entry["show"]["title"],
                entry["season"]["number"],
                entry_type,
            )
            self._process_media_item(
                entry,
                entry["show"],
                MediaTypes.SEASON.value,
                app.models.Season,
                attribute_updates,
                entry["season"]["number"],
                entry_type=entry_type,
            )
        elif entry["type"] == "episode":
            logger.info(
                "Processing episode %s S%sE%s for %s",
                entry["show"]["title"],
                entry["episode"]["season"],
                entry["episode"]["number"],
                entry_type,
            )
            self._process_episode_attribute(
                entry["show"],
                entry["episode"],
                attribute_updates,
            )

    def _process_episode_attribute(self, show_data, episode_data, attribute_updates):
        """Apply attribute updates (e.g. score) to existing Episode instances."""
        tmdb_id = self._get_tmdb_id(show_data)
        if not tmdb_id:
            return

        score = attribute_updates.get("score")
        if score is None:
            return

        season_number = episode_data["season"]
        episode_number = episode_data["number"]

        season_obj = app.models.Season.objects.filter(
            item__media_id=str(tmdb_id),
            item__source=Sources.TMDB.value,
            item__season_number=season_number,
            user=self.user,
        ).first()

        # Fall back to in-memory season created earlier in this same import run
        # (process_history builds objects into bulk_media before bulk_create_media
        # commits them, so the DB lookup above finds nothing on a first import).
        if not season_obj:
            season_key = f"{tmdb_id}:{season_number}"
            season_list = self.media_instances[MediaTypes.SEASON.value].get(season_key)
            if season_list:
                season_obj = season_list[0]

        if not season_obj:
            return

        # Trakt scores are already on the 0-10 storage scale; converting them
        # with scale_score_for_storage doubled them for 5-scale users.
        scaled_score = score

        # Try persisted episodes first (season_obj must have a pk to filter by it)
        if season_obj.pk:
            episodes = app.models.Episode.objects.filter(
                related_season=season_obj,
                item__episode_number=episode_number,
            )
            if episodes.exists():
                episodes.update(score=scaled_score)
                return

        # Fall back to in-memory episode objects from this same import run
        ep_key = f"{tmdb_id}:{season_number}:{episode_number}"
        for ep_obj in self.media_instances[MediaTypes.EPISODE.value].get(ep_key, []):
            ep_obj.score = scaled_score

    def _process_media_item(
        self,
        entry,
        media_data,
        media_type,
        model_class,
        defaults,
        season_number=None,
        *,
        entry_type=None,
    ):
        """Process media items for watchlist, ratings, and comments."""
        tmdb_id = self._get_tmdb_id(media_data)
        if not tmdb_id:
            return

        parent_type = (
            MediaTypes.TV.value if media_type == MediaTypes.SEASON.value else media_type
        )
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            parent_type,
            Sources.TMDB.value,
            tmdb_id,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        metadata = self._get_metadata(
            media_type,
            tmdb_id,
            media_data["title"],
            season_number,
        )
        if not metadata:
            return

        updated_at = parse_datetime(
            entry.get("listed_at")
            or entry.get("rated_at")
            or (entry.get("comment") or entry.get("note") or {}).get("updated_at"),
        )

        # A rating, a comment, or a note says nothing about whether the user
        # tracks the media. When it isn't already tracked from history or the
        # watchlist, store the score without a status rather than inventing one.
        rates_without_tracking = entry_type in {"rating", "comment", "note"}

        if media_type == MediaTypes.SEASON.value:
            tv_obj = self._get_tv_obj(
                tmdb_id,
                media_data,
                updated_at,
                status=None if rates_without_tracking else Status.IN_PROGRESS.value,
            )
            if not tv_obj:
                return
            defaults["related_tv"] = tv_obj

        key = f"{tmdb_id}"
        if media_type == MediaTypes.SEASON.value:
            key = f"{key}:{season_number}"

        item = self._get_or_create_item(media_type, tmdb_id, metadata, season_number)

        if key in self.media_instances[media_type]:
            self._update_instance(media_type, key, defaults)
        else:
            if rates_without_tracking:
                defaults.setdefault("status", None)
            media_obj = model_class(
                item=item,
                user=self.user,
                **defaults,
            )
            if updated_at is not None:
                media_obj._history_date = updated_at
            self.bulk_media[media_type].append(media_obj)
            self.media_instances[media_type][key] = [media_obj]

    def _get_tv_obj(
        self,
        tmdb_id,
        media_data,
        updated_at,
        status=Status.IN_PROGRESS.value,
    ):
        """Get or create a TV object for the given season."""
        tv_metadata = self._get_metadata(
            MediaTypes.TV.value,
            tmdb_id,
            media_data["title"],
        )
        if not tv_metadata:
            return None

        tv_item = self._get_or_create_item(
            MediaTypes.TV.value,
            tmdb_id,
            tv_metadata,
        )

        tv_key = f"{tmdb_id}"

        # Create or get the TV object
        if tv_key in self.media_instances[MediaTypes.TV.value]:
            tv_obj = self.media_instances[MediaTypes.TV.value][tv_key][0]
        else:
            tv_obj = app.models.TV(
                item=tv_item,
                user=self.user,
                status=status,
            )
            if updated_at is not None:
                tv_obj._history_date = updated_at
            self.bulk_media[MediaTypes.TV.value].append(tv_obj)
            self.media_instances[MediaTypes.TV.value][tv_key] = [tv_obj]
        return tv_obj

    def _update_instance(self, media_type, key, defaults):
        """Update the instance with new attributes."""
        for media_obj in self.media_instances[media_type][key]:
            for attr, value in defaults.items():
                setattr(media_obj, attr, value)
