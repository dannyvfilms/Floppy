"""Tests for bounded provider retries (issue #521).

The 429 branch used to recurse without incrementing the attempt counter, so a
provider that kept rate-limiting held a Celery worker - which runs at
concurrency 1, so the whole queue - sleeping indefinitely.
"""

from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase

from app.providers import services
from app.providers.services import (
    RATE_LIMIT_DEFAULT_WAIT_SECONDS,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_MAX_WAIT_SECONDS,
    _rate_limit_wait_seconds,
    api_request,
)


def rate_limited_response(retry_after="1"):
    """Return a 429 response that raise_for_status() will raise on."""
    response = Mock()
    response.status_code = requests.codes.too_many_requests
    response.headers = {} if retry_after is None else {"Retry-After": retry_after}
    error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = error
    return response


class RetryAfterParsingTests(SimpleTestCase):
    """Retry-After is provider-controlled and cannot be trusted."""

    def test_numeric_header_is_honoured_with_a_small_margin(self):
        """A second of clock skew shouldn't earn an immediate second 429."""
        response = Mock(headers={"Retry-After": "5"})
        self.assertEqual(_rate_limit_wait_seconds(response), 8)

    def test_long_waits_are_clamped(self):
        """An hour-long Retry-After would strand the worker for an hour."""
        response = Mock(headers={"Retry-After": "3600"})
        self.assertEqual(
            _rate_limit_wait_seconds(response),
            RATE_LIMIT_MAX_WAIT_SECONDS,
        )

    def test_http_date_header_does_not_crash(self):
        """Retry-After may be a date; int() on it used to raise."""
        response = Mock(headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        self.assertEqual(
            _rate_limit_wait_seconds(response),
            RATE_LIMIT_DEFAULT_WAIT_SECONDS + 3,
        )

    def test_missing_header_uses_the_default(self):
        """Some providers send 429 with no Retry-After at all."""
        self.assertEqual(
            _rate_limit_wait_seconds(Mock(headers={})),
            RATE_LIMIT_DEFAULT_WAIT_SECONDS + 3,
        )

    def test_missing_response_does_not_crash(self):
        """Defensive: the header read must tolerate no response object."""
        self.assertEqual(
            _rate_limit_wait_seconds(None),
            RATE_LIMIT_DEFAULT_WAIT_SECONDS + 3,
        )


class RateLimitRetryTests(SimpleTestCase):
    """The 429 retry loop must terminate."""

    def test_a_persistent_429_gives_up_instead_of_recursing_forever(self):
        """This is the bug: the attempt counter was passed through unchanged."""
        get = Mock(return_value=rate_limited_response())
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep") as sleep,
            self.assertRaises(requests.exceptions.HTTPError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        # One initial attempt plus RATE_LIMIT_MAX_RETRIES retries.
        self.assertEqual(get.call_count, RATE_LIMIT_MAX_RETRIES + 1)
        self.assertEqual(sleep.call_count, RATE_LIMIT_MAX_RETRIES)

    def test_total_sleep_is_bounded(self):
        """Bounding the attempts is pointless if each one can sleep for hours."""
        get = Mock(return_value=rate_limited_response(retry_after="86400"))
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep") as sleep,
            self.assertRaises(requests.exceptions.HTTPError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        total = sum(call.args[0] for call in sleep.call_args_list)
        self.assertLessEqual(
            total,
            RATE_LIMIT_MAX_RETRIES * RATE_LIMIT_MAX_WAIT_SECONDS,
        )

    def test_a_retry_that_succeeds_returns_the_payload(self):
        """Retrying still has to work, not just terminate."""
        ok = Mock(status_code=200)
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"ok": True}
        get = Mock(side_effect=[rate_limited_response(), ok])

        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep"),
        ):
            result = api_request("mal", "GET", "https://example.test/x")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(get.call_count, 2)
