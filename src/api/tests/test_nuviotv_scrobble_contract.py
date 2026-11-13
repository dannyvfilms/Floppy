"""What Floppy does with the playback events NuvioTV sends.

The bodies below are the ones NuvioTV's Floppy tracker builds
(`FloppyScrobbleBodyTest` in the NuvioTV repository). NuvioTV only knows a
percentage, never seconds, so a stop carries an explicit `completed` flag
(true from 80%) and no position. Start and pause carry neither. NuvioTV does
not send a stop under 1%, which is its own cut-off for a skim.

If one of these breaks, a shipped NuvioTV breaks with it.
"""

from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.utils import timezone

from app import live_playback
from app.models import Item, MediaTypes, Movie, PlaybackProgress, Sources, Status
from integrations.models import IntegrationToken

from .base import FloppyApiTestCase

SCROBBLE = "/api/v1/scrobble/"

MOVIE_START = {
    "action": "start",
    "media_type": "movie",
    "ids": {"imdb": "tt0133093", "tmdb": "603"},
    "title": "The Matrix",
}
MOVIE_STOP_FINISHED = {**MOVIE_START, "action": "stop", "completed": True}
MOVIE_STOP_ABANDONED = {**MOVIE_START, "action": "stop", "completed": False}
EPISODE_STOP_FINISHED = {
    "action": "stop",
    "media_type": "episode",
    "ids": {"imdb": "tt11280740"},
    "series_title": "Severance",
    "title": "Good News About Hell",
    "season_number": 1,
    "episode_number": 1,
    "completed": True,
}

MATRIX = {"title": "The Matrix", "image": "https://example.com/matrix.jpg"}


class NuvioTvScrobbleContractTests(FloppyApiTestCase):
    """The default token NuvioTV is told to create can do everything it needs."""

    def setUp(self):
        """Mint the default-preset token a user pastes into NuvioTV."""
        super().setUp()
        self.token, self.secret = IntegrationToken.generate(
            user=self.user1,
            name="NuvioTV",
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.secret}"}
        tmdb_movie = patch("app.providers.tmdb.movie", return_value=MATRIX)
        self.tmdb_movie = tmdb_movie.start()
        self.addCleanup(tmdb_movie.stop)

    def _scrobble(self, payload, headers=None):
        return self.client.post(
            SCROBBLE,
            payload,
            format="json",
            **(self.headers if headers is None else headers),
        )

    def _matrix(self):
        return Movie.objects.filter(user=self.user1, item__media_id="603")

    def test_start_and_pause_are_accepted_and_record_no_history(self):
        """Playback in progress is a live card, never a watch."""
        for action in ("start", "pause"):
            with self.subTest(action=action):
                response = self._scrobble({**MOVIE_START, "action": action})

                self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(self._matrix().exists())

    def test_finishing_a_movie_records_one_completed_watch(self):
        """A stop at or above NuvioTV's 80% mark completes the movie."""
        response = self._scrobble(MOVIE_STOP_FINISHED)

        self.assertEqual(response.status_code, HTTP.OK)
        movie = self._matrix().get()
        self.assertEqual(movie.status, Status.COMPLETED.value)

    def test_stopping_early_tracks_the_film_as_in_progress_not_watched(self):
        """A stop under 80% is a real end signal: In Progress, never Completed.

        Floppy cannot tell a skim from a pause-and-quit without a position, so
        NuvioTV does not send a stop under 1% (see `floppyScrobbleBody`).
        """
        response = self._scrobble(MOVIE_STOP_ABANDONED)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(self._matrix().get().status, Status.IN_PROGRESS.value)

    def test_a_movie_known_only_by_imdb_is_matched_through_tmdb(self):
        """Stremio-style ids are IMDb first; Floppy resolves them, never by title."""
        payload = {**MOVIE_STOP_FINISHED, "ids": {"imdb": "tt0133093"}}
        found = {"movie_results": [{"id": 603}], "tv_results": []}

        with patch("app.providers.tmdb.find", return_value=found):
            response = self._scrobble(payload)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(self._matrix().exists())

    def test_ids_sent_as_numbers_are_accepted_too(self):
        """Other clients send tmdb as a JSON number; that must not be a 500."""
        payload = {**MOVIE_STOP_FINISHED, "ids": {"tmdb": 603}}

        response = self._scrobble(payload)

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(self._matrix().exists())

    @patch("api.fork_views_scrobble.GenericScrobbleProcessor.process_payload")
    def test_an_episode_stop_carries_what_floppy_needs_to_find_it(self, process):
        """Show title, coordinates and ids reach the processor unchanged."""
        response = self._scrobble(EPISODE_STOP_FINISHED)

        self.assertEqual(response.status_code, HTTP.OK)
        sent = process.call_args.args[0]
        self.assertEqual(sent["media_type"], "episode")
        self.assertEqual(sent["ids"], {"imdb": "tt11280740"})
        self.assertEqual(sent["series_title"], "Severance")
        self.assertEqual((sent["season_number"], sent["episode_number"]), (1, 1))
        self.assertIs(sent["completed"], True)

    def test_an_unresolvable_stop_is_a_client_error_not_a_crash(self):
        """NuvioTV logs the failure and moves on; it must be a 4xx, not a 500."""
        with patch(
            "app.providers.tmdb.movie",
            side_effect=RuntimeError("tmdb down"),
        ):
            response = self._scrobble(MOVIE_STOP_FINISHED)

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_a_revoked_token_is_refused(self):
        """Disconnecting in Floppy takes effect on NuvioTV's next event."""
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])

        response = self._scrobble(MOVIE_START)

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_a_token_without_the_scrobble_permission_is_refused(self):
        """The permission is named, so the user can see why it failed."""
        _token, secret = IntegrationToken.generate(
            user=self.user1,
            name="Read only",
            scopes=["progress:read"],
        )

        response = self._scrobble(
            MOVIE_START,
            headers={"HTTP_AUTHORIZATION": f"Bearer {secret}"},
        )

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_the_connection_check_nuviotv_uses_works_with_the_default_token(self):
        """NuvioTV's Connect button reads the sync connections feed."""
        response = self.client.get("/api/v1/sync/connections/", **self.headers)

        self.assertEqual(response.status_code, HTTP.OK)

    def test_the_connection_check_refuses_a_bad_token(self):
        """A typo in the pasted token is reported, not accepted."""
        response = self.client.get(
            "/api/v1/sync/connections/",
            HTTP_AUTHORIZATION="Bearer flp_not_a_real_token",
        )

        self.assertEqual(response.status_code, HTTP.FORBIDDEN)


