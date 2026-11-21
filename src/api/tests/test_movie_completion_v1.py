"""The versioned movie completion route commits an independently keyed play."""

from datetime import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from app.models import Item, Movie, MoviePlay
from integrations.models import IntegrationEventReceipt, IntegrationToken

ENDPOINT = "/api/v1/scrobble/completions/v1/"
FIRST_PLAY = {"tmdb": "701", "played_at": "2026-01-01T10:00:00Z"}


@skipUnless(connection.vendor == "postgresql", "Requires the guarded PostgreSQL route")
class MovieCompletionTests(TransactionTestCase):
    """Exercise the mounted endpoint with real integration scopes and history."""

    def setUp(self):
        """Create two accounts and one movie tracked only by the owner."""
        self.owner = get_user_model().objects.create_user(username="completion-owner")
        self.other = get_user_model().objects.create_user(username="completion-other")
        self.headers = self.token_headers(self.owner, ["scrobble:write"])
        item = Item.objects.create(
            media_type="movie", source="tmdb", media_id="701", title="Fixture movie"
        )
        self.movie = Movie.objects.create(user=self.owner, item=item, status="Planning")
        fetch = patch(
            "app.providers.tmdb.movie", side_effect=AssertionError("provider I/O")
        )
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)
        credits = patch(
            "app.tasks.enqueue_item_backfills.delay",
            side_effect=self.assert_credits_after_commit,
        )
        credits.start()
        self.addCleanup(credits.stop)
        self.client = APIClient()

    def assert_credits_after_commit(self, *_args):
        """A real worker may still refresh credits after the lock is released."""
        self.assertFalse(connection.in_atomic_block)

    @staticmethod
    def token_headers(user, scopes):
        """Mint an ephemeral test token with the exact scopes."""
        _, token = IntegrationToken.generate(user, "completion fixture", scopes=scopes)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def complete(self, event_id, payload=FIRST_PLAY, headers=None):
        """Post through the native view and token authentication."""
        return self.client.post(
            ENDPOINT,
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(event_id),
            **(headers if headers is not None else self.headers),
        )

    def test_same_viewing_replays_and_a_rapid_new_viewing_is_preserved(self):
        """Discarding the acknowledgement does not change the stored viewing."""
        event_id = uuid4()
        first = self.complete(event_id)
        self.assertEqual(first.status_code, HTTP.OK)
        self.assertEqual(first.data["event_id"], str(event_id))
        replay = self.complete(event_id)
        self.assertEqual(replay.data, first.data)
        self.assertEqual(MoviePlay.objects.filter(movie=self.movie).count(), 1)

        rewatch = {"tmdb": "701", "played_at": "2026-01-01T10:05:00Z"}
        conflict = self.complete(event_id, rewatch)
        self.assertEqual(conflict.status_code, HTTP.CONFLICT)
        second = self.complete(uuid4(), rewatch)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertNotEqual(second.data["play_id"], first.data["play_id"])
        self.assertEqual(
            list(
                MoviePlay.objects.filter(movie=self.movie)
                .order_by("end_date")
                .values_list("end_date", flat=True)
            ),
            [
                datetime.fromisoformat(play["played_at"])
                for play in (FIRST_PLAY, rewatch)
            ],
        )
        self.fetch.assert_not_called()
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.progress, 1)

    def test_unscoped_or_other_account_cannot_read_or_write_tracking(self):
        """The probe and commit both retain the existing scrobble scope."""
        probe = self.client.get(ENDPOINT, {"tmdb": "701"}, **self.headers)
        self.assertEqual(probe.data, {"version": 1, "media_type": "movie"})
        unscoped = self.token_headers(self.owner, ["history:read"])
        other = self.token_headers(self.other, ["scrobble:write"])
        self.assertEqual(
            self.client.get(ENDPOINT, {"tmdb": "701"}, **unscoped).status_code,
            HTTP.FORBIDDEN,
        )
        self.assertEqual(
            self.complete(uuid4(), headers=unscoped).status_code, HTTP.FORBIDDEN
        )
        self.assertEqual(
            self.client.get(ENDPOINT, {"tmdb": "701"}, **other).status_code,
            HTTP.NOT_FOUND,
        )
        self.assertEqual(
            self.complete(uuid4(), headers=other).status_code, HTTP.NOT_FOUND
        )
        self.assertFalse(MoviePlay.objects.exists())
        self.fetch.assert_not_called()

    def test_invalid_event_is_rejected_before_claim(self):
        """A dated viewing needs a UUID and valid movie identity."""
        self.assertEqual(self.complete("invalid").status_code, HTTP.BAD_REQUEST)
        bad = self.complete(uuid4(), {**FIRST_PLAY, "tmdb": "//bad"})
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)
        self.assertFalse(MoviePlay.objects.exists())
        self.assertFalse(
            IntegrationEventReceipt.objects.filter(user=self.owner).exists()
        )


@skipUnless(connection.vendor == "sqlite", "Requires an unsupported SQLite receiver")
class MovieCompletionUnavailableTests(TestCase):
    """A receiver without PostgreSQL does not advertise or claim delivery."""

    def test_probe_and_post_are_unavailable(self):
        """SQLite keeps the legacy route and creates no guarded receipt."""
        user = get_user_model().objects.create_user(username="completion-sqlite")
        headers = MovieCompletionTests.token_headers(user, ["scrobble:write"])
        identities = [
            {"tmdb": "701"},
            {
                "media_type": "episode",
                "tmdb": "701",
                "season_number": 1,
                "episode_number": 2,
            },
        ]
        for identity in identities:
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.client.get(ENDPOINT, identity, **headers).status_code,
                    HTTP.SERVICE_UNAVAILABLE,
                )
                self.assertEqual(
                    self.client.post(
                        ENDPOINT,
                        {**identity, "played_at": FIRST_PLAY["played_at"]},
                        content_type="application/json",
                        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
                        **headers,
                    ).status_code,
                    HTTP.SERVICE_UNAVAILABLE,
                )
        self.assertFalse(IntegrationEventReceipt.objects.exists())
        self.assertFalse(MoviePlay.objects.exists())
