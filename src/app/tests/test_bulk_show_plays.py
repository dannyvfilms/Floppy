from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.services import bulk_show_plays
from app.services.metadata_resolution import MetadataResolutionResult
from app.tests.views.test_episode_bulk_save import (
    _season_episode,
    _tv_with_seasons_payload,
)

SEASONS = [
    {
        "season_number": 0,
        "season_title": "Specials",
        "episodes": [_season_episode(1, air_date="2023-12-01")],
    },
    {
        "season_number": 1,
        "season_title": "Season 1",
        "episodes": [
            _season_episode(1, air_date="2024-01-01"),
            _season_episode(2, air_date="2024-01-08"),
            _season_episode(3, air_date=None),
        ],
    },
    {
        "season_number": 2,
        "season_title": "Season 2",
        "episodes": [
            _season_episode(1, air_date="2024-02-01"),
            _season_episode(2, air_date="2999-01-01"),
        ],
    },
]


def _resolution(media_id="100"):
    return MetadataResolutionResult(
        display_provider=Sources.TMDB.value,
        identity_provider=Sources.TMDB.value,
        mapping_status="identity",
        header_metadata={},
        grouped_preview=None,
        provider_media_id=media_id,
    )


@override_settings(TRACK_TIME=True)
class BulkShowPlaysTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("bulk-plays", password="x")
        self.client.login(username="bulk-plays", password="x")
        self.show = self._show("100", "Show One")
        patches = [
            patch(
                "app.services.bulk_show_plays.services.get_media_metadata",
                side_effect=lambda _route, media_id, source, *_a: _tv_with_seasons_payload(
                    media_id,
                    source,
                    title=f"Show {media_id}",
                    seasons=SEASONS,
                ),
            ),
            patch(
                "app.services.bulk_show_plays.metadata_resolution."
                "resolve_detail_metadata",
                side_effect=lambda *a, **k: _resolution(k["media_id"]),
            ),
            patch("app.tasks.enqueue_credits_backfill_items"),
        ]
        for started in patches:
            started.start()
            self.addCleanup(started.stop)

    def _show(self, media_id, title, status=Status.PLANNING.value):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title=title,
        )
        TV.objects.create(item=item, user=self.user, status=status)
        return item

    def _post(self, item_ids, *, dry_run=False, **options):
        data = {
            "item_ids": [str(i) for i in item_ids],
            "scope": "aired",
            "existing": "skip",
            "date_mode": "air_date",
            "dry_run": "1" if dry_run else "0",
            **options,
        }
        return self.client.post(reverse("bulk_show_plays_start"), data)

    def _result(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        operation_id = response.json()["operation_id"]
        status = self.client.get(
            reverse("bulk_show_plays_status", args=[operation_id]),
        )
        self.assertEqual(status.status_code, 200)
        return status.json()

    def _plays(self):
        return Episode.objects.filter(related_season__user=self.user)

    def test_preview_counts_and_writes_nothing(self):
        result = self._result(self._post([self.show.id], dry_run=True))
        self.assertEqual(result["state"], "done")
        # Aired, non-special, dated: S1E1, S1E2, S2E1.
        self.assertEqual(result["totals"]["plays"], 3)
        self.assertEqual(result["totals"]["unaired"], 1)
        self.assertEqual(result["totals"]["no_date"], 1)
        self.assertFalse(self._plays().exists())

    def test_adds_plays_at_air_dates_and_skips_specials_unaired_undated(self):
        result = self._result(self._post([self.show.id]))
        self.assertEqual(result["totals"]["plays"], 3)
        plays = {
            (p.item.season_number, p.item.episode_number): p.end_date.date().isoformat()
            for p in self._plays().select_related("item")
        }
        self.assertEqual(
            plays,
            {(1, 1): "2024-01-01", (1, 2): "2024-01-08", (2, 1): "2024-02-01"},
        )

    def test_rerun_adds_nothing(self):
        self._result(self._post([self.show.id]))
        again = self._result(self._post([self.show.id]))
        self.assertEqual(again["totals"]["plays"], 0)
        self.assertEqual(again["totals"]["existing"], 3)
        self.assertEqual(self._plays().count(), 3)

    def test_add_another_mode_records_a_second_play(self):
        self._result(self._post([self.show.id]))
        self._result(self._post([self.show.id], existing="add"))
        self.assertEqual(self._plays().count(), 6)

    def test_one_date_mode_uses_that_day(self):
        self._result(self._post([self.show.id], date_mode="one_date", date="2025-03-05"))
        days = {p.end_date.date().isoformat() for p in self._plays()}
        self.assertEqual(days, {"2025-03-05"})
        self.assertEqual(self._plays().count(), 3)

    def test_range_mode_stays_inside_range(self):
        self._result(
            self._post(
                [self.show.id],
                date_mode="range",
                start_date="2025-01-01",
                end_date="2025-01-10",
            ),
        )
        dates = sorted(p.end_date.date().isoformat() for p in self._plays())
        self.assertGreaterEqual(dates[0], "2025-01-01")
        self.assertLessEqual(dates[-1], "2025-01-10")

    def test_season_range_can_include_specials(self):
        result = self._result(
            self._post([self.show.id], scope="seasons", season_from="0", season_to="0"),
        )
        self.assertEqual(result["totals"]["plays"], 1)
        self.assertEqual(self._plays().get().item.season_number, 0)

    def test_watched_scope_uses_completed_show_or_completed_seasons_only(self):
        completed = self._show("200", "Done Show", Status.COMPLETED.value)
        partial = self._show("300", "Partial Show")
        season_item = Item.objects.create(
            media_id="300",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Partial Show",
        )
        Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=TV.objects.get(item=partial),
            status=Status.COMPLETED.value,
        )
        untouched = self._show("400", "Not Watched")

        result = self._result(
            self._post(
                [completed.id, partial.id, untouched.id],
                dry_run=True,
                scope="watched",
            ),
        )
        # Completed show: 3 plays. Partial: season 1 only (2 dated). Third: none.
        self.assertEqual(result["totals"]["plays"], 3 + 2)
        self.assertEqual(result["totals"]["shows"], 2)

    def test_non_tv_item_is_reported_not_written(self):
        movie = Item.objects.create(
            media_id="9",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
        )
        result = self._result(self._post([self.show.id, movie.id]))
        self.assertEqual(result["problem_count"], 1)
        self.assertEqual(result["problems"][0]["title"], "A Movie")
        self.assertEqual(result["totals"]["plays"], 3)

    def test_one_failing_show_does_not_stop_the_others(self):
        other = self._show("500", "Other")
        real = bulk_show_plays.build_domain

        def flaky(user, item, route):
            if item.media_id == "100":
                raise RuntimeError("provider down")
            return real(user, item, route)

        with patch("app.services.bulk_show_plays.build_domain", side_effect=flaky):
            result = self._result(self._post([self.show.id, other.id]))
        self.assertEqual(result["problem_count"], 1)
        self.assertEqual(result["problems"][0]["state"], "failed")
        self.assertEqual(result["totals"]["plays"], 3)

    def test_large_selection_completes(self):
        ids = [self._show(str(1000 + n), f"Bulk {n}").id for n in range(25)]
        result = self._result(self._post(ids))
        self.assertEqual(result["done"], 25)
        self.assertEqual(result["totals"]["shows"], 25)
        self.assertEqual(self._plays().count(), 75)

    def test_statistics_days_are_marked_for_every_air_date(self):
        with patch(
            "app.services.bulk_episode_tracking.flush_media_change_side_effects",
        ) as flush:
            self._result(self._post([self.show.id]))
        days = flush.call_args.kwargs["statistics_day_values"]
        self.assertEqual(len(days), 3)

    def test_second_run_is_refused_while_one_is_running(self):
        cache.set(bulk_show_plays.lock_key(self.user.id), "other", 60)
        response = self._post([self.show.id])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self._plays().exists())

    def test_preview_is_allowed_while_a_run_is_locked(self):
        cache.set(bulk_show_plays.lock_key(self.user.id), "other", 60)
        self.assertEqual(self._post([self.show.id], dry_run=True).status_code, 200)

    def test_lock_is_released_after_a_run(self):
        self._result(self._post([self.show.id]))
        self.assertIsNone(cache.get(bulk_show_plays.lock_key(self.user.id)))

    def test_validation_errors(self):
        cases = [
            {"scope": "everything"},
            {"existing": "maybe"},
            {"date_mode": "whenever"},
            {"scope": "seasons"},
            {"scope": "seasons", "season_from": "3", "season_to": "1"},
            {"date_mode": "one_date"},
            {"date_mode": "one_date", "date": "2999-01-01"},
            {"date_mode": "range", "start_date": "2025-02-01", "end_date": "2025-01-01"},
        ]
        for case in cases:
            with self.subTest(case=case):
                response = self._post([self.show.id], **case)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(reverse("bulk_show_plays_start")).status_code, 400)

    def test_selection_cap(self):
        with patch.object(bulk_show_plays, "MAX_SHOWS", 2):
            response = self._post([1, 2, 3])
        self.assertEqual(response.status_code, 400)

    def test_status_is_private_to_the_user(self):
        operation = self._post([self.show.id], dry_run=True).json()["operation_id"]
        get_user_model().objects.create_user("other", password="x")
        self.client.login(username="other", password="x")
        response = self.client.get(
            reverse("bulk_show_plays_status", args=[operation]),
        )
        self.assertEqual(response.status_code, 404)

    def test_non_completed_status_update_adds_no_plays(self):
        response = self.client.post(
            reverse("bulk_status_update"),
            {"item_ids": [str(self.show.id)], "status": Status.PAUSED.value},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self._plays().exists())
