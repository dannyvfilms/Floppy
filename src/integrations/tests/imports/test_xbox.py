import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError

from app.models import DeletedMedia, Game, Item, MediaTypes, Sources, Status
from app.providers import services
from integrations.imports import helpers, xbox
from integrations.models import XboxAccount

XBOX_RECURRING_TASK_NAME = "Import from Xbox (Recurring)"

# OpenXBL wraps every v2 payload in {"content": ..., "code": ...}.
def envelope(payload):
    """Wrap a payload the way the live OpenXBL v2 API does."""
    return {"content": payload, "code": 200}


ACCOUNT_RESPONSE = envelope(
    {
        "profileUsers": [
            {
                "id": "2535473210914202",
                "settings": [
                    {"id": "Gamertag", "value": "TestGamer"},
                    {"id": "Gamerscore", "value": "19165"},
                ],
            },
        ],
    },
)

METADATA = {
    "title": "Halo Infinite",
    "image": "http://example.com/halo.jpg",
    "max_progress": None,
}


def title(
    title_id,
    name,
    last_played=None,
    pfn="Publisher.Game_6h0y724g59e1w",
    devices=None,
    title_type="Game",
):
    """Build a minimal OpenXBL title payload.

    Mirrors the live shape: ``detail`` is always null, so ``pfn`` is the only
    external identifier available.
    """
    payload = {
        "titleId": title_id,
        "name": name,
        "type": title_type,
        "pfn": pfn,
        "detail": None,
        "modernTitleId": title_id,
    }
    if devices:
        payload["devices"] = devices
    if last_played:
        payload["titleHistory"] = {"lastTimePlayed": last_played, "visible": True}
    return payload


def stats_response(minutes_by_title):
    """Build a batch user-stats response for the given titles."""
    return envelope(
        {
            "groups": [],
            "statlistscollection": [
                {
                    "arrangebyfield": "xuid",
                    "stats": [
                        {
                            "xuid": "2535473210914202",
                            "titleid": title_id,
                            "name": "MinutesPlayed",
                            "type": "Integer",
                            "value": str(minutes),
                        }
                        for title_id, minutes in minutes_by_title.items()
                    ],
                },
            ],
        },
    )


