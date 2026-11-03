"""The card model reads the same answers the media card template renders."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.card_surfaces import card_context
from app.media_card_model import card_model, card_shape
from app.models import Item, MediaTypes, Movie, Sources, Status


class MediaCardModelTest(TestCase):
    """One tracked movie and a podcast, through the library surface."""

    def setUp(self):
        """Create a user and a completed movie."""
        self.user = get_user_model().objects.create_user("model-user", password="x")
        self.item = Item.objects.create(
            media_id="model-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Model Movie",
        )
        self.movie = Movie.objects.create(
            item=self.item, user=self.user, status=Status.COMPLETED.value, progress=2,
        )

    def test_shapes(self):
        """Podcasts and music are square, library video is landscape."""
        self.assertEqual(card_shape("movie"), "poster")
        self.assertEqual(card_shape("podcast"), "square")
        self.assertEqual(card_shape("video", video_landscape=True), "landscape")

    def test_movie_model(self):
        """A completed movie has a status chip, its title and a play count."""
        ctx = card_context({"user": self.user}, "library", {"item": self.item, "media": self.movie})
        model = card_model(ctx)
        self.assertEqual(model["title"], "Model Movie")
        self.assertEqual(model["shape"], "poster")
        self.assertEqual(model["statusChip"]["kind"], "status")
        self.assertEqual(model["statusChip"]["status"], Status.COMPLETED.value)
        self.assertIn("model-1", model["href"])
