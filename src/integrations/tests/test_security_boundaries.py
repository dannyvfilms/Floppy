"""Regression coverage for integration trust boundaries."""

from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from integrations import plex, pocketcasts_artwork, podcast_rss, safe_fetch, views
from integrations.imports.helpers import MediaImportError
from integrations.imports.kapowarr import KapowarrClient


class IntegrationRedirectTests(SimpleTestCase):
    """Integration return links must remain on this Floppy instance."""

    def test_refuses_external_and_scheme_relative_destinations(self):
        for destination in (
            "https://attacker.example/",
            "//attacker.example/",
            "\\\\attacker.example/",
        ):
            with self.subTest(destination=destination):
                request = RequestFactory().post("/", {"next": destination})
                self.assertEqual(
                    views._integration_redirect(request)["Location"],
                    reverse("import_data"),
                )

    def test_callback_next_is_checked_and_local_path_is_preserved(self):
        request = RequestFactory().get("/")
        self.assertEqual(
            views._integration_redirect(request, next_url="https://attacker.example/")[
                "Location"
            ],
            reverse("import_data"),
        )
        self.assertEqual(
            views._integration_redirect(request, next_url="/onboarding/")["Location"],
            "/onboarding/",
        )


class FeedFetchBoundaryTests(SimpleTestCase):
    """Public podcast metadata cannot request internal services."""

    @patch("requests.sessions.Session.get")
    def test_internal_feed_is_refused_before_transport(self, get):
        self.assertEqual(
            podcast_rss.fetch_feed_from_rss("http://localhost/feed"), ({}, [])
        )
        self.assertIsNone(
            pocketcasts_artwork._fetch_from_rss_feed("http://localhost/feed")
        )
        get.assert_not_called()

    def test_decoded_feed_body_has_a_size_limit(self):
        response = Mock(headers={}, iter_content=Mock(return_value=[b"123", b"456"]))
        with self.assertRaises(safe_fetch.UnsafeUrlError) as caught:
            safe_fetch._read_bounded(response, max_bytes=5)
        self.assertEqual(caught.exception.reason_code, "response_too_large")


class SelfHostedRedirectBoundaryTests(SimpleTestCase):
    """Integration API keys cannot be redirected to another origin."""

    @patch("integrations.safe_fetch.validate_self_hosted_url")
    def test_https_redirect_cannot_downgrade_transport(self, validate):
        send = Mock(
            return_value=Mock(
                status_code=302, headers={"Location": "http://media.example/api"}
            )
        )
        with self.assertRaises(safe_fetch.SelfHostedUrlError):
            safe_fetch.send_to_self_hosted(
                send, "https://media.example/api", headers={"X-Api-Key": "secret"}
            )
        self.assertEqual(send.call_count, 1)
        self.assertFalse(send.call_args.kwargs["allow_redirects"])

    @patch("integrations.safe_fetch.validate_self_hosted_url")
    @patch("integrations.imports.kapowarr.requests.get")
    def test_kapowarr_refuses_cross_host_redirect(self, get, validate):
        get.return_value = Mock(
            status_code=302, headers={"Location": "https://attacker.example/"}
        )
        with self.assertRaises(MediaImportError):
            KapowarrClient("https://comics.example", "secret").healthcheck()
        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("integrations.safe_fetch.validate_self_hosted_url")
    @patch("integrations.plex.requests.get")
    def test_plex_refuses_cross_host_redirect(self, get, validate):
        get.return_value = Mock(
            status_code=302, headers={"Location": "https://attacker.example/"}
        )
        with self.assertRaises(plex.PlexClientError):
            plex.fetch_metadata("secret", "https://plex.example", "1")
        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
