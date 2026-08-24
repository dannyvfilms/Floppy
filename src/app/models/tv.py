import logging
from datetime import UTC

from django.conf import settings
from django.core.validators import (
    DecimalValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.functional import cached_property
from model_utils import FieldTracker
from requests import RequestException
from simple_history.models import HistoricalRecords
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

import events
from app import cache_utils, providers
from app.models.choices import MediaTypes, Sources, Status
from app.models.item import Item
from app.models.media import Media

logger = logging.getLogger(__name__)

# Sentinel distinguishing "no explicit end_date supplied" (fall back to the
# user's resolve_watch_date behavior) from an explicit value, including None
# (blank date deliberately chosen on the completion form).
_UNSET_END_DATE = object()
MIN_VALID_RELEASE_YEAR = 1900


class RewatchAlreadyCompleteError(Exception):
    """Raised when a rewatch's start date leaves nothing left to rewatch."""


def _runtime_minutes(value):
    """Return a positive runtime in minutes, or None.

    Providers disagree on the type: TMDB sends an int, manual items store the
    string the custom-metadata form was filled in with.
    """
    try:
        minutes = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return minutes if minutes > 0 else None


class TV(Media):
    """Model for TV shows."""

    tracker = FieldTracker()

    class Meta:
        """Meta options for the model."""

        ordering = ["user", "item"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                name="%(app_label)s_%(class)s_unique_item_user",
            ),
        ]

    @tracker  # postpone field reset until after the save
    def save(self, *args, **kwargs):
        """Save the media instance."""
        is_create = self._state.adding
        super(Media, self).save(*args, **kwargs)

        # A show created directly as COMPLETED (rather than transitioned into it)
        # must still fan out completion to its seasons/episodes.
        completed_on_create = is_create and self.status == Status.COMPLETED.value
        if (
            not is_create and self.tracker.has_changed("status")
        ) or completed_on_create:
            if self.status == Status.COMPLETED.value:
                try:
                    self._completed()
                except (
                    providers.services.ProviderAPIError,
                    RequestException,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    logger.warning(
                        "Skipping completion fan-out due to missing metadata"
                        " for %s: %s",
                        self.item.media_id,
                        error,
                    )

            elif self.status == Status.DROPPED.value:
                self._mark_in_progress_seasons_as_dropped()

            elif (
                self.status == Status.IN_PROGRESS.value
                and not self.seasons.filter(status=Status.IN_PROGRESS.value).exists()
            ):
                self._start_next_available_season()

            self.item.fetch_releases(delay=True)
        elif (
            not is_create
            and self.status == Status.IN_PROGRESS.value
            and not self.seasons.filter(status=Status.IN_PROGRESS.value).exists()
        ):
            # Keep TV+Season state aligned even when status was already IN_PROGRESS.
            self._start_next_available_season()

        cache_utils.clear_time_left_cache_for_user(self.user_id)
        cache_utils.clear_media_list_cache_for_user(self.user_id)

    @cached_property
    def progress(self):
        """Return the total episodes watched for the TV show, excluding dropped seasons."""
        return sum(
            season.progress
            for season in self.seasons.all()
            if season.item.season_number != 0 and season.status != Status.DROPPED.value
        )

    @cached_property
    def completed_episode_count(self):
        """Return the count of distinct watched episodes, excluding dropped seasons."""
        return sum(
            season.completed_episode_count
            for season in self.seasons.all()
            if season.item.season_number != 0 and season.status != Status.DROPPED.value
        )

    def _plays_sort_value(self):
        """Return completed-episode count (not furthest position) for plays/time-watched UI."""
        aggregated_progress = getattr(self, "aggregated_progress", None)
        if aggregated_progress is not None:
            return aggregated_progress
        return self.completed_episode_count

    @property
    def is_rewatching(self):
        """Return whether any season of the show is in a rewatch pass."""
        return any(
            season.rewatch_started_at is not None
            for season in self.seasons.all()
            if season.status != Status.DROPPED.value
        )

    @property
    def rewatch_started_at(self):
        """Return when this show's rewatch began, or None.

        TV has no rewatch_started_at column of its own — the pass lives on
        each season — so this reads the earliest open one. `start_rewatch`
        opens every season together, but a season skipped for already
        being covered (or one whose pass was started separately) can leave
        them different; the earliest is the more honest "since" to show.
        """
        dates = [
            season.rewatch_started_at
            for season in self.seasons.all()
            if season.rewatch_started_at is not None
        ]
        return min(dates) if dates else None

    def start_rewatch(self, started_at=None):
        """Open a rewatch pass on every season with something left to rewatch.

        A season already fully covered by plays at or after `started_at`
        is skipped rather than opened and immediately closed again —
        that's more confusing than just leaving it alone. A season with
        an already-open pass is left untouched too, so a duplicate
        submission or retry can't silently push its cutoff later and
        strand plays logged against the original one as pre-cutoff
        history. Raises RewatchAlreadyCompleteError only if every season
        would be skipped, so the caller can tell the user nothing would
        happen. Returns the seasons that *were* skipped (empty if none)
        so a caller can still tell the user about a partial skip, since
        that succeeds silently otherwise.
        """
        from app.models.media import BasicMedia  # avoid a module-load cycle

        is_explicit_start = started_at is not None
        started_at = started_at or timezone.now()
        all_seasons = [
            season
            for season in self.seasons.filter(item__season_number__gt=0)
            if season.status != Status.DROPPED.value
        ]
        if not all_seasons:
            no_seasons_msg = "This show has no seasons to rewatch."
            raise RewatchAlreadyCompleteError(no_seasons_msg)

        seasons = [season for season in all_seasons if season.rewatch_started_at is None]
        if not seasons:
            already_open_msg = "Every season is already being rewatched."
            raise RewatchAlreadyCompleteError(already_open_msg)
        BasicMedia.objects.annotate_max_progress(seasons, MediaTypes.SEASON.value)

        skipped = [
            season
            for season in seasons
            if is_explicit_start
            and season._would_be_immediately_complete(
                started_at,
                getattr(season, "max_progress", None),
            )
        ]
        openable = [season for season in seasons if season not in skipped]
        if not openable:
            all_covered_msg = "Every season is already fully watched from that date."
            raise RewatchAlreadyCompleteError(all_covered_msg)

        for season in openable:
            season.rewatch_started_at = started_at
            season.status = Status.IN_PROGRESS.value
            season._invalidate_episode_stats()  # same-module sibling
        bulk_update_with_history(
            openable,
            Season,
            fields=["rewatch_started_at", "status"],
        )

        if self.status != Status.IN_PROGRESS.value:
            self.status = Status.IN_PROGRESS.value
            bulk_update_with_history([self], TV, fields=["status"])

        return skipped

    def stop_rewatch(self, max_progress=None):
        """Close every open rewatch pass on the show's seasons.

        `max_progress` is ignored: seasons can have different episode
        counts, so each resolves its own via `Season.stop_rewatch`. Also
        reconciles the show's own status against where its seasons land —
        ending a pass before it finished can fall back to Completed (or
        stay In Progress) independently of what the show currently reads
        as, same as `start_rewatch`.
        """
        seasons = [
            season
            for season in self.seasons.filter(item__season_number__gt=0)
            if season.status != Status.DROPPED.value
        ]
        for season in seasons:
            season.stop_rewatch()

        if not seasons:
            return
        desired_status = (
            Status.COMPLETED.value
            if all(season.status == Status.COMPLETED.value for season in seasons)
            else Status.IN_PROGRESS.value
        )
        if self.status != desired_status:
            self.status = desired_status
            bulk_update_with_history([self], TV, fields=["status"])

    @property
    def progress_percentage(self):
        """Return percent of the show actually watched (0-100), or None.

        Unlike `progress` (furthest episode number touched, kept for #327's
        skip-tolerant behavior), this reflects distinct completed episodes
        against the show's total, for progress-bar style displays.
        """
        max_progress_value = getattr(self, "max_progress", None)
        try:
            max_progress_value = int(max_progress_value)
        except (TypeError, ValueError):
            return None
        if max_progress_value <= 0:
            return None
        percentage = round(self.completed_episode_count / max_progress_value * 100)
        return max(0, min(percentage, 100))

    @cached_property
    def last_watched(self):
        """Return the latest watched episode in SxxExx format."""
        watched_episodes = [
            {
                "season": season.item.season_number,
                "episode": episode.item.episode_number,
                "end_date": episode.end_date,
            }
            for season in self.seasons.all()
            if hasattr(season, "episodes") and season.item.season_number != 0
            for episode in season.episodes.all()
            if episode.end_date is not None
        ]

        if not watched_episodes:
            return ""

        latest_episode = max(
            watched_episodes,
            key=lambda x: (x["end_date"], x["season"], x["episode"]),
        )

        return f"S{latest_episode['season']:02d}E{latest_episode['episode']:02d}"

    @cached_property
    def progressed_at(self):
        """Return the date when the last attached episode was watched."""
        dates = self._season_activity_dates("progressed_at", include_specials=True)
        return max(dates) if dates else None

    @cached_property
    def start_date(self):
        """Return the first watched date, preferring main seasons over specials."""
        dates = self._season_activity_dates("start_date")
        if dates:
            return min(dates)
        special_dates = self._season_activity_dates("start_date", include_specials=True)
        if special_dates:
            return min(special_dates)
        if self.status == Status.IN_PROGRESS.value:
            return self.created_at
        return None

    @cached_property
    def end_date(self):
        """Return the last watched date across main seasons and specials."""
        dates = self._season_activity_dates("end_date", include_specials=True)
        return max(dates) if dates else None

    def _get_quick_update_season(self, operation):
        """Return the season that should handle quick TV progress updates."""
        seasons = sorted(
            (season for season in self.seasons.all() if season.item.season_number != 0),
            key=lambda season: season.item.season_number,
        )

        next_episode_target = self.next_episode_target()
        if next_episode_target is not None:
            return next_episode_target[0]

        for season in seasons:
            if season.status == Status.IN_PROGRESS.value:
                return season

        if operation == "increase" and self._start_next_available_season():
            return (
                self.seasons.filter(
                    item__season_number__gt=0,
                    status=Status.IN_PROGRESS.value,
                )
                .order_by("item__season_number")
                .first()
            )

        if operation == "decrease":
            for season in reversed(seasons):
                if season.progress > 0:
                    return season

        return None

    def next_episode_target(self):
        """Return the first tracked season and episode that can be watched next."""
        seasons = sorted(
            (season for season in self.seasons.all() if season.item.season_number != 0),
            key=lambda season: season.item.season_number,
        )
        has_caught_up_season = False
        planning_continuation = None

        for season in seasons:
            if season.status in {Status.DROPPED.value, Status.PAUSED.value}:
                continue

            next_episode_number = season.next_episode_number()
            if next_episode_number is None:
                has_caught_up_season = (
                    season.status == Status.COMPLETED.value or season.progress > 0
                )
                continue

            if season.progress > 0 or season.status == Status.IN_PROGRESS.value:
                return season, next_episode_number

            if (
                has_caught_up_season
                and season.status == Status.PLANNING.value
                and planning_continuation is None
            ):
                planning_continuation = season, next_episode_number

            has_caught_up_season = False

        return planning_continuation

    def increase_progress(self, watch_operation_id=None):
        """Increase TV progress by advancing the active season."""
        if watch_operation_id:
            from app import fork_services_episode

            operation_id = fork_services_episode.normalize_watch_operation_id(
                watch_operation_id,
            )
            claimed = (
                Episode.objects.filter(watch_operation_id=operation_id)
                .select_related("related_season", "item")
                .first()
            )
            if claimed is not None:
                if claimed.related_season.related_tv_id != self.id:
                    raise fork_services_episode.EpisodeWatchConflictError
                return fork_services_episode.resolve_episode_watch_replay(
                    claimed,
                    user_id=self.user_id,
                )
        season = self._get_quick_update_season("increase")
        if season is None:
            logger.info("No season available to increase progress for %s", self)
            return None
        return season.increase_progress(watch_operation_id=watch_operation_id)

    def decrease_progress(self):
        """Decrease TV progress by rewinding the relevant season."""
        season = self._get_quick_update_season("decrease")
        if season is None:
            logger.info("No season available to decrease progress for %s", self)
            return
        season.decrease_progress()

    def _season_activity_dates(self, attr_name, include_specials=False):
        """Collect season activity dates, optionally including specials."""
        dates = []
        for season in self.seasons.all():
            season_number = getattr(season.item, "season_number", None)
            if not include_specials and season_number == 0:
                continue

            date_value = getattr(season, attr_name, None)
            if date_value is not None:
                dates.append(date_value)

        return dates

    def _completed(self):
        """Create remaining seasons and episodes for a TV show."""
        tv_metadata = providers.services.get_media_metadata(
            self.item.media_type,
            self.item.media_id,
            self.item.source,
        )
        max_progress = tv_metadata["max_progress"]

        if not max_progress or self.progress > max_progress:
            return

        seasons_to_create = []
        seasons_to_update = []
        episodes_to_create = []

        season_numbers = [
            season["season_number"]
            for season in tv_metadata["related"]["seasons"]
            if season["season_number"] != 0
        ]
        tv_with_seasons_metadata = providers.services.get_media_metadata(
            "tv_with_seasons",
            self.item.media_id,
            self.item.source,
            season_numbers,
        )
        for season_number in season_numbers:
            season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]

            # Use season poster if available, otherwise fallback to TV show poster
            season_image = season_metadata.get("image") or self.item.image

            item, _ = Item.objects.get_or_create(
                media_id=self.item.media_id,
                source=self.item.source,
                media_type=MediaTypes.SEASON.value,
                library_media_type=(
                    MediaTypes.ANIME.value
                    if self.item.library_media_type == MediaTypes.ANIME.value
                    else MediaTypes.SEASON.value
                ),
                season_number=season_number,
                defaults={
                    **Item.title_fields_from_metadata(
                        season_metadata,
                        fallback_title=self.item.title,
                    ),
                    "image": season_image,
                },
            )
            try:
                season_instance = Season.objects.get(
                    item=item,
                    user=self.user,
                )

                if season_instance.status != Status.COMPLETED.value:
                    season_instance.status = Status.COMPLETED.value
                    seasons_to_update.append(season_instance)

            except Season.DoesNotExist:
                seasons_to_create.append(
                    Season(
                        item=item,
                        score=None,
                        status=Status.COMPLETED.value,
                        notes="",
                        related_tv=self,
                        user=self.user,
                    ),
                )

        bulk_create_with_history(seasons_to_create, Season)
        bulk_update_with_history(seasons_to_update, Season, ["status"])

        for season_instance in seasons_to_create + seasons_to_update:
            season_metadata = tv_with_seasons_metadata[
                f"season/{season_instance.item.season_number}"
            ]
            episodes_to_create.extend(
                season_instance.get_remaining_eps(
                    season_metadata,
                    end_date=getattr(self, "_pending_end_date", _UNSET_END_DATE),
                ),
            )
        bulk_create_with_history(episodes_to_create, Episode)

    def _mark_in_progress_seasons_as_dropped(self):
        """Mark all in-progress seasons as dropped."""
        in_progress_seasons = list(
            self.seasons.filter(status=Status.IN_PROGRESS.value),
        )

        for season in in_progress_seasons:
            season.status = Status.DROPPED.value

        if in_progress_seasons:
            bulk_update_with_history(
                in_progress_seasons,
                Season,
                fields=["status"],
            )

    def _start_next_available_season(
        self,
        min_season_number=0,
    ):
        """Find the next available season to watch and set it to in-progress."""
        min_season_number = int(min_season_number or 0)

        all_seasons = self.seasons.filter(
            item__season_number__gt=min_season_number,
        ).order_by("item__season_number")

        next_unwatched_season = all_seasons.exclude(
            status__in=[Status.COMPLETED.value],
        ).first()

        season_started = False

        if not next_unwatched_season:
            # If all existing seasons are watched, get the next available season
            tv_metadata = providers.services.get_media_metadata(
                self.item.media_type,
                self.item.media_id,
                self.item.source,
            )
            related_seasons = tv_metadata.get("related", {}).get("seasons", [])

            existing_season_numbers = set(
                all_seasons.values_list("item__season_number", flat=True),
            )

            for season_data in related_seasons:
                season_number = season_data["season_number"]
                if (
                    season_number > min_season_number
                    and season_number not in existing_season_numbers
                ):
                    # Use season poster if available, otherwise fallback to TV show poster
                    season_image = season_data.get("image") or self.item.image

                    item, _ = Item.objects.get_or_create(
                        media_id=self.item.media_id,
                        source=self.item.source,
                        media_type=MediaTypes.SEASON.value,
                        library_media_type=(
                            MediaTypes.ANIME.value
                            if self.item.library_media_type == MediaTypes.ANIME.value
                            else MediaTypes.SEASON.value
                        ),
                        season_number=season_data["season_number"],
                        defaults={
                            **Item.title_fields_from_metadata(
                                season_data,
                                fallback_title=self.item.title,
                            ),
                            "image": season_image,
                        },
                    )

                    next_unwatched_season = Season(
                        item=item,
                        user=self.user,
                        related_tv=self,
                        status=Status.IN_PROGRESS.value,
                    )
                    bulk_create_with_history([next_unwatched_season], Season)
                    season_started = True
                    break

        elif next_unwatched_season.status != Status.IN_PROGRESS.value:
            next_unwatched_season.status = Status.IN_PROGRESS.value
            bulk_update_with_history(
                [next_unwatched_season],
                Season,
                fields=["status"],
            )
            season_started = True
        else:
            season_started = True

        if season_started and self.status != Status.IN_PROGRESS.value:
            self.status = Status.IN_PROGRESS.value
            bulk_update_with_history(
                [self],
                TV,
                fields=["status"],
            )

        return season_started

    def _handle_completed_season(
        self,
        completed_season_number,
    ):
        """Start the next season, or complete the TV show if no seasons remain."""
        if self._start_next_available_season(
            completed_season_number,
        ):
            return

        incomplete_seasons_exist = (
            self.seasons.filter(
                item__season_number__gt=0,
            )
            .exclude(
                status=Status.COMPLETED.value,
            )
            .exists()
        )

        if not incomplete_seasons_exist and self.status != Status.COMPLETED.value:
            self.status = Status.COMPLETED.value
            bulk_update_with_history(
                [self],
                TV,
                fields=["status"],
            )


