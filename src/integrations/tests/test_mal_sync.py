"""Tests for syncing watch status from Floppy to MyAnimeList."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.test import TestCase, override_settings, tag
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    ItemProviderLink,
    Manga,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.providers.services import ProviderAPIError
from integrations import mal_sync, tasks
from integrations.imports.helpers import decrypt
from integrations.models import MALAccount


def _make_user(username="test", password="12345"):  # noqa: S107 (test fixture)
    """Create a user for tests."""
    return get_user_model().objects.create_user(username=username, password=password)


def make_mal_account(
    user,
    *,
    sync_enabled=True,
    per_item_sync_enabled=True,
    connection_broken=False,
    expired=False,
    pull_higher_progress_enabled=True,
    pull_ratings_enabled=True,
):
    """Create a MALAccount for a user with encrypted placeholder tokens."""
    expires_at = timezone.now() + (
        timedelta(hours=-1) if expired else timedelta(hours=1)
    )
    return MALAccount.objects.create(
        user=user,
        mal_username=f"{user.username}_mal",
        access_token=mal_sync.encrypt("old-access-token"),
        refresh_token=mal_sync.encrypt("old-refresh-token"),
        token_expires_at=expires_at,
        sync_enabled=sync_enabled,
        per_item_sync_enabled=per_item_sync_enabled,
        connection_broken=connection_broken,
        pull_higher_progress_enabled=pull_higher_progress_enabled,
        pull_ratings_enabled=pull_ratings_enabled,
    )


def _http_error(response):
    """Build a requests.exceptions.HTTPError carrying the given fake response."""
    return requests.exceptions.HTTPError(response=response)


@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class MALSyncModelHooks(TestCase):
    """Test that Anime/Manga.save() queues MyAnimeList sync at the right times."""

    def setUp(self):
        """Create a user and MAL-backed/non-MAL-backed items."""
        self.user = _make_user()
        self.mal_anime_item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
        )
        self.mal_manga_item = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Test Manga",
        )
        self.tmdb_anime_item = Item.objects.create(
            media_id="3",
            source=Sources.TMDB.value,
            media_type=MediaTypes.ANIME.value,
            title="Test TMDB-sourced Anime",
        )
        self.account = make_mal_account(self.user)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_status_change_queues_anime_sync(self, mock_delay, *_mocks):
        """Changing status on a MAL-backed anime queues a sync."""
        anime = Anime.objects.create(
            user=self.user,
            item=self.mal_anime_item,
            status=Status.PLANNING.value,
        )
        mock_delay.reset_mock()

        anime.status = Status.PAUSED.value
        with self.captureOnCommitCallbacks(execute=True):
            anime.save()

        mock_delay.assert_called_once_with(media_type="anime", media_id=anime.pk, clear_score=False)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_progress_change_queues_sync(self, mock_delay, *_mocks):
        """Changing progress on a MAL-backed anime queues a sync."""
        anime = Anime.objects.create(
            user=self.user,
            item=self.mal_anime_item,
            status=Status.PAUSED.value,
            progress=1,
        )
        mock_delay.reset_mock()

        anime.progress = 2
        with self.captureOnCommitCallbacks(execute=True):
            anime.save()

        mock_delay.assert_called_once_with(media_type="anime", media_id=anime.pk, clear_score=False)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_score_change_queues_sync(self, mock_delay, *_mocks):
        """Changing score on a MAL-backed manga queues a sync."""
        manga = Manga.objects.create(
            user=self.user,
            item=self.mal_manga_item,
            status=Status.PAUSED.value,
        )
        mock_delay.reset_mock()

        manga.score = Decimal("8.0")
        with self.captureOnCommitCallbacks(execute=True):
            manga.save()

        mock_delay.assert_called_once_with(media_type="manga", media_id=manga.pk, clear_score=False)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_plex_history_import_queues_no_per_item_pushes(self, mock_delay, *_mocks):
        """Regression: a Plex history import replays plays through
        _handle_anime, queueing one MAL push per replayed episode.
        """
        from integrations.imports.plex import PlexHistoryImporter

        manga = Manga.objects.create(
            user=self.user, item=self.mal_manga_item, status=Status.PAUSED.value,
        )
        mock_delay.reset_mock()

        def replay_a_play():
            manga.progress = 5
            with self.captureOnCommitCallbacks(execute=True):
                manga.save()

        importer = PlexHistoryImporter.__new__(PlexHistoryImporter)
        with patch.object(PlexHistoryImporter, "_import_data", side_effect=replay_a_play):
            importer.import_data()

        mock_delay.assert_not_called()

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_broker_outage_does_not_fail_the_save(self, mock_delay, *_mocks):
        """Regression: the on-commit enqueue raised after the save committed,
        turning a saved edit into a 500.
        """
        from kombu.exceptions import OperationalError

        manga = Manga.objects.create(
            user=self.user, item=self.mal_manga_item, status=Status.PAUSED.value,
        )
        mock_delay.side_effect = OperationalError("redis down")

        manga.progress = 5
        with self.captureOnCommitCallbacks(execute=True):
            manga.save()

        manga.refresh_from_db()
        self.assertEqual(manga.progress, 5)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_clearing_a_rating_asks_mal_to_clear_it(self, mock_delay, *_mocks):
        """Regression: an empty rating sent no score, so MAL kept the old one
        and the next full sync pulled it back into Floppy.
        """
        manga = Manga.objects.create(
            user=self.user,
            item=self.mal_manga_item,
            status=Status.PAUSED.value,
            score=Decimal("8.0"),
        )
        mock_delay.reset_mock()

        manga.score = None
        with self.captureOnCommitCallbacks(execute=True):
            manga.save()

        mock_delay.assert_called_once_with(
            media_type="manga", media_id=manga.pk, clear_score=True,
        )

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_unrelated_field_change_does_not_queue(self, mock_delay, *_mocks):
        """Editing notes only, with no status/progress/score change, doesn't sync."""
        anime = Anime.objects.create(
            user=self.user,
            item=self.mal_anime_item,
            status=Status.PAUSED.value,
        )
        mock_delay.reset_mock()

        anime.notes = "spoiler-free thoughts"
        with self.captureOnCommitCallbacks(execute=True):
            anime.save()

        mock_delay.assert_not_called()

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_tmdb_backed_anime_never_queues(self, mock_delay, *_mocks):
        """Anime sourced from TMDB (not MAL) never queues a MAL sync."""
        anime = Anime.objects.create(
            user=self.user,
            item=self.tmdb_anime_item,
            status=Status.PLANNING.value,
        )
        mock_delay.reset_mock()

        anime.status = Status.PAUSED.value
        with self.captureOnCommitCallbacks(execute=True):
            anime.save()

        mock_delay.assert_not_called()

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_creating_with_initial_status_queues_sync(self, mock_delay, *_mocks):
        """Adding a new MAL-backed entry queues a sync too, not just later edits."""
        with self.captureOnCommitCallbacks(execute=True):
            anime = Anime.objects.create(
                user=self.user,
                item=self.mal_anime_item,
                status=Status.PAUSED.value,
            )

        mock_delay.assert_called_once_with(media_type="anime", media_id=anime.pk, clear_score=False)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_completion_still_queues_sync_alongside_auto_migration(
        self,
        mock_delay,
        *_mocks,
    ):
        """Completing a flat MAL anime queues a sync even though it also
        triggers Floppy's own auto-migration to episode tracking.
        """
        anime = Anime.objects.create(
            user=self.user,
            item=self.mal_anime_item,
            status=Status.IN_PROGRESS.value,
            progress=1,
        )
        mock_delay.reset_mock()

        anime.status = Status.COMPLETED.value
        with self.captureOnCommitCallbacks(execute=True):
            anime.save()

        mock_delay.assert_called_once_with(media_type="anime", media_id=anime.pk, clear_score=False)

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_no_queue_without_per_item_sync(self, mock_delay, *_mocks):
        """Users without an active MAL connection never queue a push."""
        self.account.delete()
        with self.captureOnCommitCallbacks(execute=True):
            Anime.objects.create(
                user=self.user,
                item=self.mal_anime_item,
                status=Status.PAUSED.value,
            )

        mock_delay.assert_not_called()

    @patch("integrations.tasks.sync_mal_status.delay")
    def test_push_waits_for_the_save_to_commit(self, mock_delay, *_mocks):
        """The worker must not read the entry before its save commits."""
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            anime = Anime.objects.create(
                user=self.user,
                item=self.mal_anime_item,
                status=Status.PAUSED.value,
            )

        mock_delay.assert_not_called()
        for callback in callbacks:
            callback()
        mock_delay.assert_called_once_with(media_type="anime", media_id=anime.pk, clear_score=False)


class MALScore(TestCase):
    """Floppy's decimal scores become whole MAL scores."""

    def test_halves_round_up_and_a_real_rating_is_never_zero(self):
        """Regression: round() sent 8.5 as 8 (halves to even) and 0.3 as 0,
        which MAL reads as no score.
        """
        self.assertEqual(
            [mal_sync.mal_score(Decimal(value)) for value in ("8.5", "7.5", "0.3", "10")],
            [9, 8, 1, 10],
        )


class MALScoreZero(TestCase):
    """A Floppy score of 0 is never pushed to MAL."""

    def test_score_zero_is_left_out_of_the_push(self):
        """Regression: mal_score raised 0 to 1, so every 0-rated entry was
        previewed and pushed to MAL as a rating of 1.
        """
        media = Anime(
            item=Item(media_type=MediaTypes.ANIME.value),
            status=Status.COMPLETED.value, progress=12, score=Decimal(0),
        )

        self.assertNotIn("score", mal_sync.status_payload(media))


class MALClientCredentials(TestCase):
    """The OAuth client ID and secret always come from the same MAL app."""

    def setUp(self):
        cache.clear()
        self.user = _make_user()

    def test_personal_secret_is_not_paired_with_the_shared_client_id(self):
        """Regression: a lone personal secret used Floppy's shared client ID,
        so sign-in opened but every token exchange was rejected.
        """
        from app.providers import credentials

        credentials.set_user("mal", self.user, {"client_secret": "personal-secret"})

        self.assertEqual(mal_sync.client_credentials(self.user), ("", ""))
        self.assertFalse(mal_sync.is_sync_configured(self.user))

    def test_personal_pair_is_used_together(self):
        from app.providers import credentials

        credentials.set_user(
            "mal", self.user,
            {"client_id": "personal-id", "client_secret": "personal-secret"},
        )

        self.assertEqual(
            mal_sync.client_credentials(self.user), ("personal-id", "personal-secret"),
        )

    @override_settings(MAL_API="instance-id", MAL_API_SECRET="instance-secret")
    def test_incomplete_personal_pair_falls_back_to_the_instance_pair(self):
        """A personal client ID alone doesn't borrow the instance secret."""
        from app.providers import credentials

        credentials.set_user("mal", self.user, {"client_id": "personal-id"})

        self.assertEqual(
            mal_sync.client_credentials(self.user), ("instance-id", "instance-secret"),
        )


@override_settings(URLS=["https://floppy.example.com"])
@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class MALOAuthConnectView(TestCase):
    """Test the view that starts the MyAnimeList OAuth flow."""

    def setUp(self):
        """Create and log in a user."""
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_connect_without_configuration_shows_error(self, mock_secret, mock_id):
        """Without both credentials configured, connecting fails clearly."""
        mock_secret.return_value = ""
        response = self.client.post(reverse("mal_oauth"), follow=True)

        self.assertRedirects(response, reverse("import_data"))
        self.assertContains(response, "isn&#x27;t configured")

    def test_connect_redirects_to_mal_with_pkce(self, *_mocks):
        """Connecting redirects to MAL's authorize endpoint with PKCE params."""
        response = self.client.post(reverse("mal_oauth"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(mal_sync.AUTHORIZE_URL))
        self.assertIn("client_id=test_client_id", response.url)
        self.assertIn("code_challenge_method=plain", response.url)

        state_entries = [v for v in self.client.session.values() if isinstance(v, dict)]
        self.assertEqual(len(state_entries), 1)
        self.assertIn("code_verifier", state_entries[0])
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["redirect_uri"], [state_entries[0]["redirect_uri"]])
        self.assertEqual(query["code_challenge"], [state_entries[0]["code_verifier"]])

    @patch("app.helpers.supports_oauth_redirect", return_value=False)
    def test_connect_blocked_on_http_only_instance(self, *_mocks):
        """No device-code fallback exists for MAL, so HTTP-only instances are blocked."""
        response = self.client.post(reverse("mal_oauth"), follow=True)

        self.assertRedirects(response, reverse("import_data"))
        self.assertContains(response, "HTTPS-accessible")


@override_settings(URLS=["https://floppy.example.com"])
@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class MALOAuthCallbackView(TestCase):
    """Test the view that handles MyAnimeList's OAuth callback."""

    def setUp(self):
        """Create and log in a user."""
        self.user = _make_user()
        self.client.force_login(self.user)

    def _seed_state(self):
        response = self.client.post(reverse("mal_oauth"))
        return response.url.split("state=")[1].split("&")[0]

    def test_callback_invalid_state_shows_error(self, *_mocks):
        """A missing/unrecognized state token is rejected."""
        response = self.client.get(
            reverse("mal_callback"),
            {"state": "unknown", "code": "somecode"},
            follow=True,
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(MALAccount.objects.filter(user=self.user).exists())

    def test_callback_missing_code_shows_error(self, *_mocks):
        """A callback with no code param is rejected."""
        state_token = self._seed_state()

        response = self.client.get(
            reverse("mal_callback"),
            {"state": state_token},
            follow=True,
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(MALAccount.objects.filter(user=self.user).exists())

    @patch("integrations.mal_sync.exchange_code_for_tokens")
    def test_reconnect_heals_the_account_when_the_username_lookup_times_out(
        self, exchange, *_mocks,
    ):
        """Regression: a timeout in the username lookup aborted the reconnect
        after saving the tokens, leaving the account broken and paused.
        """
        exchange.return_value = {
            "access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600,
        }
        account = make_mal_account(self.user)
        MALAccount.objects.filter(pk=account.pk).update(
            connection_broken=True, sync_enabled=False, mal_username="OldName",
        )
        with patch(
            "integrations.mal_sync.services.api_request",
            side_effect=ProviderAPIError("mal", requests.Timeout()),
        ):
            mal_sync.connect_account(self.user, "code", "verifier", "http://x/callback")

        account.refresh_from_db()
        self.assertFalse(account.connection_broken)
        self.assertTrue(account.sync_enabled)
        self.assertEqual(account.mal_username, "OldName")

    @patch("requests.Session.get")
    @patch("requests.Session.post")
    def test_callback_success_creates_account(self, mock_post, mock_get, *_mocks):
        """A valid callback exchanges the code and stores the connection."""
        state_token = self._seed_state()

        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }
        mock_post.return_value = token_response
        user_response = MagicMock()
        user_response.json.return_value = {"name": "MyMalUser"}
        mock_get.return_value = user_response

        response = self.client.get(
            reverse("mal_callback"),
            {"state": state_token, "code": "authcode"},
            follow=True,
        )

        self.assertRedirects(response, reverse("import_data"))
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.mal_username, "MyMalUser")
        self.assertEqual(decrypt(account.access_token), "new-access-token")
        self.assertTrue(account.sync_enabled)
        self.assertFalse(account.connection_broken)
        self.assertNotIn(state_token, self.client.session)
        self.assertEqual(mock_post.call_args.kwargs["data"]["code"], "authcode")

    @patch("requests.Session.post")
    def test_callback_mal_error_shows_message(self, mock_post, *_mocks):
        """If MAL rejects the code exchange, no account is created."""
        state_token = self._seed_state()
        error_response = MagicMock(status_code=400, text="invalid_grant")
        error_response.raise_for_status.side_effect = _http_error(error_response)
        mock_post.return_value = error_response

        response = self.client.get(
            reverse("mal_callback"),
            {"state": state_token, "code": "badcode"},
            follow=True,
        )

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(MALAccount.objects.filter(user=self.user).exists())


