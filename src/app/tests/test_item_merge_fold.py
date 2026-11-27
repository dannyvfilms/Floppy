"""An unattended item merge keeps what the user recorded on both sides (prompt 66)."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from celery.app.task import Task
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    DeletedEntry,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
    Video,
    VideoPlay,
)
from app.services import item_merge
from app.services.music import merge_album_records, merge_artist_records
from app.services.music_scrobble import dedupe_artist_albums
from app.services.tracker_fold import (
    MERGE_CHANGE_REASON,
    USER_SCALAR_FIELDS,
    fold_tracker_fields,
)
from integrations import match_corrections


def _dt(day):
    return datetime(2026, 1, day, 12, 0, tzinfo=UTC)


def _item(media_id, source, media_type=MediaTypes.TV.value, **extra):
    return Item.objects.create(
        media_id=media_id,
        source=source,
        media_type=media_type,
        title="Show",
        image="x",
        **extra,
    )


class MergeFoldTests(TestCase):
    """Merging two tracked copies of one show folds the user's fields."""

    def setUp(self):
        patcher = patch.object(Task, "apply_async", autospec=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user(username="fold-user")
        self.loser = _item("100", Sources.TMDB.value)
        self.keeper = _item("200", Sources.TVDB.value)

    def _season_item(self, show, number=1):
        return _item(
            show.media_id,
            show.source,
            MediaTypes.SEASON.value,
            season_number=number,
        )

    def _episode_item(self, show, season=1, episode=1):
        return _item(
            show.media_id,
            show.source,
            MediaTypes.EPISODE.value,
            season_number=season,
            episode_number=episode,
        )

    def _merge(self):
        item_merge.merge_item(self.loser, self.keeper)
        return TV.objects.get(user=self.user, item=self.keeper)

    def test_probe_case_keeps_score_notes_status_and_leaves_no_tombstone(self):
        """The Pass 10 `merge:tv` probe, as a regression test."""
        TV.objects.create(
            user=self.user,
            item=self.loser,
            status=Status.IN_PROGRESS.value,
            score=9,
            notes="my notes",
        )
        TV.objects.create(
            user=self.user, item=self.keeper, status=Status.PLANNING.value
        )

        survivor = self._merge()

        self.assertEqual(survivor.status, Status.IN_PROGRESS.value)
        self.assertEqual(survivor.score, Decimal(9))
        self.assertIsNotNone(survivor.scored_at)
        self.assertEqual(survivor.notes, "my notes")
        self.assertFalse(DeletedMedia.objects.filter(user=self.user).exists())
        latest = survivor.history.order_by("-history_date").first()
        self.assertEqual(latest.history_change_reason, MERGE_CHANGE_REASON)
        # The library change feed still reports the old identity as gone.
        self.assertTrue(
            DeletedEntry.objects.filter(
                user=self.user,
                source=Sources.TMDB.value,
                media_id="100",
            ).exists(),
        )

    def test_both_scored_keeps_survivor_score_and_records_the_other(self):
        TV.objects.create(
            user=self.user,
            item=self.loser,
            status=Status.COMPLETED.value,
            score=9,
        )
        TV.objects.create(
            user=self.user,
            item=self.keeper,
            status=Status.COMPLETED.value,
            score=7,
        )

        survivor = self._merge()

        self.assertEqual(survivor.score, Decimal(7))
        latest = survivor.history.order_by("-history_date").first()
        self.assertIn("other score 9", latest.history_change_reason)

    def test_both_with_notes_are_joined_and_identical_notes_are_not_doubled(self):
        TV.objects.create(user=self.user, item=self.loser, notes="second")
        TV.objects.create(user=self.user, item=self.keeper, notes="first")

        self.assertEqual(self._merge().notes, "first\n\nsecond")

        other = _item("300", Sources.TMDB.value)
        TV.objects.create(user=self.user, item=other, notes="first\n\nsecond")
        item_merge.merge_item(other, self.keeper)
        self.assertEqual(
            TV.objects.get(user=self.user, item=self.keeper).notes,
            "first\n\nsecond",
        )

    def test_dates_take_earlier_start_and_later_end(self):
        """Shows keep no dates of their own; a colliding video row does."""
        loser = _item("v1", Sources.YOUTUBE.value, MediaTypes.VIDEO.value)
        keeper = _item("v2", Sources.YOUTUBE.value, MediaTypes.VIDEO.value)
        Video.objects.create(
            user=self.user, item=loser, start_date=_dt(1), end_date=_dt(20)
        )
        keeper_video = Video.objects.create(
            user=self.user, item=keeper, start_date=_dt(5), end_date=_dt(10)
        )

        item_merge.merge_item(loser, keeper)

        keeper_video.refresh_from_db()
        self.assertEqual(keeper_video.start_date, _dt(1))
        self.assertEqual(keeper_video.end_date, _dt(20))

    def test_user_held_status_on_survivor_is_never_changed(self):
        TV.objects.create(
            user=self.user, item=self.loser, status=Status.COMPLETED.value
        )
        TV.objects.create(user=self.user, item=self.keeper, status=Status.DROPPED.value)

        survivor = self._merge()

        self.assertEqual(survivor.status, Status.DROPPED.value)
        latest = survivor.history.order_by("-history_date").first()
        self.assertIn("other status Completed", latest.history_change_reason)

    def test_user_held_status_on_loser_replaces_only_planning(self):
        TV.objects.create(user=self.user, item=self.loser, status=Status.PAUSED.value)
        TV.objects.create(
            user=self.user, item=self.keeper, status=Status.PLANNING.value
        )

        self.assertEqual(self._merge().status, Status.PAUSED.value)

    def test_season_level_fold_through_the_show_merge(self):
        loser_tv = TV.objects.create(user=self.user, item=self.loser)
        keeper_tv = TV.objects.create(user=self.user, item=self.keeper)
        season_item = self._season_item(self.keeper)
        loser_season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=loser_tv,
            status=Status.COMPLETED.value,
            score=8,
            notes="great season",
        )
        keeper_season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=keeper_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = self._episode_item(self.keeper)
        Episode.objects.create(
            item=episode_item,
            related_season=loser_season,
            end_date=_dt(3),
        )
        Episode.objects.create(
            item=episode_item,
            related_season=keeper_season,
            end_date=_dt(4),
        )

        self._merge()

        keeper_season.refresh_from_db()
        self.assertFalse(Season.objects.filter(pk=loser_season.pk).exists())
        self.assertEqual(keeper_season.status, Status.COMPLETED.value)
        self.assertEqual(keeper_season.score, Decimal(8))
        self.assertEqual(keeper_season.notes, "great season")
        # Both plays survive: a repeat watch is not a duplicate.
        self.assertEqual(
            Episode.objects.filter(related_season=keeper_season).count(),
            2,
        )

    def test_season_item_merge_folds_season_fields(self):
        tv = TV.objects.create(user=self.user, item=self.keeper)
        loser_season_item = self._season_item(self.loser)
        keeper_season_item = self._season_item(self.keeper)
        Season.objects.create(
            user=self.user,
            item=loser_season_item,
            related_tv=tv,
            score=6,
            notes="season notes",
            status=Status.COMPLETED.value,
        )
        keeper_season = Season.objects.create(
            user=self.user,
            item=keeper_season_item,
            related_tv=tv,
            status=Status.PLANNING.value,
        )

        item_merge.merge_item(loser_season_item, keeper_season_item)

        keeper_season.refresh_from_db()
        self.assertEqual(keeper_season.score, Decimal(6))
        self.assertEqual(keeper_season.notes, "season notes")
        self.assertEqual(keeper_season.status, Status.COMPLETED.value)

    def test_three_users_one_tracking_both(self):
        both = self.user
        loser_only = get_user_model().objects.create_user(username="fold-loser")
        keeper_only = get_user_model().objects.create_user(username="fold-keeper")
        TV.objects.create(user=both, item=self.loser, score=9, notes="a")
        TV.objects.create(user=both, item=self.keeper, status=Status.PLANNING.value)
        loser_only_tv = TV.objects.create(
            user=loser_only,
            item=self.loser,
            score=5,
            notes="b",
        )
        keeper_only_tv = TV.objects.create(
            user=keeper_only,
            item=self.keeper,
            score=4,
            notes="c",
        )
        plays_before = self._plays_per_user()

        self._merge()

        self.assertEqual(TV.objects.filter(item=self.keeper).count(), 3)
        self.assertEqual(TV.objects.get(user=both, item=self.keeper).score, Decimal(9))
        loser_only_tv.refresh_from_db()
        self.assertEqual(loser_only_tv.item_id, self.keeper.pk)
        self.assertEqual((loser_only_tv.score, loser_only_tv.notes), (Decimal(5), "b"))
        keeper_only_tv.refresh_from_db()
        self.assertEqual(
            (keeper_only_tv.score, keeper_only_tv.notes), (Decimal(4), "c")
        )
        self.assertFalse(DeletedMedia.objects.exists())
        self.assertEqual(self._plays_per_user(), plays_before)

    def _plays_per_user(self):
        counts = {}
        for user_id in Episode.objects.values_list(
            "related_season__user_id", flat=True
        ):
            counts[("episode", user_id)] = counts.get(("episode", user_id), 0) + 1
        for user_id in MoviePlay.objects.values_list("movie__user_id", flat=True):
            counts[("movie", user_id)] = counts.get(("movie", user_id), 0) + 1
        return counts

    def test_plays_are_neither_dropped_nor_duplicated(self):
        loser_tv = TV.objects.create(user=self.user, item=self.loser)
        keeper_tv = TV.objects.create(user=self.user, item=self.keeper)
        loser_season_item = self._season_item(self.loser)
        keeper_season_item = self._season_item(self.keeper)
        loser_season = Season.objects.create(
            user=self.user,
            item=loser_season_item,
            related_tv=loser_tv,
        )
        Season.objects.create(
            user=self.user,
            item=keeper_season_item,
            related_tv=keeper_tv,
        )
        for number in (1, 2, 3):
            Episode.objects.create(
                item=self._episode_item(self.loser, episode=number),
                related_season=loser_season,
                end_date=_dt(number),
            )
        before = self._plays_per_user()

        self._merge()

        self.assertEqual(self._plays_per_user(), before)

    def test_movie_rows_on_both_items_are_kept_as_repeats(self):
        """Movies store a repeat as another row; a merge never deletes one."""
        loser = _item("10", Sources.TMDB.value, MediaTypes.MOVIE.value)
        keeper = _item("20", Sources.MANUAL.value, MediaTypes.MOVIE.value)
        loser_movie = Movie.objects.create(user=self.user, item=loser, score=8)
        keeper_movie = Movie.objects.create(user=self.user, item=keeper)
        MoviePlay.objects.create(movie=loser_movie, end_date=_dt(1))
        MoviePlay.objects.create(movie=keeper_movie, end_date=_dt(2))
        before = self._plays_per_user()

        item_merge.merge_item(loser, keeper)

        self.assertEqual(Movie.objects.filter(user=self.user, item=keeper).count(), 2)
        self.assertEqual(self._plays_per_user(), before)
        self.assertFalse(DeletedMedia.objects.exists())

    def test_colliding_video_rows_fold_and_keep_their_plays(self):
        loser = _item("v1", Sources.YOUTUBE.value, MediaTypes.VIDEO.value)
        keeper = _item("v2", Sources.YOUTUBE.value, MediaTypes.VIDEO.value)
        loser_video = Video.objects.create(
            user=self.user,
            item=loser,
            score=7,
            notes="video notes",
        )
        keeper_video = Video.objects.create(user=self.user, item=keeper)
        VideoPlay.objects.create(video=loser_video, external_id="a", end_date=_dt(1))
        VideoPlay.objects.create(
            video=loser_video, external_id="b", end_date=_dt(2), from_takeout=True,
        )
        keeper_video.upsert_play("b", 100, end_date=_dt(2))

        item_merge.merge_item(loser, keeper)

        keeper_video.refresh_from_db()
        self.assertEqual(keeper_video.score, Decimal(7))
        self.assertEqual(keeper_video.notes, "video notes")
        self.assertEqual(
            sorted(keeper_video.plays.values_list("external_id", flat=True)),
            ["a", "b"],
        )
        merged_play = keeper_video.plays.get(external_id="b")
        self.assertTrue(merged_play.from_takeout)
        self.assertTrue(merged_play.from_progress_report)
        self.assertEqual(merged_play.progress, 100)

    def test_a_failure_leaves_both_items_untouched(self):
        TV.objects.create(user=self.user, item=self.loser, score=9)
        keeper_tv = TV.objects.create(user=self.user, item=self.keeper)

        with (
            patch.object(
                item_merge,
                "fold_tracker_into",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            item_merge.merge_item(self.loser, self.keeper)

        self.assertTrue(Item.objects.filter(pk=self.loser.pk).exists())
        self.assertTrue(TV.objects.filter(user=self.user, item=self.loser).exists())
        keeper_tv.refresh_from_db()
        self.assertIsNone(keeper_tv.score)

    def test_user_delete_still_leaves_a_tombstone(self):
        """Only the merge is exempt; a real delete still remembers the title."""
        TV.objects.create(user=self.user, item=self.loser).delete()

        self.assertTrue(DeletedMedia.objects.filter(user=self.user).exists())


class FoldRuleTests(TestCase):
    """The field rule in isolation."""

    def test_field_list_is_shared_with_match_corrections(self):
        self.assertIs(match_corrections.SCALAR_FIELDS, USER_SCALAR_FIELDS)

    def test_status_ladder(self):
        cases = [
            (Status.PLANNING.value, Status.COMPLETED.value, Status.COMPLETED.value),
            (Status.COMPLETED.value, Status.IN_PROGRESS.value, Status.COMPLETED.value),
            (None, Status.PLANNING.value, Status.PLANNING.value),
            (Status.PLANNING.value, Status.DROPPED.value, Status.DROPPED.value),
            (Status.IN_PROGRESS.value, Status.DROPPED.value, Status.IN_PROGRESS.value),
            (Status.PAUSED.value, Status.COMPLETED.value, Status.PAUSED.value),
            (Status.COMPLETED.value, None, Status.COMPLETED.value),
        ]
        for survivor_status, other_status, expected in cases:
            with self.subTest(survivor=survivor_status, other=other_status):
                survivor = TV(status=survivor_status)
                fold_tracker_fields(TV(status=other_status), survivor)
                self.assertEqual(survivor.status, expected)

    def test_empty_survivor_takes_entry_source_and_larger_progress(self):
        survivor = Movie(progress=2)
        fold_tracker_fields(Movie(entry_source="plex", progress=5), survivor)
        self.assertEqual((survivor.entry_source, survivor.progress), ("plex", 5))


class MusicTrackerFoldTests(TestCase):
    """Album and artist merges keep both trackers' fields the same way."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="fold-music")
        self.artist = Artist.objects.create(name="Fold Artist")

    def test_scrobble_album_dedupe_keeps_the_duplicate_trackers_fields(self):
        rich = Album.objects.create(
            title="Blues Walk",
            artist=self.artist,
            musicbrainz_release_id="rel-1",
            image="http://img/rich.jpg",
            tracks_populated=True,
        )
        rich.tracklist.create(title="Track A", track_number=1)
        poor = Album.objects.create(title="Blues Walk", artist=self.artist)
        AlbumTracker.objects.create(
            user=self.user,
            album=rich,
            status=Status.PLANNING.value,
        )
        AlbumTracker.objects.create(
            user=self.user,
            album=poor,
            status=Status.COMPLETED.value,
            score=8,
            notes="on vinyl",
            end_date=_dt(9),
        )

        dedupe_artist_albums(self.artist)

        tracker = AlbumTracker.objects.get(user=self.user)
        self.assertEqual(tracker.album_id, rich.pk)
        self.assertEqual(tracker.status, Status.COMPLETED.value)
        self.assertEqual(tracker.score, Decimal(8))
        self.assertEqual(tracker.notes, "on vinyl")
        self.assertEqual(tracker.end_date, _dt(9))

    def test_album_record_merge_keeps_notes(self):
        source = Album.objects.create(title="One", artist=self.artist)
        target = Album.objects.create(title="One (Deluxe)", artist=self.artist)
        AlbumTracker.objects.create(user=self.user, album=source, notes="favourite")
        AlbumTracker.objects.create(user=self.user, album=target, score=6)

        merge_album_records(source, target)

        tracker = AlbumTracker.objects.get(user=self.user)
        self.assertEqual((tracker.notes, tracker.score), ("favourite", Decimal(6)))

    def test_artist_merge_never_changes_a_dropped_status(self):
        target = Artist.objects.create(name="Fold Artist Canonical")
        ArtistTracker.objects.create(
            user=self.user,
            artist=self.artist,
            status=Status.COMPLETED.value,
        )
        ArtistTracker.objects.create(
            user=self.user,
            artist=target,
            status=Status.DROPPED.value,
        )

        merge_artist_records(self.artist, target)

        self.assertEqual(
            ArtistTracker.objects.get(user=self.user).status,
            Status.DROPPED.value,
        )
