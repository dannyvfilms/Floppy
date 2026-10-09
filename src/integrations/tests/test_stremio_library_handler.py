from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app.mixins import disable_fetch_releases
from app.models import TV, Episode, Item, Movie, PlaybackProgress, Season
from app.models.choices import MediaTypes, Sources, Status
from integrations import stremio_tracker as tracker

User = get_user_model()


class RecordLibraryEventTests(TestCase):
    """The library resource: watched/unwatched and add/remove for one item."""

    def setUp(self):
        # Sessions are cached per user id, which restarts at 1 every test;
        # without a clear, one test's session leaks into the next.
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="library", password="x")
        with disable_fetch_releases():
            # The shape the Stremio importer creates: a numeric TMDB media_id
            # with the IMDB id (what Stremio sends) in provider_external_ids.
            self.item = Item.objects.create(
                media_id="800",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                provider_external_ids={"imdb_id": "tt800"},
                title="Library",
                image="",
            )
            Movie.objects.create(item=self.item, user=self.user)

    def _plays(self):
        return Movie.objects.get(item=self.item, user=self.user).plays.count()

    def _progress(self):
        return PlaybackProgress.objects.get(user=self.user, item=self.item)

    def test_watched_appends_a_play(self):
        status = tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=watched",
        )

        self.assertEqual(status, "recorded")
        self.assertEqual(self._plays(), 1)

    def test_repeated_watched_does_not_append_twice(self):
        """The poller re-observing the flag must not duplicate history."""
        tracker.record_library_event(self.user, "movie", "tt800", "action=watched")
        tracker.record_library_event(self.user, "movie", "tt800", "action=watched")

        self.assertEqual(self._plays(), 1)

    def test_unwatched_clears_progress_and_keeps_history(self):
        tracker.record_library_event(self.user, "movie", "tt800", "action=watched")
        PlaybackProgress.objects.update_or_create(
            user=self.user,
            item=self.item,
            defaults={"position_seconds": 300, "completed": True},
        )

        status = tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=unwatched",
        )

        self.assertEqual(status, "recorded")
        self.assertFalse(
            PlaybackProgress.objects.filter(user=self.user, item=self.item).exists(),
        )
        self.assertEqual(self._plays(), 1)

    def test_library_remove_clears_progress(self):
        PlaybackProgress.objects.create(
            user=self.user,
            item=self.item,
            position_seconds=200,
        )

        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=libraryRemove",
        )

        self.assertFalse(
            PlaybackProgress.objects.filter(user=self.user, item=self.item).exists(),
        )

    def test_a_movie_video_id_does_not_split_the_session(self):
        """A movie has one video, so a `videoId` must not key a second session.

        Stremio sends the movie's own id as the `videoId`. Keying the session on
        it files the flag under a different identity than the player's own
        event, so the completion never reaches the progress row that session
        owns and the two producers stop merging.
        """
        started = timezone.now()
        tracker.record_player_event(
            self.user,
            "movie",
            "tt800",
            "action=pause&currentTime=300000&duration=600000",
            now=started,
        )
        self.assertFalse(self._progress().completed)

        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=watched&videoId=tt800",
            now=started + timedelta(seconds=1),
        )

        self.assertTrue(self._progress().completed)
        self.assertEqual(self._plays(), 1)

    def test_library_add_does_not_create_history(self):
        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=libraryAdd",
        )

        self.assertEqual(self._plays(), 0)

    def test_invalid_action_is_ignored(self):
        status = tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=renamed",
        )

        self.assertEqual(status, "invalid_extra")

    def test_unresolved_media_is_skipped(self):
        status = tracker.record_library_event(
            self.user,
            "movie",
            "tt999",
            "action=watched",
        )

        self.assertEqual(status, "unresolved_media")

    def test_library_add_does_not_clear_a_completed_session(self):
        """`libraryAdd` asserts nothing about watched-ness, so it passes None.

        The item is already completed; a library add is not an un-watch. Passing
        `watched=False` for it would clear the session's completion and rewrite
        the progress row back to in-progress.
        """
        tracker.record_player_event(
            self.user,
            "movie",
            "tt800",
            "action=stop&currentTime=450000&duration=600000",
        )
        self.assertTrue(self._progress().completed)
        self.assertEqual(self._plays(), 1)

        tracker.record_library_event(self.user, "movie", "tt800", "action=libraryAdd")

        self.assertTrue(self._progress().completed)
        self.assertEqual(self._plays(), 1)

    def test_library_remove_does_not_delete_history(self):
        """Removal clears progress; the watch history is never deleted."""
        tracker.record_library_event(self.user, "movie", "tt800", "action=watched")
        PlaybackProgress.objects.update_or_create(
            user=self.user,
            item=self.item,
            defaults={"position_seconds": 300, "completed": True},
        )

        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=libraryRemove",
        )

        self.assertEqual(self._plays(), 1)
        self.assertFalse(
            PlaybackProgress.objects.filter(user=self.user, item=self.item).exists(),
        )

    def test_a_rewatch_appends_a_second_play(self):
        """A later watch crosses a session boundary and counts as a new play.

        The handler must use the session `session_for_observation` returns. The
        cached session's `play_recorded` is still true after the un-watch, so
        folding the second watch into it dedups the play away.
        """
        first = timezone.now()
        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=watched",
            now=first,
        )
        self.assertEqual(self._plays(), 1)

        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=unwatched",
            now=first + timedelta(seconds=1),
        )

        tracker.record_library_event(
            self.user,
            "movie",
            "tt800",
            "action=watched",
            now=first + timedelta(hours=4),
        )

        self.assertEqual(self._plays(), 2)


