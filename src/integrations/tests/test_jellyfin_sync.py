from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import TV, Episode, Item, MediaTypes, Movie, Season, Sources, Status
from integrations import tasks
from integrations.imports.helpers import MediaImportError, encrypt
from integrations.jellyfin_sync import (
    JellyfinPushSyncService,
    format_jellyfin_push_message,
)
from integrations.models import JellyfinAccount


def _jellyfin_movie(item_id, tmdb_id, *, played=False):
    return {
        "Id": item_id,
        "Type": "Movie",
        "ProviderIds": {"Tmdb": str(tmdb_id)},
        "UserData": {"Played": played},
    }


def _jellyfin_series(series_id, *, tmdb_id=None, tvdb_id=None):
    provider_ids = {}
    if tmdb_id is not None:
        provider_ids["Tmdb"] = str(tmdb_id)
    if tvdb_id is not None:
        provider_ids["Tvdb"] = str(tvdb_id)
    return {
        "Id": series_id,
        "Type": "Series",
        "ProviderIds": provider_ids,
    }


def _jellyfin_episode(
    item_id,
    series_id,
    season_number,
    episode_number,
    *,
    played=False,
    episode_provider_ids=None,
):
    # Real Jellyfin episode items carry episode-level provider ids (e.g. the
    # TVDB episode id), never the series id — that lives on the Series item.
    return {
        "Id": item_id,
        "Type": "Episode",
        "SeriesId": series_id,
        "ProviderIds": episode_provider_ids or {},
        "ParentIndexNumber": season_number,
        "IndexNumber": episode_number,
        "UserData": {"Played": played},
    }