class MALDisconnectToggleViews(TestCase):
    """Test disconnecting and pausing/resuming sync."""

    def setUp(self):
        """Create and log in a user with a connected MAL account."""
        self.user = _make_user()
        self.client.force_login(self.user)
        self.account = make_mal_account(self.user)

    def test_disconnect_removes_account(self):
        """Disconnecting deletes the MALAccount row."""
        self.client.post(reverse("mal_disconnect"))
        self.assertFalse(MALAccount.objects.filter(user=self.user).exists())

    def test_disconnect_removes_the_scheduled_sync(self):
        """A schedule must not outlive the account it syncs."""
        self.client.post(
            reverse("mal_export_schedule_save"),
            {"frequency": "daily", "time": "03:00"},
        )
        self.assertTrue(
            PeriodicTask.objects.filter(task=tasks.MAL_FULL_SYNC_TASK_NAME).exists(),
        )

        self.client.post(reverse("mal_disconnect"))

        self.assertFalse(
            PeriodicTask.objects.filter(task=tasks.MAL_FULL_SYNC_TASK_NAME).exists(),
        )

    def test_toggle_off_then_on(self):
        """The sync toggle can turn syncing off and back on."""
        self.client.post(reverse("mal_toggle"), {"enabled": "false"})
        self.account.refresh_from_db()
        self.assertFalse(self.account.sync_enabled)

        self.client.post(reverse("mal_toggle"), {"enabled": "true"})
        self.account.refresh_from_db()
        self.assertTrue(self.account.sync_enabled)

    def test_toggle_without_account_shows_error(self):
        """Toggling with no connected account shows an error, not a crash."""
        self.account.delete()
        response = self.client.post(
            reverse("mal_toggle"),
            {"enabled": "true"},
            follow=True,
        )
        self.assertContains(response, "Connect a MyAnimeList account")

    def test_per_item_toggle_off_then_on(self):
        """The per-item toggle can turn per-item pushes off and back on."""
        self.client.post(reverse("mal_per_item_sync_toggle"), {"enabled": "false"})
        self.account.refresh_from_db()
        self.assertFalse(self.account.per_item_sync_enabled)

        self.client.post(reverse("mal_per_item_sync_toggle"), {"enabled": "true"})
        self.account.refresh_from_db()
        self.assertTrue(self.account.per_item_sync_enabled)

    def test_per_item_toggle_leaves_overall_sync_enabled_alone(self):
        """The per-item toggle is independent of the overall sync_enabled flag."""
        self.client.post(reverse("mal_per_item_sync_toggle"), {"enabled": "false"})
        self.account.refresh_from_db()
        self.assertFalse(self.account.per_item_sync_enabled)
        self.assertTrue(self.account.sync_enabled)

    def test_per_item_toggle_without_account_shows_error(self):
        """Toggling with no connected account shows an error, not a crash."""
        self.account.delete()
        response = self.client.post(
            reverse("mal_per_item_sync_toggle"),
            {"enabled": "true"},
            follow=True,
        )
        self.assertContains(response, "Connect a MyAnimeList account")


@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class FullSyncEntriesDuplicateRows(TestCase):
    """Multiple flat rows for the same MAL id must not push an arbitrary one."""

    def setUp(self):
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        self.item = Item.objects.create(
            media_id="55", source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value, title="Rewatched Anime",
        )

    def test_a_completed_rewatch_row_outranks_a_lower_in_progress_row(self, *_mocks):
        """A finished rewatch (full progress) wins over a lower current-watch row."""
        with patch("integrations.tasks.sync_mal_status.delay"):
            Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=3,
            )
            completed_rewatch = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.COMPLETED.value, progress=13,
            )

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].pk, completed_rewatch.pk)
        self.assertEqual(entries[0].progress, 13)


@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class PullHigherMALProgress(TestCase):
    """MAL's own recorded progress is adopted locally when it is ahead."""

    def setUp(self):
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        self.item = Item.objects.create(
            media_id="9253", source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value, title="Steins;Gate",
        )

    def test_higher_remote_progress_is_pulled_in_and_completes_locally(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=5,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "completed", "num_episodes_watched": 24,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.progress, 24)
        self.assertEqual(anime.status, Status.COMPLETED.value)

    def test_entries_the_sync_filters_exclude_are_not_pulled(self, *_mocks):
        """Regression: an unselected run (the schedule) changed Dropped or
        unrated entries that the filters exclude and the preview never shows.
        """
        self.account.sync_filter_dropped = False
        self.account.save(update_fields=["sync_filter_dropped"])
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.DROPPED.value, progress=5,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {"status": "watching", "num_episodes_watched": 20}},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual(corrected, [])
        self.assertEqual(anime.progress, 5)

    def test_lower_or_equal_remote_progress_is_left_alone(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=10,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "watching", "num_episodes_watched": 10,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual(corrected, [])
        self.assertEqual(anime.progress, 10)
        self.assertEqual(anime.status, Status.IN_PROGRESS.value)

    def test_an_in_progress_rewatch_row_is_not_overwritten(self, *_mocks):
        """Only the highest row speaks for the MAL entry; a rewatch keeps its count."""
        with patch("integrations.tasks.sync_mal_status.delay"):
            Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.COMPLETED.value, progress=24,
            )
            rewatch = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=3,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "completed", "num_episodes_watched": 24,
                }},
                "manga": {},
            },
        )

        rewatch.refresh_from_db()
        self.assertEqual(corrected, [])
        self.assertEqual(rewatch.progress, 3)
        self.assertEqual(rewatch.status, Status.IN_PROGRESS.value)

    def test_planned_remote_status_is_pulled_when_floppy_has_no_progress(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=0,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "plan_to_watch", "num_episodes_watched": 0,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.progress, 0)
        self.assertEqual(anime.status, Status.PLANNING.value)

    def test_on_hold_remote_status_is_pulled_when_floppy_has_no_progress(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=0,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "on_hold", "num_episodes_watched": 0,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.progress, 0)
        self.assertEqual(anime.status, Status.PAUSED.value)

    def test_dropped_remote_status_is_pulled_when_floppy_has_no_progress(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=0,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "dropped", "num_episodes_watched": 0,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.progress, 0)
        self.assertEqual(anime.status, Status.DROPPED.value)

    def test_planned_remote_status_with_progress_becomes_in_progress(self, *_mocks):
        self.account.sync_filter_planning = True
        self.account.save(update_fields=["sync_filter_planning"])
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.PLANNING.value, progress=0,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "plan_to_watch", "num_episodes_watched": 3,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.progress, 3)
        self.assertEqual(anime.status, Status.IN_PROGRESS.value)

    def test_manga_zero_progress_statuses_are_pulled(self, *_mocks):
        statuses = {
            "100": ("plan_to_read", Status.PLANNING.value),
            "101": ("on_hold", Status.PAUSED.value),
            "102": ("dropped", Status.DROPPED.value),
        }
        with patch("integrations.tasks.sync_mal_status.delay"):
            for media_id in statuses:
                Manga.objects.create(
                    user=self.user,
                    item=Item.objects.create(
                        media_id=media_id,
                        source=Sources.MAL.value,
                        media_type=MediaTypes.MANGA.value,
                        title=f"Manga {media_id}",
                    ),
                    status=Status.IN_PROGRESS.value,
                    progress=0,
                )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {},
                "manga": {
                    media_id: {"status": mal_status, "num_chapters_read": 0}
                    for media_id, (mal_status, _status) in statuses.items()
                },
            },
        )

        corrected_ids = {media.item.media_id for media in corrected}
        local_statuses = {
            media.item.media_id: media.status
            for media in Manga.objects.filter(user=self.user).select_related("item")
        }
        self.assertEqual(corrected_ids, set(statuses))
        self.assertEqual(
            local_statuses,
            {media_id: status for media_id, (_mal_status, status) in statuses.items()},
        )

    def test_grouped_anime_is_never_touched(self, *_mocks):
        """Migrated (grouped) rows are excluded; progress can't be fabricated."""
        with patch("integrations.tasks.sync_mal_status.delay"):
            placeholder = Item.objects.create(
                media_id="100", source="tmdb", media_type="tv",
                library_media_type="anime", title="Grouped placeholder",
            )
            Anime.all_objects.create(
                user=self.user, item=self.item,
                status=Status.COMPLETED.value, progress=1,
                migrated_to_item=placeholder,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "completed", "num_episodes_watched": 24,
                }},
                "manga": {},
            },
        )

        self.assertEqual(corrected, [])

    def test_remote_rating_is_adopted_when_floppy_has_none(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=10, score=None,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "watching", "num_episodes_watched": 10, "score": 8,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual([media.pk for media in corrected], [anime.pk])
        self.assertEqual(anime.score, 8)

    def test_remote_rating_never_overwrites_an_existing_floppy_rating(self, *_mocks):
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=10, score=Decimal(5),
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "watching", "num_episodes_watched": 10, "score": 8,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual(corrected, [])
        self.assertEqual(anime.score, Decimal(5))

    def test_pull_ratings_disabled_leaves_an_unset_rating_alone(self, *_mocks):
        self.account.pull_ratings_enabled = False
        self.account.save(update_fields=["pull_ratings_enabled"])
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=10, score=None,
            )

        corrected = mal_sync.pull_higher_mal_progress(
            self.user, self.account,
            remote_statuses={
                "anime": {"9253": {
                    "status": "watching", "num_episodes_watched": 10, "score": 8,
                }},
                "manga": {},
            },
        )

        anime.refresh_from_db()
        self.assertEqual(corrected, [])
        self.assertIsNone(anime.score)


