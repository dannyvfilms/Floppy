"""Radarr/Sonarr/Seerr details in the track modal's Collection tab (#1323)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from integrations import arr_library, seerr_api
from integrations.imports import helpers
from integrations.models import RadarrInstance, SonarrInstance

RADARR_GET = "integrations.imports.radarr.requests.get"
RADARR_SEND = "integrations.imports.radarr.requests.request"
SONARR_GET = "integrations.imports.sonarr.requests.get"
SONARR_SEND = "integrations.imports.sonarr.requests.request"
SEERR_SEND = "integrations.seerr_api.requests.request"


def _response(payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.content = b"{}"
    response.json.return_value = payload
    return response


def _router(routes):
    """Return a fake `requests.get` that answers by URL path and records calls."""
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        for path, payload in routes.items():
            if url.endswith(path):
                return _response(payload)
        return _response([], 404)

    fake.calls = calls
    return fake


def _event(event_type, date, **extra):
    return {"eventType": event_type, "date": date, **extra}


MOVIE_ROW = {
    "id": 11,
    "hasFile": True,
    "monitored": True,
    "movieFile": {
        "path": "/data/movies/Dune Part Two (2024)/Dune.mkv",
        "size": 15_000_000_000,
        "dateAdded": "2026-09-30T22:40:00Z",
        "quality": {"quality": {"name": "Bluray-2160p"}},
    },
}


class RadarrPanelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="arr")
        self.instance = RadarrInstance.objects.create(
            user=self.user,
            name="4K",
            base_url="https://radarr.local:7878",
            api_key=helpers.encrypt("key"),
        )

    def _panels(self, media_id="693134"):
        return arr_library.library_panels(self.user, "tmdb", "movie", media_id)

    def test_movie_with_file_shows_path_size_queue_and_history(self):
        routes = {
            "/api/v3/movie": [MOVIE_ROW],
            "/api/v3/queue/details": [
                {
                    "title": "Dune.Part.Two.2160p",
                    "size": 100,
                    "sizeleft": 25,
                    "trackedDownloadState": "downloading",
                    "downloadClient": "SABnzbd",
                }
            ],
            "/api/v3/history/movie": [
                _event("grabbed", "2026-09-30T22:12:00Z", data={"indexer": "NZB"}),
                _event("downloadFolderImported", "2026-09-30T22:40:00Z"),
                _event("movieFileRenamed", "2026-09-30T22:41:00Z"),
                _event(
                    "downloadFailed",
                    "2026-09-28T19:30:00Z",
                    data={"message": "No space left"},
                ),
            ],
        }
        fake = _router(routes)
        with patch(RADARR_GET, fake):
            (panel,) = self._panels()

        self.assertEqual(fake.calls[0][1]["params"], {"tmdbId": "693134"})
        self.assertEqual(panel["name"], "4K")
        self.assertEqual(panel["status"], "downloading")
        self.assertEqual(panel["path"], MOVIE_ROW["movieFile"]["path"])
        self.assertEqual(panel["size"], 15_000_000_000)
        self.assertEqual(panel["quality"], "Bluray-2160p")
        self.assertEqual(panel["queue"][0]["percent"], 75)
        self.assertEqual(
            [event["label"] for event in panel["history"]],
            ["Imported", "Grabbed", "Failed"],
        )
        self.assertEqual(panel["history"][2]["detail"], "No space left")
        self.assertEqual(panel["search"], {"kind": "movie", "arr_id": 11})

    def test_missing_movie_is_reported_missing(self):
        row = {"id": 12, "hasFile": False, "monitored": True}
        routes = {
            "/api/v3/movie": [row],
            "/api/v3/queue/details": [],
            "/api/v3/history/movie": [],
        }
        with patch(RADARR_GET, _router(routes)):
            (panel,) = self._panels()
        self.assertEqual(panel["status"], "missing")
        self.assertEqual(panel["path"], "")

    def test_movie_radarr_does_not_have_gets_no_panel(self):
        with patch(RADARR_GET, _router({"/api/v3/movie": []})):
            self.assertEqual(self._panels(), [])

    def test_unreachable_server_becomes_an_error_panel_without_the_url(self):
        with patch(
            RADARR_GET, side_effect=requests.ConnectionError("https://radarr.local")
        ):
            (panel,) = self._panels()
        self.assertEqual(panel["error"], "Can't reach Radarr.")
        self.assertNotIn("radarr.local", panel["error"])

    def test_rejected_key_is_named(self):
        with patch(RADARR_GET, return_value=_response({}, 401)):
            (panel,) = self._panels()
        self.assertEqual(panel["error"], "Radarr rejected the API key.")
        self.instance.refresh_from_db()
        self.assertFalse(self.instance.connection_broken)

    def test_non_json_reply_becomes_an_error_panel(self):
        html = _response({})
        html.json.side_effect = requests.JSONDecodeError("Expecting value", "<html>", 0)
        with patch(RADARR_GET, return_value=html):
            (panel,) = self._panels()
        self.assertEqual(panel["error"], "Can't reach Radarr.")

    def test_non_tmdb_movie_is_not_looked_up(self):
        with patch(RADARR_GET) as mock_get:
            panels = arr_library.library_panels(self.user, "manual", "movie", "1")
        self.assertEqual(panels, [])
        mock_get.assert_not_called()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class SonarrPanelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="arr")
        self.instance = SonarrInstance.objects.create(
            user=self.user,
            # HTTP is mocked, but the URL policy still resolves this host.
            # A numeric address keeps cache assertions independent of mDNS.
            base_url="https://127.0.0.1:8989",
            api_key=helpers.encrypt("key"),
        )
        past = (timezone.now() - timedelta(days=3)).isoformat()
        future = (timezone.now() + timedelta(days=3)).isoformat()
        self.routes = {
            "/api/v3/series": [
                {
                    "id": 5,
                    "tmdbId": 95396,
                    "tvdbId": 371572,
                    "monitored": True,
                    "path": "/data/tv/Severance",
                    "statistics": {"episodeFileCount": 3, "episodeCount": 4},
                }
            ],
            "/api/v3/episode": [
                {
                    "id": 101,
                    "seasonNumber": 2,
                    "episodeNumber": 1,
                    "hasFile": True,
                    "monitored": True,
                    "airDateUtc": past,
                    "episodeFile": {
                        "path": "/data/tv/Severance/S02E01.mkv",
                        "size": 2_000_000_000,
                        "dateAdded": "2026-09-29T08:12:00Z",
                        "quality": {"quality": {"name": "WEBDL-1080p"}},
                    },
                },
                {
                    "id": 102,
                    "seasonNumber": 2,
                    "episodeNumber": 2,
                    "hasFile": False,
                    "monitored": True,
                    "airDateUtc": past,
                },
                {
                    "id": 103,
                    "seasonNumber": 2,
                    "episodeNumber": 3,
                    "hasFile": False,
                    "monitored": True,
                    "airDateUtc": future,
                },
                {
                    "id": 104,
                    "seasonNumber": 2,
                    "episodeNumber": 4,
                    "hasFile": False,
                    "monitored": False,
                    "airDateUtc": past,
                },
                {"id": 201, "seasonNumber": 1, "episodeNumber": 1, "hasFile": True},
            ],
            "/api/v3/queue/details": [
                {
                    "episodeId": 102,
                    "seasonNumber": 2,
                    "title": "Severance.S02E02",
                    "size": 10,
                    "sizeleft": 5,
                },
                {"episodeId": 999, "seasonNumber": 3, "title": "Other"},
            ],
            "/api/v3/history/series": [
                _event("grabbed", "2026-09-29T08:00:00Z", episodeId=101),
                _event("downloadFailed", "2026-09-28T08:00:00Z", episodeId=102),
            ],
        }

    def _panels(self, media_type, source="tmdb", media_id="95396", **kwargs):
        fake = _router(self.routes)
        with patch(SONARR_GET, fake):
            panels = arr_library.library_panels(
                self.user, source, media_type, media_id, **kwargs
            )
        return panels, fake

    def test_episode_has_file_details_and_only_its_own_history(self):
        (panel), fake = self._panels("episode", season=2, episode=1)
        (panel,) = panel
        self.assertEqual(panel["status"], "has_file")
        self.assertEqual(panel["path"], "/data/tv/Severance/S02E01.mkv")
        self.assertEqual(panel["quality"], "WEBDL-1080p")
        self.assertEqual([e["label"] for e in panel["history"]], ["Grabbed"])
        self.assertEqual(panel["search"], {"kind": "episode", "arr_id": 101})
        episode_call = next(c for c in fake.calls if c[0].endswith("/episode"))
        self.assertEqual(episode_call[1]["params"]["includeEpisodeFile"], "true")

    def test_episode_in_queue_is_downloading_and_failure_is_listed(self):
        (panel,), _ = self._panels("episode", season=2, episode=2)
        self.assertEqual(panel["status"], "downloading")
        self.assertEqual(panel["queue"][0]["percent"], 50)
        self.assertEqual([e["label"] for e in panel["history"]], ["Failed"])

    def test_unknown_episode_gets_no_panel(self):
        panels, _ = self._panels("episode", season=2, episode=40)
        self.assertEqual(panels, [])

    def test_season_counts_only_aired_monitored_episodes(self):
        (panel,), _ = self._panels("season", season=2)
        self.assertEqual(panel["summary"], (1, 2))
        self.assertEqual(panel["status"], "downloading")
        self.assertEqual(len(panel["queue"]), 1)
        self.assertEqual(
            panel["search"], {"kind": "season", "arr_id": 5, "season": 2}
        )

    def test_show_uses_series_statistics(self):
        (panel,), _ = self._panels("tv")
        self.assertEqual(panel["summary"], (3, 4))
        self.assertEqual(panel["path"], "/data/tv/Severance")
        self.assertEqual(panel["search"], {"kind": "series", "arr_id": 5})

    def test_tvdb_item_matches_on_tvdb_id(self):
        (panel,), _ = self._panels("tv", source="tvdb", media_id="371572")
        self.assertEqual(panel["name"], "Sonarr")

    def test_series_not_in_sonarr_gets_no_panel(self):
        panels, _ = self._panels("tv", media_id="1")
        self.assertEqual(panels, [])

    def test_series_list_is_cached_between_opens(self):
        self._panels("tv")
        _, fake = self._panels("tv")
        self.assertFalse(any(c[0].endswith("/api/v3/series") for c in fake.calls))


class SearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="arr")
        self.other = get_user_model().objects.create_user(username="other")
        self.radarr = RadarrInstance.objects.create(
            user=self.user,
            base_url="https://radarr.local",
            api_key=helpers.encrypt("key"),
        )
        self.sonarr = SonarrInstance.objects.create(
            user=self.user,
            base_url="https://sonarr.local",
            api_key=helpers.encrypt("key"),
        )

    @patch(RADARR_SEND)
    def test_movie_search_posts_a_movies_search_command(self, mock_send):
        mock_send.return_value = _response({})
        error = arr_library.start_search(self.user, "Radarr", self.radarr.pk, "movie", 11)
        self.assertEqual(error, "")
        args, kwargs = mock_send.call_args
        self.assertEqual(args, ("POST", "https://radarr.local/api/v3/command"))
        self.assertEqual(kwargs["json"], {"name": "MoviesSearch", "movieIds": [11]})

    @patch(SONARR_SEND)
    def test_sonarr_commands(self, mock_send):
        mock_send.return_value = _response({})
        for kind, arr_id, season, body in (
            ("episode", 101, None, {"name": "EpisodeSearch", "episodeIds": [101]}),
            (
                "season",
                5,
                2,
                {"name": "SeasonSearch", "seriesId": 5, "seasonNumber": 2},
            ),
            ("series", 5, None, {"name": "SeriesSearch", "seriesId": 5}),
        ):
            with self.subTest(kind=kind):
                error = arr_library.start_search(
                    self.user, "Sonarr", self.sonarr.pk, kind, arr_id, season
                )
                self.assertEqual(error, "")
                self.assertEqual(mock_send.call_args.kwargs["json"], body)

    @patch(RADARR_SEND)
    @patch(SONARR_SEND)
    def test_refuses_mismatched_kind_other_users_instance_and_missing_ids(
        self, mock_sonarr, mock_radarr
    ):
        cases = (
            ("Sonarr", self.sonarr.pk, "movie", 1, None),
            ("Radarr", self.radarr.pk, "episode", 1, None),
            ("Sonarr", self.sonarr.pk, "season", 1, None),
            ("Radarr", self.radarr.pk, "bogus", 1, None),
        )
        for app, instance_id, kind, arr_id, season in cases:
            with self.subTest(kind=kind, app=app):
                self.assertEqual(
                    arr_library.start_search(
                        self.user, app, instance_id, kind, arr_id, season
                    ),
                    "Unknown search.",
                )
        self.assertEqual(
            arr_library.start_search(self.other, "Radarr", self.radarr.pk, "movie", 1),
            "Radarr is not connected.",
        )
        mock_radarr.assert_not_called()
        mock_sonarr.assert_not_called()

    @patch(RADARR_SEND)
    def test_failed_search_reports_without_the_exception_text(self, mock_send):
        mock_send.side_effect = requests.ConnectionError("https://radarr.local")
        error = arr_library.start_search(self.user, "Radarr", self.radarr.pk, "movie", 1)
        self.assertEqual(error, "Couldn't start the search in Radarr.")


class SeerrRequestsTests(TestCase):
    def test_requests_are_listed_newest_first_with_a_name(self):
        data = {
            "mediaInfo": {
                "requests": [
                    {
                        "status": 2,
                        "createdAt": "2026-09-20T10:00:00.000Z",
                        "requestedBy": {"plexUsername": "maya"},
                    },
                    {
                        "status": 1,
                        "createdAt": "2026-09-22T10:00:00.000Z",
                        "requestedBy": {"displayName": "Sam", "username": "sam"},
                    },
                ]
            }
        }
        rows = seerr_api.requests_for(data)
        self.assertEqual([r["by"] for r in rows], ["Sam", "maya"])
        self.assertEqual([r["status"] for r in rows], ["Pending approval", "Approved"])
        self.assertEqual(rows[0]["when"].day, 22)

    def test_season_filter_keeps_matching_and_all_season_requests(self):
        data = {
            "mediaInfo": {
                "requests": [
                    {"createdAt": "2026-09-01T00:00:00Z", "seasons": [{"seasonNumber": 1}]},
                    {"createdAt": "2026-09-02T00:00:00Z", "seasons": [{"seasonNumber": 2}]},
                    {"createdAt": "2026-09-03T00:00:00Z", "seasons": []},
                ]
            }
        }
        rows = seerr_api.requests_for(data, season_number=2)
        self.assertEqual([r["created"][:10] for r in rows], ["2026-09-03", "2026-09-02"])

    def test_no_requests(self):
        self.assertEqual(seerr_api.requests_for({}), [])


class LibraryPanelViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="arr")
        self.client.force_login(self.user)
        RadarrInstance.objects.create(
            user=self.user,
            name="4K",
            base_url="https://radarr.local",
            api_key=helpers.encrypt("key"),
        )
        self.url = reverse("library_panel", args=["tmdb", "movie", "693134"])
        self.routes = {
            "/api/v3/movie": [MOVIE_ROW],
            "/api/v3/queue/details": [],
            "/api/v3/history/movie": [_event("grabbed", "2026-09-30T22:12:00Z")],
        }

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_get_renders_details(self):
        with patch(RADARR_GET, _router(self.routes)):
            response = self.client.get(self.url)
        self.assertContains(response, "Has file")
        self.assertContains(response, "Dune.mkv")
        self.assertContains(response, "Bluray-2160p")
        self.assertContains(response, "Search now")
        self.assertNotContains(response, "Requests")

    def test_post_starts_the_search_and_shows_it(self):
        instance = RadarrInstance.objects.get(user=self.user)
        with (
            patch(RADARR_GET, _router(self.routes)),
            patch(RADARR_SEND, return_value=_response({})) as mock_send,
        ):
            response = self.client.post(
                self.url,
                {
                    "app": "Radarr",
                    "instance_id": instance.pk,
                    "kind": "movie",
                    "arr_id": "11",
                },
            )
        self.assertContains(response, "Search started in Radarr.")
        mock_send.assert_called_once()

    def test_seerr_requests_are_shown_when_connected(self):
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = helpers.encrypt("key")
        self.user.save()
        payload = {
            "mediaInfo": {
                "requests": [
                    {
                        "status": 2,
                        "createdAt": "2026-09-22T10:00:00Z",
                        "requestedBy": {"username": "maya"},
                    }
                ]
            }
        }
        with (
            patch(RADARR_GET, _router(self.routes)),
            patch(SEERR_SEND, return_value=_response(payload)),
        ):
            response = self.client.get(self.url)
        self.assertContains(response, "Requests")
        self.assertContains(response, "maya")
        self.assertContains(response, "Approved")

    def test_episode_lists_only_requests_for_its_season(self):
        RadarrInstance.objects.all().delete()
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = helpers.encrypt("key")
        self.user.save()
        payload = {
            "mediaInfo": {
                "requests": [
                    {
                        "status": 2,
                        "createdAt": "2026-09-22T10:00:00Z",
                        "requestedBy": {"username": "maya"},
                        "seasons": [{"seasonNumber": 1}],
                    },
                    {
                        "status": 2,
                        "createdAt": "2026-09-23T10:00:00Z",
                        "requestedBy": {"username": "sam"},
                        "seasons": [{"seasonNumber": 2}],
                    },
                ]
            }
        }
        url = reverse("library_panel", args=["tmdb", "episode", "95396"])
        with patch(SEERR_SEND, return_value=_response(payload)):
            response = self.client.get(url, {"season_number": 2, "episode_number": 1})
        self.assertContains(response, "sam")
        self.assertNotContains(response, "maya")

    def test_seerr_failure_is_shown_in_the_requests_box_only(self):
        self.user.seerr_url = "http://seerr:5055"
        self.user.seerr_api_key = helpers.encrypt("key")
        self.user.save()
        with (
            patch(RADARR_GET, _router(self.routes)),
            patch(SEERR_SEND, side_effect=requests.ConnectionError("x")),
        ):
            response = self.client.get(self.url)
        self.assertContains(response, "Could not reach Seerr")
        self.assertContains(response, "Has file")

    def test_nothing_connected_renders_an_empty_panel(self):
        RadarrInstance.objects.all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Search now")


class TrackModalLibraryTabTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="arr")
        self.client.force_login(self.user)

    def _modal(self, media_type, media_id, season_number=None, **query):
        kwargs = {"source": "tmdb", "media_type": media_type, "media_id": media_id}
        if season_number is not None:
            kwargs["season_number"] = season_number
        url = reverse("track_modal", kwargs=kwargs)
        with patch("app.providers.services.get_media_metadata") as mock_metadata:
            mock_metadata.return_value = {
                "title": "Dune",
                "image": "none.svg",
                "media_id": media_id,
                "media_type": media_type,
                "source": "tmdb",
                "related": {},
                "details": {},
                "genres": [],
            }
            return self.client.get(url, query)

    def test_movie_modal_has_a_collection_tab_that_loads_the_panel(self):
        response = self._modal("movie", "693134")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["collection_tab_available"])
        self.assertEqual(
            response.context["library_panel_url"],
            reverse("library_panel", args=["tmdb", "movie", "693134"]),
        )
        self.assertContains(response, 'hx-trigger="intersect once"')

    def test_season_modal_passes_the_season_number(self):
        response = self._modal("season", "95396", season_number=2)
        self.assertTrue(response.context["collection_tab_available"])
        self.assertTrue(
            response.context["library_panel_url"].endswith("?season_number=2")
        )
