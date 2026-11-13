from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from integrations import pending_auth


def _request(user_id, native=True):
    return SimpleNamespace(
        user=SimpleNamespace(pk=user_id),
        session={},
        native_connect=native,
    )


class PendingStateConsumptionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_state_is_consumed_once(self):
        pending_auth.stash_state(_request(1), "tok", {"provider": "x"})
        self.assertEqual(pending_auth.pop_state(_request(1), "tok"), {"provider": "x"})
        self.assertIsNone(pending_auth.pop_state(_request(1), "tok"))

    def test_concurrent_callbacks_cannot_both_consume(self):
        pending_auth.stash_state(_request(1), "tok", {"provider": "x"})
        stale = cache.get(pending_auth._state_key(1, "tok"))
        # Both callbacks read the entry before either deletes it.
        with patch.object(pending_auth.cache, "get", return_value=stale):
            first = pending_auth.pop_state(_request(1), "tok")
            second = pending_auth.pop_state(_request(1), "tok")
        self.assertEqual(first, {"provider": "x"})
        self.assertIsNone(second)

    def test_other_users_callback_does_not_invalidate_the_start(self):
        pending_auth.stash_state(_request(1), "tok", {"provider": "x"})
        self.assertIsNone(pending_auth.pop_state(_request(2), "tok"))
        self.assertEqual(pending_auth.pop_state(_request(1), "tok"), {"provider": "x"})

    def test_device_login_take_is_single_use_per_user(self):
        pending_auth.put("trakt", 1, {"code": "a"})
        pending_auth.put("trakt", 2, {"code": "b"})
        stale = pending_auth.get("trakt", 1)
        with patch.object(pending_auth.cache, "get", return_value=stale):
            self.assertEqual(pending_auth.take("trakt", 1), {"code": "a"})
            self.assertIsNone(pending_auth.take("trakt", 1))
        self.assertEqual(pending_auth.get("trakt", 2), {"code": "b"})
