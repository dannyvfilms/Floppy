import logging
from collections import defaultdict
from datetime import datetime

import requests
from django.apps import apps
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import app
import app.providers.mal
from app.models import MediaTypes, Sources, Status
from app.providers import credentials
from integrations import import_progress, mal_sync
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.models import MALAccount
from integrations.webhooks import anime_mappings

logger = logging.getLogger(__name__)

# A status the user chose on purpose; an import never moves a row out of it.
HELD_STATUSES = frozenset({Status.PAUSED.value, Status.DROPPED.value})


def importer(username, user, mode, private=False):
    """Import anime and manga from MyAnimeList."""
    mal_importer = MyAnimeListImporter(username, user, mode, private=private)
    return mal_importer.import_data()


def forward_only_updates(media_type, media, list_status, parse_date):
    """Return the field changes MAL's list entry brings to a row Floppy tracks.

    Import New only ever moves a tracked title forward, the same rule Sync to
    Trackers uses when it pulls higher progress (``mal_sync``): progress goes
    up and never down, status advances (Planning, In Progress, Completed)
    without leaving a Paused or Dropped the user chose, and score, notes and
    dates fill only where Floppy has none. Nothing is returned when MAL is
    equal to or behind Floppy, so a repeat import writes nothing.
    """
    updates = {}
    progress_field = mal_sync.PROGRESS_RESPONSE_FIELDS[media_type][1]
    remote_progress = list_status.get(progress_field)
    local_progress = media.progress or 0
    progress_raised = isinstance(remote_progress, int) and remote_progress > local_progress
    if progress_raised:
        updates["progress"] = remote_progress

    target = mal_sync.MAL_STATUS_TO_FLOPPY[media_type].get(list_status.get("status"))
    status = _forward_status(media.status, target, progress_raised, local_progress)
    if status is not None:
        updates["status"] = status

    score = list_status.get("score")
    if media.score is None and isinstance(score, int) and score > 0:
        updates["score"] = score
        updates["scored_at"] = timezone.now()
    if not media.notes and list_status.get("comments"):
        updates["notes"] = list_status["comments"]
    for field, key in (("start_date", "start_date"), ("end_date", "finish_date")):
        if getattr(media, field) is None and list_status.get(key):
            updates[field] = parse_date(list_status[key])
    return updates


def _forward_status(local, target, progress_raised, local_progress):
    """Return the status to move to, or None to keep the local one."""
    if local is None or local in HELD_STATUSES or target in (None, local):
        return None
    if target == Status.COMPLETED.value:
        return target
    if local == Status.COMPLETED.value:
        return None
    if target == Status.IN_PROGRESS.value:
        return target
    # MAL says Paused or Dropped: take it when MAL is the one that moved, or
    # when Floppy never started the title.
    if target in HELD_STATUSES and (progress_raised or local_progress == 0):
        return target
    if progress_raised and local == Status.PLANNING.value:
        return Status.IN_PROGRESS.value
    return None


