import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, ItemTag, MediaTypes, Movie, Sources, Status, Tag


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

    def test_exclude_tag_filter(self):
        """Tag exclude filter hides items with the tag."""
        url = reverse("medialist", args=["movie"])
        response = self.client.get(url, {"tag_exclude": "Favorite"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Tagged Movie")
        self.assertContains(response, "Untagged Movie")

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
