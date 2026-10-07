import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from integrations import stremio_events, views

User = get_user_model()


class ManifestDeclaresEventResourcesTests(TestCase):
    def test_player_and_library_are_declared(self):
        self.assertIn("player", views.STREMIO_ADDON_MANIFEST["resources"])
        self.assertIn("library", views.STREMIO_ADDON_MANIFEST["resources"])

    def test_existing_resources_are_retained(self):
        for resource in ("catalog", "meta", "subtitles"):
            self.assertIn(resource, views.STREMIO_ADDON_MANIFEST["resources"])

    def test_version_was_bumped(self):
        """A client may hold the old manifest, so the version must change."""
        self.assertNotEqual(views.STREMIO_ADDON_MANIFEST["version"], "1.2.0")


class PlayerRouteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="routes", password="x")

    def test_player_route_accepts_an_episode_id(self):
        url = reverse(
            "stremio_addon_player",
            kwargs={
                "token": self.user.token,
                "media_type": "series",
                "media_id": "tt1%3A1%3A2",
                "extra": "action=start&currentTime=1000&duration=2000",
            },
        )

        with patch.object(views.stremio_tracker, "record_player_event") as handler:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        handler.assert_called_once_with(
            self.user,
            "series",
            "tt1:1:2",
            "action=start&currentTime=1000&duration=2000",
        )

    def test_player_route_rejects_an_invalid_token(self):
        url = reverse(
            "stremio_addon_player",
            kwargs={
                "token": "not-a-token",
                "media_type": "movie",
                "media_id": "tt1",
                "extra": "action=start&currentTime=1000",
            },
        )

        self.assertEqual(self.client.get(url).status_code, 401)

    def test_library_route_is_reachable(self):
        url = reverse(
            "stremio_addon_library",
            kwargs={
                "token": self.user.token,
                "media_type": "series",
                "media_id": "tt1",
                "extra": "action=watched&videoId=tt1%3A1%3A2",
            },
        )

        with patch.object(views.stremio_tracker, "record_library_event") as handler:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        handler.assert_called_once_with(
            self.user,
            "series",
            "tt1",
            "action=watched&videoId=tt1%3A1%3A2",
        )


