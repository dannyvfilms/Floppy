"""SQLite must preserve unknown activity dates while widening the field."""

import os
from unittest import skipIf, skipUnless

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires migration replay")
@skipUnless(connection.vendor == "sqlite", "Reproduces SQLite schema drift")
class NullableProgressedAtMigrationTests(TransactionTestCase):
    """Preserve legacy NULL values when SQLite rebuilds a media table."""

    def test_unknown_progressed_at_survives_nullable_field_migration(self):
        before = ("app", "0228_deletedentry")
        after = ("app", "0229_nullable_progressed_at")
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()

        try:
            apps = executor.migrate([before]).apps
            user = apps.get_model("users", "User").objects.create(
                username="migration-null-progressed-at",
            )
            item = apps.get_model("app", "Item").objects.create(
                source="manual",
                media_type="game",
                title="Legacy Game",
            )
            game_model = apps.get_model("app", "Game")
            game = game_model.objects.create(user_id=user.pk, item_id=item.pk)

            # Reproduce a legacy database whose physical column permits NULL
            # although the recorded migration state still says NOT NULL.
            old_field = game_model._meta.get_field("progressed_at")
            nullable_field = old_field.clone()
            nullable_field.set_attributes_from_name(old_field.name)
            nullable_field.null = True
            nullable_field.model = game_model
            with connection.schema_editor() as schema_editor:
                schema_editor.alter_field(
                    game_model,
                    old_field,
                    nullable_field,
                    strict=True,
                )
            game_model.objects.filter(pk=game.pk).update(progressed_at=None)

            migrated_apps = MigrationExecutor(connection).migrate([after]).apps
            migrated_game = migrated_apps.get_model("app", "Game").objects.get(
                pk=game.pk,
            )
            self.assertIsNone(migrated_game.progressed_at)
        finally:
            MigrationExecutor(connection).migrate(latest)