class ImportXbox(TestCase):
    """Test importing played games from Xbox via OpenXBL."""

    def setUp(self):
        """Create a user with a connected Xbox account."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.account = XboxAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("test-key"),
            xuid="2535473210914202",
            gamertag="TestGamer",
        )
        recent = (timezone.now() - timedelta(days=2)).isoformat()
        old = (timezone.now() - timedelta(days=400)).isoformat()
        self.titles_response = {
            "titles": [
                title("1777860928", "Halo Infinite", recent),
                title("1810924247", "Forza Horizon 5", old),
                title("1234567890", "Never Launched"),
            ],
        }

    def api_stub(self, minutes=None):
        """Return a services.api_request stub for the OpenXBL endpoints."""
        if minutes is None:
            minutes = {"1777860928": 1250, "1810924247": 500}

        def side_effect(_provider, method, url, **_kwargs):
            if method == "POST":
                return stats_response(minutes)
            if url.endswith("/account"):
                return ACCOUNT_RESPONSE
            if "/achievements/player/" in url:
                return envelope(self.titles_response)
            return envelope({"titles": []})

        return side_effect

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

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_import_xbox_games(self, mock_api_request, mock_search):
        """Played titles import with minutes and a status derived from last played."""
        mock_api_request.side_effect = self.api_stub()
        mock_search.side_effect = self.search_stub()

        imported_counts, _ = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 3)

        games = Game.objects.filter(user=self.user)
        halo = games.get(item__title="Halo Infinite")
        self.assertEqual(halo.progress, 1250)
        self.assertEqual(halo.status, Status.IN_PROGRESS.value)

        forza = games.get(item__title="Forza Horizon 5")
        self.assertEqual(forza.progress, 500)
        self.assertEqual(forza.status, Status.PAUSED.value)

        # No MinutesPlayed and no lastTimePlayed.
        never = games.get(item__title="Never Launched")
        self.assertEqual(never.progress, 0)
        self.assertEqual(never.status, Status.PLANNING.value)

        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)
        self.assertFalse(self.account.connection_broken)

    def test_overwrite_keeps_progress_when_minutes_unreported(self):
        """A title with no MinutesPlayed must not have tracked hours zeroed."""
        item = self.existing_game(progress=999)
        self.titles_response = {"titles": [title("1777860928", "Halo Infinite")]}

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=self.search_stub(media_id="1"),
            ),
        ):
            xbox.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 999)

    def test_overwrite_updates_progress_when_minutes_reported(self):
        """A reported MinutesPlayed value replaces existing progress."""
        item = self.existing_game(progress=10)
        self.titles_response = {"titles": [title("1777860928", "Halo Infinite")]}

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={"1777860928": 1250}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=self.search_stub(media_id="1"),
            ),
        ):
            xbox.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.progress, 1250)

    def test_overwrite_preserves_completed_status(self):
        """A manually completed game keeps its status on re-sync."""
        item = self.existing_game(progress=10, status=Status.COMPLETED.value)
        recent = (timezone.now() - timedelta(days=1)).isoformat()
        self.titles_response = {
            "titles": [title("1777860928", "Halo Infinite", recent)],
        }

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={"1777860928": 1250}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=self.search_stub(media_id="1"),
            ),
        ):
            xbox.importer(None, self.user, "overwrite")

        game = Game.objects.get(user=self.user, item=item)
        self.assertEqual(game.status, Status.COMPLETED.value)
        self.assertEqual(game.progress, 1250)

    def tombstone(self, media_id):
        """Record that the user deleted this IGDB game locally."""
        return DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            media_id=media_id,
        )

    def test_deleted_game_is_not_recreated(self):
        """Xbox reports a title forever, but a locally deleted game stays gone."""
        self.tombstone("1")
        self.titles_response = {
            "titles": [title("1777860928", "Halo Infinite")],
        }

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={"1777860928": 1250}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=self.search_stub(media_id="1"),
            ),
        ):
            imported_counts, _ = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts.get(MediaTypes.GAME.value, 0), 0)
        self.assertFalse(Game.objects.filter(user=self.user).exists())

        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)
        self.assertFalse(self.account.connection_broken)

    def test_deleted_game_does_not_block_the_rest_of_the_library(self):
        """Only the tombstoned title is skipped; the others still import."""
        self.tombstone("1")
        self.titles_response = {
            "titles": [
                title("1777860928", "Halo Infinite"),
                title("1810924247", "Forza Horizon 5"),
            ],
        }

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

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=search_by_name,
            ),
        ):
            imported_counts, _ = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(
            list(Game.objects.filter(user=self.user).values_list("item__media_id", flat=True)),
            ["2"],
        )

    def test_deleted_game_is_skipped_in_overwrite_mode(self):
        """Overwrite re-syncs the library, and must not resurrect it either."""
        self.tombstone("1")
        self.titles_response = {
            "titles": [title("1777860928", "Halo Infinite")],
        }

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                side_effect=self.api_stub(minutes={"1777860928": 1250}),
            ),
            patch(
                "integrations.imports.xbox.services.search",
                side_effect=self.search_stub(media_id="1"),
            ),
        ):
            imported_counts, _ = xbox.importer(None, self.user, "overwrite")

        self.assertEqual(imported_counts.get(MediaTypes.GAME.value, 0), 0)
        self.assertFalse(Game.objects.filter(user=self.user).exists())

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_falls_back_to_name_search(self, mock_api_request, mock_search):
        """Titles with no matching store product ID are matched by name."""
        self.titles_response = {
            "titles": [title("1777860928", "Halo Infinite", pfn=None)],
        }
        mock_api_request.side_effect = self.api_stub(minutes={"1777860928": 60})
        mock_search.return_value = {
            "results": [
                {
                    "media_id": "42",
                    "title": "Halo Infinite",
                    "image": "http://example.com/halo.jpg",
                },
            ],
        }

        imported_counts, _ = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertTrue(
            Game.objects.filter(user=self.user, item__media_id="42").exists(),
        )

    @patch("integrations.imports.xbox.external_game", return_value=None)
    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_unmatched_title_warns_instead_of_failing(
        self,
        mock_api_request,
        mock_search,
        mock_external_game,
    ):
        """A title IGDB cannot match is reported as a warning."""
        self.titles_response = {"titles": [title("999", "Unknown Game")]}
        mock_api_request.side_effect = self.api_stub(minutes={})
        mock_search.return_value = {"results": []}

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts.get(MediaTypes.GAME.value, 0), 0)
        self.assertIn("Unknown Game (999)", warnings)
        self.assertIn(f"Couldn't find a match in {Sources.IGDB.label}", warnings)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 0)

    def test_marketplace_guid_embeds_the_title_id(self):
        """The 360 marketplace product GUID is the title ID in hex."""
        self.assertEqual(
            xbox._marketplace_guid("1297287142"),  # Halo 3, 0x4D5307E6
            "66acd000-77fe-1000-9115-d8024d5307e6",
        )
        for bogus in (None, "", "not-a-number", str(0x1_0000_0000), "0"):
            self.assertIsNone(xbox._marketplace_guid(bogus), bogus)

    @patch("integrations.imports.xbox.services.get_media_metadata")
    @patch("integrations.imports.xbox.external_game")
    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_legacy_title_matches_by_marketplace_guid_before_name(
        self,
        mock_api_request,
        mock_search,
        mock_external_game,
        mock_metadata,
    ):
        """A 360-era title resolves via its marketplace GUID, not its name."""
        self.titles_response = {
            "titles": [
                title("1414793208", "MCLA: Complete", devices=["Xbox360"]),
            ],
        }
        mock_api_request.side_effect = self.api_stub(minutes={})
        mock_external_game.return_value = 4256
        mock_metadata.return_value = {
            "title": "Midnight Club: Los Angeles",
            "image": "http://example.com/mcla.jpg",
        }

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(warnings, "")
        mock_search.assert_not_called()
        mock_external_game.assert_called_once_with(
            "66acd000-77fe-1000-9115-d802545407f8",
            xbox.ExternalGameSource.XBOX_MARKETPLACE,
        )
        game = Game.objects.get(user=self.user, item__media_id="4256")
        self.assertEqual(game.item.title, "Midnight Club: Los Angeles")

    @patch("integrations.imports.xbox.services.get_media_metadata")
    @patch("integrations.imports.xbox.external_game")
    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_unmatched_modern_title_falls_back_to_marketplace_guid(
        self,
        mock_api_request,
        mock_search,
        mock_external_game,
        mock_metadata,
    ):
        """A title that fails name search still gets one GUID lookup."""
        self.titles_response = {"titles": [title("999", "Obscure Game")]}
        mock_api_request.side_effect = self.api_stub(minutes={})
        mock_search.return_value = {"results": []}
        mock_external_game.return_value = 88
        mock_metadata.return_value = {
            "title": "Obscure Game",
            "image": "http://example.com/o.jpg",
        }

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(warnings, "")
        self.assertTrue(mock_search.called)
        Game.objects.get(user=self.user, item__media_id="88")

    @patch("integrations.xbox_api.services.api_request")
    def test_invalid_api_key_marks_account_broken(self, mock_api_request):
        """A 401 from OpenXBL surfaces a reconnect message and flags the account."""
        response = Response()
        response.status_code = 401
        mock_api_request.side_effect = HTTPError(response=response)

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("Invalid or expired OpenXBL API key", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.xbox_api.services.api_request")
    def test_unreachable_provider_marks_account_broken(self, mock_api_request):
        """A wrapped transport failure flags the account instead of escaping."""
        mock_api_request.side_effect = services.ProviderAPIError(
            "OpenXBL",
            RequestsConnectionError("HTTPSConnectionPool(host='xbl.io'): timed out"),
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("Could not reach OpenXBL", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("Could not reach OpenXBL", self.account.last_error_message)
        self.assertNotIn("HTTPSConnectionPool", self.account.last_error_message)

    @patch("integrations.xbox_api.services.api_request")
    def test_transport_failure_marks_account_broken(self, mock_api_request):
        """A bare requests failure is translated rather than left to escape."""
        mock_api_request.side_effect = RequestsConnectionError(
            "Max retries exceeded with url: /api/v2/account?api_key=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError):
            xbox.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertNotIn("super-secret", self.account.last_error_message)

    @patch("integrations.xbox_api.services.api_request")
    def test_http_error_without_a_response_is_still_translated(self, mock_api_request):
        """An HTTPError carrying no response must not fail while being handled."""
        mock_api_request.side_effect = HTTPError("request never completed")

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("OpenXBL request failed", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.xbox_api.services.api_request")
    def test_unexpected_fetch_failure_marks_account_broken(self, mock_api_request):
        """An error xbox_api doesn't model still lands as durable account state."""
        mock_api_request.side_effect = ValueError(
            "bad payload from https://xbl.io/api/v2/account?token=super-secret",
        )

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("ValueError", str(context.exception))
        self.assertNotIn("super-secret", str(context.exception))
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("ValueError", self.account.last_error_message)
        self.assertNotIn("super-secret", self.account.last_error_message)

    def test_stored_error_messages_are_scrubbed_and_bounded(self):
        """Whatever reaches the account row is redacted and length-capped."""
        self.assertEqual(
            xbox._safe_message("failed with api_key=super-secret sent"),
            "failed with api_key=[REDACTED] sent",
        )

        importer = xbox.XboxImporter(self.user, "new")
        importer._mark_broken("x" * 5000)

        self.account.refresh_from_db()
        self.assertLessEqual(
            len(self.account.last_error_message),
            xbox.MAX_ERROR_MESSAGE_LENGTH,
        )
        self.assertTrue(self.account.last_error_message.endswith("…"))

    def test_import_without_connected_account(self):
        """Importing without a connected account raises a clear error."""
        XboxAccount.objects.filter(user=self.user).delete()
        self.user.refresh_from_db()

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("Connect Xbox before importing", str(context.exception))

    @patch("integrations.xbox_api.services.api_request")
    def test_blank_xuid_falls_back_to_the_account_lookup(self, mock_api_request):
        """A stored XUID that is blank is refetched rather than used as-is."""
        self.account.xuid = "   "
        self.account.save(update_fields=["xuid"])
        mock_api_request.side_effect = self.api_stub()

        with patch(
            "integrations.imports.xbox.services.search",
            side_effect=self.search_stub(),
        ):
            xbox.importer(None, self.user, "new")

        requested = [call.args[2] for call in mock_api_request.call_args_list]
        self.assertIn(
            "https://xbl.io/api/v2/achievements/player/2535473210914202",
            requested,
        )

    @patch("integrations.xbox_api.services.api_request")
    def test_missing_xuid_aborts_before_requesting_titles(self, mock_api_request):
        """Without an XUID from either source the import stops and flags the account."""
        self.account.xuid = ""
        self.account.save(update_fields=["xuid"])
        mock_api_request.return_value = envelope({"profileUsers": [{"settings": []}]})

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("no XUID", str(context.exception))
        # The title endpoints are keyed by XUID; none should have been called.
        requested = [call.args[2] for call in mock_api_request.call_args_list]
        self.assertEqual(requested, ["https://xbl.io/api/v2/account"])
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.xbox_api.services.api_request")
    def test_unsupported_mode_is_rejected(self, mock_api_request):
        """Modes Xbox cannot act on fail loudly instead of behaving like "new"."""
        for mode in ("watchlist", "update_collection", "", None):
            with self.assertRaises(helpers.MediaImportError) as context:
                xbox.importer(None, self.user, mode)

            self.assertIn("Unsupported Xbox import mode", str(context.exception))

        self.assertFalse(mock_api_request.called)
        # A bad mode is a caller error, not a broken connection.
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)

    def test_determine_game_status_logic(self):
        """Status is derived from minutes played and last played date."""
        importer_instance = xbox.XboxImporter(self.user, "new")

        self.assertEqual(
            importer_instance._determine_game_status(None, None),
            Status.PLANNING.value,
        )
        self.assertEqual(
            importer_instance._determine_game_status(
                100,
                timezone.now() - timedelta(days=2),
            ),
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(
            importer_instance._determine_game_status(
                100,
                timezone.now() - timedelta(days=90),
            ),
            Status.PAUSED.value,
        )
        # Playtime but no last-played date still counts as started.
        self.assertEqual(
            importer_instance._determine_game_status(100, None),
            Status.PAUSED.value,
        )

    def test_get_account_unwraps_envelope(self):
        """The live /account payload sits inside a content envelope."""
        from integrations import xbox_api

        with patch(
            "integrations.xbox_api.services.api_request",
            return_value=ACCOUNT_RESPONSE,
        ):
            xuid, gamertag = xbox_api.get_account("some-key")

        self.assertEqual(xuid, "2535473210914202")
        self.assertEqual(gamertag, "TestGamer")

    def test_get_account_reports_unexpected_shape(self):
        """An unrecognised /account payload names the shape it got."""
        from integrations import xbox_api

        with (
            patch(
                "integrations.xbox_api.services.api_request",
                return_value=envelope({"error": "nope"}),
            ),
            self.assertRaises(helpers.MediaImportError) as context,
        ):
            xbox_api.get_account("some-key")

        self.assertIn("object with keys ['error']", str(context.exception))

    def test_simplify_title_strips_store_decorations(self):
        """Xbox store suffixes are stripped so IGDB can match the base title."""
        cases = {
            "Isonzo (Windows)": "Isonzo",
            "Insurgency: Sandstorm (Windows)": "Insurgency: Sandstorm",
            "The Quarry for Xbox Series X|S": "The Quarry",
            "Control Ultimate Edition - Xbox Series X|S": "Control Ultimate Edition",
            "Cities: Skylines - Windows 10 Edition": "Cities: Skylines",
            "Grand Theft Auto V (Xbox One)": "Grand Theft Auto V",
            "Call of Duty®": "Call of Duty",
            "Mortal Kombat® 1": "Mortal Kombat 1",
            "Battlefield™ 2042 Xbox Series X|S": "Battlefield 2042",
            "FIFA 21 Xbox Series X|S": "FIFA 21",
            "Layers of Fear (2016)": "Layers of Fear",
            "Army of Two™ (EU)": "Army of Two",
            "DOOM Eternal (BATTLEMODE - PC)": "DOOM Eternal",
            "[PROTOTYPE]™": "PROTOTYPE",
            "Geometry Wars Evolved²": "Geometry Wars Evolved 2",
            "Tom Clancy\u2019s The Division": "Tom Clancy's The Division",
        }
        for raw, expected in cases.items():
            self.assertEqual(xbox._simplify_title(raw), expected, raw)

    def test_simplify_title_leaves_clean_names_alone(self):
        """Titles without store decorations must not be altered."""
        for raw in (
            "Cyberpunk 2077",
            "Alan Wake 2",
            "The Last Case of Benedict Fox: Definitive Edition",
            "Halo Infinite",
        ):
            self.assertEqual(xbox._simplify_title(raw), raw)

    def test_strip_decorations_removes_editions_and_brands(self):
        """Edition suffixes and publisher prefixes fall away as a fallback."""
        cases = {
            "The Last Case of Benedict Fox: Definitive Edition": (
                "The Last Case of Benedict Fox"
            ),
            "Remnant II - Standard Edition": "Remnant II",
            "Control Standard Edition": "Control",
            "Halo 3: ODST Campaign Edition": "Halo 3: ODST",
            "Gone Home Base Game": "Gone Home",
            "MCLA: Complete": "MCLA",
            "EA SPORTS FIFA 20": "FIFA 20",
            "Disney Epic Mickey 2: The Power of Two": (
                "Epic Mickey 2: The Power of Two"
            ),
        }
        for raw, expected in cases.items():
            self.assertEqual(xbox._strip_decorations(raw), expected, raw)

    def test_strip_decorations_leaves_plain_titles_alone(self):
        """Titles without edition or brand decorations must not be altered."""
        for raw in ("Halo Infinite", "Alan Wake 2", "Gone Home"):
            self.assertEqual(xbox._strip_decorations(raw), raw)

    def test_search_names_orders_candidates_most_faithful_first(self):
        """The raw store name is tried before any simplification."""
        candidates = list(
            xbox._search_names("Remnant II® - Standard Edition"),
        )
        self.assertEqual(
            candidates,
            [
                "Remnant II® - Standard Edition",
                "Remnant II - Standard Edition",
                "Remnant II",
            ],
        )

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_retries_search_with_simplified_title(self, mock_api_request, mock_search):
        """A title that only matches once simplified is still imported."""
        self.titles_response = {"titles": [title("1", "Isonzo (Windows)")]}
        mock_api_request.side_effect = self.api_stub(minutes={"1": 30})

        def search(_media_type, query, _page, source=None):
            if query != "Isonzo":
                return {"results": []}
            return {
                "results": [
                    {
                        "media_id": "77",
                        "title": "Isonzo",
                        "image": "http://example.com/i.jpg",
                    },
                ],
            }

        mock_search.side_effect = search

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(mock_search.call_count, 2)
        self.assertEqual(warnings, "")
        game = Game.objects.get(user=self.user, item__media_id="77")
        self.assertEqual(game.progress, 30)

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_one_failing_title_does_not_lose_the_rest(
        self,
        mock_api_request,
        mock_search,
    ):
        """A provider error on one title must not discard the whole import."""
        mock_api_request.side_effect = self.api_stub()
        good = self.search_stub()

        def search(media_type, query, page, source=None):
            if query == "Forza Horizon 5":
                raise services.ProviderAPIError("IGDB", "boom")
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 2)
        self.assertIn("Forza Horizon 5", warnings)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 2)

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_total_lookup_failure_reports_clearly(
        self,
        mock_api_request,
        mock_search,
    ):
        """Every title failing means the provider is down, not an empty library."""
        mock_api_request.side_effect = self.api_stub()
        mock_search.side_effect = services.ProviderAPIError("IGDB", "unauthorized")

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        self.assertIn("Could not reach", str(context.exception))
        self.assertEqual(Game.objects.filter(user=self.user).count(), 0)
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_total_non_provider_failure_does_not_blame_igdb(
        self,
        mock_api_request,
        mock_search,
    ):
        """Every title failing on our own bug must not read as IGDB being down."""
        mock_api_request.side_effect = self.api_stub()
        mock_search.side_effect = TypeError("unhashable type: 'dict'")

        with self.assertRaises(helpers.MediaImportError) as context:
            xbox.importer(None, self.user, "new")

        message = str(context.exception)
        self.assertNotIn("Could not reach", message)
        # The exception type is named; its message is not, since an unexpected
        # exception can carry the request URL or the credentials sent with it.
        self.assertIn("TypeError", message)
        self.assertNotIn("unhashable type", message)
        self.assertEqual(Game.objects.filter(user=self.user).count(), 0)

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_non_provider_exception_is_contained(self, mock_api_request, mock_search):
        """An unexpected error (e.g. bad IGDB credentials) is contained per title."""
        mock_api_request.side_effect = self.api_stub()
        good = self.search_stub()
        calls = {"n": 0}

        def search(media_type, query, page, source=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # What igdb.get_access_token raises when credentials are rejected.
                msg = "cannot access local variable 'response'"
                raise UnboundLocalError(msg)
            return good(media_type, query, page, source=source)

        mock_search.side_effect = search

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 2)
        self.assertIn("UnboundLocalError", warnings)
        self.assertNotIn("cannot access local variable", warnings)

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_celery_task_runs_the_importer(self, mock_api_request, mock_search):
        """The registered task wires through import_media to the importer."""
        from integrations import tasks

        mock_api_request.side_effect = self.api_stub()
        mock_search.side_effect = self.search_stub()

        result = tasks.import_xbox(user_id=self.user.id, mode="new")

        self.assertIn("3", str(result))
        self.assertEqual(Game.objects.filter(user=self.user).count(), 3)

    @patch("integrations.imports.xbox.external_game", return_value=None)
    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_apps_are_never_imported_as_games(
        self,
        mock_api_request,
        mock_search,
        _mock_external_game,
    ):
        """Media apps are dropped before IGDB sees them, not matched by name."""
        self.titles_response = {
            "titles": [
                title("1777860928", "Halo Infinite"),
                title("1016567257", "Netflix", title_type="App"),
                title("750323071", "Twitch", title_type="App"),
            ],
        }
        mock_api_request.side_effect = self.api_stub(minutes={"1777860928": 60})
        mock_search.side_effect = self.search_stub(media_id="1")

        imported_counts, warnings = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)
        self.assertEqual(warnings, "")
        self.assertEqual(
            [call.args[1] for call in mock_search.call_args_list],
            ["Halo Infinite"],
        )
        titles = Game.objects.filter(user=self.user).values_list(
            "item__title",
            flat=True,
        )
        self.assertEqual(list(titles), ["Halo Infinite"])

    @patch("integrations.imports.xbox.services.search")
    @patch("integrations.xbox_api.services.api_request")
    def test_title_without_a_type_is_still_imported(
        self,
        mock_api_request,
        mock_search,
    ):
        """An untyped payload is kept: unknown shape must not empty a library."""
        self.titles_response = {
            "titles": [title("1777860928", "Halo Infinite", title_type=None)],
        }
        mock_api_request.side_effect = self.api_stub(minutes={"1777860928": 60})
        mock_search.side_effect = self.search_stub(media_id="1")

        imported_counts, _ = xbox.importer(None, self.user, "new")

        self.assertEqual(imported_counts[MediaTypes.GAME.value], 1)

    def test_is_game_classifies_title_types(self):
        """Only game titles pass; an absent or blank type is treated as unknown."""
        from integrations import xbox_api

        for title_type in ("Game", "game", " GAME ", None, ""):
            self.assertTrue(xbox_api.is_game({"type": title_type}), title_type)
        self.assertTrue(xbox_api.is_game({}))

        for title_type in ("App", "app", "Application"):
            self.assertFalse(xbox_api.is_game({"type": title_type}), title_type)

    def test_game_from_either_endpoint_survives_the_merge(self):
        """A title typed Game by one endpoint is kept, and keeps both payloads."""
        from integrations import xbox_api

        def side_effect(_provider, _method, url, **_kwargs):
            if "/achievements/player/" in url:
                return envelope(
                    {"titles": [title("1777860928", "Halo Infinite")]},
                )
            return envelope(
                {
                    "titles": [
                        # Same title, typed App here: the merge must not drop it.
                        title(
                            "1777860928",
                            "Halo Infinite",
                            "2024-01-01T00:00:00Z",
                            title_type="App",
                        ),
                        title("1016567257", "Netflix", title_type="App"),
                    ],
                },
            )

        with patch(
            "integrations.xbox_api.services.api_request",
            side_effect=side_effect,
        ):
            titles = xbox_api.get_played_titles("some-key", "2535473210914202")

        self.assertEqual(list(titles), ["1777860928"])
        # The conflicting payload still merged in, so lastTimePlayed survives.
        self.assertEqual(
            titles["1777860928"]["titleHistory"]["lastTimePlayed"],
            "2024-01-01T00:00:00Z",
        )

    def test_parse_stats_ignores_unreported_titles(self):
        """Only titles present in the stats response get a minutes value."""
        from integrations import xbox_api

        parsed = xbox_api._parse_stats(
            envelope(
                {
                    "statlistscollection": [
                        {
                            "stats": [
                                {
                                    "titleid": "1",
                                    "name": "MinutesPlayed",
                                    "value": "12",
                                },
                                {"titleid": "2", "name": "Gamerscore", "value": "500"},
                                {
                                    "titleid": "3",
                                    "name": "MinutesPlayed",
                                    "value": None,
                                },
                            ],
                        },
                    ],
                },
            ),
        )

        self.assertEqual(parsed, {"1": 12})


