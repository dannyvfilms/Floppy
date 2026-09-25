"""Tests for saved media list views pinned under the sidebar."""

from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes
from users.models import SavedView


class SavedViewTests(TestCase):
    """Saving, showing, opening, deleting and reordering saved views."""

    def setUp(self):
        """Log in a user who owns the views."""
        self.credentials = {"username": "viewer", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.other_user = get_user_model().objects.create_user(
            username="other",
            password="testpass123",
        )

    def _save(self, **params):
        payload = {"media_type": MediaTypes.MOVIE.value, "name": "Finished"}
        payload.update(params)
        return self.client.post(reverse("saved_view_create"), payload)

    def _view(self, name, user=None, position=0, query="status=Completed"):
        return SavedView.objects.create(
            user=user or self.user,
            media_type=MediaTypes.MOVIE.value,
            name=name,
            query=query,
            position=position,
        )

    def test_save_stores_the_current_filters(self):
        """The saved link carries the filters, sort and layout, not request noise."""
        response = self._save(
            sort="score",
            direction="desc",
            layout="table",
            status="Completed",
            genre="",
            page="3",
        )

        self.assertEqual(response.status_code, 200)
        saved_view = SavedView.objects.get(user=self.user)
        self.assertEqual(saved_view.name, "Finished")
        self.assertEqual(response.json()["url"], saved_view.get_absolute_url())
        parsed = urlparse(saved_view.get_absolute_url())
        self.assertEqual(parsed.path, reverse("medialist", args=["movie"]))
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "sort": ["score"],
                "direction": ["desc"],
                "layout": ["table"],
                "status": ["Completed"],
            },
        )

    def test_save_without_status_means_all_statuses(self):
        """No status must not fall back to whatever status was used last."""
        self._save(sort="title")

        query = parse_qs(SavedView.objects.get(user=self.user).query)
        self.assertEqual(query["status"], ["All"])

    def test_new_views_go_to_the_bottom(self):
        """Each new view of a media type is placed after the existing ones."""
        self._save(name="First")
        self._save(name="Second")

        names = list(
            SavedView.objects.filter(user=self.user)
            .order_by("position")
            .values_list("name", flat=True),
        )
        self.assertEqual(names, ["First", "Second"])

    def test_save_rejects_blank_name_and_unknown_media_type(self):
        """Nothing is saved without a name or for a media type not in the sidebar."""
        self.assertEqual(self._save(name="  ").status_code, 400)
        self.assertEqual(self._save(media_type="nonsense").status_code, 400)
        self.assertFalse(SavedView.objects.exists())

    def test_demo_account_cannot_save(self):
        """Demo accounts are view-only."""
        self.user.is_demo = True
        self.user.save(update_fields=["is_demo"])

        self.assertEqual(self._save().status_code, 403)
        self.assertFalse(SavedView.objects.exists())

    def test_sidebar_lists_only_your_own_views(self):
        """The sidebar shows the user's saved views under their media type."""
        mine = self._view("My finished movies")
        self._view("Someone else's view", user=self.other_user)

        response = self.client.get(reverse("medialist", args=["movie"]))

        self.assertContains(response, "My finished movies")
        self.assertContains(response, f'href="{mine.get_absolute_url()}"')
        self.assertContains(response, reverse("saved_view_delete", args=[mine.id]))
        self.assertNotContains(response, "Someone else&#x27;s view")

    def test_opening_a_saved_view_shows_its_filters(self):
        """Clicking a saved view opens it, and the plain list keeps it as last used."""
        saved_view = self._view("Finished", query="status=Completed&sort=score")

        response = self.client.get(saved_view.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-current="page"')
        self.user.refresh_from_db()
        self.assertEqual(self.user.movie_status, "Completed")
        self.assertEqual(self.user.movie_sort, "score")

    def test_delete_removes_the_view_and_returns(self):
        """Delete removes the view and goes back to the page it was on."""
        saved_view = self._view("Finished")
        next_url = reverse("medialist", args=["movie"]) + "?sort=title"

        response = self.client.post(
            reverse("saved_view_delete", args=[saved_view.id]),
            {"next": next_url},
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)
        self.assertFalse(SavedView.objects.filter(id=saved_view.id).exists())

    def test_delete_ignores_an_outside_next_url(self):
        """A next URL on another site falls back to the media list."""
        saved_view = self._view("Finished")

        response = self.client.post(
            reverse("saved_view_delete", args=[saved_view.id]),
            {"next": "https://example.com/"},
        )

        self.assertRedirects(
            response,
            reverse("medialist", args=["movie"]),
            fetch_redirect_response=False,
        )

    def test_cannot_delete_someone_elses_view(self):
        """Another user's view is not found and stays in place."""
        theirs = self._view("Theirs", user=self.other_user)

        response = self.client.post(reverse("saved_view_delete", args=[theirs.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavedView.objects.filter(id=theirs.id).exists())

    def test_reorder_saves_the_new_order(self):
        """Reorder stores the dragged order and ignores other users' views."""
        first = self._view("First", position=0)
        second = self._view("Second", position=1)
        third = self._view("Third", position=2)
        theirs = self._view("Theirs", user=self.other_user, position=5)

        response = self.client.post(
            reverse("saved_view_reorder"),
            {
                "media_type": MediaTypes.MOVIE.value,
                "ids": [third.id, theirs.id, first.id],
            },
        )

        self.assertEqual(response.status_code, 204)
        names = list(
            SavedView.objects.filter(user=self.user)
            .order_by("position")
            .values_list("name", flat=True),
        )
        # "Second" was left out of the request, so it keeps its place at the end.
        self.assertEqual(names, ["Third", "First", "Second"])
        second.refresh_from_db()
        self.assertEqual(second.position, 2)
        theirs.refresh_from_db()
        self.assertEqual(theirs.position, 5)
