from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status
from lists.models import CustomList, CustomListItem


class ListSharingTest(TestCase):
    """Read-only sharing to installed users and link-only (unlisted) lists."""

    def setUp(self):
        """Create an owner, collaborator, viewer and outsider with one list."""
        users = get_user_model()
        self.owner = users.objects.create_user(username="owner", password="12345")
        self.collaborator = users.objects.create_user(
            username="collaborator",
            password="12345",
        )
        self.viewer = users.objects.create_user(username="viewer", password="12345")
        self.outsider = users.objects.create_user(username="outsider", password="12345")

        self.custom_list = CustomList.objects.create(name="Planning", owner=self.owner)
        self.custom_list.collaborators.add(self.collaborator)
        self.custom_list.viewers.add(self.viewer)

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Shared Movie",
        )
        CustomListItem.objects.create(custom_list=self.custom_list, item=self.item)

    def test_viewer_can_view_but_not_edit(self):
        """A viewer reads everything but has no write permission."""
        self.assertTrue(self.custom_list.user_can_view(self.viewer))
        self.assertFalse(self.custom_list.user_can_edit(self.viewer))
        self.assertEqual(self.custom_list.user_role(self.viewer), "Viewer")

    def test_viewer_sees_the_list_on_the_lists_page_as_read_only(self):
        """The viewer's Lists hub includes the shared list and says view only."""
        self.client.login(username="viewer", password="12345")
        response = self.client.get(reverse("lists"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planning")
        self.assertContains(response, "Shared with you · view only")

    def test_viewer_opens_the_list_without_edit_controls(self):
        """The detail page renders for a viewer without add or edit actions."""
        self.client.login(username="viewer", password="12345")
        response = self.client.get(
            reverse("list_detail", args=[self.custom_list.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Movie")
        self.assertNotContains(response, "Add New Item")
        self.assertNotContains(response, "Edit List")

    def test_viewer_cannot_change_list_membership(self):
        """A viewer posting to a write endpoint is rejected."""
        self.client.login(username="viewer", password="12345")
        response = self.client.post(
            reverse("list_item_toggle"),
            {
                "item_id": self.item.id,
                "custom_list_id": self.custom_list.id,
                "format": "json",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.custom_list.items.filter(id=self.item.id).exists())

    def test_viewer_cannot_edit_list_metadata(self):
        """The edit action rejects a viewer instead of silently redirecting."""
        self.client.login(username="viewer", password="12345")
        response = self.client.post(
            reverse("list_edit"),
            {"list_id": self.custom_list.id, "name": "Renamed"},
        )

        self.assertEqual(response.status_code, 403)
        self.custom_list.refresh_from_db()
        self.assertEqual(self.custom_list.name, "Planning")

    def test_viewer_cannot_reach_add_or_reorder_endpoints(self):
        """Read-only access is enforced server-side beyond the hidden controls."""
        self.client.login(username="viewer", password="12345")
        self.assertEqual(
            self.client.get(
                reverse("list_add_item", args=[self.custom_list.id]),
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("list_reorder_all", args=[self.custom_list.id]),
                {"item_ids[]": [self.item.id]},
            ).status_code,
            403,
        )

    def test_outsider_still_gets_404_for_private_list(self):
        """A user without any access cannot tell the private list exists."""
        self.client.login(username="outsider", password="12345")
        response = self.client.get(
            reverse("list_detail", args=[self.custom_list.id]),
        )

        self.assertEqual(response.status_code, 404)


    def test_viewer_sees_a_smart_lists_recomputed_contents(self):
        """Viewers read the owner's smart-list evaluation, not an empty shell."""
        smart_list = CustomList.objects.create(
            name="Owner Completed",
            owner=self.owner,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"status": ["Completed"]},
        )
        smart_list.viewers.add(self.viewer)
        watched = Item.objects.create(
            media_id="550",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Completed Smart Movie",
        )
        Movie.objects.create(item=watched, user=self.owner, status=Status.COMPLETED.value)

        self.client.login(username="viewer", password="12345")
        response = self.client.get(
            reverse("list_detail", args=[smart_list.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Completed Smart Movie")
        self.assertNotContains(response, "Add New Item")


class UnlistedListTest(TestCase):
    """Unlisted lists are reachable by link but absent from the public profile."""

    def setUp(self):
        """Create an unlisted list with a slug and one item."""
        self.owner = get_user_model().objects.create_user(
            username="owner",
            password="12345",
        )
        self.custom_list = CustomList.objects.create(
            name="Secret Planning",
            owner=self.owner,
            visibility="unlisted",
            public_slug="secret-planning",
        )
        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Secret Movie",
        )
        CustomListItem.objects.create(custom_list=self.custom_list, item=self.item)

    def test_anonymous_visitor_can_open_an_unlisted_list_by_slug(self):
        """The custom link opens without authentication."""
        response = self.client.get(
            reverse("list_detail", args=["secret-planning"]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secret Movie")

    def test_unlisted_list_is_omitted_from_the_public_profile(self):
        """Being link-visible does not add the list to the profile listing."""
        response = self.client.get(
            reverse("user_profile", args=[self.owner.username]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Secret Planning")

    def test_unlisted_list_exposes_link_feeds(self):
        """RSS and automation links work for unlisted lists."""
        rss = self.client.get(reverse("list_rss", args=["secret-planning"]))
        radarr = self.client.get(
            reverse("list_json", args=["secret-planning"]) + "?arr=radarr",
        )

        self.assertEqual(rss.status_code, 200)
        self.assertEqual(radarr.status_code, 200)

    def test_owner_sees_unlisted_state(self):
        """The list header names the visibility instead of calling it public."""
        self.client.login(username="owner", password="12345")
        response = self.client.get(
            reverse("list_detail", args=["secret-planning"]),
        )

        self.assertContains(response, "Unlisted")


class ListViewerManagerTest(TestCase):
    """The list browser resolves lists shared with a viewer."""

    def test_get_user_lists_includes_viewer_lists_but_not_for_editing(self):
        """Viewers see shared lists; the editable set stays owner/collaborator."""
        users = get_user_model()
        owner = users.objects.create_user(username="owner2", password="12345")
        viewer = users.objects.create_user(username="viewer2", password="12345")
        shared = CustomList.objects.create(name="Shared", owner=owner)
        shared.viewers.add(viewer)

        self.assertIn(shared, CustomList.objects.get_user_lists(viewer))
        self.assertNotIn(shared, CustomList.objects.get_editable_lists(viewer))
