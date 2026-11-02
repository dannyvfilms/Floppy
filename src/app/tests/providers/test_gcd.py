import base64
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import Item, MediaTypes, Sources
from app.providers import gcd, services
from app.services import metadata_resolution
from events.calendar.comic import process_comic
from events.calendar.helpers import date_parser


def _series_list_page(count=1):
    return {
        "count": count,
        "next": None,
        "results": [
            {
                "api_url": "https://www.comics.org/api/series/2406/?format=json",
                "name": "Batman",
                "year_began": 1940,
                "publisher": "https://www.comics.org/api/publisher/54/",
            },
        ],
    }


def _overview_item(issue_id, number, cover=True):
    return {
        "issue_id": issue_id,
        "number": number,
        "key_date": "1940-04-00" if number == "1" else "1940-06-??",
        "on_sale_date": "1940-03-01",
        "cover_url": f"https://files1.comics.org/img/{issue_id}/w400.jpg" if cover else "",
    }


@override_settings(GCD_USERNAME="reader", GCD_PASSWORD="pw")
class GcdProviderTests(TestCase):
    """GCD provider parsing, auth, and error handling (API mocked)."""

    def setUp(self):
        cache.clear()

    def test_request_headers_use_basic_auth(self):
        token = base64.b64encode(b"reader:pw").decode()

        self.assertEqual(gcd.request_headers()["Authorization"], f"Basic {token}")

    @patch("app.providers.gcd.services.api_request")
    def test_search_parses_ids_from_api_urls(self, mock_request):
        mock_request.return_value = _series_list_page(count=120)

        data = gcd.search("Bat/man", 2)

        self.assertEqual(data["page"], 2)
        self.assertEqual(data["total_results"], 120)
        self.assertEqual(data["results"][0]["media_id"], "2406")
        self.assertEqual(data["results"][0]["source"], Sources.GCD.value)
        self.assertEqual(data["results"][0]["year"], 1940)
        url = mock_request.call_args.args[2]
        self.assertTrue(url.endswith("/api/series/name/Bat%2Fman/"))
        self.assertEqual(mock_request.call_args.kwargs["params"]["page"], 2)

    @patch("app.providers.gcd.services.api_request")
    def test_search_issues_needs_a_number(self, mock_request):
        data = gcd.search_issues("Batman", 1)

        self.assertEqual(data["results"], [])
        mock_request.assert_not_called()

    @patch("app.providers.gcd.services.api_request")
    def test_search_issues_splits_series_and_number(self, mock_request):
        mock_request.return_value = {
            "count": 1,
            "results": [
                {
                    "api_url": "https://www.comics.org/api/issue/125295/",
                    "series_name": "Batman",
                    "descriptor": "12",
                    "publication_date": "December 1942",
                },
            ],
        }

        data = gcd.search_issues("Batman #12", 1)

        self.assertTrue(
            mock_request.call_args.args[2].endswith("/series/name/Batman/issue/12/"),
        )
        self.assertEqual(data["results"][0]["title"], "Batman #12")
        self.assertEqual(data["results"][0]["year"], "1942")
        self.assertEqual(data["results"][0]["media_id"], "125295")

    @patch("app.providers.gcd.services.api_request")
    def test_comic_builds_series_from_overview(self, mock_request):
        def fake(provider, method, url, params=None, headers=None, **_):
            if url.endswith("/series/2406/"):
                return {
                    "name": "Batman",
                    "year_began": 1940,
                    "notes": "The Dark Knight.",
                    "publisher": "https://www.comics.org/api/publisher/54/",
                    "active_issues": ["a", "b", "c"],
                }
            if url.endswith("/publisher/54/"):
                return {"name": "DC"}
            if params["page"] == 1:
                return {
                    "next": "page2",
                    "results": [_overview_item(3, "10"), _overview_item(1, "1", False)],
                }
            return {"next": None, "results": [_overview_item(2, "2")]}

        mock_request.side_effect = fake

        data = gcd.comic("2406")

        self.assertEqual(data["title"], "Batman")
        self.assertEqual(data["details"]["publisher"], "DC")
        self.assertEqual(data["synopsis"], "The Dark Knight.")
        self.assertEqual(
            [issue["issue_number"] for issue in data["issues"]],
            ["1", "2", "10"],
        )
        self.assertEqual(data["max_issue_number"], 10)
        self.assertEqual(data["last_issue_id"], "3")
        # Series cover is the first issue that has one.
        self.assertEqual(data["image"], "https://files1.comics.org/img/2/w400.jpg")
        self.assertEqual(data["issues"][0]["cover_date"], None)
        self.assertEqual(data["issues"][0]["store_date"], "1940-03-01")

    @patch("app.providers.gcd.MAX_OVERVIEW_PAGES", 1)
    @patch("app.providers.gcd.services.api_request")
    def test_overlong_series_is_not_given_a_last_issue(self, mock_request):
        def fake(provider, method, url, params=None, headers=None, **_):
            if url.endswith("/series/2406/"):
                return {"name": "Action Comics"}
            return {"next": "more", "results": [_overview_item(1, "1")]}

        mock_request.side_effect = fake

        data = gcd.comic("2406")

        self.assertIsNone(data["max_issue_number"])
        self.assertIsNone(data["last_issue_id"])

    @patch("app.providers.gcd.services.api_request")
    def test_comic_issue_normalises_dates_and_synopsis(self, mock_request):
        mock_request.return_value = {
            "series_name": "Batman",
            "number": "1",
            "title": "",
            "key_date": "1940-04-00",
            "on_sale_date": "1940-03-01",
            "cover": "https://files1.comics.org/img/1/w400.jpg",
            "series": "https://www.comics.org/api/series/2406/",
            "story_set": [{"synopsis": ""}, {"synopsis": "Bruce Wayne debuts."}],
        }

        data = gcd.comic_issue("1")

        self.assertEqual(data["title"], "Batman #1")
        self.assertEqual(data["synopsis"], "Bruce Wayne debuts.")
        self.assertEqual(data["details"]["volume_id"], "2406")
        self.assertIsNone(data["details"]["cover_date"])
        self.assertEqual(data["details"]["store_date"], "1940-03-01")
        self.assertEqual(data["details"]["start_date"], "1940")

    @patch("app.providers.gcd.services.api_request")
    def test_rejected_login_says_what_to_check(self, mock_request):
        response = MagicMock(status_code=401)
        mock_request.side_effect = requests.exceptions.HTTPError(response=response)

        with self.assertRaises(services.ProviderAPIError) as raised:
            gcd.comic("2406")

        self.assertEqual(raised.exception.provider, Sources.GCD.value)

    @patch("app.providers.gcd.services.api_request", return_value={})
    def test_missing_series_is_not_found(self, _mock_request):
        with self.assertRaises(services.ProviderAPIError):
            gcd.comic("999999999")