class NuvioTvProgressPercentTests(FloppyApiTestCase):
    """NuvioTV sends how far through it is; Floppy turns that into a position."""

    RUNTIME_MINUTES = 120

    def setUp(self):
        """Mint a token and track a two-hour film Floppy already knows the length of."""
        super().setUp()
        _token, secret = IntegrationToken.generate(user=self.user1, name="NuvioTV")
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}
        self.item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="https://example.com/matrix.jpg",
            runtime_minutes=self.RUNTIME_MINUTES,
        )
        for target in ("app.live_playback._attach_resolved_image",):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        tmdb_movie = patch("app.providers.tmdb.movie", return_value=MATRIX)
        tmdb_movie.start()
        self.addCleanup(tmdb_movie.stop)

    def _send(self, action, percent, **extra):
        payload = {**MOVIE_START, "action": action, **extra}
        if percent is not None:
            payload["progress_percent"] = percent
        return self.client.post(SCROBBLE, payload, format="json", **self.headers)

    def _card(self):
        return live_playback.build_home_playback_card(self.user1)

    def test_a_seek_to_half_shows_half_way_not_the_time_played(self):
        """The reported bug: seeking to 50% left the card near the first 10 minutes."""
        self._send("start", 8)
        self.assertEqual(self._card()["offset_seconds"], round(7200 * 0.08))

        self._send("pause", 50)

        card = self._card()
        self.assertEqual(card["offset_seconds"], 3600)
        self.assertEqual(card["progress_percent"], 50)

    def test_seeking_backwards_moves_the_card_back(self):
        """A position reported lower than the last one replaces it."""
        self._send("pause", 70)
        self._send("pause", 20)

        self.assertEqual(self._card()["offset_seconds"], 1440)

    def test_resuming_after_a_pause_continues_from_the_reported_percent(self):
        """Pause then start again: the new percent is the position."""
        self._send("pause", 30)
        self._send("start", 31)

        self.assertEqual(self._card()["offset_seconds"], round(7200 * 0.31))

    def test_an_explicit_position_wins_over_the_percent(self):
        """A client that does send seconds is never second-guessed."""
        self._send("pause", 50, position_seconds=600, duration_seconds=7200)

        self.assertEqual(self._card()["offset_seconds"], 600)

    def test_an_event_duration_wins_over_the_stored_runtime(self):
        """The player's own length is more exact than a provider's runtime."""
        self._send("pause", 50, duration_seconds=4000)

        self.assertEqual(self._card()["offset_seconds"], 2000)

    def test_a_film_of_unknown_length_shows_the_reported_percent(self):
        """With no length to multiply by, the card says what the client said."""
        self.item.delete()

        self._send("pause", 50)

        card = self._card()
        self.assertEqual(card["progress_percent"], 50)
        self.assertEqual(card["progress_display"], "50%")

    def test_stopping_stores_the_resume_position_and_keeps_it_in_progress(self):
        """A stop at 50% leaves a resume point at half, and no completed watch."""
        self._send("start", 5)

        response = self._send("stop", 50, completed=False)

        self.assertEqual(response.status_code, HTTP.OK)
        progress = PlaybackProgress.objects.get(user=self.user1, item=self.item)
        self.assertEqual(progress.position_seconds, 3600)
        self.assertEqual(progress.duration_seconds, 7200)
        self.assertFalse(progress.completed)
        movie = Movie.objects.get(user=self.user1, item=self.item)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertEqual(movie.history.count(), 1)

    def test_finishing_at_the_cutoff_completes_once_and_stores_the_end(self):
        """The 80% rule is still NuvioTV's `completed` flag, not Floppy's guess."""
        response = self._send("stop", 85, completed=True)

        self.assertEqual(response.status_code, HTTP.OK)
        movie = Movie.objects.get(user=self.user1, item=self.item)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        progress = PlaybackProgress.objects.get(user=self.user1, item=self.item)
        self.assertEqual(progress.position_seconds, round(7200 * 0.85))
        self.assertTrue(progress.completed)

    def test_a_percent_never_adds_a_history_entry_by_itself(self):
        """Start and pause with a percent are a live card, not a watch."""
        self._send("start", 90)
        self._send("pause", 95)

        self.assertFalse(Movie.objects.filter(user=self.user1, item=self.item).exists())
        self.assertFalse(PlaybackProgress.objects.filter(user=self.user1, item=self.item).exists())

    def test_a_stop_without_a_percent_still_works_as_before(self):
        """Older NuvioTV builds send no percent; nothing about them changes."""
        response = self._send("stop", None, completed=True)

        self.assertEqual(response.status_code, HTTP.OK)
        movie = Movie.objects.get(user=self.user1, item=self.item)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertFalse(PlaybackProgress.objects.filter(user=self.user1, item=self.item).exists())

    def test_a_percent_outside_zero_to_one_hundred_is_refused(self):
        """A malformed percent is a 400, never silently clamped into a position."""
        for bad in (-1, 100.5, "50", True):
            with self.subTest(percent=bad):
                response = self._send("pause", bad)

                self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_a_first_scrobble_of_an_untracked_film_still_stores_the_position(self):
        """No stored runtime yet: it is read from the provider, not lost."""
        self.item.delete()
        details = {**MATRIX, "max_progress": 1, "details": {"runtime": "2h 16min"}}

        with patch("api.fork_views_scrobble.services.get_media_metadata", return_value=details):
            response = self._send("stop", 50, completed=False)

        self.assertEqual(response.status_code, HTTP.OK)
        progress = PlaybackProgress.objects.get(user=self.user1, item__media_id="603")
        self.assertEqual(progress.position_seconds, 4080)
        self.assertEqual(progress.duration_seconds, 8160)

    def test_a_stop_with_a_percent_but_no_completed_flag_judges_completion(self):
        """Other clients may omit `completed`; 90% and up is a finished film."""
        response = self._send("stop", 100)

        self.assertEqual(response.status_code, HTTP.OK)
        movie = Movie.objects.get(user=self.user1, item=self.item)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        progress = PlaybackProgress.objects.get(user=self.user1, item=self.item)
        self.assertTrue(progress.completed)

    def test_a_stop_at_half_with_no_completed_flag_stays_in_progress(self):
        """Below 90% is not a finished film."""
        self._send("stop", 50)

        movie = Movie.objects.get(user=self.user1, item=self.item)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        progress = PlaybackProgress.objects.get(user=self.user1, item=self.item)
        self.assertFalse(progress.completed)
