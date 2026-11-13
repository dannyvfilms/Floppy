"""Repairing missing History days must not probe every media family per day."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import history_cache_day_builder as builder
from app.models import Game, Item, MediaTypes, Movie, Sources, Status


class MissingDayRepairTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="missing-days", password="12345",
        )
        base = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        cls.first = (base - timedelta(days=20)).date()
        for offset in range(0, 20, 2):
            item = Item.objects.create(
                media_id=f"m{offset}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {offset}",
                image="http://example.com/m.jpg",
            )
            Movie.objects.create(
                item=item,
                user=cls.user,
                status=Status.COMPLETED.value,
                end_date=base - timedelta(days=offset),
            )
        game_item = Item.objects.create(
            media_id="g1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Spanning Game",
            image="http://example.com/g.jpg",
        )
        Game.objects.create(
            item=game_item,
            user=cls.user,
            status=Status.COMPLETED.value,
            progress=300,
            start_date=base - timedelta(days=15),
            end_date=base - timedelta(days=11),
        )
        cls.day_keys = [
            (cls.first + timedelta(days=i)).strftime("%Y%m%d") for i in range(21)
        ]

    def setUp(self):
        cache.clear()

    def test_prefilter_matches_full_build_and_bounds_queries(self):
        for style in ("sessions", "repeats"):
            with self.subTest(style=style):
                with CaptureQueriesContext(connection) as prefilter:
                    by_day = builder.history_media_types_by_day(
                        self.user, self.day_keys, style,
                    )
                self.assertLessEqual(len(prefilter), 12)
                full_queries = 0
                narrowed_queries = 0
                for key in self.day_keys:
                    with CaptureQueriesContext(connection) as full:
                        expected = builder.build_history_day(
                            self.user, key, style,
                        )
                    with CaptureQueriesContext(connection) as narrowed:
                        actual = builder.build_history_day(
                            self.user, key, style, media_types=by_day[key],
                        )
                    self.assertEqual(expected, actual)
                    full_queries += len(full)
                    narrowed_queries += len(narrowed)
                self.assertLess(narrowed_queries + len(prefilter), full_queries)
