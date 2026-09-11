"""The watched-state API: assertions, not plays.

Setting unwatched through this surface must never delete history, and setting
watched must never fabricate a playback session. Those two properties are the
reason the endpoint exists separately from the playback and history routes.
"""

import datetime
import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from app.models import (
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Sources,
    Status,
    WatchStateChange,
    WatchStateOrigin,
)
from app.services.watch_state import effective_state
from integrations.models import (
    CAPABILITY_WATCHED_READ,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.identity import activate_binding, get_or_create_binding


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day):
    return datetime.datetime(2026, 7, day, 12, tzinfo=datetime.UTC)


class WatchedStateAPITestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        # The API authenticates on a token header, not a session.
        self.client.credentials(HTTP_X_API_KEY=self.user.token)
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )
        self.url = reverse(
            "api_watched_state",
            kwargs={
                "media_type": MediaTypes.MOVIE.value,
                "source": Sources.TMDB.value,
                "media_id": "603",
            },
        )


class ReadStateTests(WatchedStateAPITestCase):
    def test_an_untracked_item_reads_as_unwatched_with_no_provenance(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["watched"])
        self.assertEqual(response.json()["revision"], 0)
        self.assertIsNone(response.json()["provenance"])

    def test_state_carries_its_provenance(self):
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(1),
        )

        payload = self.client.get(self.url).json()

        self.assertTrue(payload["watched"])
        self.assertEqual(payload["play_count"], 1)
        self.assertIsNotNone(payload["provenance"])

    def test_an_unknown_media_type_is_rejected(self):
        url = reverse(
            "api_watched_state",
            kwargs={
                "media_type": "nonsense",
                "source": Sources.TMDB.value,
                "media_id": "603",
            },
        )

        self.assertEqual(self.client.get(url).status_code, 400)

    def test_a_missing_item_is_not_found(self):
        url = reverse(
            "api_watched_state",
            kwargs={
                "media_type": MediaTypes.MOVIE.value,
                "source": Sources.TMDB.value,
                "media_id": "999999",
            },
        )

        self.assertEqual(self.client.get(url).status_code, 404)


