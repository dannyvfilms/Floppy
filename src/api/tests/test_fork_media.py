# FORK: tests for fork-only API surface (media-type overlay, progress,
# collection). Mirrors the fixture/request style of the upstream api tests.
from datetime import UTC, datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache

from app.models import (
    CollectionEntry,
    ComicIssue,
    Item,
    MediaTypes,
    Music,
    Sources,
    Status,
)

from .base import FloppyApiTestCase

BACKDROP_URL = "https://image.tmdb.org/t/p/w1280/backdrop.jpg"


class ForkMediaTypeOverlayTests(FloppyApiTestCase):
    """Fork media types are first-class citizens of the media endpoints."""

    def setUp(self):
        """Create fork-type items and tracked media on top of the base fixtures."""
        super().setUp()
        self.music_item, _ = Item.objects.get_or_create(
            media_id="mb-track-1",
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            defaults={"title": "Track 1", "image": "https://example.com/t1.jpg"},
        )
        self.music = Music.objects.create(
            user=self.user1,
            item=self.music_item,
            status=Status.COMPLETED.value,
            progress=3,
        )
        self.comicissue_item, _ = Item.objects.get_or_create(
            media_id="cv-issue-1",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            defaults={"title": "Issue 1", "image": "https://example.com/i1.jpg"},
        )
        self.comicissue = ComicIssue.objects.create(
            user=self.user1,
            item=self.comicissue_item,
            status=Status.IN_PROGRESS.value,
            progress=0,
        )

    def test_music_media_type_list(self):
        """GET /media/music returns tracked music."""
        response = self.client.get(
            "/api/v1/media/music",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        data = response.json()
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["results"][0]["item"]["media_id"], "mb-track-1")

    @patch("api.views.services.get_media_metadata")
    def test_comicissue_patch_and_get(self, mock_metadata):
        """PATCH and GET a tracked comicissue row."""
        mock_metadata.return_value = {
            "media_id": "cv-issue-1",
            "source": "comicvine",
            "source_url": "https://comicvine.gamespot.com/issue/cv-issue-1",
            "media_type": "comicissue",
            "title": "Issue 1",
            "max_progress": 1,
            "image": "https://example.com/i1.jpg",
            "synopsis": "",
            "genres": [],
            "score": None,
            "score_count": None,
            "details": {},
            "related": {"seasons": [], "recommendations": []},
        }
        url = "/api/v1/media/comicissue/comicvine/cv-issue-1"
        response = self.client.patch(
            url,
            {"progress": 1, "notes": "good"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.comicissue.refresh_from_db()
        self.assertEqual(self.comicissue.progress, 1)
        self.assertEqual(self.comicissue.notes, "good")

    def test_music_delete(self):
        """DELETE removes the tracked music row."""
        response = self.client.delete(
            "/api/v1/media/music/musicbrainz/mb-track-1",
            **self.auth_headers,
        )
        self.assertIn(response.status_code, (HTTP.OK, HTTP.NO_CONTENT))
        self.assertFalse(
            Music.objects.filter(user=self.user1, item=self.music_item).exists(),
        )

    def test_aggregated_media_list_includes_fork_types(self):
        """GET /media includes fork media types in aggregate results."""
        response = self.client.get(
            "/api/v1/media",
            {"limit": 200},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        types_seen = {
            result["item"]["media_type"] for result in response.json()["results"]
        }
        self.assertIn(MediaTypes.MUSIC.value, types_seen)
        self.assertIn(MediaTypes.COMIC_ISSUE.value, types_seen)


class ForkProgressEndpointTests(FloppyApiTestCase):
    """POST .../progress mirrors the web UI progress changer."""

    def setUp(self):
        """Track a comic issue for progress testing."""
        super().setUp()
        self.item, _ = Item.objects.get_or_create(
            media_id="cv-issue-p1",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            defaults={"title": "Progress Issue", "image": ""},
        )
        self.media = ComicIssue.objects.create(
            user=self.user1,
            item=self.item,
            status=Status.IN_PROGRESS.value,
            progress=1,
        )

    def test_progress_increase_and_decrease(self):
        """Progress moves by one in each direction."""
        url = "/api/v1/media/comicissue/comicvine/cv-issue-p1/progress"
        response = self.client.post(
            url,
            {"operation": "increase"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.media.refresh_from_db()
        self.assertEqual(self.media.progress, 2)

        response = self.client.post(
            url,
            {"operation": "decrease"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.media.refresh_from_db()
        self.assertEqual(self.media.progress, 1)

    def test_progress_invalid_operation(self):
        """Unknown operations are rejected."""
        response = self.client.post(
            "/api/v1/media/comicissue/comicvine/cv-issue-p1/progress",
            {"operation": "sideways"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_progress_unknown_media(self):
        """Progress on untracked media returns 404."""
        response = self.client.post(
            "/api/v1/media/comicissue/comicvine/does-not-exist/progress",
            {"operation": "increase"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_progress_requires_auth(self):
        """Progress endpoint rejects anonymous callers."""
        response = self.client.post(
            "/api/v1/media/comicissue/comicvine/cv-issue-p1/progress",
            {"operation": "increase"},
            format="json",
        )
        self.assertIn(response.status_code, (HTTP.UNAUTHORIZED, HTTP.FORBIDDEN))


class ForkCollectionEndpointTests(FloppyApiTestCase):
    """Collection CRUD wraps the owned-media flows."""

    def _movie_item(self):
        return self.items_by_type[MediaTypes.MOVIE.value][0]

    def test_collection_add_list_update_remove(self):
        """Full lifecycle of a collection entry."""
        item = self._movie_item()
        response = self.client.post(
            "/api/v1/collection",
            {"item_id": item.id, "media_type": "bluray", "resolution": "4k"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        entry_id = response.json()["id"]

        response = self.client.get(
            "/api/v1/collection",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        data = response.json()
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["results"][0]["resolution"], "4k")

        response = self.client.patch(
            f"/api/v1/collection/{entry_id}",
            {"media_type": "dvd", "resolution": "1080p"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["resolution"], "1080p")

        response = self.client.delete(
            f"/api/v1/collection/{entry_id}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(CollectionEntry.objects.filter(id=entry_id).exists())

    def test_collection_list_returns_pages_past_the_first(self):
        """An offset page lists the next entries instead of none."""
        item = self._movie_item()
        entries = [
            CollectionEntry.objects.create(
                user=self.user1,
                item=item,
                media_type="bluray",
            )
            for _ in range(3)
        ]
        response = self.client.get(
            "/api/v1/collection",
            {"limit": 2, "offset": 2},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        data = response.json()
        self.assertEqual(data["pagination"]["total"], 3)
        self.assertEqual([row["id"] for row in data["results"]], [entries[0].id])

    def test_collection_entry_scoped_to_user(self):
        """Another user's entry is invisible and immutable."""
        item = self._movie_item()
        entry = CollectionEntry.objects.create(
            user=self.user2,
            item=item,
            media_type="bluray",
        )
        response = self.client.get(
            f"/api/v1/collection/{entry.id}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        response = self.client.delete(
            f"/api/v1/collection/{entry.id}",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertTrue(CollectionEntry.objects.filter(id=entry.id).exists())

    def test_collection_update_keeps_fields_it_is_not_sent(self):
        """A PATCH changes only the fields in the request."""
        item = self._movie_item()
        entry = CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            media_type="bluray",
            is_3d=True,
            bitrate=320,
            purchase_price="9.99",
            purchase_location="Shop",
        )

        response = self.client.patch(
            f"/api/v1/collection/{entry.id}",
            {"resolution": "4k"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        entry.refresh_from_db()
        self.assertEqual(entry.resolution, "4k")
        self.assertEqual(entry.media_type, "bluray")
        self.assertTrue(entry.is_3d)
        self.assertEqual(entry.bitrate, 320)
        self.assertEqual(str(entry.purchase_price), "9.99")
        self.assertEqual(entry.purchase_location, "Shop")

        response = self.client.patch(
            f"/api/v1/collection/{entry.id}",
            {"is_3d": False, "bitrate": None},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        entry.refresh_from_db()
        self.assertFalse(entry.is_3d)
        self.assertIsNone(entry.bitrate)
        self.assertEqual(str(entry.purchase_price), "9.99")

    def test_collection_add_requires_item(self):
        """POST without item_id is a 400."""
        response = self.client.post(
            "/api/v1/collection",
            {"media_type": "bluray"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_collection_add_and_update_store_collected_at(self):
        """POST and PATCH keep the collected date they are sent."""
        item = self._movie_item()
        response = self.client.post(
            "/api/v1/collection",
            {
                "item_id": item.id,
                "media_type": "bluray",
                "collected_at": "2024-05-01T10:30:00+02:00",
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        entry = CollectionEntry.objects.get(id=response.json()["id"])
        self.assertEqual(entry.collected_at, datetime(2024, 5, 1, 8, 30, tzinfo=UTC))

        response = self.client.patch(
            f"/api/v1/collection/{entry.id}",
            {"collected_at": "2023-01-02T03:04:05Z"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        entry.refresh_from_db()
        self.assertEqual(entry.collected_at, datetime(2023, 1, 2, 3, 4, 5, tzinfo=UTC))

        response = self.client.patch(
            f"/api/v1/collection/{entry.id}",
            {"resolution": "4k"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        entry.refresh_from_db()
        self.assertEqual(entry.collected_at, datetime(2023, 1, 2, 3, 4, 5, tzinfo=UTC))


class ForkBackdropFieldTests(FloppyApiTestCase):
    """Detail responses carry 16:9 artwork alongside the portrait poster."""

    def setUp(self):
        """Start every test with a cold backdrop cache."""
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.tv_item = self.items_by_type[MediaTypes.TV.value][0]

    def _tv_metadata(self):
        return {
            "media_id": self.tv_item.media_id,
            "source": self.tv_item.source,
            "source_url": "https://www.themoviedb.org/tv/1",
            "media_type": MediaTypes.TV.value,
            "title": self.tv_item.title,
            "max_progress": 1,
            "image": self.tv_item.image,
            "synopsis": "",
            "genres": [],
            "score": None,
            "score_count": None,
            "details": {},
            "related": {"seasons": [], "recommendations": []},
        }

    def _get_detail(self):
        return self.call_api(
            "get",
            "api_media_detail",
            args=(MediaTypes.TV.value, self.tv_item.source, self.tv_item.media_id),
            headers=self.auth_headers,
        )

    @patch("api.views.services.get_media_metadata")
    @patch("app.backdrops.get_tmdb_backdrop")
    def test_detail_serves_cached_backdrop_without_calling_tmdb(
        self,
        mock_backdrop,
        mock_metadata,
    ):
        mock_metadata.return_value = self._tv_metadata()
        cache.set(f"tmdb_backdrop_tv_{self.tv_item.media_id}", BACKDROP_URL, 60)

        response = self._get_detail()

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["backdrop"], BACKDROP_URL)
        # The poster is unchanged — backdrop is an addition, not a replacement.
        self.assertEqual(payload["image"], self.tv_item.image)
        mock_backdrop.assert_not_called()

    @patch("app.tasks_backdrops.warm_backdrops_task.apply_async")
    @patch("api.views.services.get_media_metadata")
    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_detail_never_calls_the_provider_for_a_cold_backdrop(
        self,
        mock_backdrop,
        mock_metadata,
        mock_warm,
    ):
        """A cold backdrop is fetched in the background, not in the request."""
        mock_metadata.return_value = self._tv_metadata()

        response = self._get_detail()

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIsNone(response.json()["backdrop"])
        mock_backdrop.assert_not_called()
        mock_warm.assert_called_once()

    @patch("api.views.services.get_media_metadata")
    @patch("app.backdrops.get_tmdb_backdrop")
    def test_detail_serves_the_backdrop_once_the_warm_lands(
        self,
        mock_backdrop,
        mock_metadata,
    ):
        """The background fetch (inline under eager Celery) fills Redis."""
        media_id = self.tv_item.media_id

        def fill_cache(media_type, backdrop_media_id):
            cache.set(f"tmdb_backdrop_{media_type}_{backdrop_media_id}", BACKDROP_URL)
            return BACKDROP_URL

        mock_backdrop.side_effect = fill_cache
        mock_metadata.return_value = self._tv_metadata()

        self.assertIsNone(self._get_detail().json()["backdrop"])
        self.assertEqual(self._get_detail().json()["backdrop"], BACKDROP_URL)
        mock_backdrop.assert_called_once_with(MediaTypes.TV.value, media_id)

    @patch("app.tasks_backdrops.warm_backdrops_task.apply_async")
    @patch("api.views.services.get_media_metadata")
    def test_detail_reports_null_when_no_backdrop_exists(
        self,
        mock_metadata,
        mock_warm,
    ):
        """Clients need to distinguish "no artwork" from "a poster", so: null."""
        mock_metadata.return_value = self._tv_metadata()
        # The provider's cached "no backdrop" answer.
        cache.set(f"tmdb_backdrop_tv_{self.tv_item.media_id}", settings.IMG_NONE, 60)

        payload = self._get_detail().json()

        self.assertIn("backdrop", payload)
        self.assertIsNone(payload["backdrop"])
        # A known absence is not fetched again.
        mock_warm.assert_not_called()

    @patch("api.views.services.get_media_metadata")
    @patch("app.backdrops.get_tmdb_backdrop", return_value=BACKDROP_URL)
    def test_episode_detail_carries_the_show_backdrop(
        self,
        mock_backdrop,
        mock_metadata,
    ):
        """Episode stills are often missing; the show backdrop covers that gap."""
        cache.set(f"tmdb_backdrop_tv_{self.tv_item.media_id}", BACKDROP_URL, 60)
        season_item = self.items_by_type[MediaTypes.SEASON.value][0]
        episode_item = self.items_by_type[MediaTypes.EPISODE.value][0]
        mock_metadata.return_value = self.build_episode_metadata(
            tv_item=self.tv_item,
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
                self.tv_item.source,
                self.tv_item.media_id,
                season_item.season_number,
                episode_item.episode_number,
            ),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["backdrop"], BACKDROP_URL)
        # The fixture has no still_path, which is exactly the gap being filled.
        self.assertIsNone(payload["image"])
