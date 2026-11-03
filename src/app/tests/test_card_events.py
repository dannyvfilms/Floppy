"""Save and score responses tell React cards what changed."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.card_events import card_update_event
from app.models import Item, MediaTypes, Movie, Sources, Status


class CardEventsTest(TestCase):
    """A score change reaches the card through the floppyCardUpdate trigger."""

    def setUp(self):
        """Create a user with a completed movie."""
        self.user = get_user_model().objects.create_user("events-user", password="x")
        self.client.force_login(self.user)
        self.item = Item.objects.create(
            media_id="event-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Event Movie",
        )
        self.movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
        )

    def test_event_names_the_card_and_its_status(self):
        """The payload carries the card key, status and a rate button for it."""
        detail = card_update_event(self.item, self.movie, self.user)
        self.assertEqual(detail["cardKey"], "media-card-tmdb-movie-event-1")
        self.assertEqual(detail["status"], Status.COMPLETED.value)
        self.assertFalse(detail["statusless"])
        self.assertTrue(detail["rating"]["rateUrl"].endswith(f"/{self.movie.id}"))

    def test_score_response_sends_the_event(self):
        """Rating a movie adds floppyCardUpdate to the response's HX-Trigger."""
        response = self.client.post(
            reverse("update_media_score", args=["movie", self.movie.id]),
            {"score": "4"},
        )
        self.assertEqual(response.status_code, 200)
        triggers = json.loads(response["HX-Trigger"])
        self.assertEqual(
            triggers["floppyCardUpdate"]["cardKey"],
            "media-card-tmdb-movie-event-1",
        )
        self.assertIsNotNone(triggers["floppyCardUpdate"]["rating"]["label"])
