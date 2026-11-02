"""Atomic last-used throttling for integration tokens and catalog grants.

Both touch paths must advance the stored timestamp at most once per interval
no matter how many stale in-memory copies race: the UPDATE is conditional on
the stored value and counts affected rows. These tests count *stored
advances*, not UPDATE statements — several calls may issue the conditional
query while only one changes a row.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from api.authentication import LAST_USED_WRITE_INTERVAL, _touch_last_used
from integrations.models import CatalogGrant, IntegrationToken
from integrations.stremio_catalog import touch_grant


def _stored(model, pk):
    return model.objects.filter(pk=pk).values_list("last_used_at", flat=True).first()


class TokenLastUsedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="touch-token")
        self.token, self.raw = IntegrationToken.generate(
            user=self.user, name="Throttle test"
        )

    def test_null_timestamp_is_written_once(self):
        before = timezone.now()
        _touch_last_used(self.token)
        stored = _stored(IntegrationToken, self.token.pk)
        self.assertIsNotNone(stored)
        self.assertGreaterEqual(stored, before)
        first = stored

        # Repeated callers inside the interval never advance it again.
        for _ in range(5):
            _touch_last_used(self.token)
        self.assertEqual(_stored(IntegrationToken, self.token.pk), first)

    def test_recent_timestamp_is_not_rewritten(self):
        now = timezone.now()
        IntegrationToken.objects.filter(pk=self.token.pk).update(last_used_at=now)
        # A request object holding an expired copy must not force a write.
        stale = IntegrationToken.objects.get(pk=self.token.pk)
        stale.last_used_at = now - timedelta(hours=1)
        _touch_last_used(stale)
        self.assertEqual(_stored(IntegrationToken, self.token.pk), now)

    def test_exact_cutoff_writes_and_older_stale_copies_collapse(self):
        now = timezone.now()
        cutoff_age = now - LAST_USED_WRITE_INTERVAL
        IntegrationToken.objects.filter(pk=self.token.pk).update(
            last_used_at=cutoff_age
        )
        # At exactly the interval boundary the write is due (the in-memory
        # check uses a strict <).
        token = IntegrationToken.objects.get(pk=self.token.pk)
        _touch_last_used(token)
        first = _stored(IntegrationToken, self.token.pk)
        self.assertGreater(first, cutoff_age)

        # Two separately loaded stale objects both attempt the conditional
        # write; only the first advances the stored value.
        IntegrationToken.objects.filter(pk=self.token.pk).update(
            last_used_at=now - timedelta(hours=2)
        )
        stale_a = IntegrationToken.objects.get(pk=self.token.pk)
        stale_b = IntegrationToken.objects.get(pk=self.token.pk)
        _touch_last_used(stale_a)
        after_a = _stored(IntegrationToken, self.token.pk)
        _touch_last_used(stale_b)
        after_b = _stored(IntegrationToken, self.token.pk)
        self.assertEqual(after_a, after_b)
        self.assertGreater(after_a, now - timedelta(hours=2))


class GrantLastUsedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="touch-grant")
        self.grant, _token = CatalogGrant.generate(self.user, "Throttle test")

    def test_null_recent_exact_and_expired_boundaries(self):
        touch_grant(self.grant, interval_minutes=60)
        first = _stored(CatalogGrant, self.grant.pk)
        self.assertIsNotNone(first)

        # Recent: no advance.
        touch_grant(self.grant, interval_minutes=60)
        self.assertEqual(_stored(CatalogGrant, self.grant.pk), first)

        # Exact cutoff (age == interval): due, writes. The object must be
        # reloaded so the decision uses the stored value, not the fresh
        # in-memory copy above.
        now = timezone.now()
        CatalogGrant.objects.filter(pk=self.grant.pk).update(
            last_used_at=now - timedelta(minutes=60)
        )
        touch_grant(CatalogGrant.objects.get(pk=self.grant.pk), interval_minutes=60)
        self.assertGreater(
            _stored(CatalogGrant, self.grant.pk), now - timedelta(minutes=60)
        )

        # Expired via a stale copy while the stored value is recent: no write.
        CatalogGrant.objects.filter(pk=self.grant.pk).update(last_used_at=now)
        stale = CatalogGrant.objects.get(pk=self.grant.pk)
        stale.last_used_at = now - timedelta(hours=3)
        touch_grant(stale, interval_minutes=60)
        self.assertEqual(_stored(CatalogGrant, self.grant.pk), now)

    def test_two_stale_copies_collapse_to_one_advance(self):
        now = timezone.now()
        CatalogGrant.objects.filter(pk=self.grant.pk).update(
            last_used_at=now - timedelta(hours=3)
        )
        stale_a = CatalogGrant.objects.get(pk=self.grant.pk)
        stale_b = CatalogGrant.objects.get(pk=self.grant.pk)
        touch_grant(stale_a, interval_minutes=60)
        after_a = _stored(CatalogGrant, self.grant.pk)
        touch_grant(stale_b, interval_minutes=60)
        self.assertEqual(_stored(CatalogGrant, self.grant.pk), after_a)
        self.assertGreater(after_a, now - timedelta(hours=3))

    def test_repeated_concurrent_callers_advance_once_per_interval(self):
        _touch = lambda: touch_grant(  # noqa: E731 -- inline driver
            CatalogGrant.objects.get(pk=self.grant.pk), interval_minutes=60
        )
        snapshots = []
        for _ in range(10):
            _touch()
            snapshots.append(_stored(CatalogGrant, self.grant.pk))
        # Every caller that saw a fresh stored value kept it; the stored
        # timestamp advanced at most once (the very first write).
        self.assertEqual(len(set(snapshots)), 1)
        self.assertIsNotNone(snapshots[0])
