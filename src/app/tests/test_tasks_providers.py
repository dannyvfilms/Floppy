from unittest.mock import patch

from django.test import TestCase

from app import backfill_queue, tasks_providers
from app.models import Item, MediaTypes, MetadataBackfillState, Sources


class ProviderBackfillTaskTests(TestCase):
    def setUp(self):
        backfill_queue.clear(
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY,
        )

    def test_provider_items_queryset_scopes_to_tmdb_movie_tv_anime_missing_data(self):
        needs_backfill = Item.objects.create(
            media_id="2001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Needs Providers",
        )
        already_has_data = Item.objects.create(
            media_id="2002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Has Providers",
            watch_providers={"US": {"flatrate": [{"provider_name": "Netflix"}]}},
        )
        non_tmdb_item = Item.objects.create(
            media_id="2003",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Manual Movie",
        )
        unsupported_media_type = Item.objects.create(
            media_id="2004",
            source=Sources.TMDB.value,
            media_type=MediaTypes.BOOK.value,
            title="Not a supported provider type",
        )

        queryset_ids = set(
            tasks_providers._provider_items_queryset().values_list("id", flat=True)
        )

        self.assertIn(needs_backfill.id, queryset_ids)
        self.assertNotIn(already_has_data.id, queryset_ids)
        self.assertNotIn(non_tmdb_item.id, queryset_ids)
        self.assertNotIn(unsupported_media_type.id, queryset_ids)

    @patch("app.tasks_providers.services.get_media_metadata")
    def test_populate_providers_for_items_persists_watch_providers(
        self, mock_get_metadata
    ):
        item = Item.objects.create(
            media_id="2101",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Providers Movie",
        )
        mock_get_metadata.return_value = {
            "providers": {
                "US": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]},
            },
        }

        updated_count, error_count = tasks_providers._populate_providers_for_items(
            [item]
        )

        item.refresh_from_db()
        self.assertEqual(updated_count, 1)
        self.assertEqual(error_count, 0)
        self.assertEqual(
            item.watch_providers["US"]["flatrate"][0]["provider_name"], "Netflix"
        )
        state = MetadataBackfillState.objects.get(
            item=item, field=tasks_providers.MetadataBackfillField.WATCH_PROVIDERS
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.last_success_at)

    @patch("app.tasks_providers.services.get_media_metadata")
    def test_populate_providers_for_items_records_failure_on_missing_metadata(
        self, mock_get_metadata
    ):
        item = Item.objects.create(
            media_id="2102",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="No Metadata Movie",
        )
        mock_get_metadata.return_value = None

        updated_count, error_count = tasks_providers._populate_providers_for_items(
            [item]
        )

        self.assertEqual(updated_count, 0)
        self.assertEqual(error_count, 1)
        state = MetadataBackfillState.objects.get(
            item=item, field=tasks_providers.MetadataBackfillField.WATCH_PROVIDERS
        )
        self.assertEqual(state.fail_count, 1)

    @patch("app.tasks_providers.populate_provider_backfill_queue.apply_async")
    def test_enqueue_provider_backfill_items_queues_items(self, mock_apply_async):
        item = Item.objects.create(
            media_id="2103",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Queue Movie",
        )

        queued = tasks_providers.enqueue_provider_backfill_items([item.id])

        self.assertEqual(queued, 1)
        mock_apply_async.assert_called_once()
        queue = backfill_queue.members(
            tasks_providers.WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
        )
        self.assertEqual(queue, {item.id})
