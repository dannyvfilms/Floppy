"""Tests for durable metadata cache API endpoints."""

from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import MediaTypes, Sources

from .base import FloppyApiTestCase


class MetadataCacheApiTests(FloppyApiTestCase):
    """Exercise local reads, ownership, policy discovery, and refresh controls."""

    def setUp(self):
        """Select one movie already tracked by the primary API user."""
        super().setUp()
        self.item = self.items_by_type[MediaTypes.MOVIE.value][0]
        self.route_args = (
            self.item.media_type,
            self.item.source,
            self.item.media_id,
        )

    def test_policy_requires_authentication(self):
        """The instance policy is not exposed to unauthenticated callers."""
        response = self.call_api("get", "api_metadata_cache_policy")

        self.assertEqual(response.status_code, HTTP.UNAUTHORIZED)

    def test_policy_describes_supported_client_controls(self):
        """Clients can discover effective settings and stable request controls."""
        response = self.call_api(
            "get",
            "api_metadata_cache_policy",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.data["metadata"]["read_mode"], "local-first")
        self.assertIn("effective_fresh_seconds", response.data["metadata"])
        self.assertEqual(response.data["request"]["refresh_modes"], ["queue", "wait"])
        self.assertIn("season_number", response.data["request"]["query_parameters"])

    @patch(
        "api.fork_views_cache.services.get_media_metadata",
        side_effect=AssertionError("GET must not call a provider"),
    )
    def test_get_returns_local_item_metadata_without_provider_call(self, mock_metadata):
        """The guaranteed-local read path uses the durable Item or snapshot."""
        response = self.call_api(
            "get",
            "api_metadata_cache",
            args=self.route_args,
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        mock_metadata.assert_not_called()
        self.assertEqual(response.data["metadata"]["title"], self.item.title)
        self.assertIn(response.data["cache"]["source"], {"item", "snapshot"})
        self.assertIn("stale", response.data["cache"])
        self.assertNotIn("payload", response.data["cache"])

    def test_other_user_cannot_read_snapshot(self):
        """A snapshot cannot bypass tracked-library ownership."""
        response = self.call_api(
            "get",
            "api_metadata_cache",
            args=self.route_args,
            headers=self.auth_headers2,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    @patch("app.tasks_metadata_snapshots.refresh_metadata_snapshot.apply_async")
    def test_post_queues_refresh_and_returns_local_copy(self, mock_apply_async):
        """Queue mode returns immediately with the still-usable local payload."""
        response = self.call_api(
            "post",
            "api_metadata_cache",
            args=self.route_args,
            payload={"mode": "queue"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertTrue(response.data["queued"])
        self.assertEqual(response.data["metadata"]["title"], self.item.title)
        mock_apply_async.assert_called_once()

    @patch("api.fork_views_cache.services.get_media_metadata")
    def test_post_can_wait_for_refresh(self, mock_metadata):
        """Wait mode returns the refreshed payload and its cache state."""
        mock_metadata.return_value = {
            "media_id": self.item.media_id,
            "media_type": self.item.media_type,
            "source": self.item.source,
            "title": "Refreshed title",
            "_floppy_cache": {
                "source": "provider",
                "stale": False,
                "state": "current",
            },
        }

        response = self.call_api(
            "post",
            "api_metadata_cache",
            args=self.route_args,
            payload={"mode": "wait"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.data["metadata"]["title"], "Refreshed title")
        self.assertEqual(response.data["cache"]["state"], "current")
        mock_metadata.assert_called_once()

    def test_invalid_refresh_mode_is_rejected(self):
        """Unknown client behavior is rejected instead of reinterpreted."""
        response = self.call_api(
            "post",
            "api_metadata_cache",
            args=self.route_args,
            payload={"mode": "surprise"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_invalid_variant_is_rejected(self):
        """Invalid episode selectors fail before a metadata lookup."""
        response = self.call_api(
            "get",
            "api_metadata_cache",
            args=self.route_args,
            params={"episode_number": "not-a-number"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_unknown_provider_identity_is_not_owned(self):
        """A valid route cannot read an identity outside the user's library."""
        response = self.call_api(
            "get",
            "api_metadata_cache",
            args=(MediaTypes.MOVIE.value, Sources.TMDB.value, "missing-999"),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
