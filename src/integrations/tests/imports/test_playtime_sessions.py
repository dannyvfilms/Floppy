"""Steam and Xbox syncs log new playtime as dated play sessions."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.models import Game, Item, MediaTypes, Sources, Status
from integrations.imports import helpers, steam, xbox
from integrations.models import PlaytimeSnapshot, XboxAccount
from integrations.tasks._import_helpers import format_import_message
from integrations.tests.imports.test_xbox import ACCOUNT_RESPONSE, stats_response, title
from integrations.tests.imports.test_xbox import envelope as xbox_envelope

STEAM_ID = "76561198000000000"


def steam_game(appid, minutes, recent=0, last_played=None):
    """Build one GetOwnedGames entry."""
    payload = {
        "appid": appid,
        "name": f"Game {appid}",
        "playtime_forever": minutes,
        "playtime_2weeks": recent,
    }
    if last_played is not None:
        payload["rtime_last_played"] = int(last_played.timestamp())
    return payload


def age_snapshots(hours):
    """Pretend the previous sync ran ``hours`` ago, as a scheduled one would."""
    PlaytimeSnapshot.objects.update(seen_at=timezone.now() - timedelta(hours=hours))


def tracked_minutes(user, media_id):
    """Return a game's total across every row, as the media views sum it."""
    return (
        Game.objects.filter(user=user, item__media_id=media_id).aggregate(
            total=Sum("progress"),
        )["total"]
        or 0
    )


