from django.urls import reverse
from django.utils import timezone

from app.models import (
    CollectionEntry,
    Item,
    Status,
    Video,
    VideoGameLink,
    VideoGameTag,
    VideoPlay,
)
from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase


class LibraryBulkVideoGameTests(FloppyApiTestCase):
    def test_game_search_shows_cached_watch_time_for_the_viewer_and_edition(self):
        url = reverse("api_library_bulk_video_game")
        game = Item.objects.create(media_id="known-game", source="igdb", media_type="game", title="Test Game")
        edition = Item.objects.create(
            media_id="known-edition", source="igdb", media_type="game", title="Test Game: Deluxe",
        )
        first = Item.objects.create(media_id="videobulk01", source="youtube", media_type="video", title="First video")
        second = Item.objects.create(media_id="videobulk02", source="youtube", media_type="video", title="Second video")
        VideoGameTag.objects.create(
            item=first, game_title=game.title, status=VideoGameTag.Status.FOUND, runtime_seconds=3600,
            checked_at=timezone.now(),
        )
        own = Video.objects.create(item=first, user=self.user1, status=Status.COMPLETED.value)
        VideoPlay.objects.create(video=own, external_id="first", progress=0, end_date=timezone.now())
        VideoPlay.objects.create(video=own, external_id="repeat", progress=600, end_date=timezone.now())
        manual = Video.objects.create(item=second, user=self.user1, progress=30)
        VideoGameLink.objects.create(video=manual, game_item=edition)
        Video.objects.create(item=first, user=self.user2, progress=120)

        def watch_labels(headers):
            response = self.client.get(url, {"q": "Test Game"}, **headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "private, no-store")
            return {option["id"]: option["watch_time_label"] for option in response.data}

        self.assertEqual(watch_labels(self.auth_headers), {game.pk: "1h 10m", edition.pk: "30s"})
        self.assertEqual(watch_labels(self.auth_headers2), {game.pk: "2m", edition.pk: "0m"})
        with self.captureOnCommitCallbacks(execute=True):
            assigned = self.client.post(url, {"item_ids": [first.pk], "game_id": edition.pk},
                                        format="json", **self.auth_headers)
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(watch_labels(self.auth_headers), {game.pk: "0m", edition.pk: "1h 10m"})
        self.assertEqual(watch_labels(self.auth_headers2), {game.pk: "2m", edition.pk: "0m"})

    def test_search_and_assign_only_the_callers_selected_videos(self):
        url = reverse("api_library_bulk_video_game")
        game = Item.objects.create(media_id="known-game", source="igdb", media_type="game", title="Test Game: Deluxe")
        manual = Item.objects.create(media_id="hidden", source="manual", media_type="game", title="Test Game: Private")
        first = Item.objects.create(media_id="videobulk01", source="youtube", media_type="video", title="First video")
        second = Item.objects.create(media_id="videobulk02", source="youtube", media_type="video", title="Second video")
        own = Video.objects.create(item=first, user=self.user1)
        other = Video.objects.create(item=first, user=self.user2)
        Video.objects.create(item=second, user=self.user2)
        VideoGameLink.objects.create(video=own)
        VideoGameLink.objects.create(video=other)

        options = self.client.get(url, {"q": "Test Game"}, **self.auth_headers)
        self.assertEqual(options.status_code, 200)
        self.assertEqual([option["id"] for option in options.data], [game.pk])

        rejected = self.client.post(url, {"item_ids": [first.pk, second.pk], "game_id": game.pk},
                                    format="json", **self.auth_headers)
        self.assertEqual(rejected.status_code, 400)
        self.assertIsNone(own.game_link.game_item_id)

        forbidden = self.client.post(url, {"item_ids": [first.pk], "game_id": manual.pk},
                                     format="json", **self.auth_headers)
        self.assertEqual(forbidden.status_code, 404)

        with self.captureOnCommitCallbacks(execute=True) as effects:
            assigned = self.client.post(url, {"item_ids": [first.pk, first.pk], "game_id": game.pk},
                                         format="json", **self.auth_headers)
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(assigned.data["updated"], 1)
        self.assertEqual(len(effects), 1)
        self.assertEqual(VideoGameLink.objects.get(video=own).game_item_id, game.pk)
        self.assertIsNone(VideoGameLink.objects.get(video=other).game_item_id)


class LibraryBulkAddTests(FloppyApiTestCase):
    """Bulk list membership enforces the same ownership and edit rules as web."""

    def test_add_items_is_idempotent_and_scoped_to_editable_lists(self):
        custom_list = CustomList.objects.create(name="Native list", owner=self.user1)
        item = self.items_by_type["movie"][0]
        endpoint = f"/api/v1/lists/{custom_list.id}/items/bulk/"

        response = self.client.post(
            endpoint,
            {"item_ids": [item.id]},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"added": 1, "skipped": 0})
        again = self.client.post(
            endpoint,
            {"item_ids": [item.id]},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(again.data, {"added": 0, "skipped": 1})
        self.assertEqual(CustomListItem.objects.filter(custom_list=custom_list).count(), 1)

    def test_bulk_add_rejects_smart_lists_and_non_editors(self):
        custom_list = CustomList.objects.create(name="Other user's list", owner=self.user2)
        endpoint = f"/api/v1/lists/{custom_list.id}/items/bulk/"
        denied = self.client.post(
            endpoint,
            {"item_ids": [self.items_by_type["movie"][0].id]},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(denied.status_code, 404)

        invalid = self.client.post(
            f"/api/v1/lists/{custom_list.id}/items/bulk/",
            {"item_ids": []},
            format="json",
            **self.auth_headers2,
        )
        self.assertEqual(invalid.status_code, 400)

    def test_bulk_collection_add_is_idempotent(self):
        item = self.items_by_type["movie"][0]
        endpoint = "/api/v1/library/bulk/collection/"
        first = self.client.post(endpoint, {"item_ids": [item.id]}, format="json", **self.auth_headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["created"], 1)
        second = self.client.post(endpoint, {"item_ids": [item.id]}, format="json", **self.auth_headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["already_present"], 1)
        self.assertEqual(CollectionEntry.objects.filter(user=self.user1, item=item).count(), 1)