class SetStateTests(WatchedStateAPITestCase):
    def test_setting_watched_creates_no_playback_session(self):
        """The load-bearing property: an assertion is not a play."""
        response = self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["watched"])
        self.assertEqual(MoviePlay.objects.count(), 0)
        self.assertEqual(Movie.objects.count(), 0)

    def test_setting_unwatched_preserves_history(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        movie.watch(_dt(1))
        movie.watch(_dt(5))

        response = self.client.put(
            self.url,
            data={"watched": False},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["watched"])
        self.assertEqual(
            MoviePlay.objects.filter(movie=movie).count(),
            2,
            "setting unwatched must not delete history",
        )

    def test_a_non_boolean_is_rejected(self):
        response = self.client.put(
            self.url,
            data={"watched": "yes"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_replayed_idempotency_key_does_not_apply_twice(self):
        for _ in range(2):
            response = self.client.put(
                self.url,
                data={"watched": True, "play_count": 1},
                content_type="application/json",
                headers={"idempotency-key": "evt-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["replayed"])
        self.assertEqual(WatchStateChange.objects.filter(user=self.user).count(), 1)

    def test_a_stale_if_match_is_refused(self):
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        response = self.client.put(
            self.url,
            data={"watched": False},
            content_type="application/json",
            headers={"if-match": "0"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(effective_state(self.user, self.item).watched)

    def test_a_current_if_match_is_accepted(self):
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )
        revision = effective_state(self.user, self.item).revision

        response = self.client.put(
            self.url,
            data={"watched": False},
            content_type="application/json",
            headers={"if-match": str(revision)},
        )

        self.assertEqual(response.status_code, 200)

    def test_setting_the_same_state_is_reported_as_unchanged(self):
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        response = self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        self.assertTrue(response.json()["unchanged"])

    def test_another_user_cannot_read_or_set_this_state(self):
        other = get_user_model().objects.create_user(username="other")
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        self.client.credentials(HTTP_X_API_KEY=other.token)
        self.assertFalse(self.client.get(self.url).json()["watched"])


class ChangeFeedTests(WatchedStateAPITestCase):
    def test_changes_are_returned_in_server_order_with_a_cursor(self):
        for watched in (True, False, True):
            self.client.put(
                self.url,
                data={"watched": watched},
                content_type="application/json",
            )

        payload = self.client.get(reverse("api_sync_changes")).json()

        sequences = [entry["sequence"] for entry in payload["results"]]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(payload["next_cursor"], sequences[-1])

    def test_a_cursor_returns_only_later_changes(self):
        for watched in (True, False):
            self.client.put(
                self.url,
                data={"watched": watched},
                content_type="application/json",
            )

        first = self.client.get(reverse("api_sync_changes")).json()
        cursor = first["results"][0]["sequence"]

        payload = self.client.get(
            reverse("api_sync_changes"),
            {"cursor": cursor},
        ).json()

        self.assertTrue(
            all(entry["sequence"] > cursor for entry in payload["results"]),
        )

    def test_a_bad_cursor_is_rejected(self):
        response = self.client.get(
            reverse("api_sync_changes"),
            {"cursor": "abc"},
        )

        self.assertEqual(response.status_code, 400)

    def test_one_users_feed_never_contains_anothers_changes(self):
        other = get_user_model().objects.create_user(username="other")
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        self.client.credentials(HTTP_X_API_KEY=other.token)
        payload = self.client.get(reverse("api_sync_changes")).json()

        self.assertEqual(payload["results"], [])


class ConnectionsTests(WatchedStateAPITestCase):
    def test_unavailable_capabilities_are_named_rather_than_omitted(self):
        """A direction the user asked for and cannot have must be visible.

        Saying nothing about it reads as success, which is exactly the
        "completed two-way sync" claim this program must not make.
        """
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.STREMIO.value,
            instance_key="s",
            profile_key="u",
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        payload = self.client.get(reverse("api_sync_connections")).json()

        entry = payload["results"][0]
        self.assertEqual(entry["client_kind"], SyncClientKind.STREMIO.value)
        self.assertEqual(entry["capabilities"], [])
        self.assertEqual(
            entry["unavailable_capabilities"],
            [CAPABILITY_WATCHED_READ],
        )


class ConflictTests(WatchedStateAPITestCase):
    def _conflict(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        return StateConflict.objects.create(
            user=self.user,
            item=self.item,
            binding=binding,
            reason=StateConflictReason.DIVERGENT_WATCHED.value,
            local_snapshot={"watched": True},
            remote_snapshot={"watched": False},
        )

    def test_open_conflicts_are_listed_with_both_sides(self):
        self._conflict()

        payload = self.client.get(reverse("api_sync_conflicts")).json()

        entry = payload["results"][0]
        self.assertEqual(entry["reason"], StateConflictReason.DIVERGENT_WATCHED.value)
        self.assertEqual(entry["local"], {"watched": True})
        self.assertEqual(entry["remote"], {"watched": False})

    def test_resolving_records_the_chosen_state_and_closes_the_conflict(self):
        conflict = self._conflict()

        response = self.client.post(
            reverse(
                "api_sync_conflict_resolve",
                kwargs={"conflict_id": conflict.pk},
            ),
            data={"watched": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, StateConflictStatus.RESOLVED.value)
        state = effective_state(self.user, self.item)
        self.assertTrue(state.watched)
        self.assertFalse(state.conflicted)
        self.assertEqual(state.origin_kind, WatchStateOrigin.LOCAL_UI.value)

    def test_resolving_an_unknown_conflict_is_not_found(self):
        response = self.client.post(
            reverse("api_sync_conflict_resolve", kwargs={"conflict_id": 9999}),
            data={"watched": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_another_users_conflict_is_not_resolvable(self):
        conflict = self._conflict()
        other = get_user_model().objects.create_user(username="other")
        self.client.credentials(HTTP_X_API_KEY=other.token)

        response = self.client.post(
            reverse(
                "api_sync_conflict_resolve",
                kwargs={"conflict_id": conflict.pk},
            ),
            data={"watched": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
