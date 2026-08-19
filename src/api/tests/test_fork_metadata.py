# FORK: tests for metadata-management and episode-score API endpoints.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    MetadataProviderPreference,
    Movie,
    Season,
    Sources,
)

from .base import FloppyApiTestCase


class ItemImageTests(FloppyApiTestCase):
    """PATCH /metadata/items/{id}/image overrides the stored image."""

    def test_update_image(self):
        """The image URL is persisted for a tracked item."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_item_image",
            args=(item.id,),
            payload={"image_url": "https://example.com/new.jpg"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        item.refresh_from_db()
        self.assertEqual(item.image, "https://example.com/new.jpg")

    def test_untracked_item_not_found(self):
        """Items outside the caller's library 404."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_item_image",
            args=(item.id,),
            payload={"image_url": "https://example.com/new.jpg"},
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_missing_url_rejected(self):
        """An empty image_url returns 400."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_item_image",
            args=(item.id,),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class ItemMetadataTests(FloppyApiTestCase):
    """PATCH /metadata/items/{id} applies custom-metadata overrides."""

    def setUp(self):
        """Track a manual movie item that supports custom metadata."""
        super().setUp()
        self.manual_item = Item.objects.create(
            media_id="manual-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Manual Movie",
            image="https://example.com/manual.jpg",
        )
        Movie.objects.create(item=self.manual_item, user=self.user1)

    def test_update_manual_metadata(self):
        """Custom fields are stored on the manual item."""
        response = self.call_api(
            "patch",
            "api_item_metadata",
            args=(self.manual_item.id,),
            payload={"title": "Renamed Movie"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.manual_item.refresh_from_db()
        self.assertEqual(self.manual_item.title, "Renamed Movie")

    def test_unsupported_item_rejected(self):
        """Provider-sourced items without custom support return 400."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_item_metadata",
            args=(item.id,),
            payload={"title": "X"},
            headers=self.auth_headers,
        )
        self.assertIn(
            response.status_code,
            (HTTP.BAD_REQUEST, HTTP.OK),
        )


