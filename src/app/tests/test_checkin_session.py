from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import checkin, checkin_session, live_playback
from app.models import (
    BoardGame,
    Book,
    Game,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Sources,
    Status,
    Video,
)
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

    def test_a_session_from_before_the_record_changed_is_ignored(self):
        cache.set(f"checkin_session_v1:{self.user.id}", {"media_type": "game"})

        self.assertEqual(self.phase(), checkin.PHASE_IDLE)
        self.start()

    def test_starting_a_game_pauses_a_running_movie_check_in(self):
        movie_item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Heat",
            runtime_minutes=100,
        )
        movie = Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        with (
            patch(
                "app.providers.tmdb.movie",
                return_value={"title": "Heat", "image": ""},
            ),
            patch("app.services.metadata_resolution.upsert_provider_links"),
            patch("app.models.Item.fetch_releases"),
        ):
            checkin.start(self.user, "movie", "603")

        started = cache.get(checkin._key(self.user.id))["started_at_ts"]
        with patch("app.checkin._now_ts", return_value=started + 600):
            self.start()

        self.assertIsNone(cache.get(checkin._key(self.user.id)))
        movie.refresh_from_db()
        self.assertEqual(checkin.phase(self.user, movie)["phase"], checkin.PHASE_PAUSED)

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
            ["start", "create", "edit"],
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


class NowPlayingCardTests(SessionTestCase):
    """Anything checked in shows on Home as Now Playing, and leaves it when it ends."""

    def card(self):
        return live_playback.peek_user_playback_state(self.user.id)

    def test_start_shows_the_card_with_the_assumed_end(self):
        self.start()

        card = self.card()
        self.assertEqual(card["media_type"], "game")
        self.assertEqual(card["title"], "Hades")
        record = cache.get(checkin_session._key(self.user.id))
        self.assertEqual(card["checkin_token"], record["token"])
        self.assertEqual(record["end_ts"] - record["started_at_ts"], 4 * HOUR)

    def test_stop_cancel_and_the_time_limit_take_the_card_off(self):
        for end in (
            lambda: checkin_session.stop(self.user, "igdb", "game", "1942"),
            lambda: checkin_session.cancel(self.user, "igdb", "game", "1942"),
        ):
            with self.subTest(end=end):
                self.start()
                end()
                self.assertIsNone(self.card())
        self.start()
        with self.at(4 * HOUR + 1):
            self.phase()
        self.assertIsNone(self.card())

    def test_a_card_from_something_else_is_left_alone(self):
        self.start()
        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.play",
            playback_media_type="movie",
            media_id="603",
            source="tmdb",
            title="Heat",
        )

        checkin_session.stop(self.user, "igdb", "game", "1942")

        self.assertEqual(self.card()["title"], "Heat")


