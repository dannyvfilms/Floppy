from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app import checkin, live_playback
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Season,
    Sources,
    Status,
)

RUNTIME_MINUTES = 100
RUNTIME_SECONDS = RUNTIME_MINUTES * 60


@contextmanager
def no_provider_calls():
    """The movie scrobble path asks TMDB for metadata; answer from memory."""
    with (
        patch(
            "app.providers.tmdb.movie",
            return_value={"title": "Heat", "image": ""},
        ),
        patch("app.services.metadata_resolution.upsert_provider_links"),
        patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": 1},
        ),
        patch("app.models.Item.fetch_releases"),
    ):
        yield


class CheckInTests(TestCase):
    """A movie check-in: start, Pause, Finish, Cancel and the assumed end."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="checkin",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Heat",
            image="http://example.com/heat.jpg",
            runtime_minutes=RUNTIME_MINUTES,
        )

    def movie(self, status):
        return Movie.objects.create(item=self.item, user=self.user, status=status)

    def start(self):
        with no_provider_calls():
            checkin.start(self.user, "movie", "603")

    def card(self):
        return live_playback.peek_user_playback_state(self.user.id)

    def phase(self, instance):
        return checkin.phase(self.user, instance)["phase"]

    def at(self, seconds_after_start):
        """Pretend the clock is this many seconds after the check-in began."""
        record = cache.get(checkin._key(self.user.id))
        return patch(
            "app.checkin._now_ts",
            return_value=record["started_at_ts"] + seconds_after_start,
        )

    def test_start_saves_in_progress_and_puts_a_card_on_home(self):
        planning = self.movie(Status.PLANNING.value)

        self.start()

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.IN_PROGRESS.value)
        self.assertIsNotNone(planning.start_date)
        self.assertEqual(planning.entry_source, "check-in")
        card = self.card()
        self.assertEqual(card["media_id"], "603")
        self.assertEqual(card["duration_seconds"], RUNTIME_SECONDS)
        self.assertTrue(card["checkin_token"])
        self.assertIsNotNone(card["scrobble_expires_at_ts"])
        self.assertEqual(self.phase(planning), checkin.PHASE_ACTIVE)

    def test_start_on_a_completed_movie_adds_a_rewatch_row(self):
        done = self.movie(Status.COMPLETED.value)

        self.start()

        done.refresh_from_db()
        self.assertEqual(done.status, Status.COMPLETED.value)
        self.assertEqual(
            Movie.objects.filter(
                item=self.item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            ).count(),
            1,
        )

    def test_start_needs_a_tracked_movie(self):
        Item.objects.all().delete()

        with self.assertRaises(checkin.CheckInError):
            checkin.start(self.user, "movie", "603")

    def test_button_turns_from_pause_to_finish_near_the_end(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        with self.at(RUNTIME_SECONDS * 0.5):
            self.assertEqual(self.phase(planning), checkin.PHASE_ACTIVE)
        with self.at(RUNTIME_SECONDS * 0.95):
            self.assertEqual(self.phase(planning), checkin.PHASE_FINISHABLE)

    def test_reload_hint_points_at_the_next_label_change(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        with self.at(0):
            info = checkin.phase(self.user, planning)
        self.assertEqual(info["reload_in"], int(RUNTIME_SECONDS * 0.9))

    def test_assumed_end_completes_the_movie_at_the_expected_time(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()
        record = cache.get(checkin._key(self.user.id))

        with self.at(RUNTIME_SECONDS + 1):
            self.assertEqual(self.phase(planning), checkin.PHASE_IDLE)

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.COMPLETED.value)
        self.assertEqual(planning.progress, 1)
        self.assertEqual(
            planning.end_date,
            datetime.fromtimestamp(record["end_ts"], tz=UTC).replace(second=0),
        )
        self.assertIsNone(cache.get(checkin._key(self.user.id)))
        self.assertTrue(
            PlaybackProgress.objects.get(user=self.user, item=self.item).completed,
        )

    def test_settle_before_the_end_does_nothing(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        with self.at(RUNTIME_SECONDS - 60):
            checkin.settle(self.user.id)

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.IN_PROGRESS.value)
        self.assertIsNotNone(cache.get(checkin._key(self.user.id)))

    def test_a_real_scrobble_takes_the_card_over(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        # Plex reports the same movie while the check-in is open.
        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id="603",
            source=Sources.TMDB.value,
            rating_key="plex-1",
            title="Heat",
            duration_seconds=RUNTIME_SECONDS,
            image="http://example.com/heat.jpg",
        )
        self.assertNotIn("checkin_token", self.card())

        with self.at(RUNTIME_SECONDS + 1):
            self.assertEqual(self.phase(planning), checkin.PHASE_IDLE)

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.IN_PROGRESS.value)
        self.assertIsNone(cache.get(checkin._key(self.user.id)))
        self.assertIsNotNone(self.card())

    def test_scrobbler_completes_the_check_in_row_instead_of_adding_one(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor

        with no_provider_calls():
            GenericScrobbleProcessor().process_payload(
                {
                    "media_type": "movie",
                    "ids": {"tmdb": "603"},
                    "completed": True,
                },
                self.user,
            )

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.COMPLETED.value)
        self.assertEqual(Movie.objects.filter(item=self.item).count(), 1)

    def test_a_movie_finished_elsewhere_is_not_completed_twice(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()
        Movie.objects.filter(pk=planning.pk).update(status=Status.COMPLETED.value)

        with self.at(RUNTIME_SECONDS + 1):
            checkin.settle(self.user.id)

        self.assertEqual(Movie.objects.filter(item=self.item).count(), 1)

    def test_pause_keeps_the_position_and_resume_continues_from_it(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        with self.at(30 * 60):
            checkin.pause(self.user, "movie", "603")

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.IN_PROGRESS.value)
        self.assertIsNone(self.card())
        saved = PlaybackProgress.objects.get(user=self.user, item=self.item)
        self.assertEqual(saved.position_seconds, 30 * 60)
        self.assertFalse(saved.completed)
        self.assertEqual(self.phase(planning), checkin.PHASE_PAUSED)

        self.start()
        record = cache.get(checkin._key(self.user.id))
        self.assertEqual(record["offset"], 30 * 60)
        self.assertEqual(
            record["end_ts"] - record["started_at_ts"],
            RUNTIME_SECONDS - 30 * 60,
        )
        self.assertEqual(self.card()["view_offset_seconds"], 30 * 60)

    def test_finish_completes_now_and_closes_the_card(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        with self.at(RUNTIME_SECONDS * 0.95):
            checkin.finish(self.user, "movie", "603")

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.COMPLETED.value)
        self.assertIsNotNone(planning.end_date)
        self.assertIsNone(self.card())
        self.assertIsNone(cache.get(checkin._key(self.user.id)))

    def test_cancel_removes_the_row_the_check_in_added(self):
        done = self.movie(Status.COMPLETED.value)
        self.start()

        checkin.cancel(self.user, "movie", "603")

        self.assertEqual(list(Movie.objects.filter(item=self.item)), [done])
        self.assertIsNone(self.card())

    def test_cancel_restores_a_planning_movie(self):
        planning = self.movie(Status.PLANNING.value)
        self.start()

        checkin.cancel(self.user, "movie", "603")

        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.PLANNING.value)
        self.assertIsNone(planning.start_date)

    def test_actions_need_a_running_check_in(self):
        self.movie(Status.PLANNING.value)

        for action in (checkin.pause, checkin.finish, checkin.cancel):
            with self.subTest(action=action.__name__):
                with self.assertRaises(checkin.CheckInError):
                    action(self.user, "movie", "603")

    def test_a_movie_without_a_runtime_has_no_end_to_assume(self):
        self.item.runtime_minutes = None
        self.item.save()
        planning = self.movie(Status.PLANNING.value)
        self.start()
        record = cache.get(checkin._key(self.user.id))
        self.assertIsNone(record["end_ts"])

        with self.at(24 * 60 * 60):
            self.assertEqual(self.phase(planning), checkin.PHASE_FINISHABLE)
        planning.refresh_from_db()
        self.assertEqual(planning.status, Status.IN_PROGRESS.value)

    def test_other_sources_cannot_be_checked_in(self):
        self.assertFalse(checkin.supports(MediaTypes.MOVIE.value, Sources.MANUAL.value))
        self.assertFalse(checkin.supports(MediaTypes.GAME.value, Sources.TMDB.value))


class CheckInShowTests(TestCase):
    """A show check-in is of the next unwatched episode, and saves an open play."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="checkin-show",
            password="12345",
        )
        self.show_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
            image="http://example.com/friends.jpg",
        )
        self.show = TV.objects.create(
            item=self.show_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="",
            season_number=2,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.show,
            status=Status.IN_PROGRESS.value,
        )
        from events.models import Event

        for number in range(1, 4):
            Event.objects.create(
                item=season_item,
                content_number=number,
                datetime=timezone.now(),
            )
        self.episodes = {
            number: Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Friends",
                image="",
                season_number=2,
                episode_number=number,
                runtime_minutes=20,
            )
            for number in range(1, 4)
        }
        patcher = patch(
            "app.models.Season.get_episode_item",
            side_effect=lambda number, *args, **kwargs: self.episodes[int(number)],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self):
        checkin.start(self.user, "tv", "1668")

    def card(self):
        return live_playback.peek_user_playback_state(self.user.id)

    def at(self, seconds_after_start):
        record = cache.get(checkin._key(self.user.id))
        return patch(
            "app.checkin._now_ts",
            return_value=record["started_at_ts"] + seconds_after_start,
        )

    def watched(self, number):
        Episode.objects.create(
            item=self.episodes[number],
            related_season=self.season,
            end_date=timezone.now(),
        )

    def open_plays(self):
        return Episode.objects.filter(
            related_season=self.season,
            status=Status.IN_PROGRESS.value,
        )

    def test_idle_label_names_the_next_episode(self):
        self.watched(1)

        info = checkin.phase(self.user, self.show)

        self.assertEqual(info["phase"], checkin.PHASE_IDLE)
        self.assertEqual(info["code"], "S02E02")

    def test_start_opens_the_next_episode_and_puts_a_card_on_home(self):
        self.watched(1)

        self.start()

        play = self.open_plays().get()
        self.assertEqual(play.item, self.episodes[2])
        self.assertIsNotNone(play.start_date)
        self.assertIsNone(play.end_date)
        self.assertEqual(play.entry_source, "check-in")
        card = self.card()
        self.assertEqual(card["episode_number"], 2)
        self.assertEqual(card["series_title"], "Friends")
        self.assertEqual(card["duration_seconds"], 20 * 60)
        info = checkin.phase(self.user, self.show)
        self.assertEqual(info["phase"], checkin.PHASE_ACTIVE)
        self.assertEqual(info["code"], "S02E02")

    def test_assumed_end_completes_the_episode(self):
        self.start()
        record = cache.get(checkin._key(self.user.id))

        with self.at(20 * 60 + 1):
            info = checkin.phase(self.user, self.show)

        play = Episode.objects.get(related_season=self.season, item=self.episodes[1])
        self.assertEqual(play.status, Status.COMPLETED.value)
        self.assertEqual(
            play.end_date,
            datetime.fromtimestamp(record["end_ts"], tz=UTC).replace(second=0),
        )
        self.assertIsNone(self.card())
        # The next check-in moves on to the following episode.
        self.assertEqual(info["code"], "S02E02")

    def test_pause_then_resume_continues_the_same_episode(self):
        self.start()

        with self.at(5 * 60):
            checkin.pause(self.user, "tv", "1668")

        self.assertIsNone(self.card())
        self.assertEqual(self.open_plays().count(), 1)
        info = checkin.phase(self.user, self.show)
        self.assertEqual(info["phase"], checkin.PHASE_PAUSED)
        self.assertEqual(info["code"], "S02E01")

        self.start()

        self.assertEqual(self.open_plays().count(), 1)
        record = cache.get(checkin._key(self.user.id))
        self.assertEqual(record["offset"], 5 * 60)

    def test_finish_completes_now(self):
        self.start()

        with self.at(19 * 60):
            checkin.finish(self.user, "tv", "1668")

        self.assertFalse(self.open_plays().exists())
        self.assertEqual(
            Episode.objects.get(item=self.episodes[1]).status,
            Status.COMPLETED.value,
        )
        self.assertIsNone(self.card())

    def test_cancel_removes_the_play_it_added(self):
        self.start()

        checkin.cancel(self.user, "tv", "1668")

        self.assertFalse(Episode.objects.filter(related_season=self.season).exists())
        self.assertIsNone(self.card())

    def test_cancel_keeps_a_play_that_was_already_open(self):
        Episode.objects.create(
            item=self.episodes[1],
            related_season=self.season,
            status=Status.IN_PROGRESS.value,
            start_date=timezone.now(),
        )
        self.start()

        checkin.cancel(self.user, "tv", "1668")

        self.assertEqual(self.open_plays().count(), 1)

    def test_a_show_with_no_episode_left_has_no_check_in(self):
        for number in range(1, 4):
            self.watched(number)

        self.assertIsNone(checkin.phase(self.user, self.show))
        with self.assertRaises(checkin.CheckInError):
            self.start()

    def test_an_episode_the_provider_does_not_list_is_a_clear_error(self):
        from app.services.episode_coordinates import InvalidEpisodeCoordinateError

        with patch(
            "app.models.Season.get_episode_item",
            side_effect=InvalidEpisodeCoordinateError("Episode 2x1 was not found."),
        ):
            with self.assertRaises(checkin.CheckInError):
                self.start()

        self.assertFalse(self.open_plays().exists())

    def test_untracked_show_cannot_be_checked_in(self):
        TV.objects.all().delete()

        with self.assertRaises(checkin.CheckInError):
            self.start()

    def test_a_movie_check_in_does_not_change_the_show_label(self):
        movie_item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Heat",
            runtime_minutes=100,
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        with no_provider_calls():
            checkin.start(self.user, "movie", "603")

        info = checkin.phase(self.user, self.show)

        self.assertEqual(info["phase"], checkin.PHASE_IDLE)
        self.assertEqual(info["code"], "S02E01")

    def test_the_button_endpoint_accepts_a_show(self):
        self.client.login(username="checkin-show", password="12345")
        url = reverse(
            "checkin_action",
            kwargs={"source": "tmdb", "media_type": "tv", "media_id": "1668"},
        )

        response = self.client.post(url, {"action": "start"})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.open_plays().count(), 1)


