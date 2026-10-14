"""Turn Steam and Xbox lifetime playtime into dated play sessions.

Steam and Xbox only report a lifetime minutes-played total per game, while
History and Statistics are built from *dated* Game rows (every view sums
``progress`` across all of a user's rows for the same game). So, as the PSN
importer does, each sync remembers the total it saw (:class:`PlaytimeSnapshot`)
and logs the increase since the previous sync as a new, dated Game row.
Existing rows are never rewritten once a game has a snapshot.

The first sync that sees a game has nothing to diff against:

* An untracked game is added the way these importers always added it: one
  undated row holding the lifetime total.
* A tracked game's total becomes the starting point. Play since the previous
  sync is dated only when the platform can vouch for it (Xbox: launched after
  the account's last sync; Steam: within its two-week playtime figure), and
  "overwrite" mode still reconciles a total that drifted from the platform's.

Without those rules, the first sync after upgrading would log a whole library's
lifetime playtime as one session today.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

import app
from app.models import MediaTypes, Sources, Status
from integrations.models import PlaytimeSnapshot

logger = logging.getLogger(__name__)

# Import-result key for dated session rows. It is a metric, not a media type
# (see IMPORT_COUNT_METRIC_KEYS in integrations.tasks._import_helpers).
SESSIONS_COUNT_KEY = "game_sessions"
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
            mode (str): Import mode; "overwrite" may update existing rows.
            import_note (str): Notes for a newly added game's row.
            session_note (str): Notes for a dated session row.
            existing_media: ``helpers.get_existing_media(user)``.
            previous_sync_at (datetime | None): When the platform account last
                synced, if the platform keeps one (Xbox does, Steam doesn't).
        """
        self.user = user
        self.source = source
        self.mode = mode
        self.import_note = import_note
        self.session_note = session_note
        self.existing_games = existing_media[MediaTypes.GAME.value][Sources.IGDB.value]
        self.previous_sync_at = aware(previous_sync_at)
        self.sync_time = timezone.now()
        self.snapshots = {
            snapshot.media_id: snapshot
            for snapshot in PlaytimeSnapshot.objects.filter(user=user, source=source)
        }
        self.tracked = {
            row["item__media_id"]: row["total"] or 0
            for row in app.models.Game.objects.filter(
                user=user,
                item__source=Sources.IGDB.value,
                item__media_type=MediaTypes.GAME.value,
            )
            .values("item__media_id")
            .annotate(total=Sum("progress"))
        }

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
        if existing:
            item = existing.item
            item.title = observation.title
            item.image = observation.image
            if self.mode == "overwrite" and existing.status not in KEPT_STATUSES:
                existing.status = status
                self._mark_updated(existing)

        minutes = observation.minutes
        if minutes is None:
            # The platform didn't report playtime for this title (Xbox titles
            # that don't publish MinutesPlayed): nothing to diff, and tracked
            # hours must not be zeroed.
            if not existing:
                self._add_game(media_id, observation, status, minutes=0)
            return

        snapshot = self.snapshots.get(media_id)
        previous = snapshot.minutes if snapshot else None
        previous_seen = snapshot.seen_at if snapshot else None
        # A lower total means a refund, a removed family-shared game, or a
        # sibling title whose lookup failed this run. Remember the higher one
        # so the same minutes are never logged twice.
        self._remember(media_id, max(minutes, previous or 0))

        if previous is None:
            self._first_sighting(media_id, existing, observation, status)
            return

        delta = minutes - previous
        if delta <= 0:
            self.unchanged += 1
            return
        self._add_session(
            media_id,
            observation,
            delta,
            status,
            not_before=previous_seen,
        )

    def _first_sighting(self, media_id, existing, observation, status):
        """Handle a game this platform has no remembered total for yet."""
        minutes = observation.minutes
        if not existing:
            self._add_game(media_id, observation, status, minutes=minutes)
            return

        tracked = self.tracked.get(media_id, 0)
        gap = self._gap_since_last_sync(minutes, tracked, observation)
        if gap:
            self._add_session(
                media_id,
                observation,
                gap,
                status,
                not_before=self.previous_sync_at,
            )
            return

        if self.mode == "overwrite" and minutes != tracked:
            # Overwrite has always meant "make tracked hours match the
            # platform"; adjust this row by the difference so the game's
            # total (summed across all its rows) lands on the platform's.
            existing.progress = max(0, (existing.progress or 0) + minutes - tracked)
            self._mark_updated(existing)
            return

        self.baseline += 1

    def _gap_since_last_sync(self, minutes, tracked, observation):
        """Return datable minutes played since the last sync, or 0.

        Only for a game whose tracked hours were in step with the platform at
        the last sync: the difference must be no bigger than what's tracked,
        the game must have been launched recently, and the platform must be
        able to vouch for when that play happened.
        """
        gap = minutes - tracked
        if not (0 < gap <= tracked):
            return 0
        last_played = observation.last_played
        if last_played is None or last_played > self.sync_time:
            return 0
        if self.previous_sync_at is not None:
            if last_played <= self.previous_sync_at:
                return 0
            elapsed = self.sync_time - self.previous_sync_at
            return min(gap, int(elapsed.total_seconds() // 60))
        if observation.recent_minutes is not None:
            return min(gap, observation.recent_minutes)
        return 0

    def _add_game(self, media_id, observation, status, *, minutes):
        """Queue a newly tracked game's undated lifetime row."""
        self.new_games += 1
        self.rows.append(
            app.models.Game(
                item=self._item(media_id, observation),
                user=self.user,
                status=status,
                score=None,
                progress=minutes,
                notes=self.import_note,
                start_date=None,
                end_date=None,
            ),
        )

    def _add_session(self, media_id, observation, minutes, status, *, not_before):
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

        if media_id not in self.existing_games:
            self.new_games += 1
        self.sessions += 1
        self.rows.append(
            app.models.Game(
                item=self._item(media_id, observation),
                user=self.user,
                status=status,
                score=None,
                progress=minutes,
                notes=self.session_note,
                start_date=start,
                end_date=end,
            ),
        )

    def _item(self, media_id, observation):
        existing = self.existing_games.get(media_id)
        if existing:
            return existing.item
        item, _ = app.models.Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": observation.title, "image": observation.image},
        )
        return item

    def _mark_updated(self, game):
        if game not in self.to_update:
            self.to_update.append(game)

    def _remember(self, media_id, minutes):
        snapshot = self.snapshots.get(media_id)
        if snapshot:
            snapshot.minutes = minutes
            snapshot.seen_at = self.sync_time
        else:
            self.snapshots[media_id] = PlaytimeSnapshot(
                user=self.user,
                source=self.source,
                media_id=media_id,
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