@patch("integrations.mal_sync.client_id", return_value="test_client_id")
@patch("integrations.mal_sync.client_secret", return_value="test_client_secret")
class PushStatus(TestCase):
    """Test mapping Floppy fields onto MAL's my_list_status endpoint."""

    def setUp(self):
        """Create a user, a connected MAL account, and MAL-backed items."""
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        self.anime_item = Item.objects.create(
            media_id="42",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
        )
        self.manga_item = Item.objects.create(
            media_id="99",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Test Manga",
        )

    @patch("requests.Session.put")
    def test_push_anime_status_and_progress(self, mock_put, *_mocks):
        """Anime pushes status + num_watched_episodes, using the anime status map."""
        mock_put.return_value = MagicMock(
            json=lambda: {"status": "on_hold", "num_episodes_watched": 5},
        )
        anime = Anime.objects.create(
            user=self.user,
            item=self.anime_item,
            status=Status.PAUSED.value,
            progress=5,
        )

        mal_sync.push_status(anime, self.account)

        self.assertIn("/anime/42/my_list_status", mock_put.call_args.kwargs["url"])
        data = mock_put.call_args.kwargs["data"]
        self.assertEqual(data["status"], "on_hold")
        self.assertEqual(data["num_watched_episodes"], 5)
        self.assertNotIn("score", data)

    @patch("requests.Session.put")
    def test_push_manga_uses_chapters_and_manga_status_map(self, mock_put, *_mocks):
        """Manga pushes num_chapters_read and maps status onto MAL's manga statuses."""
        mock_put.return_value = MagicMock(
            json=lambda: {"status": "dropped", "num_chapters_read": 64, "score": 8},
        )
        manga = Manga.objects.create(
            user=self.user,
            item=self.manga_item,
            status=Status.DROPPED.value,
            progress=64,
            score=Decimal("7.8"),
        )

        mal_sync.push_status(manga, self.account)

        data = mock_put.call_args.kwargs["data"]
        self.assertEqual(data["status"], "dropped")
        self.assertEqual(data["num_chapters_read"], 64)
        self.assertEqual(data["score"], 8)

    @patch("requests.Session.put")
    def test_sync_ratings_disabled_omits_score(self, mock_put, *_mocks):
        """Turning off ratings sync leaves score out of the pushed payload."""
        self.account.sync_ratings_enabled = False
        self.account.save(update_fields=["sync_ratings_enabled"])
        mock_put.return_value = MagicMock(
            json=lambda: {"status": "dropped", "num_chapters_read": 64},
        )
        manga = Manga.objects.create(
            user=self.user,
            item=self.manga_item,
            status=Status.DROPPED.value,
            progress=64,
            score=Decimal("7.8"),
        )

        mal_sync.push_status(manga, self.account)

        self.assertNotIn("score", mock_put.call_args.kwargs["data"])

    @patch("requests.Session.put")
    def test_cleared_rating_is_sent_as_zero(self, mock_put, *_mocks):
        mock_put.return_value = MagicMock(
            json=lambda: {"status": "dropped", "num_chapters_read": 64, "score": 0},
        )
        manga = Manga.objects.create(
            user=self.user, item=self.manga_item,
            status=Status.DROPPED.value, progress=64,
        )

        mal_sync.push_status(manga, self.account, clear_score=True)

        self.assertEqual(mock_put.call_args.kwargs["data"]["score"], 0)

    @patch("requests.Session.put")
    @patch("requests.Session.post")
    def test_push_refreshes_expired_token_first(self, mock_post, mock_put, *_mocks):
        """An expired access token is refreshed before pushing the update."""
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save()

        refresh_response = MagicMock()
        refresh_response.json.return_value = {
            "access_token": "refreshed-access-token",
            "refresh_token": "refreshed-refresh-token",
            "expires_in": 3600,
        }
        mock_post.return_value = refresh_response
        mock_put.return_value = MagicMock(
            json=lambda: {"status": "on_hold", "num_episodes_watched": 0},
        )

        anime = Anime.objects.create(
            user=self.user,
            item=self.anime_item,
            status=Status.PAUSED.value,
        )

        mal_sync.push_status(anime, self.account)

        self.account.refresh_from_db()
        self.assertEqual(decrypt(self.account.access_token), "refreshed-access-token")
        self.assertEqual(
            mock_put.call_args.kwargs["headers"]["Authorization"],
            "Bearer refreshed-access-token",
        )

    @patch("requests.Session.put")
    def test_missing_credentials_do_not_break_the_connection(self, mock_put, *_mocks):
        """Regression: a missing client secret was treated like MAL rejecting
        the connection, which disabled sync until a full OAuth reconnect.
        """
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save(update_fields=["token_expires_at"])
        with patch("integrations.tasks.sync_mal_status.delay"):
            anime = Anime.objects.create(
                user=self.user, item=self.anime_item, status=Status.PAUSED.value,
            )

        with patch("integrations.mal_sync.client_secret", return_value=""):
            tasks.sync_mal_status(media_type="anime", media_id=anime.pk)

        mock_put.assert_not_called()
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertTrue(self.account.sync_enabled)
        self.assertIn("isn't configured", self.account.last_error_message)

    @patch("requests.Session.post")
    def test_refresh_failure_raises_auth_error(self, mock_post, *_mocks):
        """A revoked refresh token surfaces as a clean MALAuthError."""
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save()
        error_response = MagicMock(status_code=401, text="invalid_grant")
        error_response.raise_for_status.side_effect = _http_error(error_response)
        mock_post.return_value = error_response

        with self.assertRaises(mal_sync.MALAuthError):
            mal_sync.get_valid_access_token(self.account)

    @patch("integrations.mal_sync._refresh_tokens")
    def test_stale_worker_reuses_already_refreshed_tokens(self, refresh, *_mocks):
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save(update_fields=["token_expires_at"])
        other_worker = MALAccount.objects.get(pk=self.account.pk)
        mal_sync._store_tokens(other_worker, {
            "access_token": "rotated-access", "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        })

        self.assertEqual(mal_sync.get_valid_access_token(self.account), "rotated-access")
        refresh.assert_not_called()

    @patch("integrations.mal_sync._refresh_tokens")
    def test_concurrent_refresh_waits_for_the_other_worker(self, refresh, *_mocks):
        """Regression: without a lock that works on SQLite, both workers spent
        the one-time refresh token and the loser broke the connection.
        """
        from app import cache_safety

        cache.clear()
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save(update_fields=["token_expires_at"])
        lock_key = f"mal_token_refresh:{self.account.pk}"
        cache_safety.acquire_lock(lock_key, timeout=30)

        def other_worker_finishes(_seconds):
            mal_sync._store_tokens(MALAccount.objects.get(pk=self.account.pk), {
                "access_token": "rotated-access", "refresh_token": "rotated-refresh",
                "expires_in": 3600,
            })
            cache_safety.release_lock(lock_key)

        with patch("integrations.mal_sync.time.sleep", side_effect=other_worker_finishes):
            token = mal_sync.get_valid_access_token(self.account)

        self.assertEqual(token, "rotated-access")
        refresh.assert_not_called()
        self.assertIsNone(cache.get(lock_key))

    @patch("integrations.mal_sync._refresh_tokens")
    def test_refresh_that_never_gets_the_lock_is_retried_later(self, refresh, *_mocks):
        """Regression: a waiter past its deadline refreshed anyway, spending
        a token the holder was still using, then released the holder's lock.
        """
        from app import cache_safety

        cache.clear()
        self.account.token_expires_at = timezone.now() - timedelta(minutes=5)
        self.account.save(update_fields=["token_expires_at"])
        lock_key = f"mal_token_refresh:{self.account.pk}"
        cache_safety.acquire_lock(lock_key, timeout=30)
        self.addCleanup(cache_safety.release_lock, lock_key)

        with (
            patch.object(mal_sync, "TOKEN_REFRESH_LOCK_SECONDS", 0),
            self.assertRaises(ProviderAPIError),
        ):
            mal_sync.get_valid_access_token(self.account)

        refresh.assert_not_called()
        self.assertIsNotNone(cache.get(lock_key))


class PreviewFullSync(TestCase):
    """Test the read-only diff used before a full MAL sync."""

    def setUp(self):
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        with patch("integrations.tasks.sync_mal_status.delay"):
            self.anime = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="42",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Changed Anime",
                ),
                # Dropped, not Paused/Planning, so this stays covered by the
                # default sync filters (see MALSyncFiltersTests below).
                status=Status.DROPPED.value,
                progress=5,
                score=Decimal("7.6"),
            )
            self.manga = Manga.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="99",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.MANGA.value,
                    title="Unchanged Manga",
                ),
                status=Status.COMPLETED.value,
                progress=0,
            )

    @patch("integrations.mal_sync.services.api_request")
    def test_returns_only_fields_that_would_change(self, mock_request):
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "watching",
                            "num_episodes_watched": 5,
                            "score": 7,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        # Previews run in a Celery worker, whose URLconf is empty.
        with override_settings(ROOT_URLCONF="config.celery_urls"):
            preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(
            preview,
            [
                {
                    "key": "anime:42",
                    "title": "Changed Anime",
                    "link": {
                        "media_type": "anime",
                        "source": "mal",
                        "media_id": "42",
                        "title": "Changed Anime",
                    },
                    "media_type": "Anime",
                    "mal_id": "42",
                    "not_on_list": False,
                    "changes": [
                        {
                            "target": "mal", "target_label": "MyAnimeList",
                            "field": "Status", "from": "watching", "to": "dropped",
                        },
                        {
                            "target": "mal", "target_label": "MyAnimeList",
                            "field": "Score", "from": 7, "to": 8,
                        },
                    ],
                }
            ],
        )

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_marks_planned_status_as_floppy_change(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.IN_PROGRESS.value,
            progress=0,
            score=None,
        )
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "plan_to_watch",
                            "num_episodes_watched": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(preview[0]["changes"], [
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Status", "from": Status.IN_PROGRESS.value,
                "to": Status.PLANNING.value,
            }
        ])

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_marks_on_hold_status_as_floppy_change(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.IN_PROGRESS.value,
            progress=0,
            score=None,
        )
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "on_hold",
                            "num_episodes_watched": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(preview[0]["changes"], [
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Status", "from": Status.IN_PROGRESS.value,
                "to": Status.PAUSED.value,
            }
        ])

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_marks_dropped_status_as_floppy_change(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.IN_PROGRESS.value,
            progress=0,
            score=None,
        )
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "dropped",
                            "num_episodes_watched": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(preview[0]["changes"], [
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Status", "from": Status.IN_PROGRESS.value,
                "to": Status.DROPPED.value,
            }
        ])

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_normalizes_planned_status_with_progress(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.DROPPED.value,
            progress=0,
            score=None,
        )
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "plan_to_watch",
                            "num_episodes_watched": 3,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(preview[0]["changes"], [
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Status", "from": Status.DROPPED.value,
                "to": Status.IN_PROGRESS.value,
            },
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Episodes watched", "from": 0, "to": 3,
            },
            {
                "target": "mal", "target_label": "MyAnimeList",
                "field": "Status", "from": "plan_to_watch", "to": "watching",
            },
        ])

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_marks_missing_rating_as_floppy_change(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.IN_PROGRESS.value,
            progress=10,
            score=None,
        )
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "watching",
                            "num_episodes_watched": 10,
                            "score": 8,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(preview[0]["changes"], [
            {
                "target": "floppy", "target_label": "Floppy",
                "field": "Score", "from": None, "to": 8,
            }
        ])

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_sorts_floppy_changes_before_mal_changes(self, mock_request):
        Anime.objects.filter(pk=self.anime.pk).update(
            status=Status.IN_PROGRESS.value,
            progress=0,
            score=None,
        )
        Manga.objects.filter(pk=self.manga.pk).update(status=Status.DROPPED.value)
        mock_request.side_effect = [
            {
                "data": [
                    {
                        "node": {"id": 42},
                        "list_status": {
                            "status": "on_hold",
                            "num_episodes_watched": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
            {
                "data": [
                    {
                        "node": {"id": 99},
                        "list_status": {
                            "status": "completed",
                            "num_chapters_read": 0,
                            "score": 0,
                        },
                    }
                ],
                "paging": {},
            },
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual([entry["changes"][0]["target"] for entry in preview], ["floppy", "mal"])

    @patch("integrations.mal_sync.services.api_request")
    def test_marks_entries_missing_from_mal(self, mock_request):
        mock_request.side_effect = [
            {"data": [], "paging": {}},
            {"data": [], "paging": {}},
        ]

        preview = mal_sync.preview_full_sync(self.user, self.account)

        self.assertEqual(len(preview), 2)
        self.assertTrue(all(entry["not_on_list"] for entry in preview))

    @patch("integrations.mal_sync.services.api_request")
    def test_preview_includes_filtered_titles_already_synced(self, mock_request):
        def list_response(_provider, _method, url, *, params, headers):
            self.assertEqual(params["nsfw"], "true")
            self.assertIn("Authorization", headers)
            if url.endswith("/animelist"):
                return {"data": [{"node": {"id": 42}, "list_status": {
                    "status": "dropped", "num_episodes_watched": 5, "score": 8,
                }}]}
            return {"data": [{"node": {"id": 99}, "list_status": {
                "status": "completed", "num_chapters_read": 0,
            }}]}

        mock_request.side_effect = list_response

        self.assertEqual(mal_sync.preview_full_sync(self.user, self.account), [])


class GroupedMALSync(TestCase):
    """Grouped episode progress is projected per MAL cour without duplicate rows."""

    def setUp(self):
        cache.clear()
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        self.show_item = Item.objects.create(
            media_id="100", source="tmdb", media_type="tv",
            library_media_type="anime", title="Grouped Anime",
        )
        self.show = TV(user=self.user, item=self.show_item, status=Status.IN_PROGRESS.value)
        TV.objects.bulk_create([self.show])
        self.season = Season(
            user=self.user, related_tv=self.show, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="100", source="tmdb", media_type="season",
                library_media_type="anime", season_number=1, title="Season 1",
            ),
        )
        Season.objects.bulk_create([self.season])
        episodes = []
        for number in (1, 2, 3):
            item = Item.objects.create(
                media_id="100", source="tmdb", media_type="episode",
                library_media_type="anime", season_number=1,
                episode_number=number, title=f"Episode {number}",
            )
            episodes.append(Episode(item=item, related_season=self.season))
        Episode.objects.bulk_create(episodes)

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        # Only episode 1 has an unambiguous AniBridge mapping - a recap/alt-
        # numbering episode elsewhere in the season would make the rest
        # ambiguous on a real show, exactly like Steins;Gate (MAL 9253).
        "tmdb_show:100:s1": {"mal:9253": {"1": "1"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_provider_link_from_migration_overrides_ambiguous_anibridge_mapping(
        self, metadata,
    ):
        """Auto-migrated shows use Floppy's own exact mapping, not AniBridge's.

        Regression for a completed flat MAL anime (e.g. Steins;Gate) whose
        auto-migration to grouped tracking left an exact ItemProviderLink, but
        whose AniBridge mapping only resolves the first episode - previously
        this undercounted progress down to 1 watched episode.
        """
        metadata.return_value = {"title": "Steins;Gate", "max_progress": 3}
        original_flat_item = Item.objects.create(
            media_id="9253", source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value, title="Steins;Gate",
        )
        ItemProviderLink.objects.create(
            item=original_flat_item,
            provider=Sources.TMDB.value,
            provider_media_id="100",
            provider_media_type=MediaTypes.TV.value,
            season_number=1,
            episode_offset=0,
        )

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].item.media_id, "9253")
        self.assertEqual(entries[0].progress, 3)
        self.assertEqual(entries[0].status, Status.COMPLETED.value)

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_deleted_mal_entry_is_a_mapping_issue_not_a_failed_sync(self, metadata):
        """Regression: one mapped MAL id returning 404 aborted the whole sync."""
        metadata.side_effect = ProviderAPIError(
            "MAL", MagicMock(response=MagicMock(status_code=404)),
        )

        issues = []
        entries = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(entries, [])
        self.assertEqual(
            [episode["episode"] for episode in issues[0]["episodes"]], [1, 2, 3],
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_play_left_in_progress_is_not_counted_as_watched(self, metadata):
        """Regression: an unfinished final episode raised the count and
        marked the MAL entry Completed early.
        """
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 3}
        Episode.objects.filter(
            related_season=self.season, item__episode_number=3,
        ).update(status=Status.IN_PROGRESS.value)

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(
            [(entry.progress, entry.status) for entry in entries],
            [(2, Status.IN_PROGRESS.value)],
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:111": {"1-2": "1-2"}, "mal:222": {"3-": "1-"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_link_to_first_cour_leaves_later_episodes_to_anibridge(self, metadata):
        """A season link covers only its own MAL entry's episodes.

        Regression: a link to cour 1 of a season split across two MAL
        entries mapped S1E3 onto cour 1 as episode 3, where it was clamped
        away and cour 2 was never updated.
        """
        metadata.side_effect = lambda _type, mal_id, _source: {
            "title": f"Cour {mal_id}", "max_progress": 2,
        }
        ItemProviderLink.objects.create(
            item=Item.objects.create(
                media_id="111", source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value, title="Cour 111",
            ),
            provider=Sources.TMDB.value,
            provider_media_id="100",
            provider_media_type=MediaTypes.TV.value,
            season_number=1,
            episode_offset=0,
        )

        entries = {
            entry.item.media_id: entry.progress
            for entry in mal_sync.grouped_sync_entries(self.user)
        }

        self.assertEqual(entries, {"111": 2, "222": 1})

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:1482": {"1-3": "1-3"}},
        "tmdb_show:100:s2": {"mal:1482": {"1-2": "4-5"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_season_less_identity_link_does_not_restart_later_seasons(self, metadata):
        """A show-level MAL identity link carries no per-season episode offset.

        Regression for D.Gray-man: one MAL entry spans TMDB seasons 1 and 2,
        and a season-less TMDB identity link mapped S2E1 onto MAL episode 1,
        so season 2 watches collapsed into season 1's numbers.
        """
        metadata.return_value = {"title": "D.Gray-man", "max_progress": 10}
        ItemProviderLink.objects.create(
            item=Item.objects.create(
                media_id="1482", source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value, title="D.Gray-man",
            ),
            provider=Sources.TMDB.value,
            provider_media_id="100",
            provider_media_type=MediaTypes.TV.value,
            season_number=None,
        )
        season_2 = Season(
            user=self.user, related_tv=self.show, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="100", source="tmdb", media_type="season",
                library_media_type="anime", season_number=2, title="Season 2",
            ),
        )
        Season.objects.bulk_create([season_2])
        Episode.objects.bulk_create([
            Episode(
                related_season=season_2,
                item=Item.objects.create(
                    media_id="100", source="tmdb", media_type="episode",
                    library_media_type="anime", season_number=2,
                    episode_number=number, title=f"Episode {number}",
                ),
            )
            for number in (1, 2)
        ])

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].item.media_id, "1482")
        self.assertEqual(entries[0].progress, 5)

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:33035": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_progress_is_clamped_to_the_mal_entrys_episode_count(self, metadata):
        """MAL silently ignores an out-of-range count instead of applying it.

        Regression: an overlapping or stale mapping can produce more watched
        episode numbers than a short MAL entry actually has, which must be
        clamped before the push instead of surfacing as a false
        MALSyncMismatchError ("MyAnimeList accepted the update ... but its
        response shows it wasn't applied").
        """
        metadata.return_value = {"title": "Short OVA", "max_progress": 1}

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].progress, 1)
        self.assertEqual(entries[0].status, Status.COMPLETED.value)

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_full_sync_projects_each_cour_and_ignores_migrated_progress(self, metadata):
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 2}
        anime = Anime(
            user=self.user, item=Item.objects.create(
                media_id="43", source="mal", media_type="anime", title="Old Anime",
            ),
            migrated_to_item=self.show_item, status=Status.COMPLETED.value, progress=2,
        )
        Anime.all_objects.bulk_create([anime])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            [(entry.item.media_id, entry.progress, entry.status) for entry in entries],
            [("42", 2, Status.COMPLETED.value), ("43", 1, Status.IN_PROGRESS.value)],
        )
        self.assertEqual(Anime.all_objects.filter(user=self.user).count(), 1)

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_watch_state_queues_grouped_sync_after_commit(self, delay):
        from app.services.watch_state import project_watch_state_for_change

        episode = Episode.objects.filter(related_season=self.season).first()
        with self.captureOnCommitCallbacks(execute=True):
            project_watch_state_for_change(self.user, episode.item)
            delay.assert_not_called()
        delay.assert_called_once_with(
            kwargs={"media_type": "tv", "media_id": self.show.pk},
            countdown=mal_sync.GROUPED_SYNC_DEBOUNCE_SECONDS + 1,
        )

    @patch("integrations.mal_sync._fetch_list_statuses", new=MagicMock(return_value={}))
    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={})
    def test_mapping_issues_persist_and_survive_page_reload(self):
        self.client.force_login(self.user)
        with patch("integrations.mal_sync._fetch_list_statuses", return_value={}):
            preview = tasks.preview_mal_sync(self.user.pk)
        self.assertEqual(preview["count"], 0)
        self.assertEqual(preview["mapping_issues"][0]["title"], "Grouped Anime")
        self.assertIn("S01E03", preview["mapping_issues"][0]["reason"])
        self.assertEqual(preview["mapping_issues"][0]["seasons"], [{
            "season": 1,
            "episodes": [1, 2, 3],
            "all_unmapped": True,
        }])

        tasks.bulk_sync_mal_status(self.user.pk)

        report = self.client.get(reverse("mal_full_sync_status")).json()
        self.assertEqual(report["mapping_issues"], preview["mapping_issues"])
        self.assertEqual(report["succeeded"], 0)
        self.assertEqual(report["failed"], 0)
        page = self.client.get(reverse("mal_export"))
        self.assertEqual(page.context["mal_sync_initial"]["mapping_issues"], report["mapping_issues"])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={})
    def test_ignored_show_is_skipped_from_sync_and_mapping_issues(self):
        mal_sync.set_mapping_ignored(self.user, self.show_item.pk, ignored=True)

        issues = []
        entries = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(entries, [])
        self.assertEqual(issues, [])
        self.assertEqual(
            mal_sync.ignored_mappings(self.user),
            [{"item_id": self.show_item.pk, "title": "Grouped Anime"}],
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={})
    def test_unignoring_a_show_restores_its_mapping_issue(self):
        mal_sync.set_mapping_ignored(self.user, self.show_item.pk, ignored=True)
        mal_sync.set_mapping_ignored(self.user, self.show_item.pk, ignored=False)

        issues = []
        mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(issues[0]["title"], "Grouped Anime")
        self.assertEqual(mal_sync.ignored_mappings(self.user), [])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={})
    def test_mal_mapping_ignore_view_toggles_ignore_state(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("mal_mapping_ignore"), {
            "item_id": self.show_item.pk, "ignored": "true",
        })
        self.assertEqual(response.json(), {"ignored": True})
        self.assertEqual(
            mal_sync.ignored_mapping_item_ids(self.user), {self.show_item.pk},
        )

        response = self.client.post(reverse("mal_mapping_ignore"), {
            "item_id": self.show_item.pk, "ignored": "false",
        })
        self.assertEqual(response.json(), {"ignored": False})
        self.assertEqual(mal_sync.ignored_mapping_item_ids(self.user), set())

    def test_mal_mapping_ignore_view_is_user_scoped(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_mapping_ignore"), {
            "item_id": self.show_item.pk, "ignored": "true",
        })
        self.assertEqual(response.status_code, 200)

        other = _make_user(username="ignore-other")
        self.assertEqual(mal_sync.ignored_mapping_item_ids(other), set())

    def test_unsafe_mapping_is_reported_instead_of_guessed(self):
        mappings = [
            {"mal:42": {"1-3": "1-3"}, "mal:43": {"1-3": "1-3"}},
            {"mal:42": {"1-3": "1-6|2"}},
            {"mal:42": {"1-3": "1-2|-2"}},
            {"mal:42,43": {"1-3": "1-3"}},
            {"mal:42": {"bad-range": "1-3"}},
        ]
        for targets in mappings:
            with self.subTest(targets=targets), self.settings(
                ANIBRIDGE_MAPPING_DATA_OVERRIDE={"tmdb_show:100:s1": targets},
            ):
                issues = []
                self.assertEqual(mal_sync.grouped_sync_entries(self.user, mapping_issues=issues), [])
                self.assertEqual(issues[0]["title"], "Grouped Anime")
                self.assertIn("S01E01", issues[0]["reason"])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1": "1"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_manual_episode_mappings_restore_completed_season_progress(self, metadata):
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 3}
        self.client.force_login(self.user)
        issues = []
        initial = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)
        self.assertEqual(initial[0].progress, 1)
        self.assertEqual(issues[0]["seasons"], [{
            "season": 1,
            "episodes": [2, 3],
            "all_unmapped": False,
        }])
        for source_episode in (2, 3):
            response = self.client.post(reverse("mal_episode_mapping_save"), {
                "item_id": self.show_item.pk,
                "season": 1,
                "episode": source_episode,
                "mal_id": 42,
                "mal_episode": source_episode,
            })
            self.assertEqual(response.status_code, 200)

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].progress, 3)
        self.assertEqual(entries[0].status, Status.COMPLETED.value)

    def test_season_mapping_keeps_source_numbering_across_gaps(self):
        """An untracked episode still takes its MAL number.

        Regression: overrides were numbered by list position, so E3 took
        E2's MAL episode and collided with E2 once it was watched and mapped.
        """
        from app.models import WatchState

        Episode.objects.filter(
            related_season=self.season,
            item__episode_number=2,
        ).delete()
        # A true gap: no Episode row and no watch state either.
        WatchState.objects.filter(user=self.user, item__episode_number=2).delete()
        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk,
            "season": 1,
            "episode": 1,
            "scope": "season",
            "mal_id": 500,
            "mal_episode": 4,
        })
        self.assertEqual(response.json()["mapped"], 2)
        mappings = sorted(
            (
                reference.metadata["episode_number"],
                reference.episode_mapping["episode"],
            )
            for reference in self.user.external_references.filter(
                integration="mal_sync",
            )
        )
        self.assertEqual(mappings, [(1, 4), (3, 6)])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:9": {"1-2": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_season_mapping_keeps_episodes_that_already_resolve(self, metadata):
        """Regression: a stale report let "Fix whole season" overwrite every
        tracked episode, breaking E1-2's working mapping and numbering E3
        from E1 instead of from itself.
        """
        metadata.return_value = {"title": "Cour 9", "max_progress": 2}
        self.client.force_login(self.user)

        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 3,
            "scope": "season", "mal_id": 500, "mal_episode": 1,
        })

        self.assertEqual(response.json()["mapped"], 1)
        mappings = {
            reference.metadata["episode_number"]: reference.episode_mapping
            for reference in self.user.external_references.filter(
                integration="mal_sync",
            )
        }
        self.assertEqual(mappings, {3: {"mal_id": 500, "episode": 1}})

    def test_season_mapping_counts_from_the_aligned_episode(self):
        """Regression: an earlier episode that became unresolved after the
        report was built took the first MAL episode and shifted the rest.
        """
        self.client.force_login(self.user)

        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 2,
            "scope": "season", "mal_id": 500, "mal_episode": 1,
        })

        self.assertEqual(response.json()["mapped"], 2)
        mappings = {
            reference.metadata["episode_number"]: reference.episode_mapping["episode"]
            for reference in self.user.external_references.filter(
                integration="mal_sync",
            )
        }
        self.assertEqual(mappings, {2: 1, 3: 2})

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:9": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_season_mapping_of_a_resolved_season_is_refused(self, metadata):
        metadata.return_value = {"title": "Cour 9", "max_progress": 3}
        self.client.force_login(self.user)

        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 1,
            "scope": "season", "mal_id": 500, "mal_episode": 1,
        })

        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.user.external_references.exists())

    def test_manual_mapping_is_user_scoped_and_validated(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 2,
            "mal_id": 42, "mal_episode": 2,
        })
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 2,
            "mal_id": 43, "mal_episode": 7,
        })
        self.assertEqual(response.status_code, 200)
        reference = self.user.external_references.get(integration="mal_sync")
        self.assertEqual(reference.episode_mapping, {"mal_id": 43, "episode": 7})

        other = _make_user(username="mapping-other")
        self.client.force_login(other)
        denied = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 2,
            "mal_id": 42, "mal_episode": 2,
        })
        self.assertEqual(denied.status_code, 404)

    def test_season_mapping_persists_sequential_episode_overrides(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk,
            "season": 1,
            "episode": 1,
            "scope": "season",
            "mal_id": 500,
            "mal_episode": 4,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mapped"], 3)
        mappings = {
            reference.metadata["episode_number"]: reference.episode_mapping
            for reference in self.user.external_references.filter(
                integration="mal_sync",
            )
        }
        self.assertEqual(mappings, {
            1: {"mal_id": 500, "episode": 4},
            2: {"mal_id": 500, "episode": 5},
            3: {"mal_id": 500, "episode": 6},
        })

    def test_watch_state_only_episode_can_be_mapped(self):
        """Every episode reported as a mapping issue must be fixable, even with no Episode row."""
        from app.models import WatchState

        fourth_episode_item = Item.objects.create(
            media_id="100", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=1,
            episode_number=4, title="Episode 4",
        )
        WatchState.objects.bulk_create([
            WatchState(user=self.user, item=fourth_episode_item, watched=True),
        ])
        self.client.force_login(self.user)

        season = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 1,
            "scope": "season", "mal_id": 500, "mal_episode": 1,
        })
        single = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 4,
            "mal_id": 500, "mal_episode": 4,
        })

        self.assertEqual(single.status_code, 200)
        self.assertEqual(season.json()["mapped"], 4)

    def test_manual_mappings_are_grouped_and_revertable(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_episode_mapping_save"), {
            "item_id": self.show_item.pk, "season": 1, "episode": 1,
            "scope": "season", "mal_id": 500, "mal_episode": 4,
        })
        mappings = response.json()["manual_mappings"]
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["episodes"], [1, 2, 3])
        self.assertEqual(mappings[0]["mal_episodes"], [4, 5, 6])

        other = _make_user(username="revert-other")
        self.client.force_login(other)
        denied = self.client.post(reverse("mal_episode_mapping_revert"), {
            "reference_id": mappings[0]["reference_ids"],
        })
        self.assertEqual(denied.status_code, 404)

        self.client.force_login(self.user)
        response = self.client.post(reverse("mal_episode_mapping_revert"), {
            "reference_id": mappings[0]["reference_ids"],
        })
        self.assertEqual(response.json(), {"reverted": True})
        self.assertEqual(mal_sync.manual_episode_mappings(self.user), [])

    def test_mapping_search_asks_for_three_characters(self):
        """Regression: two-character queries reached MAL, which rejects them
        with 400, and the wizard showed "search is unavailable".
        """
        self.client.force_login(self.user)
        with patch("app.providers.mal.search") as search:
            response = self.client.get(reverse("mal_mapping_search"), {"q": "86"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("three characters", response.json()["error"])
        search.assert_not_called()

    @patch("app.providers.mal.search")
    def test_mapping_wizard_searches_mal_anime(self, search):
        self.client.force_login(self.user)
        search.return_value = {"results": [{
            "media_id": "42", "title": "Prison School", "year": 2015,
            "image": "https://example.test/prison-school.jpg",
        }]}

        response = self.client.get(reverse("mal_mapping_search"), {"q": "Prison"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["media_id"], "42")
        search.assert_called_once_with(
            MediaTypes.ANIME.value,
            "Prison",
            1,
            include_nsfw=True,
        )

    @patch("app.providers.mal.services.api_request")
    def test_mapping_search_cache_is_separate_from_filtered_search(self, request):
        from app.providers import mal as mal_provider

        request.side_effect = [
            {"data": [{"node": {"id": 1, "title": "Filtered"}}]},
            {"data": [{"node": {"id": 2, "title": "Unfiltered"}}]},
        ]
        filtered = mal_provider.search("anime", "same query", 1, include_nsfw=False)
        unfiltered = mal_provider.search("anime", "same query", 1, include_nsfw=True)
        self.assertEqual(filtered["results"][0]["media_id"], 1)
        self.assertEqual(unfiltered["results"][0]["media_id"], 2)
        self.assertNotIn("nsfw", request.call_args_list[0].kwargs["params"])
        self.assertEqual(request.call_args_list[1].kwargs["params"]["nsfw"], "true")

    @patch("integrations.views.services.get_media_metadata")
    def test_mapping_wizard_lists_selected_mal_episodes(self, metadata):
        self.client.force_login(self.user)
        metadata.return_value = {
            "title": "Prison School",
            "image": "https://example.test/prison-school.jpg",
            "max_progress": 3,
        }

        response = self.client.get(reverse("mal_mapping_episodes"), {"mal_id": 42})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["episodes"], [1, 2, 3])
        self.assertEqual(response.json()["title"], "Prison School")

    @patch("integrations.views.services.get_media_metadata")
    def test_mapping_wizard_handles_unknown_episode_count(self, metadata):
        self.client.force_login(self.user)
        metadata.return_value = {
            "title": "Ongoing Anime", "image": None, "max_progress": None,
        }
        response = self.client.get(reverse("mal_mapping_episodes"), {"mal_id": 42})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["episodes"], [])

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_per_item_toggle_prevents_grouped_queue(self, delay):
        self.account.per_item_sync_enabled = False
        self.account.save(update_fields=["per_item_sync_enabled"])
        with self.captureOnCommitCallbacks(execute=True):
            mal_sync.queue_grouped_sync(self.user.pk, self.show_item)
        delay.assert_not_called()

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_per_item_task_pushes_grouped_projection(self, entries, push):
        entries.return_value = [MagicMock()]
        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)
        entries.assert_called_once_with(self.user, tv=self.show)
        push.assert_called_once_with(entries.return_value[0], self.account, clear_score=False)

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_rejected_cour_does_not_block_the_next_one(self, entries, push):
        """Each MAL entry of a grouped show is pushed on its own.

        Regression: one push covered every cour, so a mismatch or a 404 on
        the first entry stopped the rest on every later trigger too.
        """
        entries.return_value = [MagicMock(), MagicMock(), MagicMock()]
        not_found = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=404)))
        push.side_effect = [mal_sync.MALSyncMismatchError("mismatch"), not_found, None]

        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)

        self.assertEqual(
            [call.args[0] for call in push.call_args_list], entries.return_value,
        )

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_retryable_error_is_raised_after_the_other_cours(self, entries, push):
        """A temporary failure still retries the task, but only after the rest."""
        entries.return_value = [MagicMock(), MagicMock()]
        unavailable = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=503)))
        push.side_effect = [unavailable, None]

        with self.assertRaises(ProviderAPIError):
            tasks.sync_mal_status.run(media_type="tv", media_id=self.show.pk)

        self.assertEqual(push.call_count, 2)

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    @patch("integrations.mal_sync.services.api_request")
    def test_new_episode_syncs_and_then_disappears_from_preview(self, request, metadata):
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 2}
        remote = {}

        def response(_provider, method, url, **kwargs):
            if method == "PUT":
                data = kwargs["data"].copy()
                data["num_episodes_watched"] = data.pop("num_watched_episodes")
                remote[url.split("/")[-2]] = data
                return data
            self.assertEqual(kwargs["params"]["nsfw"], "true")
            return {"data": [
                {"node": {"id": int(media_id)}, "list_status": status}
                for media_id, status in remote.items()
            ] if url.endswith("/animelist") else []}

        request.side_effect = response
        self.assertEqual(len(mal_sync.preview_full_sync(self.user, self.account)), 2)
        tasks.bulk_sync_mal_status(self.user.pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.full_sync_succeeded, 2)
        self.assertEqual(mal_sync.preview_full_sync(self.user, self.account), [])

        item = Item.objects.create(
            media_id="100", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=1, episode_number=4,
            title="Episode 4",
        )
        Episode.objects.bulk_create([Episode(item=item, related_season=self.season)])
        preview = mal_sync.preview_full_sync(self.user, self.account)
        self.assertEqual([entry["mal_id"] for entry in preview], ["43"])
        self.assertIn({
            "target": "mal", "target_label": "MyAnimeList",
            "field": "Episodes watched", "from": 1, "to": 2,
        }, preview[0]["changes"])

        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)
        self.assertEqual(remote["43"]["num_episodes_watched"], 2)
        self.assertEqual(mal_sync.preview_full_sync(self.user, self.account), [])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_rewatches_unwatched_and_unmapped_episodes(self, metadata):
        from app.services.watch_state import project_watch_state_for_change

        metadata.return_value = {"title": "Mapped Anime", "max_progress": 2}
        episode = Episode.objects.get(related_season=self.season, item__episode_number=1)
        Episode.objects.bulk_create([Episode(item=episode.item, related_season=self.season)])
        dropped = Episode.objects.get(related_season=self.season, item__episode_number=2)
        Episode.objects.filter(pk=dropped.pk).update(dropped=True)
        project_watch_state_for_change(self.user, dropped.item)
        unmapped = Item.objects.create(
            media_id="100", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=0, episode_number=1,
            title="Unmapped special",
        )
        Episode.objects.bulk_create([Episode(item=unmapped, related_season=self.season)])

        entries = mal_sync.grouped_sync_entries(self.user)
        self.assertEqual({entry.item.media_id: entry.progress for entry in entries}, {"42": 1, "43": 1})
        self.assertEqual(mal_sync.grouped_sync_entries(_make_user(username="other")), [])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_watch_state_only_episode_counts_without_a_legacy_episode_row(self, metadata):
        """A canonical WatchState "watched" signal must count even with no Episode row.

        Regression: coordinates seeded every WatchState entry as unwatched
        regardless of its actual `watched` value, so an episode recorded only
        through WatchState (no legacy Episode play, e.g. a bulk import) was
        silently dropped from the pushed progress count. bulk_create is used
        throughout (not .delete()/.save()) so no post_save/post_delete signal
        reprojects the WatchState row back from the state under test.
        """
        from app.models import WatchState

        metadata.return_value = {"title": "Mapped Anime", "max_progress": 2}
        fourth_episode_item = Item.objects.create(
            media_id="100", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=1,
            episode_number=4, title="Episode 4",
        )
        WatchState.objects.bulk_create([
            WatchState(user=self.user, item=fourth_episode_item, watched=True),
        ])

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(
            {entry.item.media_id: entry.progress for entry in entries},
            {"42": 2, "43": 2},
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-4": "1-4"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_planning_show_with_no_progress_ignores_stale_watch_states(self, metadata):
        """A show reset to plan-to-watch with 0 progress must not push old watches.

        Regression: a show manually set back to planning kept its WatchState
        rows, so the preview offered to move MAL to watching with those counts.
        """
        from app.models import WatchState

        metadata.return_value = {"title": "Mapped Anime", "max_progress": 4}
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        TV.objects.filter(pk=self.show.pk).update(status=Status.PLANNING.value)
        stale_item = Item.objects.create(
            media_id="100", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=1,
            episode_number=4, title="Episode 4",
        )
        WatchState.objects.bulk_create([
            WatchState(user=self.user, item=stale_item, watched=True),
        ])

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(
            [(entry.progress, entry.status) for entry in entries],
            [(0, Status.PLANNING.value)],
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_show_with_no_watch_history_syncs_as_planning(self, metadata):
        """A Planning show with nothing watched still gets its MAL entry.

        Regression: with no episode history there was nothing to resolve a
        MAL title from, so the show was never added to MAL as plan to watch
        and was reported as a mapping issue on every sync.
        """
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 3}
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        TV.objects.filter(pk=self.show.pk).update(status=Status.PLANNING.value)

        issues = []
        entries = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(
            [(entry.item.media_id, entry.progress, entry.status) for entry in entries],
            [("42", 0, Status.PLANNING.value)],
        )
        self.assertEqual(issues, [])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={})
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_unmappable_show_with_no_history_reports_no_fixable_episode(self, metadata):
        """An unresolved show with nothing watched offers no episode to fix."""
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        TV.objects.filter(pk=self.show.pk).update(status=Status.PLANNING.value)

        issues = []
        entries = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(entries, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0]["episodes"], issues[0]["seasons"]), ([], []))
        self.assertIn("No episode history", issues[0]["reason"])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_completed_show_with_no_history_is_not_pushed_as_planning(self, metadata):
        """Only a Planning show is synced without episode history."""
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 3}
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        TV.objects.filter(pk=self.show.pk).update(status=Status.COMPLETED.value)

        self.assertEqual(mal_sync.grouped_sync_entries(self.user), [])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_statusless_show_is_not_synced_despite_watched_episodes(self, metadata):
        """A show with no status isn't tracked, so its watches must not reach MAL."""
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 3}
        TV.objects.filter(pk=self.show.pk).update(status=None)

        issues = []
        entries = mal_sync.grouped_sync_entries(self.user, mapping_issues=issues)

        self.assertEqual(entries, [])
        self.assertEqual(issues, [])

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_bulk_side_effects_queue_grouped_sync_once(self, delay):
        from app.signals import flush_media_change_side_effects

        with self.captureOnCommitCallbacks(execute=True):
            flush_media_change_side_effects(
                owner=self.user, items=[self.show_item, self.season.item],
                changed_media_type="episode", reason="episode_change",
            )
            delay.assert_not_called()
        delay.assert_called_once_with(
            kwargs={"media_type": "tv", "media_id": self.show.pk},
            countdown=mal_sync.GROUPED_SYNC_DEBOUNCE_SECONDS + 1,
        )

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_removing_a_show_rating_clears_it_on_mal(self, _delay, entries, push):
        """Regression: a grouped show's removed rating was never cleared on
        MAL, so the next full sync pulled it back onto the show.
        """
        TV.objects.filter(pk=self.show.pk).update(score=Decimal("8.0"))
        show = TV.objects.get(pk=self.show.pk)
        show.score = None
        with self.captureOnCommitCallbacks(execute=True):
            show.save()
        entries.return_value = [MagicMock(score=None)]

        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)

        push.assert_called_once_with(
            entries.return_value[0], self.account, clear_score=True,
        )
        self.assertIsNone(cache.get(mal_sync.grouped_clear_score_key(self.show.pk)))

    def _cour(self, exclusive_seasons):
        media = Anime(item=Item(media_type=MediaTypes.ANIME.value), score=None, progress=2)
        media.grouped_tv = self.show
        media.grouped_exclusive_seasons = set(exclusive_seasons)
        return media

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_pulled_cour_rating_lands_on_its_own_seasons(self, _delay):
        """Regression: a cour's MAL rating went on the show, which then pushed
        it to sibling cours with different MAL ratings.
        """
        season_2 = Season(
            user=self.user, related_tv=self.show, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="100", source="tmdb", media_type="season",
                library_media_type="anime", season_number=2, title="Season 2",
            ),
        )
        Season.objects.bulk_create([season_2])

        mal_sync.pull_grouped_rating(self._cour({1}), {"score": 8}, self.account)
        mal_sync.pull_grouped_rating(self._cour({2}), {"score": 6}, self.account)

        scores = dict(
            Season.objects.filter(related_tv=self.show)
            .values_list("item__season_number", "score")
        )
        self.assertEqual(scores, {1: 8, 2: 6})
        self.assertIsNone(TV.objects.get(pk=self.show.pk).score)

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_season_shared_by_cours_is_not_rated_by_one_of_them(self, _delay):
        mal_sync.pull_grouped_rating(self._cour(set()), {"score": 8}, self.account)

        self.assertIsNone(Season.objects.get(pk=self.season.pk).score)

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_explicit_pull_onto_a_grouped_cour_takes_only_the_score(self, _delay):
        """Regression: one cour's Completed status was saved on the whole
        show, whose save then marked every season and episode watched.
        """
        mal_sync.pull_mal_entry(
            self._cour({1}), {"status": "completed", "num_episodes_watched": 12, "score": 7},
        )

        season = Season.objects.get(pk=self.season.pk)
        self.assertEqual((season.score, season.status), (7, Status.IN_PROGRESS.value))
        self.assertEqual(TV.objects.get(pk=self.show.pk).status, Status.IN_PROGRESS.value)

    def test_preview_offers_no_rating_for_a_cour_without_its_own_season(self):
        """The sync skips such a cour, so the preview mustn't promise it."""
        media = self._cour(set())

        updates = mal_sync._local_pull_updates(
            MediaTypes.ANIME.value, media, {"status": "watching", "score": 8}, self.account,
        )

        self.assertEqual(updates, {})

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_cour_rating_comes_from_its_season_not_its_first_episode(self, metadata):
        """Regression: a watch-state episode created the entry with the show's
        rating, so the pushed score depended on query order.
        """
        from app.models import WatchState

        metadata.return_value = {"title": "Mapped Anime", "max_progress": 4}
        TV.objects.filter(pk=self.show.pk).update(score=Decimal("5.0"))
        Season.objects.filter(pk=self.season.pk).update(score=Decimal("8.0"))
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        WatchState.objects.bulk_create([
            WatchState(
                user=self.user, watched=True,
                item=Item.objects.get(media_type="episode", episode_number=number),
            )
            for number in (1, 2)
        ])

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual([entry.score for entry in entries], [Decimal("8.0")])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_pulled_rating_lands_on_a_show_without_season_rows(self, _delay, metadata):
        """Regression: a show tracked through watch states alone has no season
        row to rate, so the pull saved nothing and every sync offered it again.
        """
        from app.models import WatchState

        metadata.return_value = {"title": "Mapped Anime", "max_progress": 4}
        Episode.objects.filter(related_season=self.season)._raw_delete("default")
        Season.objects.filter(pk=self.season.pk)._raw_delete("default")
        WatchState.objects.bulk_create([
            WatchState(
                user=self.user, watched=True,
                item=Item.objects.get(media_type="episode", episode_number=number),
            )
            for number in (1, 2)
        ])
        [entry] = mal_sync.grouped_sync_entries(self.user)

        with mal_sync.suppress_per_item_push():
            mal_sync.pull_grouped_rating(entry, {"score": 8}, self.account)

        self.assertEqual(TV.objects.get(pk=self.show.pk).score, 8)
        [entry] = mal_sync.grouped_sync_entries(self.user)
        self.assertEqual(
            mal_sync._local_pull_updates(
                MediaTypes.ANIME.value, entry, {"score": 8}, self.account,
            ),
            {},
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_show_with_several_cours_offers_no_show_rating(self, metadata):
        metadata.return_value = {"title": "Cour", "max_progress": 2}

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(
            [
                mal_sync._local_pull_updates(
                    MediaTypes.ANIME.value, entry, {"score": 8}, self.account,
                )
                for entry in entries
            ],
            [{}, {}],
        )

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-3": "1-3"}},
        "tmdb_show:200:s0": {"mal:42": {"1": "1"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_another_show_on_the_same_entry_keeps_its_rating(self, metadata):
        """Regression: a later, unrated show mapped to the same MAL entry
        replaced its rating with None, so every sync offered the same pull.
        """
        metadata.return_value = {"title": "Mapped Anime", "max_progress": 4}
        Season.objects.filter(pk=self.season.pk).update(score=Decimal("8.0"))
        other = TV(
            user=self.user, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="200", source="tmdb", media_type="tv",
                library_media_type="anime", title="Other Anime",
            ),
        )
        TV.objects.bulk_create([other])
        special = Season(
            user=self.user, related_tv=other, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="200", source="tmdb", media_type="season",
                library_media_type="anime", season_number=0, title="Specials",
            ),
        )
        Season.objects.bulk_create([special])
        Episode.objects.bulk_create([Episode(
            related_season=special,
            item=Item.objects.create(
                media_id="200", source="tmdb", media_type="episode",
                library_media_type="anime", season_number=0, episode_number=1,
                title="Special 1",
            ),
        )])

        [entry] = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(entry.grouped_tv, self.show)
        self.assertEqual(entry.score, Decimal("8.0"))
        self.assertEqual(entry.grouped_seasons, {1})
        self.assertEqual(entry.grouped_exclusive_seasons, {1})

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_split_season_is_exclusive_to_no_cour(self, metadata):
        metadata.return_value = {"title": "Cour", "max_progress": 2}

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual(
            [entry.grouped_exclusive_seasons for entry in entries], [set(), set()],
        )

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_removing_a_season_rating_clears_only_its_cours(self, _delay, entries, push):
        """Regression: one season's removed rating zeroed every unrated cour,
        wiping MAL ratings on seasons never rated in Floppy.
        """
        Season.objects.filter(pk=self.season.pk).update(score=Decimal("8.0"))
        season = Season.objects.get(pk=self.season.pk)
        season.score = None
        with self.captureOnCommitCallbacks(execute=True):
            season.save()
        season_one, season_three = MagicMock(score=None), MagicMock(score=None)
        season_one.grouped_seasons, season_three.grouped_seasons = {1}, {3}
        entries.return_value = [season_one, season_three]

        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)

        self.assertEqual(
            [call.kwargs["clear_score"] for call in push.call_args_list], [True, False],
        )

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_rating_removed_during_a_push_is_kept_for_the_next(self, entries, push):
        """Regression: the finished push deleted the whole flag, dropping a
        season clear queued while it ran.
        """
        key = mal_sync.grouped_clear_score_key(self.show.pk)
        cache.set(key, [1])
        entries.return_value = [MagicMock(score=None)]
        push.side_effect = lambda *_args, **_kwargs: cache.set(key, [1, 3])

        tasks.sync_mal_status(media_type="tv", media_id=self.show.pk)

        self.assertEqual(cache.get(key), [3])

    def test_rating_clear_flag_outlasts_every_push_retry(self):
        """Regression: the flag expired after ~10 minutes while retries ran
        for ~15, so the last retry no longer sent the clear.
        """
        task = tasks.sync_mal_status
        backoff = sum(
            min(task.retry_backoff * 2 ** attempt, task.retry_backoff_max)
            for attempt in range(task.max_retries)
        )
        self.assertGreater(mal_sync.GROUPED_CLEAR_FLAG_SECONDS, backoff)

    @patch("integrations.mal_sync.push_status")
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_rating_clear_survives_a_retried_push(self, entries, push):
        """Regression: the flag was dropped before pushing, so a retry after
        a 5xx no longer cleared MAL's rating.
        """
        cache.set(mal_sync.grouped_clear_score_key(self.show.pk), ["show"])
        entries.return_value = [MagicMock(score=None)]
        push.side_effect = ProviderAPIError(
            "MAL", MagicMock(response=MagicMock(status_code=503)),
        )

        with self.assertRaises(ProviderAPIError):
            tasks.sync_mal_status.run(media_type="tv", media_id=self.show.pk)

        self.assertTrue(cache.get(mal_sync.grouped_clear_score_key(self.show.pk)))

    @patch(
        "integrations.tasks.sync_mal_status.apply_async",
        side_effect=RuntimeError("broker down"),
    )
    def test_grouped_enqueue_failure_does_not_raise(self, delay):
        """A broker outage after commit is logged, and the window is freed."""
        with self.captureOnCommitCallbacks(execute=True):
            mal_sync.queue_grouped_sync(self.user.pk, self.show_item)

        delay.assert_called_once()
        self.assertIsNone(cache.get(f"mal_grouped_sync:{self.show.pk}"))

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_bulk_side_effects_queue_every_show_in_a_mixed_batch(self, delay):
        """Regression: a batch with one show's item and another show's
        episode only queued the first show.
        """
        from app.signals import flush_media_change_side_effects

        other_item = Item.objects.create(
            media_id="200", source="tmdb", media_type="tv",
            library_media_type="anime", title="Other Anime",
        )
        other_show = TV(user=self.user, item=other_item, status=Status.IN_PROGRESS.value)
        TV.objects.bulk_create([other_show])
        other_season = Season(
            user=self.user, related_tv=other_show, status=Status.IN_PROGRESS.value,
            item=Item.objects.create(
                media_id="200", source="tmdb", media_type="season",
                library_media_type="anime", season_number=1, title="Season 1",
            ),
        )
        Season.objects.bulk_create([other_season])
        other_episode = Item.objects.create(
            media_id="200", source="tmdb", media_type="episode",
            library_media_type="anime", season_number=1, episode_number=1,
            title="Episode 1",
        )

        with self.captureOnCommitCallbacks(execute=True):
            flush_media_change_side_effects(
                owner=self.user, items=[self.show_item, other_episode],
                changed_media_type="episode", reason="episode_change",
            )

        self.assertEqual(
            sorted(call.kwargs["kwargs"]["media_id"] for call in delay.call_args_list),
            sorted([self.show.pk, other_show.pk]),
        )

    @patch("integrations.mal_sync._fetch_list_statuses", new=MagicMock(return_value={}))
    @patch("integrations.mal_sync.grouped_sync_entries")
    def test_mapping_outage_fails_full_sync_without_leaving_it_queued(self, entries):
        entries.side_effect = ProviderAPIError("mal", requests.RequestException())
        self.account.full_sync_status = "queued"
        self.account.save(update_fields=["full_sync_status"])

        tasks.bulk_sync_mal_status(self.user.pk, queued=True)

        self.account.refresh_from_db()
        self.assertEqual(self.account.full_sync_status, "failed")
        self.assertEqual(self.account.full_sync_failed, 1)
        self.assertIn("mappings or metadata", self.account.full_sync_results[0]["reason"])

    @override_settings(ANIBRIDGE_MAPPING_DATA_OVERRIDE={
        "tmdb_show:100:s1": {"mal:42": {"1-2": "1-2"}, "mal:43": {"3-4": "1-2"}},
    })
    @patch("integrations.mal_sync.services.get_media_metadata")
    def test_bulk_watches_override_stale_projection(self, metadata):
        from app.models import WatchState
        from app.providers import credentials

        credentials.set_user("mal", self.user, {"client_id": "personal-mal-client"})

        def anime_metadata(*_args):
            self.assertEqual(credentials.get("mal", "client_id"), "personal-mal-client")
            return {"title": "Mapped Anime", "max_progress": 2}

        metadata.side_effect = anime_metadata
        episode = Episode.objects.get(related_season=self.season, item__episode_number=1)
        WatchState.objects.bulk_create([
            WatchState(user=self.user, item=episode.item, watched=False),
        ])
        Episode.objects.bulk_create([
            Episode(item=episode.item, related_season=self.season, dropped=True),
        ])

        entries = mal_sync.grouped_sync_entries(self.user)

        self.assertEqual({entry.item.media_id: entry.progress for entry in entries}, {"42": 2, "43": 1})

    @patch("integrations.tasks.sync_mal_status.apply_async")
    def test_repeated_triggers_push_a_show_once(self, delay):
        """One watch fires several signals; the show is still pushed once."""
        for _ in range(3):
            with self.captureOnCommitCallbacks(execute=True):
                mal_sync.queue_grouped_sync(self.user.pk, self.show_item)
                mal_sync.queue_grouped_sync(self.user.pk, self.season.item)
        delay.assert_called_once()


