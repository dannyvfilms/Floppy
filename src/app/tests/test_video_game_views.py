"""Linking a video to a game by hand."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    Item,
    MediaTypes,
    Sources,
    Status,
    Video,
    VideoGameLink,
    VideoGameTag,
)

HOST = {"HTTP_HOST": "localhost"}


class VideoGameViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("viewer", password="x")
        self.other = get_user_model().objects.create_user("other", password="x")
        self.game = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Hades II",
        )
        self.video_item = Item.objects.create(
            media_id="abcdefghijk",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="Hades II first look",
        )
        Video.objects.create(
            item=self.video_item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=600,
            length_seconds=1200,
        )
        self.client.force_login(self.user)

    def _set(self, **data):
        return self.client.post(
            reverse("video_game_set", args=[self.video_item.pk]), data, **HOST
        )

    def test_link_a_game(self):
        response = self._set(mode="game", game_item_id=self.game.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hades II")
        self.assertContains(response, "Linked by you")
        link = VideoGameLink.objects.get()
        self.assertEqual((link.user, link.game_item), (self.user, self.game))

    def test_relinking_replaces_the_choice(self):
        other_game = Item.objects.create(
            media_id="2",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Hades",
        )
        self._set(mode="game", game_item_id=self.game.pk)
        self._set(mode="game", game_item_id=other_game.pk)
        self.assertEqual(VideoGameLink.objects.get().game_item, other_game)

    def test_not_a_game_and_back_to_the_tag(self):
        VideoGameTag.objects.create(
            item=self.video_item,
            status=VideoGameTag.Status.FOUND,
            game_title="Hades II",
            checked_at=timezone.now(),
        )
        response = self._set(mode="none")
        self.assertContains(response, "Not about a game")
        self.assertContains(response, "Use YouTube's tag")
        self.assertIsNone(VideoGameLink.objects.get().game_item)
        response = self._set(mode="auto")
        self.assertFalse(VideoGameLink.objects.exists())
        self.assertContains(response, "From YouTube's game tag")

    def test_only_games_can_be_linked(self):
        response = self._set(mode="game", game_item_id=self.video_item.pk)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(VideoGameLink.objects.exists())

    def test_unknown_mode_is_refused(self):
        self.assertEqual(self._set(mode="x").status_code, 400)

    def test_someone_elses_video_is_not_found(self):
        self.client.force_login(self.other)
        self.assertEqual(self._set(mode="none").status_code, 404)
        response = self.client.get(
            reverse("video_game_panel", args=[self.video_item.pk]), **HOST
        )
        self.assertEqual(response.status_code, 404)

    def test_sign_in_is_required(self):
        self.client.logout()
        response = self.client.post(
            reverse("video_game_set", args=[self.video_item.pk]),
            {"mode": "none"},
            **HOST,
        )
        self.assertEqual(response.status_code, 302)

    def test_search_finds_games_by_title(self):
        url = reverse("video_game_search", args=[self.video_item.pk])
        response = self.client.get(url, {"q": "hades"}, **HOST)
        self.assertContains(response, "Hades II")
        self.assertNotContains(self.client.get(url, {"q": "zelda"}, **HOST), "Hades II")
        # Too short to search: nothing listed, no error.
        self.assertNotContains(self.client.get(url, {"q": "h"}, **HOST), "Hades II")

    def test_search_never_returns_videos(self):
        url = reverse("video_game_search", args=[self.video_item.pk])
        self.assertNotContains(self.client.get(url, {"q": "first look"}, **HOST), "first look")

    def test_game_page_lists_linked_videos(self):
        from app.services import youtube_game_watch

        self._set(mode="game", game_item_id=self.game.pk)
        result = youtube_game_watch.watched_for_game(self.user, self.game)
        self.assertEqual(result["videos"], 1)
        self.assertEqual(result["items"][0]["label"], "20m")
