"""Tests for the read-only data invariant report.

Each test builds one violation of one kind on top of a clean library and
asserts that exactly that check counts it. The clean library itself must count
nothing, and the deliberate multi-row cases (repeat viewings, grouped anime in
two filled buckets) must never be reported as faults.
"""

import json
from datetime import UTC, datetime, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import data_invariants
from app.models import (
    TV,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations.models import ImportRun, OutboundStateDelivery, SyncClientKind
from integrations.state.identity import get_or_create_binding

PLAYED = datetime(2025, 3, 1, 20, 0, tzinfo=UTC)


class DataInvariantTests(TestCase):
    """One violation of each kind is counted by its own check and no other."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="private-name", password="12345"
        )
        self.other = get_user_model().objects.create_user(
            username="someone-else", password="12345"
        )
        self.show_item = self._item(MediaTypes.TV.value, title="Secret Show Title")
        self.tv = TV.objects.create(
            user=self.user, item=self.show_item, status=Status.IN_PROGRESS.value
        )
        self.season_item = self._item(MediaTypes.SEASON.value, season=1)
        self.season = Season.objects.create(
            user=self.user,
            item=self.season_item,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_item = self._item(MediaTypes.EPISODE.value, season=1, episode=1)
        self.play = Episode.objects.create(
            item=self.episode_item, related_season=self.season, end_date=PLAYED
        )
        self.movie_item = self._item(
            MediaTypes.MOVIE.value, media_id="603", source=Sources.TMDB.value
        )
        # Repeat viewings are stored as rows: never a fault.
        for _ in range(2):
            Movie.objects.create(
                user=self.user, item=self.movie_item, status=Status.COMPLETED.value
            )

    # -- helpers ----------------------------------------------------------

    def _item(
        self,
        media_type,
        *,
        media_id="81189",
        source=Sources.TVDB.value,
        season=None,
        episode=None,
        bucket="",
        title="Item",
    ):
        return Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            library_media_type=bucket,
            season_number=season,
            episode_number=episode,
            title=title,
        )

    def _counts(self, **kwargs):
        return {
            result.name: result.count for result in data_invariants.run_checks(**kwargs)
        }

    def _nonzero(self, **kwargs):
        return {name: n for name, n in self._counts(**kwargs).items() if n}

    def _empty_bucket(self, item):
        # Bulk writes stored empty buckets in real libraries until migration
        # 0231 made the database refuse them. The checks still guard a
        # database that has not migrated, so the fixture lifts the check for
        # this test only (rolled back with the test's transaction).
        update = Item.objects.filter(pk=item.pk)
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                # Run pending foreign-key checks first: PostgreSQL refuses to
                # alter a table with deferred trigger events outstanding.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "ALTER TABLE app_item DROP CONSTRAINT IF EXISTS "
                    "app_item_library_media_type_set",
                )
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                update.update(library_media_type="")
                return
            cursor.execute("PRAGMA ignore_check_constraints = ON")
            try:
                update.update(library_media_type="")
            finally:
                cursor.execute("PRAGMA ignore_check_constraints = OFF")

    def _run(self, *args):
        out = StringIO()
        call_command("check_data_invariants", *args, stdout=out)
        return out.getvalue()

    # -- the clean library ---------------------------------------------------

    def test_clean_library_counts_nothing(self):
        self.assertEqual(self._nonzero(), {})

    def test_every_check_has_a_name_kind_and_count(self):
        results = data_invariants.run_checks(examples=3)
        self.assertEqual(len(results), len(data_invariants.CHECKS))
        self.assertEqual(len({r.name for r in results}), len(results))
        for result in results:
            self.assertIn(result.kind, data_invariants.KIND_LABELS)
            self.assertEqual(result.count, 0)
            self.assertEqual(result.examples, [])

    # -- 1. empty bucket -------------------------------------------------

    def test_item_without_bucket(self):
        self._empty_bucket(self.episode_item)
        self._empty_bucket(self.movie_item)
        result = data_invariants.items_without_bucket(examples=10)
        self.assertEqual(result.count, 2)
        self.assertEqual(result.breakdown, {"episode": 1, "movie": 1})
        self.assertEqual(result.examples, [self.movie_item.pk, self.episode_item.pk])
        self.assertTrue(result.failed)
        self.assertEqual(self._nonzero(), {"items_without_bucket": 2})

    # -- 2. identity stored twice ------------------------------------------

    def test_show_copy_with_empty_bucket(self):
        copy = self._item(MediaTypes.TV.value, bucket="anime")
        self._empty_bucket(copy)
        result = data_invariants.identity_copies_with_empty_bucket(examples=10)
        self.assertEqual(result.breakdown, {"tv": 1})
        self.assertEqual(result.examples, [self.show_item.pk])
        self.assertEqual(
            self._nonzero(),
            {"identity_copies_with_empty_bucket": 1, "items_without_bucket": 1},
        )

    def test_episode_copy_with_empty_bucket(self):
        copy = self._item(MediaTypes.EPISODE.value, season=1, episode=1, bucket="tv")
        self._empty_bucket(copy)
        result = data_invariants.identity_copies_with_empty_bucket()
        self.assertEqual(result.breakdown, {"episode": 1})

    def test_grouped_anime_in_two_filled_buckets_is_review_only(self):
        anime_show = self._item(MediaTypes.TV.value, bucket="anime")
        self._item(MediaTypes.SEASON.value, season=1, bucket="anime")
        result = data_invariants.identity_copies_in_filled_buckets(examples=10)
        self.assertEqual(result.kind, data_invariants.REVIEW)
        self.assertEqual(result.breakdown, {"tv": 1, "season": 1})
        self.assertFalse(result.failed)
        self.assertIn(self.show_item.pk, result.examples)
        self.assertNotIn(anime_show.pk, result.examples)
        self.assertEqual(self._nonzero(), {"identity_copies_in_filled_buckets": 2})

    # -- 3. plays split across copies ----------------------------------------

    def test_plays_split_across_copies(self):
        copy = self._item(MediaTypes.EPISODE.value, season=1, episode=1, bucket="tv")
        second = Episode.objects.create(
            item=copy, related_season=self.season, end_date=PLAYED + timedelta(days=2)
        )
        result = data_invariants.plays_split_across_copies(examples=10)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.examples, [self.play.pk])
        self.assertNotIn(second.pk, result.examples)
        self.assertEqual(
            self._nonzero(),
            {"plays_split_across_copies": 1, "identity_copies_in_filled_buckets": 1},
        )

    def test_rating_only_rows_are_not_plays(self):
        copy = self._item(MediaTypes.EPISODE.value, season=1, episode=1, bucket="tv")
        Episode.all_objects.create(
            item=copy, related_season=self.season, rating_only=True, score=7
        )
        self.assertEqual(data_invariants.plays_split_across_copies().count, 0)

    # -- 4. one user, two copies ---------------------------------------------

    def test_user_tracks_two_copies_of_a_show(self):
        copy = self._item(MediaTypes.TV.value, bucket="anime")
        TV.objects.create(user=self.user, item=copy, status=Status.PLANNING.value)
        self._empty_bucket(copy)
        result = data_invariants.tracked_copies_with_empty_bucket(examples=10)
        self.assertEqual(result.breakdown, {"tv": 1})
        self.assertEqual(result.examples, [f"tv:{self.tv.pk}"])
        self.assertEqual(data_invariants.tracked_copies_in_filled_buckets().count, 0)

    def test_grouped_anime_tracked_twice_is_review(self):
        copy = self._item(MediaTypes.TV.value, bucket="anime")
        TV.objects.create(user=self.user, item=copy, status=Status.PLANNING.value)
        result = data_invariants.tracked_copies_in_filled_buckets()
        self.assertEqual(result.kind, data_invariants.REVIEW)
        self.assertEqual(result.breakdown, {"tv": 1})
        self.assertEqual(data_invariants.tracked_copies_with_empty_bucket().count, 0)

    def test_two_users_on_two_copies_is_not_one_user_tracking_both(self):
        copy = self._item(MediaTypes.TV.value, bucket="anime")
        TV.objects.create(user=self.other, item=copy, status=Status.PLANNING.value)
        self.assertEqual(data_invariants.tracked_copies_in_filled_buckets().count, 0)

    # -- 5. tracked and tombstoned ---------------------------------------------

    def test_tracked_and_tombstoned(self):
        # bulk_create skips any signal that would clear the tombstone, the way
        # an importer racing a delete left them in the sampled library.
        [tombstone] = DeletedMedia.objects.bulk_create(
            [
                DeletedMedia(
                    user=self.user,
                    media_type=MediaTypes.TV.value,
                    source=Sources.TVDB.value,
                    media_id="81189",
                )
            ]
        )
        DeletedMedia.objects.bulk_create(
            [
                # Another user's tombstone for the same show is not this user's.
                DeletedMedia(
                    user=self.other,
                    media_type=MediaTypes.TV.value,
                    source=Sources.TVDB.value,
                    media_id="81189",
                ),
                # Two Movie rows (repeats) still count as one title.
                DeletedMedia(
                    user=self.user,
                    media_type=MediaTypes.MOVIE.value,
                    source=Sources.TMDB.value,
                    media_id="603",
                ),
            ]
        )
        result = data_invariants.tracked_and_tombstoned(examples=10)
        self.assertEqual(result.breakdown, {"tv": 1, "movie": 1})
        self.assertIn(tombstone.pk, result.examples)

    # -- 6. structure ------------------------------------------------------------

    def test_season_user_differs_from_show(self):
        Season.objects.filter(pk=self.season.pk).update(user=self.other)
        self.assertEqual(
            self._nonzero(),
            {"season_user_differs_from_show": 1},
        )

    def test_season_item_not_its_shows(self):
        stranger = self._item(MediaTypes.SEASON.value, media_id="999", season=1)
        Season.objects.filter(pk=self.season.pk).update(item=stranger)
        nonzero = self._nonzero()
        self.assertEqual(nonzero["season_item_not_its_shows"], 1)
        # The play's item is now outside its season too: both alarms ring.
        self.assertEqual(nonzero["play_item_outside_its_season"], 1)

    def test_play_item_outside_its_season(self):
        other_season = self._item(MediaTypes.EPISODE.value, season=2, episode=1)
        Episode.objects.filter(pk=self.play.pk).update(item=other_season)
        result = data_invariants.play_item_outside_its_season(examples=10)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.examples, [self.play.pk])

    def test_play_without_item(self):
        Episode.objects.filter(pk=self.play.pk).update(item=None)
        self.assertEqual(self._nonzero(), {"play_without_item": 1})

    def test_tracker_item_wrong_type(self):
        Movie.objects.filter(user=self.user).update(item=self.show_item)
        result = data_invariants.tracker_item_wrong_type(examples=10)
        self.assertEqual(result.breakdown, {"movie": 2})
        self.assertEqual(len(result.examples), 2)
        self.assertTrue(all(e.startswith("movie:") for e in result.examples))

    # -- 7. candidate duplicate plays -----------------------------------------------

    def test_candidate_duplicate_plays(self):
        exact = Episode.objects.create(
            item=self.episode_item, related_season=self.season, end_date=PLAYED
        )
        near = Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=PLAYED + timedelta(minutes=20, seconds=3),
        )
        close = Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=PLAYED + timedelta(minutes=23),
        )
        # A rewatch the next day is a real second viewing.
        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=PLAYED + timedelta(days=1),
        )
        result = data_invariants.candidate_duplicate_plays(examples=10)
        self.assertEqual(result.kind, data_invariants.REVIEW)
        self.assertTrue(result.approximate)
        self.assertEqual(
            result.breakdown, {"same end time": 1, "within five minutes": 1}
        )
        self.assertEqual(result.count, 2)
        self.assertEqual(result.examples, [exact.pk, close.pk])
        self.assertNotIn(near.pk, result.examples)

    # -- 8. stalled work -----------------------------------------------------------------

    def test_stale_outbound_delivery(self):
        binding, _ = get_or_create_binding(
            self.user, SyncClientKind.GENERIC.value, instance_key="tv", profile_key="me"
        )
        stuck = OutboundStateDelivery.objects.create(
            binding=binding,
            user=self.user,
            item=self.movie_item,
            target_revision=1,
            status="in_flight",
            claimed_at=timezone.now() - timedelta(hours=2),
        )
        OutboundStateDelivery.objects.create(
            binding=binding,
            user=self.user,
            item=self.show_item,
            target_revision=1,
            status="in_flight",
            claimed_at=timezone.now() - timedelta(minutes=5),
        )
        result = data_invariants.stale_outbound_deliveries(examples=10)
        self.assertEqual((result.count, result.examples), (1, [stuck.pk]))

    def test_stale_import_run(self):
        old = timezone.now() - timedelta(days=3)
        leased = ImportRun.objects.create(user=self.user, source="trakt")
        ImportRun.objects.filter(pk=leased.pk).update(
            started_at=old, lease_expires_at=old
        )
        unleased = ImportRun.objects.create(user=self.user, source="simkl")
        ImportRun.objects.filter(pk=unleased.pk).update(started_at=old)
        # Still leased: a long import that is moving.
        moving = ImportRun.objects.create(user=self.user, source="plex")
        ImportRun.objects.filter(pk=moving.pk).update(
            started_at=old, lease_expires_at=timezone.now() + timedelta(minutes=5)
        )
        finished = ImportRun.objects.create(user=self.user, source="anilist")
        ImportRun.objects.filter(pk=finished.pk).update(
            started_at=old, status=ImportRun.Status.COMPLETED.value
        )
        result = data_invariants.stale_import_runs(examples=10)
        self.assertEqual(result.examples, [leased.pk, unleased.pk])

    # -- scope, safety and output -----------------------------------------------------

    def test_user_filter(self):
        self._empty_bucket(self.episode_item)
        Season.objects.filter(pk=self.season.pk).update(user=self.other)
        stranger_show = self._item(MediaTypes.TV.value, media_id="5", bucket="tv")
        TV.objects.create(user=self.other, item=stranger_show)
        self._empty_bucket(stranger_show)

        everyone = self._nonzero()
        self.assertEqual(everyone["items_without_bucket"], 2)

        mine = self._nonzero(user_id=self.user.pk)
        # The episode is played through a season that now belongs to the
        # other user, so only the show-level mismatch is still this user's.
        self.assertEqual(mine, {"season_user_differs_from_show": 1})
        theirs = self._nonzero(user_id=self.other.pk)
        self.assertEqual(theirs["items_without_bucket"], 2)

    def test_reads_only(self):
        self._empty_bucket(self.episode_item)
        with CaptureQueriesContext(connection) as queries:
            data_invariants.run_checks(examples=10)
            self._run("--json", "--verbose")
        self.assertTrue(queries.captured_queries)
        for query in queries.captured_queries:
            sql = query["sql"].lstrip().upper()
            self.assertTrue(sql.startswith("SELECT"), query["sql"])

    def test_text_report_has_ids_and_no_names(self):
        self._empty_bucket(self.episode_item)
        output = self._run("--verbose")
        self.assertIn("items_without_bucket", output)
        self.assertIn("always a fault", output)
        self.assertIn("review~", output)
        self.assertIn(str(self.episode_item.pk), output)
        self.assertIn("Nothing was changed.", output)
        for secret in ("private-name", "someone-else", "Secret Show Title"):
            self.assertNotIn(secret, output)

    def test_default_report_has_no_example_ids(self):
        self._empty_bucket(self.episode_item)
        report = json.loads(self._run("--json"))
        check = next(c for c in report["checks"] if c["name"] == "items_without_bucket")
        self.assertEqual(check["count"], 1)
        self.assertEqual(check["examples"], [])

    def test_json_report(self):
        self._empty_bucket(self.episode_item)
        report = json.loads(self._run("--json", "--verbose"))
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["faults"], 1)
        check = next(c for c in report["checks"] if c["name"] == "items_without_bucket")
        self.assertEqual(check["kind"], "fault")
        self.assertEqual(check["examples"], [self.episode_item.pk])
        for secret in ("private-name", "Secret Show Title"):
            self.assertNotIn(secret, json.dumps(report))

    def test_exit_code(self):
        self._empty_bucket(self.episode_item)
        self._run()  # no --strict: always 0
        with self.assertRaises(SystemExit) as stopped:
            self._run("--strict")
        self.assertEqual(stopped.exception.code, 1)

    def test_strict_ignores_review_counts(self):
        self._item(MediaTypes.TV.value, bucket="anime")
        self._run("--strict")

    def test_unknown_user(self):
        with self.assertRaises(CommandError):
            self._run("--user", "999999")
