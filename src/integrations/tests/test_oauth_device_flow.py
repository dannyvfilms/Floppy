from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import AuthenticationFailed

from api.authentication import authenticate_token
from integrations.models import IntegrationToken
from integrations.oauth_models import (
    OAUTH_DEVICE_CODE_GRANT,
    OAUTH_REFRESH_TOKEN_GRANT,
    OAuthClient,
    OAuthDeviceAuthorization,
    OAuthRefreshToken,
    oauth_token_digest,
)


class OAuthDeviceFlowTests(TestCase):
    """Verify Floppy's public-client OAuth device flow end to end."""

    def setUp(self):
        """Create users and a minimally privileged public OAuth client."""
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="oauth-user")
        self.other_user = user_model.objects.create_user(username="oauth-other")
        self.oauth_client = OAuthClient.register_public_client(
            name="Kodi Living Room",
            allowed_scopes=["catalog:read", "progress:read", "progress:write"],
        )

    def issue_device_code(self, scope="catalog:read progress:read"):
        """Issue one device code and return its response payload."""
        response = self.client.post(
            reverse("oauth_device_authorization"),
            {
                "client_id": self.oauth_client.client_id,
                "scope": scope,
            },
        )
        self.assertEqual(response.status_code, HTTP.OK)
        return response.json()

    def approve_and_exchange(self, scope="catalog:read progress:read"):
        """Complete device approval and exchange it for a token pair."""
        device = self.issue_device_code(scope)
        self.client.force_login(self.user)
        approval = self.client.post(
            reverse("oauth_device"),
            {
                "user_code": device["user_code"],
                "action": "approve",
            },
        )
        self.assertEqual(approval.status_code, HTTP.OK)

        token_response = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": device["device_code"],
            },
        )
        self.assertEqual(token_response.status_code, HTTP.OK)
        return device, token_response.json()

    def test_public_client_registry_restricts_client_type_scopes_and_grants(self):
        """Registry accepts only public clients using the supported OAuth surface."""
        self.assertTrue(self.oauth_client.client_id.startswith("flp_oauth_"))
        self.assertTrue(self.oauth_client.allows_scope("catalog:read"))
        self.assertTrue(self.oauth_client.allows_grant_type(OAUTH_DEVICE_CODE_GRANT))
        self.assertTrue(self.oauth_client.allows_grant_type(OAUTH_REFRESH_TOKEN_GRANT))

        with self.assertRaisesRegex(ValueError, "public OAuth clients only"):
            OAuthClient.register_public_client(
                name="Confidential client",
                client_type="confidential",
            )
        with self.assertRaisesRegex(ValueError, "supported scopes"):
            OAuthClient.register_public_client(
                name="Overprivileged client",
                allowed_scopes=["admin:everything"],
            )

    def test_device_endpoint_returns_codes_but_persists_only_digests(self):
        """Device and user secrets are disclosed once and never stored in plaintext."""
        payload = self.issue_device_code()
        authorization = OAuthDeviceAuthorization.objects.get(
            device_code_digest=oauth_token_digest(payload["device_code"])
        )

        self.assertTrue(payload["device_code"].startswith("flp_device_"))
        self.assertEqual(len(payload["user_code"]), 9)
        self.assertNotIn(payload["device_code"], authorization.device_code_digest)
        self.assertNotIn(
            payload["user_code"].replace("-", ""),
            authorization.user_code_digest,
        )
        self.assertEqual(
            authorization.requested_scopes,
            ["catalog:read", "progress:read"],
        )
        self.assertEqual(payload["interval"], authorization.interval)
        self.assertEqual(payload["expires_in"], 600)
        self.assertIn("verification_uri", payload)
        self.assertIn("verification_uri_complete", payload)

    def test_device_endpoint_rejects_scope_not_allowed_for_client(self):
        """A client cannot ask the user to approve permissions outside its registry."""
        response = self.client.post(
            reverse("oauth_device_authorization"),
            {
                "client_id": self.oauth_client.client_id,
                "scope": "catalog:read watchlist:write",
            },
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_scope")
        self.assertFalse(OAuthDeviceAuthorization.objects.exists())

    def test_pending_and_fast_polling_return_device_flow_errors(self):
        """Pending authorisation and excessive polling follow RFC 8628 semantics."""
        payload = self.issue_device_code()

        first = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": payload["device_code"],
            },
        )
        second = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": payload["device_code"],
            },
        )

        self.assertEqual(first.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(first.json()["error"], "authorization_pending")
        self.assertEqual(second.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(second.json()["error"], "slow_down")
        authorization = OAuthDeviceAuthorization.objects.get(
            device_code_digest=oauth_token_digest(payload["device_code"])
        )
        self.assertEqual(authorization.interval, 10)

    def test_approved_device_exchange_issues_scoped_integration_token(self):
        """Successful OAuth access tokens reuse IntegrationToken enforcement."""
        device, token_payload = self.approve_and_exchange()

        self.assertEqual(token_payload["token_type"], "Bearer")
        self.assertEqual(token_payload["expires_in"], 3600)
        self.assertEqual(token_payload["scope"], "catalog:read progress:read")
        self.assertTrue(token_payload["access_token"].startswith("flp_"))
        self.assertTrue(token_payload["refresh_token"].startswith("flp_refresh_"))

        user, integration_token = authenticate_token(token_payload["access_token"])
        self.assertEqual(user, self.user)
        self.assertIsInstance(integration_token, IntegrationToken)
        self.assertEqual(integration_token.client_identifier, self.oauth_client.client_id)
        self.assertEqual(
            integration_token.scopes,
            ["catalog:read", "progress:read"],
        )

        refresh_token = OAuthRefreshToken.objects.get(
            token_digest=oauth_token_digest(token_payload["refresh_token"])
        )
        self.assertEqual(refresh_token.user, self.user)
        self.assertEqual(refresh_token.client, self.oauth_client)
        self.assertEqual(refresh_token.access_token, integration_token)
        self.assertEqual(
            refresh_token.scopes,
            ["catalog:read", "progress:read"],
        )

        replay = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": device["device_code"],
            },
        )
        self.assertEqual(replay.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(replay.json()["error"], "invalid_grant")

    def test_refresh_rotates_secret_and_replay_revokes_successor_family(self):
        """Replay detection invalidates descendants without allowing scope growth."""
        _device, token_payload = self.approve_and_exchange()
        old_refresh = OAuthRefreshToken.objects.get(
            token_digest=oauth_token_digest(token_payload["refresh_token"])
        )

        refresh_response = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": token_payload["refresh_token"],
                "scope": "catalog:read",
            },
        )

        self.assertEqual(refresh_response.status_code, HTTP.OK)
        refreshed_payload = refresh_response.json()
        self.assertNotEqual(
            refreshed_payload["refresh_token"],
            token_payload["refresh_token"],
        )
        self.assertEqual(refreshed_payload["scope"], "catalog:read")

        successor = OAuthRefreshToken.objects.get(
            token_digest=oauth_token_digest(refreshed_payload["refresh_token"])
        )
        old_refresh.refresh_from_db()
        self.assertIsNotNone(old_refresh.revoked_at)
        self.assertEqual(old_refresh.replaced_by_id, successor.pk)

        _user, refreshed_access = authenticate_token(refreshed_payload["access_token"])
        self.assertEqual(refreshed_access.scopes, ["catalog:read"])

        broaden = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": refreshed_payload["refresh_token"],
                "scope": "catalog:read progress:read",
            },
        )
        self.assertEqual(broaden.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(broaden.json()["error"], "invalid_scope")

        replay = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": token_payload["refresh_token"],
            },
        )
        self.assertEqual(replay.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(replay.json()["error"], "invalid_grant")

        successor.refresh_from_db()
        self.assertIsNotNone(successor.revoked_at)
        with self.assertRaises(AuthenticationFailed):
            authenticate_token(refreshed_payload["access_token"])

        successor_reuse = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": refreshed_payload["refresh_token"],
            },
        )
        self.assertEqual(successor_reuse.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(successor_reuse.json()["error"], "invalid_grant")

    def test_refresh_replay_does_not_revoke_independent_grant(self):
        """Replay containment stays within the compromised rotation family."""
        _first_device, first_payload = self.approve_and_exchange()
        _second_device, second_payload = self.approve_and_exchange()

        rotated = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": first_payload["refresh_token"],
            },
        )
        self.assertEqual(rotated.status_code, HTTP.OK)

        replay = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": first_payload["refresh_token"],
            },
        )
        self.assertEqual(replay.status_code, HTTP.BAD_REQUEST)

        user, second_access = authenticate_token(second_payload["access_token"])
        self.assertEqual(user, self.user)
        self.assertIsNone(second_access.revoked_at)

        second_refresh = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": second_payload["refresh_token"],
            },
        )
        self.assertEqual(second_refresh.status_code, HTTP.OK)

    def test_revocation_endpoint_invalidates_refresh_family(self):
        """Revoking any refresh credential kills its full rotation lineage."""
        _device, token_payload = self.approve_and_exchange()
        rotated = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": token_payload["refresh_token"],
            },
        )
        self.assertEqual(rotated.status_code, HTTP.OK)
        rotated_payload = rotated.json()

        response = self.client.post(
            reverse("oauth_revoke"),
            {
                "client_id": self.oauth_client.client_id,
                "token": token_payload["refresh_token"],
            },
        )

        self.assertEqual(response.status_code, HTTP.OK)
        refresh_tokens = OAuthRefreshToken.objects.filter(
            client=self.oauth_client,
            user=self.user,
        )
        self.assertEqual(refresh_tokens.count(), 2)
        self.assertFalse(refresh_tokens.filter(revoked_at__isnull=True).exists())
        with self.assertRaises(AuthenticationFailed):
            authenticate_token(token_payload["access_token"])
        with self.assertRaises(AuthenticationFailed):
            authenticate_token(rotated_payload["access_token"])

    def test_revocation_endpoint_invalidates_access_token(self):
        """Revoking a raw access token invalidates it without a server error."""
        _device, token_payload = self.approve_and_exchange()

        response = self.client.post(
            reverse("oauth_revoke"),
            {
                "client_id": self.oauth_client.client_id,
                "token": token_payload["access_token"],
            },
        )

        self.assertEqual(response.status_code, HTTP.OK)
        with self.assertRaises(AuthenticationFailed):
            authenticate_token(token_payload["access_token"])

        refresh = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": token_payload["refresh_token"],
            },
        )
        self.assertEqual(refresh.status_code, HTTP.OK)

    def test_connected_applications_page_and_revocation_are_user_isolated(self):
        """Settings expose OAuth grants and revoke only the current user's access."""
        _device, token_payload = self.approve_and_exchange()
        other_token, _other_raw = IntegrationToken.generate(
            user=self.other_user,
            name="Other OAuth grant",
            client_identifier=self.oauth_client.client_id,
            scopes=["catalog:read"],
        )

        page = self.client.get(reverse("oauth_applications"))
        self.assertEqual(page.status_code, HTTP.OK)
        self.assertContains(page, "Kodi Living Room")
        self.assertContains(page, "Catalog Read")

        revoke = self.client.post(
            reverse(
                "oauth_revoke_application",
                args=(self.oauth_client.client_id,),
            )
        )
        self.assertRedirects(revoke, reverse("oauth_applications"))

        own_access = IntegrationToken.objects.get(
            token_digest=oauth_token_digest(token_payload["access_token"])
        )
        own_access.refresh_from_db()
        other_token.refresh_from_db()
        self.assertIsNotNone(own_access.revoked_at)
        self.assertIsNone(other_token.revoked_at)

    def test_metadata_publishes_device_refresh_and_scope_contract(self):
        """Discovery metadata advertises exactly the supported public-client surface."""
        response = self.client.get(reverse("oauth_authorization_server_metadata"))

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["token_endpoint_auth_methods_supported"], ["none"])
        self.assertIn(OAUTH_DEVICE_CODE_GRANT, payload["grant_types_supported"])
        self.assertIn(OAUTH_REFRESH_TOKEN_GRANT, payload["grant_types_supported"])
        self.assertIn("catalog:read", payload["scopes_supported"])
        self.assertTrue(
            payload["device_authorization_endpoint"].endswith(
                reverse("oauth_device_authorization")
            )
        )
        self.assertTrue(payload["token_endpoint"].endswith(reverse("oauth_token")))
        self.assertTrue(payload["revocation_endpoint"].endswith(reverse("oauth_revoke")))
