from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase, TestCase

from app import credits
from app.models import Item, MediaTypes, Sources, Studio


class ProviderStorageResilienceTests(TestCase):
    """Provider metadata must not fail because an opaque URL exceeds 200 chars."""

    def test_studio_logo_storage_is_not_capped_at_urlfield_default(self):
        field = Studio._meta.get_field("logo")

        self.assertIsNone(field.max_length)

    def test_credit_sync_preserves_long_studio_logo(self):
        item = Item.objects.create(
            media_id="125988",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Silo",
        )
        long_logo = "https://image.tmdb.org/t/p/original/" + ("signed-segment-" * 24)
        self.assertGreater(len(long_logo), 200)

        credits.sync_item_credits_from_metadata(
            item,
            {
                "cast": [],
                "crew": [],
                "studios_full": [
                    {
                        "studio_id": "1632",
                        "name": "Long URL Studio",
                        "logo": long_logo,
                    },
                ],
            },
        )

        studio = Studio.objects.get(
            source=Sources.TMDB.value,
            source_studio_id="1632",
        )
        self.assertEqual(studio.logo, long_logo)
        self.assertTrue(item.studio_credits.filter(studio=studio).exists())


class PlaceholderMigrationSafetyTests(SimpleTestCase):
    """The first placeholder rewrite must never overflow a bounded DB column."""

    def test_0155_skips_models_that_cannot_store_new_placeholder(self):
        migration = import_module("app.migrations.0155_rewrite_old_img_none_placeholder")
        queryset = Mock()
        manager = Mock()
        manager.filter.return_value = queryset
        field = SimpleNamespace(max_length=200)
        model = SimpleNamespace(
            _meta=SimpleNamespace(get_field=Mock(return_value=field)),
            objects=manager,
        )
        apps = SimpleNamespace(get_model=Mock(return_value=model))

        self.assertGreater(len(migration.NEW_IMG_NONE), field.max_length)

        migration.rewrite_old_placeholder(apps, schema_editor=None)

        self.assertEqual(apps.get_model.call_count, 5)
        manager.filter.assert_not_called()
        queryset.update.assert_not_called()

    def test_0155_can_rewrite_after_storage_is_wide_enough(self):
        migration = import_module("app.migrations.0155_rewrite_old_img_none_placeholder")
        queryset = Mock()
        manager = Mock()
        manager.filter.return_value = queryset
        field = SimpleNamespace(max_length=None)
        model = SimpleNamespace(
            _meta=SimpleNamespace(get_field=Mock(return_value=field)),
            objects=manager,
        )
        apps = SimpleNamespace(get_model=Mock(return_value=model))

        migration.rewrite_old_placeholder(apps, schema_editor=None)

        self.assertEqual(manager.filter.call_count, 5)
        self.assertEqual(queryset.update.call_count, 5)
