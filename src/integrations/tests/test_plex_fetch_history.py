from unittest.mock import Mock, patch

from django.test import TestCase

from integrations import plex as plex_api


class FetchHistoryTests(TestCase):
    """Plex history pages should request external IDs with each row."""

    @patch("integrations.plex.requests.get")
    def test_requests_include_guids(self, mock_get):
        response = Mock()
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {
            "MediaContainer": {
                "Metadata": [
                    {"ratingKey": "1", "Guid": [{"id": "tmdb://254013"}]},
                ],
                "totalSize": 1,
            },
        }
        mock_get.return_value = response

        entries, total = plex_api.fetch_history(
            "token",
            "http://plex.example.com",
            "2",
            0,
            size=100,
        )

        self.assertEqual(total, 1)
        self.assertEqual(entries[0]["Guid"], [{"id": "tmdb://254013"}])
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["includeGuids"], 1)
        self.assertEqual(params["librarySectionID"], "2")
