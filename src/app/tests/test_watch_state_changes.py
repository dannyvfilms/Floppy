"""The ordered change log: what counts as a decision and what does not.

Three distinctions carry the whole design. A replayed provider event is not a
rewatch. Agreement is not an event. And a library nobody synchronizes must not
accumulate a log at all, because that log is what an upgrade would otherwise
push outward.
"""

import datetime
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
    WatchStateChange,
    WatchStateOrigin,
    WatchStateSequence,
)
from app.services.watch_state import (
    RevisionConflictError,
    changes_since,
    effective_state,
    record_state_change,
)


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day, hour=12):
    return datetime.datetime(2026, 2, day, hour, tzinfo=datetime.UTC)


class ChangeLogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item, _ = Item.objects.get_or_create(
            media_id="900",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )

    def _record(self, **kwargs):
        kwargs.setdefault("watched", True)
        kwargs.setdefault("play_count", 1)
        kwargs.setdefault("watched_at", _dt(1))
        kwargs.setdefault("origin_kind", WatchStateOrigin.WEBHOOK.value)
        kwargs.setdefault("origin_key", "jellyfin:server-1:user-1")
        return record_state_change(self.user, self.item, **kwargs)

    def test_a_change_moves_state_and_records_provenance(self):
        result = self._record()

        self.assertTrue(result.applied)
        self.assertEqual(result.change.sequence, 1)
        self.assertEqual(result.change.revision, 1)
        self.assertIsNone(result.change.previous_revision)
        self.assertEqual(result.state.origin_kind, WatchStateOrigin.WEBHOOK.value)
        self.assertTrue(result.state.watched)
        self.assertEqual(result.state.first_watched_at, _dt(1))

    def test_a_replayed_provider_event_is_not_a_rewatch(self):
        first = self._record(origin_event_id="evt-1")
        second = self._record(origin_event_id="evt-1", play_count=2)

        self.assertTrue(first.applied)
        self.assertTrue(second.replayed)
        self.assertFalse(second.applied)
        self.assertEqual(second.change.pk, first.change.pk)
        self.assertEqual(WatchStateChange.objects.filter(user=self.user).count(), 1)
        self.assertEqual(effective_state(self.user, self.item).play_count, 1)

    def test_the_same_event_id_from_a_different_origin_is_a_new_event(self):
        self._record(origin_event_id="evt-1")
        other = self._record(origin_event_id="evt-1", origin_key="plex:server-2")

        self.assertFalse(other.replayed)

    def test_agreement_is_not_an_event(self):
        self._record()
        again = self._record()

        self.assertTrue(again.unchanged)
        self.assertFalse(again.applied)
        self.assertEqual(WatchStateChange.objects.filter(user=self.user).count(), 1)

    def test_revisions_and_sequences_advance_together(self):
        self._record()
        second = self._record(watched=False, play_count=0, watched_at=None)

        self.assertEqual(second.change.sequence, 2)
        self.assertEqual(second.change.revision, 2)
        self.assertEqual(second.change.previous_revision, 1)
        self.assertFalse(effective_state(self.user, self.item).watched)

    def test_first_watched_at_is_not_overwritten_by_a_later_watch(self):
        self._record(watched_at=_dt(1))
        self._record(play_count=2, watched_at=_dt(9))

        state = effective_state(self.user, self.item)
        self.assertEqual(state.first_watched_at, _dt(1))
        self.assertEqual(state.last_watched_at, _dt(9))

    def test_a_stale_expected_revision_is_refused(self):
        self._record()

        with self.assertRaises(RevisionConflictError):
            self._record(play_count=5, expected_revision=0)

    def test_a_current_expected_revision_is_accepted(self):
        self._record()
        result = self._record(play_count=5, expected_revision=1)

        self.assertTrue(result.applied)

    def test_changes_since_returns_server_order(self):
        self._record()
        self._record(play_count=2, watched_at=_dt(2))
        self._record(play_count=3, watched_at=_dt(3))

        changes = changes_since(self.user, 0)
        self.assertEqual([change.sequence for change in changes], [1, 2, 3])
        self.assertEqual([change.sequence for change in changes_since(self.user, 2)], [3])


class LocalMovementTests(TestCase):
    """A local write becomes a change only once the user is synchronizing."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item, _ = Item.objects.get_or_create(
            media_id="901",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )

    def _enable_sync(self):
        WatchStateSequence.objects.update_or_create(
            user=self.user,
            defaults={"emit_changes": True},
        )

    def test_a_library_nobody_syncs_accumulates_no_log(self):
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        self.assertTrue(effective_state(self.user, self.item).watched)
        self.assertEqual(WatchStateChange.objects.filter(user=self.user).count(), 0)

    def test_a_local_watch_becomes_a_change_once_syncing(self):
        self._enable_sync()

        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        changes = changes_since(self.user, 0)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].origin_kind, WatchStateOrigin.LOCAL_UI.value)
        self.assertTrue(changes[0].watched)
        self.assertTrue(effective_state(self.user, self.item).watched)

    def test_a_local_rewatch_advances_the_log(self):
        self._enable_sync()
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        movie.watch(_dt(1))
        movie.watch(_dt(5))

        state = effective_state(self.user, self.item)
        self.assertEqual(state.play_count, 2)
        self.assertEqual(state.revision, changes_since(self.user, 0)[-1].revision)
