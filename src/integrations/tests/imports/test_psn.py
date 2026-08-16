from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from psnawp_api.core import psnawp_exceptions
from psnawp_api.models.title_stats import PlatformCategory
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

from app.models import DeletedMedia, Game, Item, MediaTypes, Sources, Status
from app.providers import services
from integrations import psn_api
from integrations.imports import helpers, psn
from integrations.models import PSNAccount

PSN_RECURRING_TASK_NAME = "Import from PSN (Recurring)"


def stats(
    title_id,
    name,
    category=PlatformCategory.PS4,
    minutes=600,
    last_played=None,
    play_count=5,
):
    """Build a psnawp TitleStats lookalike the way title_stats reports them."""
    return SimpleNamespace(
        title_id=title_id,
        name=name,
        image_url=f"http://example.com/{title_id}.png",
        category=category,
        play_count=play_count,
        first_played_date_time=None,
        last_played_date_time=last_played,
        play_duration=timedelta(minutes=minutes),
    )


class FakeGameTitle:
    """Stand-in for psnawp's GameTitle with canned concept details."""

    def __init__(self, details):
        """Store the canned details or exception to raise."""
        self.details = details

    def get_details(self):
        """Return the canned concept payload."""
        if isinstance(self.details, Exception):
            raise self.details
        return self.details


class FakePSNAWP:
    """Stand-in for the psnawp entry point."""

    def __init__(
        self,
        titles=None,
        details_by_id=None,
        account=("1234567890", "TestPlayer"),
    ):
        """Store the canned titles, concept details and account identity."""
        self.titles = titles or []
        self.details_by_id = details_by_id or {}
        self.account = account
        self.detail_calls = []
        # psn_api._client wraps this to inject a request timeout.
        self.authenticator = SimpleNamespace(
            request_builder=SimpleNamespace(request=lambda method, **kwargs: None),
        )

    def __call__(self, npsso):
        """Mimic ``PSNAWP(npsso)``."""
        return self

    def me(self):
        """Return the client for the token owner."""
        account_id, online_id = self.account
        return SimpleNamespace(
            account_id=account_id,
            online_id=online_id,
            title_stats=lambda: iter(self.titles),
        )

    def game_title(self, title_id, account_id=None, np_communication_id=None):
        """Return the concept details stub for a title."""
        self.detail_calls.append(title_id)
        return FakeGameTitle(
            self.details_by_id.get(title_id, [{"genres": ["ACTION"]}]),
        )


