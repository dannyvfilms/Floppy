from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from app.services.episode_scores import set_episode_score

OLD = datetime(2020, 1, 1, tzinfo=UTC)


class MediaScoredAtTests(TestCase):
    """``scored_at`` records when a Media row's score was last written (#1280)."""

    def setUp(self):
        """Create a user and a movie item."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="27205",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Inception",
            image="http://example.com/image.jpg",
        )

    def _movie(self, **kwargs):
        return Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
            **kwargs,
        )

    def _age(self, movie):
        """Push the stored timestamp into the past so a restamp is visible."""
        Movie.objects.filter(pk=movie.pk).update(scored_at=OLD)
        return Movie.objects.get(pk=movie.pk)

    def test_unscored_entry_has_no_timestamp(self):
        """A row created without a score stays null."""
        movie = self._movie()
        movie.notes = "edited"
        movie.save()

        movie.refresh_from_db()
        self.assertIsNone(movie.scored_at)

    def test_create_with_score_is_stamped(self):
        """A row created with a score gets a timestamp."""
        movie = self._movie(score=Decimal("8.0"))

        movie.refresh_from_db()
        self.assertIsNotNone(movie.scored_at)

    def test_create_keeps_supplied_timestamp(self):
        """A caller that knows when the rating was given keeps that time."""
        movie = self._movie(score=Decimal("8.0"), scored_at=OLD)

        movie.refresh_from_db()
        self.assertEqual(movie.scored_at, OLD)

    def test_bulk_create_with_score_is_stamped(self):
        """Importers insert through bulk_create; the stamp still applies."""
        Movie.objects.bulk_create(
            [Movie(item=self.item, user=self.user, score=Decimal("7.5"))],
        )

        self.assertIsNotNone(Movie.objects.get(item=self.item).scored_at)

    def test_changing_score_restamps(self):
        """Setting a different score moves the timestamp forward."""
        movie = self._age(self._movie(score=Decimal("8.0")))
        movie.score = Decimal("9.0")
        movie.save()

        movie.refresh_from_db()
        self.assertGreater(movie.scored_at, OLD)

    def test_update_fields_score_persists_timestamp(self):
        """Webhooks save with update_fields=["score"]; the stamp is written too."""
        movie = self._age(self._movie(score=Decimal("8.0")))
        movie.score = Decimal("6.0")
        movie.save(update_fields=["score"])

        movie.refresh_from_db()
        self.assertGreater(movie.scored_at, OLD)

    def test_clearing_score_restamps(self):
        """Removing a rating is a rating change a sync client must see."""
        movie = self._age(self._movie(score=Decimal("8.0")))
        movie.score = None
        movie.save()

        movie.refresh_from_db()
        self.assertGreater(movie.scored_at, OLD)

    def test_unrelated_save_keeps_timestamp(self):
        """Saving other fields, or the same score, leaves the timestamp alone."""
        movie = self._age(self._movie(score=Decimal("8.0")))
        movie.notes = "edited"
        movie.score = Decimal("8.0")
        movie.save()

        movie.refresh_from_db()
        self.assertEqual(movie.scored_at, OLD)

    def test_save_with_score_deferred_keeps_timestamp(self):
        """A row loaded without its score cannot tell whether it changed."""
        movie = self._age(self._movie(score=Decimal("8.0")))
        partial = Movie.objects.only("id", "notes", "scored_at").get(pk=movie.pk)
        partial.notes = "edited"
        partial.save()

        movie.refresh_from_db()
        self.assertEqual(movie.scored_at, OLD)


class EpisodeScoredAtTests(TestCase):
    """Episode plays carry the same ``scored_at`` rule as Media rows."""

    def setUp(self):
        """Create a user, a season and one episode item."""
        metadata = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={},
        )
        metadata.start()
        self.addCleanup(metadata.stop)
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )

    def _play(self, **kwargs):
        return Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=datetime(2024, 1, 1, tzinfo=UTC),
            **kwargs,
        )

    def test_replay_inherits_rating_timestamp(self):
        """A replay copies the rating and keeps when it was given."""
        first = self._play(score=Decimal("8.0"))
        Episode.objects.filter(pk=first.pk).update(scored_at=OLD)

        replay = self._play()

        replay.refresh_from_db()
        self.assertEqual(replay.score, Decimal("8.0"))
        self.assertEqual(replay.scored_at, OLD)

    def test_set_episode_score_stamps_every_play(self):
        """The shared rating writer bypasses save(), so it stamps directly."""
        self._play()
        self._play()
        plays = Episode.objects.filter(item=self.episode_item)

        set_episode_score(plays, Decimal("7.0"), self.user.id)

        for score, scored_at in plays.values_list("score", "scored_at"):
            self.assertEqual(score, Decimal("7.0"))
            self.assertIsNotNone(scored_at)

    def test_set_episode_score_same_score_keeps_timestamp(self):
        """A retried rating request is not a new rating event."""
        self._play(score=Decimal("7.0"))
        plays = Episode.objects.filter(item=self.episode_item)
        plays.update(scored_at=OLD)

        set_episode_score(plays, Decimal("7.0"), self.user.id)

        self.assertEqual(plays.get().scored_at, OLD)

    def test_clearing_unrated_episode_keeps_timestamp(self):
        """Clearing an episode that has no rating is a no-op."""
        self._play()
        plays = Episode.objects.filter(item=self.episode_item)

        set_episode_score(plays, None, self.user.id)

        self.assertIsNone(plays.get().scored_at)
