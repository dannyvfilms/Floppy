"""Retraction must revert state without destroying history.

The behaviour being replaced deleted every row matching a title, so a single
"mark unplayed" in a media server could remove years of rewatches. These tests
pin the opposite: after a retraction the earlier plays are still there.
"""

import datetime
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    Book,
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
)
from app.services.unwatch import retract_watch


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day):
    return datetime.datetime(2026, 6, day, 12, tzinfo=datetime.UTC)


class MovieRetractionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item, _ = Item.objects.get_or_create(
            media_id="4000",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )

    def test_a_rewatched_movie_keeps_every_play(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        movie.watch(_dt(1))
        movie.watch(_dt(5))
        movie.watch(_dt(9))

        result = retract_watch(self.user, self.item)

        self.assertEqual(MoviePlay.objects.filter(movie=movie).count(), 3)
        self.assertEqual(result.preserved_plays, 3)
        self.assertEqual(result.deleted_plays, 0)
        self.assertFalse(result.attributable)

    def test_the_tracking_row_survives_and_reverts(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        retract_watch(self.user, self.item)

        movie.refresh_from_db()
        self.assertEqual(Movie.objects.count(), 1)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertIsNone(movie.end_date)

    def test_an_attributable_play_is_removed_precisely(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        movie.watch(_dt(1))
        movie.watch(_dt(5), external_id="jellyfin-evt-9")

        result = retract_watch(self.user, self.item, external_id="jellyfin-evt-9")

        self.assertEqual(result.deleted_plays, 1)
        self.assertTrue(result.attributable)
        remaining = MoviePlay.objects.filter(movie=movie)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.get().end_date, _dt(1))

    def test_retracting_an_untracked_movie_is_a_no_op(self):
        result = retract_watch(self.user, self.item)

        self.assertEqual(result.rows_reverted, 0)
        self.assertEqual(result.deleted_plays, 0)

    def test_another_users_row_is_untouched(self):
        other = get_user_model().objects.create_user(username="other")
        Movie.objects.create(
            item=self.item,
            user=other,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        retract_watch(self.user, self.item)

        self.assertEqual(
            Movie.objects.get(user=other).status,
            Status.COMPLETED.value,
        )


class EpisodeRetractionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        tv_item, _ = Item.objects.get_or_create(
            media_id="4001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Show"},
        )
        season_item, _ = Item.objects.get_or_create(
            media_id="4001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Show"},
        )
        self.episode_item, _ = Item.objects.get_or_create(
            media_id="4001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            defaults={"title": "Show"},
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

    def _watch(self, day):
        return Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=_dt(day),
        )

    def test_only_the_latest_play_is_retracted(self):
        """The failure this prevents: three rewatches, one click, all gone."""
        self._watch(1)
        self._watch(5)
        self._watch(9)

        retract_watch(self.user, self.episode_item)

        remaining = Episode.objects.filter(item=self.episode_item)
        self.assertEqual(remaining.count(), 2)
        self.assertEqual(
            sorted(row.end_date for row in remaining),
            [_dt(1), _dt(5)],
        )

    def test_an_attributable_play_is_removed_precisely(self):
        self._watch(1)
        target = self._watch(5)
        target.watch_operation_id = "3f8a1c2e-0000-4000-8000-000000000001"
        target.save(update_fields=["watch_operation_id"])
        self._watch(9)

        result = retract_watch(
            self.user,
            self.episode_item,
            watch_operation_id="3f8a1c2e-0000-4000-8000-000000000001",
        )

        self.assertTrue(result.attributable)
        remaining = Episode.objects.filter(item=self.episode_item)
        self.assertEqual(remaining.count(), 2)
        self.assertEqual(
            sorted(row.end_date for row in remaining),
            [_dt(1), _dt(9)],
        )

    def test_retracting_an_unwatched_episode_is_a_no_op(self):
        result = retract_watch(self.user, self.episode_item)

        self.assertEqual(result.deleted_plays, 0)


class GroupedAnimeRetractionTests(TestCase):
    """The same episode can exist in two library buckets; retract only one."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")

    def _bucket(self, library_media_type, media_id="4002"):
        tv_item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=library_media_type,
            defaults={"title": "Show"},
        )
        season_item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=library_media_type,
            season_number=1,
            defaults={"title": "Show"},
        )
        episode_item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=library_media_type,
            season_number=1,
            episode_number=1,
            defaults={"title": "Show"},
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=_dt(1),
        )
        return episode_item

    def test_retracting_one_bucket_leaves_the_other_alone(self):
        tv_episode = self._bucket(MediaTypes.TV.value)
        anime_episode = self._bucket(MediaTypes.ANIME.value)

        retract_watch(self.user, anime_episode)

        self.assertTrue(Episode.objects.filter(item=tv_episode).exists())
        self.assertFalse(Episode.objects.filter(item=anime_episode).exists())


class FlatMediaRetractionTests(TestCase):
    def test_a_completed_book_reverts_without_being_deleted(self):
        user = get_user_model().objects.create_user(username="owner")
        item, _ = Item.objects.get_or_create(
            media_id="4003",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            defaults={"title": "Book"},
        )
        Book.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        result = retract_watch(user, item)

        self.assertEqual(result.rows_reverted, 1)
        book = Book.objects.get()
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
