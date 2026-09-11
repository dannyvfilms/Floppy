"""Normalized metadata projections with attribution and freshness."""

from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone

from app.models import Item
from app.models.choices import MediaTypes, Sources
from app.services.metadata_projection import STALE_AFTER_DAYS, project_item_metadata

from .base import FloppyApiTestCase


class MetadataProjectionTests(FloppyApiTestCase):
    """The projection reports what Floppy holds and where it came from."""

    def setUp(self):
        """Create an item with provider metadata."""
        super().setUp()
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={
                "title": "The Matrix",
                "synopsis": "A hacker learns.",
                "source_url": "https://example.com/603",
            },
        )

    def test_identity_carries_the_external_ids(self):
        """A client resolves items by verified id, not by title."""
        self.item.provider_external_ids = {"imdb_id": "tt0133093"}
        self.item.save(update_fields=["provider_external_ids"])

        projection = project_item_metadata(self.item)

        self.assertEqual(projection["identity"]["media_id"], "603")
        self.assertEqual(
            projection["identity"]["external_ids"]["imdb_id"],
            "tt0133093",
        )

    def test_attribution_names_the_source(self):
        """Several providers require their name to be displayed."""
        projection = project_item_metadata(self.item)

        self.assertEqual(projection["attribution"]["source"], Sources.TMDB.value)
        self.assertEqual(
            projection["attribution"]["source_url"],
            "https://example.com/603",
        )

    def test_never_refreshed_is_its_own_state(self):
        """Unknown is not stale and is not fresh."""
        projection = project_item_metadata(self.item)

        self.assertEqual(projection["freshness"]["state"], "unknown")
        self.assertIsNone(projection["freshness"]["refreshed_at"])

    def test_recent_metadata_is_fresh(self):
        """A just-synced item is not flagged."""
        self.item.metadata_refreshed_at = timezone.now()
        self.item.save(update_fields=["metadata_refreshed_at"])

        projection = project_item_metadata(self.item)

        self.assertEqual(projection["freshness"]["state"], "fresh")
        self.assertEqual(projection["freshness"]["age_days"], 0)

    def test_old_metadata_is_stale(self):
        """A client can choose to refresh rather than trust it silently."""
        self.item.metadata_refreshed_at = timezone.now() - timedelta(
            days=STALE_AFTER_DAYS + 1,
        )
        self.item.save(update_fields=["metadata_refreshed_at"])

        projection = project_item_metadata(self.item)

        self.assertEqual(projection["freshness"]["state"], "stale")

    def test_empty_fields_are_omitted(self):
        """A null is not information, and bloats every payload."""
        projection = project_item_metadata(self.item)

        self.assertNotIn("original_title", projection["fields"])
        self.assertEqual(projection["fields"]["title"], "The Matrix")

    def test_authorship_is_declared_unseparated(self):
        """The projection must not imply a split it cannot make."""
        projection = project_item_metadata(self.item)

        self.assertEqual(projection["authorship"], "unseparated")


class MetadataProjectionEndpointTests(FloppyApiTestCase):
    """The endpoint is scoped to the caller's own library."""

    def setUp(self):
        """Create a tracked item for user1."""
        super().setUp()
        self.item = self.items_by_type[MediaTypes.MOVIE.value][0]

    def test_an_untracked_item_is_not_readable(self):
        """This must not become a metadata proxy over the item table."""
        orphan, _ = Item.objects.get_or_create(
            media_id="999999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Untracked"},
        )

        response = self.client.get(
            f"/api/v1/metadata/items/{orphan.id}/",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_another_user_cannot_read_it(self):
        """Item ids are not a cross-user handle."""
        response = self.client.get(
            f"/api/v1/metadata/items/{self.item.id}/",
            **self.auth_headers2,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
