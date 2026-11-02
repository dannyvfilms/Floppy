"""A recurring import that changes one row refreshes only that row's days.

The Pocket Casts poll runs every two hours. Each time it added a single podcast
it dropped every cached History day and marked every Statistics day dirty, and
rebuilding thousands of days outlasted the gap to the next poll, so the caches
never settled.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache, statistics_sync
from app.models import (
    Item,
    MediaTypes,
    Podcast,
    Sources,
    StatisticsDirtyDay,
    StatisticsSyncState,
    Status,
)
from integrations.imports import helpers
from integrations.tasks import _media_imports


def _new_podcast(user, media_id, end_date):
    item = Item.objects.create(
        media_id=media_id,
        source=Sources.POCKETCASTS.value,
        media_type=MediaTypes.PODCAST.value,
        title=f"Episode {media_id}",
        image="https://example.com/ep.jpg",
    )
    return Podcast(
        user=user,
        item=item,
        status=Status.COMPLETED.value,
        progress=30,
        end_date=end_date,
    )


class DayScopedImportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="listener", password="pass"
        )
        statistics_sync.mark_aggregate(self.user.id, reason="setup")
        StatisticsSyncState.objects.filter(user=self.user).update(
            full_sweep_requested_at=None
        )
        self.finished = timezone.now() - timedelta(days=3)
        self.other_day = history_cache.history_day_key(
            timezone.now() - timedelta(days=40)
        )
        self.other_day_key = history_cache._day_cache_key(
            self.user.id, "repeats", self.other_day
        )
        cache.set(self.other_day_key, {"entries": []}, 3600)

    def importer(self, rows):
        def run(identifier, user, mode, **kwargs):
            helpers.bulk_create_media({MediaTypes.PODCAST.value: rows}, user)
            return {MediaTypes.PODCAST.value: len(rows)}, ""

        return run

    def run_import(self, importer, scoped):
        scope = (importer,) if scoped else ()
        with (
            patch.object(_media_imports, "DAY_SCOPED_IMPORTERS", scope),
            patch.object(_media_imports.events.tasks.reload_calendar, "delay"),
            patch("app.statistics_cache.invalidate_all_statistics_days") as stats_all,
            patch("app.history_cache.invalidate_history_cache") as history_all,
        ):
            _media_imports.import_media(importer, None, self.user.id, "new")
        return history_all, stats_all

    def test_scoped_import_marks_only_the_days_it_wrote(self):
        importer = self.importer([_new_podcast(self.user, "a", self.finished)])

        history_all, stats_all = self.run_import(importer, scoped=True)

        history_all.assert_not_called()
        stats_all.assert_not_called()
        dirty = set(
            StatisticsDirtyDay.objects.filter(user=self.user).values_list(
                "day", flat=True
            )
        )
        self.assertEqual(dirty, {timezone.localtime(self.finished).date()})
        self.assertIsNone(
            StatisticsSyncState.objects.get(user=self.user).full_sweep_requested_at
        )
        self.assertIsNotNone(cache.get(self.other_day_key))

    def test_scoped_import_of_undated_rows_marks_the_aggregate_only(self):
        generation = StatisticsSyncState.objects.get(user=self.user).generation
        importer = self.importer([_new_podcast(self.user, "b", None)])

        self.run_import(importer, scoped=True)

        self.assertFalse(StatisticsDirtyDay.objects.filter(user=self.user).exists())
        state = StatisticsSyncState.objects.get(user=self.user)
        self.assertGreater(state.generation, generation)
        self.assertIsNone(state.full_sweep_requested_at)

    def test_scoped_import_that_only_saved_through_the_orm_keeps_no_sweep(self):
        def run(identifier, user, mode, **kwargs):
            statistics_sync.mark_days(user.id, [self.finished], reason="orm_save")
            return {}, ""

        self.run_import(run, scoped=True)

        self.assertIsNone(
            StatisticsSyncState.objects.get(user=self.user).full_sweep_requested_at
        )

    def test_unscoped_importer_still_drops_every_day(self):
        importer = self.importer([_new_podcast(self.user, "c", self.finished)])

        history_all, stats_all = self.run_import(importer, scoped=False)

        history_all.assert_called_once_with(self.user.id, force=True)
        stats_all.assert_called_once_with(self.user.id, reason="media_import")

    def test_failed_scoped_import_keeps_the_sweep_for_recovery(self):
        def run(identifier, user, mode, **kwargs):
            raise ValueError("provider down")

        with self.assertRaises(ValueError):
            self.run_import(run, scoped=True)

        self.assertIsNotNone(
            StatisticsSyncState.objects.get(user=self.user).full_sweep_requested_at
        )

    def test_publish_covers_every_day_a_ranged_row_spans(self):
        podcast = _new_podcast(self.user, "d", self.finished)
        podcast.start_date = self.finished - timedelta(days=2)

        helpers.publish_bulk_rows(self.user.id, [podcast])

        self.assertEqual(
            StatisticsDirtyDay.objects.filter(user=self.user).count(),
            3,
        )

    def test_a_mix_of_dated_and_undated_rows_marks_days_and_the_aggregate(self):
        dated = _new_podcast(self.user, "e", self.finished)
        undated = _new_podcast(self.user, "f", None)
        generation = StatisticsSyncState.objects.get(user=self.user).generation

        helpers.publish_bulk_rows(self.user.id, [dated, undated])

        self.assertEqual(StatisticsDirtyDay.objects.filter(user=self.user).count(), 1)
        self.assertGreater(
            StatisticsSyncState.objects.get(user=self.user).generation, generation
        )

    def test_a_noted_full_refresh_drops_every_day(self):
        def run(identifier, user, mode, **kwargs):
            helpers.note_full_refresh()
            return {MediaTypes.PODCAST.value: 1}, ""

        history_all, stats_all = self.run_import(run, scoped=True)

        history_all.assert_called_once_with(self.user.id, force=True)
        stats_all.assert_called_once_with(self.user.id, reason="media_import")
        self.assertIsNotNone(
            StatisticsSyncState.objects.get(user=self.user).full_sweep_requested_at
        )