class CheckInViewTests(TestCase):
    """The endpoint behind the button."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="checkin-view",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Heat",
            image="http://example.com/heat.jpg",
            runtime_minutes=RUNTIME_MINUTES,
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        self.url = reverse(
            "checkin_action",
            kwargs={"source": "tmdb", "media_type": "movie", "media_id": "603"},
        )
        self.client.login(username="checkin-view", password="12345")

    def test_start_then_pause_refreshes_the_page(self):
        with no_provider_calls():
            started = self.client.post(self.url, {"action": "start"})
        paused = self.client.post(self.url, {"action": "pause"})

        for response in (started, paused):
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response["HX-Refresh"], "true")
        self.assertEqual(
            Movie.objects.get(item=self.item).status,
            Status.IN_PROGRESS.value,
        )

    def test_unknown_action_is_rejected(self):
        self.assertEqual(
            self.client.post(self.url, {"action": "explode"}).status_code, 400
        )

    def test_unsupported_media_is_rejected(self):
        url = reverse(
            "checkin_action",
            kwargs={"source": "igdb", "media_type": "game", "media_id": "1"},
        )
        self.assertEqual(self.client.post(url, {"action": "start"}).status_code, 400)

    def test_action_without_a_check_in_explains_itself(self):
        response = self.client.post(self.url, {"action": "finish"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No check-in", response.content.decode())

    def test_provider_failure_is_a_retryable_error(self):
        with patch(
            "app.checkin._scrobble_movie", side_effect=RuntimeError("tmdb down")
        ):
            response = self.client.post(self.url, {"action": "start"})
        self.assertEqual(response.status_code, 502)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {"action": "start"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
