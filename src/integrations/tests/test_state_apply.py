"""The apply algorithm: every classification, and every refusal to write.

Most of these tests assert that nothing happened. That is the point — the
failures worth preventing here are writes, not missing writes. A wrong
"watched" costs a checkmark; a wrong "unwatched" costs someone's history.
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
)
from app.services.watch_state import effective_state, record_state_change
from integrations.models import (
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_PLAYED,
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
    ProviderStateObservation,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncBindingStatus,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.apply import (
    ObservedState,
    Outcome,
    apply_observation,
    resolve_conflict,
)
from integrations.state.identity import (
    activate_binding,
    deactivate_binding,
    get_or_create_binding,
    narrow_instance_key,
    require_reapproval_on_profile_change,
)


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day, hour=12):
    return datetime.datetime(2026, 4, day, hour, tzinfo=datetime.UTC)


class ApplyTestCase(TestCase):
    """Shared fixture: one user, one movie item, one active inbound binding."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item, _ = Item.objects.get_or_create(
            media_id="2000",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="server-1",
            profile_key="user-1",
        )
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_WATCHED_READ, CAPABILITY_WATCHED_WRITE_PLAYED],
            directions=[SyncDirection.INBOUND.value],
        )

    def _local_watch(self, day=1, play_count=1):
        """Move local state through the normal change path."""
        return record_state_change(
            self.user,
            self.item,
            watched=True,
            play_count=play_count,
            watched_at=_dt(day),
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key="local",
        )

    def _observe(self, **kwargs):
        return apply_observation(
            self.binding,
            self.item,
            ObservedState(**{"watched": True, **kwargs}),
        )


class BindingGateTests(ApplyTestCase):
    def test_a_disabled_binding_writes_nothing(self):
        deactivate_binding(self.binding)

        result = self._observe(play_count=1, watched_at=_dt(1))

        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertIsNone(effective_state(self.user, self.item))

    def test_a_killed_binding_writes_nothing(self):
        self.binding.kill_switch = True
        self.binding.save(update_fields=["kill_switch"])

        result = self._observe(play_count=1, watched_at=_dt(1))

        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertIsNone(effective_state(self.user, self.item))


class BaselineTests(ApplyTestCase):
    def test_an_unwatched_first_observation_is_a_baseline_not_an_instruction(self):
        """Absence of a watch is not an instruction to unwatch.

        This is what stops connecting a provider from wiping a library that the
        provider simply does not know about.
        """
        result = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=False),
        )

        self.assertEqual(result.outcome, Outcome.CONVERGENT)
        self.assertIsNone(effective_state(self.user, self.item))
        self.assertEqual(WatchStateChange.objects.count(), 0)
        self.assertTrue(
            ProviderStateObservation.objects.filter(
                binding=self.binding,
                item=self.item,
            ).exists(),
        )

    def test_a_watched_first_observation_applies(self):
        result = self._observe(play_count=1, watched_at=_dt(1))

        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertTrue(effective_state(self.user, self.item).watched)


class ReplayAndConvergenceTests(ApplyTestCase):
    def test_a_replayed_event_is_not_a_second_play(self):
        first = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=True, play_count=1, watched_at=_dt(1)),
            origin_event_id="evt-1",
        )
        second = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=True, play_count=2, watched_at=_dt(2)),
            origin_event_id="evt-1",
        )

        self.assertEqual(first.outcome, Outcome.APPLIED)
        self.assertEqual(second.outcome, Outcome.REPLAY)
        self.assertEqual(effective_state(self.user, self.item).play_count, 1)
        self.assertEqual(WatchStateChange.objects.count(), 1)

    def test_agreement_writes_nothing(self):
        self._local_watch(day=1)
        before = WatchStateChange.objects.count()

        result = self._observe(play_count=1, watched_at=_dt(1))

        self.assertEqual(result.outcome, Outcome.CONVERGENT)
        self.assertEqual(WatchStateChange.objects.count(), before)


