"""Check-ins of different media types run side by side, one per type."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import checkin, checkin_session, live_playback
from app.models import Game, Item, MediaTypes, Movie, Sources, Status

CLOSE_ENOUGH = 5


def provider_stubs():
    """Answer the movie scrobble path and the game length lookup from memory."""
    return (
        patch(
            "app.providers.tmdb.movie",
            return_value={"title": "Heat", "image": ""},
        ),
        patch("app.services.metadata_resolution.upsert_provider_links"),
        patch(
            "app.providers.services.get_media_metadata",
            return_value={"max_progress": None},
        ),
        patch("app.models.Item.fetch_releases"),
    )


class MultipleCheckInTests(TestCase):
    """A show, a movie and a game can all be checked in at once."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="multi",
            password="12345",
        )
        self.client.login(username="multi", password="12345")
        self.movie_item = self.create_item("603", Sources.TMDB, MediaTypes.MOVIE, "Heat")
        self.other_movie_item = self.create_item(
            "604",
            Sources.TMDB,
            MediaTypes.MOVIE,
            "Ronin",
        )
        self.game_item = self.create_item("1942", Sources.IGDB, MediaTypes.GAME, "Hades")
        self.other_game_item = self.create_item(
            "1943",
            Sources.IGDB,
            MediaTypes.GAME,
            "Celeste",
        )
        for item in (self.movie_item, self.other_movie_item):
            Movie.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        for item in (self.game_item, self.other_game_item):
            Game.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        for patcher in provider_stubs():
            patcher.start()
            self.addCleanup(patcher.stop)

    def create_item(self, media_id, source, media_type, title):
        return Item.objects.create(
            media_id=media_id,
            source=source.value,
            media_type=media_type.value,
            title=title,
            image="http://example.com/art.jpg",
            runtime_minutes=100 if media_type == MediaTypes.MOVIE else None,
        )

    def post(self, source, media_type, media_id, **data):
        url = reverse(
            "checkin_action",
            kwargs={"source": source, "media_type": media_type, "media_id": media_id},
        )
        return self.client.post(url, data)

    def watch_movie(self, media_id="603"):
        return self.post("tmdb", "movie", media_id, action="start")

    def play_game(self, media_id="1942"):
        return self.post("igdb", "game", media_id, action="start")

    def cards(self):
        return live_playback.build_home_playback_cards(self.user)

    def titles(self):
        return [card["title"] for card in self.cards()]

    def test_a_movie_and_a_game_run_together_with_a_card_each(self):
        self.watch_movie()
        self.play_game()

        self.assertCountEqual(self.titles(), ["Heat", "Hades"])
        movie = Movie.objects.get(item=self.movie_item)
        game = Game.objects.get(pk=checkin_session._record(self.user.id, "game")["row_id"])
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertEqual(game.status, Status.IN_PROGRESS.value)

    def test_cards_appear_oldest_first(self):
        self.watch_movie()
        record = checkin._record(self.user.id, "movie")
        with patch(
            "app.live_playback._now_ts",
            return_value=record["started_at_ts"] + 60,
        ):
            self.play_game()
        self.assertEqual(self.titles(), ["Heat", "Hades"])

    def test_the_card_that_started_first_comes_first_whatever_its_type(self):
        self.play_game()
        record = checkin_session._record(self.user.id, "game")
        with patch(
            "app.live_playback._now_ts",
            return_value=record["started_at_ts"] + 60,
        ):
            self.watch_movie()
        self.assertEqual(self.titles(), ["Hades", "Heat"])

    def test_a_second_movie_pauses_the_first_but_leaves_the_game_running(self):
        self.watch_movie("603")
        self.play_game()

        started = checkin._record(self.user.id, "movie")["started_at_ts"]
        with patch("app.checkin._now_ts", return_value=started + 600):
            self.watch_movie("604")

        self.assertEqual(checkin._record(self.user.id, "movie")["media_id"], "604")
        self.assertEqual(checkin_session._record(self.user.id, "game")["media_id"], "1942")
        self.assertCountEqual(self.titles(), ["Ronin", "Hades"])
        first = Movie.objects.get(item=self.movie_item)
        self.assertEqual(first.status, Status.IN_PROGRESS.value)
        self.assertEqual(
            checkin.phase(self.user, first)["phase"],
            checkin.PHASE_PAUSED,
        )

    def test_a_second_game_saves_the_first_but_leaves_the_movie_running(self):
        self.watch_movie()
        self.play_game("1942")
        record = checkin_session._record(self.user.id, "game")
        with patch(
            "app.checkin_session._now_ts",
            return_value=record["started_at_ts"] + 10 * 60,
        ):
            self.play_game("1943")

        first = Game.objects.get(pk=record["row_id"])
        self.assertEqual(first.progress, 10)
        self.assertIsNotNone(first.end_date)
        self.assertEqual(checkin_session._record(self.user.id, "game")["media_id"], "1943")
        self.assertCountEqual(self.titles(), ["Heat", "Celeste"])

    def test_stopping_the_game_from_its_card_leaves_the_movie_card(self):
        self.watch_movie()
        self.play_game()
        game_record = checkin_session._record(self.user.id, "game")

        with patch(
            "app.checkin_session._now_ts",
            return_value=game_record["started_at_ts"] + 120,
        ):
            response = self.post(
                "igdb",
                "game",
                "1942",
                action="stop",
                from_now_playing="1",
                checkin_token=game_record["token"],
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Heat")
        self.assertNotContains(response, "Hades")
        self.assertEqual(self.titles(), ["Heat"])
        self.assertEqual(Game.objects.get(pk=game_record["row_id"]).progress, 2)
        self.assertIsNotNone(checkin._record(self.user.id, "movie"))

    def test_cancelling_the_movie_from_its_card_leaves_the_game_card(self):
        self.watch_movie()
        self.play_game()
        movie_record = checkin._record(self.user.id, "movie")

        response = self.post(
            "tmdb",
            "movie",
            "603",
            action="cancel",
            from_now_playing="1",
            checkin_token=movie_record["token"],
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hades")
        self.assertEqual(self.titles(), ["Hades"])
        self.assertEqual(
            Movie.objects.get(item=self.movie_item).status,
            Status.PLANNING.value,
        )
        self.assertIsNotNone(checkin_session._record(self.user.id, "game"))

    def test_a_card_button_cannot_act_on_another_types_check_in(self):
        self.watch_movie()
        self.play_game()
        game_token = checkin_session._record(self.user.id, "game")["token"]

        response = self.post(
            "tmdb",
            "movie",
            "603",
            action="pause",
            from_now_playing="1",
            checkin_token=game_token,
        )

        self.assertEqual(response.status_code, 400)
        self.assertCountEqual(self.titles(), ["Heat", "Hades"])

    def test_the_fragment_lists_every_running_check_in(self):
        self.watch_movie()
        self.play_game()

        response = self.client.get(reverse("active_playback_fragment"))

        self.assertContains(response, "data-active-playback-card", count=2)
        self.assertContains(response, 'aria-label="Stop check-in"', count=2)

    def test_the_fragment_is_empty_when_nothing_is_running(self):
        self.assertEqual(self.client.get(reverse("active_playback_fragment")).content, b"")

    def test_each_type_settles_on_its_own_clock(self):
        self.watch_movie()
        self.play_game()
        movie_record = checkin._record(self.user.id, "movie")

        with patch(
            "app.checkin._now_ts",
            return_value=movie_record["end_ts"] + CLOSE_ENOUGH + 1,
        ):
            checkin.settle(self.user.id)

        self.assertEqual(
            Movie.objects.get(item=self.movie_item).status,
            Status.COMPLETED.value,
        )
        self.assertIsNone(checkin._record(self.user.id, "movie"))
        self.assertIsNotNone(checkin_session._record(self.user.id, "game"))
        self.assertEqual(self.titles(), ["Hades"])

    def test_a_scrobble_of_the_same_movie_takes_over_only_that_card(self):
        self.watch_movie()
        self.play_game()

        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id="603",
            source=Sources.TMDB.value,
            title="Heat",
            image="http://example.com/art.jpg",
            view_offset_seconds=30,
            duration_seconds=6000,
        )

        cards = self.cards()
        self.assertEqual([card["title"] for card in cards], ["Heat", "Hades"])
        self.assertIsNone(cards[0]["checkin_control"])
        self.assertIsNotNone(cards[1]["checkin_control"])
        self.assertTrue(checkin._record(self.user.id, "movie")["taken_over"])

    def test_a_scrobble_of_another_movie_leaves_the_check_in_card(self):
        self.watch_movie("603")

        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id="604",
            source=Sources.TMDB.value,
            title="Ronin",
            image="http://example.com/art.jpg",
            view_offset_seconds=30,
            duration_seconds=6000,
        )

        cards = self.cards()
        self.assertEqual([card["title"] for card in cards], ["Ronin", "Heat"])
        self.assertIsNone(cards[0]["checkin_control"])
        self.assertIsNotNone(cards[1]["checkin_control"])
        self.assertFalse(checkin._record(self.user.id, "movie").get("taken_over"))

    def test_checking_in_to_what_is_already_scrobbling_replaces_that_card(self):
        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.play",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id="603",
            source=Sources.TMDB.value,
            title="Heat",
            image="http://example.com/art.jpg",
            view_offset_seconds=30,
            duration_seconds=6000,
        )

        self.watch_movie("603")

        cards = self.cards()
        self.assertEqual(len(cards), 1)
        self.assertIsNotNone(cards[0]["checkin_control"])

    def test_a_scrobble_stop_for_the_same_title_drops_its_check_in_card(self):
        self.watch_movie()
        self.play_game()

        live_playback.apply_playback_event(
            user_id=self.user.id,
            event_type="media.stop",
            playback_media_type=MediaTypes.MOVIE.value,
            media_id="603",
            source=Sources.TMDB.value,
            view_offset_seconds=30,
            duration_seconds=6000,
        )

        self.assertEqual(self.titles(), ["Hades"])
        self.assertTrue(checkin._record(self.user.id, "movie")["taken_over"])

    def test_the_now_playing_api_reports_the_first_running_check_in(self):
        from api.fork_views_playback import build_now_playing_payload

        self.assertIsNone(build_now_playing_payload(self.user))
        self.watch_movie()
        self.play_game()

        payload = build_now_playing_payload(self.user)

        self.assertEqual(payload["title"], "Heat")
        checkin.pause(self.user, "movie", "603")
        self.assertEqual(build_now_playing_payload(self.user)["title"], "Hades")

    def test_other_users_check_ins_do_not_show(self):
        other = get_user_model().objects.create_user(username="other", password="12345")
        Movie.objects.create(
            item=self.movie_item,
            user=other,
            status=Status.PLANNING.value,
        )
        checkin.start(other, "movie", "603")

        self.assertEqual(self.cards(), [])
        self.assertEqual(len(live_playback.build_home_playback_cards(other)), 1)
