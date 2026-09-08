# FORK: the API's source allowlist has to cover the screen sources the
# fork's metadata layer resolves. `VALID_SOURCES` lives in upstream's
# api/helpers.py and never grew TVDB, so a tracked row from it was listable
# through GET /media/ — which does not consult the table — and 400'd on
# every keyed route. Plex writes these for sports.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from api.fork_helpers import FORK_EXTRA_SOURCES, install_fork_media_types
from api.helpers import VALID_SOURCES, check_source_type
from app.models import TV, Item, MediaTypes, Sources, Status

from .base import FloppyApiTestCase


class ForkExtraSourcesTests(FloppyApiTestCase):
    """Every source the fork can resolve is a source the API will answer for."""

    def test_tvdb_is_valid_for_the_screen_types(self):
        """TVDB resolves tv, season and episode metadata, so all three take it."""
        for media_type in (
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
            MediaTypes.EPISODE.value,
        ):
            with self.subTest(media_type=media_type):
                self.assertTrue(check_source_type(media_type, Sources.TVDB.value))

    def test_anime_takes_all_three_of_its_providers(self):
        """MAL natively, TMDB and TVDB through the grouped-anime route."""
        for source in (
            Sources.MAL.value,
            Sources.TMDB.value,
            Sources.TVDB.value,
        ):
            with self.subTest(source=source):
                self.assertTrue(check_source_type(MediaTypes.ANIME.value, source))

    def test_upstream_sources_survive_the_extension(self):
        """Extending a list must not displace what upstream put in it."""
        self.assertIn(Sources.TMDB.value, VALID_SOURCES[MediaTypes.TV.value])
        self.assertIn(Sources.MANUAL.value, VALID_SOURCES[MediaTypes.TV.value])
        self.assertIn(Sources.MAL.value, VALID_SOURCES[MediaTypes.ANIME.value])
        # Books are deliberately untouched: `_storyteller_book` and friends
        # resolve, but nothing on this deployment tracks one, so widening that
        # entry would close a hole no client can reach.
        self.assertNotIn(Sources.STORYTELLER.value, VALID_SOURCES[MediaTypes.BOOK.value])

    def test_an_unroutable_source_is_still_refused(self):
        """The gate still gates — this widens the table, it does not open it."""
        self.assertFalse(check_source_type(MediaTypes.TV.value, Sources.IGDB.value))
        self.assertFalse(check_source_type(MediaTypes.MOVIE.value, Sources.TVDB.value))
        self.assertFalse(check_source_type(MediaTypes.BOOK.value, "not-a-provider"))

    def test_installing_twice_does_not_duplicate(self):
        """`ready()` can run more than once; the overlay stays idempotent."""
        install_fork_media_types()
        install_fork_media_types()
        for media_type, extra in FORK_EXTRA_SOURCES.items():
            for source in extra:
                with self.subTest(media_type=media_type, source=source):
                    self.assertEqual(VALID_SOURCES[media_type].count(source), 1)


class ForkExtraSourcesEndpointTests(FloppyApiTestCase):
    """The 400 this fixes was raised before any provider was consulted."""

    def setUp(self):
        """Track a TVDB show, the way Plex writes one for a sports fixture."""
        super().setUp()
        self.tvdb_item, _ = Item.objects.get_or_create(
            media_id="399081",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            defaults={
                "title": "Premier League",
                "image": "https://artworks.thetvdb.com/banners/v4/series/399081/p.jpg",
            },
        )
        self.tvdb_tv = TV.objects.create(
            user=self.user1,
            item=self.tvdb_item,
            status=Status.IN_PROGRESS.value,
        )

    @staticmethod
    def _metadata(item, media_type):
        """The shape CompleteMediaSerializer needs, with nothing provider-specific."""
        return {
            "media_id": item.media_id,
            "source": item.source,
            "source_url": "",
            "media_type": media_type,
            "title": item.title,
            "max_progress": None,
            "image": item.image,
            "synopsis": "",
            "genres": [],
            "score": None,
            "score_count": None,
            "details": {},
            "related": {"seasons": [], "recommendations": []},
        }

    @patch("api.views.services.get_media_metadata")
    def test_tvdb_show_detail_is_reachable(self, mock_metadata):
        """The route that 400'd for every TVDB row Plex had written."""
        mock_metadata.return_value = self._metadata(
            self.tvdb_item,
            MediaTypes.TV.value,
        )

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.TV.value, Sources.TVDB.value, self.tvdb_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["media_id"], self.tvdb_item.media_id)

    def test_a_source_the_type_cannot_resolve_still_400s(self):
        """The error message this replaces is still raised where it belongs."""
        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, Sources.TVDB.value, "550"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("Cannot query", response.json()["detail"])
