from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
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
from integrations.models import PlaytimeSnapshot, PSNAccount

PSN_RECURRING_TASK_NAME = "Import from PSN (Recurring)"


def stats(
    title_id,
    name,
    category=PlatformCategory.PS4,
    minutes=600,
    last_played=None,
    play_count=5,
    first_played=None,
):
    """Build a psnawp TitleStats lookalike the way title_stats reports them."""
    return SimpleNamespace(
        title_id=title_id,
        name=name,
        image_url=f"http://example.com/{title_id}.png",
        category=category,
        play_count=play_count,
        first_played_date_time=first_played,
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
        cache.clear()
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


    def sync(self, titles, mode="new", media_id="1"):
        """Run one importer pass against canned PSN titles."""
        with (
            patch("integrations.psn_api.PSNAWP") as mock_psnawp,
            patch("integrations.imports.psn.services.search") as mock_search,
        ):
            mock_psnawp.side_effect = FakePSNAWP(titles)
            mock_search.side_effect = self.search_stub(media_id=media_id)
            return psn.importer(None, self.user, mode)

    def halo(self, minutes, last_played=None, first_played=None):
        """One PSN title for the game the sync tests track."""
        return [
            stats(
                "PPSA00001_00",
                "Halo Infinite",
                PlatformCategory.PS5,
                minutes,
                last_played,
                first_played=first_played,
            ),
        ]

    def test_first_sync_of_a_tracked_game_only_remembers_the_total(self):
        """A game already in the library keeps its history; PSN's lifetime
        total becomes the starting point for later syncs.
        """
        item = self.existing_game(progress=10)

        counts, _ = self.sync(self.halo(1250, timezone.now()), mode="overwrite")

        self.assertEqual(Game.objects.filter(user=self.user, item=item).count(), 1)
        self.assertEqual(Game.objects.get(user=self.user, item=item).progress, 10)
        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["baseline"], 1)
        snapshot = PlaytimeSnapshot.objects.get(user=self.user, media_id="1")
        self.assertEqual((snapshot.source, snapshot.minutes), ("psn", 1250))

    def upgrading_account(self, days_ago=2):
        """An account that synced before totals were remembered."""
        self.account.last_sync_at = timezone.now() - timedelta(days=days_ago)
        self.account.save()

    def test_first_sync_logs_play_since_the_last_sync_for_a_tracked_game(self):
        """Hours that were close to PSN's at the last sync make the difference
        the play since then, logged as its own dated entry.
        """
        item = self.existing_game(progress=600)
        self.upgrading_account(days_ago=2)
        previous_sync = self.account.last_sync_at
        last_played = timezone.now() - timedelta(hours=10)

        counts, _ = self.sync(self.halo(780, last_played))

        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts["baseline"], 0)
        entries = Game.objects.filter(user=self.user, item=item).order_by("progress")
        self.assertEqual([entry.progress for entry in entries], [180, 600])
        new = entries[0]
        self.assertEqual(new.end_date, last_played)
        self.assertEqual(new.start_date, previous_sync)
        self.assertEqual(PlaytimeSnapshot.objects.get(user=self.user).minutes, 780)

    def test_first_sync_ignores_a_gap_bigger_than_the_tracked_hours(self):
        """A library never in step with PSN isn't new play."""
        item = self.existing_game(progress=10)
        self.upgrading_account()

        counts, _ = self.sync(self.halo(600, timezone.now() - timedelta(hours=5)))

        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["baseline"], 1)
        self.assertEqual(Game.objects.filter(user=self.user, item=item).count(), 1)

    def test_first_sync_ignores_a_game_not_played_since_the_last_sync(self):
        """A difference in a game PSN hasn't launched lately is old history."""
        self.existing_game(progress=600)
        self.upgrading_account(days_ago=2)

        counts, _ = self.sync(self.halo(780, timezone.now() - timedelta(days=9)))

        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["baseline"], 1)

    def test_first_sync_of_a_new_account_logs_no_gap(self):
        """With no earlier sync there is no window to put the difference in."""
        self.existing_game(progress=600)

        counts, _ = self.sync(self.halo(780, timezone.now() - timedelta(hours=5)))

        self.assertEqual(counts["created"], 0)
        self.assertEqual(counts["baseline"], 1)

    def test_first_sync_with_hours_above_psn_logs_nothing(self):
        """Hours tracked beyond PSN's total leave no gap."""
        self.existing_game(progress=900)
        self.upgrading_account()

        counts, _ = self.sync(self.halo(780, timezone.now() - timedelta(hours=5)))

        self.assertEqual(counts["created"], 0)

    def test_message_says_when_a_sync_only_remembered_totals(self):
        """The first sync after updating must not read as "nothing happened"."""
        from integrations.tasks._import_helpers import format_import_message

        message = format_import_message({"created": 0, "skipped": 0, "baseline": 3})

        self.assertEqual(
            message,
            "No media was imported. 3 starting playtimes remembered.",
        )

    def test_later_sync_logs_the_new_time_as_a_dated_entry(self):
        """Time played since the previous sync becomes its own entry between
        that sync and PSN's last played time; existing entries are untouched.
        """
        item = self.existing_game(progress=10, status=Status.COMPLETED.value)
        self.sync(self.halo(0))
        previous = PlaytimeSnapshot.objects.get(user=self.user, media_id="1")
        previous.seen_at = timezone.now() - timedelta(days=3)
        previous.save()
        last_played = timezone.now() - timedelta(days=1)

        counts, _ = self.sync(self.halo(180, last_played))

        self.assertEqual(counts[MediaTypes.GAME.value], 1)
        self.assertEqual(counts["created"], 1)
        entries = Game.objects.filter(user=self.user, item=item).order_by("id")
        self.assertEqual(entries.count(), 2)
        old, new = entries
        self.assertEqual((old.progress, old.status), (10, Status.COMPLETED.value))
        self.assertEqual(new.progress, 180)
        self.assertEqual(new.start_date, previous.seen_at)
        self.assertEqual(new.end_date, last_played)
        self.assertEqual(new.status, Status.IN_PROGRESS.value)
        previous.refresh_from_db()
        self.assertEqual(previous.minutes, 180)

    def test_overwrite_mode_also_only_adds_entries(self):
        """There is nothing to overwrite: both modes log the same new time."""
        item = self.existing_game(progress=10)
        self.sync(self.halo(60))
        counts, _ = self.sync(self.halo(90, timezone.now()), mode="overwrite")

        self.assertEqual(counts["created"], 1)
        progress = sorted(
            Game.objects.filter(user=self.user, item=item).values_list(
                "progress",
                flat=True,
            ),
        )
        self.assertEqual(progress, [10, 30])

    def test_unchanged_sync_adds_nothing_and_moves_the_window(self):
        """With no new play nothing is logged, but the next entry starts at
        this sync rather than at the last time anything changed.
        """
        self.existing_game(progress=10)
        self.sync(self.halo(60))
        PlaytimeSnapshot.objects.update(seen_at=timezone.now() - timedelta(days=5))

        counts, _ = self.sync(self.halo(60))

        self.assertEqual(counts["created"], 0)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 1)
        snapshot = PlaytimeSnapshot.objects.get(user=self.user)
        self.assertGreater(snapshot.seen_at, timezone.now() - timedelta(minutes=1))

    def test_lower_reported_total_is_ignored(self):
        """A partial PSN answer neither logs time nor lowers the total."""
        self.existing_game(progress=10)
        self.sync(self.halo(600))

        counts, _ = self.sync(self.halo(0))

        self.assertEqual(counts["created"], 0)
        self.assertEqual(PlaytimeSnapshot.objects.get(user=self.user).minutes, 600)

    def test_new_game_is_imported_with_its_first_to_last_played_dates(self):
        """The setup import of an untracked game is one entry across its
        lifetime, which Repeats spreads and Sessions shows as a range.
        """
        first = timezone.now() - timedelta(days=300)
        last = timezone.now() - timedelta(days=20)

        counts, _ = self.sync(self.halo(1250, last, first_played=first))

        self.assertEqual(counts["created"], 1)
        game = Game.objects.get(user=self.user)
        self.assertEqual(
            (game.progress, game.start_date, game.end_date),
            (1250, first, last),
        )

    def test_new_game_without_dates_stays_dateless(self):
        """No dates from PSN means no dates here, so statistics aren't skewed."""
        self.sync(self.halo(1250))

        game = Game.objects.get(user=self.user)
        self.assertIsNone(game.start_date)
        self.assertIsNone(game.end_date)

    def test_track_new_play_only_skips_the_existing_playtime(self):
        """The setup choice to only track new play records totals but writes
        no entries for games that aren't in the library yet.
        """
        self.account.import_existing_playtime = False
        self.account.save()

        counts, _ = self.sync(self.halo(1250, timezone.now()))

        self.assertEqual(counts["created"], 0)
        self.assertFalse(Game.objects.filter(user=self.user).exists())

        PlaytimeSnapshot.objects.update(seen_at=timezone.now() - timedelta(days=2))
        counts, _ = self.sync(self.halo(1310, timezone.now()))

        self.assertEqual(counts["created"], 1)
        self.assertEqual(Game.objects.get(user=self.user).progress, 60)

    def test_deleted_game_still_advances_the_remembered_total(self):
        """A game deleted here stays gone and its old time isn't logged later."""
        self.tombstone("1")

        self.sync(self.halo(600))

        self.assertFalse(Game.objects.filter(user=self.user).exists())
        self.assertEqual(PlaytimeSnapshot.objects.get(user=self.user).minutes, 600)

    def test_failed_snapshot_save_does_not_leave_logged_play_behind(self):
        """Play logged without its remembered total would be logged again."""
        with (
            patch.object(
                psn.PSNImporter,
                "_save_snapshots",
                side_effect=RuntimeError("disk full"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.sync(self.halo(1250, timezone.now()))

        self.assertFalse(Game.objects.filter(user=self.user).exists())

    def test_overlapping_syncs_do_not_run_twice(self):
        """A second sync started while one runs is skipped, not double-logged."""
        from integrations import tasks

        cache.set(f"psn_import_lock_{self.user.id}", "other-task", 60)

        with patch("integrations.tasks._media_imports.import_media") as run:
            message = tasks.import_psn_recurring(user_id=self.user.id)

        run.assert_not_called()
        self.assertIn("already in progress", message)

    def test_scheduled_sync_skips_when_the_cache_is_down(self):
        """Without the lock an overlap could log the same play twice."""
        from integrations import tasks

        with (
            patch("app.cache_safety.cache_add", return_value=None),
            patch(
                "integrations.tasks._media_imports.import_media",
                return_value="ok",
            ) as run,
        ):
            tasks.import_psn_recurring(user_id=self.user.id)

        run.assert_not_called()

    def test_sync_releases_its_lock_when_done(self):
        """The lock doesn't outlive the sync it guards."""
        from integrations import tasks

        with patch("integrations.tasks._media_imports.import_media", return_value="ok"):
            tasks.import_psn(user_id=self.user.id)

        self.assertIsNone(cache.get(f"psn_import_lock_{self.user.id}"))

    def test_task_reports_what_a_sync_did(self):
        """A sync that only logs new time doesn't read as "No media imported"."""
        from integrations import tasks

        self.existing_game(progress=10)
        self.sync(self.halo(60))
        PlaytimeSnapshot.objects.update(seen_at=timezone.now() - timedelta(days=1))

        with (
            patch("integrations.psn_api.PSNAWP") as mock_psnawp,
            patch("integrations.imports.psn.services.search") as mock_search,
            patch("integrations.tasks._media_imports.events.tasks.reload_calendar"),
            patch("app.history_cache.invalidate_history_days") as invalidate_history,
        ):
            mock_psnawp.side_effect = FakePSNAWP(self.halo(120, timezone.now()))
            mock_search.side_effect = self.search_stub(media_id="1")
            message = tasks.import_psn(user_id=self.user.id, mode="new")

        self.assertIn("1 created", message)
        self.assertNotIn("No media was imported", message)
        invalidate_history.assert_called()

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
    def test_rate_limit_records_error_without_breaking(self, mock_psnawp):
        """A PSN rate limit is reported as such, without the raw response."""
        mock_psnawp.side_effect = psnawp_exceptions.PSNAWPTooManyRequests(
            "429 from https://m.np.playstation.com/?token=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("PSN rate limit exceeded", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)

    @patch("integrations.psn_api.PSNAWP")
    def test_transport_failure_records_error_without_breaking(self, mock_psnawp):
        """A bare requests failure is translated rather than left to escape."""
        mock_psnawp.side_effect = RequestsConnectionError(
            "Max retries exceeded with url: /authz?npsso=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("Could not reach PSN", str(context.exception))
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertNotIn("super-secret", self.account.last_error_message)

    @patch("integrations.psn_api.PSNAWP")
    def test_unexpected_fetch_failure_records_error_without_breaking(self, mock_psnawp):
        """An error psn_api doesn't model still lands as durable account state."""
        mock_psnawp.side_effect = ValueError(
            "bad payload from https://m.np.playstation.com/?npsso=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            psn.importer(None, self.user, "new")

        self.assertIn("ValueError", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertIn("ValueError", self.account.last_error_message)
        self.assertNotIn("super-secret", self.account.last_error_message)

    def test_stored_error_messages_are_scrubbed_and_bounded(self):
        """Whatever reaches the account row is redacted and length-capped."""
        self.assertEqual(
            psn._safe_message("failed with token=super-secret sent"),
            "failed with token=[REDACTED] sent",
        )

        importer = psn.PSNImporter(self.user, "new")
        importer._mark_failed("x" * 5000, auth=False)

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
        self.assertFalse(self.account.connection_broken)

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

    def setUp(self):
        """Start each test without remembered game lookups."""
        cache.clear()

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
    def test_concept_lookup_is_remembered_between_syncs(self, mock_psnawp):
        """A title already classified is not looked up again on the next sync."""
        fake = FakePSNAWP(
            titles=[stats("CUSA1", "Some Game", category=PlatformCategory.UNKNOWN)],
        )
        mock_psnawp.side_effect = fake

        psn_api.get_played_games("npsso")
        psn_api.get_played_games("npsso")

        self.assertEqual(fake.detail_calls, ["CUSA1"])

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
        """Connecting validates the token, stores it, syncs now and schedules."""
        response = self.client.post(
            reverse("psn_connect"),
            {"npsso": "npsso-token"},
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_get_account.assert_called_once_with("npsso-token")
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

        account = PSNAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.npsso), "npsso-token")
        self.assertEqual(account.account_id, "1234567890")
        self.assertEqual(account.online_id, "TestPlayer")
        self.assertTrue(account.is_connected)

        task = PeriodicTask.objects.get(task=PSN_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, f"*/{psn.SYNC_EVERY_HOURS}")
        self.assertEqual(task.crontab.minute, str(self.user.id % 60))
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
            {"npsso": "npsso-token"},
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
    @patch("integrations.views.psn_api.get_account")
    def test_remembered_totals_follow_the_connected_account(
        self,
        mock_account,
        _mock_delay,
    ):
        """Another PSN account's totals would read as fabricated or hidden play."""
        mock_account.return_value = ("1234567890", "TestPlayer")
        self.client.post(reverse("psn_connect"), {"npsso": "npsso-token"})
        PlaytimeSnapshot.objects.create(
            user=self.user,
            source="psn",
            media_id="1",
            minutes=600,
            seen_at=timezone.now(),
        )

        # Reconnecting the same account keeps what was remembered.
        self.client.post(reverse("psn_connect"), {"npsso": "new-token"})
        self.assertEqual(PlaytimeSnapshot.objects.filter(user=self.user).count(), 1)

        # A different account starts fresh, including the last sync time.
        PSNAccount.objects.filter(user=self.user).update(last_sync_at=timezone.now())
        mock_account.return_value = ("999", "OtherPlayer")
        self.client.post(reverse("psn_connect"), {"npsso": "other-token"})
        self.assertFalse(PlaytimeSnapshot.objects.filter(user=self.user).exists())
        self.assertIsNone(PSNAccount.objects.get(user=self.user).last_sync_at)

    def test_disconnect_forgets_the_remembered_totals(self):
        """Disconnecting clears them, so a later account never inherits them."""
        self._connect_account()
        PlaytimeSnapshot.objects.create(
            user=self.user,
            source="psn",
            media_id="1",
            minutes=600,
            seen_at=timezone.now(),
        )

        self.client.post(reverse("psn_disconnect"))

        self.assertFalse(PlaytimeSnapshot.objects.filter(user=self.user).exists())

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
    @patch(
        "integrations.views.psn_api.get_account",
        return_value=("1234567890", "TestPlayer"),
    )
    def test_connect_stores_the_existing_playtime_choice(self, _account, _delay):
        """The setup choice posted with the token is kept on the account."""
        self.client.post(
            reverse("psn_connect"),
            {"npsso": "npsso-token", "existing_playtime": "new_only"},
        )

        self.assertFalse(
            PSNAccount.objects.get(user=self.user).import_existing_playtime,
        )

    @patch("integrations.views.tasks.import_psn.delay")
    def test_sync_updates_the_choice_only_when_posted(self, _delay):
        """A sync form without the field leaves the saved choice alone."""
        account = self._connect_account()

        self.client.post(
            reverse("import_psn"),
            {"existing_playtime": "new_only"},
        )
        account.refresh_from_db()
        self.assertFalse(account.import_existing_playtime)

        self.client.post(reverse("import_psn"))
        account.refresh_from_db()
        self.assertFalse(account.import_existing_playtime)

    def test_card_shows_cadence_playtime_choice_and_logging_style(self):
        """The connected card states its fixed cadence, the playtime choice
        and the game logging style, each with its own short tooltip.
        """
        account = self._connect_account()
        account.import_existing_playtime = False
        account.save()

        html = self.client.get(reverse("import_data")).content.decode()

        self.assertIn("Import Backlog and Scrobble New Data", html)
        self.assertRegex(
            html,
            r'<option value="new_only"\s+selected>Scrobble New Data Only',
        )
        self.assertIn('id="psn-existing-playtime-sync"', html)
        self.assertIn("Game Logging:", html)
        self.assertIn(
            f"Syncs automatically every {psn.SYNC_EVERY_HOURS} hours.",
            html,
        )
        self.assertIn("Each sync adds one entry", html)
        self.assertIn("track yet get one entry", html)
        self.assertIn("Repeats spreads each entry", html)
        form = html.split('id="psn-sync-form"')[1].split("</form>")[0]
        self.assertNotIn('name="frequency"', form)
        self.assertNotIn('name="time"', form)

        self.user.game_logging_style = "sessions"
        self.user.save()
        html = self.client.get(reverse("import_data")).content.decode()
        self.assertIn("Sessions shows each entry", html)

    @patch("integrations.views.tasks.import_psn.delay")
    def test_sync_now_runs_now_and_keeps_one_fixed_schedule(self, mock_delay):
        """Every sync runs at once; pressing it again never doubles the schedule."""
        self._connect_account()

        for _ in range(2):
            self.client.post(reverse("import_psn"), {"mode": "watchlist"})

        self.assertEqual(mock_delay.call_count, 2)
        mock_delay.assert_called_with(user_id=self.user.id, mode="new")
        task = PeriodicTask.objects.get(task=PSN_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, f"*/{psn.SYNC_EVERY_HOURS}")
        self.assertTrue(task.enabled)

    @patch("integrations.views.tasks.import_psn.delay")
    def test_sync_now_replaces_an_older_daily_schedule(self, _mock_delay):
        """A schedule left from the old user-chosen frequency is swapped out."""
        from django_celery_beat.models import CrontabSchedule

        self._connect_account()
        daily = CrontabSchedule.objects.create(
            minute="30",
            hour="5",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name="Import from PSN for test at 05:30 daily",
            task=PSN_RECURRING_TASK_NAME,
            crontab=daily,
            kwargs=f'{{"user_id": {self.user.id}, "mode": "new"}}',
        )

        self.client.post(reverse("import_psn"))

        task = PeriodicTask.objects.get(task=PSN_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, f"*/{psn.SYNC_EVERY_HOURS}")

    @patch("integrations.views.tasks.import_psn.delay")
    def test_psn_schedule_does_not_collide_with_xbox(self, mock_delay):
        """PSN and Xbox schedules for the same user coexist."""
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
        self.client.post(reverse("import_psn"))

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
