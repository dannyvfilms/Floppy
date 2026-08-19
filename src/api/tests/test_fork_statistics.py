# FORK: tests for the full statistics API endpoints.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from .base import FloppyApiTestCase


class StatisticsOverviewTests(FloppyApiTestCase):
    """GET /statistics/overview."""

    def test_default_range_returns_statistics(self):
        """Without params, the user's preferred range is used."""
        response = self.call_api(
            "get",
            "api_statistics_overview",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIn("range", payload)
        self.assertIn("statistics", payload)
        self.assertIn("media_count", payload["statistics"])

    def test_all_time_range(self):
        """start_date=end_date=all selects All Time (no date bounds)."""
        response = self.call_api(
            "get",
            "api_statistics_overview",
            params={"start_date": "all", "end_date": "all"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIsNone(response.json()["range"]["start_date"])

    def test_explicit_date_range(self):
        """Explicit YYYY-MM-DD bounds are honored."""
        response = self.call_api(
            "get",
            "api_statistics_overview",
            params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIsNotNone(response.json()["range"]["start_date"])

    def test_invalid_date_rejected(self):
        """Malformed dates return 400."""
        response = self.call_api(
            "get",
            "api_statistics_overview",
            params={"start_date": "not-a-date", "end_date": "2024-12-31"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class StatisticsRefreshTests(FloppyApiTestCase):
    """POST /statistics/refresh."""

    @patch("api.fork_views_statistics.statistics_cache.schedule_statistics_refresh")
    def test_refresh_valid_range(self, mock_schedule):
        """A valid predefined range schedules a refresh."""
        response = self.call_api(
            "post",
            "api_statistics_refresh",
            payload={"range_name": "Last 12 Months"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        mock_schedule.assert_called_once()

    def test_refresh_missing_range_rejected(self):
        """Missing range_name returns 400 with valid choices."""
        response = self.call_api(
            "post",
            "api_statistics_refresh",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("choices", response.json())

    def test_refresh_invalid_range_rejected(self):
        """Unknown range names return 400."""
        response = self.call_api(
            "post",
            "api_statistics_refresh",
            payload={"range_name": "Not A Real Range"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
