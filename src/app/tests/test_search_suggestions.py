from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources
from users.models import Status


class SearchSuggestionsViewTests(TestCase):
    """Tests for the saved-library autocomplete suggestions endpoint."""

    def setUp(self):
        """Create a user with one saved movie and log them in."""
        self.user = get_user_model().objects.create_user(
            username="suggest-user",
            password="12345",
        )
        self.client.force_login(self.user)

        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/image.jpg",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
        )

    def _get(self, query, media_type=MediaTypes.MOVIE.value):
        """Request the suggestions fragment for a query/media_type."""
        return self.client.get(
            reverse("search_suggestions"),
            {"q": query, "media_type": media_type},
        )

    def test_matching_saved_item_is_suggested(self):
        """A saved item matching the query is returned with a detail link."""
        response = self._get("godfa")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Godfather")
        # Links straight to the item detail page.
        self.assertContains(response, "/details/")
        # The footer offers the full online search.
        self.assertContains(response, "Search online for")

    def test_short_query_returns_empty(self):
        """A single-character query renders nothing (below the min length)."""
        response = self._get("g")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The Godfather")
        self.assertNotContains(response, "search online")

    def test_non_matching_query_shows_keep_typing_hint(self):
        """A query with no saved matches shows the search-online hint."""
        response = self._get("nonexistenttitle")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The Godfather")
        self.assertContains(response, "search online")

    def test_scoped_to_selected_media_type(self):
        """A saved movie is not suggested when the book type is selected."""
        response = self._get("godfa", media_type=MediaTypes.BOOK.value)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The Godfather")

    def test_only_owners_items_are_suggested(self):
        """A different user does not see another user's saved items."""
        other = get_user_model().objects.create_user(
            username="other-user",
            password="12345",
        )
        self.client.force_login(other)
        response = self._get("godfa")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "The Godfather")

    def test_requires_authentication(self):
        """Anonymous requests are redirected by the login-required middleware."""
        self.client.logout()
        response = self._get("godfa")
        self.assertEqual(response.status_code, 302)
