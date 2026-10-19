"""A field the provider never returns must not force a live refetch every visit."""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    BackfillReconcileState,
    Item,
    MediaTypes,
    MetadataProviderPreference,
    Movie,
    Sources,
    Status,
)


class DetailForcedRefetchTests(TestCase):
    """The secondary fragment refetches a missing original title once a day."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="refetch")
        cls.user.title_display_preference = "original"
        cls.user.save()
        cls.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="No Original Title",
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    @patch("app.providers.services.get_media_metadata")
    def test_return_to_server_default_uses_provider_while_repair_is_pending(self, metadata):
        self.item.metadata_fetched_at = timezone.now()
        self.item.synopsis = "Una sinopsis antigua."
        self.item.save(update_fields=["metadata_fetched_at", "synopsis"])
        BackfillReconcileState.objects.create(
            key=f"metadata_language:{self.user.pk}:{settings.TMDB_LANG}",
        )
        metadata.return_value = {
            "media_id": "238", "title": "The Godfather",
            "synopsis": "An English overview.",
            "media_type": "movie", "source": "tmdb", "max_progress": 1,
            "details": {}, "related": {}, "cast": [], "crew": [],
        }
        response = self.client.get(reverse("media_details", kwargs={
            "source": "tmdb", "media_type": "movie", "media_id": "238",
            "title": "the-godfather",
        }))
        self.assertContains(response, "An English overview.")
        self.assertEqual(metadata.call_args.kwargs["language"], settings.TMDB_LANG)

    @patch("app.providers.services.get_media_metadata")
    def test_item_language_override_bypasses_stored_english_shell(self, metadata):
        self.item.metadata_fetched_at = timezone.now()
        self.item.synopsis = "Stored English overview."
        self.item.save(update_fields=["metadata_fetched_at", "synopsis"])
        MetadataProviderPreference.objects.create(
            user=self.user, item=self.item, language="es-ES",
        )
        metadata.return_value = {
            "media_id": "238", "title": "El padrino",
            "synopsis": "La historia de una familia.",
            "media_type": "movie", "source": "tmdb", "max_progress": 1,
            "details": {}, "related": {}, "cast": [], "crew": [],
        }
        response = self.client.get(reverse("media_details", kwargs={
            "source": "tmdb", "media_type": "movie", "media_id": "238",
            "title": "the-godfather",
        }))
        self.assertContains(response, "La historia de una familia.")
        self.assertEqual(metadata.call_args.kwargs["language"], "es-ES")

    @patch("integrations.tasks.fetch_collection_metadata_for_item.delay")
    @patch("app.views.credits.sync_item_credits_from_metadata")
    @patch("app.views.metadata_utils.apply_item_metadata", return_value=[])
    @patch("app.providers.services.get_media_metadata")
    def test_existing_english_metadata_localizes_on_open_without_manual_sync(
        self, mock_metadata, *_mocks,
    ):
        self.user.metadata_language = "es-ES"
        self.user.title_display_preference = "localized"
        self.user.save(update_fields=["metadata_language", "title_display_preference"])
        self.item.metadata_fetched_at = timezone.now()
        self.item.synopsis = "An English overview."
        self.item.save(update_fields=["metadata_fetched_at", "synopsis"])
        Movie.objects.bulk_create([
            Movie(item=self.item, user=self.user, status=Status.PLANNING.value),
        ])
        mock_metadata.return_value = {
            "media_id": "238", "title": "El padrino",
            "original_title": "The Godfather", "localized_title": "El padrino",
            "synopsis": "La historia de una familia.",
            "media_type": MediaTypes.MOVIE.value, "source": Sources.TMDB.value,
            "max_progress": 1, "details": {}, "related": {},
            "cast": [], "crew": [], "studios_full": [],
        }
        url = reverse("media_details", kwargs={
            "source": self.item.source, "media_type": self.item.media_type,
            "media_id": self.item.media_id, "title": "the-godfather",
        })

        response = self.client.get(url)
        self.assertContains(response, "La historia de una familia.")
        self.assertEqual(mock_metadata.call_args.kwargs["language"], "es-ES")

        self.client.get(url, {"fragment": "secondary"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.localized_title, "El padrino")
        self.assertEqual(self.item.synopsis, "La historia de una familia.")

    @patch("integrations.tasks.fetch_collection_metadata_for_item.delay")
    @patch("app.views.credits.sync_item_credits_from_metadata")
    @patch("app.views.metadata_utils.apply_item_metadata", return_value=[])
    @patch("app.providers.services.get_media_metadata")
    def test_missing_original_title_refetches_once(self, mock_metadata, *_mocks):
        mock_metadata.return_value = {
            "media_id": "238",
            "title": "No Original Title",
            "media_type": MediaTypes.MOVIE.value,
            "source": Sources.TMDB.value,
            "max_progress": 1,
            "details": {},
            "related": {},
            "cast": [],
            "crew": [],
            "studios_full": [],
        }
        url = reverse(
            "media_details",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "238",
                "title": "no-original-title",
            },
        )

        self.client.get(url, {"fragment": "secondary"})
        calls_after_first_visit = mock_metadata.call_count
        self.client.get(url, {"fragment": "secondary"})

        # The second visit makes only the fragment's normal lookup, not the
        # extra forced refetch.
        self.assertEqual(
            mock_metadata.call_count - calls_after_first_visit,
            calls_after_first_visit - 1,
        )