class FastForwardTests(ApplyTestCase):
    def _establish_agreement(self):
        """Get both sides onto a shared, recorded ancestor."""
        self._local_watch(day=1)
        self._observe(play_count=1, watched_at=_dt(1))

    def test_a_remote_change_applies_when_nothing_local_moved(self):
        self._establish_agreement()

        result = self._observe(play_count=2, watched_at=_dt(5))

        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertEqual(effective_state(self.user, self.item).play_count, 2)

    def test_a_remote_unwatch_is_refused_without_the_capability(self):
        self._establish_agreement()

        result = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=False),
        )

        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertTrue(effective_state(self.user, self.item).watched)

    def test_a_remote_unwatch_applies_when_the_capability_was_granted(self):
        self._establish_agreement()
        activate_binding(
            self.binding,
            capabilities=[
                CAPABILITY_WATCHED_READ,
                CAPABILITY_WATCHED_WRITE_PLAYED,
                CAPABILITY_WATCHED_WRITE_UNPLAYED,
            ],
            directions=[SyncDirection.INBOUND.value],
        )

        result = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=False),
        )

        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertFalse(effective_state(self.user, self.item).watched)

    def test_a_stale_remote_assertion_does_not_roll_us_back(self):
        self._establish_agreement()
        self._local_watch(day=9, play_count=2)

        result = self._observe(play_count=1, watched_at=_dt(1))

        self.assertEqual(result.outcome, Outcome.STALE_REMOTE)
        self.assertEqual(effective_state(self.user, self.item).play_count, 2)


class DivergenceTests(ApplyTestCase):
    def _diverge(self):
        """Both sides move off a shared ancestor."""
        self._local_watch(day=1)
        self._observe(play_count=1, watched_at=_dt(1))
        # Local moves on.
        self._local_watch(day=9, play_count=3)

    def test_a_remote_watch_unions_with_a_local_unwatch(self):
        record_state_change(
            self.user,
            self.item,
            watched=False,
            play_count=0,
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key="local",
        )
        self._observe(play_count=0, watched=False)
        self._local_watch(day=2)
        record_state_change(
            self.user,
            self.item,
            watched=False,
            play_count=0,
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key="local",
        )

        result = self._observe(play_count=1, watched_at=_dt(4))

        self.assertEqual(result.outcome, Outcome.APPLIED)
        self.assertTrue(effective_state(self.user, self.item).watched)

    def test_a_remote_unwatch_while_diverged_is_held_not_applied(self):
        self._diverge()

        result = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=False),
        )

        self.assertEqual(result.outcome, Outcome.CONFLICT)
        state = effective_state(self.user, self.item)
        self.assertTrue(state.watched, "local history must survive")
        self.assertTrue(state.conflicted)
        self.assertEqual(
            result.conflict.reason,
            StateConflictReason.DIVERGENT_WATCHED.value,
        )

    def test_a_repeated_disagreement_counts_rather_than_accumulates(self):
        self._diverge()
        apply_observation(self.binding, self.item, ObservedState(watched=False))
        apply_observation(self.binding, self.item, ObservedState(watched=False))

        conflicts = StateConflict.objects.filter(user=self.user)
        self.assertEqual(conflicts.count(), 1)

    def test_a_held_item_stops_moving_for_that_binding(self):
        self._diverge()
        apply_observation(self.binding, self.item, ObservedState(watched=False))
        revision_when_held = effective_state(self.user, self.item).revision

        result = self._observe(play_count=99, watched_at=_dt(20))

        self.assertEqual(result.outcome, Outcome.SKIPPED)
        self.assertEqual(
            effective_state(self.user, self.item).revision,
            revision_when_held,
        )

    def test_resolving_a_conflict_creates_a_new_revision_and_resumes(self):
        self._diverge()
        conflict = apply_observation(
            self.binding,
            self.item,
            ObservedState(watched=False),
        ).conflict
        held_revision = effective_state(self.user, self.item).revision

        resolve_conflict(conflict, watched=False, play_count=0)

        state = effective_state(self.user, self.item)
        self.assertFalse(state.watched)
        self.assertFalse(state.conflicted)
        self.assertGreater(state.revision, held_revision)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, StateConflictStatus.RESOLVED.value)


class BindingIdentityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")

    def test_a_new_binding_can_do_nothing(self):
        binding, created = get_or_create_binding(
            self.user,
            SyncClientKind.EMBY.value,
            instance_key="server-1",
            profile_key="user-1",
        )

        self.assertTrue(created)
        self.assertEqual(binding.status, SyncBindingStatus.PENDING.value)
        self.assertFalse(binding.is_operational())
        self.assertEqual(binding.approved_capabilities, [])

    def test_activation_moves_no_state(self):
        item, _ = Item.objects.get_or_create(
            media_id="2001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        changes_before = WatchStateChange.objects.count()

        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        self.assertEqual(WatchStateChange.objects.count(), changes_before)
        self.assertEqual(ProviderStateObservation.objects.count(), 0)

    def test_activation_turns_the_local_change_log_on(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        self.assertFalse(
            self.user.watch_state_sequence.emit_changes
            if hasattr(self.user, "watch_state_sequence")
            else False,
        )

        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.watch_state_sequence.emit_changes)

        deactivate_binding(binding)
        self.user.watch_state_sequence.refresh_from_db()
        self.assertFalse(self.user.watch_state_sequence.emit_changes)

    def test_an_empty_instance_is_narrowed_without_reapproval(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            profile_key="u",
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        narrow_instance_key(binding, "server-7")

        binding.refresh_from_db()
        self.assertEqual(binding.instance_key, "server-7")
        self.assertTrue(binding.is_operational())

    def test_a_different_instance_stops_the_binding(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="server-1",
            profile_key="u",
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        narrow_instance_key(binding, "server-2")

        binding.refresh_from_db()
        self.assertEqual(binding.status, SyncBindingStatus.NEEDS_REAPPROVAL.value)
        self.assertFalse(binding.is_operational())

    def test_a_changed_profile_stops_the_binding(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="server-1",
            profile_key="user-1",
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        require_reapproval_on_profile_change(binding, "user-2")

        binding.refresh_from_db()
        self.assertFalse(binding.is_operational())

    def test_reapproving_with_fewer_capabilities_revokes(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        activate_binding(
            binding,
            capabilities=[
                CAPABILITY_WATCHED_READ,
                CAPABILITY_WATCHED_WRITE_UNPLAYED,
            ],
            directions=[SyncDirection.INBOUND.value],
        )

        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        binding.refresh_from_db()
        self.assertFalse(binding.has_capability(CAPABILITY_WATCHED_WRITE_UNPLAYED))

    def test_a_direction_without_its_capability_allows_nothing(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        self.assertFalse(
            binding.allows(
                SyncDirection.INBOUND.value,
                CAPABILITY_WATCHED_WRITE_UNPLAYED,
            ),
        )
        self.assertFalse(
            binding.allows(
                SyncDirection.OUTBOUND.value,
                CAPABILITY_WATCHED_READ,
            ),
        )


class JellyfinBindingMigrationMappingTests(TestCase):
    """The mapping must preserve permissions exactly, in both directions."""

    @staticmethod
    def _mapping_module():
        import importlib

        return importlib.import_module(
            "integrations.migrations.0038_backfill_jellyfin_binding",
        )

    def test_push_enabled_without_a_schedule_grants_no_write_direction(self):
        """`push_watched_enabled` defaults True but pushes nothing on its own.

        Granting outbound on that flag alone would hand a write direction to
        every Jellyfin user who never turned pushing on.
        """
        module = self._mapping_module()

        class _User:
            jellyfin_mark_played_enabled = False
            jellyfin_mark_unplayed_enabled = False

        class _Account:
            pull_history_enabled = True
            push_watched_enabled = True
            push_unwatched_enabled = False
            scheduled_push_enabled = False
            instant_push_enabled = False

        capabilities, directions = module._capabilities_for(_User(), _Account())

        self.assertNotIn("outbound", directions)
        self.assertNotIn("watched.push_played", capabilities)
        self.assertIn("inbound", directions)

    def test_push_with_a_schedule_grants_the_outbound_direction(self):
        module = self._mapping_module()

        class _User:
            jellyfin_mark_played_enabled = True
            jellyfin_mark_unplayed_enabled = False

        class _Account:
            pull_history_enabled = True
            push_watched_enabled = True
            push_unwatched_enabled = False
            scheduled_push_enabled = True
            instant_push_enabled = False

        capabilities, directions = module._capabilities_for(_User(), _Account())

        self.assertIn("outbound", directions)
        self.assertIn("watched.push_played", capabilities)
        self.assertIn("watched.write_played", capabilities)
        self.assertNotIn("watched.push_unplayed", capabilities)
        self.assertNotIn("watched.write_unplayed", capabilities)