class InvalidMediaIdTests(TestCase):
    """A media id that fails the addon pattern never reaches the tracker.

    The id is client-supplied and is bound into queries downstream, so the
    route rejects it up front rather than letting the handler resolve it.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="routes-invalid", password="x")

    def test_player_route_rejects_an_invalid_media_id(self):
        url = reverse(
            "stremio_addon_player",
            kwargs={
                "token": self.user.token,
                "media_type": "movie",
                "media_id": "not-an-id",
                "extra": "action=start&currentTime=1000",
            },
        )

        with patch.object(views.stremio_tracker, "record_player_event") as handler:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        handler.assert_not_called()

    def test_library_route_rejects_an_invalid_media_id(self):
        # Episode 0 does not exist, so `tt1:1:0` is genuinely malformed.
        url = reverse(
            "stremio_addon_library",
            kwargs={
                "token": self.user.token,
                "media_type": "series",
                "media_id": "tt1%3A1%3A0",
                "extra": "action=watched",
            },
        )

        with patch.object(views.stremio_tracker, "record_library_event") as handler:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        handler.assert_not_called()

    def test_routes_accept_season_zero_specials(self):
        """Season 0 is Stremio's specials bucket; the guard must not reject it.

        It did, which silently dropped every special before it reached the
        tracker.
        """
        for route, handler_name in (
            ("stremio_addon_library", "record_library_event"),
            ("stremio_addon_player", "record_player_event"),
        ):
            with self.subTest(route=route):
                extra = (
                    "action=watched"
                    if route == "stremio_addon_library"
                    else "action=pause&currentTime=1000&duration=2000"
                )
                url = reverse(
                    route,
                    kwargs={
                        "token": self.user.token,
                        "media_type": "series",
                        "media_id": "tt1%3A0%3A2",
                        "extra": extra,
                    },
                )

                with patch.object(views.stremio_tracker, handler_name) as handler:
                    response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                handler.assert_called_once()


class SubtitlesVideoExtrasTests(TestCase):
    """The `subtitles` extra carries the selected release's identity.

    Stremio appends `videoHash`/`videoSize`/`filename` when the chosen stream
    has them. Floppy serves subtitles itself and never read the extra, so the
    route captures it and reports presence — nothing is stored yet.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="subtitles-extras", password="x")
        # The handler logs only on the first request per item per window, so a
        # leftover throttle key would silence the line under test.
        cache.clear()

    def _get(self, extra=None, media_id="tt1"):
        kwargs = {
            "token": self.user.token,
            "media_type": "movie",
            "media_id": media_id,
        }
        if extra is not None:
            kwargs["extra"] = extra
        url = reverse("stremio_addon_subtitles", kwargs=kwargs)
        with patch.object(views.stremio_queue, "reserve_pending", return_value="throttled"):
            return self.client.get(url)

    def test_the_route_still_resolves_without_an_extra(self):
        """A client that sends no extra must keep working.

        The segment is optional. Requiring it would 404 every such request and
        stop playback tracking for that client with no error anywhere.
        """
        response = self._get()

        self.assertEqual(response.status_code, 200)

    def test_the_log_reports_which_release_extras_arrived(self):
        with self.assertLogs("integrations.views", level="INFO") as captured:
            self._get(extra="videoHash=abc123&videoSize=12345&filename=Show.S01E01.mkv")

        line = next(
            entry for entry in captured.output if "stremio_subtitles_extras" in entry
        )
        self.assertIn("videoHash=True", line)
        self.assertIn("videoSize=True", line)
        self.assertIn("filename=True", line)

    def test_a_client_that_sends_nothing_is_reported_as_sending_nothing(self):
        """Absence is the answer too, so it must be visible rather than silent."""
        with self.assertLogs("integrations.views", level="INFO") as captured:
            self._get()

        line = next(
            entry for entry in captured.output if "stremio_subtitles_extras" in entry
        )
        self.assertIn("videoHash=False", line)
        self.assertIn("videoSize=False", line)
        self.assertIn("filename=False", line)


class ParseSubtitlesVideoExtrasTests(TestCase):
    def test_it_reports_present_and_absent_extras(self):
        parsed = stremio_events.parse_subtitles_video_extras(
            "videoHash=abc&filename=Show.S01E01.mkv",
        )

        self.assertEqual(
            parsed,
            {"videoHash": True, "videoSize": False, "filename": True},
        )

    def test_an_empty_value_counts_as_absent(self):
        """Stremio omits the key rather than sending an empty one, but a blank
        value must not be read as a usable hash or filename.
        """
        parsed = stremio_events.parse_subtitles_video_extras("videoHash=&filename=")

        self.assertEqual(
            parsed,
            {"videoHash": False, "videoSize": False, "filename": False},
        )

    def test_no_extra_reports_nothing_present(self):
        self.assertEqual(
            stremio_events.parse_subtitles_video_extras(None),
            {"videoHash": False, "videoSize": False, "filename": False},
        )


class PlayerResourceGateTests(TestCase):
    """The player/library resources must be withdrawable without a code change."""

    def setUp(self):
        self.user = User.objects.create_user(username="gate", password="x")

    def test_the_gate_defaults_enabled_and_withdraws_on_a_falsy_value(self):
        url = reverse("stremio_addon_manifest", kwargs={"token": self.user.token})

        self.assertIn("player", self.client.get(url).json()["resources"])

        with patch.dict(os.environ, {"STREMIO_ENABLE_PLAYER_RESOURCE": "0"}):
            resources = self.client.get(url).json()["resources"]

        self.assertNotIn("player", resources)
        self.assertNotIn("library", resources)
        self.assertIn("subtitles", resources)