@override_settings(GCD_USERNAME="reader", GCD_PASSWORD="pw")
class GcdRoutingTests(TestCase):
    """The GCD source is routed and selectable like any other comic source."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.services.gcd.comic")
    @patch("app.providers.services.comicvine.comic")
    def test_metadata_routes_by_source(self, mock_cv, mock_gcd):
        services.get_media_metadata("comic", "5", Sources.GCD.value)
        services.get_media_metadata("comic", "5", Sources.COMICVINE.value)

        mock_gcd.assert_called_once()
        mock_cv.assert_called_once()

    @patch("app.providers.services.gcd.search_issues")
    @patch("app.providers.services.gcd.search")
    @patch("app.providers.services.comicvine.search")
    def test_search_routes_by_source(self, mock_cv, mock_gcd, mock_gcd_issues):
        empty = {"page": 1, "total_results": 0, "total_pages": 1, "results": []}
        mock_gcd.return_value = empty
        mock_gcd_issues.return_value = empty
        mock_cv.return_value = empty

        services.search("comic", "batman", 2, Sources.GCD.value)
        services.search("comicissue", "batman #1", 1, Sources.GCD.value)
        services.search("comic", "batman", 2, Sources.COMICVINE.value)

        mock_gcd.assert_called_once_with("batman", 2, user=None)
        mock_gcd_issues.assert_called_once()
        mock_cv.assert_called_once()

    def test_user_default_source_is_honoured_when_configured(self):
        user = get_user_model().objects.create_user(username="gcd", password="x")
        user.comic_metadata_source_default = Sources.GCD.value

        self.assertEqual(
            metadata_resolution.metadata_default_source(user, MediaTypes.COMIC.value),
            Sources.GCD.value,
        )
        self.assertEqual(
            metadata_resolution.metadata_default_source(
                user,
                MediaTypes.COMIC_ISSUE.value,
            ),
            Sources.GCD.value,
        )

    @override_settings(GCD_USERNAME="", GCD_PASSWORD="")
    def test_default_falls_back_to_comic_vine_without_a_login(self):
        user = get_user_model().objects.create_user(username="gcd2", password="x")
        user.comic_metadata_source_default = Sources.GCD.value

        self.assertEqual(
            metadata_resolution.metadata_default_source(user, MediaTypes.COMIC.value),
            Sources.COMICVINE.value,
        )


class GcdCalendarTests(TestCase):
    """Calendar events for a GCD series use GCD's issue dates."""

    def setUp(self):
        self.item = Item.objects.create(
            media_id="2406",
            source=Sources.GCD.value,
            media_type=MediaTypes.COMIC.value,
            title="Batman",
            image="http://example.com/batman.jpg",
        )

    @patch("events.calendar.comic.gcd.comic_issue")
    @patch("events.calendar.comic.services.get_media_metadata")
    def test_uses_gcd_store_date(self, mock_metadata, mock_issue):
        mock_metadata.return_value = {"max_issue_number": 10, "last_issue_id": "3"}
        mock_issue.return_value = {
            "details": {"store_date": "1940-03-01", "cover_date": None},
        }
        events_bulk = []

        self.assertTrue(process_comic(self.item, events_bulk))

        mock_issue.assert_called_once_with("3")
        self.assertEqual(events_bulk[0].content_number, 10)
        self.assertEqual(events_bulk[0].datetime, date_parser("1940-03-01"))

    @patch("events.calendar.comic.gcd.comic_issue")
    @patch("events.calendar.comic.services.get_media_metadata")
    def test_series_without_a_known_last_issue_is_skipped(
        self,
        mock_metadata,
        mock_issue,
    ):
        mock_metadata.return_value = {"max_issue_number": None, "last_issue_id": None}
        events_bulk = []

        self.assertTrue(process_comic(self.item, events_bulk))

        self.assertEqual(events_bulk, [])
        mock_issue.assert_not_called()
