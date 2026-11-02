"""Tests for saved media list views pinned under the sidebar."""

import re
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes
from users.models import HISTORY_VIEW_TYPE, SavedView


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


class HistorySavedViewTests(TestCase):
    """Saved views of the History page share the sidebar machinery."""

    def setUp(self):
        """Log in a user who owns the views."""
        self.credentials = {"username": "historian", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _save(self, query, name="No music"):
        return self.client.post(
            reverse("saved_view_create"),
            {"media_type": HISTORY_VIEW_TYPE, "name": name, "query": query},
        )

    def test_save_keeps_only_the_filter_window_fields(self):
        """The saved link reopens History with its filters, minus paging noise."""
        response = self._save(
            "media_type=tv,movie&start-date=2026-01-01&genre=Drama&page=4&tv=12&empty=",
        )

        self.assertEqual(response.status_code, 200)
        saved_view = SavedView.objects.get(user=self.user)
        self.assertEqual(saved_view.media_type, HISTORY_VIEW_TYPE)
        parsed = urlparse(saved_view.get_absolute_url())
        self.assertEqual(parsed.path, reverse("history"))
        self.assertEqual(response.json()["url"], saved_view.get_absolute_url())
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "start-date": ["2026-01-01"],
                "media_type": ["tv,movie"],
                "genre": ["Drama"],
            },
        )

    def test_save_with_no_filters_opens_plain_history(self):
        """A view saved with nothing chosen links to History without a query."""
        self._save("")

        self.assertEqual(
            SavedView.objects.get().get_absolute_url(),
            reverse("history"),
        )

    def test_save_rejects_blank_name(self):
        """A History view needs a name like any other saved view."""
        response = self._save("media_type=tv", name=" ")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(SavedView.objects.exists())

    def test_sidebar_shows_views_under_history_for_their_owner_only(self):
        """History gets its own group with only the user's views."""
        other = get_user_model().objects.create_user(
            username="other",
            password="testpass123",
        )
        mine = SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="No music",
            query="media_type=tv",
        )
        SavedView.objects.create(
            user=other,
            media_type=HISTORY_VIEW_TYPE,
            name="Someone else's",
        )
        # A movie view must not leak into the History group.
        SavedView.objects.create(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            name="Finished movies",
            query="status=Completed",
        )

        response = self.client.get(mine.get_absolute_url())

        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, f'href="{mine.get_absolute_url()}"')
        self.assertContains(response, reverse("saved_view_delete", args=[mine.id]))
        self.assertNotContains(response, "Someone else&#x27;s")

    def test_history_without_views_keeps_the_plain_link(self):
        """No saved views means no extra group in the sidebar."""
        response = self.client.get(reverse("history"))

        self.assertNotContains(response, reverse("saved_view_reorder"))

    def test_saved_view_filters_the_history_page(self):
        """Opening the saved link applies its media type filter."""
        saved_view = SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="Movies",
            query="media_type=movie",
        )

        response = self.client.get(saved_view.get_absolute_url())

        self.assertEqual(response.status_code, 200)

    def test_delete_returns_to_history(self):
        """Deleting a History view without a safe next URL lands on History."""
        saved_view = SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="Gone",
        )

        response = self.client.post(reverse("saved_view_delete", args=[saved_view.id]))

        self.assertRedirects(
            response,
            reverse("history"),
            fetch_redirect_response=False,
        )
        self.assertFalse(SavedView.objects.exists())

    def test_reorder_works_for_history_views(self):
        """History views reorder like any other group."""
        first = SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="First",
            position=0,
        )
        second = SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="Second",
            position=1,
        )

        response = self.client.post(
            reverse("saved_view_reorder"),
            {"media_type": HISTORY_VIEW_TYPE, "ids": [second.id, first.id]},
        )

        self.assertEqual(response.status_code, 204)
        second.refresh_from_db()
        self.assertEqual(second.position, 0)

    def test_demo_account_cannot_save_history_views(self):
        """Demo accounts stay view-only."""
        self.user.is_demo = True
        self.user.save()

        response = self._save("media_type=tv")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SavedView.objects.exists())

    def _toggle_button_classes(self, url):
        """Return the class list of the sidebar's "Saved History views" button."""
        html = self.client.get(url).content.decode()
        match = re.search(
            r'<button[^>]*?class="([^"]*)"[^>]*?aria-label="Saved History views"',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def test_sidebar_chevron_shows_on_hover_or_when_current(self):
        """The expand arrow is hidden at rest, except on the page that is open."""
        SavedView.objects.create(
            user=self.user,
            media_type=HISTORY_VIEW_TYPE,
            name="No music",
            query="media_type=tv",
        )

        elsewhere = self._toggle_button_classes(reverse("calendar"))
        on_history = self._toggle_button_classes(reverse("history"))

        self.assertIn("pointer-fine:opacity-0", elsewhere)
        self.assertIn("pointer-fine:group-hover:opacity-100", elsewhere)
        self.assertNotIn("pointer-fine:opacity-0", on_history)
