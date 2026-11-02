"""Stable machine-readable ``code`` on the golden-path refusals (#1615)."""
from http import HTTPStatus as HTTP  # noqa: N814

from app.models import MediaTypes, Sources

from .base import FloppyApiTestCase


class ErrorCodeTests(FloppyApiTestCase):
    """``code`` rides beside the unchanged ``detail`` and status."""

    def _detail_args(self, item):
        return (item.media_type, item.source, item.media_id)

    def test_deleting_untracked_media_is_media_not_tracked(self):
        response = self.call_api(
            "delete",
            "api_media_detail",
            args=(MediaTypes.GAME.value, Sources.IGDB.value, "424242"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        body = response.json()
        self.assertEqual(body["code"], "MEDIA_NOT_TRACKED")
        self.assertEqual(body["detail"], "Media not found or not tracked.")

    def test_unknown_status_is_invalid_status(self):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=self._detail_args(item),
            payload={"status": "not-a-status"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["code"], "INVALID_STATUS")

    def test_other_validation_errors_carry_no_code(self):
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        response = self.call_api(
            "patch",
            "api_media_detail",
            args=self._detail_args(item),
            payload={"score": 99},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertNotIn("code", response.json())
