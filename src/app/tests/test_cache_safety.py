"""Tests for telling a held lock apart from a broken cache (issue #521)."""

from unittest import mock

from django.test import SimpleTestCase

from app import cache_safety
from app.cache_safety import ON_ERROR_PROCEED, ON_ERROR_SKIP, acquire_lock, cache_add


class CacheAddTests(SimpleTestCase):
    """The three states cache.add can be in."""

    def test_returns_true_when_claimed(self):
        """A free key is claimed."""
        with mock.patch.object(cache_safety.cache, "add", return_value=True):
            self.assertIs(cache_add("key"), True)

    def test_returns_false_when_already_held(self):
        """django-redis returns False when the key exists."""
        with mock.patch.object(cache_safety.cache, "add", return_value=False):
            self.assertIs(cache_add("key"), False)

    def test_returns_none_when_ignore_exceptions_swallows_a_failure(self):
        """IGNORE_EXCEPTIONS turns a backend error into None, not False."""
        with mock.patch.object(cache_safety.cache, "add", return_value=None):
            self.assertIsNone(cache_add("key"))

    def test_returns_none_when_the_backend_raises_outright(self):
        """Pool exhaustion can raise before a command is ever issued."""
        with mock.patch.object(
            cache_safety.cache,
            "add",
            side_effect=ConnectionError("pool exhausted"),
        ):
            self.assertIsNone(cache_add("key"))


class AcquireLockTests(SimpleTestCase):
    """Resolving the unavailable case according to what the lock guards."""

    def test_a_free_lock_is_acquired_under_either_policy(self):
        """The happy path is unaffected by the on_error choice."""
        for policy in (ON_ERROR_SKIP, ON_ERROR_PROCEED):
            with (
                self.subTest(on_error=policy),
                mock.patch.object(cache_safety.cache, "add", return_value=True),
            ):
                self.assertTrue(acquire_lock("key", timeout=10, on_error=policy))

    def test_a_held_lock_is_refused_under_either_policy(self):
        """on_error only governs the unavailable case, never a real conflict."""
        for policy in (ON_ERROR_SKIP, ON_ERROR_PROCEED):
            with (
                self.subTest(on_error=policy),
                mock.patch.object(cache_safety.cache, "add", return_value=False),
            ):
                self.assertFalse(acquire_lock("key", timeout=10, on_error=policy))

    def test_skip_treats_an_unavailable_cache_as_held(self):
        """Best-effort maintenance must not pile onto a struggling host."""
        with mock.patch.object(cache_safety.cache, "add", return_value=None):
            self.assertFalse(
                acquire_lock("key", timeout=10, on_error=ON_ERROR_SKIP),
            )

    def test_proceed_treats_an_unavailable_cache_as_free(self):
        """Work the user asked for must not be silently refused."""
        with mock.patch.object(cache_safety.cache, "add", return_value=None):
            self.assertTrue(
                acquire_lock("key", timeout=10, on_error=ON_ERROR_PROCEED),
            )

    def test_release_tolerates_an_unavailable_cache(self):
        """Releasing in a finally block must never mask the original error."""
        with mock.patch.object(
            cache_safety.cache,
            "delete",
            side_effect=ConnectionError("gone"),
        ):
            cache_safety.release_lock("key")  # must not raise
