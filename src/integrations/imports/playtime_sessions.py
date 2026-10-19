"""Turn Steam and Xbox lifetime playtime into dated play sessions.

Steam and Xbox only report a lifetime minutes-played total per game, while
History and Statistics are built from *dated* Game rows (every view sums
``progress`` across all of a user's rows for the same game). So, as the PSN
importer does, each sync remembers the total it saw (:class:`PlaytimeSnapshot`)
and logs the increase since the previous sync as a new, dated Game row.
Existing rows are never rewritten once a game has a snapshot.

Remembered totals are kept per platform *account* (Steam ID, Xbox XUID), so
switching accounts starts fresh instead of reading one account's total as new
play on the other.

The first sync that sees a game has nothing to diff against:

* An untracked game is added the way these importers always added it: one
  undated row holding the lifetime total.
* A tracked game's total becomes the starting point. Play since the previous
  sync is dated only when the platform can vouch for it: Steam's two-week
  playtime figure, or -- in overwrite mode, the only mode that kept tracked
  hours in step with Xbox -- time since the Xbox account's last sync.
  Overwrite still reconciles a drifted total, but only on a game tracked as a
  single undated row, so other platforms' rows and dated plays are left alone.

Without those rules, the first sync after upgrading would log a whole library's
lifetime playtime as one session today.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

import app
from app.models import MediaTypes, Sources, Status
from integrations.models import PlaytimeSnapshot

logger = logging.getLogger(__name__)

# Import-result key for dated session rows. It is a metric, not a media type
# (see IMPORT_COUNT_METRIC_KEYS in integrations.tasks._import_helpers).
SESSIONS_COUNT_KEY = "game_sessions"
# Statuses only the user sets; a sync never replaces them.
KEPT_STATUSES = frozenset({Status.COMPLETED.value, Status.DROPPED.value})


@dataclass
class PlaytimeObservation:
    """What a platform reported for one IGDB game during this sync.

    Several platform titles can resolve to the same IGDB game (editions,
    remasters sharing an entry), so observations are merged before storing.
    """

    title: str
    image: str
    minutes: int | None = None
    recent_minutes: int | None = None
    last_played: object = None

    def merge(self, minutes, recent_minutes, last_played):
        """Fold another platform title for the same game into this one."""
        if minutes is not None:
            self.minutes = (self.minutes or 0) + minutes
        if recent_minutes is not None:
            self.recent_minutes = (self.recent_minutes or 0) + recent_minutes
        last_played = aware(last_played)
        if last_played and (self.last_played is None or last_played > self.last_played):
            self.last_played = last_played


@dataclass
class TrackedGame:
    """A user's existing rows for one game, summarized."""

    total: int = 0
    rows: int = 0
    # The user's undated row: the one an import adds and overwrite may adjust.
    base: object = None
    # The status the media views show: the row with the latest activity wins.
    status: str | None = None
    _latest: object = field(default=None, repr=False)

    def add(self, game):
        """Fold one of the user's rows for the game into the summary."""
        self.total += game.progress or 0
        self.rows += 1
        if self.base is None and game.start_date is None and game.end_date is None:
            self.base = game
        activity = game.end_date or game.progressed_at or game.created_at
        if activity and (self._latest is None or activity > self._latest):
            self._latest = activity
            self.status = game.status


def aware(value):
    """Return a timezone-aware datetime, leaving None alone."""
    if value is not None and timezone.is_naive(value):
        return timezone.make_aware(value)
    return value


