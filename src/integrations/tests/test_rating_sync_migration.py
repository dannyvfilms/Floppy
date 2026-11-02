"""Upgrade/rollback must preserve watched intents and local tracking scores."""

import os
from unittest import skipIf

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires the migration graph")
class RatingSyncMigrationTests(TransactionTestCase):
    """Exercise real schema operations on the configured database backend."""

    def test_watched_delivery_and_local_score_survive_upgrade_and_rollback(self):
        before = ("integrations", "0058_psn_playtime_snapshots")
        after = ("integrations", "0059_rating_sync")
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            # Use the state of the migrations actually left applied. Other
            # apps' latest leaves can depend on later integration migrations.
            apps = executor.migrate([before]).apps
            user = apps.get_model("users", "User").objects.create(
                username="migration-rating"
            )
            item = apps.get_model("app", "Item").objects.create(
                source="tmdb",
                media_type="movie",
                media_id="550",
                title="Movie",
            )
            apps.get_model("app", "Movie").objects.create(
                user_id=user.pk, item_id=item.pk, score=8
            )
            binding = apps.get_model("integrations", "SyncBinding").objects.create(
                user_id=user.pk,
                client_kind="jellyfin",
                origin_key="migration-test",
            )
            watched = apps.get_model(
                "integrations", "OutboundStateDelivery"
            ).objects.create(
                binding_id=binding.pk,
                user_id=user.pk,
                item_id=item.pk,
                target_revision=1,
                status="pending",
                intent=False,
            )
            apps = MigrationExecutor(connection).migrate([after]).apps
            deliveries = apps.get_model("integrations", "OutboundStateDelivery").objects
            self.assertEqual(deliveries.get(pk=watched.pk).operation, "watched")
            self.assertFalse(deliveries.get(pk=watched.pk).intent)
            deliveries.create(
                binding_id=binding.pk,
                user_id=user.pk,
                item_id=item.pk,
                target_revision=1,
                operation="rating",
                rating=7,
            )
            apps = MigrationExecutor(connection).migrate([before]).apps
            surviving = apps.get_model(
                "integrations", "OutboundStateDelivery"
            ).objects.get()
            self.assertEqual(surviving.pk, watched.pk)
            self.assertEqual(surviving.status, "pending")
            self.assertFalse(surviving.intent)
            self.assertEqual(apps.get_model("app", "Movie").objects.get().score, 8)
        finally:
            MigrationExecutor(connection).migrate(latest)
