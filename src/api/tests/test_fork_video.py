"""Video play upsert."""

import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.urls import reverse
from django.utils import timezone

from app import history_cache
from app.history_cache_day_builder import build_history_day
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

    def test_a_thumbnail_over_plain_http_is_ignored(self):
        """An http poster would be blocked as mixed content on an https install."""
        response = self._post(thumbnailUrl="http://i.ytimg.com/vi/vid1/mqdefault.jpg")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Item.objects.get(media_id="vid1").image, "")

    def test_the_first_description_is_kept(self):
        """The item is shared, so a later report never rewrites the description."""
        self._post(description="  What this video is about.  ")
        self._post(
            description="A different text.", externalId="youtube:vid1:2026-10-03"
        )
        self.assertEqual(
            Item.objects.get(media_id="vid1").synopsis,
            "What this video is about.",
        )

    def test_video_details_render_backdrop_and_channel_avatar_fragment(self):
        self._post(
            media_id="vidAAAAAAAA",
            channel="Example Channel",
            thumbnailUrl="https://i.ytimg.com/vi/vidAAAAAAAA/hqdefault.jpg",
        )
        self._metadata_patcher.stop()
        self.client.force_login(self.user1)
        url = reverse(
            "media_details",
            kwargs={
                "source": "youtube",
                "media_type": MediaTypes.VIDEO.value,
                "media_id": "vidAAAAAAAA",
                "title": "a-video",
            },
        )
        response = self.client.get(url)
        self.assertContains(response, "detail-carousel-content")
        self.assertContains(response, "detail-carousel-overview-caption")
        self.assertContains(response, "detail-carousel-overview-extension")
        self.assertContains(response, "video-channel-avatar")
        self.assertContains(response, "md:justify-start")
        self.assertContains(response, 'class="detail-carousel-grid__title min-w-0"')
        html = response.content.decode()
        self.assertLess(
            html.index('class="detail-carousel-grid__synopsis"'),
            html.index('<h1 class="text-2xl'),
        )
        self.assertContains(response, "maxresdefault.jpg")
        self.assertContains(response, "hqdefault.jpg")
        self.assertContains(response, "data-image-fallback-on-small")
        self.assertContains(response, "selected = 1; videoPlaying = true")
        self.assertContains(response, "detail-carousel-preview--bounded")
        self.assertNotContains(response, "detail-carousel-overview-player")
        with patch(
            "app.youtube_channel_art.video_details",
            return_value={
                "avatar": "https://yt3.ggpht.com/avatar",
                "description": "Example description <script>alert(1)</script>",
            },
        ):
            response = self.client.get(url, {"fragment": "video-metadata"})
        self.assertContains(response, "yt3.ggpht.com/avatar")
        self.assertContains(response, "Example description")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertEqual(Item.objects.get(media_id="vidAAAAAAAA").synopsis, "")

    def test_fetched_description_does_not_replace_stored_description(self):
        self._post(media_id="vidAAAAAAAA", description="Description from client")
        self._metadata_patcher.stop()
        self.client.force_login(self.user1)
        url = reverse(
            "media_details",
            kwargs={
                "source": "youtube",
                "media_type": "video",
                "media_id": "vidAAAAAAAA",
                "title": "a-video",
            },
        )
        with patch(
            "app.youtube_channel_art.video_details",
            return_value={"avatar": "", "description": "Fetched description"},
        ):
            response = self.client.get(url, {"fragment": "video-metadata"})
        self.assertNotContains(response, "Fetched description")
        self.assertEqual(
            Item.objects.get(media_id="vidAAAAAAAA").synopsis, "Description from client"
        )

    def test_video_player_does_not_require_stored_thumbnail(self):
        self._post(media_id="vidAAAAAAAA", channel="Example Channel")
        self._metadata_patcher.stop()
        self.client.force_login(self.user1)
        url = reverse(
            "media_details",
            kwargs={
                "source": "youtube",
                "media_type": "video",
                "media_id": "vidAAAAAAAA",
                "title": "a-video",
            },
        )
        response = self.client.get(url)
        self.assertContains(response, "selected = 1; videoPlaying = true")
        self.assertContains(response, "vidAAAAAAAA")
        self.assertContains(response, "maxresdefault.jpg")

    def test_youtube_player_wrapper_sends_only_the_origin(self):
        url = reverse("youtube_player")
        response = self.client.get(url, {"v": "vidAAAAAAAA"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Referrer-Policy"], "strict-origin-when-cross-origin"
        )
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertContains(response, 'src="https://www.youtube.com/embed/vidAAAAAAAA"')
        self.assertNotContains(response, "autoplay=1")
        response = self.client.get(url, {"v": "vidAAAAAAAA", "autoplay": "1"})
        self.assertContains(response, "/embed/vidAAAAAAAA?autoplay=1")
        response = self.client.get(url, {"v": "<invalid>"})
        self.assertEqual(response.status_code, 400)

    def test_the_details_page_shows_what_the_client_reported(self):
        """Channel and length in the sidebar, description and YouTube link on the page."""
        self._post(
            channel="Beyond Babish",
            lengthSeconds=3900,
            description="Ranking every pumpkin product.",
            publishedAt="2026-09-20T10:00:00Z",
        )
        # The base class stubs metadata for the API; this page needs the real one.
        self._metadata_patcher.stop()
        self.client.force_login(self.user1)
        url = reverse(
            "media_details",
            kwargs={
                "source": "youtube",
                "media_type": MediaTypes.VIDEO.value,
                "media_id": "vid1",
                "title": "a-video",
            },
        )
        # The sidebar and links load in a second request.
        response = self.client.get(url, {"fragment": "secondary"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Beyond Babish")
        self.assertContains(response, "1h 5m")
        self.assertNotContains(response, "No details available")
        page = self.client.get(url)
        self.assertContains(page, "Ranking every pumpkin product.")
        self.assertContains(page, "https://www.youtube.com/watch?v=vid1")

    def test_a_thumbnail_for_another_video_is_ignored(self):
        """A poster is only kept when its URL names the video being posted."""
        response = self._post(thumbnailUrl="https://i.ytimg.com/vi/other/mqdefault.jpg")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Item.objects.get(media_id="vid1").image, "")
        self._post(thumbnailUrl="https://i.ytimg.com/an/vid1/avatar.jpg")
        self.assertEqual(Item.objects.get(media_id="vid1").image, "")

    def test_a_new_poster_refreshes_history_for_other_viewers(self):
        """The poster is on the shared item, so every viewer's cached days go stale."""
        item = Item.objects.create(
            media_id="vid1",
            source="youtube",
            media_type=MediaTypes.VIDEO.value,
            library_media_type=MediaTypes.VIDEO.value,
            title="A Video",
        )
        other = Video.objects.create(item=item, user=self.user2)
        other.upsert_play("youtube:vid1:2026-09-01", 900, end_date=timezone.now())
        with patch(
            "api.fork_views_video.history_cache.invalidate_history_days",
        ) as invalidate:
            self._post(thumbnailUrl="https://i.ytimg.com/vi/vid1/mqdefault.jpg")
        poster_calls = [
            call
            for call in invalidate.call_args_list
            if call.kwargs.get("reason") == "video_poster_change"
        ]
        self.assertEqual([call.args[0] for call in poster_calls], [self.user2.id])

    def test_plays_on_the_same_day_list_the_latest_post_first(self):
        """YouTube only gives a day, so the plays tie and the later post wins."""
        for media_id in ("vidA", "vidB", "vidC"):
            self._post(
                media_id=media_id,
                title=media_id,
                externalId=f"youtube:{media_id}:2026-10-02",
            )
        day = history_cache.history_day_key(VideoPlay.objects.first().end_date)
        history_day = build_history_day(self.user1, day)
        titles = [entry["title"] for entry in history_day["entries"]]
        self.assertEqual(titles, ["vidC", "vidB", "vidA"])

    def test_searching_videos_returns_an_empty_page(self):
        """Videos come from clients, so the search API has no provider to ask."""
        response = self.client.get(
            reverse("api_search_provider", kwargs={"media_type": "video"}),
            {"q": "anything"},
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])


class VideoGameTagTriggerTests(FloppyApiTestCase):
    """A first post queues one game-tag lookup, later posts do not."""

    def test_first_post_queues_one_lookup(self):
        url = reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": "HQp_b8VHtgI"},
        )
        payload = {
            "title": "A Minecraft video",
            "lengthSeconds": 1000,
            "progressSeconds": 100,
            "externalId": "youtube:HQp_b8VHtgI:2026-10-02",
        }
        with (
            patch("api.fork_views_video.lookup_youtube_game_tag.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.client.post(url, payload, format="json", **self.auth_headers)
        delay.assert_called_once_with(Item.objects.get(media_id="HQp_b8VHtgI").pk)


class VideoPlayManageApiTests(FloppyApiTestCase):
    """List and delete the plays of a video."""

    def _post(self, day, media_id="vid1"):
        """Post one play on the given day."""
        url = reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": media_id},
        )
        return self.client.post(
            url,
            {
                "title": "A Video",
                "lengthSeconds": 1000,
                "progressSeconds": 100,
                "externalId": f"youtube:{media_id}:{day}",
            },
            format="json",
            **self.auth_headers,
        )

    def _plays_url(self, media_id="vid1"):
        return reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": media_id},
        )

    def _delete(self, external_id, media_id="vid1"):
        return self.client.delete(
            reverse(
                "api_video_play_detail",
                kwargs={
                    "source": "youtube",
                    "media_id": media_id,
                    "external_id": external_id,
                },
            ),
            **self.auth_headers,
        )

    def test_plays_are_listed_newest_first(self):
        """The list carries the external id, progress and date of each play."""
        self._post("2026-10-02")
        self._post("2026-10-04")
        response = self.client.get(self._plays_url(), **self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            [play["external_id"] for play in response.data["results"]],
            ["youtube:vid1:2026-10-04", "youtube:vid1:2026-10-02"],
        )
        self.assertEqual(response.data["results"][0]["progress_seconds"], 100)

    def test_listing_an_unknown_video_is_not_found(self):
        """No video, no list."""
        response = self.client.get(self._plays_url("nope"), **self.auth_headers)
        self.assertEqual(response.status_code, 404)

    def test_deleting_a_play_moves_the_last_watched_date_back(self):
        """The video keeps its status and its other plays."""
        self._post("2026-10-02")
        self._post("2026-10-04")
        response = self._delete("youtube:vid1:2026-10-04")
        self.assertEqual(response.status_code, 204)
        video = Video.objects.get()
        self.assertEqual(VideoPlay.objects.count(), 1)
        self.assertEqual(video.end_date.date().isoformat(), "2026-10-02")
        self.assertEqual(video.status, Status.IN_PROGRESS.value)

    def test_deleting_the_last_play_keeps_the_video(self):
        """The video stays tracked, with no watched date."""
        self._post("2026-10-02")
        self.assertEqual(self._delete("youtube:vid1:2026-10-02").status_code, 204)
        video = Video.objects.get()
        self.assertIsNone(video.end_date)
        self.assertEqual(VideoPlay.objects.count(), 0)

    def test_deleting_removes_the_day_from_history(self):
        """History no longer shows the deleted play."""
        self._post("2026-10-02")
        day = history_cache.history_day_key(VideoPlay.objects.get().end_date)
        self._delete("youtube:vid1:2026-10-02")
        self.assertIsNone(build_history_day(self.user1, day))

    def test_a_play_with_slashes_in_its_external_id_can_be_deleted(self):
        """Any id the create endpoint accepts can be addressed to delete it."""
        external_id = "client/app:vid1:2026-10-02"
        response = self.client.post(
            self._plays_url(),
            {
                "title": "A Video",
                "lengthSeconds": 1000,
                "progressSeconds": 100,
                "externalId": external_id,
            },
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self._delete(external_id).status_code, 204)
        self.assertEqual(VideoPlay.objects.count(), 0)

    def test_deleting_an_unknown_play_or_video_is_not_found(self):
        """Neither is an error beyond 404."""
        self._post("2026-10-02")
        self.assertEqual(self._delete("youtube:vid1:2020-01-01").status_code, 404)
        self.assertEqual(
            self._delete("youtube:nope:2026-10-02", media_id="nope").status_code,
            404,
        )
        self.assertEqual(VideoPlay.objects.count(), 1)

    def test_another_users_play_cannot_be_deleted(self):
        """Plays belong to the caller's own video."""
        item = Item.objects.create(
            media_id="vid1",
            source="youtube",
            media_type=MediaTypes.VIDEO.value,
            library_media_type=MediaTypes.VIDEO.value,
            title="A Video",
        )
        other = Video.objects.create(item=item, user=self.user2)
        other.upsert_play("youtube:vid1:2026-10-02", 100, end_date=timezone.now())
        self.assertEqual(self._delete("youtube:vid1:2026-10-02").status_code, 404)
        self.assertEqual(VideoPlay.objects.count(), 1)
        self.assertEqual(
            self.client.get(self._plays_url(), **self.auth_headers).status_code,
            404,
        )


