"""Video play upsert."""

from django.urls import reverse

from app import history_cache
from app.models import Item, MediaTypes, Status, Video, VideoPlay

from .base import FloppyApiTestCase


class VideoPlayApiTests(FloppyApiTestCase):
    """A second post with the same external id updates the play."""

    def test_upsert_raises_progress_and_completes(self):
        """20% stays in progress. 85% completes the same play. No provider calls."""
        url = reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": "dQw4w9WgXcQ"},
        )
        payload = {
            "title": "Ranking EVERY Trader Joe's Pumpkin Product",
            "channel": "Beyond Babish",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "lengthSeconds": 1000,
            "progressSeconds": 200,
            "externalId": "youtube:dQw4w9WgXcQ:2026-10-02",
        }
        self._metadata_mock.reset_mock()
        first = self.client.post(url, payload, format="json", **self.auth_headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["status"], Status.IN_PROGRESS.value)

        payload["progressSeconds"] = 850
        second = self.client.post(url, payload, format="json", **self.auth_headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["status"], Status.COMPLETED.value)
        self.assertEqual(VideoPlay.objects.count(), 1)
        self._metadata_mock.assert_not_called()

        history = self.client.get(
            reverse("api_history"),
            {"media_type": MediaTypes.VIDEO.value, "flat": "1"},
            **self.auth_headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertIn(payload["title"], str(history.data))

    def _post(self, media_id="vid1", **overrides):
        """Post one play for a 1000 second video."""
        url = reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": media_id},
        )
        payload = {
            "title": "A Video",
            "lengthSeconds": 1000,
            "progressSeconds": 100,
            "externalId": "youtube:vid1:2026-10-02",
        }
        payload.update(overrides)
        return self.client.post(url, payload, format="json", **self.auth_headers)

    def test_a_completed_video_stays_completed_on_a_later_low_report(self):
        """A rewatch that starts at 10% must not undo the completion."""
        self._post(progressSeconds=900)
        response = self._post(
            progressSeconds=100,
            externalId="youtube:vid1:2026-10-03",
        )
        self.assertEqual(response.data["status"], Status.COMPLETED.value)
        video = Video.objects.get()
        # Completing fills the bar, as for every other media type.
        self.assertEqual(video.progress, 1000)
        self.assertEqual(VideoPlay.objects.count(), 2)

    def test_a_stale_report_does_not_lower_progress_or_dates(self):
        """Re-sending an older day with less progress changes nothing."""
        self._post(progressSeconds=600, externalId="youtube:vid1:2026-10-03")
        before = Video.objects.get()
        self._post(progressSeconds=50, externalId="youtube:vid1:2026-10-02")
        video = Video.objects.get()
        self.assertEqual(video.progress, 600)
        self.assertEqual(video.end_date, before.end_date)
        self._post(progressSeconds=50, externalId="youtube:vid1:2026-10-03")
        self.assertEqual(
            VideoPlay.objects.get(external_id__endswith="10-03").progress, 600
        )

    def test_a_later_post_does_not_rename_the_shared_item(self):
        """The item is shared between users, so only the first post names it."""
        self._post(title="First Title")
        self._post(title="Renamed Title")
        self.assertEqual(Item.objects.get(media_id="vid1").title, "First Title")

    def test_published_at_sets_the_upload_date_once(self):
        """The first reported upload date is kept, so the event never moves."""
        self._post(publishedAt="2026-09-01T10:00:00Z")
        self._post(publishedAt="2026-10-01T10:00:00Z")
        item = Item.objects.get(media_id="vid1", media_type=MediaTypes.VIDEO.value)
        self.assertEqual(item.release_datetime.date().isoformat(), "2026-09-01")

    def test_video_list_page_renders(self):
        """The Videos list shows what the play endpoint created."""
        self._post()
        self.client.force_login(self.user1)
        response = self.client.get("/medialist/video")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["media_list"].paginator.count, 1)

    def test_video_details_page_renders_from_the_stored_item(self):
        """History links here, so it must render without a provider."""
        self._post()
        self._metadata_patcher.stop()  # the base class mocks the metadata lookup
        self.client.force_login(self.user1)
        response = self.client.get("/details/youtube/video/vid1/a-video")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["media"]["title"], "A Video")

    def test_video_track_modal_renders(self):
        """The edit button on a History card opens this modal."""
        self._post()
        self.client.force_login(self.user1)
        response = self.client.get("/track_modal/youtube/video/vid1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Progress (Seconds)")

    def test_the_history_index_lists_the_day_of_a_video_play(self):
        """A day whose only activity is a video must be asked for."""
        self._post()
        play = VideoPlay.objects.get()
        for style in ("sessions", "repeats"):
            self.assertIn(
                history_cache.history_day_key(play.end_date),
                history_cache.build_history_index(self.user1, style),
            )

    def test_bad_seconds_are_clamped_not_a_server_error(self):
        """Negative or huge numbers must never reach the database."""
        response = self._post(lengthSeconds=-1, progressSeconds=-5)
        self.assertEqual(response.status_code, 201)
        response = self._post(lengthSeconds=10**12, progressSeconds=10**12)
        self.assertEqual(response.status_code, 200)
        video = Video.objects.get()
        self.assertEqual(video.length_seconds, 2_147_483_647)

    def test_a_repeated_post_does_not_create_a_second_play(self):
        """A retry of the same report is the same play."""
        for _ in range(3):
            self._post()
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_the_generic_create_route_points_to_the_plays_route(self):
        """A new video cannot be created through the provider-backed route."""
        response = self.client.post(
            "/api/v1/media/video/",
            {"media_id": "x", "source": "youtube", "status": "Planning"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("plays", response.data["detail"])

    def test_an_approved_thumbnail_is_stored_as_the_item_image(self):
        """i.ytimg.com and img.youtube.com are the YouTube artwork hosts."""
        thumb = "https://i.ytimg.com/vi/vid1/mqdefault.jpg"
        self._post(thumbnailUrl=thumb)
        self.assertEqual(Item.objects.get(media_id="vid1").image, thumb)

        other = "https://img.youtube.com/vi/vid2/hqdefault.jpg"
        self._post(
            media_id="vid2", externalId="youtube:vid2:2026-10-02", thumbnail_url=other
        )
        self.assertEqual(Item.objects.get(media_id="vid2").image, other)

    def test_an_unapproved_thumbnail_is_ignored(self):
        """A caller-supplied host is not stored and does not fail the play."""
        response = self._post(thumbnailUrl="https://evil.example/poster.jpg")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Item.objects.get(media_id="vid1").image, "")

    def test_a_later_thumbnail_does_not_replace_the_stored_image(self):
        """The first approved poster stays. The item is shared across users."""
        first = "https://i.ytimg.com/vi/vid1/mqdefault.jpg"
        self._post(thumbnailUrl=first)
        self._post(
            thumbnailUrl="https://i.ytimg.com/vi/vid1/hqdefault.jpg",
            externalId="youtube:vid1:2026-10-03",
        )
        self.assertEqual(Item.objects.get(media_id="vid1").image, first)
