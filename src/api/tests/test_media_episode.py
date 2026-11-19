from unittest.mock import patch

from django.db.utils import OperationalError
from django.urls import reverse

from app.models import Episode, Item, MediaTypes, Sources

from .base import FloppyApiTestCase
from .helpers import (
    check_changes_history_entry_structure,
    check_consumption_structure,
    check_minimized_lists_structure,
    check_pagination_structure,
)


class MediaEpisodeTests(FloppyApiTestCase):
    """Validate episode endpoint contracts."""

    def setUp(self):
        """Use an authoritative episode list for episode-route tests."""
        super().setUp()
        self._episode_metadata_patcher = patch(
            "api.views.services.get_media_metadata",
            return_value={
                "episodes": [
                    {"episode_number": episode_number}
                    for episode_number in (1, 2, 3)
                ],
                "related": {"seasons": [{"season_number": 1}]},
            },
        )
        self._episode_metadata_patcher.start()
        self.addCleanup(self._episode_metadata_patcher.stop)

    def test_episode_endpoints_reject_non_tv_media_type(self):
        """Episode endpoints should return 400 when media_type is not tv."""
        requests = [
            (
                "get",
                "api_media_episode_detail",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "patch",
                "api_media_episode_detail",
                ("movie", "tmdb", 1, 1, 1),
                {"notes": "x"},
            ),
            (
                "delete",
                "api_media_episode_detail",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "get",
                "api_media_episode_changes_history",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "get",
                "api_media_episode_consumption_history",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "get",
                "api_media_episode_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1, 1),
                None,
            ),
            (
                "patch",
                "api_media_episode_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1, 1),
                {"notes": "x"},
            ),
            (
                "delete",
                "api_media_episode_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1, 1),
                None,
            ),
            (
                "get",
                "api_media_episode_lists",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "put",
                "api_media_episode_list_detail",
                ("movie", "tmdb", 1, 1, 1, 1),
                {},
            ),
            (
                "delete",
                "api_media_episode_list_detail",
                ("movie", "tmdb", 1, 1, 1, 1),
                None,
            ),
            (
                "post",
                "api_media_episode_sync",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
        ]

        for method, url_name, args, payload in requests:
            response = self.call_api(
                method,
                url_name,
                args=args,
                payload=payload,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 400)

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_get_returns_expected_shape(self, mock_metadata):
        """Episode detail GET should return complete serialized payload."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["media_id"], tv_item.media_id)
        self.assertEqual(payload["source"], tv_item.source)
        self.assertIn("consumptions", payload)
        self.assertIn("lists", payload)
        self.assertEqual(
            payload["details"]["season_number"], season_item.season_number
        )
        self.assertEqual(
            payload["details"]["episode_number"], episode_item.episode_number
        )
        self.assertNotIn("season_number", payload)
        self.assertNotIn("episode_number", payload)

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_get_exposes_imdb_rating(self, mock_metadata):
        """Episode detail GET should expose the episode Item's IMDb rating."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        episode_item.imdb_rating = 9.2
        episode_item.imdb_rating_count = 4321
        episode_item.save()

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imdb_rating"], 9.2)
        self.assertEqual(payload["imdb_rating_count"], 4321)

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_media_type_status_enabled_by_default(self, mock_metadata):
        """Episode detail reports tv as enabled when nothing is disabled."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["media_type_status"],
            {"media_type": "tv", "enabled": True, "message": None},
        )

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_media_type_status_disabled_via_library_media_type(
        self,
        mock_metadata,
    ):
        """A disabled anime library_media_type is surfaced with a redirect hint."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        self.user1.anime_enabled = False
        self.user1.save(update_fields=["anime_enabled"])

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            params={"library_media_type": MediaTypes.ANIME.value},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        status = response.json()["media_type_status"]
        self.assertEqual(status["media_type"], "anime")
        self.assertFalse(status["enabled"])
        self.assertIn("tv", status["message"])

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_patch_with_invalid_field_returns_400(self, mock_metadata):
        """Episode PATCH with unknown field should return 400."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "patch",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            payload={"invalid_field": "value"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_delete_not_tracked_returns_404(self, mock_metadata):
        """Episode delete of untracked episode should return 404."""
        tv_item = self.items_by_type[MediaTypes.TV.value][1]

        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=99,
            episode_number=99,
            title="Unknown Episode",
            image=None,
            synopsis="unknown",
            score=0,
            score_count=0,
        )

        response = self.call_api(
            "delete",
            "api_media_episode_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 99, 99),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_episode_consumption_history_requires_authentication(self):
        """Episode consumption history should require authentication."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        response = self.client.get(
            reverse(
                "api_media_episode_consumption_history",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    episode_item.episode_number,
                ),
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_episode_lists_requires_authentication(self):
        """Episode lists endpoint should require authentication."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        response = self.client.get(
            reverse(
                "api_media_episode_lists",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    episode_item.episode_number,
                ),
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_episode_sync_requires_valid_season(self):
        """Episode sync should reject on non-existent parent season."""
        response = self.call_api(
            "post",
            "api_media_episode_sync",
            args=(MediaTypes.TV.value, "tmdb", "99999", 1, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_episode_detail_get_invalid_media_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Episode detail GET should surface provider lookup failures."""
        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_episode_detail_get_invalid_season_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Episode detail GET should surface provider errors on invalid season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                999,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_get_invalid_episode_id_returns_not_found(
        self, mock_metadata
    ):
        """Episode detail GET should return 404 for unknown episode number."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=1,
            title="Episode 1",
            image="https://example.com/ep-1.jpg",
        )

        response = self.call_api(
            "get",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_episode_detail_patch_updates_episode_fields(self):
        """Episode detail PATCH should update tracked episode fields."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        def _metadata_side_effect(media_type, *_args, **_kwargs):
            if media_type == "tv_with_seasons":
                return {
                    f"season/{season_item.season_number}": {"episodes": [{}, {}]},
                    "related": {
                        "seasons": [{"season_number": season_item.season_number}]
                    },
                }
            if media_type == "season":
                return self.build_episode_metadata(
                    tv_item=tv_item,
                    season_number=season_item.season_number,
                    episode_number=episode_item.episode_number,
                    title=episode_item.title,
                    image=episode_item.image,
                )
            return {}

        with patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_metadata_side_effect,
        ):
            response = self.call_api(
                "patch",
                "api_media_episode_detail",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    episode_item.episode_number,
                ),
                payload={"end_date": None},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["media_type"], MediaTypes.TV.value)
        self.assertIn("consumptions", payload)
        self.assertIn("details", payload)
        self.assertIsNone(payload["consumptions"][0]["end_date"])

    @patch("api.views.services.get_media_metadata")
    def test_episode_detail_delete_tracked_episode_returns_204(self, mock_metadata):
        """Episode detail DELETE should remove tracked episode."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=tv_item,
            season_number=season_item.season_number,
            episode_number=episode_item.episode_number,
            title=episode_item.title,
            image=episode_item.image,
        )

        response = self.call_api(
            "delete",
            "api_media_episode_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)

    def test_episode_consumption_history_get_returns_paginated_payload(self):
        """Episode history endpoint should return paginated consumptions."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(
            self, payload["pagination"], total=1, limit=20, offset=0
        )
        for entry in payload["results"]:
            check_consumption_structure(self, entry)

    def test_episode_consumption_history_invalid_media_id_returns_empty_results(self):
        """Episode history endpoint should return empty results for unknown media."""
        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_episode_consumption_history_invalid_season_id_returns_empty_results(self):
        """Episode history endpoint should return empty results for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_episode_consumption_history_invalid_episode_id_returns_not_found(self):
        """Episode history endpoint should reject unknown episode numbers."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_episode_consumption_history_cleans_up_detached_episode(self):
        """Invalid history access removes the matching detached play rows."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        detached_item = Item.objects.create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            title="Detached episode",
            season_number=season_item.season_number,
            episode_number=999,
        )
        detached_episode = Episode.objects.create(
            item=detached_item,
            related_season=self.season_medias[0],
        )

        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Episode.objects.filter(pk=detached_episode.pk).exists())
        self.assertTrue(Item.objects.filter(pk=detached_item.pk).exists())

    def test_episode_history_provider_failure_preserves_detached_history(self):
        """Unavailable provider metadata must not trigger destructive cleanup."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        detached_item = Item.objects.create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            title="Detached episode",
            season_number=season_item.season_number,
            episode_number=999,
        )
        detached_episode = Episode.objects.create(
            item=detached_item,
            related_season=self.season_medias[0],
        )

        with patch(
            "api.views.services.get_media_metadata",
            side_effect=RuntimeError("provider unavailable"),
        ):
            response = self.call_api(
                "get",
                "api_media_episode_consumption_history",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    999,
                ),
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 500)
        self.assertTrue(Episode.objects.filter(pk=detached_episode.pk).exists())

    def test_episode_consumption_entry_detail_get_returns_expected_structure(self):
        """Episode history entry-detail GET should return serialized consumption."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        consumption_id = self.episode_medias[0].id

        response = self.call_api(
            "get",
            "api_media_episode_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                consumption_id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        check_consumption_structure(self, response.json())

    def test_episode_lookup_failure_returns_generic_detail(self):
        """A failed entry lookup answers with the fixed detail on each method."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        args = (
            MediaTypes.TV.value,
            tv_item.source,
            tv_item.media_id,
            season_item.season_number,
            episode_item.episode_number,
            self.episode_medias[0].id,
        )
        for method, payload in (("get", None), ("patch", {"notes": "x"}), ("delete", None)):
            with self.subTest(method=method), patch(
                "api.views.BasicMedia.objects.filter_media",
                side_effect=RuntimeError("secret /srv/private/path"),
            ):
                response = self.call_api(
                    method,
                    "api_media_episode_consumption_entry_detail",
                    args=args,
                    payload=payload,
                    headers=self.auth_headers,
                )
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"detail": "Internal Server Error"})

    def test_episode_consumption_entry_detail_delete_removes_history_entry(self):
        """Episode history entry-detail DELETE should remove an existing row."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        consumption_id = self.episode_medias[0].id

        response = self.call_api(
            "delete",
            "api_media_episode_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                consumption_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)

    def test_episode_consumption_entry_detail_patch_updates_history_entry(self):
        """Episode history entry-detail PATCH should persist valid updates."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        consumption_id = self.episode_medias[0].id

        with patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "episodes": [{"episode_number": episode_item.episode_number}],
                "related": {"seasons": [{"season_number": season_item.season_number}]},
            },
        ):
            response = self.call_api(
                "patch",
                "api_media_episode_consumption_entry_detail",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    episode_item.episode_number,
                    consumption_id,
                ),
                payload={"end_date": None},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertIsNone(payload["end_date"])

    def test_episode_consumption_entry_detail_patch_invalid_payload_returns_bad_request(
        self,
    ):
        """Episode history entry-detail PATCH should reject invalid values."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        consumption_id = self.episode_medias[0].id

        response = self.call_api(
            "patch",
            "api_media_episode_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                consumption_id,
            ),
            payload={"end_date": "invalid-date"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_episode_lists_get_returns_lists(self):
        """Episode lists endpoint should return associated lists."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        list_id = self.lists_by_name["favorites"].id

        self.call_api(
            "put",
            "api_media_episode_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        response = self.call_api(
            "get",
            "api_media_episode_lists",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for entry in payload["results"]:
            check_minimized_lists_structure(self, entry)

    def test_episode_lists_get_invalid_ids_returns_empty_results(self):
        """Episode lists endpoint should return empty results for unknown ids."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        requests = [
            (MediaTypes.TV.value, "tmdb", 999999, 1, 1),
            (MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999, 1),
            (
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999,
            ),
        ]
        for args in requests:
            response = self.call_api(
                "get",
                "api_media_episode_lists",
                args=args,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["results"], [])

    def test_episode_list_detail_put_adds_media_to_list(self):
        """Episode list-detail PUT should add episode to list."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_episode_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        for entry in response.json():
            check_minimized_lists_structure(self, entry)

    @patch("api.views.run_retryable_db_operation")
    def test_episode_list_detail_put_returns_503_on_persistent_lock(
        self,
        mock_retry,
    ):
        """Episode list-detail PUT should return 503 when the DB stays locked."""
        mock_retry.side_effect = OperationalError("database is locked")
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_episode_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.json())

    def test_episode_list_detail_delete_removes_media_from_list(self):
        """Episode list-detail DELETE should remove episode from list."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        list_id = self.lists_by_name["favorites"].id

        self.call_api(
            "put",
            "api_media_episode_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        response = self.call_api(
            "delete",
            "api_media_episode_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
                list_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)

    def test_episode_changes_history_get_returns_paginated_payload(self):
        """Episode changes-history endpoint should return paginated entries."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]

        response = self.call_api(
            "get",
            "api_media_episode_changes_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])
        for entry in payload["results"]:
            check_changes_history_entry_structure(self, entry)

    @patch("api.views.tmdb.process_episodes", return_value=[])
    @patch("api.views.services.get_media_metadata")
    def test_episode_sync_returns_accepted(
        self,
        mock_metadata,
        _mock_process_episodes,
    ):
        """Episode sync endpoint should proxy to season sync and return accepted."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        mock_metadata.return_value = {
            "title": "TV Show 1 - Season 1 Synced",
            "image": "https://example.com/season-1-synced.jpg",
            "episodes": [
                {
                    "episode_number": episode_item.episode_number,
                    "image": "https://example.com/episode-1-synced.jpg",
                }
            ],
        }

        response = self.call_api(
            "post",
            "api_media_episode_sync",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 202)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_episode_sync_invalid_ids_return_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Episode sync should surface provider failures for invalid ids."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        requests = [
            (MediaTypes.TV.value, "tmdb", 999999, 1, 1),
            (MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999, 1),
            (
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999,
            ),
        ]
        for args in requests:
            response = self.call_api(
                "post",
                "api_media_episode_sync",
                args=args,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 500)

    def test_episode_sync_rejects_manual_source(self):
        """Episode sync endpoint should reject manual source."""
        response = self.call_api(
            "post",
            "api_media_episode_sync",
            args=(MediaTypes.TV.value, Sources.MANUAL.value, 701, 1, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
