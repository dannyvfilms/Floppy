"""REST writes for a show stored in the Anime library bucket (issue #1532)."""

from unittest.mock import patch

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from lists.models import CustomList

from .base import FloppyApiTestCase

MEDIA_ID = "209867"
ANIME = MediaTypes.ANIME.value


class AnimeBucketWriteTests(FloppyApiTestCase):
    """A TMDB show whose rows all sit in the anime bucket."""

    def setUp(self):
        """Create a tracked show, season and watched episode in the anime bucket."""
        super().setUp()
        metadata_patcher = patch(
            "api.views.services.get_media_metadata",
            return_value={
                "title": "Frieren",
                "image": "https://example.com/x.jpg",
                "episodes": [{"episode_number": 1}, {"episode_number": 2}],
                "related": {"seasons": [{"season_number": 1}]},
            },
        )
        metadata_patcher.start()
        self.addCleanup(metadata_patcher.stop)
        common = {
            "media_id": MEDIA_ID,
            "source": Sources.TMDB.value,
            "library_media_type": ANIME,
            "image": "https://example.com/x.jpg",
        }
        tv_item = Item.objects.create(
            media_type=MediaTypes.TV.value,
            title="Frieren",
            **common,
        )
        self.season_item = Item.objects.create(
            media_type=MediaTypes.SEASON.value,
            title="Frieren S1",
            season_number=1,
            **common,
        )
        episode_item = Item.objects.create(
            media_type=MediaTypes.EPISODE.value,
            title="Frieren E2",
            season_number=1,
            episode_number=2,
            **common,
        )
        tv = TV.objects.create(item=tv_item, user=self.user1, status=Status.COMPLETED.value)
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user1,
            related_tv=tv,
            status=Status.COMPLETED.value,
        )
        self.season_payload = {
            "source": Sources.TMDB.value,
            "media_id": MEDIA_ID,
            "season_number": 1,
            "status": 0,
            "score": 7,
            "library_media_type": ANIME,
        }
        self.episode = Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date="2026-01-02T10:00:00Z",
        )

    def test_episode_history_entry_delete_in_anime_bucket(self):
        """DELETE a specific episode history entry with the anime bucket."""
        response = self.call_api(
            "delete",
            "api_media_episode_consumption_entry_detail",
            args=(MediaTypes.TV.value, Sources.TMDB.value, MEDIA_ID, 1, 2, self.episode.id),
            params={"library_media_type": ANIME},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Episode.objects.filter(id=self.episode.id).exists())

    def test_season_score_patch_in_anime_bucket(self):
        """PATCH a season score with the anime bucket."""
        response = self.call_api(
            "patch",
            "api_media_season_detail",
            args=(MediaTypes.TV.value, Sources.TMDB.value, MEDIA_ID, 1),
            params={"library_media_type": ANIME},
            payload={"score": 6},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.season.refresh_from_db()
        self.assertEqual(self.season.score, 6)

    def test_season_post_in_anime_bucket_creates_season(self):
        """POST a season that is not tracked yet, in the anime bucket."""
        self.season.delete()
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.SEASON.value,),
            payload=self.season_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Season.objects.get(user=self.user1, item__media_id=MEDIA_ID).item.id, self.season_item.id)

    def test_season_post_when_already_tracked_returns_conflict(self):
        """POST a season that is already tracked is a 409, not a 500."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.SEASON.value,),
            payload=self.season_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 409, response.content[:300])
        self.assertEqual(
            response.json(),
            {"detail": "Conflict. Media is already tracked."},
        )

    def test_season_history_entry_delete_in_anime_bucket(self):
        """DELETE a season history entry with the anime bucket."""
        response = self.call_api(
            "delete",
            "api_media_season_consumption_entry_detail",
            args=(MediaTypes.TV.value, Sources.TMDB.value, MEDIA_ID, 1, self.season.id),
            params={"library_media_type": ANIME},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Season.objects.filter(id=self.season.id).exists())

    def test_season_delete_in_anime_bucket(self):
        """DELETE a tracked season with the anime bucket."""
        response = self.call_api(
            "delete",
            "api_media_season_detail",
            args=(MediaTypes.TV.value, Sources.TMDB.value, MEDIA_ID, 1),
            params={"library_media_type": ANIME},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Season.objects.filter(id=self.season.id).exists())

    def test_season_patch_reports_lists_of_the_anime_bucket_item(self):
        """The PATCH response lists the anime item's lists, not the TV item's."""
        favorites = CustomList.objects.create(name="Anime picks", owner=self.user1)
        favorites.items.add(self.season_item)

        response = self.call_api(
            "patch",
            "api_media_season_detail",
            args=(MediaTypes.TV.value, Sources.TMDB.value, MEDIA_ID, 1),
            params={"library_media_type": ANIME},
            payload={"score": 6},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        list_ids = [entry["list_id"] for entry in response.json()["lists"]]
        self.assertEqual(list_ids, [favorites.id])
