"""Tests for the media state endpoint (#1612)."""
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import Mock, patch

from app.models import MediaTypes, Movie, MoviePlay, Sources
from app.providers import services

from .base import FloppyApiTestCase

METADATA_PATH = "api.fork_views_tracking.services.get_media_metadata"


def _provider_error(status_code):
    response = Mock(status_code=status_code, headers={})
    return services.ProviderAPIError(Sources.TMDB.value, Mock(response=response))


class MediaStateTests(FloppyApiTestCase):
    """GET media/{media_type}/{source}/{media_id}/state."""

    def _get(self, media_type, source, media_id):
        return self.call_api(
            "get",
            "api_media_state",
            args=(media_type, source, media_id),
            headers=self.auth_headers,
        )

    def test_tracked_item_lists_consumptions_with_ids(self):
        """A tracked item is resolved without a provider call."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        with patch(METADATA_PATH) as lookup:
            response = self._get(item.media_type, item.source, item.media_id)
        lookup.assert_not_called()
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertTrue(body["resolved"])
        self.assertTrue(body["tracked"])
        self.assertTrue(body["consumptions"])
        self.assertIn("consumption_id", body["consumptions"][0])

    def test_movie_with_several_plays_lists_each_with_its_own_id(self):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        movie = Movie.objects.filter(user=self.user1, item=item).first()
        plays = [MoviePlay.objects.create(movie=movie) for _ in range(2)]
        response = self._get(item.media_type, item.source, item.media_id)
        ids = {entry["consumption_id"] for entry in response.json()["consumptions"]}
        self.assertEqual(ids, {play.id for play in plays})

    def test_unknown_consumption_id_has_typed_404(self):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_consumption_entry_detail",
            args=(item.media_type, item.source, item.media_id, 999999),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["code"], "CONSUMPTION_NOT_FOUND")

    def test_valid_provider_item_untracked_is_200_with_no_consumptions(self):
        with patch(METADATA_PATH, return_value={"title": "Wii Fit"}):
            response = self._get(MediaTypes.GAME.value, Sources.IGDB.value, "2186")
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(
            response.json(),
            {
                "media": {
                    "media_type": "game",
                    "source": "igdb",
                    "media_id": "2186",
                    "title": "Wii Fit",
                },
                "resolved": True,
                "tracked": False,
                "consumptions": [],
            },
        )

    def test_unknown_provider_id_is_typed_404(self):
        with patch(METADATA_PATH, side_effect=_provider_error(HTTP.NOT_FOUND)):
            response = self._get(MediaTypes.GAME.value, Sources.IGDB.value, "0")
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["code"], "MEDIA_NOT_FOUND")

    def test_provider_outage_is_retryable_503(self):
        with patch(METADATA_PATH, side_effect=_provider_error(HTTP.BAD_GATEWAY)):
            response = self._get(MediaTypes.GAME.value, Sources.IGDB.value, "2186")
        self.assertEqual(response.status_code, HTTP.SERVICE_UNAVAILABLE)
        body = response.json()
        self.assertEqual(body["code"], "PROVIDER_UNAVAILABLE")
        self.assertTrue(body["retryable"])

    def test_untracked_manual_item_is_not_found_without_provider_call(self):
        with patch(METADATA_PATH) as lookup:
            response = self._get(MediaTypes.GAME.value, Sources.MANUAL.value, "nope")
        lookup.assert_not_called()
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["code"], "MEDIA_NOT_FOUND")

    def test_invalid_source_for_type_is_400(self):
        response = self._get(MediaTypes.MOVIE.value, Sources.IGDB.value, "1")
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class MediaSeasonEpisodeStateTests(FloppyApiTestCase):
    """GET media/tv/{source}/{id}/{season}[/{episode}]/state."""

    def _get(self, name, *args):
        return self.call_api(
            "get",
            name,
            args=(MediaTypes.TV.value, Sources.TMDB.value, *args),
            headers=self.auth_headers,
        )

    def test_tracked_season_reports_consumptions(self):
        with patch(METADATA_PATH) as lookup:
            response = self._get("api_media_season_state", "1001", "1")
        lookup.assert_not_called()
        body = response.json()
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(body["tracked"])
        self.assertEqual(body["media"]["season_number"], 1)
        self.assertTrue(body["consumptions"])

    def test_untracked_season_is_resolved_via_provider(self):
        with patch(METADATA_PATH, return_value={"title": "Season 9"}):
            response = self._get("api_media_season_state", "1001", "9")
        body = response.json()
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(body["resolved"])
        self.assertFalse(body["tracked"])
        self.assertEqual(body["consumptions"], [])

    def test_untracked_episode_checked_against_season_episodes(self):
        season = {"episodes": [{"episode_number": 7, "title": "Seven"}]}
        with patch(METADATA_PATH, return_value=season):
            found = self._get("api_media_episode_state", "1001", "9", "7")
            missing = self._get("api_media_episode_state", "1001", "9", "8")
        self.assertEqual(found.status_code, HTTP.OK)
        self.assertEqual(found.json()["media"]["title"], "Seven")
        self.assertFalse(found.json()["tracked"])
        self.assertEqual(missing.status_code, HTTP.NOT_FOUND)
        self.assertEqual(missing.json()["code"], "MEDIA_NOT_FOUND")

    def test_season_provider_outage_is_503(self):
        with patch(METADATA_PATH, side_effect=_provider_error(HTTP.BAD_GATEWAY)):
            response = self._get("api_media_season_state", "1001", "9")
        self.assertEqual(response.status_code, HTTP.SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "PROVIDER_UNAVAILABLE")