class SyncMALStatusTask(TestCase):
    """Test the Celery task that drives a single push to MyAnimeList."""

    def setUp(self):
        """Create a user, item and anime entry to sync."""
        self.user = _make_user()
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
        )
        with patch("integrations.tasks.sync_mal_status.delay"):
            self.anime = Anime.objects.create(
                user=self.user,
                item=self.item,
                status=Status.PAUSED.value,
            )

    def test_noop_when_media_deleted(self):
        """A media row deleted before the task runs is a silent no-op."""
        pk = self.anime.pk
        self.anime.delete()
        tasks.sync_mal_status(media_type="anime", media_id=pk)  # should not raise

    def test_noop_when_no_mal_account(self):
        """No MAL connection at all is a silent no-op."""
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)
        mock_push.assert_not_called()

    def test_noop_when_sync_disabled_or_broken(self):
        """A paused or broken connection is a silent no-op."""
        make_mal_account(self.user, sync_enabled=False)
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)
        mock_push.assert_not_called()

    def test_noop_when_per_item_sync_disabled(self):
        """Turning off per-item sync stops the per-save push only."""
        account = make_mal_account(self.user)
        account.per_item_sync_enabled = False
        account.save(update_fields=["per_item_sync_enabled"])

        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)

        mock_push.assert_not_called()

    def test_calls_push_status_when_connected(self):
        """A healthy, enabled connection gets pushed to."""
        account = make_mal_account(self.user)
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)
        mock_push.assert_called_once_with(self.anime, account, clear_score=False)

    def test_saving_a_rewatch_row_pushes_the_completed_row(self):
        """A lower rewatch row must not replace a completed MAL entry."""
        account = make_mal_account(self.user)
        with patch("integrations.tasks.sync_mal_status.delay"):
            completed = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.COMPLETED.value, progress=12,
            )
            rewatch = Anime.objects.create(
                user=self.user, item=self.item,
                status=Status.IN_PROGRESS.value, progress=3,
            )

        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=rewatch.pk)

        mock_push.assert_called_once_with(completed, account, clear_score=False)

    def test_noop_when_media_has_no_status(self):
        """Statusless imported media has no MAL list status to push."""
        make_mal_account(self.user)
        Anime.objects.filter(pk=self.anime.pk).update(status=None)

        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)

        mock_push.assert_not_called()

    def test_finds_anime_migrated_to_episode_tracking(self):
        """A migrated row syncs the current grouped history, not its old count."""
        make_mal_account(self.user)
        Anime.objects.filter(pk=self.anime.pk).update(migrated_to_item_id=None)
        # Simulate migration by pointing at a placeholder item id, matching how
        # the default ActiveAnimeManager excludes rows with migrated_to_item set.
        other_item = Item.objects.create(
            media_id="999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Migrated placeholder",
        )
        Anime.objects.filter(pk=self.anime.pk).update(migrated_to_item=other_item)
        self.assertFalse(Anime.objects.filter(pk=self.anime.pk).exists())
        self.assertTrue(Anime.all_objects.filter(pk=self.anime.pk).exists())

        show = TV(user=self.user, item=other_item, status=Status.IN_PROGRESS.value)
        TV.objects.bulk_create([show])
        projected = MagicMock()
        with (
            patch("integrations.mal_sync.push_status") as mock_push,
            patch("integrations.mal_sync.grouped_sync_entries", return_value=[projected]) as mock_entries,
        ):
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)
        mock_entries.assert_called_once_with(self.user, tv=show)
        mock_push.assert_called_once_with(projected, self.user.mal_account, clear_score=False)

    def test_not_found_from_mal_is_logged_not_raised(self):
        """A 404 from MAL (e.g. a deleted MAL entry) doesn't raise or retry."""
        make_mal_account(self.user)
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=404)))
        with patch("integrations.mal_sync.push_status", side_effect=error):
            tasks.sync_mal_status(
                media_type="anime", media_id=self.anime.pk
            )  # no raise

    def test_other_provider_errors_propagate_for_retry(self):
        """A transient (e.g. 5xx) error is re-raised so Celery can retry it."""
        make_mal_account(self.user)
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=503)))
        with (
            patch("integrations.mal_sync.push_status", side_effect=error),
            self.assertRaises(ProviderAPIError),
        ):
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)

    def test_auth_error_breaks_connection(self):
        """An expired/revoked connection turns sync off and records why."""
        account = make_mal_account(self.user)
        with patch(
            "integrations.mal_sync.push_status",
            side_effect=mal_sync.MALAuthError("expired"),
        ):
            tasks.sync_mal_status(media_type="anime", media_id=self.anime.pk)

        account.refresh_from_db()
        self.assertTrue(account.connection_broken)
        self.assertFalse(account.sync_enabled)
        self.assertIn("expired", account.last_error_message)