class VideoChannelTests(FloppyApiTestCase):
    """A video's channel is its author: filter, sort, lists and saved views."""

    def _post(self, media_id, channel, title=None):
        url = reverse(
            "api_video_play",
            kwargs={"source": "youtube", "media_id": media_id},
        )
        return self.client.post(
            url,
            {
                "title": title or f"Video {media_id}",
                "channel": channel,
                "lengthSeconds": 1000,
                "progressSeconds": 900,
                "externalId": f"youtube:{media_id}:2026-10-02",
            },
            format="json",
            **self.auth_headers,
        )

    def setUp(self):
        """Two channels, signed in for the web pages."""
        super().setUp()
        self._post("vidA", "Beyond Babish")
        self._post("vidB", "Beyond Babish")
        self._post("vidC", "Home Gadgets")
        self.client.force_login(self.user1)

    def test_the_first_channel_becomes_the_author_once(self):
        """The item is shared, so a later post never renames the channel."""
        self._post("vidA", "Someone Else")
        self.assertEqual(Item.objects.get(media_id="vidA").authors, ["Beyond Babish"])

    def test_the_list_filters_by_channel(self):
        """Choosing a channel narrows the Videos list."""
        response = self.client.get("/medialist/video", {"author": "Beyond Babish"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["media_list"].paginator.count, 2)
        response = self.client.get("/medialist/video", {"author": "Home Gadgets"})
        self.assertEqual(response.context["media_list"].paginator.count, 1)

    def test_the_filter_menu_offers_channels_not_formats(self):
        """Channels are listed and named as such. Formats stay a reading filter."""
        response = self.client.get("/medialist/video")
        filter_data = response.context["filter_data"]
        self.assertTrue(filter_data["show_authors"])
        self.assertTrue(filter_data["author_is_channel"])
        self.assertFalse(filter_data["show_formats"])
        self.assertEqual(
            [author["value"] for author in filter_data["authors"]],
            ["Beyond Babish", "Home Gadgets"],
        )
        self.assertContains(response, "All Channels")

    def test_the_sort_menu_calls_it_channel_and_sorts_by_it(self):
        """The author sort reads Channel on videos and orders by channel."""
        response = self.client.get(
            "/medialist/video", {"sort": "author", "direction": "desc"}
        )
        self.assertIn(("author", "Channel"), response.context["sort_choices"])
        titles = [
            entry.item.title for entry in response.context["media_list"].object_list
        ]
        self.assertEqual(titles[0], "Video vidC")

    def test_the_table_has_a_channel_column(self):
        """The table layout shows each video's channel."""
        response = self.client.get("/medialist/video", {"layout": "table"})
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.content.decode(), r"<th[^>]*>\s*Channel")
        self.assertRegex(
            response.content.decode(), r"<td[^>]*>\s*<span[^>]*>\s*Beyond Babish"
        )

    def test_other_media_types_keep_the_author_wording(self):
        """Books still say Author and still offer Format."""
        response = self.client.get("/medialist/book")
        filter_data = response.context["filter_data"]
        self.assertFalse(filter_data["author_is_channel"])
        self.assertTrue(filter_data["show_formats"])
        self.assertIn(("author", "Author"), response.context["sort_choices"])

    def test_a_saved_view_keeps_the_channel(self):
        """The saved query carries the author parameter."""
        response = self.client.post(
            reverse("saved_view_create"),
            {"media_type": "video", "name": "Babish", "author": "Beyond Babish"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("author=Beyond+Babish", response.json()["url"])

    def test_a_smart_list_can_match_a_channel(self):
        """A smart list of videos from one channel."""
        from lists.models import CustomList

        smart = CustomList.objects.create(
            name="Babish", owner=self.user1, is_smart=True
        )
        response = self.client.post(
            reverse("list_smart_rules_update", args=[smart.id]),
            json.dumps({"media_types": ["video"], "author": "Beyond Babish"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(smart.items.values_list("media_id", flat=True)),
            ["vidA", "vidB"],
        )
        page = self.client.get(f"/list/{smart.id}")
        self.assertContains(page, "Channel:")
        self.assertContains(page, "Beyond Babish")

    def test_the_migration_copies_existing_channels(self):
        """Videos stored before this change get their channel as author."""
        import importlib

        migration = importlib.import_module(
            "app.migrations.0214_video_channel_as_author"
        )
        item = Item.objects.get(media_id="vidA")
        item.authors = []
        item.save(update_fields=["authors"])
        migration.copy_channel_to_authors(django_apps, None)
        item.refresh_from_db()
        self.assertEqual(item.authors, ["Beyond Babish"])
