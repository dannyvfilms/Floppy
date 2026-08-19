# FORK: tests for fork-only API surface (media-type overlay, progress,
# collection). Mirrors the fixture/request style of the upstream api tests.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

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

    def test_collection_add_requires_item(self):
        """POST without item_id is a 400."""
        response = self.client.post(
            "/api/v1/collection",
            {"media_type": "bluray"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