class JellyfinPushSyncServiceTests(TestCase):
    """Cover the Floppy -> Jellyfin watched-state push sync."""

    def setUp(self):
        """Create a user with a connected Jellyfin account and a watched movie."""
        self.user = get_user_model().objects.create_user(username="jf-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key=encrypt("api-key"),
            jellyfin_user_id="jf-user-1",
            push_watched_enabled=True,
            push_unwatched_enabled=False,
        )
        self.item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        self.movie = Movie.objects.create(
            user=self.user,
            item=self.item,
            status=Status.COMPLETED.value,
        )

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_played")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_pushes_watched_movie_not_yet_played(self, mock_items, mock_mark_played):
        """A completed Floppy movie should mark the matching Jellyfin item played."""
        mock_items.return_value = iter([_jellyfin_movie("jf-1", "603", played=False)])

        counts, warnings = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_played.assert_called_once_with("jf-1")
        self.assertEqual(counts.get("marked_played"), 1)
        self.assertEqual(warnings, "")

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_played")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_skips_write_when_already_played(self, mock_items, mock_mark_played):
        """No write should happen when Jellyfin already reflects the desired state."""
        mock_items.return_value = iter([_jellyfin_movie("jf-1", "603", played=True)])

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_played.assert_not_called()
        self.assertEqual(counts.get("skipped_already_synced"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_unplayed")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_unwatched_push_disabled_by_default(self, mock_items, mock_mark_unplayed):
        """push_unwatched defaults off, so played Jellyfin items are left alone."""
        self.movie.status = Status.IN_PROGRESS.value
        self.movie.save(update_fields=["status"])
        mock_items.return_value = iter([_jellyfin_movie("jf-1", "603", played=True)])

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_unplayed.assert_not_called()
        self.assertEqual(counts.get("skipped_already_synced"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_unplayed")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_unwatched_push_when_enabled(self, mock_items, mock_mark_unplayed):
        """Enabling push_unwatched should clear played state Floppy no longer has."""
        self.account.push_unwatched_enabled = True
        self.account.save(update_fields=["push_unwatched_enabled"])
        self.movie.status = Status.IN_PROGRESS.value
        self.movie.save(update_fields=["status"])
        mock_items.return_value = iter([_jellyfin_movie("jf-1", "603", played=True)])

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_unplayed.assert_called_once_with("jf-1")
        self.assertEqual(counts.get("marked_unplayed"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_played")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_pushes_watched_episode(self, mock_items, mock_mark_played):
        """A watched episode should be matched by tmdb id + season/episode number."""
        tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
        )
        TV.objects.create(user=self.user, item=tv_item, status=Status.IN_PROGRESS.value)
        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Friends Season 1",
        )
        tv = TV.objects.get(item=tv_item, user=self.user)
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="The Pilot",
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now(),
        )
        mock_items.return_value = iter(
            [
                _jellyfin_series("jf-series-1", tmdb_id="1668"),
                _jellyfin_episode(
                    "jf-ep-1",
                    "jf-series-1",
                    1,
                    1,
                    played=False,
                    episode_provider_ids={"Tvdb": "303821"},
                ),
            ],
        )

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_played.assert_called_once_with("jf-ep-1")
        self.assertEqual(counts.get("marked_played"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.mark_played")
    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_pushes_watched_episode_tracked_via_tvdb(
        self,
        mock_items,
        mock_mark_played,
    ):
        """Shows tracked with TVDB as the identity provider should still match."""
        tv_item = Item.objects.create(
            media_id="79168",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Peep Show",
        )
        TV.objects.create(user=self.user, item=tv_item, status=Status.IN_PROGRESS.value)
        season_item = Item.objects.create(
            media_id="79168",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Peep Show Season 1",
        )
        tv = TV.objects.get(item=tv_item, user=self.user)
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="79168",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Warring Factions",
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now(),
        )
        mock_items.return_value = iter(
            [
                _jellyfin_series("jf-series-tvdb", tvdb_id="79168"),
                _jellyfin_episode("jf-ep-tvdb-1", "jf-series-tvdb", 1, 1, played=False),
            ],
        )

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        mock_mark_played.assert_called_once_with("jf-ep-tvdb-1")
        self.assertEqual(counts.get("marked_played"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_episode_with_unknown_series_is_skipped(self, mock_items):
        """Episodes whose SeriesId has no Series entry should skip, not crash."""
        tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
        )
        tv = TV.objects.create(
            user=self.user,
            item=tv_item,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Friends Season 1",
        )
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="The Pilot",
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now(),
        )
        mock_items.return_value = iter(
            [_jellyfin_episode("jf-ep-orphan", "missing-series", 1, 1)],
        )

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        self.assertEqual(counts.get("skipped_no_match"), 2)

    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_empty_library_appends_warning(self, mock_items):
        """An empty Jellyfin sweep should warn about library access."""
        mock_items.return_value = iter([])

        _, warnings = JellyfinPushSyncService(self.user, self.account).sync()

        self.assertIn("no library items", warnings)

    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_unsupported_source_is_counted_and_skipped(self, mock_items):
        """Items tracked via a source Jellyfin can't expose (e.g. MAL) are skipped."""
        anime_item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Anime Movie",
        )
        Movie.objects.create(
            user=self.user,
            item=anime_item,
            status=Status.COMPLETED.value,
        )
        mock_items.return_value = iter([])

        counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        self.assertEqual(counts.get("skipped_unsupported_source"), 1)
        # The setUp movie (TMDB-sourced) has no matching Jellyfin item either.
        self.assertEqual(counts.get("skipped_no_match"), 1)

    @patch("integrations.jellyfin_sync.JellyfinClient.iter_library_items")
    def test_no_match_is_counted_and_skipped(self, mock_items):
        """Movies without a matching Jellyfin provider id are counted, not errored."""
        mock_items.return_value = iter([])

        with self.assertLogs("integrations.jellyfin_sync", level="INFO") as logs:
            counts, _ = JellyfinPushSyncService(self.user, self.account).sync()

        self.assertEqual(counts.get("skipped_no_match"), 1)
        self.assertIn(
            "1 distinct titles; showing 1: The Matrix [Tmdb:603]",
            "\n".join(logs.output),
        )

    def test_unmatched_title_log_is_bounded(self):
        """A large stale history should produce one concise diagnostic line."""
        service = JellyfinPushSyncService(self.user, self.account)
        service.unmatched_titles = {f"Title {number}" for number in range(21)}

        with self.assertLogs("integrations.jellyfin_sync", level="INFO") as logs:
            service._log_unmatched_titles()

        self.assertIn("21 distinct titles; showing 20", logs.output[0])
        self.assertIn("(+1 more)", logs.output[0])

    def test_sync_raises_when_not_connected(self):
        """Sync should refuse to run without a connected account."""
        self.account.api_key = ""
        self.account.save(update_fields=["api_key"])

        with self.assertRaises(MediaImportError):
            JellyfinPushSyncService(self.user, self.account).sync()


class FormatJellyfinPushMessageTests(TestCase):
    """Cover the push-sync result message formatter."""

    def test_all_zero_counts_reads_as_nothing_to_sync(self):
        """A run that changed nothing should say so explicitly, not vaguely."""
        message = format_jellyfin_push_message({})
        self.assertIn("Nothing to sync", message)

    def test_marked_counts_are_reported(self):
        """Non-zero marked_played/marked_unplayed counts should be summarized."""
        message = format_jellyfin_push_message(
            {"marked_played": 3, "marked_unplayed": 1},
        )
        self.assertIn("marked 3 watched", message)
        self.assertIn("marked 1 unwatched", message)

    def test_skip_reasons_are_reported(self):
        """Skip counters should surface why items weren't touched."""
        message = format_jellyfin_push_message(
            {"skipped_no_match": 2, "skipped_unsupported_source": 1},
        )
        self.assertIn("2 had no Jellyfin match", message)
        self.assertIn("1 use an unsupported metadata source", message)

    def test_warning_text_is_appended(self):
        """Warning text, when present, should be appended to the message."""
        message = format_jellyfin_push_message({"marked_played": 1}, "some warning")
        self.assertIn("some warning", message)


class PushJellyfinWatchedTaskTests(TestCase):
    """Cover the push_jellyfin_watched Celery task."""

    def setUp(self):
        """Create a user with a connected Jellyfin account."""
        self.user = get_user_model().objects.create_user(username="jf-task-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local:8096",
            api_key=encrypt("api-key"),
            jellyfin_user_id="jf-user-1",
        )

    def test_task_requires_connected_account(self):
        """The task should raise when the user has no Jellyfin account."""
        other_user = get_user_model().objects.create_user(username="jf-no-account")

        with self.assertRaises(MediaImportError):
            tasks.push_jellyfin_watched(user_id=other_user.id)

    @patch("integrations.tasks._media_imports.JellyfinPushSyncService.sync")
    def test_task_records_error_on_failure(self, mock_sync):
        """A sync failure should mark the account broken and record the error."""
        mock_sync.side_effect = MediaImportError("boom")

        with self.assertRaises(MediaImportError):
            tasks.push_jellyfin_watched(user_id=self.user.id)

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertEqual(self.account.last_error_message, "boom")

    @patch("integrations.tasks._media_imports.JellyfinPushSyncService.sync")
    def test_task_records_success(self, mock_sync):
        """A successful sync should clear errors and stamp last_sync_at."""
        mock_sync.return_value = ({"marked_played": 1}, "")

        tasks.push_jellyfin_watched(user_id=self.user.id)

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertEqual(self.account.last_error_message, "")
        self.assertIsNotNone(self.account.last_sync_at)
