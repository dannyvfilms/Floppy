import datetime
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from uuid import UUID

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.utils import OperationalError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import (
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Sources,
    Status,
)
from app.providers import services as provider_services
from app.providers.services import get_media_metadata as resolve_media_metadata

from .base import FloppyApiTestCase
from .helpers import (
    check_changes_history_record_structure,
    check_complete_media_structure,
    check_consumption_structure,
    check_media_structure,
    check_minimized_lists_structure,
    check_pagination_structure,
)


class MediaCoreTests(FloppyApiTestCase):
    """Validate media endpoint behavior for core media types."""

    def setUp(self):
        """Set up."""
        super().setUp()

    def _prepare_tv_progress_fixture(self, *, future_episode_number=None):
        """Give the first seeded show provider totals and watched episodes."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        tv_item.provider_episode_count = 11
        tv_item.save(update_fields=["provider_episode_count"])

        now = timezone.now()
        Episode.objects.filter(
            pk__in=[episode_media.pk for episode_media in self.episode_medias],
        ).update(status=Status.IN_PROGRESS.value)
        for episode_media in self.episode_medias:
            episode_item = episode_media.item
            episode_item.release_datetime = now - timezone.timedelta(days=1)
            if episode_item.episode_number == future_episode_number:
                episode_item.release_datetime = now + timezone.timedelta(days=1)
            episode_item.save(update_fields=["release_datetime"])

        watched_episode = self.episode_medias[0]
        Episode.objects.filter(pk=watched_episode.pk).update(
            status=Status.COMPLETED.value,
            end_date=now,
        )

    def test_media_list_get_returns_paginated_payload(self):
        """Media list endpoint should return standard pagination payload."""
        response = self.call_api("get", "api_media_list", headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=sum(
                len(items)
                for media_type, items in self.items_by_type.items()
                if media_type not in {MediaTypes.SEASON.value, MediaTypes.EPISODE.value}
            ),
            limit=20,
            offset=0,
        )
        self.assertIn("results", payload)
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertEqual(
                set(item),
                {
                    "id",
                    "consumption_id",
                    "item",
                    "item_id",
                    "parent_id",
                    "tracked",
                    "created_at",
                    "score",
                    "scored_at",
                    "status",
                    "progress",
                    "episodes_left",
                    "total_episodes_left",
                    "progress_scope",
                    "progress_unit",
                    "progressed_at",
                    "start_date",
                    "end_date",
                    "notes",
                    "source",
                    "lists",
                    "next_episode",
                    "show",
                },
            )

    def test_tv_media_list_reports_released_and_total_remaining_episodes(self):
        """TV list responses expose released and provider-total remaining counts."""
        self._prepare_tv_progress_fixture(future_episode_number=3)
        tv_item = self.items_by_type[MediaTypes.TV.value][0]

        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.TV.value,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        result = next(
            result
            for result in response.json()["results"]
            if result["item"]["media_id"] == tv_item.media_id
        )
        self.assertEqual(result["progress"], 1)
        self.assertEqual(result["episodes_left"], 1)
        self.assertEqual(result["total_episodes_left"], 10)

    def test_tv_media_list_excludes_dropped_seasons_from_remaining_total(self):
        """Dropped seasons do not contribute to either remaining count."""
        self._prepare_tv_progress_fixture()
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        for season_media, provider_count in zip(
            self.season_medias,
            (3, 4, 4),
        ):
            season_media.item.provider_episode_count = provider_count
            season_media.item.save(update_fields=["provider_episode_count"])
        self.season_medias[1].status = Status.DROPPED.value
        self.season_medias[1].save(update_fields=["status"])

        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.TV.value,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        result = next(
            result
            for result in response.json()["results"]
            if result["item"]["media_id"] == tv_item.media_id
        )
        self.assertEqual(result["episodes_left"], 2)
        self.assertEqual(result["total_episodes_left"], 6)

    def test_media_list_get_with_type_filter_returns_filtered_results(self):
        """Media list endpoint should filter results by media type."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"media_type": MediaTypes.TV.value},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        self.assertIn("results", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=len(self.tv_medias),
            limit=20,
            offset=0,
        )
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertEqual(item["item"]["media_type"], MediaTypes.TV.value)

    def test_media_list_get_with_status_filter_returns_filtered_results(self):
        """Media list endpoint should filter results by status."""
        completed_movie = self.movie_medias[0]
        completed_movie.status = Status.COMPLETED.value
        completed_movie.save(update_fields=["status"])

        response = self.call_api(
            "get",
            "api_media_list",
            params={
                "media_type": MediaTypes.MOVIE.value,
                "status": "3",
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertEqual(item["item"]["media_type"], MediaTypes.MOVIE.value)
            self.assertEqual(item["status"], 3)

    def test_media_list_get_with_search_filter_returns_filtered_results(self):
        """Media list endpoint should filter results by search query."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={
                "media_type": MediaTypes.MOVIE.value,
                "search": "Movie 1",
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertIn("movie 1", item["item"]["title"].lower())

    def test_media_list_get_with_sort_filter_returns_sorted_results(self):
        """Media list endpoint should sort results when requested."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"media_type": MediaTypes.MOVIE.value, "sort": "title_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        titles = [item["item"]["title"] for item in payload["results"]]
        self.assertEqual(titles, sorted(titles, reverse=True))

    def test_media_list_get_sorts_by_user_score(self):
        """Media list accepts score as a tracked-media sort field."""
        for media, score in zip(self.movie_medias, (7, 9, 8), strict=True):
            media.score = score
            media.save(update_fields=["score"])

        response = self.call_api(
            "get",
            "api_media_list",
            params={"media_type": MediaTypes.MOVIE.value, "sort": "score_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["score"] for item in response.json()["results"]],
            [9, 8, 7],
        )

        response = self.call_api(
            "get",
            "api_media_list",
            params={"sort": "score_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["score"] for item in response.json()["results"][:3]],
            [9, 8, 7],
        )

    def test_media_list_get_with_exclude_filter_excludes_type(self):
        """Media list endpoint should exclude requested media types."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"exclude": MediaTypes.MOVIE.value},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertNotEqual(item["item"]["media_type"], MediaTypes.MOVIE.value)

    def test_media_list_get_invalid_status_returns_bad_request(self):
        """Media list endpoint should reject unsupported status values."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"status": "abc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_list_get_invalid_sort_returns_bad_request(self):
        """Media list endpoint should reject unsupported sort values."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"sort": "unknown_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_type_list_invalid_type_returns_bad_request(self):
        """Media-type list endpoint should reject unsupported media types."""
        response = self.call_api(
            "get",
            "api_media_type_list",
            args=("invalid",),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_type_list_get_returns_paginated_payload(self):
        """Media-type list endpoint should return standard pagination payload."""
        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=len(self.movie_medias),
            limit=20,
            offset=0,
        )
        self.assertIn("results", payload)
        for item in payload["results"]:
            check_media_structure(self, item)

    def test_media_type_list_get_with_search_filter_returns_filtered_results(self):
        """Media-type list endpoint should filter by search query."""
        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            params={"search": "Movie 1"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertIn("movie 1", item["item"]["title"].lower())

    def test_media_type_list_get_with_sort_filter_returns_sorted_results(self):
        """Media-type list endpoint should sort by requested field."""
        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            params={"sort": "title_desc"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        titles = [item["item"]["title"] for item in payload["results"]]
        self.assertEqual(titles, sorted(titles, reverse=True))

    def test_media_type_list_get_with_status_filter_returns_filtered_results(self):
        """Media-type list endpoint should filter by status."""
        completed_movie = self.movie_medias[0]
        completed_movie.status = Status.COMPLETED.value
        completed_movie.save(update_fields=["status"])

        response = self.call_api(
            "get",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            params={"status": "3"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertGreaterEqual(len(payload["results"]), 1)
        for item in payload["results"]:
            check_media_structure(self, item)
            self.assertEqual(item["status"], 3)

    def test_media_type_list_post_creates_media(self):
        """Media-type create endpoint should create new media items."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": "manual",
                "title": "Manual Movie",
                "image": "https://example.com/poster.jpg",
                "status": 3,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()

        check_media_structure(self, payload)
        manual_media_id = payload["item"]["media_id"]
        self.assertEqual(str(UUID(manual_media_id)), manual_media_id)
        self.assertEqual(payload["item"]["source"], "manual")
        self.assertEqual(payload["item"]["media_type"], MediaTypes.MOVIE.value)

    def test_media_type_list_post_accepts_multipart(self):
        """Multipart create should validate exactly like the JSON path (#1043)."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": "manual",
                "title": "Multipart Movie",
                "image": "https://example.com/poster.jpg",
                "status": 3,
                "progress": 0,
            },
            headers=self.auth_headers,
            content_type=None,
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        check_media_structure(self, payload)
        self.assertEqual(payload["item"]["title"], "Multipart Movie")
        self.assertEqual(payload["status"], 3)

    def test_media_type_list_post_accepts_form_urlencoded(self):
        """Form-urlencoded create (no file part) must not hit the immutable QueryDict."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload=urlencode(
                {
                    "source": "manual",
                    "title": "Urlencoded Movie",
                    "status": 3,
                    "progress": 0,
                },
            ),
            headers=self.auth_headers,
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["item"]["title"], "Urlencoded Movie")

    def test_media_type_list_post_rejects_file_upload(self):
        """An uploaded file part is rejected instead of being stored as a filename."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": "manual",
                "title": "File Movie",
                "status": 3,
                "image": SimpleUploadedFile(
                    "cover.jpg",
                    b"not-really-a-jpeg",
                    content_type="image/jpeg",
                ),
            },
            headers=self.auth_headers,
            content_type=None,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("image_url", response.json()["detail"])
        self.assertFalse(Item.objects.filter(title="File Movie").exists())

    def test_media_type_list_post_applies_image_url(self):
        """`image_url` supplied on create is written to the item."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": "manual",
                "title": "Image URL Movie",
                "image_url": "https://example.com/from-image-url.jpg",
                "status": 3,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json()["item"]["image"],
            "https://example.com/from-image-url.jpg",
        )

    @patch("api.views.services.get_media_metadata")
    def test_media_type_list_post_applies_image_url_for_provider(self, mock_metadata):
        """`image_url` overrides provider artwork on create."""
        mock_metadata.return_value = {
            "media_id": 424242,
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "title": "Provider Movie",
            "image": "https://image.tmdb.org/t/p/w500/provider.jpg",
            "max_progress": None,
            "genres": [],
            "related": {},
            "details": {},
        }

        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": Sources.TMDB.value,
                "media_id": 424242,
                "image_url": "https://example.com/override.jpg",
                "status": 3,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json()["item"]["image"],
            "https://example.com/override.jpg",
        )

    def test_completed_post_removes_planning_and_merges_metadata(self):
        """Append-style Completed POST removes a stale planning row."""
        movie = self.movie_medias[0]
        movie.status = Status.PLANNING.value
        movie.score = 8
        movie.notes = "planned note"
        movie.save(update_fields=["status", "score", "notes"])

        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": movie.item.source,
                "media_id": movie.item.media_id,
                "status": 3,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        movies = Movie.objects.filter(item=movie.item, user=self.user1)
        self.assertEqual(movies.count(), 1)
        completed = movies.get()
        self.assertEqual(completed.status, Status.COMPLETED.value)
        self.assertEqual(completed.score, 8)
        self.assertEqual(completed.notes, "planned note")

    def test_media_type_list_post_without_status_still_defaults_to_planning(self):
        """Generic POST keeps its append-oriented Planning default."""
        movie = self.movie_medias[1]

        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={
                "source": movie.item.source,
                "media_id": movie.item.media_id,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Movie.objects.filter(
                item=movie.item,
                user=self.user1,
                status=Status.PLANNING.value,
            ).exists(),
        )

    def test_media_type_list_post_invalid_type_returns_bad_request(self):
        """Media-type create endpoint should reject unsupported media types."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=("invalid",),
            payload={"source": "tmdb", "media_id": "501"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_type_list_post_missing_body_returns_bad_request(self):
        """Media-type create endpoint should reject missing payloads."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_type_list_post_missing_media_id_returns_bad_request(self):
        """Provider-backed create should require media_id."""
        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.MOVIE.value,),
            payload={"source": "tmdb"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_returns_expected_shape(self, mock_metadata):
        """Media detail GET should return a complete serialized payload."""
        # TODO: Use real mock data fixtures instead of hardcoding values
        self._prepare_tv_progress_fixture()
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        mock_metadata.return_value = {
            "media_id": 1,
            "source": "tmdb",
            "source_url": "https://www.themoviedb.org/tv/1",
            "media_type": "tv",
            "title": "Pride",
            "max_progress": 11,
            "image": "https://image.tmdb.org/t/p/w500/rnahKduAA2VZFgrXemu97Fh6OD2.jpg",
            "synopsis": "Haru Satonaka is the captain of an ice-hockey team, a star athlete who stakes everything on hockey but can only consider love as a game. Aki Murase is a woman who has been waiting for her lover who went abroad two years ago. These two persons start a relationship while frankly admitting to each other that it is only a love game. …The result is the unfolding of a drama of people with their respective pasts and with their pride as individuals.",
            "genres": ["Drama"],
            "score": 7.8,
            "score_count": 30,
            "cast": [
                {
                    "person_id": "101",
                    "name": "Cast Member",
                    "image": "https://example.com/cast.jpg",
                    "known_for_department": "Acting",
                    "gender": "unknown",
                    "department": "Acting",
                    "role": "Lead",
                    "order": 0,
                    "episode_count": 11,
                }
            ],
            "crew": [
                {
                    "person_id": "202",
                    "name": "Crew Member",
                    "image": "https://example.com/crew.jpg",
                    "known_for_department": "Directing",
                    "gender": "unknown",
                    "department": "Directing",
                    "role": "Director",
                    "order": 0,
                }
            ],
            "details": {
                "format": "TV",
                "first_air_date": "2004-01-12",
                "last_air_date": "2004-03-22",
                "status": "Ended",
                "seasons": 1,
                "episodes": 11,
                "runtime": "1h 0m",
                "studios": ["Fuji Television Network"],
                "country": "Japan",
                "languages": ["Japanese"],
            },
            "related": {
                "seasons": [
                    {
                        "source": "tmdb",
                        "media_type": "season",
                        "image": "https://image.tmdb.org/t/p/w500/nCcGD18HmDFunCl8KBigqUPlIi8.jpg",
                        "media_id": 1,
                        "title": "Pride",
                        "season_number": 1,
                        "season_title": "Season 1",
                        "first_air_date": "2004-01-12",
                        "max_progress": 11,
                    }
                ],
                "recommendations": [
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/7t6iXlbfoBSfVyINLRHms5kqfze.jpg",
                        "media_id": 281401,
                        "title": "Finding Her Edge",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/poQgqeiKzA50etdQoJxELMA6M4s.jpg",
                        "media_id": 68780,
                        "title": "Star",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/qmQqRCHIdlQvnbFG3xh4OnkznVJ.jpg",
                        "media_id": 78749,
                        "title": "Transit Girls",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/g1sYAQt0OeCxzyfagSEqxUlsLnt.jpg",
                        "media_id": 271607,
                        "title": "The Fragrant Flower Blooms with Dignity",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/S0xduJgRyZCDVzTjtZVuHIGlhj.jpg",
                        "media_id": 156510,
                        "title": "Bibliophile Princess",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/i6gZ7fVpLBK3l5FkxCzMtEtT7Bz.jpg",
                        "media_id": 2822,
                        "title": "Felicity",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/tOKUKERvfaOf7Dy2IAKT5HYYXJJ.jpg",
                        "media_id": 133908,
                        "title": "SkyMed",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/7Zm7epVFEovMEVLpM6FvrjhaNXn.jpg",
                        "media_id": 881,
                        "title": "Days of Our Lives",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/lU2oU80UhGREf1dJBRb756KWEWJ.jpg",
                        "media_id": 37565,
                        "title": "Tsubasa RESERVoir CHRoNiCLE",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/mN3kMuh7Cy9byeySK6pymnpIOZO.jpg",
                        "media_id": 1054,
                        "title": "The Young and the Restless",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/ys1VsQYMNMlQIKt3eCx2DWUZcxW.jpg",
                        "media_id": 36837,
                        "title": "His and Her Circumstances",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/vxtmMvfTOYRL4fQn9B8Pla6oH2N.jpg",
                        "media_id": 22104,
                        "title": "Touch",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/mxkKDJNZg9z9WHC98qTGALPHlKL.jpg",
                        "media_id": 42893,
                        "title": "Hotaru no Hikari: It's Only a Little Light in My Life",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/qetD01amQRFX5ibXQ7rWLe6togE.jpg",
                        "media_id": 287591,
                        "title": "In the Clear Moonlit Dusk",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/zvUrE0KPWxKDPLtJWAfDIcdP7zl.jpg",
                        "media_id": 68786,
                        "title": "Hirugao: Love Affairs in the Afternoon",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/5k7bkqolsaJVCj321gLkuikk2Ax.jpg",
                        "media_id": 232926,
                        "title": "7th Time Loop: The Villainess Enjoys a Carefree Life Married to Her Worst Enemy!",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/nASkt8izgpR4toMYgiAnxfjWcE2.jpg",
                        "media_id": 94245,
                        "title": "Swagger",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/iKMCbTAkEgvA97M8Isdqp4t12Cf.jpg",
                        "media_id": 92875,
                        "title": "Sanditon",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/vycEpFfopE9M6AjCEubMOnrYSKm.jpg",
                        "media_id": 5325,
                        "title": "Army Wives",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/ejqfETzpBBnR89btARDKrLsv8dp.jpg",
                        "media_id": 72026,
                        "title": "Love and Lies",
                    },
                ],
            },
            "tvdb_id": 84831,
            "external_links": {
                "IMDb": "https://www.imdb.com/title/tt0416409/",
                "TVDB": "https://www.thetvdb.com/dereferrer/series/84831",
                "Wikidata": "https://www.wikidata.org/wiki/Q2040235",
            },
            "last_episode_season": 1,
            "next_episode_season": None,
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
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_complete_media_structure(self, payload)
        self.assertEqual(
            set(payload),
            {
                "id",
                "media_id",
                "source",
                "source_url",
                "media_type",
                "title",
                "max_progress",
                "episodes_left",
                "total_episodes_left",
                "image",
                "backdrop",
                "synopsis",
                "genres",
                "score",
                "score_count",
                "imdb_rating",
                "imdb_rating_count",
                "cast",
                "crew",
                "details",
                "related",
                "item_id",
                "parent_id",
                "tracked",
                "consumptions_number",
                "consumptions",
                "lists",
                "media_type_status",
            },
        )
        self.assertEqual(payload["episodes_left"], 2)
        self.assertEqual(payload["total_episodes_left"], 10)
        self.assertEqual(payload["cast"], mock_metadata.return_value["cast"])
        self.assertEqual(payload["crew"], mock_metadata.return_value["crew"])

    @patch("api.views.services.get_media_metadata")
    def test_provider_tracking_persists_episode_count(self, mock_metadata):
        """Provider-backed tracking stores the total used by later list calls."""
        mock_metadata.return_value = {
            "media_id": "9001",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "title": "Tracked Provider Show",
            "image": "https://example.com/provider-show.jpg",
            "max_progress": 12,
            "details": {"episodes": 12},
            "related": {"seasons": []},
        }

        response = self.call_api(
            "post",
            "api_media_type_list",
            args=(MediaTypes.TV.value,),
            payload={"source": Sources.TMDB.value, "media_id": "9001"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        item = Item.objects.get(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
        )
        self.assertEqual(item.provider_episode_count, 12)
        payload = response.json()
        self.assertEqual(payload["total_episodes_left"], 12)
        self.assertIsNone(payload["episodes_left"])

    @patch("api.views.services.get_media_metadata")
    def test_tv_detail_reports_tracked_season(self, mock_metadata):
        """TV detail should preserve tracked state for provider seasons."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        season_media = self.season_medias[0]
        mock_metadata.return_value = {
            "media_id": tv_item.media_id,
            "source": tv_item.source,
            "media_type": MediaTypes.TV.value,
            "related": {
                "seasons": [
                    {
                        "media_id": tv_item.media_id,
                        "source": tv_item.source,
                        "media_type": MediaTypes.SEASON.value,
                        "season_number": season_media.item.season_number,
                    },
                ],
            },
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        season = response.json()["related"]["seasons"][0]
        self.assertTrue(season["tracked"])
        self.assertEqual(season["id"], season_media.item_id)

    @patch("api.views.services.get_media_metadata")
    def test_tv_detail_untracked_season_reports_synced_imdb_rating(
        self,
        mock_metadata,
    ):
        """An untracked season with a previously-synced Item still shows its rating."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        Item.objects.create(
            media_id=tv_item.media_id,
            source=tv_item.source,
            media_type=MediaTypes.SEASON.value,
            title="Untracked Season 5",
            season_number=5,
            imdb_rating=6.7,
            imdb_rating_count=42,
        )
        mock_metadata.return_value = {
            "media_id": tv_item.media_id,
            "source": tv_item.source,
            "media_type": MediaTypes.TV.value,
            "related": {
                "seasons": [
                    {
                        "media_id": tv_item.media_id,
                        "source": tv_item.source,
                        "media_type": MediaTypes.SEASON.value,
                        "season_number": 5,
                    },
                ],
            },
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        season = response.json()["related"]["seasons"][0]
        self.assertFalse(season["tracked"])
        self.assertEqual(season["item"]["imdb_rating"], 6.7)
        self.assertEqual(season["item"]["imdb_rating_count"], 42)

    def test_media_detail_get_invalid_type_returns_bad_request(self):
        """Media detail endpoint should reject unsupported media types."""
        response = self.call_api(
            "get",
            "api_media_detail",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_detail_get_invalid_media_id_returns_ok_with_null_item_id(self):
        """Media detail endpoint no longer 500s when provider metadata is bare.

        Regression test for #888: build_item_id()/build_parent_id() used to
        dereference `media_type` unconditionally, so metadata missing that
        field (as returned here by the shared get_media_metadata patch)
        crashed outside any handler instead of degrading gracefully.
        """
        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["item_id"])
        self.assertIsNone(response.data["parent_id"])

    def test_media_detail_get_exposes_imdb_rating_for_untracked_item(self):
        """Untracked movies with a previously-synced Item still show IMDb rating."""
        Item.objects.create(
            media_id="777",
            source="tmdb",
            media_type=MediaTypes.MOVIE.value,
            title="Synced Movie",
            imdb_rating=8.5,
            imdb_rating_count=1200,
        )

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 777),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["imdb_rating"], 8.5)
        self.assertEqual(response.data["imdb_rating_count"], 1200)

    def test_media_detail_get_imdb_rating_none_without_synced_item(self):
        """Media with no Item row at all reports a null IMDb rating."""
        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["imdb_rating"])
        self.assertIsNone(response.data["imdb_rating_count"])

    def test_media_detail_get_media_type_status_enabled_by_default(self):
        """media_type_status reports enabled with no message when unrestricted."""
        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["media_type_status"],
            {"media_type": "movie", "enabled": True, "message": None},
        )

    def test_media_detail_get_media_type_status_disabled_suggests_alternate(self):
        """Disabling anime surfaces a redirect hint toward tv, still enabled."""
        self.user1.anime_enabled = False
        self.user1.save(update_fields=["anime_enabled"])

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.ANIME.value, Sources.MAL.value, 2001),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        status = response.data["media_type_status"]
        self.assertEqual(status["media_type"], "anime")
        self.assertFalse(status["enabled"])
        self.assertIn("tv", status["message"])

    def test_media_detail_get_media_type_status_disabled_without_alternate(self):
        """Disabling a type with no known alternate omits the redirect hint."""
        self.user1.game_enabled = False
        self.user1.save(update_fields=["game_enabled"])

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.GAME.value, Sources.IGDB.value, 4001),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        status = response.data["media_type_status"]
        self.assertEqual(status["media_type"], "game")
        self.assertFalse(status["enabled"])
        self.assertNotIn("also be available", status["message"])

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_podcast_resolves_tracked_and_untracked_episodes(
        self,
        mock_metadata,
    ):
        """Generic podcast details should identify catalog and tracked episodes."""
        show = PodcastShow.objects.create(
            podcast_uuid="api-podcast-show",
            source=Sources.POCKETCASTS.value,
            title="API Podcast Show",
            image="https://example.com/api-podcast.jpg",
            description="API podcast description",
            genres=["News"],
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="api-podcast-episode",
            title="API Podcast Episode",
            duration=1200,
        )
        mock_metadata.side_effect = resolve_media_metadata

        untracked_response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.PODCAST.value, Sources.POCKETCASTS.value, episode.episode_uuid),
            headers=self.auth_headers,
        )

        self.assertEqual(untracked_response.status_code, 200)
        untracked_payload = untracked_response.json()
        self.assertEqual(untracked_payload["media_id"], episode.episode_uuid)
        self.assertEqual(untracked_payload["source"], Sources.POCKETCASTS.value)
        self.assertEqual(untracked_payload["media_type"], MediaTypes.PODCAST.value)
        self.assertEqual(untracked_payload["title"], episode.title)
        self.assertEqual(untracked_payload["image"], show.image)
        self.assertFalse(untracked_payload["tracked"])

        item = Item.objects.create(
            media_id=episode.episode_uuid,
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title=episode.title,
            image=show.image,
        )
        Podcast.objects.create(
            user=self.user1,
            item=item,
            show=show,
            episode=episode,
            status=Status.COMPLETED.value,
        )

        tracked_response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.PODCAST.value, Sources.POCKETCASTS.value, episode.episode_uuid),
            headers=self.auth_headers,
        )

        self.assertEqual(tracked_response.status_code, 200)
        tracked_payload = tracked_response.json()
        self.assertEqual(tracked_payload["media_id"], episode.episode_uuid)
        self.assertEqual(tracked_payload["title"], episode.title)
        self.assertTrue(tracked_payload["tracked"])

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_unresolvable_podcast_returns_not_found(self, mock_metadata):
        """An unknown podcast episode should return 404 instead of an empty 200."""
        mock_metadata.side_effect = resolve_media_metadata

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.PODCAST.value, Sources.POCKETCASTS.value, "missing-episode"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Media not found."})

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_book_publishers_shapes(self, mock_metadata):
        """Providers return publishers as a list, a joined string, or nothing."""
        cases = (
            # Open Library edition records return a list
            (["Smithsonian Institution Press", "Other"], ["Smithsonian Institution Press", "Other"]),
            # BoardGameGeek joins names into one string
            ("Smithsonian Institution Press, Other", ["Smithsonian Institution Press", "Other"]),
            # an edition with no publisher
            (None, []),
            ("", []),
        )
        for provider_value, expected in cases:
            with self.subTest(publishers=provider_value):
                mock_metadata.return_value = {
                    "media_id": "OL1418181M",
                    "source": Sources.OPENLIBRARY.value,
                    "media_type": MediaTypes.BOOK.value,
                    "title": "The Lawn",
                    "details": {"publishers": provider_value},
                }

                response = self.call_api(
                    "get",
                    "api_media_detail",
                    args=(
                        MediaTypes.BOOK.value,
                        Sources.OPENLIBRARY.value,
                        "OL1418181M",
                    ),
                    headers=self.auth_headers,
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["details"]["publishers"], expected)

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_board_game_designers_shapes(self, mock_metadata):
        """Designers and publishers are lists in the response whatever the provider sent."""
        mock_metadata.return_value = {
            "media_id": "1",
            "source": Sources.BGG.value,
            "media_type": MediaTypes.BOARDGAME.value,
            "title": "Game",
            "details": {"designers": None, "publishers": ["A", "B"]},
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.BOARDGAME.value, Sources.BGG.value, "1"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        details = response.json()["details"]
        self.assertEqual(details["designers"], [])
        self.assertEqual(details["publishers"], ["A", "B"])

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_invalid_music_id_returns_not_found(self, mock_metadata):
        """An invalid MusicBrainz ID should return 404 instead of an empty 200."""
        mock_metadata.side_effect = resolve_media_metadata

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MUSIC.value, Sources.MUSICBRAINZ.value, "invalid-id"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Media not found."})

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_music_preserves_identity_metadata(self, mock_metadata):
        """Generic music details should preserve provider identity fields."""
        mock_metadata.return_value = {
            "media_id": "11111111-1111-1111-1111-111111111111",
            "source": Sources.MUSICBRAINZ.value,
            "media_type": MediaTypes.MUSIC.value,
            "title": "API Song - API Artist",
            "image": "https://example.com/api-song.jpg",
            "synopsis": "",
            "genres": [],
            "related": {},
            "details": {"artist": "API Artist"},
            "max_progress": None,
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(
                MediaTypes.MUSIC.value,
                Sources.MUSICBRAINZ.value,
                "11111111-1111-1111-1111-111111111111",
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["media_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(payload["source"], Sources.MUSICBRAINZ.value)
        self.assertEqual(payload["media_type"], MediaTypes.MUSIC.value)
        self.assertEqual(payload["title"], "API Song - API Artist")

    @patch("api.views.services.get_media_metadata", side_effect=RuntimeError("boom"))
    def test_media_detail_get_provider_failure_remains_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Unexpected provider failures should not be converted into 404s."""
        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.MUSIC.value, Sources.MUSICBRAINZ.value, "valid-looking-id"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("errors", response.data)
        self.assertNotIn("boom", response.data["detail"])

    @patch("api.views._queue_game_lengths_refresh", return_value=True)
    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_game_creates_item_for_untracked_game(
        self,
        mock_metadata,
        _mock_queue_refresh,
    ):
        """Untracked IGDB games should get an Item so lengths can resolve, #989."""
        mock_metadata.return_value = {
            "media_id": "9201",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "title": "Untracked Game",
            "image": "https://example.com/untracked-game.jpg",
            "synopsis": "",
            "genres": [],
            "related": {},
            "details": {},
            "max_progress": None,
        }

        self.assertFalse(
            Item.objects.filter(
                media_id="9201",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
            ).exists(),
        )

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.GAME.value, Sources.IGDB.value, "9201"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Item.objects.filter(
                media_id="9201",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
            ).exists(),
        )
        payload = response.json()
        self.assertEqual(payload["details"]["provider_game_lengths"]["state"], "pending")

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_get_game_ready_state_strips_raw_provider_payload(
        self,
        mock_metadata,
    ):
        """Existing lengths should report ready and omit raw provider blobs, #989."""
        Item.objects.create(
            media_id="9202",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Ready Game",
            provider_game_lengths={
                "active_source": "igdb",
                "igdb": {
                    "game_id": 9202,
                    "summary": {
                        "hastily_seconds": 3600,
                        "normally_seconds": 7200,
                        "completely_seconds": 10800,
                        "count": 12,
                    },
                    "raw": [{"should": "not leak"}],
                },
            },
            provider_game_lengths_source="igdb",
            provider_game_lengths_match="exact_title_year",
        )
        mock_metadata.return_value = {
            "media_id": "9202",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "title": "Ready Game",
            "image": "https://example.com/ready-game.jpg",
            "synopsis": "",
            "genres": [],
            "related": {},
            "details": {},
            "max_progress": None,
        }

        response = self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.GAME.value, Sources.IGDB.value, "9202"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        lengths = response.json()["details"]["provider_game_lengths"]
        self.assertEqual(lengths["state"], "ready")
        self.assertEqual(lengths["igdb"]["summary"]["normally_seconds"], 7200)
        self.assertNotIn("raw", lengths["igdb"])

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_patch_updates_media_fields(self, mock_metadata):
        """Media detail PATCH should update mutable media fields."""
        # TODO: Use real mock data fixtures instead of hardcoding values
        status = 2
        score = 8
        notes = "Great TV show!"
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        mock_metadata.return_value = {
            "media_id": 1,
            "source": "tmdb",
            "source_url": "https://www.themoviedb.org/tv/1",
            "media_type": "tv",
            "title": "Pride",
            "max_progress": 11,
            "image": "https://image.tmdb.org/t/p/w500/rnahKduAA2VZFgrXemu97Fh6OD2.jpg",
            "synopsis": "Haru Satonaka is the captain of an ice-hockey team, a star athlete who stakes everything on hockey but can only consider love as a game. Aki Murase is a woman who has been waiting for her lover who went abroad two years ago. These two persons start a relationship while frankly admitting to each other that it is only a love game. …The result is the unfolding of a drama of people with their respective pasts and with their pride as individuals.",
            "genres": ["Drama"],
            "score": 7.8,
            "score_count": 30,
            "details": {
                "format": "TV",
                "first_air_date": "2004-01-12",
                "last_air_date": "2004-03-22",
                "status": "Ended",
                "seasons": 1,
                "episodes": 11,
                "runtime": "1h 0m",
                "studios": ["Fuji Television Network"],
                "country": "Japan",
                "languages": ["Japanese"],
            },
            "related": {
                "seasons": [
                    {
                        "source": "tmdb",
                        "media_type": "season",
                        "image": "https://image.tmdb.org/t/p/w500/nCcGD18HmDFunCl8KBigqUPlIi8.jpg",
                        "media_id": 1,
                        "title": "Pride",
                        "season_number": 1,
                        "season_title": "Season 1",
                        "first_air_date": "2004-01-12",
                        "max_progress": 11,
                    }
                ],
                "recommendations": [
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/7t6iXlbfoBSfVyINLRHms5kqfze.jpg",
                        "media_id": 281401,
                        "title": "Finding Her Edge",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/poQgqeiKzA50etdQoJxELMA6M4s.jpg",
                        "media_id": 68780,
                        "title": "Star",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/qmQqRCHIdlQvnbFG3xh4OnkznVJ.jpg",
                        "media_id": 78749,
                        "title": "Transit Girls",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/g1sYAQt0OeCxzyfagSEqxUlsLnt.jpg",
                        "media_id": 271607,
                        "title": "The Fragrant Flower Blooms with Dignity",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/S0xduJgRyZCDVzTjtZVuHIGlhj.jpg",
                        "media_id": 156510,
                        "title": "Bibliophile Princess",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/i6gZ7fVpLBK3l5FkxCzMtEtT7Bz.jpg",
                        "media_id": 2822,
                        "title": "Felicity",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/tOKUKERvfaOf7Dy2IAKT5HYYXJJ.jpg",
                        "media_id": 133908,
                        "title": "SkyMed",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/7Zm7epVFEovMEVLpM6FvrjhaNXn.jpg",
                        "media_id": 881,
                        "title": "Days of Our Lives",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/lU2oU80UhGREf1dJBRb756KWEWJ.jpg",
                        "media_id": 37565,
                        "title": "Tsubasa RESERVoir CHRoNiCLE",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/mN3kMuh7Cy9byeySK6pymnpIOZO.jpg",
                        "media_id": 1054,
                        "title": "The Young and the Restless",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/ys1VsQYMNMlQIKt3eCx2DWUZcxW.jpg",
                        "media_id": 36837,
                        "title": "His and Her Circumstances",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/vxtmMvfTOYRL4fQn9B8Pla6oH2N.jpg",
                        "media_id": 22104,
                        "title": "Touch",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/mxkKDJNZg9z9WHC98qTGALPHlKL.jpg",
                        "media_id": 42893,
                        "title": "Hotaru no Hikari: It's Only a Little Light in My Life",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/qetD01amQRFX5ibXQ7rWLe6togE.jpg",
                        "media_id": 287591,
                        "title": "In the Clear Moonlit Dusk",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/zvUrE0KPWxKDPLtJWAfDIcdP7zl.jpg",
                        "media_id": 68786,
                        "title": "Hirugao: Love Affairs in the Afternoon",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/5k7bkqolsaJVCj321gLkuikk2Ax.jpg",
                        "media_id": 232926,
                        "title": "7th Time Loop: The Villainess Enjoys a Carefree Life Married to Her Worst Enemy!",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/nASkt8izgpR4toMYgiAnxfjWcE2.jpg",
                        "media_id": 94245,
                        "title": "Swagger",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/iKMCbTAkEgvA97M8Isdqp4t12Cf.jpg",
                        "media_id": 92875,
                        "title": "Sanditon",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/vycEpFfopE9M6AjCEubMOnrYSKm.jpg",
                        "media_id": 5325,
                        "title": "Army Wives",
                    },
                    {
                        "source": "tmdb",
                        "media_type": "tv",
                        "image": "https://image.tmdb.org/t/p/w500/ejqfETzpBBnR89btARDKrLsv8dp.jpg",
                        "media_id": 72026,
                        "title": "Love and Lies",
                    },
                ],
            },
            "tvdb_id": 84831,
            "external_links": {
                "IMDb": "https://www.imdb.com/title/tt0416409/",
                "TVDB": "https://www.thetvdb.com/dereferrer/series/84831",
                "Wikidata": "https://www.wikidata.org/wiki/Q2040235",
            },
            "last_episode_season": 1,
            "next_episode_season": None,
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
        }

        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id),
            payload={"status": status, "score": score, "notes": notes},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_complete_media_structure(self, payload)
        self.assertEqual(payload["consumptions"][0]["status"], status)
        self.assertEqual(payload["consumptions"][0]["score"], score)
        self.assertEqual(payload["consumptions"][0]["notes"], notes)

    def test_media_detail_patch_sets_image_url(self):
        """PATCH `image_url` should update the item's artwork (#1043)."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={
                "status": 3,
                "image_url": "https://example.com/patched.jpg",
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200, response.content)
        movie_item.refresh_from_db()
        self.assertEqual(movie_item.image, "https://example.com/patched.jpg")

    def test_media_detail_patch_image_only_is_allowed(self):
        """An image-only PATCH must not trip the 'no valid fields' guard."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"image": "https://example.com/alias.jpg"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200, response.content)
        movie_item.refresh_from_db()
        self.assertEqual(movie_item.image, "https://example.com/alias.jpg")

    def test_media_detail_patch_invalid_image_url_returns_bad_request(self):
        """A malformed image URL is rejected before anything is written."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        original_image = movie_item.image
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"image_url": "not-a-url"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        movie_item.refresh_from_db()
        self.assertEqual(movie_item.image, original_image)

    def test_media_detail_patch_invalid_type_returns_bad_request(self):
        """Media detail PATCH should reject unsupported media types."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=("invalid", movie_item.source, movie_item.media_id),
            payload={"status": 3},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_detail_patch_invalid_media_id_returns_not_found(self):
        """Media detail PATCH should return not found for unknown provider ids."""
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            payload={"status": 3},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_media_detail_patch_with_unknown_field_returns_bad_request(self):
        """Media PATCH should reject fields outside the allowed whitelist."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"unknown_field": "value"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no valid fields", response.json().get("detail", "").lower())

    def test_media_detail_patch_rejects_dropped_only(self):
        """Media PATCH does not support the episode-only dropped field."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"dropped": True},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no valid fields", response.json().get("detail", "").lower())

    def _mock_movie_metadata(self, mock_metadata):
        """Configure a minimal valid movie metadata mock for PATCH tests."""
        mock_metadata.return_value = {
            "media_id": 550,
            "source": "tmdb",
            "source_url": "https://www.themoviedb.org/movie/550",
            "media_type": "movie",
            "title": "Fight Club",
            "max_progress": 1,
            "image": "https://image.tmdb.org/t/p/w500/placeholder.jpg",
            "synopsis": "A depressed man forms an underground fight club.",
            "genres": ["Drama"],
            "score": 8.4,
            "score_count": 100,
            "details": {
                "format": "Movie",
                "release_date": "1999-10-15",
                "status": "Released",
                "runtime": "2h 19m",
                "studios": ["Fox 2000 Pictures"],
                "country": "United States of America",
                "languages": ["English"],
            },
            "related": {"recommendations": []},
        }

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_patch_accepts_string_status_label(self, mock_metadata):
        """Media PATCH should accept a human-readable status label."""
        self._mock_movie_metadata(mock_metadata)
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"status": "Completed"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["consumptions"][0]["status"], 3)

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_patch_accepts_case_insensitive_status_label(
        self,
        mock_metadata,
    ):
        """Media PATCH should accept a status label regardless of casing."""
        self._mock_movie_metadata(mock_metadata)
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"status": "in progress"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["consumptions"][0]["status"], 1)

    @patch("api.views.services.get_media_metadata")
    def test_media_detail_patch_accepts_numeric_string_status(self, mock_metadata):
        """Media PATCH should accept a status code sent as a numeric string."""
        self._mock_movie_metadata(mock_metadata)
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"status": "3"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["consumptions"][0]["status"], 3)

    def test_media_detail_patch_rejects_unknown_status_label(self):
        """Media PATCH should reject a status label that doesn't match any status."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"status": "not-a-status"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid status value", response.json().get("detail", "").lower())

    def test_media_changes_history_returns_paginated_payload(self):
        """Changes history endpoint should return change entries."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_changes_history",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=3,
            limit=20,
            offset=0,
        )
        self.assertIn("results", payload)
        for item in payload["results"]:
            check_changes_history_record_structure(self, item)

    def test_media_changes_history_invalid_type_returns_bad_request(self):
        """Changes history endpoint should reject unsupported media types."""
        response = self.call_api(
            "get",
            "api_media_changes_history",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_changes_history_invalid_media_id_returns_not_found(self):
        """Changes history endpoint should return not found for unknown provider ids."""
        response = self.call_api(
            "get",
            "api_media_changes_history",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_media_consumption_history_returns_paginated_payload(self):
        """Consumption history endpoint should return consumption entries."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_consumption_history",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=1,
            limit=20,
            offset=0,
        )
        self.assertIn("results", payload)
        for item in payload["results"]:
            check_consumption_structure(self, item)

    def test_media_consumption_history_invalid_type_returns_bad_request(self):
        """Consumption history endpoint should reject unsupported media types."""
        response = self.call_api(
            "get",
            "api_media_consumption_history",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_consumption_history_invalid_media_id_returns_not_found(self):
        """Consumption history endpoint should return not found for unknown ids."""
        response = self.call_api(
            "get",
            "api_media_consumption_history",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_media_consumption_history_untouched_movie_unchanged(self):
        """A movie with zero MoviePlay rows returns the tracker row as before."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_consumption_history",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_pagination_structure(
            self,
            payload["pagination"],
            total=1,
            limit=20,
            offset=0,
        )
        self.assertEqual(
            payload["results"][0]["consumption_id"],
            self.movie_medias[0].id,
        )

    def test_media_consumption_history_shows_multiple_movie_plays(self):
        """Once a movie has MoviePlay rows, history lists each play separately."""
        movie = self.movie_medias[0]
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        play_one, _ = movie.watch(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC))
        play_two, _ = movie.watch(datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC))

        response = self.call_api(
            "get",
            "api_media_consumption_history",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_pagination_structure(
            self,
            payload["pagination"],
            total=2,
            limit=20,
            offset=0,
        )
        returned_ids = {entry["consumption_id"] for entry in payload["results"]}
        self.assertEqual(returned_ids, {play_one.id, play_two.id})

    def test_media_consumption_entry_detail_delete_removes_movie_play(self):
        """Entry-detail DELETE finds a MoviePlay id once the movie has plays."""
        movie = self.movie_medias[0]
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        play, _ = movie.watch(datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC))

        response = self.call_api(
            "delete",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                play.id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(MoviePlay.objects.filter(id=play.id).exists())

    def test_media_consumption_entry_detail_colliding_movie_id_deletes_play(self):
        """A play id equal to the Movie id deletes the play, not the movie.

        Movie and MoviePlay use independent id sequences, so an entry id can
        match both. Checking the Movie row first deleted the whole movie and
        its plays (issue #1217).
        """
        movie = self.movie_medias[0]
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        MoviePlay.objects.create(
            id=movie.id,
            movie=movie,
            end_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )
        survivor = MoviePlay.objects.create(
            id=movie.id + 1000,
            movie=movie,
            end_date=datetime.datetime(2025, 2, 14, tzinfo=datetime.UTC),
        )

        response = self.call_api(
            "delete",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                movie.id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(Movie.objects.filter(id=movie.id).exists())
        self.assertFalse(MoviePlay.objects.filter(id=movie.id).exists())
        self.assertTrue(MoviePlay.objects.filter(id=survivor.id).exists())

    def test_media_consumption_entry_detail_colliding_movie_id_reads_play(self):
        """GET and PATCH resolve a colliding entry id to the play, not the movie.

        The movie's own end_date/notes must stay untouched when the id belongs
        to a MoviePlay (issue #1217).
        """
        movie = self.movie_medias[0]
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        MoviePlay.objects.create(
            id=movie.id,
            movie=movie,
            end_date=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        )

        get_response = self.call_api(
            "get",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                movie.id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertIsNotNone(get_response.json()["end_date"])

        patch_response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                movie.id,
            ),
            payload={"notes": "collision-note"},
            headers=self.auth_headers,
        )

        self.assertEqual(patch_response.status_code, 200)
        movie.refresh_from_db()
        self.assertNotEqual(movie.notes, "collision-note")

    def test_media_consumption_entry_detail_delete_removes_history_entry(self):
        """Entry-detail DELETE should remove an existing consumption row."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "delete",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)

        get_response = self.call_api(
            "get",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 404)

    def test_media_consumption_entry_detail_get_returns_expected_structure(self):
        """Entry-detail endpoint should return a complete serialized payload."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "get",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertEqual(
            set(payload),
            {
                "consumption_id",
                "created",
                "score",
                "scored_at",
                "progress",
                "progressed_at",
                "status",
                "start_date",
                "end_date",
                "notes",
                "source",
            },
        )

    def test_media_consumption_entry_detail_get_preserves_actual_progress(self):
        """Entry-detail endpoint should return the stored non-binary progress value."""
        game_item = self.items_by_type[MediaTypes.GAME.value][0]
        game_media = self.game_medias[0]
        game_media.progress = 120
        game_media.status = Status.IN_PROGRESS.value
        game_media.save(update_fields=["progress", "status"])

        response = self.call_api(
            "get",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.GAME.value,
                game_item.source,
                game_item.media_id,
                game_media.id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertEqual(payload["progress"], 120)
        self.assertEqual(payload["status"], 1)

    def test_media_consumption_entry_detail_invalid_type_methods(self):
        """Entry-detail endpoints should reject unsupported media types."""
        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_consumption_entry_detail",
                args=("invalid", "tmdb", 501, 1),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 400)

    def test_media_consumption_entry_detail_invalid_media_id_methods(self):
        """Entry-detail endpoints should return not found for unknown media ids."""
        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_consumption_entry_detail",
                args=(MediaTypes.MOVIE.value, "tmdb", 999999, 1),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 404)

    def test_media_consumption_entry_detail_invalid_consumption_id_methods(self):
        """Entry-detail endpoints should return not found for unknown consumption ids."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        invalid_consumption_id = 999999

        for method in ["get", "patch", "delete"]:
            response = self.call_api(
                method,
                "api_media_consumption_entry_detail",
                args=(
                    MediaTypes.MOVIE.value,
                    movie_item.source,
                    movie_item.media_id,
                    invalid_consumption_id,
                ),
                payload={"notes": "x"} if method == "patch" else None,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, 404)

    def test_media_consumption_entry_detail_patch_updates_history_entry(self):
        """Entry-detail PATCH should persist valid updates."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            payload={"notes": "updated-from-test"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertEqual(payload["notes"], "updated-from-test")

    def test_exact_history_patch_upgrades_planning_row_without_duplicate(self):
        """Exact history PATCH updates the selected row in place."""
        movie = self.movie_medias[2]
        movie.status = Status.PLANNING.value
        movie.save(update_fields=["status"])
        consumption_id = movie.id
        end_date = timezone.now().isoformat()

        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie.item.source,
                movie.item.media_id,
                consumption_id,
            ),
            payload={"status": 3, "end_date": end_date},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Movie.objects.filter(item=movie.item, user=self.user1).count(),
            1,
        )
        movie.refresh_from_db()
        self.assertEqual(movie.id, consumption_id)
        self.assertEqual(movie.status, Status.COMPLETED.value)

    def test_media_consumption_entry_detail_patch_null_score_clears_rating(self):
        """Entry-detail PATCH should clear an existing score when sent null."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        self.movie_medias[0].score = 7
        self.movie_medias[0].save()

        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            payload={"score": None},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertIsNone(payload["score"])

    def test_media_consumption_entry_detail_patch_score_reports_scored_at(self):
        """A score PATCH returns when the rating was set, for sync clients (#1280)."""
        movie = self.movie_medias[0]
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                movie.id,
            ),
            payload={"score": 8.4},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        movie.refresh_from_db()
        self.assertIsNotNone(movie.scored_at)
        self.assertEqual(
            parse_datetime(response.json()["scored_at"]),
            movie.scored_at,
        )

    def test_media_consumption_entry_detail_patch_invalid_score_returns_bad_request(
        self,
    ):
        """Entry-detail PATCH should reject non-numeric score values."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            payload={"score": "not-a-number"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_consumption_entry_detail_patch_accepts_datetime_strings(self):
        """Entry-detail PATCH should accept ISO datetime values for date fields."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            payload={
                "start_date": "2023-10-01T00:00:00Z",
                "end_date": "2023-10-02T15:30:00Z",
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_consumption_structure(self, payload)
        self.assertTrue(payload["start_date"].startswith("2023-10-01T00:00:00"))
        self.assertTrue(payload["end_date"].startswith("2023-10-02T15:30:00"))

    def test_media_consumption_entry_detail_patch_invalid_payload_returns_bad_request(
        self,
    ):
        """Entry-detail PATCH should reject invalid payload values."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        consumption_id = self.movie_medias[0].id
        response = self.call_api(
            "patch",
            "api_media_consumption_entry_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                consumption_id,
            ),
            payload={"end_date": "invalid-date"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_lists_get_returns_lists(self):
        """Media list relation endpoint should return associated lists."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self.call_api(
            "get",
            "api_media_lists",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertEqual(len(payload["results"]), 1)
        for item in payload["results"]:
            check_minimized_lists_structure(self, item)

    def test_media_lists_get_invalid_media_id_returns_empty_results(self):
        """Media list relation endpoint should return empty results for unknown media."""
        response = self.call_api(
            "get",
            "api_media_lists",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])

    def test_media_lists_invalid_type_methods(self):
        """Media list relation endpoints should reject unsupported media types."""
        get_response = self.call_api(
            "get",
            "api_media_lists",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 400)

        list_id = self.lists_by_name["favorites"].id
        put_response = self.call_api(
            "put",
            "api_media_list_detail",
            args=("invalid", "tmdb", 501, list_id),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(put_response.status_code, 400)

        delete_response = self.call_api(
            "delete",
            "api_media_list_detail",
            args=("invalid", "tmdb", 501, list_id),
            headers=self.auth_headers,
        )
        self.assertEqual(delete_response.status_code, 400)

    def test_media_list_detail_delete_removes_media_from_list(self):
        """Media list detail DELETE should remove media from an existing list."""
        list_id = self.lists_by_name["favorites"].id
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self.call_api(
            "delete",
            "api_media_list_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                list_id,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 204)
        get_response = self.call_api(
            "get",
            "api_media_lists",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["results"], [])

    def test_media_list_detail_delete_invalid_media_id_returns_not_found(self):
        """Media list detail DELETE should reject unknown media ids."""
        list_id = self.lists_by_name["favorites"].id
        response = self.call_api(
            "delete",
            "api_media_list_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999, list_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_media_list_detail_delete_invalid_list_id_returns_not_found(self):
        """Media list detail DELETE should reject unknown list ids."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "delete",
            "api_media_list_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                999999,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    def test_media_list_detail_put_adds_media_to_list(self):
        """Media list detail PUT should add media when missing from list."""
        list_id = self.lists_by_name["favorites"].id
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][1]

        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        get_response = self.call_api(
            "get",
            "api_media_lists",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.json()
        self.assertIn("results", payload)
        for item in payload["results"]:
            check_minimized_lists_structure(self, item)
            self.assertEqual(item["list_id"], list_id)

    @patch("api.fork_helpers.services.get_media_metadata")
    def test_media_list_detail_put_invalid_media_id_returns_not_found(
        self,
        mock_metadata,
    ):
        """Media list detail PUT should reject ids the provider does not know."""
        mock_metadata.side_effect = provider_services.ProviderAPIError(
            "tmdb",
            Mock(response=Mock(status_code=404, headers={})),
        )
        list_id = self.lists_by_name["favorites"].id
        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999, list_id),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Item.objects.filter(media_id="999999").exists())

    @patch("api.fork_helpers.services.get_media_metadata")
    def test_media_list_detail_put_creates_unknown_item(self, mock_metadata):
        """Media list detail PUT should create an item Floppy has not seen."""
        mock_metadata.return_value = {
            "media_id": "999999",
            "source": "tmdb",
            "media_type": MediaTypes.MOVIE.value,
            "title": "Fresh Movie",
            "image": "https://example.com/fresh.jpg",
        }
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999, list_id),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        item = Item.objects.get(media_id="999999", source="tmdb")
        self.assertEqual(item.title, "Fresh Movie")
        self.assertTrue(
            self.lists_by_name["favorites"].items.filter(id=item.id).exists(),
        )

    @patch("api.views.run_retryable_db_operation")
    def test_media_list_detail_put_returns_503_on_persistent_lock(self, mock_retry):
        """Media list detail PUT should return 503 when the DB stays locked."""
        mock_retry.side_effect = OperationalError("database is locked")
        list_id = self.lists_by_name["favorites"].id
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][1]

        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                list_id,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.json())

    def test_media_list_detail_put_invalid_list_id_returns_not_found(self):
        """Media list detail PUT should reject unknown list ids."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][1]
        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(
                MediaTypes.MOVIE.value,
                movie_item.source,
                movie_item.media_id,
                999999,
            ),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 404)

    @patch("api.views.services.get_media_metadata")
    def test_media_recommendations_returns_related_items(self, mock_metadata):
        """Recommendations endpoint should return provider recommendations."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        recommended_item = self.items_by_type[MediaTypes.MOVIE.value][1]
        mock_metadata.return_value = {
            "related": {
                "recommendations": [
                    {
                        "media_id": recommended_item.media_id,
                        "source": recommended_item.source,
                        "media_type": recommended_item.media_type,
                        "title": recommended_item.title,
                        "image": recommended_item.image,
                    },
                ],
            },
        }

        response = self.call_api(
            "get",
            "api_media_recommendations",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["media_id"], recommended_item.media_id)
        self.assertEqual(payload[0]["title"], recommended_item.title)

    def test_media_recommendations_invalid_type_returns_bad_request(self):
        """Recommendations endpoint should reject unsupported media types."""
        response = self.call_api(
            "get",
            "api_media_recommendations",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_media_recommendations_invalid_media_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Recommendations endpoint should surface provider lookup failures."""
        response = self.call_api(
            "get",
            "api_media_recommendations",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata")
    def test_media_seasons_get_returns_expected_structure(self, mock_metadata):
        """Media seasons endpoint should return paginated media payload."""
        tv_item = self.items_by_type[MediaTypes.TV.value][0]
        mock_metadata.return_value = {
            "related": {
                "seasons": [
                    {
                        "season_number": 1,
                        "season_title": "Season 1",
                        "image": "https://example.com/season-1.jpg",
                    },
                    {
                        "season_number": 2,
                        "season_title": "Season 2",
                        "image": "https://example.com/season-2.jpg",
                    },
                ],
            },
        }

        response = self.call_api(
            "get",
            "api_media_seasons",
            args=(MediaTypes.TV.value, tv_item.source, tv_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("pagination", payload)
        check_pagination_structure(
            self,
            payload["pagination"],
            total=2,
            limit=20,
            offset=0,
        )
        self.assertIn("results", payload)
        self.assertEqual(len(payload["results"]), 2)
        for item in payload["results"]:
            check_media_structure(self, item)

    def test_media_seasons_invalid_type_returns_bad_request(self):
        """Media seasons endpoint should reject non-tv media types."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "get",
            "api_media_seasons",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_media_seasons_invalid_media_id_returns_internal_server_error(
        self,
        _mock_metadata,
    ):
        """Media seasons endpoint should surface provider lookup failures."""
        response = self.call_api(
            "get",
            "api_media_seasons",
            args=(MediaTypes.TV.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    @patch("api.views.services.get_media_metadata")
    def test_media_sync_returns_accepted_and_updates_item(self, mock_metadata):
        """Sync endpoint should refresh metadata and return accepted."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        mock_metadata.return_value = {
            "title": "Movie 1 Synced",
            "image": "https://example.com/movie-1-synced.jpg",
        }

        response = self.call_api(
            "post",
            "api_media_sync",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn("Metadata synced successfully", payload["detail"])

        movie_item.refresh_from_db()
        self.assertEqual(movie_item.title, "Movie 1 Synced")
        self.assertEqual(movie_item.image, "https://example.com/movie-1-synced.jpg")

    @patch("api.views.services.get_media_metadata", side_effect=Exception("boom"))
    def test_media_sync_invalid_media_id_returns_internal_server_error(
        self, _mock_metadata
    ):
        """Sync endpoint should surface provider lookup failures."""
        response = self.call_api(
            "post",
            "api_media_sync",
            args=(MediaTypes.MOVIE.value, "tmdb", 999999),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 500)

    def test_media_sync_invalid_type_returns_bad_request(self):
        """Sync endpoint should reject unsupported media types."""
        response = self.call_api(
            "post",
            "api_media_sync",
            args=("invalid", "tmdb", 501),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)

    def test_media_sync_rejects_manual_source(self):
        """Sync endpoint should reject manual items."""
        response = self.call_api(
            "post",
            "api_media_sync",
            args=(MediaTypes.MOVIE.value, Sources.MANUAL.value, 701),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
