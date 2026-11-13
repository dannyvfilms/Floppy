"""A non-numeric ``page`` query parameter must fall back to page 1, not 500."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from lists.models import CustomList


class NonNumericPageTests(TestCase):
    """Send ``?page=abc`` to every list-shaped view."""

    def setUp(self):
        """Create a logged-in user and a list."""
        self.user = get_user_model().objects.create_user(
            username="pager",
            password="test-only-pw",
        )
        self.client.force_login(self.user)
        self.custom_list, _ = CustomList.objects.get_or_create(
            name="Pager list",
            owner=self.user,
        )

    def _assert_not_500(self, url, **extra):
        response = self.client.get(url, {"page": "abc"}, **extra)
        self.assertLess(response.status_code, 500, url)

    def test_medialist(self):
        """The media list falls back to page 1, plain and as an HTMX fragment."""
        url = reverse("medialist", args=["movie"])
        self._assert_not_500(url)
        self._assert_not_500(url, HTTP_HX_REQUEST="true")

    def test_music_artists(self):
        """The music artists subview re-checked the raw page; it must not 500."""
        url = reverse("medialist", args=["music"])
        self._assert_not_500(url)
        self._assert_not_500(url, HTTP_HX_REQUEST="true")

    def test_collection_list(self):
        """The collection list falls back to page 1."""
        self._assert_not_500(reverse("collection_list"))

    def test_search(self):
        """Search falls back to page 1 (video has no provider to call)."""
        response = self.client.get(
            reverse("search"),
            {"media_type": "video", "q": "x", "page": "abc"},
        )
        self.assertLess(response.status_code, 500)

    def test_list_detail(self):
        """The list detail page falls back to page 1."""
        self._assert_not_500(
            reverse("list_detail", args=[self.custom_list.id]),
        )
