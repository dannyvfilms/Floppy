import os
from unittest import TestCase, mock

import requests

from config.test_network import (
    UnexpectedExternalNetworkAccessError,
    test_network_enabled,
    test_url_is_local,
)


class TestNetworkIsolationTests(TestCase):
    def test_loopback_urls_are_allowed_by_policy(self):
        for url in (
            "http://127.0.0.1:8000/health/",
            "http://localhost:8080/",
            "http://[::1]:8000/",
        ):
            with self.subTest(url=url):
                self.assertTrue(test_url_is_local(url))

    def test_public_urls_are_not_local(self):
        self.assertFalse(test_url_is_local("https://api.themoviedb.org/3/movie/1"))
        self.assertFalse(test_url_is_local("https://musicbrainz.org/ws/2"))

    def test_external_requests_fail_before_network_io(self):
        with self.assertRaisesRegex(
            UnexpectedExternalNetworkAccessError,
            "External HTTP is disabled for ordinary tests",
        ) as error:
            requests.get("https://example.com/provider-fixture", timeout=30)

        self.assertIsInstance(error.exception, requests.ConnectionError)

    def test_explicit_network_run_is_detected(self):
        with mock.patch.dict(os.environ, {"FLOPPY_TEST_ALLOW_NETWORK": "1"}):
            self.assertTrue(test_network_enabled())

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(test_network_enabled())