class MyAnimeListImporter:
    """Class to handle importing user data from MyAnimeList."""

    def __init__(self, username, user, mode, private=False):
        """Initialize the importer with username, user, and mode.

        Args:
            username (str): MyAnimeList username to import from
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.username = username
        self.user = user
        self.mode = mode
        self.private = private
        self.access_token = None
        if private:
            try:
                mal_account = user.mal_account
            except MALAccount.DoesNotExist as error:
                msg = "Connect your MyAnimeList account before importing its private list."
                raise MediaImportError(msg) from error
            if not mal_account.is_connected:
                msg = "Reconnect your MyAnimeList account before importing its private list."
                raise MediaImportError(msg)
            self.access_token = mal_sync.get_valid_access_token(mal_account)
            self.username = "@me"
        self.warnings = []
        self.base_url = "https://api.myanimelist.net/v2/users"

        # Track existing media for "new" mode
        self.existing_media = helpers.get_existing_media(user)
        self.deleted_media = helpers.get_deleted_media(user)

        # Track media IDs to delete in overwrite mode
        self.to_delete = defaultdict(lambda: defaultdict(set))

        # Track bulk creation lists for each media type
        self.bulk_media = defaultdict(list)

        # Tracked titles Import New brought up to date, and how many it left alone
        self.updated_media = defaultdict(list)
        self.unchanged = 0
        self._tracked_rows = {}

        logger.info(
            "Initialized MyAnimeList importer for user %s with mode %s",
            username,
            mode,
        )

    def import_data(self):
        """Import all user data from MyAnimeList."""
        self._process_media_type(MediaTypes.ANIME.value)
        self._process_media_type(MediaTypes.MANGA.value)

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)
        self._save_updates()

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        created = sum(imported_counts.values())
        updated = sum(len(rows) for rows in self.updated_media.values())
        if updated:
            # Only a run that updated something adds the split, so a run that
            # only creates keeps the message it always had.
            imported_counts["created"] = created
            imported_counts["updated"] = updated
            for media_type, rows in self.updated_media.items():
                imported_counts[media_type] = (
                    imported_counts.get(media_type, 0) + len(rows)
                )
        if self.unchanged:
            imported_counts["unchanged"] = self.unchanged

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages

    def _process_media_type(self, media_type):
        """Process all media of a specific type from MyAnimeList."""
        logger.info("Fetching %s from MyAnimeList", media_type)
        params = {
            "fields": (
                "num_episodes,num_chapters,alternative_titles,"
                "list_status{comments,num_times_rewatched,num_times_reread}"
            ),
            "nsfw": "true",
            "limit": 1000,
        }
        url = f"{self.base_url}/{self.username}/{media_type}list"

        try:
            response = self._get_whole_response(url, params)
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == requests.codes.not_found:
                msg = f"User {self.username} not found."
                raise MediaImportError(msg) from error
            if (
                error.response.status_code == requests.codes.forbidden
                and not self.private
            ):
                logger.warning(
                    "MyAnimeList %s list is private for user %s, skipping.",
                    media_type,
                    self.username,
                )
                self.warnings.append(
                    f"Your MyAnimeList {media_type} list is private and could not "
                    "be imported. Make it public on MyAnimeList to import it.",
                )
                return
            raise

        total = len(response["data"])
        for i, content in enumerate(response["data"], start=1):
            import_progress.report(i, total, f"MyAnimeList ({media_type})")
            try:
                self._process_entry(content, media_type)
            except Exception as error:
                msg = f"Error processing entry: {content}"
                raise MediaImportUnexpectedError(msg) from error

    def _get_whole_response(self, url, params):
        """Fetch whole data from user."""
        headers = (
            {"Authorization": f"Bearer {self.access_token}"}
            if self.private
            else {"X-MAL-CLIENT-ID": credentials.get("mal", "client_id")}
        )

        data = app.providers.services.api_request(
            "MAL",
            "GET",
            url,
            params=params,
            headers=headers,
        )

        while "next" in data["paging"]:
            next_url = data["paging"]["next"]
            next_data = app.providers.services.api_request(
                "MAL",
                "GET",
                next_url,
                params=params,
                headers=headers,
            )
            data["data"].extend(next_data["data"])
            data["paging"] = next_data["paging"]

        return data

    def _process_entry(self, content, media_type):
        """Process a single entry from MyAnimeList."""
        list_status = content["list_status"]
        # MAL uses zero for an unrated entry; Floppy permits a real zero.
        score = list_status["score"] or None
        status = self._get_status(list_status["status"])

        try:
            image_url = content["node"]["main_picture"]["large"]
        except KeyError:
            image_url = settings.IMG_NONE

        # Check if we should process this entry based on mode. skip_existing is
        # off so a deleted title is still skipped, while a title already tracked
        # reaches the forward-only update below instead of being ignored.
        media_id = str(content["node"]["id"])
        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            media_type,
            Sources.MAL.value,
            media_id,
            self.mode,
            deleted_media=self.deleted_media,
            skip_existing=False,
        ):
            return
        if (
            self.mode == "new"
            and media_id in self.existing_media[media_type][Sources.MAL.value]
        ):
            self._update_existing(content, media_type, media_id)
            return

        item, _ = helpers.get_or_create_item_across_buckets(
            user=self.user,
            media_id=str(content["node"]["id"]),
            source=Sources.MAL.value,
            media_type=media_type,
            defaults={
                **app.providers.mal.get_title_fields(content["node"]),
                "image": image_url,
            },
        )

        model = apps.get_model(app_label="app", model_name=media_type)
        updated_at = parse_datetime(list_status.get("updated_at"))

        # Handle completed repeats
        if media_type == MediaTypes.ANIME.value:
            progress = list_status["num_episodes_watched"]
            repeats = list_status["num_times_rewatched"]
            if list_status["is_rewatching"]:
                if repeats == 0:
                    repeats = 1
                status = Status.IN_PROGRESS.value
        else:
            progress = list_status["num_chapters_read"]
            repeats = list_status["num_times_reread"]
            if list_status["is_rereading"]:
                if repeats == 0:
                    repeats = 1
                status = Status.IN_PROGRESS.value

        if repeats >= 1:
            for _ in range(repeats):
                max_progress = content["node"].get("num_episodes") or content[
                    "node"
                ].get(
                    "num_chapters",
                )
                instance = model(
                    item=item,
                    user=self.user,
                    score=score,
                    progress=max_progress or 0,
                    status=Status.COMPLETED.value,
                    start_date=self._parse_mal_date(list_status.get("start_date")),
                    end_date=self._parse_mal_date(list_status.get("finish_date")),
                    notes=list_status["comments"],
                )

                instance._history_date = updated_at
                self.bulk_media[media_type].append(instance)

        # Add current status entry
        instance = model(
            item=item,
            user=self.user,
            score=score,
            progress=progress,
            status=status,
            start_date=self._parse_mal_date(list_status.get("start_date")),
            end_date=self._parse_mal_date(list_status.get("finish_date")),
            notes=list_status["comments"],
        )
        instance._history_date = updated_at
        self.bulk_media[media_type].append(instance)

        self._sync_to_movie_entry(
            content["node"]["id"],
            media_type,
            list_status,
            status,
            updated_at,
        )

    def _update_existing(self, content, media_type, media_id):
        """Bring a tracked title up to MAL's progress and status, forward only."""
        media = self._tracked_row(media_type, media_id)
        updates = forward_only_updates(
            media_type,
            media,
            content["list_status"],
            self._parse_mal_date,
        )
        if not updates:
            self.unchanged += 1
            return
        for field, value in updates.items():
            setattr(media, field, value)
        updated_at = parse_datetime(content["list_status"].get("updated_at") or "")
        if updated_at is not None:
            media._history_date = updated_at
        media._update_fields = tuple(updates)
        self.updated_media[media_type].append(media)

    def _tracked_row(self, media_type, media_id):
        """Return the row that speaks for a tracked title.

        A rewatch is its own row, so the title can have several; the one with
        the most progress is the entry MAL describes, and a rewatch in flight
        is left as it is.
        """
        if media_type not in self._tracked_rows:
            model = apps.get_model(app_label="app", model_name=media_type)
            best = {}
            for row in model.objects.filter(
                user=self.user,
                item__source=Sources.MAL.value,
            ).select_related("item"):
                current = best.get(row.item.media_id)
                if current is None or (row.progress or 0) > (current.progress or 0):
                    best[row.item.media_id] = row
            self._tracked_rows[media_type] = best
        return self._tracked_rows[media_type].get(media_id) or self.existing_media[
            media_type
        ][Sources.MAL.value][media_id]

    def _save_updates(self):
        """Write the updates, one batch per media type and set of fields."""
        for media_type, rows in self.updated_media.items():
            model = apps.get_model(app_label="app", model_name=media_type)
            by_fields = defaultdict(list)
            for row in rows:
                by_fields[row._update_fields].append(row)
            for fields, batch in by_fields.items():
                helpers.bulk_update_media(
                    batch,
                    model,
                    fields,
                    self.user,
                    change_reason="MyAnimeList import",
                )

    def _sync_to_movie_entry(self, mal_id, media_type, list_status, status, updated_at):
        """If this MAL anime maps to a TMDB movie, sync data to that Movie entry."""
        if media_type != MediaTypes.ANIME.value:
            return
        # Fast path: skip if the user has no Movie entries to sync to.
        if not self.existing_media[MediaTypes.MOVIE.value]:
            return

        mapping_data = anime_mappings.fetch_mapping_data()
        tmdb_movie_id = anime_mappings.get_tmdb_movie_id_from_mal_id(
            mapping_data, str(mal_id)
        )
        if not tmdb_movie_id:
            return

        tmdb_movie_id_str = str(tmdb_movie_id)
        source = Sources.TMDB.value

        if tmdb_movie_id_str not in self.existing_media[MediaTypes.MOVIE.value][source]:
            return

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.MOVIE.value,
            source,
            tmdb_movie_id_str,
            self.mode,
            deleted_media=self.deleted_media,
        ):
            return

        movie_media = self.existing_media[MediaTypes.MOVIE.value][source]
        movie_item = movie_media[tmdb_movie_id_str].item
        movie_progress = 1 if status == Status.COMPLETED.value else 0

        movie_instance = app.models.Movie(
            item=movie_item,
            user=self.user,
            score=list_status["score"] or None,
            progress=movie_progress,
            status=status,
            start_date=self._parse_mal_date(list_status.get("start_date")),
            end_date=self._parse_mal_date(list_status.get("finish_date")),
            notes=list_status["comments"],
        )
        movie_instance._history_date = updated_at
        self.bulk_media[MediaTypes.MOVIE.value].append(movie_instance)
        logger.info(
            "Synced MAL anime %s to Movie entry (TMDB ID: %s)",
            mal_id,
            tmdb_movie_id_str,
        )

    def _parse_mal_date(self, date_str):
        """Parse MAL date string (YYYY-MM-YY) into datetime object."""
        if date_str is None:
            return None

        year_only_len = 4  # YYYY
        year_month_len = 7  # YYYY-MM

        if len(date_str) == year_only_len and date_str.isdigit():
            date_str = f"{date_str}-01-01"  # Default to January 1st

        elif (
            len(date_str) == year_month_len
            and date_str[:4].isdigit()
            and date_str[5:7].isdigit()
        ):
            date_str = f"{date_str}-01"  # Default to first day of the month

        return datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=0,
            minute=0,
            second=0,
            tzinfo=timezone.get_current_timezone(),
        )

    def _get_status(self, status):
        """Convert the status from MyAnimeList to the status used in the app."""
        status_mapping = {
            "completed": Status.COMPLETED.value,
            "reading": Status.IN_PROGRESS.value,
            "watching": Status.IN_PROGRESS.value,
            "plan_to_watch": Status.PLANNING.value,
            "plan_to_read": Status.PLANNING.value,
            "on_hold": Status.PAUSED.value,
            "dropped": Status.DROPPED.value,
        }
        return status_mapping[status]
