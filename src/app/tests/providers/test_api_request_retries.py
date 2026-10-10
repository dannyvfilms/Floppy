"""Tests for bounded provider retries (issue #521).

The 429 branch used to recurse without incrementing the attempt counter, so a
provider that kept rate-limiting held a Celery worker - which runs at
concurrency 1, so the whole queue - sleeping indefinitely.
"""

from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from app.providers import services
from app.providers.services import (
    COMICVINE_REQUEST_TIMEOUT,
    RATE_LIMIT_DEFAULT_WAIT_SECONDS,
    RATE_LIMIT_MAX_COOLDOWN_SECONDS,
    RATE_LIMIT_MAX_RETRIES,
    RATE_LIMIT_MAX_RETRIES_INTERACTIVE,
    RATE_LIMIT_MAX_WAIT_SECONDS,
    RATE_LIMIT_MAX_WAIT_SECONDS_INTERACTIVE,
    ProviderAPIError,
    _rate_limit_cooldown_key,
    _rate_limit_wait_seconds,
    api_request,
    interactive_request_scope,
)


class CooldownIsolationMixin:
    """Cooldowns outlive a request by design, so clear them between tests."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)


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


class RateLimitRetryTests(CooldownIsolationMixin, SimpleTestCase):
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

    @patch.object(services.session, "get")
    def test_comicvine_uses_a_bounded_background_timeout(self, get):
        get.side_effect = requests.exceptions.Timeout()

        with self.assertRaises(ProviderAPIError):
            api_request("comicvine", "GET", "https://example.test/x")

        self.assertEqual(get.call_args.kwargs["timeout"], COMICVINE_REQUEST_TIMEOUT)

    def test_a_wait_longer_than_the_budget_is_not_retried_at_all(self):
        """Hardcover answers an exhausted daily quota with hours (#1025).

        Sleeping the clamped 60s and retrying into that only spends more of the
        quota and strands a worker, so the whole attempt budget is skipped.
        """
        get = Mock(return_value=rate_limited_response(retry_after="86400"))
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep") as sleep,
            self.assertRaises(ProviderAPIError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        self.assertEqual(get.call_count, 1)
        self.assertEqual(sleep.call_count, 0)

    def test_a_long_wait_arms_a_cooldown_that_skips_the_next_request(self):
        """The next caller must not spend another request into the same wall."""
        get = Mock(return_value=rate_limited_response(retry_after="86400"))
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep"),
            self.assertRaises(ProviderAPIError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        get.reset_mock()
        with (
            patch.object(services.session, "get", get),
            self.assertRaises(ProviderAPIError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        self.assertEqual(get.call_count, 0)

    def test_the_cooldown_is_keyed_to_the_credential_that_was_limited(self):
        """A member's personal token must survive the instance token's quota."""
        instance = {"Authorization": "Bearer instance-token"}
        personal = {"Authorization": "Bearer personal-token"}
        get = Mock(return_value=rate_limited_response(retry_after="86400"))
        with (
            patch.object(services.session, "get", get),
            self.assertRaises(ProviderAPIError),
        ):
            api_request("hardcover", "GET", "https://example.test/x", headers=instance)

        self.assertTrue(cache.get(_rate_limit_cooldown_key("hardcover", instance)))
        self.assertIsNone(cache.get(_rate_limit_cooldown_key("hardcover", personal)))

        get.reset_mock()
        with (
            patch.object(services.session, "get", get),
            self.assertRaises(ProviderAPIError),
        ):
            api_request("hardcover", "GET", "https://example.test/x", headers=personal)

        # The personal token is not in cooldown, so it still gets to try.
        self.assertEqual(get.call_count, 1)

    def test_the_cooldown_key_never_stores_the_token(self):
        """The digest is the point: cache keys land in logs and dumps."""
        key = _rate_limit_cooldown_key("hardcover", {"Authorization": "Bearer s3cret"})

        self.assertNotIn("s3cret", key)

    def test_the_cooldown_is_capped(self):
        """Retry-After is provider-controlled; a bad value must expire."""
        get = Mock(return_value=rate_limited_response(retry_after="999999"))
        with (
            patch.object(services.session, "get", get),
            patch.object(services.cache, "set") as cache_set,
            self.assertRaises(ProviderAPIError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        self.assertEqual(cache_set.call_args.args[2], RATE_LIMIT_MAX_COOLDOWN_SECONDS)

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


class InteractiveRequestScopeTests(CooldownIsolationMixin, SimpleTestCase):
    """Request-serving callers must fail fast instead of blocking (#1008)."""

    def test_interactive_scope_caps_retries_and_wait(self):
        """A book detail page must not block for the background retry budget."""
        get = Mock(return_value=rate_limited_response(retry_after="4"))
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep") as sleep,
            self.assertRaises(requests.exceptions.HTTPError),
            interactive_request_scope(),
        ):
            api_request("hardcover", "GET", "https://example.test/x")

        self.assertEqual(get.call_count, RATE_LIMIT_MAX_RETRIES_INTERACTIVE + 1)
        self.assertEqual(sleep.call_count, RATE_LIMIT_MAX_RETRIES_INTERACTIVE)
        total = sum(call.args[0] for call in sleep.call_args_list)
        self.assertLessEqual(
            total,
            RATE_LIMIT_MAX_RETRIES_INTERACTIVE * RATE_LIMIT_MAX_WAIT_SECONDS_INTERACTIVE,
        )

    def test_scope_is_reset_after_use(self):
        """The context manager must not leak into calls made outside it."""
        get = Mock(return_value=rate_limited_response())
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep"),
            self.assertRaises(requests.exceptions.HTTPError),
            interactive_request_scope(),
        ):
            api_request("hardcover", "GET", "https://example.test/x")

        get.reset_mock()
        with (
            patch.object(services.session, "get", get),
            patch.object(services.time, "sleep") as sleep,
            self.assertRaises(requests.exceptions.HTTPError),
        ):
            api_request("mal", "GET", "https://example.test/x")

        self.assertEqual(get.call_count, RATE_LIMIT_MAX_RETRIES + 1)
        self.assertEqual(sleep.call_count, RATE_LIMIT_MAX_RETRIES)


