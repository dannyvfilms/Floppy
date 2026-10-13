from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import checkin, checkin_session
from app.models import BoardGame, Game, Item, MediaTypes, Sources, Status
from app.track_actions import track_actions

HOUR = 60 * 60


class SessionTestCase(TestCase):
    media_type = MediaTypes.GAME.value
    model = Game

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="session",
            password="12345",
        )
        self.item = Item.objects.create(
            media_id="1942",
            source=Sources.IGDB.value,
            media_type=self.media_type,
            title="Hades",
            image="http://example.com/hades.jpg",
        )
        self.earlier = self.model.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=0,
        )
        # Saving asks the provider for the game's length; there is none here.
        patcher = patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": None},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def start(self):
        checkin_session.start(self.user, "igdb", self.media_type, "1942")

    def at(self, seconds_after_start):
        record = cache.get(checkin_session._key(self.user.id))
        return patch(
            "app.checkin_session._now_ts",
            return_value=record["started_at_ts"] + seconds_after_start,
        )

    def phase(self):
        return checkin.phase(self.user, self.earlier)["phase"]


class GameSessionTests(SessionTestCase):
    """A game session is its own entry, saved at the start and finished by Stop."""

    def test_start_saves_a_new_in_progress_entry_beside_the_old_one(self):
        self.start()

        session = Game.objects.exclude(pk=self.earlier.pk).get()
        self.assertEqual(session.status, Status.IN_PROGRESS.value)
        self.assertIsNotNone(session.start_date)
        self.assertIsNone(session.end_date)
        self.assertEqual(session.entry_source, "check-in")
        self.assertEqual(self.phase(), checkin_session.PHASE_SESSION)
        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.status, Status.COMPLETED.value)

    def test_stop_adds_the_elapsed_minutes_and_the_end_time(self):
        self.start()

        with self.at(95 * 60 + 10):
            checkin_session.stop(self.user, "igdb", "game", "1942")

        session = Game.objects.exclude(pk=self.earlier.pk).get()
        self.assertEqual(session.progress, 96)
        self.assertIsNotNone(session.end_date)
        self.assertEqual(session.status, Status.IN_PROGRESS.value)
        self.assertEqual(self.phase(), checkin_session.PHASE_IDLE)

    def test_a_quick_session_still_counts_a_minute(self):
        self.start()

        with self.at(5):
            checkin_session.stop(self.user, "igdb", "game", "1942")

        self.assertEqual(Game.objects.exclude(pk=self.earlier.pk).get().progress, 1)

    def test_another_users_tracker_does_not_allow_a_check_in(self):
        stranger = get_user_model().objects.create_user(username="stranger")

        with self.assertRaises(checkin.CheckInError):
            checkin_session.start(stranger, "igdb", "game", "1942")

        self.assertFalse(Game.objects.filter(user=stranger).exists())

    def test_starting_another_game_saves_the_running_one_first(self):
        other = Item.objects.create(
            media_id="77",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Celeste",
        )
        Game.objects.create(item=other, user=self.user, status=Status.PLANNING.value)
        self.start()
        with self.at(30 * 60):
            checkin_session.start(self.user, "igdb", "game", "77")

        first = Game.objects.filter(item=self.item).exclude(pk=self.earlier.pk).get()
        self.assertEqual(first.progress, 30)
        self.assertIsNotNone(first.end_date)
        record = cache.get(checkin_session._key(self.user.id))
        self.assertEqual(record["media_id"], "77")

    def test_cancel_removes_the_entry_it_added(self):
        self.start()

        checkin_session.cancel(self.user, "igdb", "game", "1942")

        self.assertEqual(list(Game.objects.all()), [self.earlier])
        self.assertEqual(self.phase(), checkin_session.PHASE_IDLE)

    def test_cancel_keeps_an_entry_that_was_edited_meanwhile(self):
        self.start()
        Game.objects.exclude(pk=self.earlier.pk).update(progress=45)

        checkin_session.cancel(self.user, "igdb", "game", "1942")

        self.assertEqual(Game.objects.count(), 2)

    def test_a_forgotten_session_closes_after_four_hours_without_made_up_hours(self):
        self.start()

        with self.at(4 * HOUR + 1):
            self.assertEqual(self.phase(), checkin_session.PHASE_IDLE)

        session = Game.objects.exclude(pk=self.earlier.pk).get()
        self.assertEqual(session.progress, 0)
        self.assertIsNotNone(session.start_date)
        self.assertIsNone(session.end_date)

    def test_a_session_is_still_running_before_the_limit(self):
        self.start()

        with self.at(4 * HOUR - 60):
            self.assertEqual(self.phase(), checkin_session.PHASE_SESSION)

    def test_another_game_does_not_show_this_session(self):
        self.start()
        other = Item.objects.create(
            media_id="7",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Celeste",
        )
        other_row = Game.objects.create(item=other, user=self.user)

        self.assertEqual(
            checkin.phase(self.user, other_row)["phase"],
            checkin_session.PHASE_IDLE,
        )

    def test_start_needs_a_tracked_game(self):
        Game.objects.all().delete()

        with self.assertRaises(checkin.CheckInError):
            self.start()

    def test_stop_needs_a_running_session(self):
        with self.assertRaises(checkin.CheckInError):
            checkin_session.stop(self.user, "igdb", "game", "1942")

    def test_actions_follow_the_session(self):
        idle = checkin.phase(self.user, self.earlier)
        self.assertEqual(
            [a["key"] for a in track_actions("game", Status.COMPLETED.value, idle)],
            ["create", "start", "edit"],
        )
        self.start()
        running = checkin.phase(self.user, self.earlier)
        self.assertEqual(
            [a["key"] for a in track_actions("game", Status.COMPLETED.value, running)],
            ["stop", "cancel", "edit"],
        )


