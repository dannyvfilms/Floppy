"""Backfilling an existing library must be silent and repeatable.

The property that matters most is negative: projecting a library that predates
the feature must not emit a single change, because changes are what later get
delivered to providers. A backfill that emitted them would push a user's whole
library outward on upgrade.
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
    Season,
    Sources,
    Status,
    WatchState,
    WatchStateChange,
    WatchStateSequence,
)
from app.services.watch_state import suspend_projection
from app.tasks_watch_state import backfill_watch_state


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day):
    return datetime.datetime(2026, 3, day, 12, tzinfo=datetime.UTC)


class BackfillTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        # suspend_projection reproduces a library tracked before the projection
        # existed: rows in the legacy stores, no WatchState rows at all.
        with suspend_projection():
            self.movie_item = self._build_movie()
            self.episode_item = self._build_episode()
            self.book_item = self._build_book()

        self.assertEqual(WatchState.objects.count(), 0)

    def _build_movie(self):
        item, _ = Item.objects.get_or_create(
            media_id="1000",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Film"},
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )
        return item

    def _build_episode(self):
        tv_item, _ = Item.objects.get_or_create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Show"},
        )
        season_item, _ = Item.objects.get_or_create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Show"},
        )
        episode_item, _ = Item.objects.get_or_create(
            media_id="1001",
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
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=_dt(2),
        )
        return episode_item

    def _build_book(self):
        item, _ = Item.objects.get_or_create(
            media_id="1002",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            defaults={"title": "Book"},
        )
        Book.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(3),
        )
        return item

    def test_backfill_projects_every_tracked_type(self):
        backfill_watch_state(user_id=self.user.id)

        states = {
            state.item_id: state
            for state in WatchState.objects.filter(user=self.user)
        }
        self.assertEqual(len(states), 3)
        for item in (self.movie_item, self.episode_item, self.book_item):
            self.assertTrue(states[item.pk].watched, item.media_type)

    def test_backfill_emits_no_changes(self):
        backfill_watch_state(user_id=self.user.id)

        self.assertEqual(WatchStateChange.objects.count(), 0)

    def test_backfill_emits_no_changes_even_when_syncing_is_on(self):
        """A user who already synchronizes must not have their library replayed.

        Backfill describes rows that were already there; treating them as new
        decisions would deliver the whole library outward.
        """
        WatchStateSequence.objects.update_or_create(
            user=self.user,
            defaults={"emit_changes": True},
        )

        backfill_watch_state(user_id=self.user.id)

        self.assertEqual(WatchStateChange.objects.count(), 0)
        self.assertEqual(WatchState.objects.filter(user=self.user).count(), 3)

    def test_backfill_is_idempotent(self):
        backfill_watch_state(user_id=self.user.id)
        digests = sorted(
            WatchState.objects.values_list("item_id", "state_digest"),
        )

        backfill_watch_state(user_id=self.user.id)

        self.assertEqual(WatchState.objects.count(), 3)
        self.assertEqual(
            sorted(WatchState.objects.values_list("item_id", "state_digest")),
            digests,
        )

    def test_backfill_does_not_reach_another_users_library(self):
        other = get_user_model().objects.create_user(username="other")

        backfill_watch_state(user_id=other.id)

        self.assertEqual(WatchState.objects.count(), 0)

    def test_containers_are_not_projected(self):
        backfill_watch_state(user_id=self.user.id)

        container_types = {MediaTypes.TV.value, MediaTypes.SEASON.value}
        projected_types = {
            state.item.media_type for state in WatchState.objects.select_related("item")
        }
        self.assertFalse(projected_types & container_types)
