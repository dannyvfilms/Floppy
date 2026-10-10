"""A repeat provider-link upsert with unchanged data must not write."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import Item, ItemProviderLink, MediaTypes, Sources
from app.services import metadata_resolution


class ProviderLinkWriteTests(TestCase):
    """Detail pages call the upsert on GET; unchanged links stay read-only."""

    def test_unchanged_links_issue_no_writes(self):
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Linked",
        )
        metadata = {
            "media_id": "603",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "external_ids": {"imdb_id": "tt0133093"},
        }
        metadata_resolution.upsert_provider_links(item, metadata)
        item.refresh_from_db()

        with CaptureQueriesContext(connection) as captured:
            metadata_resolution.upsert_provider_links(item, metadata)

        writes = [
            query["sql"]
            for query in captured.captured_queries
            if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]
        self.assertEqual(writes, [])


class ProviderLinkIdentityTests(TestCase):
    """A link must not contradict the item's own source id."""

    def setUp(self):
        self.item = Item.objects.create(
            media_id="312878",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="D.Gray-man Hallow",
        )
        metadata_resolution.upsert_provider_links(
            self.item,
            {
                "media_id": "67145",
                "source": Sources.TMDB.value,
                "provider_external_ids": {"tvdb_id": "312878"},
            },
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
        )

    def links(self):
        return dict(
            ItemProviderLink.objects.filter(item=self.item, season_number=None)
            .values_list("provider", "provider_media_id"),
        )

    def test_legitimate_cross_provider_links_are_written(self):
        self.assertEqual(
            self.links(),
            {Sources.TMDB.value: "67145", Sources.TVDB.value: "312878"},
        )

    def test_metadata_labelled_with_the_items_own_id_is_refused(self):
        """Regression: TMDB metadata carrying the show's TVDB id as its media_id
        stored tmdb:312878 and replaced the TVDB link with a TVDB season id,
        so no import could match the show and Plex created a duplicate.
        """
        with self.assertLogs("app.services.metadata_resolution", "WARNING"):
            metadata_resolution.upsert_provider_links(
                self.item,
                {
                    "media_id": "312878",
                    "source": Sources.TMDB.value,
                    "provider_external_ids": {
                        "imdb_id": "tt5954268",
                        "tvdb_id": "5641463",
                    },
                },
                provider=Sources.TMDB.value,
                provider_media_type=MediaTypes.TV.value,
            )

        self.item.refresh_from_db()
        self.assertEqual(
            self.links(),
            {Sources.TMDB.value: "67145", Sources.TVDB.value: "312878"},
        )
        self.assertEqual(self.item.provider_external_ids["tmdb_id"], "67145")
        self.assertEqual(self.item.provider_external_ids["tvdb_id"], "312878")
        self.assertEqual(self.item.provider_external_ids["imdb_id"], "tt5954268")

    def test_season_links_are_not_checked_against_the_show_id(self):
        metadata_resolution.upsert_provider_links(
            self.item,
            {"media_id": "999", "source": Sources.TVDB.value},
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.TV.value,
            season_number=2,
        )

        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=self.item, provider=Sources.TVDB.value,
                provider_media_id="999", season_number=2,
            ).exists(),
        )