class ImportPSN(TestCase):
    """Test importing played games from PlayStation Network."""

    def setUp(self):
        """Create a user with a connected PSN account."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.account = PSNAccount.objects.create(
            user=self.user,
            npsso=helpers.encrypt("test-npsso"),
            account_id="1234567890",
            online_id="TestPlayer",
        )
        recent = timezone.now() - timedelta(days=2)
        old = timezone.now() - timedelta(days=400)
        self.titles = [
            stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5, 1250, recent),
            stats("CUSA00002_00", "Forza Horizon 5", PlatformCategory.PS4, 500, old),
            stats("CUSA00003_00", "Never Launched", PlatformCategory.PS4, 0, None),
        ]

    def search_stub(self, media_id=None):
        """Return a services.search stub that matches every title by name."""
        counter = {"n": 0}

        def side_effect(_media_type, query, _page, source=None):
            counter["n"] += 1
            return {
                "results": [
                    {
                        "media_id": media_id or str(counter["n"]),
                        "title": query,
                        "image": "http://example.com/i.jpg",
                    },
                ],
            }

        return side_effect

    def existing_game(self, progress, status=Status.PAUSED.value, media_id="1"):
        """Create a pre-existing tracked game without triggering provider calls."""
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Halo Infinite",
            image="http://example.com/halo.jpg",
        )
        game = Game.objects.create(
            item=item,
            user=self.user,
            status=Status.PAUSED.value,
            progress=progress,
        )
        if status != Status.PAUSED.value:
            # .update() bypasses save(), which would fetch metadata for COMPLETED.
            Game.objects.filter(pk=game.pk).update(status=status)
        return item

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_import_psn_games(self, mock_psnawp, mock_search):
        """Played titles import with minutes and a status derived from last played."""
        mock_psnawp.side_effect = FakePSNAWP(self.titles)
        mock_search.side_effect = self.search_stub()

        imported_counts, _ = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 3)

        games = Game.objects.filter(user=self.user)
        halo = games.get(item__title="Halo Infinite")
        self.assertEqual(halo.progress, 1250)
        self.assertEqual(halo.status, Status.IN_PROGRESS.value)

        forza = games.get(item__title="Forza Horizon 5")
        self.assertEqual(forza.progress, 500)
        self.assertEqual(forza.status, Status.PAUSED.value)

        # Zero minutes and no last played date.
        never = games.get(item__title="Never Launched")
        self.assertEqual(never.progress, 0)
        self.assertEqual(never.status, Status.PLANNING.value)

        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)
        self.assertFalse(self.account.connection_broken)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_same_game_on_both_platforms_aggregates(self, mock_psnawp, mock_search):
        """PS4 and PS5 releases of one game merge into a single tracked game."""
        recent = timezone.now() - timedelta(days=1)
        old = timezone.now() - timedelta(days=100)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats("CUSA10001_00", "Ghost of Tsushima", PlatformCategory.PS4, 900, old),
                stats("PPSA10002_00", "Ghost of Tsushima", PlatformCategory.PS5, 300, recent),
            ],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        imported_counts, warnings = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(warnings, "")
        game = Game.objects.get(user=self.user)
        self.assertEqual(game.progress, 1200)
        # The PS5 session is recent, so the merged game reads as in progress.
        self.assertEqual(game.status, Status.IN_PROGRESS.value)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_overwrite_updates_progress(self, mock_psnawp, mock_search):
        """PSN's cumulative duration replaces existing progress on overwrite."""
        item = self.existing_game(progress=10)
        mock_psnawp.side_effect = FakePSNAWP(
            [stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5, 1250)],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 1250)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_overwrite_preserves_completed_status(self, mock_psnawp, mock_search):
        """A manually completed game keeps its status on re-sync."""
        item = self.existing_game(progress=10, status=Status.COMPLETED.value)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats(
                    "PPSA00001_00",
                    "Halo Infinite",
                    PlatformCategory.PS5,
                    1250,
                    recent,
                ),
            ],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.status, Status.COMPLETED.value)
        self.assertEqual(game.progress, 1250)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_status_set_completed_mid_sync_is_not_clobbered(
        self,
        mock_psnawp,
        mock_search,
    ):
        """A user marking a game Completed while the sync runs keeps that
        status: the guard must hold against the database state at write
        time, not the snapshot read before the long matching phase.
        """
        item = self.existing_game(progress=10)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats(
                    "PPSA00001_00",
                    "Halo Infinite",
                    PlatformCategory.PS5,
                    1250,
                    recent,
                ),
            ],
        )
        good = self.search_stub(media_id="1")

        def search_and_complete_concurrently(media_type, query, page, source=None):
            # Simulates the user's edit landing between the importer's
            # snapshot and its final write.
            Game.objects.filter(user=self.user, item__media_id="1").update(
                status=Status.COMPLETED.value,
            )
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search_and_complete_concurrently

        psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.status, Status.COMPLETED.value)
        self.assertEqual(game.progress, 1250)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_new_mode_leaves_existing_progress_and_status_alone(
        self,
        mock_psnawp,
        mock_search,
    ):
        """The default "new" mode must never touch an existing game's
        progress or status, only refresh the item metadata.
        """
        item = self.existing_game(progress=10)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats(
                    "PPSA00001_00",
                    "Halo Infinite",
                    PlatformCategory.PS5,
                    1250,
                    recent,
                ),
            ],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        imported_counts, _ = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts.get(MediaTypes.GAME.value, 0), 0)
        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 10)
        self.assertEqual(game.status, Status.PAUSED.value)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_overwrite_preserves_dropped_status(self, mock_psnawp, mock_search):
        """A manually dropped game keeps its status but gets fresh hours."""
        item = self.existing_game(progress=10, status=Status.DROPPED.value)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats(
                    "PPSA00001_00",
                    "Halo Infinite",
                    PlatformCategory.PS5,
                    1250,
                    recent,
                ),
            ],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.status, Status.DROPPED.value)
        self.assertEqual(game.progress, 1250)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_partial_lookup_failure_never_lowers_progress(
        self,
        mock_psnawp,
        mock_search,
    ):
        """A failed lookup for one of several aggregated title IDs must not
        shrink progress to the partial sum of the titles that did match.
        """
        item = self.existing_game(progress=1200)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats(
                    "CUSA00001_00",
                    "Halo Infinite PS4EDITION",
                    PlatformCategory.PS4,
                    900,
                    recent,
                ),
                stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5, 300, recent),
            ],
        )
        good = self.search_stub(media_id="1")

        def search(media_type, query, page, source=None):
            if "PS4EDITION" in query:
                raise services.ProviderAPIError("IGDB", "transient")
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search

        _, warnings = psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 1200)
        self.assertIn("Halo Infinite PS4EDITION", warnings)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_zero_reported_playtime_never_lowers_progress(
        self,
        mock_psnawp,
        mock_search,
    ):
        """PSN reports playDuration 0 for some played games (e.g. Life Is
        Strange); like Xbox's unreported minutes, that must not zero
        tracked hours on overwrite.
        """
        item = self.existing_game(progress=1200)
        recent = timezone.now() - timedelta(days=1)
        mock_psnawp.side_effect = FakePSNAWP(
            [stats("CUSA00001_00", "Halo Infinite", PlatformCategory.PS4, 0, recent)],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        psn.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 1200)

    def tombstone(self, media_id):
        """Record that the user deleted this IGDB game locally."""
        return DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            media_id=media_id,
        )

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_deleted_game_is_not_recreated(self, mock_psnawp, mock_search):
        """PSN reports a title forever, but a locally deleted game stays gone."""
        self.tombstone("1")
        mock_psnawp.side_effect = FakePSNAWP(
            [stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5, 1250)],
        )
        mock_search.side_effect = self.search_stub(media_id="1")

        imported_counts, _ = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts.get(MediaTypes.GAME.value, 0), 0)
        self.assertFalse(Game.objects.filter(user=self.user).exists())

        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)
        self.assertFalse(self.account.connection_broken)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_deleted_game_does_not_block_the_rest_of_the_library(
        self,
        mock_psnawp,
        mock_search,
    ):
        """Only the tombstoned title is skipped; the others still import."""
        self.tombstone("1")
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5),
                stats("CUSA00002_00", "Forza Horizon 5", PlatformCategory.PS4),
            ],
        )

        def search_by_name(_media_type, query, _page, source=None):
            return {
                "results": [
                    {
                        "media_id": "1" if "Halo" in query else "2",
                        "title": query,
                        "image": "http://example.com/i.jpg",
                    },
                ],
            }

        mock_search.side_effect = search_by_name

        imported_counts, _ = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(
            list(
                Game.objects.filter(user=self.user).values_list(
                    "item__media_id",
                    flat=True,
                ),
            ),
            ["2"],
        )

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_apps_are_never_imported_as_games(self, mock_psnawp, mock_search):
        """Uncategorised titles without store genres are dropped before IGDB."""
        fake = FakePSNAWP(
            [
                stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5, 60),
                stats("CUSA00127_00", "Netflix", PlatformCategory.UNKNOWN),
                stats("CUSA24899_00", "Stray", PlatformCategory.UNKNOWN, 240),
            ],
            details_by_id={
                "CUSA00127_00": [{"genres": []}],
                "CUSA24899_00": [{"genres": ["ADVENTURE"]}],
            },
        )
        mock_psnawp.side_effect = fake
        mock_search.side_effect = self.search_stub()

        imported_counts, warnings = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 2)
        # The skip is deliberate but must stay auditable by the user: the
        # genre heuristic is best-effort, and a misclassified game would
        # otherwise vanish silently.
        self.assertIn("Netflix", warnings)
        self.assertIn("non-game", warnings)
        self.assertNotIn("Stray", warnings)
        # Only the uncategorised titles cost a concept lookup.
        self.assertEqual(
            sorted(fake.detail_calls),
            ["CUSA00127_00", "CUSA24899_00"],
        )
        self.assertEqual(
            [call.args[1] for call in mock_search.call_args_list],
            ["Halo Infinite", "Stray"],
        )

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_failed_concept_lookup_keeps_the_title(self, mock_psnawp, mock_search):
        """A title whose concept lookup fails imports rather than vanishing."""
        mock_psnawp.side_effect = FakePSNAWP(
            [stats("CUSA18723_00", "ELDEN RING", PlatformCategory.UNKNOWN, 3000)],
            details_by_id={
                "CUSA18723_00": psnawp_exceptions.PSNAWPNotFound("not found"),
            },
        )
        mock_search.side_effect = self.search_stub(media_id="7")

        imported_counts, _ = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertTrue(
            Game.objects.filter(user=self.user, item__media_id="7").exists(),
        )

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_concept_lookup_failures_fail_open_per_title(
        self,
        mock_psnawp,
        mock_search,
    ):
        """Rate limits, auth blips and transport errors on the per-title
        concept lookup keep the title and never abort the whole sync.
        """
        errors = (
            psnawp_exceptions.PSNAWPTooManyRequests("429"),
            psnawp_exceptions.PSNAWPUnauthorized("401"),
            psnawp_exceptions.PSNAWPClientError("418"),
            RequestsTimeout("timed out"),
        )
        for index, error in enumerate(errors):
            with self.subTest(error=type(error).__name__):
                mock_psnawp.side_effect = FakePSNAWP(
                    [
                        stats(
                            "CUSA18723_00",
                            "ELDEN RING",
                            PlatformCategory.UNKNOWN,
                            3000,
                        ),
                    ],
                    details_by_id={"CUSA18723_00": error},
                )
                # A fresh IGDB id per subtest: deleting games between runs
                # would leave DeletedMedia tombstones that block the import.
                mock_search.side_effect = self.search_stub(media_id=str(100 + index))

                imported_counts, _ = psn.importer(None, self.user, "new")

                self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
                self.account.refresh_from_db()
                self.assertFalse(self.account.connection_broken)

    @patch("integrations.psn_api.PSNAWP")
    def test_invalid_token_marks_account_broken(self, mock_psnawp):
        """An expired NPSSO surfaces a reconnect message and flags the account."""
        mock_psnawp.side_effect = psnawp_exceptions.PSNAWPAuthenticationError(
            "Your npsso code has expired or is incorrect: super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("Invalid or expired PSN NPSSO token", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertNotIn("super-secret", self.account.last_error_message)

    @patch("integrations.psn_api.PSNAWP")
    def test_rate_limit_marks_account_broken(self, mock_psnawp):
        """A PSN rate limit is reported as such, without the raw response."""
        mock_psnawp.side_effect = psnawp_exceptions.PSNAWPTooManyRequests(
            "429 from https://m.np.playstation.com/?token=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("PSN rate limit exceeded", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.psn_api.PSNAWP")
    def test_transport_failure_marks_account_broken(self, mock_psnawp):
        """A bare requests failure is translated rather than left to escape."""
        mock_psnawp.side_effect = RequestsConnectionError(
            "Max retries exceeded with url: /authz?npsso=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("Could not reach PSN", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertNotIn("super-secret", self.account.last_error_message)

    @patch("integrations.psn_api.PSNAWP")
    def test_unexpected_fetch_failure_marks_account_broken(self, mock_psnawp):
        """An error psn_api doesn't model still lands as durable account state."""
        mock_psnawp.side_effect = ValueError(
            "bad payload from https://m.np.playstation.com/?npsso=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("ValueError", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("ValueError", self.account.last_error_message)
        self.assertNotIn("super-secret", self.account.last_error_message)

    def test_stored_error_messages_are_scrubbed_and_bounded(self):
        """Whatever reaches the account row is redacted and length-capped."""
        self.assertEqual(
            psn._safe_message("failed with token=super-secret sent"),
            "failed with token=[REDACTED] sent",
        )

        importer = psn.PSNImporter(self.user, "new")
        importer._mark_broken("x" * 5000)

        self.account.refresh_from_db()
        self.assertLessEqual(
            len(self.account.last_error_message),
            psn.MAX_ERROR_MESSAGE_LENGTH,
        )
        self.assertTrue(self.account.last_error_message.endswith("…"))

    def test_import_without_connected_account(self):
        """Importing without a connected account raises a clear error."""
        PSNAccount.objects.filter(user=self.user).delete()
        self.user.refresh_from_db()

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn(
            "Connect PlayStation Network before importing",
            str(context.exception),
        )

    @patch("integrations.psn_api.PSNAWP")
    def test_unsupported_mode_is_rejected(self, mock_psnawp):
        """Modes PSN cannot act on fail loudly instead of behaving like "new"."""
        for mode in ("watchlist", "update_collection", "", None):
            with self.assertRaises(helpers.MediaImportError) as context:
                psn.importer(None, self.user, mode)

            self.assertIn("Unsupported PSN import mode", str(context.exception))

        self.assertFalse(mock_psnawp.called)
        # A bad mode is a caller error, not a broken connection.
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_unmatched_title_warns_instead_of_failing(self, mock_psnawp, mock_search):
        """A title IGDB doesn't know shows up as a warning, not a failure."""
        mock_psnawp.side_effect = FakePSNAWP(
            [
                stats("PPSA00001_00", "Halo Infinite", PlatformCategory.PS5),
                stats("CUSA99999_00", "Obscure Japan-Only Game", PlatformCategory.PS4),
            ],
        )
        good = self.search_stub(media_id="1")

        def search(media_type, query, page, source=None):
            if "Obscure" in query:
                return {"results": []}
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search

        imported_counts, warnings = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertIn("Obscure Japan-Only Game", warnings)
        self.assertIn("Couldn't find a match", warnings)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_one_failing_title_does_not_lose_the_rest(self, mock_psnawp, mock_search):
        """A provider error on one title must not discard the whole import."""
        mock_psnawp.side_effect = FakePSNAWP(self.titles)
        good = self.search_stub()

        def search(media_type, query, page, source=None):
            if query == "Forza Horizon 5":
                raise services.ProviderAPIError("IGDB", "boom")
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search

        imported_counts, warnings = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 2)
        self.assertIn("Forza Horizon 5", warnings)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 2)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_total_lookup_failure_reports_clearly(self, mock_psnawp, mock_search):
        """Every title failing means the provider is down, not an empty library."""
        mock_psnawp.side_effect = FakePSNAWP(self.titles)
        mock_search.side_effect = services.ProviderAPIError("IGDB", "unauthorized")

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("Could not reach", str(context.exception))
        self.assertEqual(Game.objects.filter(user=self.user).count(), 0)
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_total_non_provider_failure_does_not_blame_igdb(
        self,
        mock_psnawp,
        mock_search,
    ):
        """Every title failing on our own bug must not read as IGDB being down."""
        mock_psnawp.side_effect = FakePSNAWP(self.titles)
        mock_search.side_effect = TypeError("unhashable type: 'dict'")

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        message = str(context.exception)
        self.assertNotIn("Could not reach", message)
        # The exception type is named; its message is not, since an unexpected
        # exception can carry the request URL or the credentials sent with it.
        self.assertIn("TypeError", message)
        self.assertNotIn("unhashable type", message)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 0)

    @patch("integrations.psn_api.PSNAWP")
    def test_empty_library_still_marks_synced(self, mock_psnawp):
        """No played titles is a successful (empty) sync, not an error."""
        mock_psnawp.side_effect = FakePSNAWP([])

        imported_counts, warnings = psn.importer(None, self.user, "new")

        self.assertEqual(imported_counts, {})
        self.assertEqual(warnings, "")
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)

    def test_determine_game_status_logic(self):
        """Status is derived from minutes played and last played date."""
        importer_instance = psn.PSNImporter(self.user, "new")

        self.assertEqual(
            importer_instance._determine_game_status(0, None),
            Status.PLANNING.value,
        )
        self.assertEqual(
            importer_instance._determine_game_status(
                60,
                timezone.now() - timedelta(days=2),
            ),
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(
            importer_instance._determine_game_status(
                60,
                timezone.now() - timedelta(days=60),
            ),
            Status.PAUSED.value,
        )
        self.assertEqual(
            importer_instance._determine_game_status(60, None),
            Status.PAUSED.value,
        )

    def test_search_names_strips_psn_store_decorations(self):
        """PSN store suffixes and characters are normalised for IGDB."""
        cases = {
            "It Takes Two  PS4™ & PS5™": ["It Takes Two PS4 & PS5", "It Takes Two"],
            "Gran Turismo™SPORT": ["Gran Turismo SPORT"],
            "FINAL FANTASY Ⅻ THE ZODIAC AGE": ["FINAL FANTASY XII THE ZODIAC AGE"],
            "God of War® III Remastered": ["God of War III Remastered"],
            "Uncharted™: The Nathan Drake Collection": [
                "Uncharted: The Nathan Drake Collection",
            ],
            "Horizon Zero Dawn™": ["Horizon Zero Dawn"],
        }
        for raw, expected in cases.items():
            self.assertEqual(list(psn._search_names(raw)), expected, raw)

    def test_search_names_leaves_clean_names_alone(self):
        """Titles without store decorations must not be altered."""
        for raw in (
            "Cyberpunk 2077",
            "Kena: Bridge of Spirits",
            "Marvel's Spider-Man: Miles Morales",
        ):
            self.assertEqual(list(psn._search_names(raw)), [raw], raw)

    def test_search_names_strips_editions_as_fallback(self):
        """Edition suffixes fall away in the last candidate."""
        self.assertEqual(
            list(psn._search_names("Control: Ultimate Edition PS4")),
            [
                "Control: Ultimate Edition PS4",
                "Control: Ultimate Edition",
                "Control",
            ],
        )

    @patch("integrations.imports.psn.services.search")
    @patch("integrations.psn_api.PSNAWP")
    def test_celery_task_runs_the_importer(self, mock_psnawp, mock_search):
        """The registered task wires through import_media to the importer."""
        from integrations import tasks

        mock_psnawp.side_effect = FakePSNAWP(self.titles)
        mock_search.side_effect = self.search_stub()

        result = tasks.import_psn(user_id=self.user.id, mode="new")

        self.assertIn("3", str(result))
        self.assertEqual(Game.objects.filter(user=self.user).count(), 3)


class PSNAPITests(TestCase):
    """Test the psn_api client helpers directly."""

    @patch("integrations.psn_api.PSNAWP")
    def test_get_account_returns_ids(self, mock_psnawp):
        """The connect-time validation returns account and online IDs."""
        mock_psnawp.side_effect = FakePSNAWP(account=("9876", "SomePlayer"))

        self.assertEqual(psn_api.get_account("npsso"), ("9876", "SomePlayer"))

    @patch("integrations.psn_api.PSNAWP")
    def test_get_account_translates_auth_errors(self, mock_psnawp):
        """A rejected token becomes a constructed MediaImportError."""
        mock_psnawp.side_effect = psnawp_exceptions.PSNAWPAuthenticationError(
            "expired: super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn_api.get_account("npsso")

        self.assertIn("Invalid or expired PSN NPSSO token", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))

    @patch("integrations.psn_api.PSNAWP")
    def test_client_injects_request_timeout(self, mock_psnawp):
        """Requests get a default timeout injected, since psnawp sends none."""
        captured = {}

        def raw_request(method, **kwargs):
            captured.update(kwargs, method=method)

        fake = FakePSNAWP()
        fake.authenticator.request_builder.request = raw_request
        mock_psnawp.side_effect = fake

        client = psn_api._client("npsso")
        client.authenticator.request_builder.request("get", url="https://x")

        self.assertEqual(
            captured["timeout"],
            psn_api.REQUEST_TIMEOUT_SECONDS,
        )

    @patch("integrations.psn_api.PSNAWP")
    def test_unknown_psnawp_error_names_the_type_only(self, mock_psnawp):
        """An unmodelled psnawp error is reported by type, not by message."""
        mock_psnawp.side_effect = psnawp_exceptions.PSNAWPServerError(
            "500 body with npsso=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn_api.get_account("npsso")

        self.assertIn("PSN is currently unavailable", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))


class PSNViewTests(TestCase):
    """Test the PSN connect/disconnect/import views."""

    def setUp(self):
        """Create and log in a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("integrations.views.tasks.import_psn.delay")
    @patch(
        "integrations.views.psn_api.get_account",
        return_value=("1234567890", "TestPlayer"),
    )
    def test_connect_stores_token_and_imports_once(
        self,
        mock_get_account,
        mock_delay,
    ):
        """A one time connect validates the token, stores it and imports now."""
        response = self.client.post(
            reverse("psn_connect"),
            {"npsso": "npsso-token", "frequency": "once", "mode": "new"},
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_get_account.assert_called_once_with("npsso-token")
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

        account = PSNAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.npsso), "npsso-token")
        self.assertEqual(account.account_id, "1234567890")
        self.assertEqual(account.online_id, "TestPlayer")
        self.assertTrue(account.is_connected)

        self.assertFalse(
            PeriodicTask.objects.filter(task=PSN_RECURRING_TASK_NAME).exists(),
        )

    @patch("integrations.views.tasks.import_psn.delay")
    @patch(
        "integrations.views.psn_api.get_account",
        return_value=("1234567890", "TestPlayer"),
    )
    def test_connect_with_frequency_only_schedules(
        self,
        _mock_get_account,
        mock_delay,
    ):
        """A recurring connect schedules the import instead of running it."""
        self.client.post(
            reverse("psn_connect"),
            {
                "npsso": "npsso-token",
                "frequency": "daily",
                "time": "05:30",
                "mode": "new",
            },
        )

        mock_delay.assert_not_called()
        task = PeriodicTask.objects.get(task=PSN_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, "5")
        self.assertEqual(task.crontab.minute, "30")
        self.assertEqual(task.crontab.day_of_week, "*")
        self.assertIn("Import from PSN for test", task.name)

    @patch("integrations.views.psn_api.get_account")
    def test_connect_requires_token(self, mock_get_account):
        """Submitting an empty token is rejected before calling PSN."""
        response = self.client.post(reverse("psn_connect"), {})

        self.assertRedirects(response, reverse("import_data"))
        mock_get_account.assert_not_called()
        self.assertFalse(PSNAccount.objects.filter(user=self.user).exists())

    @patch(
        "integrations.views.psn_api.get_account",
        side_effect=helpers.MediaImportError("Invalid or expired PSN NPSSO token."),
    )
    def test_connect_with_invalid_token_is_not_stored(self, _mock_get_account):
        """A token PSN rejects is never persisted."""
        response = self.client.post(
            reverse("psn_connect"),
            {"npsso": "bad-token"},
            follow=True,
        )

        self.assertContains(response, "Could not connect to PlayStation Network")
        self.assertFalse(PSNAccount.objects.filter(user=self.user).exists())

    @patch(
        "integrations.views.psn_api.get_account",
        side_effect=ValueError("bad payload for npsso=super-secret"),
    )
    def test_connect_failure_does_not_echo_the_raw_error(self, _mock_get_account):
        """The token travels with this request, so nothing raw goes back."""
        response = self.client.post(
            reverse("psn_connect"),
            {"npsso": "npsso-token"},
            follow=True,
        )

        self.assertContains(response, "Failed to connect to PlayStation Network")
        self.assertContains(response, "ValueError")
        self.assertNotContains(response, "super-secret")
        self.assertFalse(PSNAccount.objects.filter(user=self.user).exists())

    @patch("integrations.views.tasks.import_psn.delay")
    @patch(
        "integrations.views.psn_api.get_account",
        return_value=("1234567890", "TestPlayer"),
    )
    def test_disconnect_removes_account_and_schedule(self, _mock_account, _mock_delay):
        """Disconnecting deletes both the account row and its periodic task."""
        self.client.post(
            reverse("psn_connect"),
            {"npsso": "npsso-token", "frequency": "daily", "time": "04:00"},
        )
        self.assertTrue(
            PeriodicTask.objects.filter(task=PSN_RECURRING_TASK_NAME).exists(),
        )

        response = self.client.post(reverse("psn_disconnect"))

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(PSNAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task=PSN_RECURRING_TASK_NAME,
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists(),
        )

    @patch("integrations.views.tasks.import_psn.delay")
    def test_sync_now_requires_connected_account(self, mock_delay):
        """Sync Now without a connected account queues nothing."""
        response = self.client.post(reverse("import_psn"), follow=True)

        self.assertContains(response, "Connect PlayStation Network before importing.")
        mock_delay.assert_not_called()

    def _connect_account(self):
        """Attach a connected PSN account to the logged in user."""
        return PSNAccount.objects.create(
            user=self.user,
            npsso=helpers.encrypt("npsso-token"),
            account_id="1234567890",
            online_id="TestPlayer",
        )

    @patch("integrations.views.tasks.import_psn.delay")
    def test_one_time_import_runs_now_without_scheduling(self, mock_delay):
        """A one time import runs straight away and schedules nothing."""
        self._connect_account()

        self.client.post(
            reverse("import_psn"),
            {"frequency": "once", "mode": "overwrite", "time": "04:00"},
        )

        mock_delay.assert_called_once_with(user_id=self.user.id, mode="overwrite")
        self.assertFalse(
            PeriodicTask.objects.filter(task=PSN_RECURRING_TASK_NAME).exists(),
        )

    @patch("integrations.views.tasks.import_psn.delay")
    def test_scheduled_import_does_not_run_immediately(self, mock_delay):
        """A scheduled import only runs on schedule, never on creation."""
        self._connect_account()

        self.client.post(
            reverse("import_psn"),
            {"frequency": "2days", "mode": "new", "time": "23:15"},
        )

        mock_delay.assert_not_called()
        task = PeriodicTask.objects.get(task=PSN_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, "23")
        self.assertEqual(task.crontab.minute, "15")
        self.assertEqual(task.crontab.day_of_week, "*/2")

    @patch("integrations.views.tasks.import_psn.delay")
    def test_psn_schedule_does_not_collide_with_xbox(self, mock_delay):
        """PSN and Xbox schedules for the same user and time coexist."""
        from integrations.models import XboxAccount

        self._connect_account()
        XboxAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("openxbl-key"),
            xuid="123",
        )

        self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "new", "time": "04:00"},
        )
        self.client.post(
            reverse("import_psn"),
            {"frequency": "daily", "mode": "new", "time": "04:00"},
        )

        mock_delay.assert_not_called()
        self.assertEqual(
            PeriodicTask.objects.filter(task=PSN_RECURRING_TASK_NAME).count(),
            1,
        )
        self.assertEqual(
            PeriodicTask.objects.filter(
                task="Import from Xbox (Recurring)",
            ).count(),
            1,
        )