class SteamPlaySessions(TestCase):
    """Steam playtime increases become dated Game rows."""

    def setUp(self):
        """Create a user and stub the IGDB lookups (app id N -> IGDB id N)."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        external = patch(
            "integrations.imports.steam.external_game",
            side_effect=lambda appid, _source: int(appid),
        )
        metadata = patch(
            "integrations.imports.steam.services.get_media_metadata",
            side_effect=lambda _type, media_id, _source: {
                "title": f"Game {media_id}",
                "image": "http://example.com/i.jpg",
            },
        )
        self.api = patch("integrations.imports.steam.services.api_request").start()
        external.start()
        metadata.start()
        self.addCleanup(patch.stopall)

    def sync(self, games, mode="new"):
        self.api.return_value = {"response": {"games": games}}
        return steam.importer(STEAM_ID, self.user, mode)

    def sessions(self, media_id="10"):
        return Game.objects.filter(
            user=self.user,
            item__media_id=media_id,
            end_date__isnull=False,
        ).order_by("end_date")

    def test_first_sync_adds_undated_lifetime_row(self):
        """A brand-new game is added as before: one undated lifetime row."""
        counts, _ = self.sync(
            [steam_game(10, 600, recent=60, last_played=timezone.now())]
        )

        game = Game.objects.get(user=self.user)
        self.assertEqual(game.progress, 600)
        self.assertIsNone(game.end_date)
        self.assertEqual(counts[MediaTypes.GAME.value], 1)
        self.assertEqual(counts["game_sessions"], 0)
        snapshot = PlaytimeSnapshot.objects.get(user=self.user, source="steam")
        self.assertEqual((snapshot.media_id, snapshot.minutes), ("10", 600))

    def test_next_sync_logs_increase_as_dated_session(self):
        """New minutes since the last sync become their own dated row."""
        self.sync([steam_game(10, 600)])
        age_snapshots(24)
        played_at = timezone.now() - timedelta(hours=1)

        counts, _ = self.sync([steam_game(10, 690, recent=90, last_played=played_at)])

        session = self.sessions().get()
        self.assertEqual(session.progress, 90)
        self.assertEqual(session.end_date, played_at.replace(microsecond=0))
        self.assertEqual(session.start_date, session.end_date - timedelta(minutes=90))
        self.assertEqual(session.notes, steam.SESSION_NOTE)
        self.assertEqual(tracked_minutes(self.user, "10"), 690)
        self.assertEqual(counts["game_sessions"], 1)
        self.assertEqual(counts[MediaTypes.GAME.value], 0)
        self.assertEqual(counts["created"], 1)
        self.assertIn("1 play sessions logged", format_import_message(counts))

    def test_session_never_starts_before_previous_sync(self):
        """A long increase is clamped to the window since the previous sync."""
        self.sync([steam_game(10, 600)])
        snapshot = PlaytimeSnapshot.objects.get(user=self.user)
        snapshot.seen_at = timezone.now() - timedelta(hours=2)
        snapshot.save()

        self.sync([steam_game(10, 900, recent=300, last_played=timezone.now())])

        session = self.sessions().get()
        self.assertEqual(session.progress, 300)
        self.assertGreaterEqual(session.start_date, snapshot.seen_at)

    def test_sessions_are_logged_in_new_mode_and_never_rewrite_rows(self):
        """Both modes only add rows; the original lifetime row stays put."""
        self.sync([steam_game(10, 600)])
        self.sync([steam_game(10, 630, recent=30, last_played=timezone.now())])
        self.sync([steam_game(10, 700, recent=100, last_played=timezone.now())])

        self.assertEqual(
            list(self.sessions().values_list("progress", flat=True)),
            [30, 70],
        )
        baseline = Game.objects.get(user=self.user, end_date__isnull=True)
        self.assertEqual(baseline.progress, 600)
        self.assertEqual(tracked_minutes(self.user, "10"), 700)

    def test_unchanged_or_lower_total_logs_nothing(self):
        """No new play, or a lower total (refund), adds no row or double count."""
        self.sync([steam_game(10, 600)])
        counts, _ = self.sync([steam_game(10, 600)])
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(counts["created"], 0)

        self.sync([steam_game(10, 550)])
        self.sync([steam_game(10, 620, recent=20, last_played=timezone.now())])

        self.assertEqual(self.sessions().get().progress, 20)
        self.assertEqual(
            PlaytimeSnapshot.objects.get(user=self.user).minutes,
            620,
        )

    def test_upgrade_remembers_tracked_game_without_backfilling(self):
        """An already-synced game becomes the starting point, not a session."""
        self.sync([steam_game(10, 1000)], mode="overwrite")
        PlaytimeSnapshot.objects.all().delete()  # as before this change

        counts, _ = self.sync([steam_game(10, 1000)], mode="overwrite")

        self.assertEqual(counts["baseline"], 1)
        self.assertFalse(self.sessions().exists())
        self.assertTrue(PlaytimeSnapshot.objects.filter(user=self.user).exists())

    def test_upgrade_dates_recent_play_steam_vouches_for(self):
        """Play since the last pre-upgrade sync is dated, up to playtime_2weeks."""
        self.sync([steam_game(10, 1000)], mode="overwrite")
        PlaytimeSnapshot.objects.all().delete()

        self.sync(
            [steam_game(10, 1060, recent=45, last_played=timezone.now())],
            mode="overwrite",
        )

        self.assertEqual(self.sessions().get().progress, 45)

    def test_overwrite_still_reconciles_drift_on_first_sighting(self):
        """Overwrite makes tracked hours match Steam when they can't be dated."""
        self.sync([steam_game(10, 10)])
        PlaytimeSnapshot.objects.all().delete()

        self.sync([steam_game(10, 1250)], mode="new")
        self.assertEqual(tracked_minutes(self.user, "10"), 10)
        PlaytimeSnapshot.objects.all().delete()

        self.sync([steam_game(10, 1250)], mode="overwrite")
        self.assertEqual(tracked_minutes(self.user, "10"), 1250)
        self.assertFalse(self.sessions().exists())

    def test_overwrite_keeps_completed_status(self):
        """A game the user marked Completed keeps that status."""
        self.sync([steam_game(10, 600)])
        Game.objects.filter(user=self.user).update(status=Status.COMPLETED.value)

        self.sync(
            [steam_game(10, 660, recent=60, last_played=timezone.now())],
            mode="overwrite",
        )

        baseline = Game.objects.get(user=self.user, end_date__isnull=True)
        self.assertEqual(baseline.status, Status.COMPLETED.value)

    def test_app_ids_for_the_same_game_are_merged(self):
        """Two Steam app IDs resolving to one IGDB game add up once."""
        with patch(
            "integrations.imports.steam.external_game",
            return_value=10,
        ):
            self.sync([steam_game(10, 100), steam_game(11, 50)])
            self.sync(
                [
                    steam_game(10, 130, recent=30, last_played=timezone.now()),
                    steam_game(11, 50),
                ],
            )

        self.assertEqual(self.sessions().get().progress, 30)
        self.assertEqual(tracked_minutes(self.user, "10"), 180)

    def test_session_shows_up_in_history(self):
        """The dated row is what makes the play appear on the History page."""
        self.sync([steam_game(10, 600)])
        self.sync([steam_game(10, 690, recent=90, last_played=timezone.now())])

        for style in ("sessions", "repeats"):
            with self.subTest(style=style):
                history_cache.invalidate_history_cache(self.user.id, force=True)
                days = history_cache.build_history_days(
                    self.user,
                    filters={"media_type": MediaTypes.GAME.value},
                    logging_style_override=style,
                )
                minutes = sum(
                    entry["runtime_minutes"]
                    for day in days
                    for entry in day["entries"]
                    if entry["media_type"] == MediaTypes.GAME.value
                )
                self.assertEqual(minutes, 90)


