from unittest.mock import patch

from django.db.utils import OperationalError

from api.serializers import CompleteMediaSerializer, EpisodeSerializer
from app.models import TV, Episode, Item, MediaTypes, Season, Sources

from .base import FloppyApiTestCase
from .helpers import (
    check_changes_history_entry_structure,
    check_complete_media_structure,
    check_consumption_structure,
    check_media_structure,
    check_minimized_lists_structure,
    check_pagination_structure,
)


class MediaSeasonTests(FloppyApiTestCase):
    """Validate season endpoint contracts."""

    def test_season_endpoints_reject_non_tv_media_type(self):
        """Season endpoints should return 400 when media_type is not tv."""
        requests = [
            ("get", "api_media_seasons", ("movie", "tmdb", 1), None),
            ("get", "api_media_season_detail", ("movie", "tmdb", 1, 1), None),
            (
                "patch",
                "api_media_season_detail",
                ("movie", "tmdb", 1, 1),
                {"notes": "x"},
            ),
            (
                "delete",
                "api_media_season_detail",
                ("movie", "tmdb", 1, 1),
                None,
            ),
            (
                "get",
                "api_media_season_changes_history",
                ("movie", "tmdb", 1, 1),
                None,
            ),
            (
                "get",
                "api_media_season_episodes",
                ("movie", "tmdb", 1, 1),
                None,
            ),
            (
                "get",
                "api_media_season_consumption_history",
                ("movie", "tmdb", 1, 1),
                None,
            ),
            (
                "get",
                "api_media_season_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "patch",
                "api_media_season_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1),
                {"notes": "x"},
            ),
            (
                "delete",
                "api_media_season_consumption_entry_detail",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "get",
                "api_media_season_lists",
                ("movie", "tmdb", 1, 1),
                None,
            ),
            (
                "put",
                "api_media_season_list_detail",
                ("movie", "tmdb", 1, 1, 1),
                {},
            ),
            (
                "delete",
                "api_media_season_list_detail",
                ("movie", "tmdb", 1, 1, 1),
                None,
            ),
            (
                "post",
                "api_media_season_sync",
                ("movie", "tmdb", 1, 1),
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

    def test_season_detail_delete_tracked_season_returns_204(self):
        """Season delete of tracked season should return 204."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "delete",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)

    def test_season_detail_delete_invalid_media_id_returns_404(self):
        """Season delete with invalid media_id should return 404."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "delete",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                "99999999",
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_detail_delete_invalid_season_number_returns_404(self):
        """Season delete with invalid season_number should return 404."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]

        response = self.call_api(
            "delete",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                "999",
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    @patch("api.views.services.get_media_metadata")
    def test_season_detail_get_returns_expected_shape(self, mock_metadata):
        """Season detail GET should return complete serialized payload."""
        source = "tmdb"
        media_id = 1
        season_number = 1
        mock_metadata.return_value = {
            "source": "tmdb",
            "media_type": "season",
            "season_title": "Season 1",
            "max_progress": 11,
            "image": "https://image.tmdb.org/t/p/w500/nCcGD18HmDFunCl8KBigqUPlIi8.jpg",
            "season_number": 1,
            "synopsis": "Haru Satonaka is the captain of an ice-hockey team, a star athlete who stakes everything on hockey but can only consider love as a game. Aki Murase is a woman who has been waiting for her lover who went abroad two years ago. These two persons start a relationship while frankly admitting to each other that it is only a love game. …The result is the unfolding of a drama of people with their respective pasts and with their pride as individuals.",
            "score": 8.8,
            "score_count": 8,
            "details": {
                "first_air_date": "2004-01-12",
                "last_air_date": "2004-03-22",
                "episodes": 11,
                "runtime": "1h 0m",
                "total_runtime": "11h 0m",
            },
            "episodes": [
                {
                    "air_date": "2004-01-12",
                    "episode_number": 1,
                    "episode_type": "standard",
                    "id": 1130462,
                    "name": "Bond of Love and Youth",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/aD5EoDq1a9n876Gadde1wp5nImg.jpg",
                    "vote_average": 8.8,
                    "vote_count": 8,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-01-19",
                    "episode_number": 2,
                    "episode_type": "standard",
                    "id": 1130463,
                    "name": "Strength That Overcomes Loneliness",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/eAKtWo35CUTTZnoomrfrCNz1gDT.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-01-26",
                    "episode_number": 3,
                    "episode_type": "standard",
                    "id": 1130464,
                    "name": "Leader's Beautiful Form",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/lpcAOBuMfvWlFN7dkJqHPWaXZnJ.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-02-02",
                    "episode_number": 4,
                    "episode_type": "standard",
                    "id": 1130465,
                    "name": "Men's Camaraderie and Women's Pride",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/8nnKJ52jEbILjvSy98MBo4dKX1q.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Mariko Hirata",
                            "credit_id": "68204ad8afc73518c4738c27",
                            "order": 500,
                            "adult": False,
                            "gender": 1,
                            "id": 71643,
                            "known_for_department": "Acting",
                            "name": "Asami Mizukawa",
                            "original_name": "水川あさみ",
                            "popularity": 3.4886,
                            "profile_path": "/s65mobAWexnr8QroTXvJUeem6o1.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-02-09",
                    "episode_number": 5,
                    "episode_type": "standard",
                    "id": 1130466,
                    "name": "Wounds of the Heart",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/z4paen1ZtzL4aMkks7ln5SckMt.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Ken Egawa",
                            "credit_id": "68204af58b1e454432ad8d5a",
                            "order": 501,
                            "adult": False,
                            "gender": 2,
                            "id": 66589,
                            "known_for_department": "Acting",
                            "name": "Morio Kazama",
                            "original_name": "風間 杜夫",
                            "popularity": 1.7379,
                            "profile_path": "/x0DzJzdivusbFzNs0KNPXqhiH3M.jpg",
                        },
                        {
                            "character": "Kyoko Egawa",
                            "credit_id": "68204b16afc73518c4738c2b",
                            "order": 502,
                            "adult": False,
                            "gender": 1,
                            "id": 1015972,
                            "known_for_department": "Acting",
                            "name": "Miyako Yamaguchi",
                            "original_name": "山口美也子",
                            "popularity": 1.3304,
                            "profile_path": "/6rgEtsqAvY6JeThYw8MGzSOoTmk.jpg",
                        },
                    ],
                },
                {
                    "air_date": "2004-02-16",
                    "episode_number": 6,
                    "episode_type": "standard",
                    "id": 1130467,
                    "name": "Dear Mother",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/eKbVMzKSoeJ6MQ0INOOW7Sj1QYc.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Chieko Imaizumi",
                            "credit_id": "68204b4eafc73518c4738c30",
                            "order": 503,
                            "adult": False,
                            "gender": 1,
                            "id": 79945,
                            "known_for_department": "Acting",
                            "name": "Keiko Matsuzaka",
                            "original_name": "松坂慶子",
                            "popularity": 2.6161,
                            "profile_path": "/s56n7UkfLmZaCa33kw8t8IR7wAP.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-02-23",
                    "episode_number": 7,
                    "episode_type": "standard",
                    "id": 1130468,
                    "name": "Disturbance",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/bbxj6WQ8LzKpq4kAmMCiT0E3bqg.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-01",
                    "episode_number": 8,
                    "episode_type": "standard",
                    "id": 1130469,
                    "name": "Tragedy",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/s2q9GUcwpmo6UIblrk1T22NmHZL.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-08",
                    "episode_number": 9,
                    "episode_type": "standard",
                    "id": 1130470,
                    "name": "Lament",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/9DwPwMlK0X9yUyjXMeSazRs01xY.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-15",
                    "episode_number": 10,
                    "episode_type": "standard",
                    "id": 1130471,
                    "name": "Hope",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/6oqT6rHKfdPGQQekT4Nx24W2C80.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Hiroshi Kagami",
                            "credit_id": "68204b7cb3ef0ec980863ba5",
                            "order": 504,
                            "adult": False,
                            "gender": 2,
                            "id": 110500,
                            "known_for_department": "Acting",
                            "name": "Hirofumi Arai",
                            "original_name": "新井浩文",
                            "popularity": 1.2402,
                            "profile_path": "/8nG16y3euYjEB9ZfZP2ixx7DpXy.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-03-22",
                    "episode_number": 11,
                    "episode_type": "finale",
                    "id": 1130472,
                    "name": "Pride Called Love",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/cbBDe2EOSqeAsqdOjbA2CBKN1Dm.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Hiroshi Kagami",
                            "credit_id": "68204b7cb3ef0ec980863ba5",
                            "order": 504,
                            "adult": False,
                            "gender": 2,
                            "id": 110500,
                            "known_for_department": "Acting",
                            "name": "Hirofumi Arai",
                            "original_name": "新井浩文",
                            "popularity": 1.2402,
                            "profile_path": "/8nG16y3euYjEB9ZfZP2ixx7DpXy.jpg",
                        }
                    ],
                },
            ],
            "providers": {
                "JP": {
                    "link": "https://www.themoviedb.org/tv/1/watch?locale=JP",
                    "flatrate": [
                        {
                            "logo_path": "/pbpMk2JmcoNnQwx5JGpXngfoWtp.jpg",
                            "provider_id": 8,
                            "provider_name": "Netflix",
                            "display_priority": 0,
                        },
                        {
                            "logo_path": "/dpR8r13zWDeUR0QkzWidrdMxa56.jpg",
                            "provider_id": 1796,
                            "provider_name": "Netflix Standard with Ads",
                            "display_priority": 24,
                        },
                        {
                            "logo_path": "/8QWktqRs0xcar91ncdWx1EJkTuY.jpg",
                            "provider_id": 2498,
                            "provider_name": "FOD Channel Amazon Channel",
                            "display_priority": 48,
                        },
                        {
                            "logo_path": "/9EWAEok40O0HVhV0MYJmlE4LhGy.jpg",
                            "provider_id": 2683,
                            "provider_name": "FOD",
                            "display_priority": 80,
                        },
                    ],
                }
            },
            "media_id": "1",
            "source_url": "https://www.themoviedb.org/tv/1/season/1",
            "title": "Pride",
            "tvdb_id": 84831,
            "external_links": {
                "IMDb": "https://www.imdb.com/title/tt0416409/",
                "TVDB": "https://www.thetvdb.com/dereferrer/series/84831",
                "Wikidata": "https://www.wikidata.org/wiki/Q2040235",
            },
            "genres": ["Drama"],
        }

        response = self.call_api(
            "get",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                source,
                media_id,
                season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_complete_media_structure(self, payload)

    def test_season_detail_get_invalid_media_id_returns_ok_with_null_item_id(self):
        """Season detail GET no longer 500s when provider metadata is bare.

        Regression test for #888: build_item_id()/build_parent_id() used to
        dereference `media_type` unconditionally, so metadata missing that
        field (as returned here by the shared get_media_metadata patch)
        crashed outside any handler instead of degrading gracefully.
        """
        tv_item = self.items_by_type[MediaTypes.TV.value][0]

        response = self.call_api(
            "get",
            "api_media_season_detail",
            args=(MediaTypes.TV.value, tv_item.source, "99999999", 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["item_id"])
        self.assertIsNone(response.data["parent_id"])

    @patch("api.views.services.get_media_metadata")
    def test_season_detail_get_exposes_imdb_rating(self, mock_metadata):
        """Season detail GET should expose the season Item's IMDb rating."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        season_item.imdb_rating = 7.3
        season_item.imdb_rating_count = 890
        season_item.save()

        mock_metadata.return_value = {
            "media_id": tv_item.media_id,
            "source": tv_item.source,
            "media_type": "season",
            "season_number": season_item.season_number,
            "related": {"episodes": []},
        }

        response = self.call_api(
            "get",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imdb_rating"], 7.3)
        self.assertEqual(payload["imdb_rating_count"], 890)

    @patch("api.views.services.get_media_metadata")
    def test_season_detail_untracked_episode_reports_synced_imdb_rating(
        self,
        mock_metadata,
    ):
        """An untracked episode with a previously-synced Item still shows its rating."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        Item.objects.create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            title="Untracked Episode 99",
            season_number=season_item.season_number,
            episode_number=99,
            imdb_rating=5.4,
            imdb_rating_count=17,
        )

        mock_metadata.return_value = {
            "source": tv_item.source,
            "media_id": tv_item.media_id,
            "media_type": "season",
            "season_number": season_item.season_number,
            "episodes": [
                {
                    "episode_number": 99,
                    "season_number": season_item.season_number,
                    "show_id": tv_item.media_id,
                    "name": "Untracked Episode 99",
                    "overview": "",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "air_date": None,
                    "runtime": None,
                    "episode_type": None,
                    "crew": [],
                    "guest_stars": [],
                    "still_path": None,
                },
            ],
            "related": {"episodes": []},
        }

        response = self.call_api(
            "get",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        episode = response.json()["related"]["episodes"][0]
        self.assertFalse(episode["tracked"])
        self.assertEqual(episode["item"]["imdb_rating"], 5.4)
        self.assertEqual(episode["item"]["imdb_rating_count"], 17)

    @patch("api.views.services.get_media_metadata")
    def test_season_detail_patch_updates_season_fields(self, mock_metadata):
        """Season detail PATCH should update season fields."""
        status = 2
        score = 7
        notes = "Updated notes"
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        mock_metadata.return_value = {
            "source": "tmdb",
            "media_type": "season",
            "season_title": "Season 1",
            "max_progress": 11,
            "image": "https://image.tmdb.org/t/p/w500/nCcGD18HmDFunCl8KBigqUPlIi8.jpg",
            "season_number": 1,
            "synopsis": "Haru Satonaka is the captain of an ice-hockey team, a star athlete who stakes everything on hockey but can only consider love as a game. Aki Murase is a woman who has been waiting for her lover who went abroad two years ago. These two persons start a relationship while frankly admitting to each other that it is only a love game. …The result is the unfolding of a drama of people with their respective pasts and with their pride as individuals.",
            "score": 8.8,
            "score_count": 8,
            "details": {
                "first_air_date": "2004-01-12",
                "last_air_date": "2004-03-22",
                "episodes": 11,
                "runtime": "1h 0m",
                "total_runtime": "11h 0m",
            },
            "episodes": [
                {
                    "air_date": "2004-01-12",
                    "episode_number": 1,
                    "episode_type": "standard",
                    "id": 1130462,
                    "name": "Bond of Love and Youth",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/aD5EoDq1a9n876Gadde1wp5nImg.jpg",
                    "vote_average": 8.8,
                    "vote_count": 8,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-01-19",
                    "episode_number": 2,
                    "episode_type": "standard",
                    "id": 1130463,
                    "name": "Strength That Overcomes Loneliness",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/eAKtWo35CUTTZnoomrfrCNz1gDT.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-01-26",
                    "episode_number": 3,
                    "episode_type": "standard",
                    "id": 1130464,
                    "name": "Leader's Beautiful Form",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/lpcAOBuMfvWlFN7dkJqHPWaXZnJ.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-02-02",
                    "episode_number": 4,
                    "episode_type": "standard",
                    "id": 1130465,
                    "name": "Men's Camaraderie and Women's Pride",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/8nnKJ52jEbILjvSy98MBo4dKX1q.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Mariko Hirata",
                            "credit_id": "68204ad8afc73518c4738c27",
                            "order": 500,
                            "adult": False,
                            "gender": 1,
                            "id": 71643,
                            "known_for_department": "Acting",
                            "name": "Asami Mizukawa",
                            "original_name": "水川あさみ",
                            "popularity": 3.4886,
                            "profile_path": "/s65mobAWexnr8QroTXvJUeem6o1.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-02-09",
                    "episode_number": 5,
                    "episode_type": "standard",
                    "id": 1130466,
                    "name": "Wounds of the Heart",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/z4paen1ZtzL4aMkks7ln5SckMt.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Ken Egawa",
                            "credit_id": "68204af58b1e454432ad8d5a",
                            "order": 501,
                            "adult": False,
                            "gender": 2,
                            "id": 66589,
                            "known_for_department": "Acting",
                            "name": "Morio Kazama",
                            "original_name": "風間 杜夫",
                            "popularity": 1.7379,
                            "profile_path": "/x0DzJzdivusbFzNs0KNPXqhiH3M.jpg",
                        },
                        {
                            "character": "Kyoko Egawa",
                            "credit_id": "68204b16afc73518c4738c2b",
                            "order": 502,
                            "adult": False,
                            "gender": 1,
                            "id": 1015972,
                            "known_for_department": "Acting",
                            "name": "Miyako Yamaguchi",
                            "original_name": "山口美也子",
                            "popularity": 1.3304,
                            "profile_path": "/6rgEtsqAvY6JeThYw8MGzSOoTmk.jpg",
                        },
                    ],
                },
                {
                    "air_date": "2004-02-16",
                    "episode_number": 6,
                    "episode_type": "standard",
                    "id": 1130467,
                    "name": "Dear Mother",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/eKbVMzKSoeJ6MQ0INOOW7Sj1QYc.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Chieko Imaizumi",
                            "credit_id": "68204b4eafc73518c4738c30",
                            "order": 503,
                            "adult": False,
                            "gender": 1,
                            "id": 79945,
                            "known_for_department": "Acting",
                            "name": "Keiko Matsuzaka",
                            "original_name": "松坂慶子",
                            "popularity": 2.6161,
                            "profile_path": "/s56n7UkfLmZaCa33kw8t8IR7wAP.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-02-23",
                    "episode_number": 7,
                    "episode_type": "standard",
                    "id": 1130468,
                    "name": "Disturbance",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/bbxj6WQ8LzKpq4kAmMCiT0E3bqg.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-01",
                    "episode_number": 8,
                    "episode_type": "standard",
                    "id": 1130469,
                    "name": "Tragedy",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/s2q9GUcwpmo6UIblrk1T22NmHZL.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-08",
                    "episode_number": 9,
                    "episode_type": "standard",
                    "id": 1130470,
                    "name": "Lament",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/9DwPwMlK0X9yUyjXMeSazRs01xY.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [],
                },
                {
                    "air_date": "2004-03-15",
                    "episode_number": 10,
                    "episode_type": "standard",
                    "id": 1130471,
                    "name": "Hope",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/6oqT6rHKfdPGQQekT4Nx24W2C80.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Hiroshi Kagami",
                            "credit_id": "68204b7cb3ef0ec980863ba5",
                            "order": 504,
                            "adult": False,
                            "gender": 2,
                            "id": 110500,
                            "known_for_department": "Acting",
                            "name": "Hirofumi Arai",
                            "original_name": "新井浩文",
                            "popularity": 1.2402,
                            "profile_path": "/8nG16y3euYjEB9ZfZP2ixx7DpXy.jpg",
                        }
                    ],
                },
                {
                    "air_date": "2004-03-22",
                    "episode_number": 11,
                    "episode_type": "finale",
                    "id": 1130472,
                    "name": "Pride Called Love",
                    "overview": "",
                    "production_code": "",
                    "runtime": 60,
                    "season_number": 1,
                    "show_id": 1,
                    "still_path": "/cbBDe2EOSqeAsqdOjbA2CBKN1Dm.jpg",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "crew": [],
                    "guest_stars": [
                        {
                            "character": "Hiroshi Kagami",
                            "credit_id": "68204b7cb3ef0ec980863ba5",
                            "order": 504,
                            "adult": False,
                            "gender": 2,
                            "id": 110500,
                            "known_for_department": "Acting",
                            "name": "Hirofumi Arai",
                            "original_name": "新井浩文",
                            "popularity": 1.2402,
                            "profile_path": "/8nG16y3euYjEB9ZfZP2ixx7DpXy.jpg",
                        }
                    ],
                },
            ],
            "providers": {
                "JP": {
                    "link": "https://www.themoviedb.org/tv/1/watch?locale=JP",
                    "flatrate": [
                        {
                            "logo_path": "/pbpMk2JmcoNnQwx5JGpXngfoWtp.jpg",
                            "provider_id": 8,
                            "provider_name": "Netflix",
                            "display_priority": 0,
                        },
                        {
                            "logo_path": "/dpR8r13zWDeUR0QkzWidrdMxa56.jpg",
                            "provider_id": 1796,
                            "provider_name": "Netflix Standard with Ads",
                            "display_priority": 24,
                        },
                        {
                            "logo_path": "/8QWktqRs0xcar91ncdWx1EJkTuY.jpg",
                            "provider_id": 2498,
                            "provider_name": "FOD Channel Amazon Channel",
                            "display_priority": 48,
                        },
                        {
                            "logo_path": "/9EWAEok40O0HVhV0MYJmlE4LhGy.jpg",
                            "provider_id": 2683,
                            "provider_name": "FOD",
                            "display_priority": 80,
                        },
                    ],
                }
            },
            "media_id": "1",
            "source_url": "https://www.themoviedb.org/tv/1/season/1",
            "title": "Pride",
            "tvdb_id": 84831,
            "external_links": {
                "IMDb": "https://www.imdb.com/title/tt0416409/",
                "TVDB": "https://www.thetvdb.com/dereferrer/series/84831",
                "Wikidata": "https://www.wikidata.org/wiki/Q2040235",
            },
            "genres": ["Drama"],
        }

        response = self.call_api(
            "patch",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            payload={"status": status, "score": score, "notes": notes},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_complete_media_structure(self, payload)
        self.assertEqual(payload["consumptions"][0]["status"], status)
        self.assertEqual(payload["consumptions"][0]["score"], score)
        self.assertEqual(payload["consumptions"][0]["notes"], notes)

    def test_season_detail_patch_invalid_media_id_returns_not_found(self):
        """Season detail PATCH with invalid media_id should return 404."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "patch",
            "api_media_season_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            payload={"invalid_field": "value"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_season_episodes_get_returns_episode_list(self):
        """Season episodes GET should return list of episodes."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "get",
            "api_media_season_episodes",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])
        for episode in payload["results"]:
            check_media_structure(self, episode)

    @patch("api.views.services.get_media_metadata")
    def test_season_episodes_get_reports_tracked_episodes(self, mock_metadata):
        """Season episodes GET should report tracked status for watched episodes.

        Regression test: get_season_episodes previously filtered on
        item__episode_number=None when only a season_number was given, so this
        always returned an empty queryset and every episode showed
        tracked=False regardless of real Episode consumption rows.
        """
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        tracked_episode_items = self.items_by_type[MediaTypes.EPISODE.value]

        mock_metadata.return_value = {
            "episodes": [
                {
                    "episode_number": episode_item.episode_number,
                    "season_number": episode_item.season_number,
                    "show_id": tv_item.media_id,
                    "name": f"Provider episode {episode_item.episode_number}",
                    "overview": "",
                    "vote_average": 0.0,
                    "vote_count": 0,
                    "air_date": None,
                    "runtime": None,
                    "episode_type": None,
                    "crew": [],
                    "guest_stars": [],
                    "still_path": None,
                }
                for episode_item in tracked_episode_items
            ],
        }

        response = self.call_api(
            "get",
            "api_media_season_episodes",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), len(tracked_episode_items))
        tracked_episode = next(
            episode_media
            for episode_media in self.episode_medias
            if episode_media.item_id == tracked_episode_items[0].id
        )
        first_result = next(
            episode for episode in results if episode["item"]["episode_number"] == 1
        )
        self.assertTrue(first_result["tracked"])
        self.assertEqual(first_result["consumption_id"], tracked_episode.id)
        self.assertEqual(first_result["item"]["title"], "Provider episode 1")

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_season_episodes_get_invalid_media_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Season episodes GET with invalid media_id should return 500."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "get",
            "api_media_season_episodes",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                "99999999",
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_season_episodes_get_invalid_season_number_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Season episodes GET with invalid season_number should return 500."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]

        response = self.call_api(
            "get",
            "api_media_season_episodes",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    def test_season_changes_history_get_returns_paginated_payload(self):
        """Season changes-history endpoint should return paginated entries."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "get",
            "api_media_season_changes_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(self, payload["pagination"])
        self.assertGreaterEqual(len(payload["results"]), 1)
        for entry in payload["results"]:
            check_changes_history_entry_structure(self, entry)

    def test_season_changes_history_invalid_media_id_returns_not_found(self):
        """Season changes-history endpoint should return 404 for unknown media."""
        response = self.call_api(
            "get",
            "api_media_season_changes_history",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_changes_history_invalid_season_number_returns_not_found(self):
        """Season changes-history endpoint should return 404 for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        response = self.call_api(
            "get",
            "api_media_season_changes_history",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_consumption_history_get_returns_paginated_payload(self):
        """Season consumption-history endpoint should return paginated entries."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "get",
            "api_media_season_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
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

    def test_season_consumption_history_invalid_media_id_returns_empty_results(self):
        """Season consumption-history should return empty results for unknown media."""
        response = self.call_api(
            "get",
            "api_media_season_consumption_history",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])

    def test_season_consumption_history_invalid_season_number_returns_empty_results(
        self,
    ):
        """Season consumption-history should return empty results for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        response = self.call_api(
            "get",
            "api_media_season_consumption_history",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])

    def test_season_consumption_history_scopes_to_library_media_type_bucket(self):
        """Season consumption-history should not mix rows from a different bucket.

        Regression test: Item rows can be bucketed by library_media_type (e.g.
        a grouped-anime row sharing the same season_number as a plain-TV row).
        The manager previously returned both rows for a bare season_number
        lookup, so the API could nondeterministically surface a stale/wrong
        bucket's consumption record instead of the tracked one.
        """
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        self.season_medias[0].notes = "non-anime-bucket"
        self.season_medias[0].save()

        anime_bucket_item = Item.objects.create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Bucket Season 1",
            image="https://example.com/anime-season-1.jpg",
            season_number=season_item.season_number,
        )
        anime_bucket_season = Season.objects.create(
            item=anime_bucket_item,
            user=self.user1,
            related_tv=self.tv_medias[0],
            notes="anime-bucket",
        )

        response = self.call_api(
            "get",
            "api_media_season_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_pagination_structure(self, payload["pagination"], total=1)
        self.assertEqual(payload["results"][0]["notes"], "non-anime-bucket")

        anime_response = self.call_api(
            "get",
            "api_media_season_consumption_history",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            params={"library_media_type": MediaTypes.ANIME.value},
            headers=self.auth_headers,
        )

        self.assertEqual(anime_response.status_code, 200)
        anime_payload = anime_response.json()
        check_pagination_structure(self, anime_payload["pagination"], total=1)
        self.assertEqual(anime_payload["results"][0]["notes"], "anime-bucket")
        self.assertEqual(
            anime_payload["results"][0]["consumption_id"],
            anime_bucket_season.id,
        )

    def test_season_consumption_entry_detail_get_returns_expected_structure(self):
        """Season history entry detail GET should return serialized consumption."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        consumption_id = self.season_medias[0].id

        response = self.call_api(
            "get",
            "api_media_season_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                consumption_id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        check_consumption_structure(self, response.json())

    def test_season_consumption_entry_detail_delete_removes_history_entry(self):
        """Season history entry detail DELETE should remove the row."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        consumption_id = self.season_medias[0].id

        response = self.call_api(
            "delete",
            "api_media_season_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                consumption_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)

        get_response = self.call_api(
            "get",
            "api_media_season_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                consumption_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 404)

    def test_season_consumption_entry_detail_patch_updates_history_entry(self):
        """Season history entry detail PATCH should persist valid changes."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        consumption_id = self.season_medias[0].id

        response = self.call_api(
            "patch",
            "api_media_season_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                consumption_id,
            ),
            payload={"notes": "season-updated-from-test"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertEqual(payload["notes"], "season-updated-from-test")

    def test_season_consumption_entry_detail_patch_invalid_payload_returns_bad_request(
        self,
    ):
        """Season history entry detail PATCH should reject invalid payload."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        consumption_id = self.season_medias[0].id

        response = self.call_api(
            "patch",
            "api_media_season_consumption_entry_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                consumption_id,
            ),
            payload={"end_date": "invalid-date"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_season_consumption_entry_detail_invalid_media_id_methods(self):
        """Season history entry-detail methods should return 404 for unknown media."""
        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_season_consumption_entry_detail",
                args=(MediaTypes.TV.value, "tmdb", 999999, 1, self.season_medias[0].id),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 404)

    def test_season_consumption_entry_detail_invalid_season_number_methods(self):
        """Season history entry-detail methods should return 404 for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_season_consumption_entry_detail",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    999,
                    self.season_medias[0].id,
                ),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 404)

    def test_season_consumption_entry_detail_invalid_consumption_id_methods(self):
        """Season history entry-detail methods should return 404 for unknown entry."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_season_consumption_entry_detail",
                args=(
                    MediaTypes.TV.value,
                    tv_item.source,
                    tv_item.media_id,
                    season_item.season_number,
                    999999,
                ),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 404)

    def test_season_lists_get_returns_lists(self):
        """Season lists endpoint should return related list entries."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]

        response = self.call_api(
            "get",
            "api_media_season_lists",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertEqual(len(payload["results"]), 1)
        for entry in payload["results"]:
            check_minimized_lists_structure(self, entry)

    def test_season_lists_get_invalid_media_id_returns_empty_results(self):
        """Season lists endpoint should return empty list for unknown media."""
        response = self.call_api(
            "get",
            "api_media_season_lists",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_season_lists_get_invalid_season_number_returns_empty_results(self):
        """Season lists endpoint should return empty list for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        response = self.call_api(
            "get",
            "api_media_season_lists",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_season_list_detail_delete_removes_media_from_list(self):
        """Season list-detail DELETE should remove season from existing list."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        list_id = self.lists_by_name["watching"].id

        response = self.call_api(
            "delete",
            "api_media_season_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                list_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 204)

        get_response = self.call_api(
            "get",
            "api_media_season_lists",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["results"], [])

    def test_season_list_detail_delete_invalid_media_id_returns_not_found(self):
        """Season list-detail DELETE should return 404 for unknown media."""
        list_id = self.lists_by_name["watching"].id
        response = self.call_api(
            "delete",
            "api_media_season_list_detail",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1, list_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_list_detail_delete_invalid_season_number_returns_not_found(self):
        """Season list-detail DELETE should return 404 for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        list_id = self.lists_by_name["watching"].id
        response = self.call_api(
            "delete",
            "api_media_season_list_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999, list_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_list_detail_delete_invalid_list_id_returns_not_found(self):
        """Season list-detail DELETE should return 404 for unknown list."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        response = self.call_api(
            "delete",
            "api_media_season_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_list_detail_put_adds_media_to_list(self):
        """Season list-detail PUT should add season when missing."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_season_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        get_response = self.call_api(
            "get",
            "api_media_season_lists",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 2)
        for entry in payload["results"]:
            check_minimized_lists_structure(self, entry)

    def test_season_list_detail_put_invalid_media_id_returns_not_found(self):
        """Season list-detail PUT should return 404 for unknown media."""
        list_id = self.lists_by_name["favorites"].id
        response = self.call_api(
            "put",
            "api_media_season_list_detail",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1, list_id),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_list_detail_put_invalid_season_number_returns_not_found(self):
        """Season list-detail PUT should return 404 for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        list_id = self.lists_by_name["favorites"].id
        response = self.call_api(
            "put",
            "api_media_season_list_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999, list_id),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_season_list_detail_put_invalid_list_id_returns_not_found(self):
        """Season list-detail PUT should return 404 for unknown list."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        response = self.call_api(
            "put",
            "api_media_season_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                999999,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    @patch("api.views.run_retryable_db_operation")
    def test_season_list_detail_put_returns_503_on_persistent_lock(self, mock_retry):
        """Season list-detail PUT should return 503 when the DB stays locked."""
        mock_retry.side_effect = OperationalError("database is locked")
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_season_list_detail",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.json())

    @patch("api.views.tmdb.process_episodes", return_value=[])
    @patch("api.views.services.get_media_metadata")
    def test_season_sync_returns_accepted_and_updates_item(
        self,
        mock_metadata,
        _mock_process_episodes,
    ):
        """Season sync should refresh metadata and return accepted."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        mock_metadata.return_value = {
            "title": "TV Show 1 - Season 1 Synced",
            "image": "https://example.com/season-1-synced.jpg",
            "episodes": [],
        }

        response = self.call_api(
            "post",
            "api_media_season_sync",
            args=(
                MediaTypes.TV.value,
                tv_item.source,
                tv_item.media_id,
                season_item.season_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("Metadata synced successfully", payload["detail"])

        season_item.refresh_from_db()
        self.assertEqual(season_item.title, "TV Show 1 - Season 1 Synced")
        self.assertEqual(season_item.image, "https://example.com/season-1-synced.jpg")

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_season_sync_invalid_media_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Season sync should surface provider errors for unknown media."""
        response = self.call_api(
            "post",
            "api_media_season_sync",
            args=(MediaTypes.TV.value, "tmdb", 999999, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_season_sync_invalid_season_number_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Season sync should surface provider errors for unknown season."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        response = self.call_api(
            "post",
            "api_media_season_sync",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id, 999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    def test_season_sync_rejects_manual_source(self):
        """Season sync endpoint should reject manual source."""
        response = self.call_api(
            "post",
            "api_media_season_sync",
            args=(MediaTypes.TV.value, Sources.MANUAL.value, 701, 1),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)


class EpisodeSerializerAirDateTests(FloppyApiTestCase):
    """Regression tests for #888 item 11 (unwatched episode air dates)."""

    def setUp(self):
        """Track a show with one season and one episode missing release_datetime."""
        super().setUp()
        tv_item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Air Date Show",
        )
        self.tv = TV.objects.create(item=tv_item, user=self.user1)
        season_item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Air Date Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user1,
            related_tv=self.tv,
        )
        self.episode_item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Air Date Show",
            season_number=1,
            episode_number=1,
            release_datetime=None,
        )
        self.episode = Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
        )

    def test_tracked_episode_backfills_air_date_from_provider(self):
        """A tracked episode with a null stored release_datetime uses the
        provider's air_date instead of staying null, same as the untracked
        case.
        """
        instance = {
            "show_id": "1001",
            "season_number": 1,
            "episode_number": 1,
            "name": "When You're Lost in the Darkness",
            "air_date": "2023-01-15",
        }
        context = {
            "source": Sources.TMDB.value,
            "tracked_episodes": {1: self.episode},
        }

        result = EpisodeSerializer(context=context).to_representation(instance)

        self.assertIsNotNone(result["item"]["release_datetime"])
        self.assertTrue(
            str(result["item"]["release_datetime"]).startswith("2023-01-15"),
        )

    def test_untracked_episode_still_backfills_air_date(self):
        """Sibling untracked episode keeps working the same way."""
        instance = {
            "show_id": "1001",
            "season_number": 1,
            "episode_number": 2,
            "name": "Infected",
            "air_date": "2023-01-22",
        }
        context = {
            "source": Sources.TMDB.value,
            "tracked_episodes": {1: self.episode},
        }

        result = EpisodeSerializer(context=context).to_representation(instance)

        self.assertFalse(result["tracked"])
        self.assertIsNotNone(result["item"]["release_datetime"])
        self.assertTrue(
            str(result["item"]["release_datetime"]).startswith("2023-01-22"),
        )

    def test_existing_untracked_item_uses_provider_still_without_losing_rating(self):
        """An existing image-less Item keeps its ratings and gets a response-only still."""
        item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Provider title",
            season_number=1,
            episode_number=2,
            imdb_rating=8.7,
            imdb_rating_count=123,
        )
        instance = {
            "show_id": "air-date-show-1",
            "season_number": 1,
            "episode_number": 2,
            "name": "Provider title",
            "still_path": "/episode-still.jpg",
        }

        result = EpisodeSerializer(
            context={
                "source": Sources.TMDB.value,
                "existing_items_by_episode": {2: item},
            },
        ).to_representation(instance)

        self.assertEqual(result["item"]["imdb_rating"], 8.7)
        self.assertEqual(result["item"]["imdb_rating_count"], 123)
        self.assertEqual(
            result["item"]["image"],
            "https://image.tmdb.org/t/p/original/episode-still.jpg",
        )
        item.refresh_from_db()
        self.assertIsNone(item.image)

    def test_existing_untracked_item_image_takes_precedence_over_provider_still(self):
        """Stored episode artwork remains authoritative over provider metadata."""
        item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Stored title",
            image="https://example.test/stored-still.jpg",
            season_number=1,
            episode_number=2,
        )
        instance = {
            "show_id": "air-date-show-1",
            "season_number": 1,
            "episode_number": 2,
            "name": "Provider title",
            "still_path": "/provider-still.jpg",
        }

        result = EpisodeSerializer(
            context={
                "source": Sources.TMDB.value,
                "existing_items_by_episode": {2: item},
            },
        ).to_representation(instance)

        self.assertEqual(result["item"]["image"], "https://example.test/stored-still.jpg")

    def test_existing_untracked_tvdb_item_uses_provider_image(self):
        """TVDB episode images are already normalized instead of a still path."""
        item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Provider title",
            season_number=1,
            episode_number=2,
        )
        instance = {
            "show_id": "air-date-show-1",
            "season_number": 1,
            "episode_number": 2,
            "name": "Provider title",
            "still_path": None,
            "image": "https://artworks.thetvdb.com/episode-still.jpg",
        }

        result = EpisodeSerializer(
            context={
                "source": Sources.TVDB.value,
                "existing_items_by_episode": {2: item},
            },
        ).to_representation(instance)

        self.assertEqual(
            result["item"]["image"],
            "https://artworks.thetvdb.com/episode-still.jpg",
        )

    def test_untracked_episode_lookup_excludes_anime_bucket_by_default(self):
        """TV detail must not reuse a same-coordinate grouped-anime Item."""
        Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime episode",
            image="https://example.test/anime.jpg",
            season_number=1,
            episode_number=2,
            imdb_rating=1.0,
        )
        Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="TV episode",
            season_number=1,
            episode_number=2,
            imdb_rating=8.5,
        )
        metadata = {
            "media_id": "air-date-show-1",
            "source": Sources.TMDB.value,
            "season_number": 1,
            "episodes": [
                {
                    "show_id": "air-date-show-1",
                    "season_number": 1,
                    "episode_number": 2,
                    "name": "TV episode",
                    "still_path": "/tv.jpg",
                },
            ],
        }

        CompleteMediaSerializer()._process_episodes(metadata)

        episode = metadata["related"]["episodes"][0]
        self.assertEqual(episode["item"]["imdb_rating"], 8.5)
        self.assertEqual(
            episode["item"]["image"],
            "https://image.tmdb.org/t/p/original/tv.jpg",
        )

    def test_existing_untracked_season_uses_provider_image(self):
        """Existing image-less season Items keep ratings and get response artwork."""
        item = Item.objects.create(
            media_id="air-date-show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season 2",
            season_number=2,
            imdb_rating=8.2,
        )
        metadata = {
            "media_id": "air-date-show-1",
            "source": Sources.TMDB.value,
            "related": {
                "seasons": [
                    {
                        "season_number": 2,
                        "title": "Season 2",
                        "image": "https://example.test/season-2.jpg",
                    },
                ],
            },
        }

        CompleteMediaSerializer()._process_seasons(metadata)

        season = metadata["related"]["seasons"][0]
        self.assertEqual(season["item"]["imdb_rating"], 8.2)
        self.assertEqual(season["item"]["image"], "https://example.test/season-2.jpg")
        item.refresh_from_db()
        self.assertIsNone(item.image)