class LibraryVideoIdBatchTests(TestCase):
    """One library event may name a batch of episodes through `videoId`."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="library-batch", password="x")
        # Watching an episode syncs the season through provider metadata; the
        # test network guard blocks the real call, so stub the payload.
        metadata = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "season/1": {
                    "episodes": [{"episode_number": number} for number in (1, 2, 3)],
                },
                "related": {"seasons": [{"season_number": 1}]},
                "cast": [],
                "crew": [],
            },
        )
        metadata.start()
        self.addCleanup(metadata.stop)
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt900"},
                title="Batch Series",
                image="",
            )
            tv = TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            season_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
                title="Batch Series",
                image="",
            )
            season = Season.objects.create(
                item=season_item,
                related_tv=tv,
                user=self.user,
                status=Status.PLANNING.value,
            )
            self.episode_items = {}
            for number in (1, 2):
                episode_item = Item.objects.create(
                    media_id="1399",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    season_number=1,
                    episode_number=number,
                    title=f"Episode {number}",
                    image="",
                )
                # Seed the row `_append_play` reaches the season through.
                Episode.objects.bulk_create(
                    [
                        Episode(
                            item=episode_item,
                            related_season=season,
                            end_date=None,
                        ),
                    ],
                )
                self.episode_items[number] = episode_item

    def _plays(self, number):
        """Count plays for one episode, ignoring the seeded fixture row."""
        return Episode.objects.filter(item=self.episode_items[number]).count() - 1

    def test_a_batched_video_id_list_records_every_episode(self):
        status = tracker.record_library_event(
            self.user,
            "series",
            "tt900",
            "action=watched&videoId=tt900%3A1%3A1,tt900%3A1%3A2",
        )

        self.assertEqual(status, "recorded")
        self.assertEqual(self._plays(1), 1)
        self.assertEqual(self._plays(2), 1)


class LegacyVerifierOverlapTests(TestCase):
    """The tracker must consult the shared play dedupe before appending.

    The legacy verifier completes a title at 90% while playback continues, and
    the tracker sees the client's own `stop` minutes later. Both describe one
    viewing, so the second append has to be suppressed by the same window check
    the legacy webhook path uses.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="legacy-overlap", password="x")
        metadata = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "season/1": {
                    "episodes": [{"episode_number": number} for number in (1, 2, 3)],
                },
                "related": {"seasons": [{"season_number": 1}]},
                "cast": [],
                "crew": [],
            },
        )
        metadata.start()
        self.addCleanup(metadata.stop)
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt900"},
                title="Overlap Series",
                image="",
            )
            tv = TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            season_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
                title="Overlap Series",
                image="",
            )
            self.season = Season.objects.create(
                item=season_item,
                related_tv=tv,
                user=self.user,
                status=Status.PLANNING.value,
            )
            self.episode_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=2,
                title="An Episode",
                image="",
            )
            # Seed the row the tracker reaches the season through; it is
            # fixture plumbing, so `_plays` counts it out.
            Episode.objects.bulk_create(
                [
                    Episode(
                        item=self.episode_item,
                        related_season=self.season,
                        end_date=None,
                    ),
                ],
            )
            self.seeded_plays = Episode.objects.filter(
                item=self.episode_item,
            ).count()

    def _plays(self):
        return (
            Episode.objects.filter(item=self.episode_item).count() - self.seeded_plays
        )

    def test_a_legacy_episode_play_suppresses_the_tracker_append(self):
        """The 90%-completion verifier and the client's `stop` are one play."""
        ended = timezone.now()
        # What the legacy path leaves behind: the verifier completed the
        # episode at 90%, so the play row is already there when the client's
        # own `stop` arrives a minute later.
        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=ended,
        )

        tracker.record_player_event(
            self.user,
            "series",
            "tt900%3A1%3A2",
            "action=stop&currentTime=1410000&duration=1500000",
            now=ended + timedelta(minutes=1),
        )

        self.assertEqual(self._plays(), 1)

    def test_a_player_stop_then_a_library_watched_appends_one_play(self):
        """The two producers share one session, so they append one play.

        A client that emits events sends both a `player` stop and a `library`
        watched flag for the same viewing. They are the same session (the
        library event names the same video id), so the flag must not append a
        second history row.
        """
        ended = timezone.now()
        tracker.record_player_event(
            self.user,
            "series",
            "tt900%3A1%3A2",
            "action=stop&currentTime=1410000&duration=1500000",
            now=ended,
        )
        self.assertEqual(self._plays(), 1)

        tracker.record_library_event(
            self.user,
            "series",
            "tt900",
            "action=watched&videoId=tt900%3A1%3A2",
            now=ended + timedelta(minutes=1),
        )

        self.assertEqual(self._plays(), 1)
