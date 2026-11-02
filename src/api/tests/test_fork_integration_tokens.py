# FORK: tests for Scoped Third-Party Credentials (PR1 - #636).
import hashlib
from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import Mock

from django.utils import timezone

from api.authentication import (
    HasScope,
)
from app.models import PlaybackProgress
from integrations.models import DEFAULT_INTEGRATION_SCOPES, IntegrationToken

from .base import FloppyApiTestCase


class IntegrationTokenModelTests(FloppyApiTestCase):
    """Verify IntegrationToken generation, digest hashing, and scope validation."""

    def test_token_generation_stores_digest_only(self):
        """Raw token string must never be stored in the database."""
        token, raw_token = IntegrationToken.generate(
            user=self.user1,
            name="Nuvio Living Room",
            client_identifier="nuvio-tv",
        )

        self.assertTrue(raw_token.startswith("flp_"))
        self.assertEqual(token.token_prefix, raw_token[:12])

        expected_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        self.assertEqual(token.token_digest, expected_digest)
        self.assertEqual(token.name, "Nuvio Living Room")
        self.assertEqual(token.client_identifier, "nuvio-tv")
        self.assertEqual(token.scopes, DEFAULT_INTEGRATION_SCOPES)
        self.assertTrue(token.is_valid())

        # Verify plaintext token is not in any DB column
        refreshed = IntegrationToken.objects.get(pk=token.pk)
        self.assertNotIn(raw_token, refreshed.token_digest)
        self.assertNotIn(raw_token, refreshed.name)
        self.assertNotIn(raw_token, refreshed.client_identifier)
        self.assertEqual(str(token), f"IntegrationToken(Nuvio Living Room, {self.user1.username})")

    def test_custom_scopes_and_expiration(self):
        """Custom scopes and expiration timestamps are respected."""
        expires = timezone.now() + timedelta(days=30)
        custom_scopes = ["scrobble:write", "progress:read"]

        token, raw = IntegrationToken.generate(
            user=self.user1,
            name="Restricted Client",
            scopes=custom_scopes,
            expires_at=expires,
        )

        self.assertEqual(token.scopes, custom_scopes)
        self.assertEqual(token.expires_at, expires)
        self.assertTrue(token.is_valid())

    def test_has_scope_matching(self):
        """has_scope correctly evaluates exact matches and wildcards."""
        token, _ = IntegrationToken.generate(
            user=self.user1,
            name="Scoped",
            scopes=["scrobble:write", "progress:read"],
        )
        self.assertTrue(token.has_scope("scrobble:write"))
        self.assertTrue(token.has_scope("progress:read"))
        self.assertFalse(token.has_scope("progress:write"))
        self.assertFalse(token.has_scope("watchlist:write"))

        # Wildcard scope
        wildcard_token, _ = IntegrationToken.generate(
            user=self.user1,
            name="Super",
            scopes=["*"],
        )
        self.assertTrue(wildcard_token.has_scope("scrobble:write"))
        self.assertTrue(wildcard_token.has_scope("any:custom:scope"))

        # Empty scopes
        empty_token, _ = IntegrationToken.generate(
            user=self.user1,
            name="Empty",
            scopes=[],
        )
        self.assertFalse(empty_token.has_scope("scrobble:write"))

    def test_validity_revocation_and_expiration(self):
        """is_valid reflects revocation and expiration states."""
        # Unexpired, unrevoked
        token, _ = IntegrationToken.generate(user=self.user1, name="Valid")
        self.assertTrue(token.is_valid())

        # Future expiration
        token.expires_at = timezone.now() + timedelta(hours=1)
        self.assertTrue(token.is_valid())

        # Past expiration
        token.expires_at = timezone.now() - timedelta(seconds=1)
        self.assertFalse(token.is_valid())

        # Revoked with future expiration
        token.expires_at = timezone.now() + timedelta(hours=1)
        token.revoked_at = timezone.now()
        self.assertFalse(token.is_valid())