class BoardGameSessionTests(SessionTestCase):
    media_type = MediaTypes.BOARDGAME.value
    model = BoardGame

    def start(self):
        checkin_session.start(self.user, "igdb", "boardgame", "1942")

    def plays(self):
        return BoardGame.objects.get(pk=self.earlier.pk).progress

    def test_log_a_play_adds_one_to_the_latest_entry(self):
        checkin_session.log_play(self.user, "igdb", "1942")
        checkin_session.log_play(self.user, "igdb", "1942")

        self.assertEqual(self.plays(), 2)
        self.assertEqual(BoardGame.objects.count(), 1)

    def test_start_saves_nothing_until_stop(self):
        self.start()

        self.assertEqual(self.plays(), 0)
        self.assertEqual(BoardGame.objects.count(), 1)
        self.assertEqual(self.phase(), checkin_session.PHASE_SESSION)

    def test_stop_logs_one_play(self):
        self.start()

        checkin_session.stop(self.user, "igdb", "boardgame", "1942")

        self.assertEqual(self.plays(), 1)
        self.assertEqual(self.phase(), checkin_session.PHASE_IDLE)

    def test_cancel_and_a_forgotten_session_log_nothing(self):
        self.start()
        checkin_session.cancel(self.user, "igdb", "boardgame", "1942")
        self.start()
        with self.at(4 * HOUR + 1):
            self.assertEqual(self.phase(), checkin_session.PHASE_IDLE)

        self.assertEqual(self.plays(), 0)

    def test_actions_lead_with_log_a_play(self):
        idle = checkin.phase(self.user, self.earlier)
        self.assertEqual(
            [
                a["key"]
                for a in track_actions("boardgame", Status.COMPLETED.value, idle)
            ],
            ["log_play", "start", "edit"],
        )


class SessionViewTests(SessionTestCase):
    """The same endpoint carries the source, which games need and movies do not."""

    def setUp(self):
        super().setUp()
        self.client.login(username="session", password="12345")

    def url(self, media_type="game"):
        return reverse(
            "checkin_action",
            kwargs={"source": "igdb", "media_type": media_type, "media_id": "1942"},
        )

    def test_start_then_stop_refreshes_the_page(self):
        started = self.client.post(self.url(), {"action": "start"})
        stopped = self.client.post(self.url(), {"action": "stop"})

        for response in (started, stopped):
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response["HX-Refresh"], "true")
        self.assertEqual(Game.objects.count(), 2)

    def test_movie_actions_are_not_available_for_a_game(self):
        for name in ("pause", "finish", "resume"):
            with self.subTest(action=name):
                response = self.client.post(self.url(), {"action": name})
                self.assertEqual(response.status_code, 400)

    def test_stop_without_a_session_explains_itself(self):
        response = self.client.post(self.url(), {"action": "stop"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("No check-in", response.content.decode())

    def test_log_a_play_is_for_board_games(self):
        BoardGame.objects.create(
            item=Item.objects.create(
                media_id="1942",
                source=Sources.IGDB.value,
                media_type=MediaTypes.BOARDGAME.value,
                title="Catan",
            ),
            user=self.user,
        )

        response = self.client.post(self.url("boardgame"), {"action": "log_play"})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(BoardGame.objects.get().progress, 1)
