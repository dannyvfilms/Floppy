import importlib
import json

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import (
    TV,
    Album,
    Artist,
    CollectionEntry,
    Game,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Music,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
    Tag,
    Track,
)


class TagsModalViewTest(TestCase):
    """Test the tags_modal view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
        )
        self.tag1 = Tag.objects.create(user=self.user, name="Favorite")
        self.tag2 = Tag.objects.create(user=self.user, name="Must Watch")

    def test_tags_modal_shows_user_tags(self):
        """Modal renders all user tags."""
        url = reverse(
            "tags_modal",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "278",
            },
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Favorite")
        self.assertContains(response, "Must Watch")
        self.assertContains(response, reverse("tag_delete"))

    def test_tags_modal_shows_applied_status(self):
        """Modal shows correct has_tag status."""
        ItemTag.objects.create(tag=self.tag1, item=self.item)
        url = reverse(
            "tags_modal",
            kwargs={
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "media_id": "278",
            },
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # tag1 is applied, so its button should show "Remove"
        self.assertContains(response, "Remove")


class TagItemToggleViewTest(TestCase):
    """Test the tag_item_toggle view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
            genres=["Drama"],
        )
        self.tag = Tag.objects.create(user=self.user, name="Favorite")

    def test_add_tag_to_item(self):
        """Toggle adds tag when not present."""
        url = reverse("tag_item_toggle")
        response = self.client.post(
            url, {"tag_id": self.tag.id, "item_id": self.item.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ItemTag.objects.filter(tag=self.tag, item=self.item).exists())

    def test_tag_a_video_and_list_it_on_the_tag_page(self):
        """A video takes tags like any other media type."""
        video_item = Item.objects.create(
            media_id="vid1",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="A Tagged Video",
            image="http://example.com/video.jpg",
        )
        response = self.client.post(
            reverse("tag_item_toggle"),
            {"tag_id": self.tag.id, "item_id": video_item.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ItemTag.objects.filter(tag=self.tag, item=video_item).exists())

        response = self.client.get(reverse("tag_index"))
        self.assertEqual(response.status_code, 200)

    def test_toggle_returns_oob_preview_refresh(self):
        """Toggle response refreshes the detail-tag preview via OOB swap."""
        url = reverse("tag_item_toggle")
        response = self.client.post(
            url,
            {
                "tag_id": self.tag.id,
                "item_id": self.item.id,
                "preview_genres_json": json.dumps(["Drama"]),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="tag-preview-movie-278"')
        self.assertContains(response, 'data-has-preview="true"')
        self.assertContains(response, "Genres")
        self.assertContains(response, "Drama")
        self.assertContains(response, "Tags")
        self.assertContains(response, "Favorite")

    def test_toggle_preserves_implied_genres_in_preview(self):
        """Toggle response should keep implied genres in the hover preview."""
        url = reverse("tag_item_toggle")
        response = self.client.post(
            url,
            {
                "tag_id": self.tag.id,
                "item_id": self.item.id,
                "preview_genres_json": json.dumps(["Drama"]),
                "preview_implied_genres_json": json.dumps(["Crime"]),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Implied Genres")
        self.assertContains(response, "Crime")

    def test_remove_tag_from_item(self):
        """Toggle removes tag when already present."""
        ItemTag.objects.create(tag=self.tag, item=self.item)
        url = reverse("tag_item_toggle")
        response = self.client.post(
            url, {"tag_id": self.tag.id, "item_id": self.item.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ItemTag.objects.filter(tag=self.tag, item=self.item).exists())

    def test_cannot_toggle_other_user_tag(self):
        """Cannot toggle a tag owned by another user."""
        other_user = get_user_model().objects.create_user(
            username="other", password="12345"
        )
        other_tag = Tag.objects.create(user=other_user, name="Other Tag")
        url = reverse("tag_item_toggle")
        response = self.client.post(
            url, {"tag_id": other_tag.id, "item_id": self.item.id}
        )
        self.assertEqual(response.status_code, 404)


class TagCreateViewTest(TestCase):
    """Test the tag_create view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
            genres=["Drama"],
        )

    def test_create_tag(self):
        """Creates a new tag for the user."""
        url = reverse("tag_create")
        response = self.client.post(url, {"name": "New Tag", "item_id": self.item.id})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Tag.objects.filter(user=self.user, name="New Tag").exists())

    def test_create_from_track_tab_returns_the_tab_editor(self):
        """A create made inside the edit modal keeps the tab shell, not the popup one."""
        url = reverse("tag_create")
        response = self.client.post(
            url,
            {
                "name": "New Tag",
                "item_id": self.item.id,
                "tag_surface": "track",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="tag_surface"')
        self.assertContains(response, 'value="track"')
        self.assertNotContains(response, "tagsOpen = false")
        self.assertContains(response, "New Tag")

    def test_create_returns_oob_preview_refresh(self):
        """Create response refreshes the detail-tag preview via OOB swap."""
        url = reverse("tag_create")
        response = self.client.post(
            url,
            {
                "name": "New Tag",
                "item_id": self.item.id,
                "preview_genres_json": json.dumps(["Drama"]),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="tag-preview-movie-278"')
        self.assertContains(response, "Genres")
        self.assertContains(response, "Drama")
        self.assertContains(response, "Tags")
        self.assertContains(response, "New Tag")

    def test_create_tag_busts_cached_medialist_filter_data(self):
        """Creating a tag invalidates the cached filter_data so it appears immediately."""
        list_url = reverse("medialist", args=[MediaTypes.MOVIE.value])
        first_response = self.client.get(list_url)
        self.assertNotIn("Cozy", first_response.context["filter_data"]["tags"])

        self.client.post(reverse("tag_create"), {"name": "Cozy"})

        second_response = self.client.get(list_url)
        self.assertIn("Cozy", second_response.context["filter_data"]["tags"])

    def test_create_tag_auto_applies(self):
        """Tag is auto-applied to item when item_id provided."""
        url = reverse("tag_create")
        self.client.post(url, {"name": "New Tag", "item_id": self.item.id})
        tag = Tag.objects.get(user=self.user, name="New Tag")
        self.assertTrue(ItemTag.objects.filter(tag=tag, item=self.item).exists())

    def test_reject_duplicate_case_insensitive(self):
        """Rejects creating a tag with the same name (case-insensitive)."""
        Tag.objects.create(user=self.user, name="Favorite")
        url = reverse("tag_create")
        self.client.post(url, {"name": "favorite", "item_id": self.item.id})
        self.assertEqual(Tag.objects.filter(user=self.user).count(), 1)

    def test_reject_empty_name(self):
        """Rejects creating a tag with empty name."""
        url = reverse("tag_create")
        response = self.client.post(url, {"name": "", "item_id": self.item.id})
        self.assertEqual(response.status_code, 400)


class TagDeleteViewTest(TestCase):
    """Test the tag_delete view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
            genres=["Drama"],
        )
        self.tag = Tag.objects.create(user=self.user, name="Favorite")
        self.other_tag = Tag.objects.create(user=self.user, name="Must Watch")
        ItemTag.objects.create(tag=self.tag, item=self.item)

    def test_delete_tag_removes_it_from_library(self):
        """Deleting a tag removes the tag object and its item links."""
        url = reverse("tag_delete")
        response = self.client.post(
            url,
            {"tag_id": self.tag.id, "item_id": self.item.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tag.objects.filter(id=self.tag.id).exists())
        self.assertFalse(ItemTag.objects.filter(tag_id=self.tag.id).exists())

    def test_delete_returns_modal_and_oob_preview_refresh(self):
        """Delete response refreshes both the modal and the detail-tag preview."""
        url = reverse("tag_delete")
        response = self.client.post(
            url,
            {
                "tag_id": self.tag.id,
                "item_id": self.item.id,
                "preview_genres_json": json.dumps(["Drama"]),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.other_tag.name)
        self.assertNotContains(response, "Favorite</span>")
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, 'id="tag-preview-movie-278"')
        self.assertContains(response, "Click to add tags")
        self.assertContains(response, "Tags")
        self.assertContains(response, "Genres")
        self.assertContains(response, "Drama")

    def test_cannot_delete_other_user_tag(self):
        """Cannot delete a tag owned by another user."""
        other_user = get_user_model().objects.create_user(
            username="other", password="12345"
        )
        foreign_tag = Tag.objects.create(user=other_user, name="Other Tag")
        url = reverse("tag_delete")
        response = self.client.post(
            url,
            {"tag_id": foreign_tag.id, "item_id": self.item.id},
        )
        self.assertEqual(response.status_code, 404)


class TagFilterViewTest(TestCase):
    """Test tag filtering in the media_list view."""

    def setUp(self):
        cache.clear()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item1 = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Tagged Movie",
            image="http://example.com/image.jpg",
        )
        self.item2 = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Untagged Movie",
            image="http://example.com/image.jpg",
        )
        Movie.objects.create(
            item=self.item1,
            user=self.user,
            status=Status.COMPLETED,
        )
        Movie.objects.create(
            item=self.item2,
            user=self.user,
            status=Status.COMPLETED,
        )

        self.tag = Tag.objects.create(user=self.user, name="Favorite")
        ItemTag.objects.create(tag=self.tag, item=self.item1)

    def test_include_tag_filter(self):
        """Tag filter shows only items with the tag."""
        url = reverse("medialist", args=["movie"])
        response = self.client.get(url, {"tag": "Favorite"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tagged Movie")
        self.assertNotContains(response, "Untagged Movie")

    def test_tag_filter_logs_shown_count(self):
        with self.assertLogs("app.media_list_views", level="INFO") as logs:
            self.client.get(reverse("medialist", args=["movie"]), {"tag": "Favorite"})

        self.assertIn("shown=1", "\n".join(logs.output))

    def test_empty_tag_filter_logs_why(self):
        """An empty tagged list logs the status filter and tracked/untracked split."""
        untracked = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Untracked Movie",
            image="http://example.com/image.jpg",
        )
        ItemTag.objects.create(tag=self.tag, item=untracked)
        ItemTag.objects.filter(item=self.item1).delete()
        self.user.update_preference("movie_status", Status.PLANNING.value)

        with self.assertLogs("app.media_list_views", level="WARNING") as logs:
            self.client.get(reverse("medialist", args=["movie"]), {"tag": "Favorite"})

        output = "\n".join(logs.output)
        self.assertIn("shown=0", output)
        self.assertIn("from saved", output)
        self.assertIn("tagged_items=1", output)
        self.assertIn("untracked=1", output)

    def test_empty_tag_filter_log_matches_tag_case_insensitively(self):
        self.user.update_preference("movie_status", Status.PLANNING.value)

        with self.assertLogs("app.media_list_views", level="WARNING") as logs:
            self.client.get(reverse("medialist", args=["movie"]), {"tag": "favorite"})

        self.assertIn("tagged_items=1", "\n".join(logs.output))

    def test_empty_tag_filter_log_counts_items_not_tracker_rows(self):
        """Several tracker rows on one item must not make untracked negative."""
        Movie.objects.create(
            item=self.item1,
            user=self.user,
            status=Status.DROPPED,
        )
        self.user.update_preference("movie_status", Status.PLANNING.value)

        with self.assertLogs("app.media_list_views", level="WARNING") as logs:
            self.client.get(reverse("medialist", args=["movie"]), {"tag": "Favorite"})

        self.assertIn("untracked=0", "\n".join(logs.output))

    def test_exclude_tag_filter(self):
        """Tag exclude filter hides items with the tag."""
        url = reverse("medialist", args=["movie"])
        response = self.client.get(url, {"tag_exclude": "Favorite"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Tagged Movie")
        self.assertContains(response, "Untagged Movie")

    def test_tag_counts_stay_global_when_filter_applied(self):
        """Tag dropdown counts show totals, not the filtered subset (#1072)."""
        home = Tag.objects.create(user=self.user, name="Watched at Home")
        ItemTag.objects.create(tag=home, item=self.item2)

        url = reverse("medialist", args=["movie"])
        response = self.client.get(url, {"tag": "Favorite"})

        tag_counts = response.context["filter_data"]["tag_counts"]
        self.assertEqual(tag_counts["Favorite"], 1)
        self.assertEqual(tag_counts["Watched at Home"], 1)

    def test_multiple_tag_filter_modes(self):
        """Multiple tags support AND, OR, and NOT semantics."""
        comedy = Tag.objects.create(user=self.user, name="Comedy")
        untagged_item = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Still Untagged Movie",
        )
        Movie.objects.create(
            item=untagged_item, user=self.user, status=Status.COMPLETED
        )
        ItemTag.objects.create(tag=comedy, item=self.item2)

        url = reverse("medialist", args=["movie"])
        and_response = self.client.get(
            url,
            {"tag": ["Favorite", "Comedy"], "tag_mode": "and"},
        )
        self.assertEqual(and_response.context["media_list"].paginator.count, 0)

        or_response = self.client.get(
            url,
            {"tag": ["Favorite", "Comedy"], "tag_mode": "or"},
        )
        self.assertEqual(or_response.context["media_list"].paginator.count, 2)

        not_response = self.client.get(
            url,
            {"tag": ["Favorite", "Comedy"], "tag_mode": "not"},
        )
        self.assertEqual(not_response.context["media_list"].paginator.count, 1)
        self.assertContains(not_response, "Still Untagged Movie")

    def test_legacy_exclude_tag_falls_back_to_not_mode(self):
        """Old scalar tag_exclude links remain valid without a data migration."""
        response = self.client.get(
            reverse("medialist", args=["movie"]),
            {"tag_exclude": "Favorite"},
        )
        self.assertEqual(response.context["current_tag"], ["Favorite"])
        self.assertEqual(response.context["current_tag_mode"], "not")

    def test_tag_filter_case_insensitive(self):
        """Tag filter is case-insensitive."""
        url = reverse("medialist", args=["movie"])
        response = self.client.get(url, {"tag": "favorite"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tagged Movie")
        self.assertNotContains(response, "Untagged Movie")

    def test_no_tag_filter_shows_all(self):
        """No tag filter shows all items."""
        url = reverse("medialist", args=["movie"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tagged Movie")
        self.assertContains(response, "Untagged Movie")

    def test_tag_filter_data_is_ordered_by_current_media_usage(self):
        """Tag options show current-list usage counts, including zeroes."""
        popular = Tag.objects.create(user=self.user, name="Popular")
        unused = Tag.objects.create(user=self.user, name="Unused")
        game_only = Tag.objects.create(user=self.user, name="Game Only")
        ItemTag.objects.create(tag=popular, item=self.item1)
        ItemTag.objects.create(tag=popular, item=self.item2)

        game_item = Item.objects.create(
            media_id="game-1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Tagged Game",
        )
        ItemTag.objects.create(tag=game_only, item=game_item)

        response = self.client.get(reverse("medialist", args=["movie"]))
        self.assertEqual(response.status_code, 200)
        filter_data = response.context["filter_data"]

        self.assertEqual(
            filter_data["tags"],
            ["Popular", "Favorite", "Game Only", "Unused"],
        )
        self.assertEqual(
            filter_data["tag_counts"],
            {"Popular": 2, "Favorite": 1, "Game Only": 0, "Unused": 0},
        )
        self.assertContains(response, '"tag_counts"')
        self.assertContains(response, 'x-text="tagCounts[option] || 0"')

    def test_tag_filter_counts_refresh_after_bulk_assignment(self):
        """Tag usage counts are invalidated when a tag is assigned in bulk."""
        list_url = reverse("medialist", args=["movie"])
        first_response = self.client.get(list_url)
        self.assertEqual(
            first_response.context["filter_data"]["tag_counts"],
            {"Favorite": 1},
        )

        toggle_response = self.client.post(
            reverse("tag_bulk_toggle"),
            {
                "tag_name": "Favorite",
                "action": "add",
                "item_ids": [self.item2.id],
            },
        )
        self.assertEqual(toggle_response.status_code, 204)

        second_response = self.client.get(list_url)
        self.assertEqual(
            second_response.context["filter_data"]["tag_counts"],
            {"Favorite": 2},
        )


class TagIndexViewTest(TestCase):
    """Test the tag_index view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.movie_item = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
        )
        self.other_movie_item = Item.objects.create(
            media_id="279",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Se7en",
            image="http://example.com/image2.jpg",
        )
        self.tag = Tag.objects.create(user=self.user, name="Favorite")
        self.empty_tag = Tag.objects.create(user=self.user, name="Someday")
        ItemTag.objects.create(tag=self.tag, item=self.movie_item)
        ItemTag.objects.create(tag=self.tag, item=self.other_movie_item)

    def test_shows_tags_with_item_counts(self):
        """Index page lists tags with usage counts and per-media-type links."""
        response = self.client.get(reverse("tag_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Favorite")
        self.assertContains(response, "Someday")
        tags_by_name = {tag.name: tag for tag in response.context["tags"]}
        self.assertEqual(tags_by_name["Favorite"].item_count, 2)
        self.assertEqual(tags_by_name["Someday"].item_count, 0)

    def test_tag_link_ignores_saved_status_filter(self):
        """Following a tag link lists every tagged entry, whatever status was saved."""
        Movie.objects.create(
            item=self.movie_item,
            user=self.user,
            status=Status.COMPLETED,
        )
        self.user.update_preference("movie_status", Status.PLANNING.value)

        response = self.client.get(reverse("tag_index"))
        link = response.context["tags"][0].type_breakdown[0]["url"]
        response = self.client.get(link)

        self.assertContains(response, "The Shawshank Redemption")

    def test_only_shows_current_users_tags(self):
        """Index page never surfaces another user's tags."""
        other_user = get_user_model().objects.create_user(
            username="other", password="12345"
        )
        Tag.objects.create(user=other_user, name="Not Mine")
        response = self.client.get(reverse("tag_index"))
        self.assertNotContains(response, "Not Mine")

    def test_delete_from_index_removes_tag(self):
        """Deleting a tag from the index page removes it without an item_id."""
        response = self.client.post(
            reverse("tag_delete"),
            {"tag_id": self.tag.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Tag.objects.filter(id=self.tag.id).exists())


class TagBulkToggleViewTest(TestCase):
    """Test the tag_bulk_toggle view."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item1 = Item.objects.create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Shawshank Redemption",
            image="http://example.com/image.jpg",
        )
        self.item2 = Item.objects.create(
            media_id="279",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Se7en",
            image="http://example.com/image2.jpg",
        )
        self.tag = Tag.objects.create(user=self.user, name="Favorite")

    def test_bulk_add_applies_to_all_items(self):
        """Bulk add creates ItemTag links for every selected item."""
        url = reverse("tag_bulk_toggle")
        response = self.client.post(
            url,
            {
                "tag_name": "Favorite",
                "action": "add",
                "item_ids": [self.item1.id, self.item2.id],
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertTrue(
            ItemTag.objects.filter(tag=self.tag, item=self.item1).exists(),
        )
        self.assertTrue(
            ItemTag.objects.filter(tag=self.tag, item=self.item2).exists(),
        )

    def test_bulk_add_is_idempotent(self):
        """Bulk add does not error when an item already has the tag."""
        ItemTag.objects.create(tag=self.tag, item=self.item1)
        url = reverse("tag_bulk_toggle")
        response = self.client.post(
            url,
            {
                "tag_name": "Favorite",
                "action": "add",
                "item_ids": [self.item1.id, self.item2.id],
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            ItemTag.objects.filter(tag=self.tag, item=self.item1).count(),
            1,
        )

    def test_bulk_remove_removes_from_all_items(self):
        """Bulk remove deletes ItemTag links for every selected item."""
        ItemTag.objects.create(tag=self.tag, item=self.item1)
        ItemTag.objects.create(tag=self.tag, item=self.item2)
        url = reverse("tag_bulk_toggle")
        response = self.client.post(
            url,
            {
                "tag_name": "Favorite",
                "action": "remove",
                "item_ids": [self.item1.id, self.item2.id],
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ItemTag.objects.filter(tag=self.tag).exists())

    def test_cannot_bulk_tag_with_other_users_tag(self):
        """Cannot apply a tag owned by another user."""
        other_user = get_user_model().objects.create_user(
            username="other", password="12345"
        )
        Tag.objects.create(user=other_user, name="Not Mine")
        url = reverse("tag_bulk_toggle")
        response = self.client.post(
            url,
            {
                "tag_name": "Not Mine",
                "action": "add",
                "item_ids": [self.item1.id],
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_requires_item_ids(self):
        """Rejects requests with no items selected."""
        url = reverse("tag_bulk_toggle")
        response = self.client.post(
            url,
            {"tag_name": "Favorite", "action": "add", "item_ids": []},
        )
        self.assertEqual(response.status_code, 400)


class TagLinkShowsEveryTaggedEntryTest(TestCase):
    """The Tags page link must list the entries its count includes (#1351)."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.tag = Tag.objects.create(user=self.user, name="Will Not Play")

    def _item(self, media_type, title, media_id=None, **extra):
        item = Item.objects.create(
            media_id=media_id or title,
            source=extra.pop("source", Sources.MANUAL.value),
            media_type=media_type,
            title=title,
            image="http://example.com/image.jpg",
            **extra,
        )
        ItemTag.objects.create(tag=self.tag, item=item)
        return item

    def _followed(self, media_type):
        """Click the tag's link for ``media_type`` on the Tags page."""
        response = self.client.get(reverse("tag_index"))
        tag = next(t for t in response.context["tags"] if t.id == self.tag.id)
        entry = next(e for e in tag.type_breakdown if e["media_type"] == media_type)
        return entry, self.client.get(entry["url"])

    def test_link_lists_games_in_every_status(self):
        for index, status in enumerate(
            [Status.PLANNING, Status.COMPLETED, Status.DROPPED],
        ):
            item = self._item(MediaTypes.GAME.value, f"Game {index}")
            Game.objects.create(item=item, user=self.user, status=status.value)
        self.user.update_preference("game_status", Status.IN_PROGRESS.value)

        entry, response = self._followed(MediaTypes.GAME.value)

        self.assertEqual(entry["count"], 3)
        for index in range(3):
            self.assertContains(response, f"Game {index}")

    def test_link_lists_rating_only_games(self):
        """A row with no status (an imported rating) sits outside every status."""
        item = self._item(MediaTypes.GAME.value, "Rated Only Game")
        Game.objects.create(item=item, user=self.user, status=None, score=7)

        _entry, response = self._followed(MediaTypes.GAME.value)

        self.assertContains(response, "Rated Only Game")

    def test_link_lists_tagged_games_nobody_tracks(self):
        self._item(MediaTypes.GAME.value, "Tagged Only Game")

        _entry, response = self._followed(MediaTypes.GAME.value)

        self.assertContains(response, "Tagged Only Game")

    def test_link_lists_collected_games_without_a_tracker(self):
        item = self._item(MediaTypes.GAME.value, "Collected Game")
        CollectionEntry.objects.create(user=self.user, item=item)

        _entry, response = self._followed(MediaTypes.GAME.value)

        self.assertContains(response, "Collected Game")

    def test_tagged_but_untracked_items_do_not_leak_into_plain_lists(self):
        """Only asking for the tag brings in items nobody tracks."""
        self._item(MediaTypes.GAME.value, "Tagged Only Game")

        response = self.client.get(reverse("medialist", args=["game"]))

        self.assertNotContains(response, "Tagged Only Game")

    def test_untracked_tag_match_ignores_other_users_tags(self):
        other = get_user_model().objects.create_user(username="o", password="p")
        theirs = Tag.objects.create(user=other, name="Will Not Play")
        item = Item.objects.create(
            media_id="x",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="Their Game",
            image="http://example.com/image.jpg",
        )
        ItemTag.objects.create(tag=theirs, item=item)

        response = self.client.get(
            reverse("medialist", args=["game"]),
            {"tag": "Will Not Play", "status": ["no_status"]},
        )

        self.assertNotContains(response, "Their Game")

    def test_tagged_but_untracked_items_obey_not_mode(self):
        self._item(MediaTypes.GAME.value, "Tagged Only Game")

        response = self.client.get(
            reverse("medialist", args=["game"]),
            {"tag": "Will Not Play", "tag_mode": "not", "status": ["no_status"]},
        )

        self.assertNotContains(response, "Tagged Only Game")

    def test_link_lists_tagged_only_items_in_separate_entries_mode(self):
        """The Python-built path (one card per entry) finds them too."""
        self._item(MediaTypes.GAME.value, "Tagged Only Game")
        self.user.game_show_each_play = True
        self.user.save(update_fields=["game_show_each_play"])

        _entry, response = self._followed(MediaTypes.GAME.value)

        self.assertContains(response, "Tagged Only Game")

    def test_grouped_anime_links_to_the_anime_list(self):
        item = self._item(
            MediaTypes.TV.value,
            "Grouped Anime",
            source=Sources.TMDB.value,
            library_media_type=MediaTypes.ANIME.value,
        )
        TV.objects.create(item=item, user=self.user, status=Status.PLANNING.value)

        entry, response = self._followed(MediaTypes.ANIME.value)

        self.assertEqual(entry["count"], 1)
        self.assertContains(response, "Grouped Anime")

    def test_grouped_anime_links_to_the_tv_list_when_that_is_its_library(self):
        item = self._item(
            MediaTypes.TV.value,
            "Grouped Anime",
            source=Sources.TMDB.value,
            library_media_type=MediaTypes.ANIME.value,
        )
        TV.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        self.user.anime_library_mode = MediaTypes.TV.value
        self.user.save(update_fields=["anime_library_mode"])

        _entry, response = self._followed(MediaTypes.TV.value)

        self.assertContains(response, "Grouped Anime")

    def test_music_link_opens_the_tracks_view(self):
        """Tags sit on tracks; the default artists view never lists them."""
        artist = Artist.objects.create(name="Band")
        album = Album.objects.create(title="Record", artist=artist)
        track = Track.objects.create(album=album, title="Song")
        item = self._item(
            MediaTypes.MUSIC.value,
            "Tagged Song",
            source=Sources.MUSICBRAINZ.value,
        )
        Music.objects.create(
            item=item,
            user=self.user,
            artist=artist,
            album=album,
            track=track,
            status=Status.COMPLETED.value,
        )

        entry, response = self._followed(MediaTypes.MUSIC.value)

        self.assertIn("subview=tracks", entry["url"])
        self.assertContains(response, "Tagged Song")

    def test_podcast_list_honours_the_tag_filter(self):
        tagged = PodcastShow.objects.create(
            podcast_uuid="tagged-show",
            source=Sources.POCKETCASTS.value,
            title="Tagged Show",
        )
        other = PodcastShow.objects.create(
            podcast_uuid="other-show",
            source=Sources.POCKETCASTS.value,
            title="Other Show",
        )
        for show in (tagged, other):
            PodcastShowTracker.objects.create(
                user=self.user,
                show=show,
                status=Status.IN_PROGRESS.value,
            )
        self._item(
            MediaTypes.PODCAST.value,
            "Tagged Show",
            media_id="tagged-show",
            source=Sources.POCKETCASTS.value,
        )

        _entry, response = self._followed(MediaTypes.PODCAST.value)
        self.assertContains(response, "Tagged Show")
        self.assertNotContains(response, "Other Show")

        response = self.client.get(
            reverse("medialist", args=["podcast"]),
            {"tag": "Will Not Play", "tag_mode": "not"},
        )
        self.assertNotContains(response, "Tagged Show")
        self.assertContains(response, "Other Show")

    def test_podcast_list_finds_shows_by_a_tagged_episode(self):
        """An episode's tag counts for its show."""
        tagged = PodcastShow.objects.create(
            podcast_uuid="tagged-show",
            source=Sources.POCKETCASTS.value,
            title="Show With Tagged Episode",
        )
        other = PodcastShow.objects.create(
            podcast_uuid="other-show",
            source=Sources.POCKETCASTS.value,
            title="Show Without Tags",
        )
        for show in (tagged, other):
            PodcastShowTracker.objects.create(
                user=self.user,
                show=show,
                status=Status.IN_PROGRESS.value,
            )
        PodcastEpisode.objects.create(
            show=tagged,
            episode_uuid="tagged-episode",
            title="Episode",
        )
        self._item(
            MediaTypes.PODCAST.value,
            "Episode",
            media_id="tagged-episode",
            source=Sources.POCKETCASTS.value,
        )

        _entry, response = self._followed(MediaTypes.PODCAST.value)
        self.assertContains(response, "Show With Tagged Episode")
        self.assertNotContains(response, "Show Without Tags")

        response = self.client.get(
            reverse("medialist", args=["podcast"]),
            {"tag": "Will Not Play", "tag_mode": "not"},
        )
        self.assertNotContains(response, "Show With Tagged Episode")
        self.assertContains(response, "Show Without Tags")


class NormalizeTagNamesMigrationTest(TestCase):
    """Names stored with stray whitespace never matched the tag filter (#1351)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.migration = importlib.import_module(
            "app.migrations.0200_normalize_tag_names",
        )

    def _tag(self, name):
        tag = Tag.objects.create(user=self.user, name="placeholder")
        Tag.objects.filter(pk=tag.pk).update(name=name)
        return tag

    def _item(self, media_id):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title=media_id,
            image="http://example.com/image.jpg",
        )

    def test_trailing_space_is_removed(self):
        tag = self._tag("Will Not Play ")

        self.migration.normalize_tag_names(django_apps, None)

        tag.refresh_from_db()
        self.assertEqual(tag.name, "Will Not Play")

    def test_tags_that_become_equal_are_merged(self):
        keeper = self._tag("Backlog")
        stray = self._tag("backlog ")
        shared, only_stray = self._item("a"), self._item("b")
        ItemTag.objects.create(tag=keeper, item=shared)
        ItemTag.objects.create(tag=stray, item=shared)
        ItemTag.objects.create(tag=stray, item=only_stray)

        self.migration.normalize_tag_names(django_apps, None)

        self.assertFalse(Tag.objects.filter(pk=stray.pk).exists())
        self.assertCountEqual(
            ItemTag.objects.filter(tag=keeper).values_list("item_id", flat=True),
            [shared.id, only_stray.id],
        )

    def test_two_strays_of_one_name_merge_into_one_tag(self):
        self._tag(" Later")
        self._tag("Later ")

        self.migration.normalize_tag_names(django_apps, None)

        self.assertEqual(list(Tag.objects.values_list("name", flat=True)), ["Later"])

    def test_tagged_list_finds_the_entry_after_normalizing(self):
        tag = self._tag("Will Not Play ")
        item = self._item("Stray Game")
        Game.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        ItemTag.objects.create(tag=tag, item=item)
        self.client.login(username="test", password="12345")
        url = reverse("medialist", args=["game"])

        self.assertNotContains(
            self.client.get(url, {"tag": "Will Not Play "}),
            "Stray Game",
        )
        self.migration.normalize_tag_names(django_apps, None)

        self.assertContains(self.client.get(url, {"tag": "Will Not Play"}), "Stray Game")