class XboxPlaySessions(TestCase):
    """Xbox playtime increases become dated Game rows."""

    def setUp(self):
        """Create a connected account and stub OpenXBL and IGDB search."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.account = XboxAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("test-key"),
            xuid="2535473210914202",
            gamertag="TestGamer",
        )
        self.minutes = {}
        self.last_played = None

        def api(_provider, method, url, **_kwargs):
            if method == "POST":
                return stats_response(self.minutes)
            if url.endswith("/account"):
                return ACCOUNT_RESPONSE
            if "/achievements/player/" in url:
                played = self.last_played.isoformat() if self.last_played else None
                return xbox_envelope(
                    {"titles": [title("1777860928", "Halo Infinite", played)]},
                )
            return xbox_envelope({"titles": []})

        patch("integrations.xbox_api.services.api_request", side_effect=api).start()
        patch(
            "integrations.imports.xbox.services.search",
            return_value={
                "results": [
                    {
                        "media_id": "1",
                        "title": "Halo Infinite",
                        "image": "http://example.com/i.jpg",
                    },
                ],
            },
        ).start()
        self.addCleanup(patch.stopall)

    def sync(self, minutes, last_played=None, mode="new"):
        if minutes is None:
            self.minutes = {}
        else:
            self.minutes = {"1777860928": minutes}
        self.last_played = last_played
        return xbox.importer(None, self.user, mode)

    def sessions(self):
        return Game.objects.filter(user=self.user, end_date__isnull=False)

    def test_next_sync_logs_increase_as_dated_session(self):
        """New minutes since the last sync become their own dated row."""
        self.sync(1000, timezone.now() - timedelta(days=3))
        age_snapshots(3)
        played_at = timezone.now() - timedelta(minutes=5)

        counts, _ = self.sync(1120, played_at)

        session = self.sessions().get()
        self.assertEqual(session.progress, 120)
        self.assertEqual(session.end_date, played_at)
        self.assertEqual(session.notes, xbox.SESSION_NOTE)
        self.assertEqual(session.status, Status.IN_PROGRESS.value)
        self.assertEqual(tracked_minutes(self.user, "1"), 1120)
        self.assertEqual(counts["game_sessions"], 1)

    def test_stale_last_played_ends_session_at_sync_time(self):
        """A last-played time from before the previous sync isn't used."""
        self.sync(1000)
        before = timezone.now()

        self.sync(1060, timezone.now() - timedelta(days=30))

        self.assertGreaterEqual(self.sessions().get().end_date, before)

    def test_upgrade_dates_play_since_last_account_sync(self):
        """An upgraded account dates play since its last sync, capped by time."""
        item = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Halo Infinite",
            image="http://example.com/i.jpg",
        )
        Game.objects.create(
            item=item,
            user=self.user,
            status=Status.PAUSED.value,
            progress=1000,
        )
        self.account.last_sync_at = timezone.now() - timedelta(minutes=90)
        self.account.save()

        self.sync(1200, timezone.now() - timedelta(minutes=1))

        # 200 new minutes can't fit in 90; only what fits is dated.
        self.assertEqual(self.sessions().get().progress, 90)
        self.assertTrue(PlaytimeSnapshot.objects.filter(source="xbox").exists())

    def test_unreported_minutes_leave_tracking_alone(self):
        """No MinutesPlayed: no snapshot, no session, hours untouched."""
        self.sync(1000)
        counts, _ = self.sync(None, timezone.now(), mode="overwrite")

        self.assertEqual(tracked_minutes(self.user, "1"), 1000)
        self.assertFalse(self.sessions().exists())
        self.assertEqual(counts["created"], 0)