class IntegrationTokenAuthHeaderTests(FloppyApiTestCase):
    """Verify authentication across X-API-Key and Authorization headers."""

    def setUp(self):
        super().setUp()
        self.token, self.raw_token = IntegrationToken.generate(
            user=self.user1,
            name="Test Client",
        )

    def test_auth_via_x_api_key(self):
        """API Key authentication works with IntegrationToken."""
        headers = {"HTTP_X_API_KEY": self.raw_token}
        response = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers=headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)

    def test_inactive_user_cannot_authenticate_with_any_token_header(self):
        self.token.scopes = ["*"]
        self.token.save(update_fields=["scopes"])
        self.user1.is_active = False
        self.user1.save(update_fields=["is_active"])
        for raw_token in (self.raw_token, self.user1.token):
            for headers in (
                {"HTTP_X_API_KEY": raw_token},
                {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"},
                {"HTTP_AUTHORIZATION": f"Token {raw_token}"},
            ):
                with self.subTest(
                    headers=list(headers), scoped=raw_token == self.raw_token
                ):
                    response = self.call_api(
                        "get",
                        "api_user_preferences",
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.token.refresh_from_db()
        self.assertIsNone(self.token.last_used_at)

    def test_auth_via_bearer_header(self):
        """Authorization: Bearer header authenticates with IntegrationToken."""
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"}
        response = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers=headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)

    def test_auth_via_token_header(self):
        """Authorization: Token header authenticates with IntegrationToken."""
        headers = {"HTTP_AUTHORIZATION": f"Token {self.raw_token}"}
        response = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers=headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)

    def test_revoked_token_is_rejected(self):
        """Revoked tokens are rejected with 403 Forbidden."""
        self.token.revoked_at = timezone.now()
        self.token.save(update_fields=["revoked_at"])

        # Verify rejection via X-API-Key
        res1 = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_X_API_KEY": self.raw_token},
        )
        self.assertEqual(res1.status_code, HTTP.FORBIDDEN)

        # Verify rejection via Bearer header
        res2 = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"},
        )
        self.assertEqual(res2.status_code, HTTP.FORBIDDEN)

    def test_expired_token_is_rejected(self):
        """Expired tokens are rejected with 403 Forbidden."""
        self.token.expires_at = timezone.now() - timedelta(minutes=5)
        self.token.save(update_fields=["expires_at"])

        response = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_X_API_KEY": self.raw_token},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_invalid_token_strings_rejected(self):
        """Malformed or unknown tokens are rejected."""
        bad_headers = [
            {"HTTP_X_API_KEY": "flp_nonexistent_token_digest_not_found"},
            {"HTTP_X_API_KEY": "random_garbage_string"},
            {"HTTP_X_API_KEY": ""},
            {"HTTP_AUTHORIZATION": "Bearer flp_invalid_token_value"},
        ]
        for header in bad_headers:
            with self.subTest(header=header):
                response = self.call_api(
                    "post",
                    "api_scrobble",
                    payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
                    headers=header,
                )
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_backward_compatibility_legacy_user_token(self):
        """Legacy User.token authenticates via all supported header formats."""
        # Test legacy key in X-API-Key header
        res1 = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_X_API_KEY": self.user1.token},
        )
        self.assertEqual(res1.status_code, HTTP.OK)

        # Test legacy key in Bearer header
        res2 = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_AUTHORIZATION": f"Bearer {self.user1.token}"},
        )
        self.assertEqual(res2.status_code, HTTP.OK)

        # Test legacy key in Token header
        res3 = self.call_api(
            "post",
            "api_scrobble",
            payload={"action": "start", "media_type": "movie", "ids": {"tmdb": "603"}},
            headers={"HTTP_AUTHORIZATION": f"Token {self.user1.token}"},
        )
        self.assertEqual(res3.status_code, HTTP.OK)

    def test_user_isolation_with_integration_token(self):
        """Actions performed with user1's integration token are isolated to user1."""
        movie_item = self.items_by_type["movie"][0]

        res = self.call_api(
            "put",
            "api_playback_progress",
            payload={"media_type": "movie", "ids": {"tmdb": movie_item.media_id}, "position_seconds": 888},
            headers={"HTTP_X_API_KEY": self.raw_token},
        )
        self.assertEqual(res.status_code, HTTP.OK)

        # Progress belongs to user1
        p1 = PlaybackProgress.objects.get(user=self.user1, item=movie_item)
        self.assertEqual(p1.position_seconds, 888)

        # User2 does not have progress
        self.assertFalse(PlaybackProgress.objects.filter(user=self.user2, item=movie_item).exists())


class ScopePermissionTests(FloppyApiTestCase):
    """Test HasScope DRF permission class behavior."""

    def test_has_scope_permission_with_integration_token(self):
        """HasScope allows granted scopes and blocks ungranted scopes."""
        token, _ = IntegrationToken.generate(
            user=self.user1,
            name="Scrobble Only",
            scopes=["scrobble:write"],
        )

        perm = HasScope("scrobble:write")
        perm_denied = HasScope("watchlist:write")

        req = Mock()
        req.user = self.user1
        req.auth = token

        self.assertTrue(perm.has_permission(req, None))
        self.assertFalse(perm_denied.has_permission(req, None))

    def test_has_scope_permission_legacy_token_full_access(self):
        """Legacy token (request.auth is None) passes all scope checks."""
        perm = HasScope("any:restricted:scope")

        req = Mock()
        req.user = self.user1
        req.auth = None

        self.assertTrue(perm.has_permission(req, None))

    def test_has_scope_unauthenticated(self):
        """Unauthenticated requests are denied by HasScope."""
        perm = HasScope("scrobble:write")

        req = Mock()
        req.user = Mock(is_authenticated=False)
        req.auth = None

        self.assertFalse(perm.has_permission(req, None))