class BulkSyncMALStatusTask(TestCase):
    """Test the one-off "Sync All Now" background task."""

    def setUp(self):
        """Create a user with a mix of MAL-backed and non-MAL-backed entries."""
        # An empty MAL list unless a test supplies one: a failed fetch
        # stops a full sync before it pushes anything.
        lists = patch("integrations.mal_sync._fetch_list_statuses", return_value={})
        lists.start()
        self.addCleanup(lists.stop)
        self.user = _make_user()
        with patch("integrations.tasks.sync_mal_status.delay"):
            self.anime = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="1",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Anime One",
                ),
                # Covered by the default sync filters (watched); Planning
                # and Paused are excluded by default (MALSyncFiltersTests).
                status=Status.IN_PROGRESS.value,
            )
            self.manga = Manga.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="2",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.MANGA.value,
                    title="Manga One",
                ),
                status=Status.IN_PROGRESS.value,
            )
            self.tmdb_anime = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="3",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.ANIME.value,
                    title="TMDB-sourced Anime",
                ),
                status=Status.IN_PROGRESS.value,
            )

    def test_noop_when_no_account(self):
        """No connection at all is a silent no-op."""
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)
        mock_push.assert_not_called()

    def test_selected_limits_the_push_to_those_entries(self):
        """Only the entries picked in the review are pushed."""
        make_mal_account(self.user, pull_higher_progress_enabled=False)
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk, selected=["manga:2"])
        self.assertEqual(
            [call.args[0].item.media_id for call in mock_push.call_args_list],
            ["2"],
        )

    def test_pull_takes_mal_values_instead_of_pushing(self):
        """A pulled entry adopts MyAnimeList's status, progress and score."""
        make_mal_account(self.user, pull_higher_progress_enabled=False)
        remote = {
            "anime": {
                "1": {"status": "dropped", "num_episodes_watched": 5, "score": 7},
            },
            "manga": {},
        }
        with (
            patch(
                "integrations.mal_sync._fetch_list_statuses",
                side_effect=lambda media_type, _account: remote[media_type],
            ),
            patch("integrations.mal_sync.push_status") as mock_push,
            patch("integrations.tasks.sync_mal_status.delay"),
        ):
            tasks.bulk_sync_mal_status(
                user_id=self.user.pk, selected=["anime:1"], pull=["anime:1"],
            )

        mock_push.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(
            (self.anime.status, self.anime.progress, self.anime.score),
            (Status.DROPPED.value, 5, 7),
        )
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.full_sync_results[-1]["direction"], "pull")

    def test_pull_reports_the_list_fetch_error(self):
        """A pull that couldn't load the MAL list says so.

        Regression: the fetch error was swallowed, so every selected pull
        failed as "Not on your MyAnimeList list" instead.
        """
        make_mal_account(self.user, pull_higher_progress_enabled=False)
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=503)))
        with (
            patch("integrations.mal_sync._fetch_list_statuses", side_effect=error),
            patch("integrations.mal_sync.push_status"),
            patch("integrations.tasks.sync_mal_status.delay"),
        ):
            tasks.bulk_sync_mal_status(
                user_id=self.user.pk, selected=["anime:1"], pull=["anime:1"],
            )

        result = MALAccount.objects.get(user=self.user).full_sync_results[-1]
        self.assertEqual(result["outcome"], "failed")
        self.assertIn("503", result["reason"])

    def test_list_outage_pushes_nothing_when_higher_progress_is_kept(self):
        """Regression: a failed list fetch was only logged, so the sync
        pushed Floppy's lower count over MAL's higher one.
        """
        make_mal_account(self.user, pull_higher_progress_enabled=True)
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=503)))
        with (
            patch("integrations.mal_sync._fetch_list_statuses", side_effect=error),
            patch("integrations.mal_sync.push_status") as mock_push,
        ):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        mock_push.assert_not_called()
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.full_sync_status, "failed")
        self.assertIn("nothing was pushed", account.full_sync_results[0]["reason"])

    def test_schedule_does_not_take_over_a_queued_sync(self):
        """Regression: a scheduled run claimed the QUEUED row a user's review
        had just written, then pushed every entry, ignoring the user's
        selection and pulls; the user's own task found it RUNNING and quit.
        """
        make_mal_account(self.user)
        MALAccount.objects.filter(user=self.user).update(full_sync_status="queued")
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        mock_push.assert_not_called()
        self.assertEqual(
            MALAccount.objects.get(user=self.user).full_sync_status, "queued",
        )

    def test_full_sync_pulls_queue_no_per_item_pushes(self):
        """Regression: each pulled row's save queued its own push on top of
        the full sync's, doubling MAL calls on a large first sync.
        """
        make_mal_account(self.user)
        remote = {
            "anime": {"1": {"status": "watching", "num_episodes_watched": 9}},
            "manga": {},
        }
        with (
            patch(
                "integrations.mal_sync._fetch_list_statuses",
                side_effect=lambda media_type, _account: remote[media_type],
            ),
            patch("integrations.mal_sync.push_status"),
            patch("integrations.tasks.sync_mal_status.delay") as per_item,
            self.captureOnCommitCallbacks(execute=True),
        ):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 9)
        per_item.assert_not_called()

    def test_rating_pull_runs_without_progress_pull(self):
        """A rating the preview offers is pulled even when progress pulls are off."""
        make_mal_account(self.user, pull_higher_progress_enabled=False)
        remote = {
            "anime": {
                "1": {"status": "watching", "num_episodes_watched": 9, "score": 8},
            },
            "manga": {},
        }
        with (
            patch(
                "integrations.mal_sync._fetch_list_statuses",
                side_effect=lambda media_type, _account: remote[media_type],
            ),
            patch("integrations.mal_sync.push_status"),
            patch("integrations.tasks.sync_mal_status.delay"),
        ):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        self.anime.refresh_from_db()
        self.assertEqual((self.anime.score, self.anime.progress), (8, 0))

    def test_grouped_entry_never_offers_a_progress_pull(self):
        """Grouped progress is episode history, so only a rating can be pulled."""
        account = make_mal_account(self.user)
        media = Anime(item=Item(media_type=MediaTypes.ANIME.value), score=None, progress=2)
        media.grouped_tv = MagicMock()
        media.grouped_exclusive_seasons = {1}

        updates = mal_sync._local_pull_updates(
            MediaTypes.ANIME.value,
            media,
            {"status": "completed", "num_episodes_watched": 12, "score": 7},
            account,
        )

        self.assertEqual(updates, {"score": 7})

    def test_a_status_poll_during_the_entry_build_does_not_fail_the_sync(self):
        """Claiming a sync refreshes the heartbeat, even on a long-idle account."""
        account = make_mal_account(self.user, pull_higher_progress_enabled=False)
        MALAccount.objects.filter(pk=account.pk).update(
            updated_at=timezone.now() - timedelta(hours=1),
        )
        real_entries = mal_sync.full_sync_entries
        polled = []

        def poll_then_build(*args, **kwargs):
            polled.append(
                mal_sync.reconcile_stale_full_sync(
                    MALAccount.objects.get(pk=account.pk),
                ).full_sync_status,
            )
            return real_entries(*args, **kwargs)

        with (
            patch("integrations.mal_sync.full_sync_entries", side_effect=poll_then_build),
            patch("integrations.mal_sync.push_status"),
        ):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        self.assertEqual(polled, ["running"])
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "completed")

    def test_running_sync_is_not_overwritten_by_duplicate_task(self):
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.full_sync_processed = 10
        account.full_sync_results = [{"title": "Already synced", "outcome": "succeeded"}]
        account.save()
        with patch("integrations.mal_sync.full_sync_entries") as entries:
            tasks.bulk_sync_mal_status(self.user.pk)
        entries.assert_not_called()
        account.refresh_from_db()
        self.assertEqual(account.full_sync_processed, 10)
        self.assertEqual(account.full_sync_results[0]["title"], "Already synced")

    def test_stale_running_sync_is_reclaimed(self):
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.full_sync_started_at = timezone.now() - timedelta(hours=25)
        account.save(update_fields=["full_sync_status", "full_sync_started_at"])
        # updated_at is the heartbeat the reclaim now checks; auto_now means a
        # plain save() always bumps it, so backdate it with a raw update().
        type(account).objects.filter(pk=account.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )
        with patch("integrations.mal_sync.full_sync_entries", return_value=[]):
            tasks.bulk_sync_mal_status(self.user.pk)
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "completed")
        self.assertEqual(account.full_sync_total, 0)

    def test_queued_sync_fails_cleanly_when_sync_was_disabled(self):
        account = make_mal_account(self.user, sync_enabled=False)
        account.full_sync_status = "queued"
        account.save(update_fields=["full_sync_status"])

        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk, queued=True)

        mock_push.assert_not_called()
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "failed")
        self.assertIn("disabled", account.full_sync_results[0]["reason"])
        self.assertEqual(
            (account.full_sync_total, account.full_sync_succeeded, account.full_sync_failed),
            (0, 0, 1),
        )

    def test_scheduled_sync_keeps_the_last_report_while_sync_is_off(self):
        """Regression: every scheduled tick replaced the report with a single
        failure row but kept the old counts, showing e.g. 40 succeeded, 1 failed.
        """
        account = make_mal_account(self.user, sync_enabled=False)
        report = [{
            "title": "A", "media_type": "Anime", "mal_id": "1",
            "outcome": "succeeded", "reason": "",
        }]
        account.full_sync_status = "completed"
        account.full_sync_succeeded = 1
        account.full_sync_results = report
        account.save(update_fields=[
            "full_sync_status", "full_sync_succeeded", "full_sync_results",
        ])

        tasks.bulk_sync_mal_status(user_id=self.user.pk)

        account.refresh_from_db()
        self.assertEqual(
            (account.full_sync_status, account.full_sync_results), ("completed", report),
        )

    def test_pull_higher_progress_disabled_skips_the_correction(self):
        """Turning the setting off skips fetching/adopting MAL's remote progress."""
        make_mal_account(
            self.user, pull_higher_progress_enabled=False, pull_ratings_enabled=False,
        )
        with (
            patch("integrations.mal_sync.pull_higher_mal_progress") as mock_pull,
            patch("integrations.mal_sync.push_status"),
        ):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        mock_pull.assert_not_called()

    def test_pushes_only_mal_backed_entries(self):
        """Every MAL-sourced anime/manga is pushed; the TMDB one is skipped."""
        make_mal_account(self.user)
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        pushed = {call.args[0] for call in mock_push.call_args_list}
        self.assertEqual(pushed, {self.anime, self.manga})
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.full_sync_status, "completed")
        self.assertEqual(account.full_sync_total, 2)
        self.assertEqual(account.full_sync_processed, 2)
        self.assertEqual(account.full_sync_succeeded, 2)
        self.assertEqual(account.full_sync_failed, 0)
        self.assertEqual(
            {result["title"] for result in account.full_sync_results},
            {"Anime One", "Manga One"},
        )

    def test_full_sync_ignores_the_per_item_toggle(self):
        """Turning off per-item sync doesn't stop "Sync All Now"/scheduled full syncs."""
        make_mal_account(self.user, per_item_sync_enabled=False)
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        pushed = {call.args[0] for call in mock_push.call_args_list}
        self.assertEqual(pushed, {self.anime, self.manga})

    def test_skips_media_with_no_status(self):
        """Statusless imported media is omitted from a full sync."""
        make_mal_account(self.user)
        Anime.objects.filter(pk=self.anime.pk).update(status=None)

        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        mock_push.assert_called_once_with(self.manga, self.user.mal_account)

    def test_stops_and_breaks_connection_on_auth_error(self):
        """An auth failure partway through stops the batch and disables sync."""
        account = make_mal_account(self.user)
        with patch(
            "integrations.mal_sync.push_status",
            side_effect=mal_sync.MALAuthError("expired"),
        ) as mock_push:
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        account.refresh_from_db()
        self.assertTrue(account.connection_broken)
        self.assertFalse(account.sync_enabled)
        self.assertEqual(account.full_sync_status, "failed")
        self.assertEqual(account.full_sync_failed, 1)
        self.assertEqual(account.full_sync_results[0]["reason"], "expired")
        self.assertEqual(mock_push.call_count, 1)

    def test_continues_and_records_failures(self):
        """A non-auth failure on one entry doesn't abort the rest of the batch."""
        make_mal_account(self.user)
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=404)))
        with patch("integrations.mal_sync.push_status", side_effect=[error, None]):
            tasks.bulk_sync_mal_status(user_id=self.user.pk)

        account = MALAccount.objects.get(user=self.user)
        self.assertIn("1 of 2", account.last_error_message)
        self.assertEqual(account.full_sync_status, "completed")
        self.assertEqual(account.full_sync_succeeded, 1)
        self.assertEqual(account.full_sync_failed, 1)
        failed_result = next(
            result
            for result in account.full_sync_results
            if result["outcome"] == "failed"
        )
        self.assertTrue(failed_result["reason"])