class PlaytimeSessionLogger:
    """Decide, per game, whether a sync adds a session, a new game, or nothing."""

    def __init__(
        self,
        user,
        *,
        source,
        account,
        mode,
        import_note,
        session_note,
        existing_media,
        previous_sync_at=None,
    ):
        """Load the user's remembered totals and tracked playtime.

        Args:
            user: The importing user.
            source (str): ``PlaytimeSnapshot.source`` for this platform.
            account (str): The platform account ID (Steam ID, Xbox XUID).
            mode (str): Import mode; "overwrite" may update existing rows.
            import_note (str): Notes for a newly added game's row.
            session_note (str): Notes for a dated session row.
            existing_media: ``helpers.get_existing_media(user)``.
            previous_sync_at (datetime | None): When the platform account last
                synced, if the platform keeps one (Xbox does, Steam doesn't).
        """
        self.user = user
        self.source = source
        self.account = str(account)
        self.mode = mode
        self.import_note = import_note
        self.session_note = session_note
        self.existing_games = existing_media[MediaTypes.GAME.value][Sources.IGDB.value]
        self.previous_sync_at = aware(previous_sync_at)
        self.sync_time = timezone.now()
        self.snapshots = {
            snapshot.media_id: snapshot
            for snapshot in PlaytimeSnapshot.objects.filter(
                user=user,
                source=source,
                media_id__startswith=f"{self.account}:",
            )
        }
        self.tracked = {}
        for game in (
            app.models.Game.objects.filter(
                user=user,
                item__source=Sources.IGDB.value,
                item__media_type=MediaTypes.GAME.value,
            )
            .select_related("item")
            .only(
                "id",
                "item__media_id",
                "progress",
                "status",
                "start_date",
                "end_date",
                "progressed_at",
                "created_at",
            )
            .order_by("created_at", "id")
        ):
            self.tracked.setdefault(game.item.media_id, TrackedGame()).add(game)

        self.rows = []
        self.to_update = []
        self.new_games = 0
        self.sessions = 0
        self.unchanged = 0
        self.baseline = 0

    def store(self, media_id, observation, *, status):
        """Record one game's reported playtime.

        Args:
            media_id (str): The IGDB game ID.
            observation (PlaytimeObservation): The merged platform report.
            status (str): The status the importer derives from that report.
        """
        existing = self.existing_games.get(media_id)
        tracked = self.tracked.get(media_id) if existing else None
        if existing:
            item = existing.item
            item.title = observation.title
            item.image = observation.image
            base = tracked.base if tracked else None
            if (
                self.mode == "overwrite"
                and base is not None
                and base.status not in KEPT_STATUSES
            ):
                base.status = status
                self._mark_updated(base)

        minutes = observation.minutes
        if minutes is None:
            # The platform didn't report playtime for this title (Xbox titles
            # that don't publish MinutesPlayed): nothing to diff, and tracked
            # hours must not be zeroed.
            if not existing:
                self._add_game(media_id, observation, status, minutes=0)
            return

        key = self._key(media_id)
        snapshot = self.snapshots.get(key)
        previous = snapshot.minutes if snapshot else None
        previous_seen = snapshot.seen_at if snapshot else None
        # A lower total means a refund, a removed family-shared game, or a
        # sibling title whose lookup failed this run. Remember the higher one
        # so the same minutes are never logged twice.
        self.remember(media_id, minutes)

        if not existing:
            # Untracked here -- never added, or deleted since the last sync:
            # (re)added with its lifetime total, as these importers always did.
            self._add_game(media_id, observation, status, minutes=minutes)
            return

        if previous is None:
            self._first_sighting(existing, tracked, observation, status)
            return

        delta = minutes - previous
        if delta <= 0:
            self.unchanged += 1
            return
        self._add_session(
            existing.item,
            tracked,
            delta,
            observation,
            status,
            not_before=previous_seen,
        )

    def _first_sighting(self, existing, tracked, observation, status):
        """Handle a tracked game this account has no remembered total for."""
        minutes = observation.minutes
        total = tracked.total if tracked else 0
        drift = minutes - total
        gap = self._gap_since_last_sync(drift, total, observation)
        if gap:
            self._add_session(
                existing.item,
                tracked,
                gap,
                observation,
                status,
                not_before=self.previous_sync_at,
            )
            drift -= gap

        if drift and self.mode == "overwrite" and self._is_single_base_row(tracked):
            # Overwrite has always meant "make tracked hours match the
            # platform". Only a game tracked as one undated row is adjusted;
            # dated plays and other platforms' rows are history, not drift.
            tracked.base.progress = max(0, (tracked.base.progress or 0) + drift)
            self._mark_updated(tracked.base)
        elif not gap:
            self.baseline += 1

    def _gap_since_last_sync(self, drift, total, observation):
        """Return datable minutes played since the last sync, or 0.

        Only for a game whose tracked hours were in step with the platform at
        the last sync: the difference must be no bigger than what's tracked,
        the game must have been launched recently, and the platform must be
        able to vouch for when that play happened.
        """
        if not (0 < drift <= total):
            return 0
        last_played = observation.last_played
        if last_played is None or last_played > self.sync_time:
            return 0
        if observation.recent_minutes is not None:
            # Steam: playtime_2weeks is play Steam itself places in time.
            return min(drift, observation.recent_minutes)
        if self.previous_sync_at is not None and self.mode == "overwrite":
            # Xbox: "new" mode never refreshed tracked hours, so a difference
            # there is months of play, not play since the last sync.
            if last_played <= self.previous_sync_at:
                return 0
            elapsed = self.sync_time - self.previous_sync_at
            return min(drift, int(elapsed.total_seconds() // 60))
        return 0

    @staticmethod
    def _is_single_base_row(tracked):
        """Return whether the game is tracked as exactly one undated row."""
        return tracked is not None and tracked.rows == 1 and tracked.base is not None

    def _add_game(self, media_id, observation, status, *, minutes):
        """Queue a newly tracked game's undated lifetime row."""
        self.new_games += 1
        item, _ = app.models.Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": observation.title, "image": observation.image},
        )
        self.rows.append(
            app.models.Game(
                item=item,
                user=self.user,
                status=status,
                score=None,
                progress=minutes,
                notes=self.import_note,
                start_date=None,
                end_date=None,
            ),
        )

    def _add_session(self, item, tracked, minutes, observation, status, *, not_before):
        """Queue a dated row for ``minutes`` of play since ``not_before``.

        The session ends at the platform's last-played time when that falls in
        this sync's window (otherwise now) and is kept compact, so a short
        evening session isn't smeared across every day since the last sync.
        """
        end = observation.last_played
        if (
            end is None
            or end > self.sync_time
            or (not_before is not None and end < not_before)
        ):
            end = self.sync_time
        start = end - timedelta(minutes=minutes)
        if not_before is not None and start < not_before:
            start = min(not_before, end)

        # The newest row decides the status the game shows, so a session must
        # not turn a game the user finished or dropped back into "playing".
        if tracked is not None and tracked.status in KEPT_STATUSES:
            status = tracked.status

        self.sessions += 1
        self.rows.append(
            app.models.Game(
                item=item,
                user=self.user,
                status=status,
                score=None,
                progress=minutes,
                notes=self.session_note,
                start_date=start,
                end_date=end,
            ),
        )

    def _mark_updated(self, game):
        if game not in self.to_update:
            self.to_update.append(game)

    def _key(self, media_id):
        return f"{self.account}:{media_id}"

    def remember(self, media_id, minutes):
        """Remember the total the platform reported for a game this sync.

        Also called for games the user deleted here, so re-adding one later
        doesn't log everything played in between as a single new session.
        """
        if minutes is None:
            return
        key = self._key(media_id)
        snapshot = self.snapshots.get(key)
        if snapshot:
            snapshot.minutes = max(minutes, snapshot.minutes)
            snapshot.seen_at = self.sync_time
        else:
            self.snapshots[key] = PlaytimeSnapshot(
                user=self.user,
                source=self.source,
                media_id=key,
                minutes=minutes,
                seen_at=self.sync_time,
            )

    def save_snapshots(self):
        """Persist this sync's totals; call in the transaction that saves rows."""
        PlaytimeSnapshot.objects.bulk_create(
            [snapshot for snapshot in self.snapshots.values() if snapshot.pk is None],
        )
        PlaytimeSnapshot.objects.bulk_update(
            [snapshot for snapshot in self.snapshots.values() if snapshot.pk],
            fields=["minutes", "seen_at"],
        )

    def counts(self):
        """Return the importer's result counts.

        ``created``/``updated`` decide whether History and Statistics caches
        are refreshed, so a sync that only logged sessions still refreshes.
        """
        return {
            MediaTypes.GAME.value: self.new_games,
            SESSIONS_COUNT_KEY: self.sessions,
            "created": len(self.rows),
            "updated": len(self.to_update),
            "skipped": self.unchanged,
            "baseline": self.baseline,
        }
