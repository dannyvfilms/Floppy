from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from api.authentication import authenticate_token
from integrations.models import DEFAULT_INTEGRATION_SCOPES, IntegrationToken
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
        cache.clear()
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
        for content_type in ("application/x-www-form-urlencoded", "application/json"):
            with self.subTest(content_type=content_type):
                payload = self.issue_device_code()
                data = {
                    "client_id": self.oauth_client.client_id,
                    "grant_type": OAUTH_DEVICE_CODE_GRANT,
                    "device_code": payload["device_code"],
                }
                if content_type == "application/x-www-form-urlencoded":
                    data = urlencode(data)

                first = self.client.post(
                    reverse("oauth_token"), data, content_type=content_type
                )
                second = self.client.post(
                    reverse("oauth_token"), data, content_type=content_type
                )

                self.assertEqual(first.status_code, HTTP.BAD_REQUEST)
                self.assertEqual(first.json()["error"], "authorization_pending")
                self.assertEqual(second.status_code, HTTP.BAD_REQUEST)
                self.assertEqual(second.json()["error"], "slow_down")
                for response in (first, second):
                    self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(response["Pragma"], "no-cache")
                authorization = OAuthDeviceAuthorization.objects.get(
                    device_code_digest=oauth_token_digest(payload["device_code"])
                )
                self.assertIsNone(authorization.user_id)
                self.assertEqual(authorization.interval, 10)

    def test_expired_device_code_returns_expired_token(self):
        """An expired unapproved code returns an OAuth error, not a server error."""
        payload = self.issue_device_code()
        OAuthDeviceAuthorization.objects.filter(
            device_code_digest=oauth_token_digest(payload["device_code"])
        ).update(expires_at=timezone.now() - timedelta(seconds=1))

        response = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": payload["device_code"],
            },
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["error"], "expired_token")
        self.assertFalse(IntegrationToken.objects.exists())
        self.assertFalse(OAuthRefreshToken.objects.exists())

    def test_denied_device_code_returns_access_denied(self):
        """A user-denied device request cannot be exchanged for credentials."""
        payload = self.issue_device_code()
        authorization = OAuthDeviceAuthorization.objects.get(
            device_code_digest=oauth_token_digest(payload["device_code"])
        )
        authorization.deny(self.user)

        response = self.client.post(
            reverse("oauth_token"),
            {
                "client_id": self.oauth_client.client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": payload["device_code"],
            },
        )

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["error"], "access_denied")
        self.assertFalse(IntegrationToken.objects.exists())
        self.assertFalse(OAuthRefreshToken.objects.exists())

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
        with self.assertRaises(AuthenticationFailed):
            authenticate_token(token_payload["access_token"])

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

    def test_oauth_access_token_is_not_listed_as_manual_app_token(self):
        """OAuth-issued credentials stay out of the manual App tokens list."""
        _device, token_payload = self.approve_and_exchange()
        access_token = IntegrationToken.objects.get(
            token_digest=oauth_token_digest(token_payload["access_token"])
        )

        page = self.client.get(reverse("integrations"))

        self.assertEqual(page.status_code, HTTP.OK)
        self.assertNotContains(page, access_token.token_prefix)

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
        self.assertTrue(
            payload["registration_endpoint"].endswith(reverse("oauth_register"))
        )

    def test_device_authorization_endpoint_is_rate_limited(self):
        """An anonymous caller cannot create unlimited device authorisations."""
        for _ in range(10):
            self.issue_device_code()

        response = self.client.post(
            reverse("oauth_device_authorization"),
            {"client_id": self.oauth_client.client_id},
        )

        self.assertEqual(response.status_code, HTTP.TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["error"], "slow_down")
        self.assertEqual(OAuthDeviceAuthorization.objects.count(), 10)

    def test_issuing_a_device_code_deletes_long_expired_authorizations(self):
        """Expired device authorisations do not accumulate forever."""
        stale, _device_code, _user_code = OAuthDeviceAuthorization.issue(
            client=self.oauth_client,
            requested_scopes=["catalog:read"],
        )
        OAuthDeviceAuthorization.objects.filter(pk=stale.pk).update(
            expires_at=timezone.now() - timedelta(days=2),
        )

        fresh = self.issue_device_code()

        self.assertFalse(OAuthDeviceAuthorization.objects.filter(pk=stale.pk).exists())
        self.assertEqual(OAuthDeviceAuthorization.objects.count(), 1)
        self.assertIn("device_code", fresh)

    def register(self, **data):
        """Post to the registration endpoint as an anonymous app."""
        return self.client.post(reverse("oauth_register"), data)

    def test_app_can_register_itself_and_run_the_whole_flow(self):
        """A brand-new app gets a client ID, a code, and a token after approval."""
        registered = self.register(client_name="  Living   Room TV ")

        self.assertEqual(registered.status_code, HTTP.CREATED)
        payload = registered.json()
        self.assertEqual(payload["client_name"], "Living Room TV")
        self.assertEqual(payload["token_endpoint_auth_method"], "none")
        self.assertIn(OAUTH_DEVICE_CODE_GRANT, payload["grant_types"])

        device = self.client.post(
            reverse("oauth_device_authorization"),
            {"client_id": payload["client_id"], "scope": "catalog:read"},
        ).json()
        self.client.force_login(self.user)
        page = self.client.get(reverse("oauth_device"), {"user_code": device["user_code"]})
        self.assertContains(page, "Living Room TV")
        self.assertContains(page, "Unverified application")
        self.client.post(
            reverse("oauth_device"),
            {"user_code": device["user_code"], "action": "approve"},
        )
        self.client.logout()
        token = self.client.post(
            reverse("oauth_token"),
            {
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "client_id": payload["client_id"],
                "device_code": device["device_code"],
            },
        )
        self.assertEqual(token.status_code, HTTP.OK)
        self.assertEqual(token.json()["scope"], "catalog:read")

    def test_registered_app_gets_list_scopes_only_when_it_asks(self):
        """A registered app may ask for lists, but naming no scope stays the tracking preset."""
        client_id = self.register(client_name="FanFilm").json()["client_id"]

        def requested(**extra):
            response = self.client.post(
                reverse("oauth_device_authorization"),
                {"client_id": client_id, **extra},
            )
            self.assertEqual(response.status_code, HTTP.OK)
            return OAuthDeviceAuthorization.objects.get(
                device_code_digest=oauth_token_digest(response.json()["device_code"])
            ).requested_scopes

        self.assertEqual(requested(), DEFAULT_INTEGRATION_SCOPES)
        self.assertEqual(
            requested(scope="progress:read lists:read lists:write"),
            ["progress:read", "lists:read", "lists:write"],
        )
        self.assertIn("lists:write", self.client.get(reverse("oauth_scope_metadata")).content.decode())

    def test_registration_rejects_missing_and_overlong_names(self):
        """The app must give a name, and a short one."""
        for data in ({}, {"client_name": "   "}, {"client_name": "x" * 61}):
            response = self.register(**data)
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
            self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_registration_is_rate_limited(self):
        """An anonymous caller cannot create unlimited clients."""
        for _ in range(10):
            self.assertEqual(self.register(client_name="App").status_code, HTTP.CREATED)

        response = self.register(client_name="App")

        self.assertEqual(response.status_code, HTTP.TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["error"], "slow_down")

    def test_registering_deletes_old_clients_nobody_signed_in_with(self):
        """Unused registrations disappear after a day; ones with a sign-in stay."""
        self.approve_and_exchange()  # gives self.oauth_client a refresh token
        unused = OAuthClient.register_public_client(name="Unused")
        old = timezone.now() - timedelta(days=2)
        OAuthClient.objects.filter(pk__in=[unused.pk, self.oauth_client.pk]).update(
            created_at=old
        )

        self.register(client_name="New")

        self.assertFalse(OAuthClient.objects.filter(pk=unused.pk).exists())
        self.assertTrue(OAuthClient.objects.filter(pk=self.oauth_client.pk).exists())
        self.assertTrue(OAuthClient.objects.filter(name="New").exists())

    def test_rate_limit_ignores_a_spoofed_header_unless_it_is_the_trusted_one(self):
        """A caller cannot dodge the limit by sending their own X-Real-IP."""
        for index in range(10):
            self.client.post(
                reverse("oauth_register"),
                {"client_name": "App"},
                HTTP_X_REAL_IP=f"10.0.0.{index}",
            )

        spoofed = self.client.post(
            reverse("oauth_register"),
            {"client_name": "App"},
            HTTP_X_REAL_IP="10.0.0.99",
        )
        self.assertEqual(spoofed.status_code, HTTP.TOO_MANY_REQUESTS)

        cache.clear()
        with override_settings(ALLAUTH_TRUSTED_CLIENT_IP_HEADER="X-Real-IP"):
            for index in range(10):
                response = self.client.post(
                    reverse("oauth_register"),
                    {"client_name": "App"},
                    HTTP_X_REAL_IP=f"10.0.1.{index}",
                )
                self.assertEqual(response.status_code, HTTP.CREATED)
            other_caller = self.client.post(
                reverse("oauth_register"),
                {"client_name": "App"},
                HTTP_X_REAL_IP="10.0.1.99",
            )
        self.assertEqual(other_caller.status_code, HTTP.CREATED)

    def test_replay_revokes_a_long_refresh_chain_in_constant_queries(self):
        """Revoking a long rotation lineage does not query once per link."""
        _device, first = self.approve_and_exchange()
        refresh = first["refresh_token"]
        for _ in range(12):
            refreshed = self.client.post(
                reverse("oauth_token"),
                {
                    "client_id": self.oauth_client.client_id,
                    "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                    "refresh_token": refresh,
                },
            ).json()
            refresh = refreshed["refresh_token"]

        with CaptureQueriesContext(connection) as short_chain:
            self.client.post(
                reverse("oauth_revoke"),
                {"client_id": self.oauth_client.client_id, "token": refresh},
            )

        self.assertLess(len(short_chain), 12)
        self.assertFalse(
            OAuthRefreshToken.objects.filter(revoked_at__isnull=True).exists()
        )
