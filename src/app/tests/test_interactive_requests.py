"""Who sets the interactive mark that background maintenance stands back for.

People browse through HTML pages, the web pages' React islands and the Floppy
app. Scrobblers, third-party clients and timer polls must never hold the mark,
or maintenance that skips while it is set would never run.
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from app import interactive_requests
from app.interactive_requests import (
    INTERACTIVE_REQUEST_CACHE_KEY,
    INTERACTIVE_REQUEST_TTL_SECONDS,
    refresh_interactive_mark,
)
from integrations.models import IntegrationToken
from integrations.oauth_scope_info import FIRST_PARTY_CLIENT_ID, FULL_ACCOUNT_SCOPE

JSON = {"HTTP_ACCEPT": "application/json"}
HTML = {"HTTP_ACCEPT": "text/html"}


class InteractiveMarkClassificationTests(TestCase):
    """One case per kind of client, through the real middleware and DRF."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="person", password="pw"
        )
        cls.user.token = "legacy-user-token"
        cls.user.save(update_fields=["token"])
        _, cls.app_token = IntegrationToken.generate(
            cls.user,
            "Floppy app",
            scopes=[FULL_ACCOUNT_SCOPE],
            client_identifier=FIRST_PARTY_CLIENT_ID,
        )
        _, cls.third_party_token = IntegrationToken.generate(cls.user, "Nuvio")

    def setUp(self):
        self.signed_in = self.client_class()
        self.signed_in.force_login(self.user)
        self.media = reverse("api_media_list")

    def sets_mark(self, client, method, path, **extra):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        interactive_requests._last_marked_at = None
        getattr(client, method)(path, **extra)
        return bool(cache.get(INTERACTIVE_REQUEST_CACHE_KEY))

    def test_people_set_the_mark(self):
        cases = {
            "html page": (self.signed_in, "/", HTML),
            "htmx swap": (
                self.signed_in,
                reverse("history"),
                {**HTML, "HTTP_HX_REQUEST": "true"},
            ),
            "session api read": (self.signed_in, self.media, JSON),
            "app device-flow token": (
                self.client,
                self.media,
                {**JSON, "HTTP_AUTHORIZATION": f"Bearer {self.app_token}"},
            ),
        }
        for name, (client, path, extra) in cases.items():
            with self.subTest(name):
                self.assertTrue(self.sets_mark(client, "get", path, **extra))

    def test_automation_and_polls_do_not(self):
        third = f"Bearer {self.third_party_token}"
        cases = {
            "third-party token": (
                self.client,
                "get",
                self.media,
                {**JSON, "HTTP_AUTHORIZATION": third},
            ),
            "x-api-key": (
                self.client,
                "get",
                self.media,
                {**JSON, "HTTP_X_API_KEY": self.third_party_token},
            ),
            "legacy user token": (
                self.client,
                "get",
                self.media,
                {**JSON, "HTTP_AUTHORIZATION": "Bearer legacy-user-token"},
            ),
            "legacy token with a session cookie": (
                self.signed_in,
                "get",
                self.media,
                {**JSON, "HTTP_AUTHORIZATION": "Bearer legacy-user-token"},
            ),
            "third-party token with a session cookie": (
                self.signed_in,
                "get",
                self.media,
                {**JSON, "HTTP_AUTHORIZATION": third},
            ),
            "listenbrainz client": (
                self.client,
                "get",
                reverse("listenbrainz_validate_token"),
                {"HTTP_AUTHORIZATION": f"Token {self.third_party_token}"},
            ),
            "api write": (
                self.signed_in,
                "post",
                reverse("api_playback_progress"),
                {"data": {}, "content_type": "application/json"},
            ),
            "anonymous api": (self.client, "get", self.media, JSON),
            "now-playing poll": (
                self.signed_in,
                "get",
                reverse("api_playback_home_cards"),
                JSON,
            ),
            "cover refresh poll": (
                self.signed_in,
                "get",
                reverse("api_home_artwork"),
                JSON,
            ),
            "discover status poll": (
                self.signed_in,
                "get",
                reverse("api_discover_status"),
                JSON,
            ),
            "htmx artwork poll": (
                self.signed_in,
                "get",
                reverse("home_rows_artwork_refresh"),
                {**HTML, "HTTP_HX_REQUEST": "true"},
            ),
            "health": (self.client, "get", "/health/", {}),
            "static": (self.client, "get", "/static/css/main.css", {}),
        }
        for name, (client, method, path, extra) in cases.items():
            with self.subTest(name):
                self.assertFalse(self.sets_mark(client, method, path, **extra))

    @override_settings(FLOPPY_AUTO_LOGIN_USERNAME="person")
    def test_auto_login_does_not_make_a_credentialless_client_count(self):
        self.assertFalse(self.sets_mark(self.client, "get", self.media, **JSON))

    def test_classifying_an_api_read_adds_no_query(self):
        token = IntegrationToken.objects.get(client_identifier=FIRST_PARTY_CLIENT_ID)
        user = get_user_model().objects.get(pk=self.user.pk)
        session = RequestFactory().get(self.media)
        session.auth, session.user = None, user
        session.COOKIES[settings.SESSION_COOKIE_NAME] = "x"
        app = RequestFactory().get(self.media)
        app.auth, app.user = token, user
        with self.assertNumQueries(0):
            self.assertTrue(interactive_requests.marks_api_request(session))
            self.assertTrue(interactive_requests.marks_api_request(app))


class MarkRenewalTests(TestCase):
    """The mark is written at most once per window and renewed before it lapses."""

    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        interactive_requests._last_marked_at = None

    def test_writes_at_most_once_per_window_and_renews_before_ttl(self):
        clock = [1000.0]
        with (
            patch.object(interactive_requests.time, "monotonic", lambda: clock[0]),
            patch.object(
                interactive_requests,
                "mark_interactive_request",
                wraps=interactive_requests.mark_interactive_request,
            ) as write,
        ):
            for _ in range(5):
                refresh_interactive_mark()
                clock[0] += 1
            self.assertEqual(write.call_count, 1)
            clock[0] = 1000.0 + interactive_requests._MARK_RENEW_SECONDS
            refresh_interactive_mark()
            self.assertEqual(write.call_count, 2)
        self.assertLess(
            interactive_requests._MARK_RENEW_SECONDS, INTERACTIVE_REQUEST_TTL_SECONDS
        )
        self.assertTrue(cache.get(INTERACTIVE_REQUEST_CACHE_KEY))

    def test_cache_outage_does_not_record_a_write(self):
        with patch.object(
            interactive_requests,
            "mark_interactive_request",
            side_effect=ConnectionError("redis down"),
        ):
            with self.assertRaises(ConnectionError):
                refresh_interactive_mark()
        self.assertIsNone(interactive_requests._last_marked_at)
