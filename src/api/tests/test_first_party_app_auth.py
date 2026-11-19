"""The built-in Floppy app's device-flow token manages the account like a session.

Only the server-defined first-party client gets the full-account marker, and
only through a device grant the person approved with the full-access wording.
Every other token keeps today's restrictions.
"""

import dataclasses
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from app.providers import credentials
from integrations.models import IntegrationToken
from integrations.oauth_models import (
    OAUTH_DEVICE_CODE_GRANT,
    OAUTH_REFRESH_TOKEN_GRANT,
    OAuthClient,
)
from integrations.oauth_scope_info import FIRST_PARTY_CLIENT_ID, FULL_ACCOUNT_SCOPE

SCOPE = "catalog:read progress:read"
# An invalid bearer token is refused with 403 (BearerAuthentication sends no
# WWW-Authenticate header), the same as for every other token.
REFUSED = (HTTP.UNAUTHORIZED, HTTP.FORBIDDEN)
MARKER_WORDING = "Approving signs the Floppy app into your account with full access."


class FirstPartyAppAuthTests(APITestCase):
    """Full account access for the first-party app, and for nothing else."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="social-only", password=None
        )
        self.registered = OAuthClient.register_public_client(
            name="Floppy app", allowed_scopes=["catalog:read", "progress:read"]
        )

    # -- helpers ------------------------------------------------------------

    def device_code(self, client_id, scope=SCOPE):
        return self.client.post(
            reverse("oauth_device_authorization"),
            {"client_id": client_id, "scope": scope},
        )

    def approve(self, user_code, user=None):
        self.client.force_login(user or self.user)
        page = self.client.post(
            reverse("oauth_device"), {"user_code": user_code, "action": "approve"}
        )
        self.client.logout()
        return page

    def exchange(self, client_id, device_code):
        return self.client.post(
            reverse("oauth_token"),
            {
                "client_id": client_id,
                "grant_type": OAUTH_DEVICE_CODE_GRANT,
                "device_code": device_code,
            },
        )

    def sign_in(self, client_id=FIRST_PARTY_CLIENT_ID, user=None, scope=SCOPE):
        device = self.device_code(client_id, scope)
        self.assertEqual(device.status_code, HTTP.OK, device.content)
        device = device.json()
        self.approve(device["user_code"], user)
        token = self.exchange(client_id, device["device_code"])
        self.assertEqual(token.status_code, HTTP.OK, token.content)
        return token.json()

    def refresh(self, client_id, refresh_token, **extra):
        return self.client.post(
            reverse("oauth_token"),
            {
                "client_id": client_id,
                "grant_type": OAUTH_REFRESH_TOKEN_GRANT,
                "refresh_token": refresh_token,
                **extra,
            },
        )

    @staticmethod
    def bearer(pair):
        return {"HTTP_AUTHORIZATION": f"Bearer {pair['access_token']}"}

    def never_routes(self):
        return (
            ("get", reverse("api_settings_user_catalog_grants")),
            ("get", reverse("api_settings_user_account")),
            ("get", reverse("api_settings_user_o_auth_applications")),
            ("get", reverse("api_playback_home_cards")),
        )

    def save_credentials(self, headers):
        spec = dataclasses.replace(credentials.get_spec("tmdb"), validator=None)
        with patch("app.providers.credentials.get_spec", return_value=spec):
            return self.client.put(
                reverse("api_provider_credentials", args=("tmdb",)),
                {"scope": "personal", "values": {"api_key": "first-party-key"}},
                format="json",
                **headers,
            )

    # -- the first-party token ----------------------------------------------

    def test_first_party_token_carries_the_marker_and_reaches_never_routes(self):
        pair = self.sign_in()
        self.assertIn(FULL_ACCOUNT_SCOPE, pair["scope"].split())
        for method, url in self.never_routes():
            response = getattr(self.client, method)(url, **self.bearer(pair))
            self.assertEqual(response.status_code, HTTP.OK, (url, response.content))

        response = self.save_credentials(self.bearer(pair))
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.assertTrue(response.json()["ok"])

    def test_credential_disclosure_and_issuance_require_a_session(self):
        pair = self.sign_in()
        routes = (
            ("get", "api_settings_user_token", None),
            ("head", "api_settings_user_token", None),
            ("get", "api_calendar_links", None),
            ("get", "api_settings_user_rss", None),
            ("post", "api_user_token_regenerate", {}),
            ("post", "api_settings_user_integration_tokens", {"name": "Phone", "scopes": ["user:read"]}),
            ("post", "api_settings_user_catalog_grants", {"name": "TV"}),
        )
        original_token = self.user.token
        for method, route, payload in routes:
            with self.subTest(route=route):
                response = getattr(self.client, method)(
                    reverse(route), payload, format="json", **self.bearer(pair)
                )
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.user.refresh_from_db()
        self.assertEqual(self.user.token, original_token)
        self.assertFalse(IntegrationToken.objects.filter(user=self.user, client_identifier="").exists())
        self.client.force_login(self.user)
        for method, route, payload in routes:
            with self.subTest(session_route=route):
                response = getattr(self.client, method)(reverse(route), payload, format="json")
                self.assertIn(response.status_code, (HTTP.OK, HTTP.CREATED), response.content)
        self.client.logout()

    def test_provider_guides_do_not_disclose_permanent_credentials_to_bearer(self):
        from integrations.models import CatalogGrant

        pair = self.sign_in()
        grant, grant_secret = CatalogGrant.generate(user=self.user, name="Existing install")
        for slug in ("plex", "jellyfin", "emby", "kodi", "seerr", "stremio"):
            for tab in ("connection", "tracking"):
                with self.subTest(slug=slug, tab=tab):
                    response = self.client.get(
                        reverse("api_provider_detail", args=(slug,)), {"tab": tab}, **self.bearer(pair),
                    )
                    if response.status_code == HTTP.BAD_REQUEST:
                        continue  # Some providers expose no tracking tab.
                    self.assertEqual(response.status_code, HTTP.OK, response.content)
                    self.assertNotIn(self.user.token, response.content.decode())
                    self.assertNotIn(grant_secret, response.content.decode())
                    if response.json()["guidesSessionRequired"]:
                        self.assertEqual(response.json()["guides"], [])
                        self.assertEqual(response.json()["guideCopy"], {})
        self.client.force_login(self.user)
        response = self.client.get(reverse("api_provider_detail", args=("jellyfin",)), {"tab": "connection"})
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertIn(self.user.token, response.json()["guideCopy"]["webhook"])
        self.client.logout()
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)

    def test_bearer_cannot_approve_an_independent_oauth_grant(self):
        pair = self.sign_in()
        device = self.device_code(self.registered.client_id).json()
        url = reverse("api_connection_device")
        lookup = self.client.get(url, {"user_code": device["user_code"]}, **self.bearer(pair))
        self.assertEqual(lookup.status_code, HTTP.OK)
        response = self.client.post(url, {"user_code": device["user_code"], "action": "approve"}, **self.bearer(pair))
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        response = self.exchange(self.registered.client_id, device["device_code"])
        self.assertEqual(response.json()["error"], "authorization_pending")
        from integrations.oauth_models import OAuthDeviceAuthorization

        pending = OAuthDeviceAuthorization.for_user_code(device["user_code"])
        pending.last_polled_at = None
        pending.save(update_fields=["last_polled_at"])
        self.client.force_login(self.user)
        response = self.client.post(url, {"user_code": device["user_code"], "action": "approve"})
        self.assertEqual(response.status_code, HTTP.OK)
        self.client.logout()
        self.assertEqual(self.exchange(self.registered.client_id, device["device_code"]).status_code, HTTP.OK)

    def test_account_bearer_cannot_create_or_read_authenticator_credentials(self):
        pair = self.sign_in()
        url = reverse("api_settings_user_account")
        response = self.client.get(url, **self.bearer(pair))
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertTrue(response.json()["credentialSessionRequired"])
        self.assertEqual(response.json()["authenticator"]["secret"], "")
        self.user.refresh_from_db()
        self.assertFalse(self.user.authenticator_secret)
        for payload in (
            {"new_password1": "password-one", "new_password2": "password-one"},
            *({"action": action} for action in ("start_authenticator_setup", "enable_authenticator", "disable_authenticator", "regenerate_recovery_codes")),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(url, payload, **self.bearer(pair)).status_code, HTTP.FORBIDDEN)
        self.client.force_login(self.user)
        session = self.client.get(url)
        self.assertTrue(session.json()["authenticator"]["secret"])
        secret = session.json()["authenticator"]["secret"]
        self.client.logout()
        response = self.client.get(url, **self.bearer(pair))
        self.assertNotIn(secret, response.content.decode())
        self.assertEqual(response.json()["freshRecoveryCodes"], [])

    def test_full_access_admin_cannot_mint_or_promote_password_accounts(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        other = get_user_model().objects.create_user(username="member", password="original")
        pair = self.sign_in()
        routes = (
            ("post", reverse("api_settings_managed_users"), {"username": "persistent-admin", "password": "known"}),
            ("patch", reverse("api_settings_managed_user_detail", args=(other.id,)), {"is_superuser": True}),
            ("post", reverse("api_settings_managed_user_password", args=(other.id,)), {"password": "changed-password"}),
        )
        for method, url, payload in routes:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, payload, format="json", **self.bearer(pair))
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        other.refresh_from_db()
        self.assertFalse(other.is_superuser)
        self.assertTrue(other.check_password("original"))
        self.assertFalse(get_user_model().objects.filter(username="persistent-admin").exists())
        self.client.force_login(self.user)
        response = self.client.post(reverse("api_settings_managed_user_password", args=(other.id,)), {"password": "changed-password"}, format="json")
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        other.refresh_from_db()
        self.assertTrue(other.check_password("changed-password"))
        self.client.logout()

    def test_full_access_can_list_and_revoke_tokens_and_grants(self):
        from integrations.models import CatalogGrant

        pair = self.sign_in()
        token, _raw = IntegrationToken.generate(user=self.user, name="Phone", scopes=["user:read"])
        grant, _raw = CatalogGrant.generate(user=self.user, name="TV")
        for listing, detail, pk in (
            ("api_settings_user_integration_tokens", "api_settings_user_integration_token_detail", token.id),
            ("api_settings_user_catalog_grants", "api_settings_user_catalog_grant_detail", grant.id),
        ):
            response = self.client.get(reverse(listing), **self.bearer(pair))
            self.assertEqual(response.status_code, HTTP.OK)
            self.assertEqual([row["id"] for row in response.json()["results"]], [pk])
            response = self.client.delete(reverse(detail, args=(pk,)), **self.bearer(pair))
            self.assertEqual(response.status_code, HTTP.OK)
        token.refresh_from_db()
        grant.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertIsNotNone(grant.revoked_at)

    def test_account_route_works_with_the_bearer_token(self):
        pair = self.sign_in()
        response = self.client.post(
            reverse("api_settings_user_account"),
            {"username": "renamed"},
            **self.bearer(pair),
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "renamed")
        self.assertFalse(response.json()["user"]["hasUsablePassword"])

    def test_registered_app_with_the_same_scopes_is_refused(self):
        pair = self.sign_in(self.registered.client_id)
        self.assertNotIn(FULL_ACCOUNT_SCOPE, pair["scope"].split())
        for method, url in self.never_routes():
            response = getattr(self.client, method)(url, **self.bearer(pair))
            self.assertEqual(response.status_code, HTTP.FORBIDDEN, url)
        self.assertEqual(self.save_credentials(self.bearer(pair)).status_code, HTTP.FORBIDDEN)

    def test_settings_token_with_every_scope_is_still_refused(self):
        _token, raw = IntegrationToken.generate(
            user=self.user, name="all", scopes=["*"]
        )
        response = self.client.get(
            reverse("api_settings_user_account"), HTTP_AUTHORIZATION=f"Bearer {raw}"
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    # -- nobody else can obtain the marker ----------------------------------

    def test_marker_cannot_be_requested(self):
        for client_id in (FIRST_PARTY_CLIENT_ID, self.registered.client_id):
            response = self.device_code(client_id, f"catalog:read {FULL_ACCOUNT_SCOPE}")
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, client_id)
            self.assertEqual(response.json()["error"], "invalid_scope")

    def test_claiming_the_first_party_id_with_another_clients_grant_fails(self):
        device = self.device_code(self.registered.client_id).json()
        self.approve(device["user_code"])
        response = self.exchange(FIRST_PARTY_CLIENT_ID, device["device_code"])
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_grant")

        # The registered client's own exchange never carries the marker.
        pair = self.exchange(self.registered.client_id, device["device_code"]).json()
        self.assertNotIn(FULL_ACCOUNT_SCOPE, pair["scope"].split())
        response = self.refresh(FIRST_PARTY_CLIENT_ID, pair["refresh_token"])
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_registration_cannot_mint_the_first_party_id(self):
        response = self.client.post(
            reverse("oauth_register"), {"client_name": FIRST_PARTY_CLIENT_ID}
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertNotEqual(response.json()["client_id"], FIRST_PARTY_CLIENT_ID)

    def test_marker_needs_both_the_client_and_the_scope(self):
        self.client.force_login(self.user)
        made = self.client.post(
            reverse("api_settings_user_integration_tokens"),
            {"name": "sneaky", "scopes": [FULL_ACCOUNT_SCOPE]},
            format="json",
        )
        self.client.logout()
        self.assertEqual(made.status_code, HTTP.BAD_REQUEST)

        for client_identifier, scopes in (
            ("", [FULL_ACCOUNT_SCOPE]),
            (FIRST_PARTY_CLIENT_ID, ["catalog:read"]),
            (self.registered.client_id, [FULL_ACCOUNT_SCOPE]),
        ):
            _token, raw = IntegrationToken.generate(
                user=self.user,
                name="forged",
                scopes=scopes,
                client_identifier=client_identifier,
            )
            response = self.client.get(
                reverse("api_settings_user_account"), HTTP_AUTHORIZATION=f"Bearer {raw}"
            )
            self.assertEqual(response.status_code, HTTP.FORBIDDEN, client_identifier)

    # -- refresh, revocation and the kill switch ----------------------------

    def test_refresh_keeps_the_marker_without_escalating(self):
        pair = self.sign_in()
        refreshed = self.refresh(FIRST_PARTY_CLIENT_ID, pair["refresh_token"])
        self.assertEqual(refreshed.status_code, HTTP.OK, refreshed.content)
        refreshed = refreshed.json()
        self.assertIn(FULL_ACCOUNT_SCOPE, refreshed["scope"].split())
        old = self.client.get(reverse("api_settings_user_account"), **self.bearer(pair))
        self.assertIn(old.status_code, REFUSED)
        new = self.client.get(reverse("api_settings_user_account"), **self.bearer(refreshed))
        self.assertEqual(new.status_code, HTTP.OK)

        # Narrowing drops the marker; asking for more than was granted fails.
        narrowed = self.refresh(
            FIRST_PARTY_CLIENT_ID, refreshed["refresh_token"], scope="catalog:read"
        ).json()
        self.assertEqual(narrowed["scope"], "catalog:read")
        widened = self.refresh(
            FIRST_PARTY_CLIENT_ID,
            narrowed["refresh_token"],
            scope=f"catalog:read {FULL_ACCOUNT_SCOPE}",
        )
        self.assertEqual(widened.json()["error"], "invalid_scope")

    def test_registered_refresh_cannot_add_the_marker(self):
        pair = self.sign_in(self.registered.client_id)
        response = self.refresh(
            self.registered.client_id,
            pair["refresh_token"],
            scope=f"catalog:read {FULL_ACCOUNT_SCOPE}",
        )
        self.assertNotIn(FULL_ACCOUNT_SCOPE, response.json().get("scope", ""))

    def test_revoking_the_app_cuts_access_and_refresh(self):
        pair = self.sign_in()
        listed = self.client.get(
            reverse("api_settings_user_o_auth_applications"), **self.bearer(pair)
        ).json()["results"]
        self.assertEqual(listed[0]["name"], "Floppy app (full access)")
        self.assertEqual(listed[0]["scopes"][0]["label"], "Full account access")

        revoked = self.client.delete(
            reverse(
                "api_settings_user_o_auth_application_detail",
                args=(FIRST_PARTY_CLIENT_ID,),
            ), **self.bearer(pair),
        )
        self.assertEqual(revoked.status_code, HTTP.OK)
        response = self.client.get(reverse("api_settings_user_account"), **self.bearer(pair))
        self.assertIn(response.status_code, REFUSED)
        self.assertEqual(
            self.refresh(FIRST_PARTY_CLIENT_ID, pair["refresh_token"]).json()["error"],
            "invalid_grant",
        )

    def test_deactivated_account_loses_access(self):
        pair = self.sign_in()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.get(reverse("api_settings_user_account"), **self.bearer(pair))
        self.assertIn(response.status_code, REFUSED)

    def test_setting_off_withdraws_full_access(self):
        pair = self.sign_in()
        with override_settings(FLOPPY_APP_FULL_ACCESS=False):
            response = self.client.get(
                reverse("api_settings_user_account"), **self.bearer(pair)
            )
            self.assertEqual(response.status_code, HTTP.FORBIDDEN)
            fresh = self.sign_in()
            self.assertNotIn(FULL_ACCOUNT_SCOPE, fresh["scope"].split())

    # -- consent wording ----------------------------------------------------

    def test_approval_page_states_full_access_only_for_the_first_party_app(self):
        self.client.force_login(self.user)
        first = self.device_code(FIRST_PARTY_CLIENT_ID).json()
        page = self.client.get(reverse("oauth_device"), {"user_code": first["user_code"]})
        self.assertContains(page, MARKER_WORDING)
        self.assertNotContains(page, "Unverified application.")

        other = self.device_code(self.registered.client_id).json()
        page = self.client.get(reverse("oauth_device"), {"user_code": other["user_code"]})
        self.assertContains(page, "Unverified application.")
        self.assertNotContains(page, MARKER_WORDING)

    # -- every other rule still applies -------------------------------------

    def test_demo_account_is_still_refused(self):
        self.user.is_demo = True
        self.user.save(update_fields=["is_demo"])
        pair = self.sign_in()
        self.assertEqual(self.save_credentials(self.bearer(pair)).status_code, HTTP.FORBIDDEN)
        response = self.client.delete(
            reverse(
                "api_settings_user_o_auth_application_detail",
                args=(FIRST_PARTY_CLIENT_ID,),
            ),
            **self.bearer(pair),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_superuser_routes_still_need_a_superuser(self):
        pair = self.sign_in()
        response = self.client.get(reverse("api_settings_managed_users"), **self.bearer(pair))
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

        admin = get_user_model().objects.create_superuser(username="admin", password=None)
        pair = self.sign_in(user=admin)
        response = self.client.get(reverse("api_settings_managed_users"), **self.bearer(pair))
        self.assertEqual(response.status_code, HTTP.OK)

    def test_other_users_data_stays_isolated(self):
        other = get_user_model().objects.create_user(username="someone-else")
        pair = self.sign_in()
        token = self.client.get(reverse("api_settings_user_account"), **self.bearer(pair))
        self.assertEqual(token.json()["user"]["username"], self.user.username)
        self.assertNotEqual(token.json()["user"]["username"], other.username)