class Season(Media):
    """Model for seasons of TV shows."""

    related_tv = models.ForeignKey(
        TV,
        on_delete=models.CASCADE,
        related_name="seasons",
    )
    rewatch_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When the current rewatch began. Plays before it are kept as"
            " history but don't count towards the current pass."
        ),
    )

    tracker = FieldTracker()

    class Meta:
        """Limit the uniqueness of seasons.

        Only one season per media can have the same season number.
        """

        constraints = [
            models.UniqueConstraint(
                fields=["related_tv", "item"],
                name="%(app_label)s_season_unique_tv_item",
            ),
        ]

    def __str__(self):
        """Return the title of the media and season number."""
        return f"{self.item.title} S{self.item.season_number}"

    def available_episode_numbers(self):
        """Return released episode numbers known by the local calendar."""
        prefetched_events = getattr(self.item, "prefetched_events", None)
        if prefetched_events is None:
            event_rows = events.models.Event.objects.filter(
                item=self.item,
                content_number__isnull=False,
            ).only("content_number", "datetime")
        else:
            event_rows = prefetched_events

        now = timezone.now()
        episode_numbers = set()
        for event in event_rows:
            episode_number = getattr(event, "content_number", None)
            event_datetime = getattr(event, "datetime", None)
            if episode_number is None or event_datetime is None:
                continue
            if event_datetime.year < MIN_VALID_RELEASE_YEAR or event_datetime > now:
                continue
            try:
                episode_numbers.add(int(episode_number))
            except (TypeError, ValueError):
                continue

        return sorted(episode_numbers)

    def next_episode_number(self, episode_numbers=None):
        """Return the next released episode, or none when the season is caught up."""
        if episode_numbers is None:
            episode_numbers = self.available_episode_numbers()

        if not episode_numbers:
            max_progress = getattr(self, "max_progress", None)
            try:
                max_progress = int(max_progress)
            except (TypeError, ValueError):
                max_progress = None
            if max_progress and max_progress > 0:
                episode_numbers = range(1, max_progress + 1)

        return providers.tmdb.find_next_episode(
            self.progress,
            [{"episode_number": number} for number in episode_numbers],
        )

    @tracker  # postpone field reset until after the save
    def save(self, *args, **kwargs):
        """Save the media instance."""
        # if related_tv is not set
        if self.related_tv_id is None:
            self.related_tv = self.get_tv()

        is_create = self._state.adding
        super(Media, self).save(*args, **kwargs)

        # A season created directly as COMPLETED (rather than transitioned into
        # it) must still create the remaining episode watch records.
        completed_on_create = is_create and self.status == Status.COMPLETED.value
        if (
            not is_create and self.tracker.has_changed("status")
        ) or completed_on_create:
            if self.status == Status.COMPLETED.value:
                try:
                    season_metadata = providers.services.get_media_metadata(
                        MediaTypes.SEASON.value,
                        self.item.media_id,
                        self.item.source,
                        [self.item.season_number],
                    )
                    episodes_to_create = self.get_remaining_eps(
                        season_metadata,
                        end_date=getattr(self, "_pending_end_date", _UNSET_END_DATE),
                    )
                    if episodes_to_create:
                        bulk_create_with_history(
                            episodes_to_create,
                            Episode,
                        )

                    # Completing the season ends any pass it was in.
                    if self.rewatch_started_at is not None:
                        self.rewatch_started_at = None
                        self._invalidate_episode_stats()
                        bulk_update_with_history(
                            [self],
                            Season,
                            fields=["rewatch_started_at"],
                        )

                    self.related_tv._handle_completed_season(
                        self.item.season_number,
                    )
                except (
                    providers.services.ProviderAPIError,
                    RequestException,
                    KeyError,
                    TypeError,
                    ValueError,
                ) as error:
                    logger.warning(
                        "Skipping season completion fan-out due to missing"
                        " metadata for %s S%s: %s",
                        self.item.media_id,
                        self.item.season_number,
                        error,
                    )

            elif (
                self.status == Status.DROPPED.value
                and self.related_tv.status != Status.DROPPED.value
            ):
                self.related_tv.status = Status.DROPPED.value
                bulk_update_with_history(
                    [self.related_tv],
                    TV,
                    fields=["status"],
                )

            elif (
                self.status == Status.IN_PROGRESS.value
                and self.related_tv.status != Status.IN_PROGRESS.value
            ):
                self.related_tv.status = Status.IN_PROGRESS.value
                bulk_update_with_history(
                    [self.related_tv],
                    TV,
                    fields=["status"],
                )

            self.item.fetch_releases(delay=True)

        cache_utils.clear_time_left_cache_for_user(self.user_id)
        cache_utils.clear_media_list_cache_for_user(self.user_id)

    @property
    def progress(self):
        """Return the current episode number of the season.

        For rewatching: only considers it a rewatch if a strict majority of watched
        episodes have reached the same repeat count. This tolerates a minority of
        skipped/out-of-order episodes during a genuine rewatch pass (issue #327),
        while still ignoring a single errant repeat during normal watching.
        """
        stats = self._get_episode_stats()
        episode_counts = stats["episode_counts"]
        if not episode_counts:
            return 0

        if self.status == Status.IN_PROGRESS.value:
            total_episodes = len(episode_counts)
            majority_threshold = total_episodes / 2

            # Find the highest repeat level reached by a strict majority of
            # episodes. Vote counts are monotonically non-increasing as the
            # level rises, so the last level clearing the bar is the deepest
            # confirmed rewatch pass.
            best_level = 1
            for level in range(2, max(episode_counts.values()) + 1):
                votes = sum(1 for count in episode_counts.values() if count >= level)
                if votes > majority_threshold:
                    best_level = level

            if best_level > 1:
                # Report the highest episode number that reached this level,
                # tolerating any episodes that didn't (the minority gaps).
                qualifying = [
                    ep_num
                    for ep_num, count in episode_counts.items()
                    if count >= best_level
                ]
                return max(qualifying)

        # Otherwise, use the maximum episode number watched (at least once)
        # This handles normal watching and errant repeats
        return stats["max_episode_number"]

    @property
    def completed_episode_count(self):
        """Return the number of unique episodes with a completed play."""
        stats = self._get_episode_stats()
        return len(stats["completed_episode_numbers"])

    def _plays_sort_value(self):
        """Return completed-episode count (not furthest position) for plays/time-watched UI."""
        aggregated_progress = getattr(self, "aggregated_progress", None)
        if aggregated_progress is not None:
            return aggregated_progress
        return self.completed_episode_count

    @property
    def progress_percentage(self):
        """Return percent of the season actually watched (0-100), or None.

        Unlike `progress` (furthest episode number touched, kept for #327's
        skip-tolerant behavior), this reflects distinct completed episodes
        against the season's total, for progress-bar style displays.
        """
        max_progress_value = getattr(self, "max_progress", None)
        try:
            max_progress_value = int(max_progress_value)
        except (TypeError, ValueError):
            return None
        if max_progress_value <= 0:
            return None
        percentage = round(self.completed_episode_count / max_progress_value * 100)
        return max(0, min(percentage, 100))

    def _is_fully_watched(self, max_progress=None):
        """Return whether the current pass covers every episode of the season."""
        max_progress_value = max_progress
        if max_progress_value is None:
            max_progress_value = getattr(self, "max_progress", None)
        try:
            max_progress_value = int(max_progress_value)
        except (TypeError, ValueError):
            return False
        return (
            max_progress_value > 0
            and self.completed_episode_count >= max_progress_value
        )

    def _would_be_immediately_complete(self, started_at, max_progress=None):
        """Return whether opening a pass from started_at leaves nothing to rewatch.

        Checked without persisting: swaps in the candidate start, asks
        `_is_fully_watched` (which reads plays through the pass window it
        implies), then puts the season's actual state back.
        """
        original_started_at = self.rewatch_started_at
        self.rewatch_started_at = started_at
        self._invalidate_episode_stats()
        try:
            return self._is_fully_watched(max_progress)
        finally:
            self.rewatch_started_at = original_started_at
            self._invalidate_episode_stats()

    def derived_status_from_episode_progress(self, max_progress=None):
        """Return the effective season status from local episode history."""
        if self.status in {Status.DROPPED.value, Status.PAUSED.value}:
            return self.status

        completed_episode_count = self.completed_episode_count
        progress_value = self.progress

        if self._is_fully_watched(max_progress):
            return Status.COMPLETED.value
        if progress_value > 0 or completed_episode_count > 0:
            return Status.IN_PROGRESS.value
        if self.status == Status.PLANNING.value:
            return Status.PLANNING.value
        return self.status

    def promote_to_completed_if_fully_watched(self, max_progress=None):
        """Persist a completed season when local episode history proves it."""
        desired_status = self.derived_status_from_episode_progress(
            max_progress=max_progress,
        )
        if desired_status != Status.COMPLETED.value or self.status in {
            Status.COMPLETED.value,
            Status.IN_PROGRESS.value,
        }:
            return False

        self.status = Status.COMPLETED.value
        update_fields = ["status"]
        if self.rewatch_started_at is not None:
            self.rewatch_started_at = None
            self._invalidate_episode_stats()
            update_fields.append("rewatch_started_at")
        bulk_update_with_history([self], Season, fields=update_fields)
        self.related_tv._handle_completed_season(self.item.season_number)
        return True

    @property
    def is_rewatching(self):
        """Return whether the season is in an open rewatch pass."""
        return self.rewatch_started_at is not None

    def refresh_from_db(self, *args, **kwargs):
        """Drop cached episode stats so a reload can't serve the old window."""
        super().refresh_from_db(*args, **kwargs)
        self._invalidate_episode_stats()

    @property
    def pass_started_on(self):
        """Return the start of the day the current pass began, or None.

        Watch dates are often date-only and land at midnight, so a pass started
        at 09:00 has to accept a play dated that same morning. Comparing against
        the day boundary does that without letting an old play count just
        because its row happens to have been written during the pass.
        """
        if self.rewatch_started_at is None:
            return None
        return timezone.localtime(self.rewatch_started_at).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    def play_counts_for_pass(self, episode):
        """Return whether a play belongs to the season's current pass."""
        if self.rewatch_started_at is None:
            return True
        played_at = episode.end_date or episode.created_at
        if played_at is None:
            return True
        rewatch_started = self.rewatch_started_at
        if timezone.is_naive(played_at):
            played_at = timezone.make_aware(played_at, UTC)
        if timezone.is_naive(rewatch_started):
            rewatch_started = timezone.make_aware(rewatch_started, UTC)
        if played_at >= rewatch_started:
            return True
        started_on = self.pass_started_on
        if started_on is None:
            return False
        if timezone.is_naive(started_on):
            started_on = timezone.make_aware(started_on, UTC)
        if played_at < started_on:
            return False
        # Date-only plays are stored at local midnight, so compare in the same
        # local zone `pass_started_on` was built in. Reading the raw UTC value
        # here would see a non-UTC deployment's local midnight as the previous
        # day's 22:00Z and drop the play from its own pass.
        local_played_at = timezone.localtime(played_at)
        return (
            local_played_at.hour == 0
            and local_played_at.minute == 0
            and local_played_at.second == 0
            and local_played_at.microsecond == 0
        )

    def _invalidate_episode_stats(self):
        """Drop cached episode stats after the pass or its plays changed."""
        if hasattr(self, "_episode_stats_cache"):
            del self._episode_stats_cache

    def start_rewatch(self, started_at=None, max_progress=None):
        """Begin a new pass, keeping every existing play as history.

        A no-op if a pass is already open, so a duplicate submission or
        retry can't silently push the cutoff later and strand plays
        logged against the original one as pre-cutoff history. Raises
        RewatchAlreadyCompleteError if the plays already logged at or
        after `started_at` already cover the season — opening a pass
        that would immediately close itself again is more confusing than
        just refusing it. Looks up its own episode count when
        `max_progress` isn't supplied — see `stop_rewatch` for why that
        can't be a shared value.
        """
        if self.rewatch_started_at is not None:
            return
        is_explicit_start = started_at is not None
        started_at = started_at or timezone.now()
        if max_progress is None:
            from app.models.media import BasicMedia  # avoid a module-load cycle

            BasicMedia.objects.annotate_max_progress([self], MediaTypes.SEASON.value)
            max_progress = getattr(self, "max_progress", None)

        if is_explicit_start and self._would_be_immediately_complete(started_at, max_progress):
            already_complete_msg = "Every episode is already watched from that date."
            raise RewatchAlreadyCompleteError(already_complete_msg)

        self.rewatch_started_at = started_at
        self.status = Status.IN_PROGRESS.value
        self._invalidate_episode_stats()
        bulk_update_with_history(
            [self],
            Season,
            fields=["rewatch_started_at", "status"],
        )

    def stop_rewatch(self, max_progress=None):
        """Abandon the current pass; the full history decides the status again.

        Looks up its own episode count when `max_progress` isn't supplied,
        so a caller resolving several seasons at once (e.g.
        `TV.stop_rewatch`) doesn't have to share one value across seasons
        that can have different episode counts.
        """
        if self.rewatch_started_at is None:
            return
        if max_progress is None:
            from app.models.media import BasicMedia  # avoid a module-load cycle

            BasicMedia.objects.annotate_max_progress([self], MediaTypes.SEASON.value)
            max_progress = getattr(self, "max_progress", None)
        self.rewatch_started_at = None
        self._invalidate_episode_stats()
        if self._is_fully_watched(max_progress):
            self.status = Status.COMPLETED.value
        bulk_update_with_history(
            [self],
            Season,
            fields=["rewatch_started_at", "status"],
        )

    def finish_rewatch_if_complete(self, max_progress=None):
        """Close the pass and complete the season once every episode is replayed.

        Does not fan out to the parent TV — callers that care (e.g.
        advancing to the next season) do that themselves, since a bulk
        caller closing several seasons at once needs that to happen after
        every season in the batch has settled, not mid-loop.
        """
        if self.rewatch_started_at is None:
            return False
        if (
            self.derived_status_from_episode_progress(max_progress=max_progress)
            != Status.COMPLETED.value
        ):
            return False

        self.rewatch_started_at = None
        self.status = Status.COMPLETED.value
        self._invalidate_episode_stats()
        bulk_update_with_history(
            [self],
            Season,
            fields=["rewatch_started_at", "status"],
        )
        return True

    def _get_episode_stats(self):
        """Return cached episode stats for this season."""
        cached = getattr(self, "_episode_stats_cache", None)
        if cached is not None:
            return cached

        # Filter in Python: season querysets prefetch `episodes`, and a
        # queryset filter here would bypass that cache and turn every list
        # page into an N+1.
        episodes = [ep for ep in self.episodes.all() if self.play_counts_for_pass(ep)]
        episode_counts = {}
        completed_episode_numbers = set()
        max_episode_number = 0

        for ep in episodes:
            ep_num = ep.item.episode_number
            if ep.status == Status.COMPLETED.value:
                episode_counts[ep_num] = episode_counts.get(ep_num, 0) + 1
                completed_episode_numbers.add(ep_num)
            if (
                (ep.status in {Status.COMPLETED.value, Status.DROPPED.value})
                and ep_num
                and ep_num > max_episode_number
            ):
                max_episode_number = ep_num

        cached = {
            "episode_counts": episode_counts,
            "completed_episode_numbers": completed_episode_numbers,
            "max_episode_number": max_episode_number,
        }
        self._episode_stats_cache = cached
        return cached

    @property
    def progressed_at(self):
        """Return the date when the last episode was watched."""
        dates = [
            episode.end_date
            for episode in self.episodes.all()
            if episode.end_date is not None
        ]
        return max(dates) if dates else None

    @property
    def start_date(self):
        """Return the date of the first episode watched."""
        dates = [
            episode.end_date
            for episode in self.episodes.all()
            if episode.end_date is not None
        ]
        return min(dates) if dates else None

    @property
    def end_date(self):
        """Return the date of the last episode watched."""
        dates = [
            episode.end_date
            for episode in self.episodes.all()
            if episode.end_date is not None
        ]
        return max(dates) if dates else None

    def increase_progress(self, watch_operation_id=None):
        """Watch the next episode of the season."""
        if watch_operation_id:
            from app import fork_services_episode

            operation_id = fork_services_episode.normalize_watch_operation_id(
                watch_operation_id,
            )
            claimed = (
                Episode.objects.filter(watch_operation_id=operation_id)
                .select_related("related_season", "item")
                .first()
            )
            if claimed is not None:
                return fork_services_episode.resolve_episode_watch_replay(
                    claimed,
                    user_id=self.user_id,
                    season_id=self.id,
                )
        season_metadata = providers.services.get_media_metadata(
            MediaTypes.SEASON.value,
            self.item.media_id,
            self.item.source,
            [self.item.season_number],
        )
        episodes = season_metadata["episodes"]

        next_episode_number = providers.tmdb.find_next_episode(self.progress, episodes)

        now = timezone.now()

        if next_episode_number:
            return self.watch(
                next_episode_number,
                now,
                watch_operation_id=watch_operation_id,
            )
        logger.info("No more episodes to watch.")
        return None

    def watch(
        self, episode_number, end_date, watch_operation_id=None, **episode_fields
    ):
        """Create or add a repeat to an episode of the season."""
        from app import fork_services_episode

        item = self.get_episode_item(episode_number)

        result = fork_services_episode.create_episode_watch(
            self,
            item,
            end_date,
            watch_operation_id=watch_operation_id,
            **episode_fields,
        )
        if result.created:
            logger.info("%s created successfully.", result.episode)
            cache_utils.clear_time_left_cache_for_user(self.user_id)
            cache_utils.clear_media_list_cache_for_user(self.user_id)
        return result

    def decrease_progress(self):
        """Unwatch the current episode of the season."""
        self.unwatch(self.progress)

    def unwatch(self, episode_number):
        """Unwatch the episode instance."""
        item = self.get_episode_item(episode_number)

        episodes = Episode.objects.filter(
            related_season=self,
            item=item,
        ).order_by("-end_date")

        episode = episodes.first()

        if episode is None:
            logger.warning(
                "Episode %s does not exist.",
                self.item,
            )
            return

        # Get count before deletion for logging
        remaining_count = episodes.count() - 1

        episode.delete()
        logger.info(
            "Deleted %s S%02dE%02d (%d remaining instances)",
            self.item.title,
            self.item.season_number,
            episode_number,
            remaining_count,
        )

        # Re-evaluate season/TV status after deletion so completed shows don't stay "In progress"
        if hasattr(self, "_episode_stats_cache"):
            delattr(self, "_episode_stats_cache")
        self._sync_status_after_episode_change()
        cache_utils.clear_time_left_cache_for_user(self.user_id)
        cache_utils.clear_media_list_cache_for_user(self.user_id)

    def _sync_status_after_episode_change(self):
        """Recalculate season (and TV) status using local data (no provider calls)."""
        if self.status == Status.DROPPED.value:
            return
        if self.status == Status.PAUSED.value:
            return

        # What episodes do we have logged?
        episode_numbers = set(
            self.episodes.filter(
                status__in=[Status.COMPLETED.value, Status.DROPPED.value],
            ).values_list("item__episode_number", flat=True),
        )
        episode_numbers.discard(None)
        max_watched = max(episode_numbers) if episode_numbers else 0

        # Best local hint for total episodes: release events in the DB
        total_eps = (
            events.models.Event.objects.filter(
                item=self.item,
                content_number__isnull=False,
                datetime__lte=timezone.now(),
            ).aggregate(max_ep=Max("content_number"))["max_ep"]
            or 0
        )

        desired_status = None

        if total_eps > 0 and max_watched >= total_eps:
            # We know how many have released and we've logged them all.
            # Respect a manual IN_PROGRESS override (rewatch) rather than
            # forcing back to Completed.
            desired_status = (
                Status.IN_PROGRESS.value
                if self.status == Status.IN_PROGRESS.value
                else Status.COMPLETED.value
            )
        elif max_watched > 0 and total_eps == 0:
            # No release data, but we have watches — stay in progress
            desired_status = Status.IN_PROGRESS.value
        elif max_watched > 0:
            desired_status = Status.IN_PROGRESS.value
        else:
            desired_status = Status.PLANNING.value

        season_updates = []
        if desired_status and self.status != desired_status:
            self.status = desired_status
            season_updates.append(self)

        # Align the parent TV unless it was dropped explicitly
        tv_updates = []
        tv = getattr(self, "related_tv", None)
        if tv and tv.status != Status.DROPPED.value and desired_status:
            if desired_status == Status.COMPLETED.value:
                # Only mark TV complete if all real seasons are complete
                has_incomplete = (
                    tv.seasons.filter(
                        item__season_number__gt=0,
                    )
                    .exclude(status=Status.COMPLETED.value)
                    .exists()
                )
                tv_target = (
                    Status.COMPLETED.value
                    if not has_incomplete
                    else Status.IN_PROGRESS.value
                )
            else:
                tv_target = Status.IN_PROGRESS.value

            if tv.status != tv_target:
                tv.status = tv_target
                tv_updates.append(tv)

        if season_updates:
            bulk_update_with_history(season_updates, Season, fields=["status"])
        if tv_updates:
            bulk_update_with_history(tv_updates, TV, fields=["status"])

    def get_tv(self):
        """Get related TV instance for a season and create it if it doesn't exist."""
        # Scope to the season's own bucket (anime vs. non-anime) so a season
        # is never silently attached to a TV row from the show's other
        # identity when both exist — see #623.
        is_anime_bucket = self.item.library_media_type == MediaTypes.ANIME.value

        def _bucket_scoped(queryset):
            if is_anime_bucket:
                return queryset.filter(item__library_media_type=MediaTypes.ANIME.value)
            return queryset.exclude(item__library_media_type=MediaTypes.ANIME.value)

        try:
            tv = _bucket_scoped(
                TV.objects.filter(
                    item__media_id=self.item.media_id,
                    item__media_type=MediaTypes.TV.value,
                    item__season_number=None,
                    item__source=self.item.source,
                    user=self.user,
                ),
            ).get()
        except TV.MultipleObjectsReturned:
            tv = (
                _bucket_scoped(
                    TV.objects.filter(
                        item__media_id=self.item.media_id,
                        item__media_type=MediaTypes.TV.value,
                        item__season_number=None,
                        item__source=self.item.source,
                        user=self.user,
                    ),
                )
                .order_by("id")
                .first()
            )
            logger.warning(
                "Multiple TV records for media_id=%s source=%s user=%s — using oldest",
                self.item.media_id,
                self.item.source,
                self.user_id,
            )
            return tv
        except TV.DoesNotExist:
            fallback_title = self.item.series_name or self.item.title
            try:
                tv_metadata = providers.services.get_media_metadata(
                    MediaTypes.TV.value,
                    self.item.media_id,
                    self.item.source,
                )
                season_count = tv_metadata.get("details", {}).get("seasons")
                if season_count is None:
                    season_count = len(
                        tv_metadata.get("related", {}).get("seasons", [])
                    )
            except (
                Exception
            ) as exc:  # pragma: no cover - defensive for test/no-network paths
                logger.warning(
                    "Could not fetch TV metadata for media_id=%s while creating season parent: %s",
                    self.item.media_id,
                    exc,
                )
                tv_metadata = {
                    "title": fallback_title,
                    "localized_title": fallback_title,
                    "original_title": None,
                    "image": self.item.image,
                    "details": {},
                    "related": {"seasons": []},
                }
                season_count = None

            # creating tv with multiple seasons from a completed season
            if self.status == Status.COMPLETED.value and season_count > 1:
                status = Status.IN_PROGRESS.value
            else:
                status = self.status

            item, _ = Item.objects.get_or_create(
                media_id=self.item.media_id,
                source=self.item.source,
                media_type=MediaTypes.TV.value,
                library_media_type=self.item.library_media_type,
                defaults={
                    **Item.title_fields_from_metadata(
                        tv_metadata,
                        fallback_title=fallback_title,
                    ),
                    "image": tv_metadata.get("image") or self.item.image,
                },
            )

            tv = TV(
                item=item,
                score=None,
                status=status,
                notes="",
                user=self.user,
            )

            # save_base to avoid custom save method
            TV.save_base(tv)

            logger.info("%s did not exist, it was created successfully.", tv)

        return tv

    def get_remaining_eps(self, season_metadata, end_date=_UNSET_END_DATE):
        """Return episodes needed to complete a season."""
        plays = Episode.objects.filter(related_season=self)
        started_on = self.pass_started_on
        if started_on is None:
            latest_watched_ep_num = plays.aggregate(
                latest_watched_ep_num=Max("item__episode_number"),
            )["latest_watched_ep_num"]
        else:
            # Narrow in SQL, then apply `play_counts_for_pass` so the plays
            # treated as watched here are exactly the ones that count toward
            # the pass's progress. Any divergence between the two leaves a
            # season unable to ever reach max_progress.
            plays = plays.filter(
                models.Q(end_date__gte=started_on)
                | models.Q(end_date__isnull=True, created_at__gte=started_on),
            ).select_related("item")
            latest_watched_ep_num = max(
                (
                    play.item.episode_number
                    for play in plays
                    if play.item.episode_number is not None
                    and self.play_counts_for_pass(play)
                ),
                default=None,
            )

        if latest_watched_ep_num is None:
            latest_watched_ep_num = 0

        episodes_to_create = []

        # Calculate current time once before the loop
        now = timezone.now().replace(second=0, microsecond=0)

        # Create Episode objects for the remaining episodes
        for episode in reversed(season_metadata["episodes"]):
            if episode["episode_number"] <= latest_watched_ep_num:
                break

            item = self.get_episode_item(episode["episode_number"], season_metadata)

            # An explicit end_date (including None) from the completion form
            # applies uniformly; otherwise fall back to the user's preference.
            if end_date is _UNSET_END_DATE:
                resolved_end_date = self.user.resolve_watch_date(
                    now, episode.get("air_date")
                )
            else:
                resolved_end_date = end_date

            episode_db = Episode(
                related_season=self,
                item=item,
                end_date=resolved_end_date,
            )
            episodes_to_create.append(episode_db)

        return episodes_to_create

    def get_episode_item(self, episode_number, season_metadata=None):
        """Get the episode item instance, create it if it doesn't exist."""
        if not season_metadata:
            season_metadata = providers.services.get_media_metadata(
                MediaTypes.SEASON.value,
                self.item.media_id,
                self.item.source,
                [self.item.season_number],
            )

        from app import helpers

        image = settings.IMG_NONE
        runtime_minutes = None
        release_datetime = None
        matched_episode = {}
        tvdb_episode_images = {}
        normalized_episode_number = int(episode_number)

        if (
            isinstance(season_metadata, dict)
            and isinstance(season_metadata.get("episodes"), list)
        ):
            from app.services.episode_coordinates import (
                InvalidEpisodeCoordinateError,
                cleanup_episode_history_for_season,
                resolve_episode_coordinate,
            )

            try:
                matched_episode = resolve_episode_coordinate(
                    self.item.media_id,
                    self.item.source,
                    self.item.season_number,
                    normalized_episode_number,
                    season_metadata=season_metadata,
                ).episode
            except InvalidEpisodeCoordinateError:
                cleanup_episode_history_for_season(self, normalized_episode_number)
                raise

        if self.item.source == Sources.TMDB.value:
            if isinstance(season_metadata, dict):
                tvdb_episode_images = season_metadata.get("_tvdb_episode_image_map")
                if tvdb_episode_images is None:
                    tvdb_episode_images = providers.tmdb.get_tvdb_episode_image_map(
                        season_metadata.get("tvdb_id"),
                        season_metadata.get("season_number") or self.item.season_number,
                        tmdb_media_id=self.item.media_id,
                    )
                    season_metadata["_tvdb_episode_image_map"] = tvdb_episode_images
            else:
                tvdb_episode_images = providers.tmdb.get_tvdb_episode_image_map(
                    season_metadata.get("tvdb_id"),
                    season_metadata.get("season_number") or self.item.season_number,
                    tmdb_media_id=self.item.media_id,
                )

        if isinstance(season_metadata, dict):
            episodes_by_number = season_metadata.get("_episodes_by_number")
            if episodes_by_number is None:
                episodes_by_number = {}
                for episode in season_metadata.get("episodes") or []:
                    if not isinstance(episode, dict):
                        continue
                    try:
                        episode_key = int(episode["episode_number"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    episodes_by_number[episode_key] = episode
                season_metadata["_episodes_by_number"] = episodes_by_number
            matched_episode = episodes_by_number.get(normalized_episode_number, {})
        else:
            for episode in season_metadata["episodes"]:
                try:
                    metadata_episode_number = int(episode["episode_number"])
                except (KeyError, TypeError, ValueError):
                    continue
                if metadata_episode_number == normalized_episode_number:
                    matched_episode = episode
                    break

        if matched_episode:
            image = helpers.first_real_image(
                (
                    f"https://image.tmdb.org/t/p/original{matched_episode['still_path']}"
                    if matched_episode.get("still_path")
                    else None
                ),
                tvdb_episode_images.get(str(episode_number)),
                matched_episode.get("image"),
            )

            # Extract runtime from episode metadata. TMDB sends an integer
            # number of minutes, manual items whatever the custom-metadata form
            # stored (a string), so compare only after coercing.
            runtime_minutes = _runtime_minutes(matched_episode.get("runtime"))

            # Extract release_datetime from episode air_date
            air_date = matched_episode.get("air_date")
            if air_date:
                from datetime import UTC, datetime

                from django.utils import timezone

                try:
                    # Providers return a date-only value (TMDB as a
                    # "YYYY-MM-DD" string, TVDB sometimes as a naive
                    # datetime) with no real-world timezone attached - it's
                    # a calendar date, not a local wall-clock moment. Anchor
                    # it to UTC rather than the server's configured
                    # TIME_ZONE: using the server's local zone here shifted
                    # dates by that zone's UTC offset (e.g. Europe/Berlin's
                    # +2h in summer pushed a July 15 air date to July 14
                    # 22:00 UTC), which can flip the calendar date shown to
                    # users depending on deployment timezone.
                    if isinstance(air_date, str):
                        date_obj = datetime.strptime(air_date, "%Y-%m-%d")  # noqa: DTZ007  # date-only value; no timezone applies
                        release_datetime = date_obj.replace(tzinfo=UTC)
                    elif hasattr(air_date, "year"):
                        # Already a datetime object
                        release_datetime = (
                            air_date
                            if timezone.is_aware(air_date)
                            else air_date.replace(tzinfo=UTC)
                        )
                except (ValueError, TypeError):
                    # If parsing fails, keep release_datetime as None
                    pass

        # An episode's library bucket should mirror the show's grouping bucket
        # (e.g. 'tv'/'anime' for grouped anime), never the season's own 'season'
        # type. Copying the season's 'season' bucket onto episodes is what
        # produced the stray ('episode','season') items, so fall back to
        # 'episode' whenever the season is in its own (non-grouped) bucket.
        season_bucket = self.item.library_media_type
        episode_bucket = (
            season_bucket
            if season_bucket and season_bucket != MediaTypes.SEASON.value
            else MediaTypes.EPISODE.value
        )

        item, created = Item.objects.get_or_create(
            media_id=self.item.media_id,
            source=self.item.source,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=episode_bucket,
            season_number=self.item.season_number,
            episode_number=normalized_episode_number,
            defaults={
                **Item.title_fields_from_episode_metadata(
                    matched_episode,
                    fallback_title=self.item.title,
                ),
                "image": image,
                "runtime_minutes": runtime_minutes,
                "release_datetime": release_datetime,
            },
        )

        # Update fields if not set and we have them now
        updated = False
        if not created:
            update_fields = []
            title_fields = Item.title_fields_from_episode_metadata(
                matched_episode,
                fallback_title=self.item.title,
            )
            for field_name, value in title_fields.items():
                if getattr(item, field_name) != value:
                    setattr(item, field_name, value)
                    update_fields.append(field_name)
                    updated = True
            if item.library_media_type != episode_bucket:
                item.library_media_type = episode_bucket
                update_fields.append("library_media_type")
                updated = True
            if not item.runtime_minutes and runtime_minutes:
                item.runtime_minutes = runtime_minutes
                update_fields.append("runtime_minutes")
                updated = True
            if not item.release_datetime and release_datetime:
                item.release_datetime = release_datetime
                update_fields.append("release_datetime")
                updated = True
            if updated:
                item.save(update_fields=update_fields)
        elif created:
            # Ensure runtime and release_datetime are set for newly created items
            needs_save = False
            if runtime_minutes and not item.runtime_minutes:
                item.runtime_minutes = runtime_minutes
                needs_save = True
            if release_datetime and not item.release_datetime:
                item.release_datetime = release_datetime
                needs_save = True
            if needs_save:
                item.save(
                    update_fields=[
                        "library_media_type",
                        "runtime_minutes",
                        "release_datetime",
                    ],
                )

        return item


class Episode(models.Model):
    """Model for episodes of a season."""

    tracker = FieldTracker(fields=["status", "dropped"])
    history = HistoricalRecords(
        cascade_delete_history=True,
        excluded_fields=[
            "item",
            "related_season",
            "created_at",
            "score",
            "watch_operation_id",
            # `status` stays excluded: every episode row is a watch, so its
            # status is inert noise in the timeline. `start_date` is tracked so
            # the history modal can show "Started on …" (issue #377).
            "status",
            "notes",
        ],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    watch_operation_id = models.UUIDField(null=True, unique=True, editable=False)
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True)
    related_season = models.ForeignKey(
        Season,
        on_delete=models.CASCADE,
        related_name="episodes",
    )
    end_date = models.DateTimeField(null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.COMPLETED.value,
    )
    notes = models.TextField(blank=True, default="")
    dropped = models.BooleanField(default=False)
    score = models.DecimalField(
        null=True,
        blank=True,
        max_digits=3,
        decimal_places=1,
        validators=[
            DecimalValidator(3, 1),
            MinValueValidator(0),
            MaxValueValidator(10),
        ],
    )

    class Meta:
        """Meta options for the model."""

        ordering = [
            "related_season",
            "item__episode_number",
            "-end_date",
            "-created_at",
        ]

    def __str__(self):
        """Return the season and episode number."""
        return self.item.__str__()

    def save(self, *args, **kwargs):
        """Save the episode instance."""
        from app.services.completion import (
            finalize_completed_entry,
            prepare_completed_entry,
        )

        if self.tracker.has_changed("status"):
            self.dropped = self.status == Status.DROPPED.value
        elif self.tracker.has_changed("dropped"):
            self.status = (
                Status.DROPPED.value if self.dropped else Status.COMPLETED.value
            )
        if self._state.adding and self.score is None:
            # A rating belongs to the episode, not to one viewing of it — the
            # score endpoint writes every play at once — so a replay inherits
            # the rating instead of coming back unrated.
            self.score = (
                Episode.objects.filter(
                    related_season_id=self.related_season_id,
                    item_id=self.item_id,
                )
                .exclude(score__isnull=True)
                .values_list("score", flat=True)
                .first()
            )

        planning_entries, merged_fields = prepare_completed_entry(self)
        if merged_fields and kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = tuple(
                dict.fromkeys((*kwargs["update_fields"], *merged_fields)),
            )

        if planning_entries:
            with transaction.atomic():
                super().save(*args, **kwargs)
                finalize_completed_entry(planning_entries)
        else:
            super().save(*args, **kwargs)

        season_number = self.item.season_number
        if season_number is None:
            return
        try:
            tv_with_seasons_metadata = providers.services.get_media_metadata(
                "tv_with_seasons",
                self.item.media_id,
                self.item.source,
                [season_number],
            )
            season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]
            max_progress = len(season_metadata["episodes"])
            self.related_season.max_progress = max_progress
        except (
            providers.services.ProviderAPIError,
            RequestException,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            max_progress = self._local_season_max_progress()
            if not max_progress:
                logger.warning(
                    "Skipping Episode status sync due to missing metadata for "
                    "%s S%sE%s: %s",
                    self.item.media_id,
                    season_number,
                    self.item.episode_number,
                    error,
                )
                return
            logger.info(
                "Using locally recorded episode count %s for %s S%s "
                "(provider metadata missing)",
                max_progress,
                self.item.media_id,
                season_number,
            )
            self.related_season.max_progress = max_progress

        # clear prefetch cache to get the updated episodes
        if hasattr(self.related_season, "_episode_stats_cache"):
            delattr(self.related_season, "_episode_stats_cache")
        self.related_season.refresh_from_db()

        desired_status = self.related_season.derived_status_from_episode_progress(
            max_progress=max_progress,
        )

        if desired_status != self.related_season.status:
            self.related_season.status = desired_status
            bulk_update_with_history(
                [self.related_season],
                Season,
                fields=["status"],
            )

        # Close an explicit rewatch once this play completed it, so the next
        # pass starts from a clean window.
        self.related_season.finish_rewatch_if_complete(max_progress=max_progress)

        if desired_status == Status.COMPLETED.value:
            self.related_season.related_tv._handle_completed_season(season_number)
        elif self.related_season.related_tv.status != Status.IN_PROGRESS.value:
            self.related_season.related_tv.status = Status.IN_PROGRESS.value
            bulk_update_with_history(
                [self.related_season.related_tv],
                TV,
                fields=["status"],
            )

    @property
    def progress(self):
        """Expose episode number as progress for list rendering/sorting fallbacks."""
        if hasattr(self, "_progress_override"):
            return self._progress_override
        item = getattr(self, "item", None)
        return item.episode_number if item else None

    @progress.setter
    def progress(self, value):
        self._progress_override = value

    @property
    def max_progress(self):
        """Expose related season max progress when available."""
        if hasattr(self, "_max_progress_override"):
            return self._max_progress_override
        related_season = getattr(self, "related_season", None)
        return getattr(related_season, "max_progress", None)

    @max_progress.setter
    def max_progress(self, value):
        self._max_progress_override = value

    @property
    def progressed_at(self):
        """Return the progressed at."""
        return None

    def _local_season_max_progress(self):
        """Return the media-server-sourced episode count for this season, if any.

        Only set when the provider has no metadata for the season, so the count
        is the sole authority available for completion.
        """
        season_item = getattr(self.related_season, "item", None)
        count = getattr(season_item, "local_season_episode_count", None)
        return count if count and count > 0 else None