class ReadingSessionTests(SessionTestCase):
    """Books and manga are read on the latest entry; Stop hands over to the edit dialog."""

    media_type = MediaTypes.BOOK.value
    model = Book

    def start(self):
        checkin_session.start(self.user, "openlibrary", self.media_type, "1942")

    def setUp(self):
        super().setUp()
        Item.objects.filter(pk=self.item.pk).update(source="openlibrary")

    def test_a_finished_book_starts_a_new_read(self):
        self.start()

        read = Book.objects.exclude(pk=self.earlier.pk).get()
        self.assertEqual(read.status, Status.IN_PROGRESS.value)
        self.assertEqual(read.entry_source, "check-in")
        self.assertEqual(
            live_playback.peek_user_playback_state(self.user.id)["media_type"], "book"
        )

    def test_an_unfinished_book_is_picked_up_where_it_is(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)

        self.start()

        self.assertEqual(Book.objects.count(), 1)
        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.status, Status.IN_PROGRESS.value)
        self.assertIsNotNone(self.earlier.start_date)

    def test_stop_sets_the_end_date_and_leaves_the_pages_to_the_reader(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()

        checkin_session.stop(self.user, "openlibrary", "book", "1942")

        self.earlier.refresh_from_db()
        self.assertIsNotNone(self.earlier.end_date)
        self.assertEqual(self.earlier.progress, 0)
        self.assertIsNone(live_playback.peek_user_playback_state(self.user.id))

    def test_stop_adds_the_elapsed_minutes_to_reading_time(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()

        with self.at(95 * 60 + 10):
            checkin_session.stop(self.user, "openlibrary", "book", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 96)

    def test_a_second_session_adds_to_the_same_read(self):
        Book.objects.filter(pk=self.earlier.pk).update(
            status=Status.IN_PROGRESS.value,
            reading_time=30,
        )
        self.start()

        with self.at(20 * 60):
            checkin_session.stop(self.user, "openlibrary", "book", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 50)

    def test_a_re_read_starts_its_own_reading_time(self):
        Book.objects.filter(pk=self.earlier.pk).update(reading_time=300)
        self.start()

        with self.at(10 * 60):
            checkin_session.stop(self.user, "openlibrary", "book", "1942")

        read = Book.objects.exclude(pk=self.earlier.pk).get()
        self.assertEqual(read.reading_time, 10)
        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 300)

    def test_a_replaced_check_in_keeps_the_time_read(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()

        with self.at(15 * 60):
            self.start()

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 15)

    def test_cancel_and_a_forgotten_session_add_no_reading_time(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()
        checkin_session.cancel(self.user, "openlibrary", "book", "1942")
        self.start()

        with self.at(5 * HOUR):
            checkin_session.settle(self.user.id)

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 0)

    def test_an_audiobook_has_no_reading_time(self):
        Item.objects.filter(pk=self.item.pk).update(format="audiobook")
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()

        with self.at(30 * 60):
            checkin_session.stop(self.user, "openlibrary", "book", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.reading_time, 0)

    def test_manga_reading_time_builds_up_on_its_one_entry(self):
        item = Item.objects.create(
            media_id="5",
            source=Sources.MANGAUPDATES.value,
            media_type=MediaTypes.MANGA.value,
            title="Berserk",
        )
        row = Manga.objects.create(
            item=item, user=self.user, status=Status.COMPLETED.value, reading_time=40
        )

        checkin_session.start(self.user, "mangaupdates", "manga", "5")
        with self.at(25 * 60):
            checkin_session.stop(self.user, "mangaupdates", "manga", "5")

        row.refresh_from_db()
        self.assertEqual(row.reading_time, 65)

    def test_cancel_puts_the_entry_back(self):
        Book.objects.filter(pk=self.earlier.pk).update(status=Status.PLANNING.value)
        self.start()

        checkin_session.cancel(self.user, "openlibrary", "book", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.status, Status.PLANNING.value)
        self.assertIsNone(self.earlier.start_date)

    def test_cancel_removes_a_re_read_it_started(self):
        self.start()

        checkin_session.cancel(self.user, "openlibrary", "book", "1942")

        self.assertEqual(list(Book.objects.all()), [self.earlier])

    def test_a_finished_manga_is_reopened_not_duplicated(self):
        item = Item.objects.create(
            media_id="5",
            source=Sources.MANGAUPDATES.value,
            media_type=MediaTypes.MANGA.value,
            title="Berserk",
        )
        row = Manga.objects.create(
            item=item, user=self.user, status=Status.COMPLETED.value
        )

        checkin_session.start(self.user, "mangaupdates", "manga", "5")

        self.assertEqual(Manga.objects.count(), 1)
        row.refresh_from_db()
        self.assertEqual(row.status, Status.IN_PROGRESS.value)

    def test_actions(self):
        idle = checkin.phase(self.user, self.earlier)
        keys = lambda status, phase: [  # noqa: E731
            a["key"] for a in track_actions("book", status, phase)
        ]
        self.assertEqual(
            keys(Status.COMPLETED.value, idle), ["create", "start", "edit"]
        )
        self.assertEqual(keys(Status.PLANNING.value, idle), ["start", "edit"])
        manga = track_actions("manga", Status.COMPLETED.value, idle)
        self.assertEqual([a["key"] for a in manga], ["start", "edit"])
        self.start()
        self.earlier.item.refresh_from_db()
        running = track_actions(
            "book", Status.COMPLETED.value, checkin.phase(self.user, self.earlier)
        )
        self.assertEqual([a["key"] for a in running], ["stop", "cancel", "edit"])
        self.assertEqual(running[0]["then"], "edit")


class VideoSessionTests(SessionTestCase):
    media_type = MediaTypes.VIDEO.value
    model = Video

    def start(self):
        checkin_session.start(self.user, "youtube", "video", "1942")

    def setUp(self):
        super().setUp()
        Item.objects.filter(pk=self.item.pk).update(source="youtube")
        Video.objects.filter(pk=self.earlier.pk).update(
            status=Status.PLANNING.value,
            length_seconds=600,
        )
        self.earlier.refresh_from_db()

    def test_the_card_ends_when_the_video_does(self):
        self.start()

        record = cache.get(checkin_session._key(self.user.id))
        self.assertEqual(record["end_ts"] - record["started_at_ts"], 600)

    def test_stop_saves_the_time_watched(self):
        self.start()

        with self.at(300):
            checkin_session.stop(self.user, "youtube", "video", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.progress, 300)
        self.assertEqual(self.earlier.status, Status.IN_PROGRESS.value)

    def test_watching_to_the_end_completes_it(self):
        self.start()

        with self.at(601):
            self.phase()

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.status, Status.COMPLETED.value)

    def test_a_card_that_expired_first_does_not_lose_the_watch(self):
        self.start()
        live_playback.clear_user_playback_state(self.user.id)

        with self.at(601):
            self.phase()

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.status, Status.COMPLETED.value)

    def test_cancel_saves_nothing(self):
        self.start()

        checkin_session.cancel(self.user, "youtube", "video", "1942")

        self.earlier.refresh_from_db()
        self.assertEqual(self.earlier.progress, 0)


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

    def test_start_then_stop_updates_tracking_without_reloading(self):
        started = self.client.post(self.url(), {"action": "start"})
        stopped = self.client.post(self.url(), {"action": "stop"})

        for response in (started, stopped):
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("HX-Refresh", response)
            self.assertContains(response, 'hx-swap-oob="outerHTML"')
            self.assertNotContains(response, "detail-carousel-wrap")
        self.assertEqual(Game.objects.count(), 2)

    def test_refresh_keeps_the_same_session_and_modal_targets(self):
        started = self.client.post(self.url(), {"action": "start"})
        current = Game.objects.order_by("-id").first()
        self.assertContains(started, "Stop</span>")
        self.assertContains(started, f'"instance_id": "{current.id}"')
        count = Game.objects.count()
        with patch("app.providers.services.get_media_metadata", side_effect=AssertionError("provider called")):
            refreshed = self.client.post(self.url(), {"action": "refresh"})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(Game.objects.count(), count)
        self.assertContains(refreshed, "/details/igdb/game/1942/hades")
        self.assertNotContains(refreshed, "location.reload()")
        cancelled = self.client.post(self.url(), {"action": "cancel"})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(list(Game.objects.all()), [self.earlier])
        self.assertContains(cancelled, "Check-in</span>")

    def test_now_playing_stop_saves_elapsed_game_time(self):
        self.client.post(self.url(), {"action": "start"})
        record = checkin_session._record(self.user.id)
        card = live_playback.build_home_playback_card(self.user)
        self.assertEqual(card["checkin_control"]["action"], "stop")
        with patch("app.checkin_session._now_ts", return_value=record["started_at_ts"] + 120):
            response = self.client.post(self.url(), {
                "action": "stop", "from_now_playing": "1", "checkin_token": record["token"],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertNotIn("HX-Refresh", response)
        self.assertIsNone(live_playback.build_home_playback_card(self.user))
        self.assertEqual(Game.objects.get(pk=record["row_id"]).progress, 2)

    def test_now_playing_cancel_removes_the_session_it_started(self):
        self.client.post(self.url(), {"action": "start"})
        record = checkin_session._record(self.user.id)
        fragment = self.client.get(reverse("active_playback_fragment"))
        self.assertContains(fragment, 'aria-label="Stop check-in"')
        self.assertContains(fragment, 'aria-label="Cancel check-in"')
        self.assertContains(fragment, "rounded-full", count=2)
        response = self.client.post(self.url(), {
            "action": "cancel", "from_now_playing": "1", "checkin_token": record["token"],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertEqual(list(Game.objects.all()), [self.earlier])
        self.assertIsNone(live_playback.build_home_playback_card(self.user))

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

    def test_stop_can_hand_over_to_the_edit_dialog(self):
        self.client.post(self.url(), {"action": "start"})

        response = self.client.post(self.url(), {"action": "stop", "then": "edit"})

        self.assertEqual(response.status_code, 204)
        self.assertNotIn("HX-Refresh", response)
