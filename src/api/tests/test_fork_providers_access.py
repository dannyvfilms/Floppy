# Tests for provider endpoints that the existing fork tests did not
# exercise yet (import route, schedule list, device approval, connection
# direction/pause, metadata match preview/apply).
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import Item, MediaTypes, Movie, Sources
from integrations.models import SyncBinding
from integrations.oauth_models import OAuthClient, OAuthDeviceAuthorization
from lists.models import CustomListItem

from .base import FloppyApiTestCase


class ProviderSchedulesTests(FloppyApiTestCase):
    """GET /providers/<slug>/schedules/."""

    def test_requires_authentication(self):
        response = self.call_api(
            "get", "api_provider_schedules", args=("mal",), headers=self.invalid_auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_unknown_slug_is_404(self):
        response = self.call_api(
            "get", "api_provider_schedules", args=("no-such",), headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["detail"], "Unknown provider.")

    def test_empty_schedule_list(self):
        response = self.call_api(
            "get", "api_provider_schedules", args=("mal",), headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"results": []})


class ProviderImportTests(FloppyApiTestCase):
    """POST /providers/<slug>/import/."""

    def test_requires_authentication(self):
        response = self.call_api(
            "post", "api_provider_import", args=("mal",), payload={}, headers=self.invalid_auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_unknown_slug_is_404(self):
        response = self.call_api(
            "post", "api_provider_import", args=("no-such",), payload={}, headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(
            response.json()["detail"], "Use the import endpoint for this provider."
        )

    def test_missing_username_is_refused_without_500(self):
        response = self.call_api(
            "post", "api_provider_import", args=("mal",), payload={}, headers=self.auth_headers
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("detail", response.json())


class DeviceApprovalTests(FloppyApiTestCase):
    """GET/POST /connections/device/."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user1)
        self.oauth_client = OAuthClient.register_public_client(name="Pair App")
        authorization, _device_code, self.user_code = OAuthDeviceAuthorization.issue(
            client=self.oauth_client,
            requested_scopes=["user:read"],
        )
        self.authorization = authorization

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_connection_device",
            params={"user_code": self.user_code},
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_lookup_describes_the_application(self):
        response = self.call_api(
            "get",
            "api_connection_device",
            params={"user_code": self.user_code},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["user_code"], self.user_code)
        self.assertEqual(body["application"], "Pair App")
        self.assertTrue(body["scopes"])

    def test_unknown_code_is_404(self):
        response = self.call_api(
            "get",
            "api_connection_device",
            params={"user_code": "NOPE-NOPE"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["detail"], "That device code is not valid.")

    def test_approve_then_reuse_is_refused(self):
        response = self.call_api(
            "post",
            "api_connection_device",
            payload={"user_code": self.user_code, "action": "approve"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"ok": True, "action": "approve"})
        # The approval guard refuses reuse (a different message than the
        # lookup path reports).
        response = self.call_api(
            "post",
            "api_connection_device",
            payload={"user_code": self.user_code, "action": "approve"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "This device authorisation can no longer be approved.",
        )

    def test_deny_is_supported(self):
        authorization, _device_code, user_code = OAuthDeviceAuthorization.issue(
            client=self.oauth_client,
            requested_scopes=["user:read"],
        )
        response = self.call_api(
            "post",
            "api_connection_device",
            payload={"user_code": user_code, "action": "deny"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"ok": True, "action": "deny"})

    def test_invalid_action_is_refused(self):
        response = self.call_api(
            "post",
            "api_connection_device",
            payload={"user_code": self.user_code, "action": "maybe"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Choose whether to approve or deny this application.",
        )

    def test_unknown_code_post_is_refused(self):
        response = self.call_api(
            "post",
            "api_connection_device",
            payload={"user_code": "NOPE-NOPE", "action": "approve"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "That device code is not valid.")


class ConnectionControlTests(FloppyApiTestCase):
    """POST /connections/<binding_id>/direction/ and /pause/."""

    def setUp(self):
        super().setUp()
        self.other_binding = SyncBinding.objects.create(
            user=self.user2,
            client_kind="plex",
            origin_key="binding-user2",
        )

    def test_requires_authentication(self):
        response = self.call_api(
            "post",
            "api_connection_direction",
            args=(self.other_binding.id,),
            payload={"direction": "off"},
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_direction_unknown_or_foreign_binding_changes_nothing(self):
        for binding_id in (999_999, self.other_binding.id):
            response = self.call_api(
                "post",
                "api_connection_direction",
                args=(binding_id,),
                payload={"direction": "both"},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
            self.assertEqual(
                response.json()["detail"], "That connection no longer exists."
            )
        self.other_binding.refresh_from_db()
        self.assertEqual(self.other_binding.approved_directions, [])

    def test_pause_unknown_or_foreign_binding_changes_nothing(self):
        for binding_id in (999_999, self.other_binding.id):
            response = self.call_api(
                "post",
                "api_connection_pause",
                args=(binding_id,),
                payload={"paused": True},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.other_binding.refresh_from_db()
        self.assertFalse(self.other_binding.kill_switch)


class MetadataMatchPreviewTests(FloppyApiTestCase):
    """POST /metadata-review/items/<item_id>/preview/."""

    def setUp(self):
        super().setUp()
        self.source_item = Item.objects.create(
            media_id="7001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Origin Movie",
            image="https://example.com/origin.jpg",
        )
        Movie.objects.create(item=self.source_item, user=self.user1)
        self.search_results = {
            "results": [
                {
                    "media_id": "7002",
                    "title": "Destination Movie",
                    "image": "https://example.com/destination.jpg",
                }
            ]
        }

    def preview(self, headers=None, payload=None):
        with patch("app.providers.services.search", return_value=self.search_results):
            return self.call_api(
                "post",
                "api_metadata_match_preview",
                args=(self.source_item.pk,),
                payload=payload
                or {"q": "destination", "destination_media_id": "7002"},
                headers=headers or self.auth_headers,
            )

    def test_requires_authentication(self):
        response = self.preview(headers=self.invalid_auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_other_users_item_is_404(self):
        response = self.preview(headers=self.auth_headers2)
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json()["detail"], "Not found.")
        # Nothing moved.
        self.assertTrue(
            Movie.objects.filter(user=self.user1, item=self.source_item).exists()
        )

    def test_unknown_item_is_404(self):
        with patch("app.providers.services.search", return_value=self.search_results):
            response = self.call_api(
                "post",
                "api_metadata_match_preview",
                args=(99_999_999,),
                payload={"q": "destination"},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_invalid_destination_is_refused(self):
        payload = {"q": "destination", "destination_media_id": "999999"}
        response = self.preview(payload=payload)
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"], "Choose a valid same-type destination."
        )

    def test_preview_returns_token_and_destination(self):
        response = self.preview()
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        body = response.json()
        self.assertTrue(body["token"])
        self.assertEqual(body["source"]["media_id"], "7001")
        self.assertEqual(body["destination"]["media_id"], "7002")
        self.assertIn("counts", body)


class MetadataMatchApplyTests(FloppyApiTestCase):
    """POST /metadata-review/items/<item_id>/apply/."""

    def setUp(self):
        super().setUp()
        self.source_item = Item.objects.create(
            media_id="7001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Origin Movie",
            image="https://example.com/origin.jpg",
        )
        Movie.objects.create(item=self.source_item, user=self.user1)
        self.destination_item = Item.objects.create(
            media_id="7002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Destination Movie",
            image="https://example.com/destination.jpg",
        )
        self.search_results = {
            "results": [
                {
                    "media_id": "7002",
                    "title": "Destination Movie",
                    "image": "https://example.com/destination.jpg",
                }
            ]
        }

    def _preview_token(self):
        with patch("app.providers.services.search", return_value=self.search_results):
            response = self.call_api(
                "post",
                "api_metadata_match_preview",
                args=(self.source_item.pk,),
                payload={"q": "destination", "destination_media_id": "7002"},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        return response.json()["token"]

    def test_requires_authentication(self):
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            args=(self.source_item.pk,),
            payload={"destination_item_id": self.destination_item.pk, "token": "x"},
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_other_users_item_is_404(self):
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            args=(self.source_item.pk,),
            payload={
                "destination_item_id": self.destination_item.pk,
                "token": "whatever",
            },
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertTrue(
            Movie.objects.filter(user=self.user1, item=self.source_item).exists()
        )

    def test_missing_token_is_refused(self):
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            args=(self.source_item.pk,),
            payload={"destination_item_id": self.destination_item.pk},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Refresh the correction preview before applying.",
        )

    def test_apply_moves_the_tracked_entry(self):
        token = self._preview_token()
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            args=(self.source_item.pk,),
            payload={
                "destination_item_id": self.destination_item.pk,
                "token": token,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["id"], self.destination_item.pk)
        self.assertFalse(
            Movie.objects.filter(user=self.user1, item=self.source_item).exists()
        )
        self.assertTrue(
            Movie.objects.filter(user=self.user1, item=self.destination_item).exists()
        )

    def test_stale_token_is_conflict(self):
        token = self._preview_token()
        # Add a tracked list item behind the preview's back: the digest covers
        # the tracked state (a status change alone does not go stale).
        CustomListItem.objects.create(
            custom_list=self.lists_by_name["favorites"], item=self.source_item
        )
        response = self.call_api(
            "post",
            "api_metadata_match_apply",
            args=(self.source_item.pk,),
            payload={
                "destination_item_id": self.destination_item.pk,
                "token": token,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CONFLICT, response.content)