class ProviderErrorLoggingTests(SimpleTestCase):
    """The error log has to be diagnosable on its own (#1025).

    An isinstance(headers, dict) check silently discarded the headers of every
    real response, because requests uses CaseInsensitiveDict - a Mapping, but
    not a dict subclass. Every provider error logged content_type=None and
    never parsed the body, which is what made a plain Hardcover rate-limit
    message look like a mysterious headerless blob.
    """

    def test_case_insensitive_headers_are_read(self):
        response = Mock(status_code=429)
        response.headers = requests.structures.CaseInsensitiveDict(
            {"Content-Type": "application/json; charset=utf-8"},
        )
        response.json.return_value = {"error": "Too Many Requests"}
        error = requests.exceptions.HTTPError(response=response)

        with self.assertLogs("app.providers.services", level="ERROR") as logs:
            ProviderAPIError("hardcover", error)

        self.assertIn("response_keys=['error']", logs.output[0])

    def test_rate_limit_headers_are_surfaced(self):
        response = Mock()
        response.headers = requests.structures.CaseInsensitiveDict(
            {"Retry-After": "5980", "X-Ratelimit-Daily-Remaining": "0"},
        )

        self.assertEqual(
            services._rate_limit_headers(response),
            {"Retry-After": "5980", "X-Ratelimit-Daily-Remaining": "0"},
        )


class InteractiveTimeoutTests(CooldownIsolationMixin, SimpleTestCase):
    """A provider that never answers must not hold a web thread for minutes."""

    def _timeout_used(self, *, interactive):
        ok = Mock()
        ok.json.return_value = {}
        with patch.object(services, "resilient_request", return_value=ok) as request:
            if interactive:
                with interactive_request_scope():
                    api_request("igdb", "GET", "https://example.test/x")
            else:
                api_request("igdb", "GET", "https://example.test/x")
        return request.call_args.kwargs["timeout"]

    def test_interactive_request_uses_the_short_timeout(self):
        self.assertLessEqual(self._timeout_used(interactive=True), 10)

    def test_background_request_keeps_the_patient_timeout(self):
        self.assertEqual(
            self._timeout_used(interactive=False),
            services.settings.REQUEST_TIMEOUT,
        )

    def test_read_timeouts_are_not_retried_but_connection_failures_are(self):
        retry = services.session.get_adapter("https://api.themoviedb.org/3").max_retries

        self.assertIs(retry.read, False)
        self.assertEqual(retry.total, 3)
