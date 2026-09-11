# FORK: scope enforcement for scoped third-party credentials (Nuvio programme A0).
"""Verify that declared token scopes are actually enforced at the API boundary.

The map in ``api.scopes`` is only a control if every routed view is covered and
an unmapped view is denied. :class:`ScopeMapCoverageTests` is what stops a new
endpoint from quietly becoming reachable by every scoped token.
"""

from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.urls import get_resolver
from django.utils import timezone
from rest_framework.views import APIView

from api import scopes
from api.authentication import LAST_USED_WRITE_INTERVAL, HasScope
from integrations.models import DEFAULT_INTEGRATION_SCOPES, IntegrationToken

from .base import FloppyApiTestCase

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def routed_api_views():
    """Yield (view class, allowed methods) for every DRF view in the URLconf."""
    seen = {}

    def walk(resolver):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern)
                continue
            callback = pattern.callback
            view_class = getattr(callback, "cls", None) or getattr(
                callback,
                "view_class",
                None,
            )
            if view_class is None or not issubclass(view_class, APIView):
                continue
            key = f"{view_class.__module__}.{view_class.__name__}"
            methods = {
                method.upper()
                for method in HTTP_METHODS
                if hasattr(view_class, method)
            }
            seen.setdefault(key, set()).update(methods)

    walk(get_resolver())
    return seen


class ScopeMapCoverageTests(FloppyApiTestCase):
    """The scope map must stay exhaustive over the routed API surface."""

    def test_every_routed_view_and_method_is_mapped(self):
        """A routed view or method missing from the map fails the build."""
        missing = []
        for key, methods in routed_api_views().items():
            mapped = scopes.VIEW_SCOPES.get(key)
            if mapped is None:
                missing.append(f"{key} (whole view)")
                continue
            missing.extend(
                [f"{key}.{method}" for method in sorted(methods - set(mapped))],
            )

        self.assertEqual(
            missing,
            [],
            "Add these to api.scopes.VIEW_SCOPES; unmapped endpoints are denied "
            "to every scoped token:\n" + "\n".join(missing),
        )

    def test_map_has_no_entries_for_unrouted_views(self):
        """A stale map entry means a route was removed without a map update."""
        routed = set(routed_api_views())
        stale = sorted(set(scopes.VIEW_SCOPES) - routed)
        self.assertEqual(stale, [])

    def test_every_mapped_scope_is_in_the_vocabulary(self):
        """A typo in a scope name would silently deny every token."""
        sentinels = {scopes.ANY_SCOPE, scopes.NEVER}
        unknown = sorted(
            {
                scope
                for mapped in scopes.VIEW_SCOPES.values()
                for scope in mapped.values()
                if scope not in scopes.ALL_SCOPES and scope not in sentinels
            },
        )
        self.assertEqual(unknown, [])

    def test_tracking_preset_matches_the_default_token_scopes(self):
        """The documented preset and the minted default must not drift apart."""
        self.assertEqual(
            list(scopes.TRACKING_PRESET),
            list(DEFAULT_INTEGRATION_SCOPES),
        )
        self.assertTrue(set(DEFAULT_INTEGRATION_SCOPES) <= scopes.ALL_SCOPES)


