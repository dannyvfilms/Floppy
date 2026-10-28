"""Rating endpoints: clearing a score, and the card fragment a rating returns."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from app.templatetags.app_tags import item_slot_id


class CardRatingFragmentTests(TestCase):
    """Rating an item returns the card's rating, still a button, for the swap."""

    def setUp(self):
        """Log in and track a movie."""
        credentials = {"username": "score-user", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.client.login(**credentials)
        item = Item.objects.create(
            media_id="score-movie",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Score Movie",
        )
        self.movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
        )
        self.url = reverse(
            "update_media_score", args=[MediaTypes.MOVIE.value, self.movie.id]
        )

    def test_response_swaps_the_card_rating_and_keeps_it_rateable(self):
        """The swapped-in rating shows the new score and can be clicked again."""
        response = self.client.post(self.url, {"score": "7", "toggle": "true"})

        self.assertContains(response, f'id="{item_slot_id("media-card-rating", self.movie.item)}"')
        self.assertContains(response, "media-card-rate-button")
        self.assertContains(response, f'hx-post="{self.url}"')
        self.assertContains(response, "rating: 7")

    def test_clearing_the_rating_leaves_the_empty_star(self):
        """Clicking the current score clears it and the card offers the empty star."""
        self.client.post(self.url, {"score": "7", "toggle": "true"})
        response = self.client.post(self.url, {"score": "7", "toggle": "true"})

        self.movie.refresh_from_db()
        self.assertIsNone(self.movie.score)
        self.assertContains(response, "rating: null")


class MusicScoreToggleTests(TestCase):
    """The music pages' picker clears a score by clicking it again, like every other."""

    def setUp(self):
        """Log in and create an artist and album tracker."""
        credentials = {"username": "music-toggle", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.client.login(**credentials)
        self.artist = Artist.objects.create(name="Toggle Artist")
        self.album = Album.objects.create(title="Toggle Album", artist=self.artist)

    def test_album_score_toggles_off(self):
        """Posting the stored album score with toggle clears it."""
        url = reverse("update_album_score", args=[self.album.id])
        self.client.post(url, {"score": "8", "toggle": "true"})
        tracker = AlbumTracker.objects.get(user=self.user, album=self.album)
        self.assertEqual(tracker.score, 8)

        response = self.client.post(url, {"score": "8", "toggle": "true"})

        tracker.refresh_from_db()
        self.assertIsNone(tracker.score)
        self.assertIsNone(response.json()["score"])

    def test_artist_score_toggles_off(self):
        """Posting the stored artist score with toggle clears it."""
        url = reverse("update_artist_score", args=[self.artist.id])
        self.client.post(url, {"score": "8", "toggle": "true"})
        tracker = ArtistTracker.objects.get(user=self.user, artist=self.artist)
        self.assertEqual(tracker.score, 8)

        self.client.post(url, {"score": "8", "toggle": "true"})

        tracker.refresh_from_db()
        self.assertIsNone(tracker.score)

    def test_score_without_toggle_is_kept(self):
        """A plain post of the same score keeps it, as before."""
        url = reverse("update_album_score", args=[self.album.id])
        self.client.post(url, {"score": "8"})
        self.client.post(url, {"score": "8"})

        tracker = AlbumTracker.objects.get(user=self.user, album=self.album)
        self.assertEqual(tracker.score, 8)