class FullSyncEntriesFilters(TestCase):
    """Test the account-level status/rating filters applied to a full sync."""

    def setUp(self):
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        with patch("integrations.tasks.sync_mal_status.delay"):
            self.completed = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="1",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Completed Anime",
                ),
                status=Status.COMPLETED.value,
                score=Decimal(8),
            )
            self.in_progress = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="2",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="In Progress Anime",
                ),
                status=Status.IN_PROGRESS.value,
                score=Decimal(7),
            )
            self.dropped = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="3",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Dropped Anime",
                ),
                status=Status.DROPPED.value,
                score=Decimal(6),
            )
            self.planning = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="4",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Planning Anime",
                ),
                status=Status.PLANNING.value,
            )
            self.paused = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="5",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Paused Anime",
                ),
                status=Status.PAUSED.value,
            )
            self.unrated_dropped = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="6",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Unrated Dropped Anime",
                ),
                status=Status.DROPPED.value,
                score=None,
            )

    def test_defaults_include_watched_and_dropped_but_not_planning_or_paused(self):
        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            {media.item.title for media in entries},
            {
                "Completed Anime",
                "In Progress Anime",
                "Dropped Anime",
                "Unrated Dropped Anime",
            },
        )

    def test_filtered_out_best_row_is_not_replaced_by_a_rewatch(self):
        """Regression: with Completed filtered out, a rewatch row at 3 was
        pushed as "watching 3" over MAL's completed 12, although the per-item
        push and the pulls treat the completed watch as the entry.
        """
        rewatched = Item.objects.create(
            media_id="7", source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value, title="Rewatched",
        )
        with patch("integrations.tasks.sync_mal_status.delay"):
            Anime.objects.create(
                user=self.user, item=rewatched, status=Status.COMPLETED.value, progress=12,
            )
            Anime.objects.create(
                user=self.user, item=rewatched, status=Status.IN_PROGRESS.value, progress=3,
            )
        self.account.sync_filter_completed = False
        self.account.save(update_fields=["sync_filter_completed"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertNotIn("Rewatched", {media.item.title for media in entries})

    def test_planning_and_paused_can_be_opted_in(self):
        self.account.sync_filter_planning = True
        self.account.sync_filter_paused = True
        self.account.save(update_fields=["sync_filter_planning", "sync_filter_paused"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertTrue(
            {"Planning Anime", "Paused Anime"} <= {media.item.title for media in entries},
        )

    def test_unchecking_completed_drops_completed_only(self):
        self.account.sync_filter_completed = False
        self.account.save(update_fields=["sync_filter_completed"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            {media.item.title for media in entries},
            {"In Progress Anime", "Dropped Anime", "Unrated Dropped Anime"},
        )

    def test_unchecking_in_progress_drops_in_progress_only(self):
        self.account.sync_filter_in_progress = False
        self.account.save(update_fields=["sync_filter_in_progress"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            {media.item.title for media in entries},
            {"Completed Anime", "Dropped Anime", "Unrated Dropped Anime"},
        )

    def test_unchecking_dropped_drops_dropped_entries(self):
        self.account.sync_filter_dropped = False
        self.account.save(update_fields=["sync_filter_dropped"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            {media.item.title for media in entries},
            {"Completed Anime", "In Progress Anime"},
        )

    def test_rated_only_excludes_entries_without_a_score(self):
        self.account.sync_filter_rated_only = True
        self.account.save(update_fields=["sync_filter_rated_only"])

        entries = mal_sync.full_sync_entries(self.user, self.account)

        self.assertEqual(
            {media.item.title for media in entries},
            {"Completed Anime", "In Progress Anime", "Dropped Anime"},
        )

    def test_no_account_includes_watched_and_dropped_only(self):
        """Without an account to read filters from, fall back to the defaults."""
        entries = mal_sync.full_sync_entries(self.user)

        self.assertEqual(
            {media.item.title for media in entries},
            {
                "Completed Anime",
                "In Progress Anime",
                "Dropped Anime",
                "Unrated Dropped Anime",
            },
        )


class MALSyncFiltersView(TestCase):
    """Test the view that saves the full-sync status/rating filters."""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_without_account_shows_error(self):
        response = self.client.post(reverse("mal_sync_filters_save"), follow=True)
        self.assertContains(response, "Connect a MyAnimeList account")

    def test_saves_selected_filters(self):
        account = make_mal_account(self.user)
        response = self.client.post(
            reverse("mal_sync_filters_save"),
            {"dropped": "on", "paused": "on", "rated_only": "on"},
            follow=True,
        )

        self.assertContains(response, "sync filters saved")
        account.refresh_from_db()
        self.assertFalse(account.sync_filter_completed)
        self.assertFalse(account.sync_filter_in_progress)
        self.assertTrue(account.sync_filter_dropped)
        self.assertFalse(account.sync_filter_planning)
        self.assertTrue(account.sync_filter_paused)
        self.assertTrue(account.sync_filter_rated_only)
        self.assertFalse(account.sync_ratings_enabled)
        self.assertFalse(account.pull_higher_progress_enabled)
        self.assertFalse(account.pull_ratings_enabled)


@tag("slow", "playwright")
class MALSyncReportBrowser(StaticLiveServerTestCase):
    """The saved report remains visible when polling fails, including on reload."""

    def test_report_survives_reload_on_desktop_and_mobile(self):
        import tempfile
        from pathlib import Path

        from playwright.sync_api import expect, sync_playwright

        user = _make_user()
        account = make_mal_account(user)
        account.full_sync_status = "completed"
        account.full_sync_processed = 65
        account.full_sync_succeeded = 65
        account.full_sync_results = [
            {"title": f"Synced Anime {index}", "media_type": "Anime",
             "mal_id": str(index), "outcome": "succeeded", "reason": ""}
            for index in range(65)
        ] + [{
            "title": "Unmapped Anime", "media_type": "Anime", "mal_id": "",
            "outcome": "skipped", "reason": "No reliable MAL episode mapping for: S01E03",
        }]
        account.save()
        self.client.force_login(user)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context()
            context.add_cookies([{
                "name": settings.SESSION_COOKIE_NAME,
                "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                "url": self.live_server_url,
            }])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/sync/mal/full/status", lambda route: route.abort())
            for width, height in ((1366, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(self.live_server_url + reverse("mal_export"))
                for _ in range(2):
                    expect(page.get_by_text("65 results", exact=True)).to_be_visible()
                    expect(page.get_by_text("Synced Anime 64", exact=True)).to_be_visible()
                    expect(page.get_by_text("Unmapped Anime", exact=True)).to_be_hidden()
                    page.get_by_role("tab", name="Mapping Issues").click()
                    expect(page.get_by_text("Unmapped Anime", exact=True)).to_be_visible()
                    expect(page.get_by_text("Synced Anime 64", exact=True)).to_be_hidden()
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width,
                    )
                    page.get_by_text("Anime with mapping issues", exact=True).first.scroll_into_view_if_needed()
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / f"mal-report-{width}.png"))
                    page.reload()
            self.assertEqual(errors, [])
            context.close()
            browser.close()


class RetryFailedMALStatusTask(TestCase):
    """Test retrying only the entries marked failed on the last full sync."""

    def setUp(self):
        self.user = _make_user()
        self.account = make_mal_account(self.user)
        with patch("integrations.tasks.sync_mal_status.delay"):
            self.anime = Anime.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="1", source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value, title="Anime One",
                ),
                status=Status.IN_PROGRESS.value,
            )
            self.manga = Manga.objects.create(
                user=self.user,
                item=Item.objects.create(
                    media_id="2", source=Sources.MAL.value,
                    media_type=MediaTypes.MANGA.value, title="Manga One",
                ),
                status=Status.IN_PROGRESS.value,
            )
        self.account.full_sync_status = "completed"
        self.account.full_sync_total = 2
        self.account.full_sync_succeeded = 1
        self.account.full_sync_failed = 1
        self.account.full_sync_results = [
            {
                "title": "Anime One", "media_type": "Anime", "mal_id": "1",
                "outcome": "failed", "reason": "boom",
            },
            {
                "title": "Manga One", "media_type": "Manga", "mal_id": "2",
                "outcome": "succeeded", "reason": "",
            },
        ]
        self.account.save()

    def test_noop_without_failed_entries(self):
        self.account.full_sync_results = [self.account.full_sync_results[1]]
        self.account.save(update_fields=["full_sync_results"])
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.retry_failed_mal_status(self.user.pk)
        mock_push.assert_not_called()

    def test_disabled_sync_releases_the_queued_retry(self):
        """Regression: the early return left the page's QUEUED row, so new
        syncs were refused as in progress for 15 minutes.
        """
        self.account.sync_enabled = False
        self.account.full_sync_status = "queued"
        self.account.save(update_fields=["sync_enabled", "full_sync_status"])

        tasks.retry_failed_mal_status(self.user.pk, queued=True)

        self.account.refresh_from_db()
        self.assertFalse(self.account.full_sync_is_active)

    def test_noop_when_sync_disabled(self):
        self.account.sync_enabled = False
        self.account.save(update_fields=["sync_enabled"])
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.retry_failed_mal_status(self.user.pk)
        mock_push.assert_not_called()

    def test_retries_only_the_failed_entry(self):
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.retry_failed_mal_status(self.user.pk)

        mock_push.assert_called_once_with(self.anime, self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.full_sync_status, "completed")
        self.assertEqual(self.account.full_sync_succeeded, 2)
        self.assertEqual(self.account.full_sync_failed, 0)
        results_by_id = {result["mal_id"]: result for result in self.account.full_sync_results}
        self.assertEqual(results_by_id["1"]["outcome"], "succeeded")
        self.assertEqual(results_by_id["2"]["outcome"], "succeeded")

    def test_failed_pull_is_retried_as_a_pull(self):
        """Retry repeats the direction the user chose for the entry.

        Regression: retry always pushed, so a failed pull overwrote MAL with
        Floppy's values - or added a title that wasn't on the MAL list.
        """
        self.account.full_sync_results[0]["direction"] = "pull"
        self.account.save(update_fields=["full_sync_results"])
        remote = {"1": {"status": "completed", "num_episodes_watched": 12, "score": 9}}
        with (
            patch("integrations.mal_sync._fetch_list_statuses", return_value=remote),
            patch("integrations.mal_sync.push_status") as mock_push,
            patch("integrations.tasks.sync_mal_status.delay"),
        ):
            tasks.retry_failed_mal_status(self.user.pk)

        mock_push.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(
            (self.anime.status, self.anime.progress, self.anime.score),
            (Status.COMPLETED.value, 12, 9),
        )
        self.account.refresh_from_db()
        results_by_id = {result["mal_id"]: result for result in self.account.full_sync_results}
        self.assertEqual(results_by_id["1"]["outcome"], "succeeded")
        self.assertEqual(results_by_id["1"]["reason"], "Pulled from MyAnimeList")

    def test_entry_that_fails_again_keeps_its_updated_reason(self):
        error = ProviderAPIError("MAL", MagicMock(response=MagicMock(status_code=503)))
        with patch("integrations.mal_sync.push_status", side_effect=error):
            tasks.retry_failed_mal_status(self.user.pk)

        self.account.refresh_from_db()
        self.assertEqual(self.account.full_sync_status, "completed")
        self.assertEqual(self.account.full_sync_failed, 1)
        results_by_id = {result["mal_id"]: result for result in self.account.full_sync_results}
        self.assertEqual(results_by_id["1"]["outcome"], "failed")
        self.assertIn("503", results_by_id["1"]["reason"])

    def test_auth_error_breaks_connection_and_stops(self):
        with patch(
            "integrations.mal_sync.push_status",
            side_effect=mal_sync.MALAuthError("expired"),
        ):
            tasks.retry_failed_mal_status(self.user.pk)

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertFalse(self.account.sync_enabled)
        self.assertEqual(self.account.full_sync_status, "failed")

    def test_running_sync_blocks_retry(self):
        self.account.full_sync_status = "running"
        self.account.full_sync_started_at = timezone.now()
        self.account.save(update_fields=["full_sync_status", "full_sync_started_at"])
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.retry_failed_mal_status(self.user.pk)
        mock_push.assert_not_called()


class MALFullSyncView(TestCase):
    """Test the "Sync All Now" view."""

    def setUp(self):
        """Create and log in a user."""
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_without_account_shows_error(self):
        """No connection at all shows a clear error, no task queued."""
        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync"), follow=True)
        mock_delay.assert_not_called()
        self.assertContains(response, "Connect a MyAnimeList account")

    def test_broken_connection_shows_error(self):
        """A broken connection blocks a full sync until reconnected."""
        make_mal_account(self.user, connection_broken=True)
        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync"), follow=True)
        mock_delay.assert_not_called()
        self.assertContains(response, "Reconnect")

    def test_healthy_connection_queues_task(self):
        """A working connection queues the background task for this user."""
        make_mal_account(self.user)
        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(
                reverse("mal_full_sync"), {"confirmed": "true"}, follow=True
            )
        mock_delay.assert_called_once_with(
            user_id=self.user.pk, selected=None, pull=[], queued=True,
        )
        self.assertContains(response, "started in the background")
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.full_sync_status, "queued")
        self.assertEqual(account.full_sync_results, [])

    def test_active_sync_is_not_queued_twice(self):
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.save(update_fields=["full_sync_status"])

        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(
                reverse("mal_full_sync"), {"confirmed": "true"}, follow=True
            )

        mock_delay.assert_not_called()
        self.assertContains(response, "already in progress")

    def test_stale_running_sync_can_be_restarted(self):
        """A row left RUNNING by a killed worker must not block starting a new sync."""
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.save(update_fields=["full_sync_status"])
        MALAccount.objects.filter(pk=account.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(
                reverse("mal_full_sync"), {"confirmed": "true"}, follow=True
            )

        mock_delay.assert_called_once_with(
            user_id=self.user.pk, selected=None, pull=[], queued=True,
        )
        self.assertContains(response, "started in the background")
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "queued")

    def test_status_returns_latest_persisted_progress(self):
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.full_sync_total = 4
        account.full_sync_processed = 2
        account.full_sync_succeeded = 1
        account.full_sync_failed = 1
        account.full_sync_results = [{"title": "A", "media_type": "Anime", "mal_id": "1", "outcome": "failed", "reason": ""}]
        account.full_sync_results = [
            {
                "title": "Failed Anime",
                "media_type": "Anime",
                "mal_id": "42",
                "outcome": "failed",
                "reason": "Not found",
            }
        ]
        account.save()

        response = self.client.get(reverse("mal_full_sync_status"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], 2)
        self.assertTrue(response.json()["is_active"])
        self.assertEqual(response.json()["results"][0]["reason"], "Not found")

    def test_status_does_not_expose_another_users_sync(self):
        other_user = _make_user(username="other")
        make_mal_account(other_user)

        response = self.client.get(reverse("mal_full_sync_status"))

        self.assertEqual(response.status_code, 404)

    def test_status_poll_reconciles_a_stale_running_sync(self):
        """Polling must not show a spinner forever once the worker has died."""
        account = make_mal_account(self.user)
        account.full_sync_status = "running"
        account.save(update_fields=["full_sync_status"])
        MALAccount.objects.filter(pk=account.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        response = self.client.get(reverse("mal_full_sync_status"))

        self.assertEqual(response.json()["status"], "failed")
        self.assertFalse(response.json()["is_active"])

    def test_retry_without_account_shows_error(self):
        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)
        mock_delay.assert_not_called()
        self.assertContains(response, "Connect a MyAnimeList account")

    def test_retry_without_failed_entries_shows_error(self):
        make_mal_account(self.user)
        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)
        mock_delay.assert_not_called()
        self.assertContains(response, "No failed MyAnimeList entries")

    def test_broker_outage_releases_the_queued_sync(self):
        """Regression: with Redis down the view raised a 500 and left the
        account QUEUED, refusing every sync for 15 minutes.
        """
        from kombu.exceptions import OperationalError

        make_mal_account(self.user)
        with patch(
            "integrations.tasks.bulk_sync_mal_status.delay",
            side_effect=OperationalError("redis down"),
        ):
            response = self.client.post(
                reverse("mal_full_sync"), {"confirmed": "true"}, follow=True,
            )

        self.assertContains(response, "Could not queue the sync")
        account = MALAccount.objects.get(user=self.user)
        self.assertEqual(account.full_sync_status, "failed")
        self.assertFalse(account.full_sync_is_active)

    def test_broker_outage_releases_the_queued_retry(self):
        from kombu.exceptions import OperationalError

        account = make_mal_account(self.user)
        account.full_sync_status = "completed"
        account.full_sync_failed = 1
        account.full_sync_results = [{
            "title": "A", "media_type": "Anime", "mal_id": "1",
            "outcome": "failed", "reason": "",
        }]
        account.save(update_fields=[
            "full_sync_status", "full_sync_failed", "full_sync_results",
        ])
        with patch(
            "integrations.tasks.retry_failed_mal_status.delay",
            side_effect=OperationalError("redis down"),
        ):
            response = self.client.post(
                reverse("mal_full_sync_retry_failed"), follow=True,
            )

        self.assertContains(response, "Could not queue the retry")
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "completed")

    def test_retry_is_refused_when_only_the_whole_sync_failed(self):
        """Regression: an aborted sync's single row had no MAL entry, so a
        retry pushed nothing and still reported "1 entries still failed".
        """
        account = make_mal_account(self.user)
        account.full_sync_status = "failed"
        account.full_sync_failed = 1
        account.full_sync_results = [{
            "title": "MyAnimeList lists", "media_type": "Anime", "mal_id": "",
            "outcome": "failed", "reason": "Couldn't load your MyAnimeList lists",
        }]
        account.save(update_fields=[
            "full_sync_status", "full_sync_failed", "full_sync_results",
        ])

        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)

        mock_delay.assert_not_called()
        self.assertContains(response, "run a full sync again")
        self.assertEqual(mal_sync.full_sync_report(account)["retryable"], 0)

    def test_retry_queues_task_when_entries_failed(self):
        account = make_mal_account(self.user)
        account.full_sync_failed = 2
        account.full_sync_results = [{"title": "A", "media_type": "Anime", "mal_id": "1", "outcome": "failed", "reason": ""}]
        account.save(update_fields=["full_sync_results", "full_sync_failed"])

        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)

        mock_delay.assert_called_once_with(user_id=self.user.pk, queued=True)
        self.assertContains(response, "Retrying failed MyAnimeList entries")
        account.refresh_from_db()
        self.assertEqual(account.full_sync_status, "queued")

    def test_retry_blocked_while_sync_active(self):
        account = make_mal_account(self.user)
        account.full_sync_failed = 1
        account.full_sync_results = [{"title": "A", "media_type": "Anime", "mal_id": "1", "outcome": "failed", "reason": ""}]
        account.full_sync_status = "running"
        account.save(update_fields=["full_sync_results", "full_sync_failed", "full_sync_status"])

        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)

        mock_delay.assert_not_called()
        self.assertContains(response, "already in progress")

    def test_retry_reclaims_a_stale_running_sync(self):
        account = make_mal_account(self.user)
        account.full_sync_failed = 1
        account.full_sync_results = [{"title": "A", "media_type": "Anime", "mal_id": "1", "outcome": "failed", "reason": ""}]
        account.full_sync_status = "running"
        account.save(update_fields=["full_sync_results", "full_sync_failed", "full_sync_status"])
        MALAccount.objects.filter(pk=account.pk).update(
            updated_at=timezone.now() - timedelta(minutes=30),
        )

        with patch("integrations.tasks.retry_failed_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync_retry_failed"), follow=True)

        mock_delay.assert_called_once_with(user_id=self.user.pk, queued=True)
        self.assertContains(response, "Retrying failed MyAnimeList entries")

    def test_complete_report_survives_page_reload(self):
        account = make_mal_account(self.user)
        account.full_sync_status = "completed"
        account.full_sync_results = [
            {"title": f"Synced Anime {index}", "media_type": "Anime",
             "mal_id": str(index), "outcome": "succeeded", "reason": ""}
            for index in range(65)
        ]
        account.save(update_fields=["full_sync_status", "full_sync_results"])

        for _ in range(2):
            response = self.client.get(reverse("mal_export"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["mal_sync_initial"]["results"], account.full_sync_results)
            self.assertContains(response, "Synced Anime 64")
        status = self.client.get(reverse("mal_full_sync_status")).json()
        self.assertEqual(len(status["results"]), 65)

        account.connection_broken = True
        account.save(update_fields=["connection_broken"])
        page = self.client.get(reverse("mal_export"))
        self.assertContains(page, "Full sync status")
        self.assertContains(page, 'x-for="(entry, index) in syncResults()"')

    def test_mapping_issues_are_in_page_tab_not_review_modal(self):
        make_mal_account(self.user)
        response = self.client.get(reverse("mal_export"))
        self.assertContains(response, 'id="mal-mapping-tab"')
        self.assertContains(response, 'aria-labelledby="mal-mapping-tab"')
        self.assertContains(response, '@click="previewMalSync(false)"')
        self.assertContains(response, 'class="max-h-96 overflow-y-auto space-y-2 pr-2"')
        self.assertContains(response, "Fix whole season")
        self.assertContains(response, "activeModal === 'mal-mapping-wizard'")
        self.assertContains(response, 'x-for="result in mappingSearchResults"')
        self.assertContains(response, 'x-for="episode in malEpisodeOptions"')
        self.assertContains(response, ':aria-valuenow="malSyncPreviewProgress"')
        page, modal = response.content.decode().split('x-show="activeModal === \'mal-sync-preview\'"', 1)
        self.assertIn("Anime with mapping issues", page)
        self.assertNotIn("Anime with mapping issues", modal)

    def test_full_sync_requires_preview_confirmation(self):
        make_mal_account(self.user)
        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            response = self.client.post(reverse("mal_full_sync"), follow=True)
        mock_delay.assert_not_called()
        self.assertContains(response, "Review the MyAnimeList changes")

    @patch("integrations.mal_sync.preview_full_sync")
    def test_preview_returns_changes_without_queuing_sync(self, mock_preview):
        make_mal_account(self.user)
        mock_preview.return_value = [
            {
                "title": "Changed Anime",
                "media_type": "Anime",
                "mal_id": "42",
                "not_on_list": False,
                "changes": [
                    {"field": "Status", "from": "watching", "to": "completed"}
                ],
            }
        ]

        with patch("integrations.tasks.bulk_sync_mal_status.delay") as mock_delay:
            result = tasks.preview_mal_sync(self.user.pk)

        self.assertEqual(result["count"], 1)
        mock_delay.assert_not_called()

    @patch("integrations.tasks.preview_mal_sync.delay")
    @patch("integrations.mal_sync.preview_full_sync")
    def test_preview_request_queues_without_doing_provider_work(self, preview, delay):
        make_mal_account(self.user)
        delay.return_value.id = "preview-task"
        response = self.client.post(reverse("mal_full_sync_preview"))
        self.assertEqual(response.status_code, 202)
        preview.assert_not_called()
        delay.assert_called_once_with(self.user.pk)
        token = response.json()["token"]
        with patch("integrations.tasks.preview_mal_sync.AsyncResult") as result:
            result.return_value.ready.return_value = False
            result.return_value.info = {
                "percent": 42,
                "message": "Checking anime mappings",
            }
            pending = self.client.get(reverse("mal_full_sync_preview"), {"token": token})
            self.assertEqual(pending.status_code, 202)
            self.assertEqual(pending.json()["progress"], 42)
            self.assertEqual(pending.json()["message"], "Checking anime mappings")
            result.return_value.ready.return_value = True
            result.return_value.failed.return_value = False
            result.return_value.result = {"changes": [], "mapping_issues": [], "count": 0}
            completed = self.client.get(reverse("mal_full_sync_preview"), {"token": token})
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["count"], 0)
        other = _make_user(username="other-preview")
        make_mal_account(other)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("mal_full_sync_preview"), {"token": token}).status_code, 404)

    @patch("integrations.tasks.preview_mal_sync.delay")
    def test_preview_result_links_each_title_to_its_page(self, delay):
        """The web request turns the worker's link fields into a detail URL."""
        make_mal_account(self.user)
        delay.return_value.id = "preview-task"
        token = self.client.post(reverse("mal_full_sync_preview")).json()["token"]
        with patch("integrations.tasks.preview_mal_sync.AsyncResult") as result:
            result.return_value.ready.return_value = True
            result.return_value.failed.return_value = False
            result.return_value.result = {
                "changes": [{
                    "key": "tv:1",
                    "link": {
                        "media_type": "tv",
                        "route_media_type": "anime",
                        "source": "tvdb",
                        "media_id": "284131",
                        "title": "Nanatsu no Taizai",
                    },
                }],
                "mapping_issues": [],
                "count": 1,
            }
            completed = self.client.get(reverse("mal_full_sync_preview"), {"token": token})
        change = completed.json()["changes"][0]
        self.assertNotIn("link", change)
        self.assertEqual(
            change["url"],
            reverse(
                "media_details",
                kwargs={
                    "source": "tvdb",
                    "media_type": "anime",
                    "media_id": "284131",
                    "title": "nanatsu-no-taizai",
                },
            ),
        )

    @patch("integrations.mal_sync.preview_full_sync", side_effect=ValueError("bad mapping"))
    def test_preview_worker_returns_safe_error(self, preview):
        make_mal_account(self.user)
        result = tasks.preview_mal_sync(self.user.pk)
        self.assertIn("worker logs", result["error"])
        self.assertNotIn("bad mapping", result["error"])

    def test_preview_rejects_invalid_token_without_loading_results(self):
        make_mal_account(self.user)
        with patch("integrations.tasks.preview_mal_sync.AsyncResult") as result:
            response = self.client.get(reverse("mal_full_sync_preview"), {"token": "invalid"})
        self.assertEqual(response.status_code, 400)
        result.assert_not_called()

    def test_preview_start_requires_csrf(self):
        from django.test import Client

        make_mal_account(self.user)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with patch("integrations.tasks.preview_mal_sync.delay") as delay:
            response = client.post(reverse("mal_full_sync_preview"))
        self.assertEqual(response.status_code, 302)
        delay.assert_not_called()

    def test_preview_broker_failure_returns_json(self):
        from kombu.exceptions import OperationalError

        make_mal_account(self.user)
        with patch("integrations.tasks.preview_mal_sync.delay", side_effect=OperationalError()):
            response = self.client.post(reverse("mal_full_sync_preview"))
        self.assertEqual(response.status_code, 503)
        self.assertIn("background worker", response.json()["error"])


