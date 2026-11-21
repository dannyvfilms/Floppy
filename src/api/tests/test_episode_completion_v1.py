"""Authenticated completion delivery for canonical, locally tracked TV episodes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http import HTTPStatus as HTTP  # noqa: N814
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.db.models.signals import post_save
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from api.tests.test_movie_completion_v1 import ENDPOINT
from app.models import TV, Episode, Item, Season
from integrations.models import IntegrationEventReceipt, IntegrationToken


def token_headers(user, scopes):
    """Authenticate as a single synthetic user with an independent credential."""
    _, token = IntegrationToken.generate(user, "episode fixture", scopes=scopes)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


IDENTITY = {
    "media_type": "episode",
    "tmdb": "1800",
    "season_number": 1,
    "episode_number": 2,
}
TIMESTAMP = "2026-01-02T14:01:02.123456+04:00"
UTC_INSTANT = datetime.fromisoformat(TIMESTAMP).astimezone(UTC)


@skipUnless(connection.vendor == "postgresql", "The guarded route requires PostgreSQL")
class EpisodeCompletionTests(TransactionTestCase):
    """Read real stable identities and wall-clock instants from PostgreSQL."""

    def setUp(self):
        """Build local data for two users without contacting a metadata provider."""
        self.owner = get_user_model().objects.create_user(username="episode-owner")
        self.other = get_user_model().objects.create_user(
            username="other-episode-owner"
        )
        self.headers = token_headers(self.owner, ["scrobble:write"])
        show = Item.objects.create(
            media_type="tv", source="tmdb", media_id="1800", title="Fixture series"
        )
        season = Item.objects.create(
            media_type="season",
            source="tmdb",
            media_id="1800",
            season_number=1,
            title="Fixture season",
            provider_episode_count=12,
        )
        self.first = Item.objects.create(
            media_type="episode",
            source="tmdb",
            media_id="1800",
            season_number=1,
            episode_number=2,
            title="Fixture episode",
        )
        self.other_episode = Item.objects.create(
            media_type="episode",
            source="tmdb",
            media_id="1800",
            season_number=1,
            episode_number=3,
            title="Other episode",
        )
        self.tv = TV.objects.create(user=self.owner, item=show, status="In progress")
        self.season = Season.objects.create(
            user=self.owner, item=season, related_tv=self.tv, status="In progress"
        )
        self.client = APIClient()
        self.body = {**IDENTITY, "played_at": TIMESTAMP}

    def send(self, key, body=None, headers=None, client=None):
        """Write only through the mounted integration-token route."""
        return (client or self.client).post(
            ENDPOINT,
            self.body if body is None else body,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(key),
            **(self.headers if headers is None else headers),
        )

    def test_capability_has_exact_user_and_coordinate(self):
        """A missing episode, wrong account, or wrong scoped token gets no capability."""
        probe = self.client.get(ENDPOINT, IDENTITY, **self.headers)
        self.assertEqual(probe.data, {"version": 1, **IDENTITY})
        headers = token_headers(self.other, ["scrobble:write"])
        self.assertEqual(
            self.client.get(ENDPOINT, IDENTITY, **headers).status_code, HTTP.NOT_FOUND
        )
        self.assertEqual(
            self.send(uuid4(), headers=headers).status_code, HTTP.NOT_FOUND
        )
        unscoped = token_headers(self.owner, ["progress:read"])
        self.assertEqual(
            self.client.get(ENDPOINT, IDENTITY, **unscoped).status_code, HTTP.FORBIDDEN
        )
        self.assertEqual(
            self.send(uuid4(), headers=unscoped).status_code, HTTP.FORBIDDEN
        )
        self.assertEqual(
            self.client.get(
                ENDPOINT, {**IDENTITY, "episode_number": 15}, **self.headers
            ).status_code,
            HTTP.NOT_FOUND,
        )

    def test_lost_reply_and_rapid_real_rewatch(self):
        """Discard the first reply, rotate credentials and record the next real watch."""
        key = uuid4()
        first = self.send(key)
        self.assertEqual(first.status_code, HTTP.OK, first.data)
        ack = first.data
        self.assertEqual(
            ack,
            {
                **IDENTITY,
                "event_id": str(key),
                "play_id": ack["play_id"],
                "played_at": UTC_INSTANT.isoformat(),
            },
        )
        rotated = token_headers(self.owner, ["scrobble:write"])
        self.assertEqual(self.send(key, headers=rotated).data, ack)
        second_body = {**self.body, "played_at": "2026-01-02T10:01:03.123456Z"}
        self.assertEqual(self.send(key, second_body).status_code, HTTP.CONFLICT)
        self.assertEqual(
            self.send(key, {**self.body, "episode_number": 3}).status_code,
            HTTP.CONFLICT,
        )
        self.assertEqual(
            self.send(key, {"tmdb": "1800", "played_at": TIMESTAMP}).status_code,
            HTTP.CONFLICT,
        )
        second = self.send(uuid4(), second_body)
        self.assertEqual(second.status_code, HTTP.OK, second.data)
        self.assertNotEqual(ack["play_id"], second.data["play_id"])
        plays = Episode.objects.filter(
            related_season=self.season, item=self.first
        ).order_by("end_date")
        self.assertEqual(
            list(plays.values_list("end_date", flat=True)),
            [UTC_INSTANT, datetime.fromisoformat(second_body["played_at"])],
        )
        self.assertEqual(Episode.objects.filter(item=self.other_episode).count(), 0)

    def test_missing_coordinates_or_naive_timestamp_never_write(self):
        """An integration cannot quietly convert uncertain input into a movie or local time."""
        for bad in (
            {**self.body, "played_at": "2026-01-02T10:01:02"},
            {**self.body, "episode_number": 0},
            {**self.body, "season_number": -1},
            {**self.body, "media_type": "movie"},
            {**self.body, "media_type": "series"},
            {k: v for k, v in self.body.items() if k != "episode_number"},
            {k: v for k, v in self.body.items() if k != "season_number"},
        ):
            with self.subTest(values=bad):
                self.assertEqual(self.send(uuid4(), bad).status_code, HTTP.BAD_REQUEST)
        self.assertFalse(Episode.objects.exists())
        self.assertFalse(IntegrationEventReceipt.objects.exists())

    def test_concurrent_identical_retries_record_one_original_play(self):
        """Two independent PostgreSQL connections dispatch the same event concurrently."""
        key, barrier = uuid4(), Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                response = self.send(key, client=APIClient())
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0][0], HTTP.OK, responses)
        self.assertEqual(
            Episode.objects.filter(
                related_season=self.season, end_date=UTC_INSTANT
            ).count(),
            1,
        )
        self.assertEqual(
            IntegrationEventReceipt.objects.filter(user=self.owner).count(), 1
        )

    def test_season_projection_only_runs_after_the_receipt_commits(self):
        """Provider-dependent episode-count refresh is downstream of durable history."""
        key = uuid4()
        original = Episode._sync_season_after_save
        observed = []

        def verify(play):
            receipt = IntegrationEventReceipt.objects.get(
                user=self.owner, client_event_id=f"scrobble-completion-v1:{key}"
            )
            observed.append(
                (connection.in_atomic_block, receipt.response_status_code, play.pk)
            )
            return original(play)

        callbacks = []

        def after_save(sender, instance, **kwargs):
            # Model readers scheduled by a normal post-save receiver see the projection.
            transaction.on_commit(lambda: callbacks.append(len(observed)))

        post_save.connect(after_save, sender=Episode, weak=False)
        self.addCleanup(post_save.disconnect, after_save, sender=Episode)
        with patch.object(Episode, "_sync_season_after_save", verify):
            response = self.send(key)
        self.assertEqual(callbacks, [1])
        self.assertEqual(response.status_code, HTTP.OK, response.data)
        self.assertEqual(observed, [(False, HTTP.OK, response.data["play_id"])])
