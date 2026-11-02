"""The day-key collector costs a fixed number of queries per batch, not per item."""

from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import history_cache
from app.models import (
    TV,
    Anime,
    Episode,
    Game,
    Item,
    MediaTypes,
    MetadataBackfillField,
    Movie,
    Season,
    Sources,
    Status,
)
from app.tasks_backfill_state import _collect_backfill_day_keys

PER_TYPE = 6


def _item(media_type, n, **extra):
    return Item.objects.create(
        media_id=f"{media_type}-{n}",
        source=Sources.TMDB.value,
        media_type=media_type,
        title=f"{media_type} {n}",
        **extra,
    )


class CollectBackfillDayKeysTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.users = [users.create_user(username=f"u{i}") for i in range(2)]
        self.base = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.expected = defaultdict(set)
        self.items = []
        self.items_by_type = defaultdict(list)

    def _expect(self, user, when):
        self.expected[user.id].add(history_cache.history_day_key(when))

    def _build(self):
        for n in range(PER_TYPE):
            when = self.base - timedelta(days=n)
            for media_type, model in (
                (MediaTypes.MOVIE.value, Movie),
                (MediaTypes.GAME.value, Game),
                (MediaTypes.ANIME.value, Anime),
            ):
                item = _item(media_type, n)
                self.items.append(item)
                self.items_by_type[media_type].append(item)
                for user in self.users[: 1 + n % 2]:
                    model.objects.create(
                        item=item,
                        user=user,
                        status=Status.COMPLETED.value,
                        end_date=when,
                    )
                    self._expect(user, when)
            tv_item = _item(MediaTypes.TV.value, n)
            season_item = _item(MediaTypes.SEASON.value, n, season_number=1)
            episode_item = _item(
                MediaTypes.EPISODE.value, n, season_number=1, episode_number=1
            )
            self.items += [tv_item, season_item]
            user = self.users[n % 2]
            tv = TV.objects.create(
                item=tv_item, user=user, status=Status.IN_PROGRESS.value
            )
            season = Season.objects.create(
                item=season_item,
                user=user,
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            Episode.objects.create(
                item=episode_item, related_season=season, end_date=when
            )
            self._expect(user, when)

    def test_credits_batch_returns_every_owner_day(self):
        self._build()
        with CaptureQueriesContext(connection) as queries:
            result = _collect_backfill_day_keys(
                self.items, MetadataBackfillField.CREDITS
            )
        self.assertEqual({u: set(d) for u, d in result.items()}, dict(self.expected))
        # movie, game, anime, tv episodes, season episodes: one query each.
        self.assertLessEqual(len(queries), 5)

    def test_genres_skip_anime(self):
        self._build()
        result = _collect_backfill_day_keys(self.items, MetadataBackfillField.GENRES)
        anime_days = {
            history_cache.history_day_key(self.base - timedelta(days=n))
            for n in range(PER_TYPE)
        }
        self.assertTrue(anime_days & set().union(*result.values()))
        with CaptureQueriesContext(connection) as queries:
            _collect_backfill_day_keys(
                self.items_by_type[MediaTypes.ANIME.value],
                MetadataBackfillField.GENRES,
            )
        self.assertEqual(len(queries), 0)

    def test_runtime_anime_range_expands_every_day(self):
        item = _item(MediaTypes.ANIME.value, 99)
        Anime.objects.create(
            item=item,
            user=self.users[0],
            status=Status.COMPLETED.value,
            start_date=self.base - timedelta(days=2),
            end_date=self.base,
        )
        result = _collect_backfill_day_keys([item], MetadataBackfillField.RUNTIME)
        expected = set(
            history_cache.history_day_keys_for_range(
                self.base - timedelta(days=2), self.base
            )
        )
        self.assertEqual(result[self.users[0].id], expected)
        self.assertGreater(len(expected), 1)

    def test_empty_batch_costs_nothing(self):
        with CaptureQueriesContext(connection) as queries:
            self.assertFalse(
                _collect_backfill_day_keys([], MetadataBackfillField.CREDITS)
            )
        self.assertEqual(len(queries), 0)
