"""Upgrade fences preserve old provider state without promising old continuity."""

import os
import uuid
from unittest import skipIf

from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires migration replay")
class ReliableSyncMigrationTests(TransactionTestCase):
    """Exercise the real pre-contract schema and its data migration."""

    def _exercise_upgrade(self, *, drift=False):
        """An active provider survives upgrade; earlier gaps cannot appear complete."""
        executor = MigrationExecutor(connection)
        after = executor.loader.graph.leaf_nodes()
        before = [node for node in after if node[0] != "app"] + [
            ("app", "0215_video_game_tag")
        ]
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            user = apps.get_model("users", "User").objects.create(
                username="upgrade-sync", token="upgrade-test-token"
            )
            sequence = apps.get_model("app", "WatchStateSequence").objects.create(
                user_id=user.pk, emit_changes=True, last_sequence=5
            )
            item = apps.get_model("app", "Item").objects.create(
                media_type="movie", source="tmdb", media_id="993301", title="Upgrade"
            )
            apps.get_model("app", "WatchStateChange").objects.create(
                user_id=user.pk,
                item_id=item.pk,
                sequence=2,
                revision=1,
                watched=True,
                play_count=1,
                origin_kind="local_ui",
                correlation_id=uuid.uuid4(),
            )
            apps.get_model("app", "ProgressChange").objects.create(
                user_id=user.pk,
                item_id=item.pk,
                sequence=5,
                position_seconds=30,
                correlation_id=uuid.uuid4(),
            )
            binding = apps.get_model("integrations", "SyncBinding").objects.create(
                user_id=user.pk,
                client_kind="generic",
                origin_key="upgrade-sync-binding",
                status="active",
                approved_capabilities=["watched.read"],
                approved_directions=["inbound"],
            )
            executor = MigrationExecutor(connection)
            if drift:
                state = executor.loader.project_state(before)
                migration = executor.loader.get_migration("app", "0216_reliable_sync_contract")
                for operation in migration.operations:
                    if isinstance(operation, migrations.AddField):
                        following = state.clone()
                        operation.state_forwards("app", following)
                        with connection.schema_editor() as editor:
                            operation.database_forwards("app", editor, state, following)
                        state = following
            executor.migrate(after)
            apps = executor.loader.project_state(after).apps
            upgraded = apps.get_model("app", "WatchStateSequence").objects.get(
                pk=sequence.pk
            )
            self.assertEqual(
                apps.get_model("integrations", "SyncBinding")
                .objects.get(pk=binding.pk)
                .status,
                "active",
            )
            self.assertTrue(upgraded.emit_changes)
            self.assertFalse(upgraded.api_feed_enabled)
            self.assertEqual(upgraded.last_sequence, 6)
            self.assertEqual(upgraded.watched_cursor_floor, 6)
            self.assertEqual(upgraded.progress_cursor_floor, 6)
            self.assertEqual(upgraded.watched_pruned_through, 0)
            self.assertIsNotNone(upgraded.sync_generation)
            self.assertEqual(
                apps.get_model("app", "WatchStateChange")
                .objects.filter(user_id=user.pk)
                .count(),
                1,
            )
            self.assertEqual(
                apps.get_model("app", "ProgressChange")
                .objects.filter(user_id=user.pk)
                .count(),
                1,
            )
        finally:
            MigrationExecutor(connection).migrate(after)

    def test_existing_emission_and_history_are_preserved_and_fenced(self):
        """Preserve native provider state and fence earlier recording gaps."""
        self._exercise_upgrade()

    def test_existing_columns_do_not_break_upgrade_replay(self):
        """Recover a partially applied schema without manually faking migrations."""
        self._exercise_upgrade(drift=True)