class ScopeEnforcementTests(FloppyApiTestCase):
    """Scoped tokens reach only what their scopes name."""

    def setUp(self):
        """Mint tokens with narrow scopes."""
        super().setUp()
        self.read_token, self.read_raw = IntegrationToken.generate(
            user=self.user1,
            name="read only",
            scopes=["watchlist:read"],
        )
        self.progress_token, self.progress_raw = IntegrationToken.generate(
            user=self.user1,
            name="progress only",
            scopes=["progress:read", "progress:write"],
        )

    def headers(self, raw):
        """Return request headers authenticating with ``raw``."""
        return {"HTTP_X_API_KEY": raw}

    def test_granted_scope_is_allowed(self):
        """A token holding watchlist:read may read the collection."""
        response = self.client.get(
            "/api/v1/collection/",
            **self.headers(self.read_raw),
        )
        self.assertEqual(response.status_code, HTTP.OK)

    def test_missing_scope_is_denied(self):
        """The same token may not write, because it lacks watchlist:write."""
        response = self.client.post(
            "/api/v1/collection/",
            {"media_type": "movie", "source": "tmdb", "media_id": "701"},
            format="json",
            **self.headers(self.read_raw),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_scope_is_resolved_per_method_on_one_view(self):
        """GET and PUT on playback progress take different scopes."""
        read_only, raw = IntegrationToken.generate(
            user=self.user1,
            name="progress read",
            scopes=["progress:read"],
        )
        self.assertEqual(read_only.scopes, ["progress:read"])

        allowed = self.client.get("/api/v1/playback/progress/", **self.headers(raw))
        self.assertEqual(allowed.status_code, HTTP.OK)

        denied = self.client.put(
            "/api/v1/playback/progress/",
            {"items": []},
            format="json",
            **self.headers(raw),
        )
        self.assertEqual(denied.status_code, HTTP.FORBIDDEN)

    def test_cross_domain_scope_does_not_leak(self):
        """A progress token cannot read the collection."""
        response = self.client.get(
            "/api/v1/collection/",
            **self.headers(self.progress_raw),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_wildcard_scope_reaches_mapped_endpoints(self):
        """'*' remains a full grant for mapped endpoints."""
        _, raw = IntegrationToken.generate(
            user=self.user1,
            name="wildcard",
            scopes=["*"],
        )
        response = self.client.get("/api/v1/collection/", **self.headers(raw))
        self.assertEqual(response.status_code, HTTP.OK)

    def test_token_rotation_is_denied_to_every_scoped_token(self):
        """A scoped token must not be able to mint an unscoped one."""
        _, raw = IntegrationToken.generate(
            user=self.user1,
            name="wildcard",
            scopes=["*"],
        )
        response = self.client.post(
            "/api/v1/user/token/regenerate/",
            **self.headers(raw),
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_token_rotation_still_works_for_the_legacy_token(self):
        """The account token keeps full access, including rotation."""
        response = self.client.post(
            "/api/v1/user/token/regenerate/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)

    def test_legacy_token_keeps_full_access(self):
        """Legacy User.token requests carry no scopes and are not restricted."""
        response = self.client.get("/api/v1/collection/", **self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)

    def test_default_preset_covers_the_tracking_flows(self):
        """A default-preset token can scrobble, resume, and change saved state."""
        _, raw = IntegrationToken.generate(user=self.user1, name="tracking client")

        self.assertEqual(
            self.client.get(
                "/api/v1/playback/progress/",
                **self.headers(raw),
            ).status_code,
            HTTP.OK,
        )
        self.assertEqual(
            self.client.get("/api/v1/collection/", **self.headers(raw)).status_code,
            HTTP.OK,
        )
        self.assertEqual(
            self.client.get("/api/v1/discover/", **self.headers(raw)).status_code,
            HTTP.OK,
        )

    def test_default_preset_does_not_reach_other_domains(self):
        """The tracking preset grants nothing outside tracking."""
        _, raw = IntegrationToken.generate(user=self.user1, name="tracking client")

        for path in (
            "/api/v1/music/artists/",
            "/api/v1/podcasts/shows/",
            "/api/v1/user/preferences/",
            "/api/v1/export/csv/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path, **self.headers(raw))
                self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_unmapped_view_is_denied(self):
        """An endpoint absent from the map is denied, not allowed by default."""

        class UnmappedView(APIView):
            """A view the map does not know about."""

        request = self.client.get("/api/v1/collection/", **self.headers(self.read_raw))
        permission = HasScope()
        request.wsgi_request.user = self.user1
        request.wsgi_request.auth = self.read_token
        self.assertFalse(
            permission.has_permission(request.wsgi_request, UnmappedView()),
        )


class LastUsedTrackingTests(FloppyApiTestCase):
    """Token use is recorded, but not on every request."""

    def test_first_use_records_a_timestamp(self):
        """last_used_at is null until the token is used."""
        token, raw = IntegrationToken.generate(user=self.user1, name="client")
        self.assertIsNone(token.last_used_at)

        self.client.get("/api/v1/collection/", HTTP_X_API_KEY=raw)

        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    def test_recent_use_does_not_write_again(self):
        """A second request inside the interval leaves the row untouched."""
        token, raw = IntegrationToken.generate(user=self.user1, name="client")
        self.client.get("/api/v1/collection/", HTTP_X_API_KEY=raw)
        token.refresh_from_db()
        first = token.last_used_at

        self.client.get("/api/v1/collection/", HTTP_X_API_KEY=raw)
        token.refresh_from_db()
        self.assertEqual(token.last_used_at, first)

    def test_use_after_the_interval_writes_again(self):
        """Once the interval has passed the timestamp advances."""
        token, raw = IntegrationToken.generate(user=self.user1, name="client")
        stale = timezone.now() - LAST_USED_WRITE_INTERVAL - timedelta(seconds=1)
        IntegrationToken.objects.filter(pk=token.pk).update(last_used_at=stale)

        self.client.get("/api/v1/collection/", HTTP_X_API_KEY=raw)

        token.refresh_from_db()
        self.assertGreater(token.last_used_at, stale)