class MultiUserIsolation(TestCase):
    """Confirm each user's sync is scoped to their own MAL connection only."""

    def setUp(self):
        """Create two users, each with their own MAL account and anime entry."""
        self.alice = _make_user(username="alice")
        self.bob = _make_user(username="bob")
        self.alice_account = make_mal_account(self.alice)
        self.bob_account = make_mal_account(self.bob)

        with patch("integrations.tasks.sync_mal_status.delay"):
            self.alice_anime = Anime.objects.create(
                user=self.alice,
                item=Item.objects.create(
                    media_id="1",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Alice's Anime",
                ),
                status=Status.PLANNING.value,
            )
            self.bob_anime = Anime.objects.create(
                user=self.bob,
                item=Item.objects.create(
                    media_id="2",
                    source=Sources.MAL.value,
                    media_type=MediaTypes.ANIME.value,
                    title="Bob's Anime",
                ),
                status=Status.PLANNING.value,
            )

    def test_updating_one_users_anime_only_uses_their_own_account(self):
        """Syncing Alice's entry pushes through Alice's account, never Bob's."""
        with patch("integrations.mal_sync.push_status") as mock_push:
            tasks.sync_mal_status(media_type="anime", media_id=self.alice_anime.pk)
        mock_push.assert_called_once_with(self.alice_anime, self.alice_account, clear_score=False)

    def test_disconnecting_one_account_leaves_the_other_untouched(self):
        """Disconnecting Alice's account never affects Bob's connection."""
        self.client.force_login(self.alice)
        self.client.post(reverse("mal_disconnect"))
        self.assertFalse(MALAccount.objects.filter(user=self.alice).exists())
        self.assertTrue(MALAccount.objects.filter(user=self.bob).exists())