class XboxViewTests(TestCase):
    """Test the Xbox connect/disconnect/import views."""

    def setUp(self):
        """Create and log in a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("integrations.views.tasks.import_xbox.delay")
    @patch(
        "integrations.views.xbox_api.get_account",
        return_value=("2535473210914202", "TestGamer"),
    )
    def test_connect_stores_key_and_imports_once(
        self,
        mock_get_account,
        mock_delay,
    ):
        """A one time connect validates the key, stores it and imports now."""
        response = self.client.post(
            reverse("xbox_connect"),
            {"api_key": "openxbl-key", "frequency": "once", "mode": "new"},
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_get_account.assert_called_once_with("openxbl-key")
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

        account = XboxAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.api_key), "openxbl-key")
        self.assertEqual(account.xuid, "2535473210914202")
        self.assertEqual(account.gamertag, "TestGamer")
        self.assertTrue(account.is_connected)

        self.assertFalse(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).exists(),
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    @patch(
        "integrations.views.xbox_api.get_account",
        return_value=("2535473210914202", "TestGamer"),
    )
    def test_connect_with_frequency_only_schedules(
        self,
        _mock_get_account,
        mock_delay,
    ):
        """A recurring connect schedules the import instead of running it."""
        self.client.post(
            reverse("xbox_connect"),
            {
                "api_key": "openxbl-key",
                "frequency": "daily",
                "time": "05:30",
                "mode": "new",
            },
        )

        mock_delay.assert_not_called()
        task = PeriodicTask.objects.get(task=XBOX_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, "5")
        self.assertEqual(task.crontab.minute, "30")
        self.assertEqual(task.crontab.day_of_week, "*")

    @patch("integrations.views.xbox_api.get_account")
    def test_connect_requires_api_key(self, mock_get_account):
        """Submitting an empty key is rejected before calling OpenXBL."""
        response = self.client.post(reverse("xbox_connect"), {})

        self.assertRedirects(response, reverse("import_data"))
        mock_get_account.assert_not_called()
        self.assertFalse(XboxAccount.objects.filter(user=self.user).exists())

    @patch(
        "integrations.views.xbox_api.get_account",
        side_effect=helpers.MediaImportError("Invalid or expired OpenXBL API key."),
    )
    def test_connect_with_invalid_key_is_not_stored(self, _mock_get_account):
        """A key OpenXBL rejects is never persisted."""
        response = self.client.post(
            reverse("xbox_connect"),
            {"api_key": "bad-key"},
            follow=True,
        )

        self.assertContains(response, "Could not connect to Xbox")
        self.assertFalse(XboxAccount.objects.filter(user=self.user).exists())

    @patch(
        "integrations.views.xbox_api.get_account",
        side_effect=ValueError("bad payload for api_key=super-secret"),
    )
    def test_connect_failure_does_not_echo_the_raw_error(self, _mock_get_account):
        """The key travels with this request, so nothing raw goes back to the page."""
        response = self.client.post(
            reverse("xbox_connect"),
            {"api_key": "openxbl-key"},
            follow=True,
        )

        self.assertContains(response, "Failed to connect to Xbox")
        self.assertContains(response, "ValueError")
        self.assertNotContains(response, "super-secret")
        self.assertFalse(XboxAccount.objects.filter(user=self.user).exists())

    @patch("integrations.views.tasks.import_xbox.delay")
    @patch(
        "integrations.views.xbox_api.get_account",
        return_value=("2535473210914202", "TestGamer"),
    )
    def test_disconnect_removes_account_and_schedule(self, _mock_account, _mock_delay):
        """Disconnecting deletes both the account row and its periodic task."""
        self.client.post(
            reverse("xbox_connect"),
            {"api_key": "openxbl-key", "frequency": "daily", "time": "04:00"},
        )
        self.assertTrue(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).exists(),
        )

        response = self.client.post(reverse("xbox_disconnect"))

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(XboxAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task=XBOX_RECURRING_TASK_NAME,
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists(),
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_sync_now_requires_connected_account(self, mock_delay):
        """Sync Now without a connected account queues nothing."""
        response = self.client.post(reverse("import_xbox"), follow=True)

        self.assertContains(response, "Connect Xbox before importing.")
        mock_delay.assert_not_called()

    def _connect_account(self):
        """Attach a connected Xbox account to the logged in user."""
        return XboxAccount.objects.create(
            user=self.user,
            api_key=helpers.encrypt("openxbl-key"),
            xuid="2535473210914202",
            gamertag="TestGamer",
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_one_time_import_runs_now_without_scheduling(self, mock_delay):
        """A one time import runs straight away and schedules nothing."""
        self._connect_account()

        self.client.post(
            reverse("import_xbox"),
            {"frequency": "once", "mode": "overwrite", "time": "04:00"},
        )

        mock_delay.assert_called_once_with(user_id=self.user.id, mode="overwrite")
        self.assertFalse(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).exists(),
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_scheduled_import_does_not_run_immediately(self, mock_delay):
        """A scheduled import only runs on schedule, never on creation."""
        self._connect_account()

        self.client.post(
            reverse("import_xbox"),
            {"frequency": "2days", "mode": "new", "time": "23:15"},
        )

        mock_delay.assert_not_called()
        task = PeriodicTask.objects.get(task=XBOX_RECURRING_TASK_NAME)
        self.assertEqual(task.crontab.hour, "23")
        self.assertEqual(task.crontab.minute, "15")
        self.assertEqual(task.crontab.day_of_week, "*/2")
        self.assertEqual(json.loads(task.kwargs)["mode"], "new")
        # A start_time in the past makes celery beat fire the task immediately.
        self.assertGreater(task.start_time, timezone.now())

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_new_schedule_keeps_existing_ones(self, _mock_delay):
        """Adding a schedule leaves earlier Xbox schedules untouched."""
        self._connect_account()

        self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "new", "time": "04:00"},
        )
        self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "overwrite", "time": "20:00"},
        )

        tasks_by_time = {
            task.crontab.hour: json.loads(task.kwargs)["mode"]
            for task in PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME)
        }
        self.assertEqual(tasks_by_time, {"4": "new", "20": "overwrite"})

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_duplicate_schedule_is_rejected(self, _mock_delay):
        """The same time and frequency cannot be scheduled twice."""
        self._connect_account()

        payload = {"frequency": "daily", "mode": "new", "time": "04:00"}
        self.client.post(reverse("import_xbox"), payload)
        response = self.client.post(reverse("import_xbox"), payload, follow=True)

        self.assertContains(response, "The same import task is already scheduled.")
        self.assertEqual(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).count(),
            1,
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_another_users_schedule_does_not_block_this_one(self, _mock_delay):
        """A task named for a recycled username belongs to whoever holds it."""
        self._connect_account()
        payload = {"frequency": "daily", "mode": "new", "time": "04:00"}
        self.client.post(reverse("import_xbox"), payload)

        # The first user renames, and a new account takes the freed username.
        self.user.username = "renamed"
        self.user.save(update_fields=["username"])
        other_credentials = {"username": "test", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        XboxAccount.objects.create(
            user=other_user,
            api_key=helpers.encrypt("openxbl-key"),
            xuid="2535473210914203",
            gamertag="OtherGamer",
        )
        self.client.login(**other_credentials)

        response = self.client.post(reverse("import_xbox"), payload, follow=True)

        self.assertContains(response, "Xbox import task scheduled.")
        tasks_by_user = {
            json.loads(task.kwargs)["user_id"]: task.name
            for task in PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME)
        }
        self.assertEqual(set(tasks_by_user), {self.user.id, other_user.id})
        # The name the first user left behind is repaired, not handed over.
        self.assertIn("for renamed at", tasks_by_user[self.user.id])
        self.assertIn("for test at", tasks_by_user[other_user.id])

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_schedule_left_by_a_deleted_user_is_cleaned_up(self, _mock_delay):
        """A name held by a task whose user is gone is reclaimed, not a 500."""
        departed_user = get_user_model().objects.create_user(
            username="departed",
            password="12345",
        )
        PeriodicTask.objects.create(
            name="Import from Xbox for test at 04:00:00 daily",
            task=XBOX_RECURRING_TASK_NAME,
            crontab=CrontabSchedule.objects.create(
                minute="0",
                hour="4",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
            ),
            kwargs=json.dumps({"user_id": departed_user.id, "mode": "new"}),
            enabled=True,
        )
        departed_user.delete()

        self._connect_account()
        response = self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "new", "time": "04:00"},
            follow=True,
        )

        self.assertContains(response, "Xbox import task scheduled.")
        task = PeriodicTask.objects.get(task=XBOX_RECURRING_TASK_NAME)
        self.assertEqual(json.loads(task.kwargs)["user_id"], self.user.id)

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_duplicate_schedule_survives_a_username_change(self, _mock_delay):
        """Renaming does not hand the same user a second copy of a schedule."""
        self._connect_account()
        payload = {"frequency": "daily", "mode": "new", "time": "04:00"}
        self.client.post(reverse("import_xbox"), payload)

        self.user.username = "renamed"
        self.user.save(update_fields=["username"])
        response = self.client.post(reverse("import_xbox"), payload, follow=True)

        self.assertContains(response, "The same import task is already scheduled.")
        self.assertEqual(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).count(),
            1,
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_disabled_schedule_is_re_enabled(self, _mock_delay):
        """Rescheduling revives a disabled task rather than rejecting it."""
        self._connect_account()
        self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "new", "time": "04:00"},
        )
        task = PeriodicTask.objects.get(task=XBOX_RECURRING_TASK_NAME)
        task.enabled = False
        task.start_time = timezone.now() - timedelta(days=1)
        task.save(update_fields=["enabled", "start_time"])

        response = self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "overwrite", "time": "04:00"},
            follow=True,
        )

        self.assertContains(response, "Xbox import task re-enabled.")
        self.assertEqual(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).count(),
            1,
        )
        task.refresh_from_db()
        self.assertTrue(task.enabled)
        self.assertEqual(json.loads(task.kwargs)["mode"], "overwrite")
        # A start_time in the past makes celery beat fire the task immediately.
        self.assertGreater(task.start_time, timezone.now())

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_another_users_disabled_schedule_is_left_alone(self, _mock_delay):
        """Reviving a schedule never touches one belonging to someone else."""
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        self.client.force_login(other_user)
        XboxAccount.objects.create(
            user=other_user,
            api_key=helpers.encrypt("openxbl-key"),
            xuid="2535473210914203",
            gamertag="OtherGamer",
        )
        payload = {"frequency": "daily", "mode": "new", "time": "04:00"}
        self.client.post(reverse("import_xbox"), payload)
        other_task = PeriodicTask.objects.get(task=XBOX_RECURRING_TASK_NAME)
        other_task.enabled = False
        other_task.save(update_fields=["enabled"])

        self._connect_account()
        self.client.login(**self.credentials)
        response = self.client.post(reverse("import_xbox"), payload, follow=True)

        self.assertContains(response, "Xbox import task scheduled.")
        other_task.refresh_from_db()
        self.assertFalse(other_task.enabled)
        self.assertEqual(json.loads(other_task.kwargs)["user_id"], other_user.id)
        self.assertEqual(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).count(),
            2,
        )

    @patch("integrations.views.tasks.import_xbox.delay")
    def test_invalid_import_time_is_rejected(self, mock_delay):
        """A malformed time schedules nothing rather than falling back."""
        self._connect_account()

        response = self.client.post(
            reverse("import_xbox"),
            {"frequency": "daily", "mode": "new", "time": "not-a-time"},
            follow=True,
        )

        self.assertContains(response, "Invalid import time.")
        mock_delay.assert_not_called()
        self.assertFalse(
            PeriodicTask.objects.filter(task=XBOX_RECURRING_TASK_NAME).exists(),
        )