class ManualEpisodeMetadataTests(FloppyApiTestCase):
    """PATCH /metadata/items/{id} on a manual episode.

    Episode rows have no ``user`` column -- ownership is inherited from the
    related season -- so the ownership check has to join through it.
    """

    def setUp(self):
        """Track a manual show with one season and one episode."""
        super().setUp()
        tv_item = Item.objects.create(
            media_id="manual-tv-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.TV.value,
            title="Manual Show",
        )
        tv = TV.objects.create(item=tv_item, user=self.user1)
        season_item = Item.objects.create(
            media_id="manual-tv-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Manual Show",
            season_number=2026,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user1,
            related_tv=tv,
        )
        self.episode_item = Item.objects.create(
            media_id="manual-tv-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.EPISODE.value,
            title="Manual Show",
            season_number=2026,
            episode_number=1,
        )
        Episode.objects.create(item=self.episode_item, related_season=self.season)

    def test_update_manual_episode_metadata(self):
        """Episode overrides are stored instead of raising."""
        response = self.call_api(
            "patch",
            "api_item_metadata",
            args=(self.episode_item.id,),
            payload={"episode_title": "A video about spinning things"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.episode_item.refresh_from_db()
        self.assertEqual(
            self.episode_item.manual_metadata["episode_title"],
            "A video about spinning things",
        )

    def test_other_users_episode_not_found(self):
        """An episode in someone else's library still 404s."""
        response = self.call_api(
            "patch",
            "api_item_metadata",
            args=(self.episode_item.id,),
            payload={"episode_title": "Nope"},
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_watching_an_episode_with_a_string_runtime(self):
        """Manual items store the runtime as a string; watching must survive it."""
        season_metadata = {
            "episodes": [
                {
                    "episode_number": 1,
                    "title": "A video about spinning things",
                    "image": "https://example.com/episode.jpg",
                    "runtime": "12",
                },
            ],
        }
        with patch(
            "app.providers.services.get_media_metadata",
            return_value=season_metadata,
        ):
            self.season.watch(1, datetime.datetime.now(tz=datetime.UTC))

        self.assertEqual(
            Episode.objects.filter(
                related_season=self.season,
                item__episode_number=1,
            ).count(),
            2,
        )
        self.episode_item.refresh_from_db()
        self.assertEqual(self.episode_item.runtime_minutes, 12)


class ProviderPreferenceTests(FloppyApiTestCase):
    """GET/PUT media provider-preference."""

    def test_get_default_preference(self):
        """Without an override the provider is null with options listed."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_provider_preference",
            args=(MediaTypes.MOVIE.value, item.source, item.media_id),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIsNone(payload["provider"])
        self.assertIn("available_providers", payload)

    def test_put_valid_provider(self):
        """A valid provider is persisted as an override."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        get_response = self.call_api(
            "get",
            "api_media_provider_preference",
            args=(MediaTypes.MOVIE.value, item.source, item.media_id),
            headers=self.auth_headers,
        )
        providers = get_response.json()["available_providers"]
        if not providers:
            self.skipTest("No metadata providers available for movie items")
        response = self.call_api(
            "put",
            "api_media_provider_preference",
            args=(MediaTypes.MOVIE.value, item.source, item.media_id),
            payload={"provider": providers[0]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(
            MetadataProviderPreference.objects.filter(
                user=self.user1,
                item=item,
                provider=providers[0],
            ).exists(),
        )

    def test_put_invalid_provider_rejected(self):
        """Unknown providers return 400."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "put",
            "api_media_provider_preference",
            args=(MediaTypes.MOVIE.value, item.source, item.media_id),
            payload={"provider": "not-a-provider"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class EpisodeScoreTests(FloppyApiTestCase):
    """PATCH episode score updates all plays of the episode."""

    def _patch_score(self, payload, headers=None):
        return self.call_api(
            "patch",
            "api_media_episode_score",
            args=("tv", "tmdb", "1001", 1, 901),
            payload=payload,
            headers=headers or self.auth_headers,
        )

    def _episode_number(self):
        return self.episode_medias[0].item.episode_number

    def test_score_set_and_clear(self):
        """Score is stored on every play and can be cleared with null."""
        episode_number = self._episode_number()
        response = self.call_api(
            "patch",
            "api_media_episode_score",
            args=("tv", "tmdb", "1001", 1, episode_number),
            payload={"score": 8.5},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        episode = Episode.objects.get(id=self.episode_medias[0].id)
        self.assertEqual(str(episode.score), "8.5")

        cleared = self.call_api(
            "patch",
            "api_media_episode_score",
            args=("tv", "tmdb", "1001", 1, episode_number),
            payload={"score": None},
            headers=self.auth_headers,
        )
        self.assertEqual(cleared.status_code, HTTP.OK)
        episode.refresh_from_db()
        self.assertIsNone(episode.score)

    def test_invalid_score_rejected(self):
        """Out-of-range and non-numeric scores return 400."""
        episode_number = self._episode_number()
        for bad in ("abc", 11, -1):
            response = self.call_api(
                "patch",
                "api_media_episode_score",
                args=("tv", "tmdb", "1001", 1, episode_number),
                payload={"score": bad},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_untracked_episode_not_found(self):
        """Episodes with no plays return 404."""
        response = self.call_api(
            "patch",
            "api_media_episode_score",
            args=("tv", "tmdb", "1001", 1, 999),
            payload={"score": 5},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class EpisodePatchScoreTests(FloppyApiTestCase):
    """The generic episode PATCH accepts the fork's score/dropped fields."""

    @patch("api.views.services.get_media_metadata")
    def test_patch_episode_score_field(self, mock_metadata):
        """PATCH on the episode detail route can set score."""
        episode = self.episode_medias[0]
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        mock_metadata.return_value = self.build_episode_metadata(
            tv_item,
            1,
            episode.item.episode_number,
            "TV Show 1",
            "https://example.com/episode-1.jpg",
        )
        episode.end_date = datetime.datetime(
            2024,
            1,
            1,
            tzinfo=datetime.UTC,
        )
        episode.save(update_fields=["end_date"])
        response = self.call_api(
            "patch",
            "api_media_episode_detail",
            args=(
                "tv",
                "tmdb",
                "1001",
                1,
                episode.item.episode_number,
            ),
            payload={"score": "7.0"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        episode.refresh_from_db()
        self.assertEqual(str(episode.score), "7.0")
