"""Discover reads a show's last-watched date without walking its episodes."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app.discover.profile import compute_taste_profile, preload_tv_activity_dates
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)


class TvActivityDatesTests(TestCase):
    def setUp(self):
        for target in (
            "app.signals._handle_media_cache_change",
            "app.signals._sync_owner_smart_lists_for_items",
            "app.signals._schedule_credits_backfill_if_needed",
            "app.models.Item.fetch_releases",
        ):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user(username="tv", password="x")
        self.now = timezone.now()

    def show(self, media_id, season_dates):
        """Create a show with one season per list of episode end dates."""
        show_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title=f"Show {media_id}",
            genres=["Drama"],
        )
        show = TV.objects.create(
            user=self.user, item=show_item, status=Status.COMPLETED.value
        )
        for number, dates in season_dates.items():
            self.season(show, media_id, number, dates)
        return show

    def season(self, show, media_id, number, dates, *, archived=False):
        season_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title=f"Show {media_id}",
            season_number=number,
        )
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=show,
            order_archived=archived,
        )
        for index, end_date in enumerate(dates, start=1):
            episode_item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Show {media_id}",
                season_number=number,
                episode_number=index,
            )
            Episode.objects.create(
                item=episode_item, related_season=season, end_date=end_date
            )
        return season

    def days_ago(self, days):
        return self.now - timedelta(days=days)

    def test_preloaded_dates_match_what_the_model_computes(self):
        watched = self.show(
            "1",
            {
                1: [self.days_ago(30), self.days_ago(20)],
                2: [self.days_ago(10), None],
                0: [self.days_ago(5)],
            },
        )
        untouched = self.show("2", {1: [None, None]})
        no_seasons = self.show("3", {})
        archived = self.show("4", {1: [self.days_ago(40)]})
        self.season(archived, "4", 2, [self.days_ago(1)], archived=True)

        entries = list(TV.objects.filter(user=self.user).order_by("id"))
        preload_tv_activity_dates(entries)
        preloaded = {e.id: (e.end_date, e.progressed_at) for e in entries}

        for show in (watched, untouched, no_seasons, archived):
            fresh = TV.objects.get(id=show.id)
            self.assertEqual(
                preloaded[show.id], (fresh.end_date, fresh.progressed_at), show.item
            )
        self.assertEqual(preloaded[watched.id][0], self.days_ago(5))
        self.assertIsNone(preloaded[untouched.id][0])
        self.assertEqual(preloaded[archived.id][0], self.days_ago(40))

    def test_dates_cost_one_query_however_many_shows(self):
        for index in range(5):
            self.show(str(index), {1: [self.days_ago(index + 1)]})
        entries = list(TV.objects.filter(user=self.user))

        with CaptureQueriesContext(connection) as queries:
            preload_tv_activity_dates(entries)
            [(entry.end_date, entry.progressed_at) for entry in entries]

        self.assertEqual(len(queries), 1)

    def test_shows_are_read_in_batches_and_never_twice(self):
        for index in range(5):
            self.show(str(index), {1: [self.days_ago(index + 1)]})
        entries = list(TV.objects.filter(user=self.user))

        with (
            patch("app.discover.profile.TV_ACTIVITY_BATCH_SIZE", 2),
            CaptureQueriesContext(connection) as queries,
        ):
            preload_tv_activity_dates(entries)
            preload_tv_activity_dates(entries)

        self.assertEqual(len(queries), 3)
        for query in queries.captured_queries:
            self.assertIn("IN (", query["sql"])

    def test_other_entries_and_other_users_are_left_alone(self):
        other = get_user_model().objects.create_user(username="other", password="x")
        mine = self.show("1", {1: [self.days_ago(3)]})
        other_item = Item.objects.create(
            media_id="9",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Other",
        )
        TV.objects.create(user=other, item=other_item)

        entries = list(TV.objects.filter(user=self.user))
        preload_tv_activity_dates(entries)
        preload_tv_activity_dates([])
        preload_tv_activity_dates([object()])

        self.assertEqual(entries[0].end_date, self.days_ago(3))
        self.assertEqual(entries[0].id, mine.id)

    def test_profile_queries_do_not_grow_with_the_number_of_shows(self):
        def profile_queries():
            with CaptureQueriesContext(connection) as queries:
                compute_taste_profile(self.user, MediaTypes.TV.value)
            return len(queries)

        self.show("1", {1: [self.days_ago(3)], 2: [self.days_ago(2)]})
        few = profile_queries()
        for index in range(2, 8):
            self.show(str(index), {1: [self.days_ago(index)], 2: [self.days_ago(1)]})

        self.assertEqual(profile_queries(), few)
