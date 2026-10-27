"""The watched-state API: assertions, not plays.

Setting unwatched through this surface must never delete history, and setting
watched must never fabricate a playback session. Those two properties are the
reason the endpoint exists separately from the playback and history routes.
"""

import datetime
import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from api import fork_views_watched_state as api_views
from api import scopes as api_scopes
from app.models import (
    BackfillReconcileState,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Sources,
    Status,
    WatchState,
    WatchStateChange,
    WatchStateOrigin,
    WatchStateSequence,
)
from app.services.episode_ordering import persist_order
from app.services.watch_state import effective_state, record_state_change
from app.tasks_watch_state import REPAIR_KEY, REPAIR_VERSION, repair_watch_state
from integrations.models import (
    CAPABILITY_WATCHED_PULL,
    CAPABILITY_WATCHED_READ,
    IntegrationToken,
    OutboundStateDelivery,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncBinding,
    SyncBindingStatus,
    SyncCheckpoint,
    SyncClientKind,
    SyncDirection,
)
from integrations.state.checkpoints import (
    compaction_watermark,
    record_applied_position,
    reset_pull_positions,
)
from integrations.state.identity import (
    activate_binding,
    deactivate_binding,
    get_or_create_binding,
)


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day):
    return datetime.datetime(2026, 7, day, 12, tzinfo=datetime.UTC)


def make_pull_binding(user, instance_key="kodi-test"):
    """Return an active pull-only Kodi binding, as registration would leave it."""
    binding, _ = get_or_create_binding(
        user,
        SyncClientKind.KODI.value,
        instance_key=instance_key,
    )
    activate_binding(
        binding,
        capabilities=[CAPABILITY_WATCHED_PULL],
        directions=[SyncDirection.OUTBOUND.value],
    )
    return binding


def mark_repair_complete():
    """Record that the one-time watched-state repair has finished."""
    BackfillReconcileState.objects.update_or_create(
        key=REPAIR_KEY,
        defaults={
            "strategy_version": REPAIR_VERSION,
            "completed_at": timezone.now(),
        },
    )


class WatchedStateAPITestCase(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        mark_repair_complete()
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

    def test_repeating_watched_a_second_later_is_still_unchanged(self):
        """Re-sending the same state must not depend on the clock ticking over."""
        clock = [timezone.now().replace(microsecond=0)]
        with patch("django.utils.timezone.now", side_effect=lambda: clock[0]):
            self.client.put(
                self.url,
                data={"watched": True},
                content_type="application/json",
            )
            clock[0] += datetime.timedelta(seconds=2)
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

    def test_an_unusable_limit_is_rejected(self):
        for limit in ("0", "-1", "abc", ""):
            with self.subTest(limit=limit):
                response = self.client.get(
                    reverse("api_sync_changes"),
                    {"limit": limit},
                )
                self.assertEqual(response.status_code, 400)

    def test_an_oversized_limit_is_clamped_not_refused(self):
        """Existing clients that ask for more than the cap keep working."""
        response = self.client.get(reverse("api_sync_changes"), {"limit": 100000})

        self.assertEqual(response.status_code, 200)

    def test_an_integer_cursor_keeps_working_after_registration(self):
        """Registering must not change what a legacy integer cursor means."""
        self.client.post(
            reverse("api_sync_connections"),
            data={"instance_key": "kodi-legacy"},
            format="json",
        )
        self.client.put(
            self.url,
            data={"watched": True},
            content_type="application/json",
        )

        payload = self.client.get(reverse("api_sync_changes"), {"cursor": 0}).json()

        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["next_cursor"], payload["results"][0]["sequence"])


class ChangeFeedEpisodeIdentityTests(WatchedStateAPITestCase):
    def test_an_episode_change_names_its_season_and_episode(self):
        """Episodes share their show's media_id, so the feed must say which one."""
        Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            provider_external_ids={"tmdb_id": 1396, "imdb_id": "tt0903747"},
        )
        episode = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 3",
            season_number=2,
            episode_number=3,
        )
        record_state_change(
            self.user,
            episode,
            watched=True,
            origin_kind=WatchStateOrigin.LOCAL_API.value,
        )

        row = self.client.get(reverse("api_sync_changes")).json()["results"][-1]

        self.assertEqual((row["season_number"], row["episode_number"]), (2, 3))
        self.assertEqual(row["ids"], {"tmdb": "1396", "imdb": "tt0903747"})


class WatchedSnapshotTests(WatchedStateAPITestCase):
    """The compact snapshot a pull client rebuilds its watched cache from."""

    def setUp(self):
        super().setUp()
        self.snapshot_url = reverse("api_sync_watched_state")
        self.binding = make_pull_binding(self.user)
        self.show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            provider_external_ids={"tmdb_id": 1396, "imdb_id": "tt0903747"},
        )

    def _snapshot(self, params=None):
        """Call the snapshot as the registered pull connection."""
        query = {"connection": self.binding.origin_key, **(params or {})}
        return self.client.get(self.snapshot_url, query)

    def _watch(self, item, user=None, *, watched=True):
        return record_state_change(
            user or self.user,
            item,
            watched=watched,
            play_count=1 if watched else 0,
            watched_at=_dt(1) if watched else None,
            origin_kind=WatchStateOrigin.LOCAL_API.value,
        )

    def _movie(self, number):
        return Item.objects.create(
            media_id=str(10_000 + number),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {number}",
        )

    def _episode(self, season, episode):
        return Item.objects.create(
            media_id=self.show.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title=f"Episode {episode}",
            season_number=season,
            episode_number=episode,
        )

    def _walk(self, **params):
        """Return every row of a snapshot, page by page, plus the pages."""
        pages = []
        query = dict(params)
        while True:
            payload = self._snapshot(query).json()
            pages.append(payload)
            if not payload["has_more"]:
                break
            query["cursor"] = payload["next_cursor"]
            query["resume_cursor"] = payload["resume_cursor"]
        return [row for page in pages for row in page["results"]], pages

    def test_a_movie_row_is_compact(self):
        self._watch(self.item)

        payload = self._snapshot().json()

        self.assertEqual(
            set(payload),
            {"results", "next_cursor", "has_more", "resume_cursor"},
        )
        self.assertEqual(
            payload["results"],
            [
                {
                    "media_id": "603",
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "season_number": None,
                    "episode_number": None,
                    "ids": {},
                    "numbering": "provider",
                    "episode_order_id": None,
                    "title": "The Matrix",
                    "series_title": None,
                    "play_count": 1,
                    "last_watched_at": "2026-07-01T12:00:00Z",
                    "watched_at": "2026-07-01T12:00:00Z",
                },
            ],
        )

    def test_an_episode_row_names_its_show_season_and_episode(self):
        self._watch(self._episode(2, 3))

        row = self._snapshot().json()["results"][0]

        self.assertEqual(row["media_type"], MediaTypes.EPISODE.value)
        self.assertEqual((row["season_number"], row["episode_number"]), (2, 3))
        self.assertEqual(row["ids"], {"tmdb": "1396", "imdb": "tt0903747"})
        self.assertEqual(row["series_title"], "Breaking Bad")

    def test_a_row_matches_the_change_feed_identity_for_the_same_item(self):
        self._watch(self._episode(2, 3))

        snapshot = self._snapshot().json()["results"][0]
        change = self.client.get(reverse("api_sync_changes")).json()["results"][0]

        for key in ("media_id", "source", "media_type", "season_number"):
            self.assertEqual(snapshot[key], change[key])
        self.assertEqual(snapshot["episode_number"], change["episode_number"])
        self.assertEqual(snapshot["ids"], change["ids"])

    def test_only_watched_movies_and_episodes_are_returned(self):
        watched_movie = self.item
        self._watch(watched_movie)
        self._watch(self._movie(1), watched=False)
        self._watch(self._episode(1, 1))
        self._watch(self.show)
        self._watch(
            Item.objects.create(
                media_id="1396",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Season 1",
                season_number=1,
            ),
        )

        rows, _ = self._walk()

        self.assertCountEqual(
            [(row["media_type"], row["media_id"]) for row in rows],
            [
                (MediaTypes.MOVIE.value, "603"),
                (MediaTypes.EPISODE.value, "1396"),
            ],
        )

    def test_another_users_states_are_never_returned(self):
        other = get_user_model().objects.create_user(username="other")
        self._watch(self.item, other)

        self.assertEqual(self._snapshot().json()["results"], [])

        self.client.credentials(HTTP_X_API_KEY=other.token)
        theirs = make_pull_binding(other)
        rows = self._snapshot({"connection": theirs.origin_key}).json()["results"]
        self.assertEqual(len(rows), 1)

    def test_pages_cover_every_row_once_in_stable_item_order(self):
        items = [self._movie(number) for number in range(5)]
        for item in reversed(items):
            self._watch(item)

        rows, pages = self._walk(limit=2)

        self.assertEqual(len(pages), 3)
        self.assertEqual(
            [row["media_id"] for row in rows],
            [item.media_id for item in items],
        )
        self.assertEqual([page["has_more"] for page in pages], [True, True, False])

    def test_an_exact_multiple_of_the_page_size_ends_without_a_phantom_page(self):
        for number in range(4):
            self._watch(self._movie(number))

        _, pages = self._walk(limit=2)

        self.assertEqual([page["has_more"] for page in pages], [True, False])
        self.assertEqual(len(pages[-1]["results"]), 2)

    def test_an_empty_snapshot_resumes_from_zero(self):
        payload = self._snapshot().json()

        self.assertEqual(payload["results"], [])
        self.assertFalse(payload["has_more"])
        self.assertEqual(payload["resume_cursor"], 0)

    def test_the_resume_cursor_is_the_sequence_when_the_snapshot_began(self):
        self._watch(self._movie(1))
        self._watch(self._movie(2))
        newest = WatchStateSequence.objects.get(user=self.user).last_sequence

        payload = self._snapshot().json()

        self.assertEqual(payload["resume_cursor"], newest)
        self.assertGreater(newest, 0)

    def test_a_change_between_pages_is_recovered_from_the_resume_cursor(self):
        """No gap: whatever moves after page one is in the feed from the cursor."""
        served = self._movie(1)
        untouched = self._movie(2)
        added_later = self._movie(3)
        self._watch(served)
        self._watch(untouched)
        first = self._snapshot({"limit": 1}).json()
        resume = first["resume_cursor"]

        self._watch(served, watched=False)
        self._watch(added_later)
        second = self._snapshot(
            {
                "limit": 100,
                "cursor": first["next_cursor"],
                "resume_cursor": resume,
            },
        ).json()
        feed = self.client.get(reverse("api_sync_changes"), {"cursor": resume}).json()

        self.assertEqual(second["resume_cursor"], resume)
        self.assertEqual(
            {entry["media_id"] for entry in feed["results"]},
            {served.media_id, added_later.media_id},
        )
        self.assertTrue(
            all(entry["sequence"] > resume for entry in feed["results"]),
        )

    def test_a_later_page_requires_the_resume_cursor(self):
        self._watch(self.item)

        response = self._snapshot({"cursor": 1})

        self.assertEqual(response.status_code, 400)

    def test_unusable_limits_and_cursors_are_rejected(self):
        for params in (
            {"limit": "0"},
            {"limit": "-1"},
            {"limit": "abc"},
            {"limit": ""},
            {"cursor": "abc", "resume_cursor": "0"},
            {"cursor": "-1", "resume_cursor": "0"},
            {"cursor": "1", "resume_cursor": "abc"},
            {"cursor": "1", "resume_cursor": "-1"},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self._snapshot(params).status_code,
                    400,
                )

    def test_an_oversized_limit_is_clamped(self):
        for number in range(3):
            self._watch(self._movie(number))

        response = self._snapshot({"limit": 10_000_000})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 3)

    def test_a_page_costs_the_same_queries_however_many_rows_it_holds(self):
        def page_queries():
            with CaptureQueriesContext(connection) as queries:
                self._snapshot()
            return len(queries)

        # The first call creates the pin; every later one only refreshes it.
        page_queries()

        for number in range(2):
            self._watch(self._movie(number))
            self._watch(self._episode(1, number + 1))
        small = page_queries()
        for number in range(2, 12):
            self._watch(self._movie(number))
            self._watch(self._episode(1, number + 1))

        self.assertEqual(page_queries(), small)

    def test_a_default_tracking_token_can_read_the_snapshot(self):
        _, secret = IntegrationToken.generate(user=self.user, name="Kodi")
        self.client.credentials(HTTP_X_API_KEY=secret)

        self.assertEqual(self._snapshot().status_code, 200)

    def test_a_token_without_sync_read_is_refused(self):
        _, secret = IntegrationToken.generate(
            user=self.user,
            name="Narrow",
            scopes=["catalog:read"],
        )
        self.client.credentials(HTTP_X_API_KEY=secret)

        self.assertEqual(self._snapshot().status_code, 403)

    def test_the_snapshot_requires_authentication(self):
        self.client.credentials()

        self.assertIn(self._snapshot().status_code, (401, 403))


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


class RegisterConnectionTests(WatchedStateAPITestCase):
    """A pull client names itself once and is bound to read-only change emission."""

    def setUp(self):
        super().setUp()
        self.register_url = reverse("api_sync_connections")
        self.body = {"instance_key": "kodi-0123456789abcdef", "label": "Living room"}

    def _register(self, body=None):
        return self.client.post(
            self.register_url,
            data=self.body if body is None else body,
            format="json",
        )

    def test_registering_creates_an_active_pull_only_kodi_binding(self):
        response = self._register()

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["client_kind"], SyncClientKind.KODI.value)
        self.assertEqual(payload["status"], SyncBindingStatus.ACTIVE.value)
        self.assertEqual(payload["capabilities"], [CAPABILITY_WATCHED_PULL])
        self.assertEqual(payload["directions"], [SyncDirection.OUTBOUND.value])
        self.assertTrue(payload["origin_key"])
        self.assertTrue(payload["resnapshot_required"])
        binding = SyncBinding.objects.get(user=self.user)
        self.assertEqual(binding.origin_key, payload["origin_key"])
        self.assertEqual(binding.instance_key, self.body["instance_key"])
        self.assertEqual(binding.label, "Living room")

    def test_registering_turns_change_emission_on(self):
        self._register()

        self.assertTrue(
            WatchStateSequence.objects.get(user=self.user).emit_changes,
        )

    def test_registering_twice_returns_the_same_binding(self):
        first = self._register().json()
        second = self._register()

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["id"], first["id"])
        self.assertEqual(second.json()["origin_key"], first["origin_key"])
        self.assertEqual(SyncBinding.objects.filter(user=self.user).count(), 1)

    def test_a_disabled_binding_stays_disabled_and_is_reported(self):
        """The user chose Off; a client's next call must not undo that."""
        first = self._register().json()
        SyncBinding.objects.filter(pk=first["id"]).update(
            status=SyncBindingStatus.DISABLED.value,
        )

        response = self._register()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "connection_inactive")
        self.assertEqual(response.json()["reason"], "disabled")
        self.assertEqual(
            SyncBinding.objects.get(pk=first["id"]).status,
            SyncBindingStatus.DISABLED.value,
        )

    def test_a_binding_needing_reapproval_is_not_reactivated(self):
        first = self._register().json()
        SyncBinding.objects.filter(pk=first["id"]).update(
            status=SyncBindingStatus.NEEDS_REAPPROVAL.value,
        )

        response = self._register()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "needs_reapproval")
        self.assertEqual(
            SyncBinding.objects.get(pk=first["id"]).status,
            SyncBindingStatus.NEEDS_REAPPROVAL.value,
        )

    def test_registering_does_not_override_a_kill_switch(self):
        first = self._register().json()
        SyncBinding.objects.filter(pk=first["id"]).update(kill_switch=True)

        response = self._register()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "connection_inactive")
        self.assertEqual(response.json()["reason"], "kill_switch")
        self.assertTrue(SyncBinding.objects.get(pk=first["id"]).kill_switch)

    def test_a_pending_binding_is_activated_and_its_stale_position_dropped(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.KODI.value,
            instance_key=self.body["instance_key"],
        )
        record_applied_position(binding, 7)

        response = self._register()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SyncBindingStatus.ACTIVE.value)
        self.assertTrue(response.json()["resnapshot_required"])
        self.assertFalse(SyncCheckpoint.objects.filter(binding=binding).exists())

    def test_registering_merges_into_an_existing_approval_without_narrowing(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.KODI.value,
            instance_key=self.body["instance_key"],
        )
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ, "play.push"],
            directions=[SyncDirection.INBOUND.value, SyncDirection.OUTBOUND.value],
        )

        response = self._register()

        self.assertEqual(response.status_code, 200)
        binding.refresh_from_db()
        self.assertEqual(
            binding.approved_capabilities,
            ["play.push", CAPABILITY_WATCHED_PULL, CAPABILITY_WATCHED_READ],
        )
        self.assertEqual(
            sorted(binding.approved_directions),
            [SyncDirection.INBOUND.value, SyncDirection.OUTBOUND.value],
        )

    def test_re_registering_updates_a_renamed_label(self):
        self._register()

        response = self._register({**self.body, "label": "Bedroom"})

        self.assertEqual(response.json()["label"], "Bedroom")
        self.assertEqual(SyncBinding.objects.get(user=self.user).label, "Bedroom")

    def test_re_registering_a_pinned_binding_does_not_ask_for_a_resnapshot(self):
        first = self._register().json()
        record_applied_position(SyncBinding.objects.get(pk=first["id"]), 3)

        self.assertFalse(self._register().json()["resnapshot_required"])

    def test_another_user_registering_the_same_key_gets_their_own_binding(self):
        mine = self._register().json()
        other = get_user_model().objects.create_user(username="other")
        self.client.credentials(HTTP_X_API_KEY=other.token)

        theirs = self._register()

        self.assertEqual(theirs.status_code, 201)
        self.assertNotEqual(theirs.json()["origin_key"], mine["origin_key"])
        self.assertEqual(SyncBinding.objects.filter(user=other).count(), 1)
        self.assertEqual(SyncBinding.objects.filter(user=self.user).count(), 1)

    def test_a_registered_binding_appears_in_the_connections_list(self):
        registered = self._register().json()

        listed = self.client.get(self.register_url).json()["results"]

        self.assertEqual([row["id"] for row in listed], [registered["id"]])
        self.assertEqual(listed[0]["capabilities"], [CAPABILITY_WATCHED_PULL])
        self.assertEqual(listed[0]["unavailable_capabilities"], [])

    def test_a_missing_or_malformed_body_is_rejected_with_a_specific_message(self):
        for body, expected in (
            ({}, "instance_key"),
            ({"instance_key": ""}, "instance_key"),
            ({"instance_key": "   "}, "instance_key"),
            ({"instance_key": 12}, "instance_key"),
            ({"instance_key": "x" * 256}, "instance_key"),
            ({"instance_key": " " + "x" * 255}, None),
            ({"instance_key": "kodi", "label": 5}, "label"),
            ({"instance_key": "kodi", "label": "x" * 256}, "label"),
            (["instance_key"], "JSON object"),
        ):
            with self.subTest(body=body):
                response = self._register(body)
                if expected is None:
                    # Stripped, it fits: judged by what is stored, not what was sent.
                    self.assertEqual(response.status_code, 201)
                    continue
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, response.json()["detail"])
        self.assertEqual(SyncBinding.objects.filter(user=self.user).count(), 1)

    def test_registration_requires_authentication(self):
        self.client.credentials()

        self.assertIn(self._register().status_code, (401, 403))

    def test_a_default_tracking_token_cannot_register(self):
        """Registering turns on a write per save, so it is a write scope."""
        _, secret = IntegrationToken.generate(user=self.user, name="Kodi")
        self.client.credentials(HTTP_X_API_KEY=secret)

        self.assertEqual(self._register().status_code, 403)
        self.assertFalse(SyncBinding.objects.filter(user=self.user).exists())

    def test_a_pull_sync_token_can_register_and_snapshot(self):
        _, secret = IntegrationToken.generate(
            user=self.user,
            name="Umbrella",
            scopes=list(api_scopes.PULL_SYNC_PRESET),
        )
        self.client.credentials(HTTP_X_API_KEY=secret)

        registered = self._register()

        self.assertEqual(registered.status_code, 201)
        snapshot = self.client.get(
            reverse("api_sync_watched_state"),
            {"connection": registered.json()["origin_key"]},
        )
        self.assertEqual(snapshot.status_code, 200)

    def test_the_pull_sync_preset_adds_only_sync_write(self):
        self.assertEqual(
            set(api_scopes.PULL_SYNC_PRESET),
            set(api_scopes.TRACKING_PRESET) | {"sync:write"},
        )

    def test_registrations_per_user_are_capped(self):
        for number in range(api_views.MAX_PULL_CONNECTIONS):
            self.assertEqual(
                self._register({"instance_key": f"device-{number}"}).status_code,
                201,
            )

        refused = self._register({"instance_key": "one-too-many"})

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "connection_limit")
        self.assertEqual(
            self._register({"instance_key": "device-0"}).status_code,
            200,
        )
        self.assertEqual(
            SyncBinding.objects.filter(user=self.user).count(),
            api_views.MAX_PULL_CONNECTIONS,
        )

    def test_the_cap_is_per_user(self):
        for number in range(api_views.MAX_PULL_CONNECTIONS):
            self._register({"instance_key": f"device-{number}"})
        other = get_user_model().objects.create_user(username="other")
        self.client.credentials(HTTP_X_API_KEY=other.token)

        self.assertEqual(self._register().status_code, 201)

    def test_changes_after_registering_are_logged_but_never_delivered(self):
        self._register()

        record_state_change(
            self.user,
            self.item,
            watched=True,
            origin_kind=WatchStateOrigin.LOCAL_API.value,
        )

        self.assertEqual(
            WatchStateChange.objects.filter(user=self.user).count(),
            1,
        )
        self.assertFalse(OutboundStateDelivery.objects.exists())


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


class PullSyncTestCase(WatchedStateAPITestCase):
    """A registered pull client reading the snapshot and the named feed."""

    def setUp(self):
        super().setUp()
        self.snapshot_url = reverse("api_sync_watched_state")
        self.feed_url = reverse("api_sync_changes")
        self.binding = make_pull_binding(self.user)

    def _snapshot(self, params=None, *, connection=None):
        query = {"connection": connection or self.binding.origin_key, **(params or {})}
        return self.client.get(self.snapshot_url, query)

    def _feed(self, cursor, **params):
        query = {"connection": self.binding.origin_key, "cursor": cursor, **params}
        return self.client.get(self.feed_url, query)

    def _watch(self, item, *, watched=True):
        return record_state_change(
            self.user,
            item,
            watched=watched,
            play_count=1 if watched else 0,
            watched_at=_dt(1) if watched else None,
            origin_kind=WatchStateOrigin.LOCAL_API.value,
        )

    def _movie(self, number):
        return Item.objects.create(
            media_id=str(20_000 + number),
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Movie {number}",
        )

    def _pinned(self):
        return SyncCheckpoint.objects.filter(binding=self.binding).first()


class PullConnectionGateTests(PullSyncTestCase):
    """The snapshot and the named feed only serve a live, emitting pull connection."""

    def test_the_snapshot_requires_a_connection(self):
        response = self.client.get(self.snapshot_url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "connection_required")

    def test_an_unknown_connection_must_register_again(self):
        theirs, _ = get_or_create_binding(
            get_user_model().objects.create_user(username="other"),
            SyncClientKind.KODI.value,
            instance_key="theirs",
        )
        for origin_key in ("nope", theirs.origin_key):
            with self.subTest(connection=origin_key):
                response = self._snapshot(connection=origin_key)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["code"], "connection_inactive")
                self.assertEqual(response.json()["reason"], "missing")

    def test_a_binding_that_is_not_a_pull_connection_is_refused(self):
        other, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        activate_binding(
            other,
            capabilities=[CAPABILITY_WATCHED_READ],
            directions=[SyncDirection.INBOUND.value],
        )

        response = self._snapshot(connection=other.origin_key)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "not_pull")

    def test_an_inactive_connection_is_refused_with_the_reason(self):
        for reason, prepare in (
            ("disabled", lambda: deactivate_binding(self.binding)),
            (
                "needs_reapproval",
                lambda: SyncBinding.objects.filter(pk=self.binding.pk).update(
                    status=SyncBindingStatus.NEEDS_REAPPROVAL.value,
                ),
            ),
            (
                "kill_switch",
                lambda: SyncBinding.objects.filter(pk=self.binding.pk).update(
                    kill_switch=True,
                ),
            ),
        ):
            with self.subTest(reason=reason):
                make_pull_binding(self.user)
                SyncBinding.objects.filter(pk=self.binding.pk).update(
                    status=SyncBindingStatus.ACTIVE.value,
                    kill_switch=False,
                    disabled_at=None,
                )
                self.binding.refresh_from_db()
                prepare()

                for response in (self._snapshot(), self._feed(0)):
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()["code"], "connection_inactive")
                    self.assertEqual(response.json()["reason"], reason)

    def test_a_snapshot_is_refused_while_change_emission_is_off(self):
        """A cursor for a log nobody is writing is a gap the client cannot see."""
        WatchStateSequence.objects.filter(user=self.user).update(emit_changes=False)

        response = self._snapshot()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "emission_off")
        self.assertIsNone(self._pinned())

    def test_a_named_feed_for_an_unknown_connection_is_refused(self):
        response = self.client.get(
            self.feed_url,
            {"connection": "nope", "cursor": 0},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "cursor_expired")
        self.assertEqual(response.json()["reason"], "connection_missing")

    def test_a_snapshot_for_an_unknown_connection_still_says_inactive(self):
        response = self._snapshot(connection="nope")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "connection_inactive")
        self.assertEqual(response.json()["reason"], "missing")

    def test_an_unnamed_legacy_feed_pull_is_unchanged(self):
        self._watch(self._movie(1))

        response = self.client.get(self.feed_url, {"cursor": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_a_named_feed_before_any_snapshot_must_snapshot_first(self):
        self._watch(self._movie(1))

        response = self._feed(0)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "cursor_expired")

    def test_a_named_non_pull_feed_keeps_its_existing_behaviour(self):
        """Nuvio-style bindings pass `connection` without a snapshot."""
        other, _ = get_or_create_binding(
            self.user,
            SyncClientKind.STREMIO.value,
            instance_key="s",
            profile_key="u",
        )
        activate_binding(
            other,
            capabilities=["watched.push_played"],
            directions=[SyncDirection.OUTBOUND.value],
        )
        self._watch(self._movie(1))

        response = self.client.get(
            self.feed_url,
            {"connection": other.origin_key, "cursor": 0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)


class PullGapTests(PullSyncTestCase):
    """A period with the log off, or a reset binding, can never be pulled across."""

    def test_a_disable_write_reenable_cycle_forces_a_resnapshot(self):
        first = self._watch(self._movie(1))
        pinned = self._snapshot().json()["resume_cursor"]
        self.assertEqual(self._feed(pinned).status_code, 200)

        deactivate_binding(self.binding)
        # A UI write: it reaches the legacy store, and the projection records
        # it as a change only while the log is on.
        missed = self._movie(2)
        Movie.objects.create(
            item=missed,
            user=self.user,
            status=Status.COMPLETED.value,
            end_date=_dt(2),
        )
        self.assertFalse(
            WatchStateChange.objects.filter(item=missed).exists(),
            "the log is off, so this write left no change row",
        )
        self.assertTrue(effective_state(self.user, missed).watched)
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_WATCHED_PULL],
            directions=[SyncDirection.OUTBOUND.value],
        )

        stale = self._feed(pinned)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "cursor_expired")

        fresh = self._snapshot().json()
        self.assertEqual(
            {row["media_id"] for row in fresh["results"]},
            {first.state.item.media_id, missed.media_id},
        )
        self.assertEqual(self._feed(fresh["resume_cursor"]).status_code, 200)

    def test_a_feed_acknowledgement_advances_the_snapshot_checkpoint(self):
        pinned = self._snapshot().json()["resume_cursor"]

        self.assertEqual(self._feed(pinned + 3).status_code, 200)

        self.assertEqual(self._pinned().last_sequence, pinned + 3)

    def test_a_feed_acknowledgement_never_recreates_a_voided_checkpoint(self):
        """A request that passed the gate before a void must not undo it."""
        pinned = self._snapshot().json()["resume_cursor"]
        reset_pull_positions(self.user)
        self.assertIsNone(self._pinned())

        with patch.object(api_views.WatchedStateChangeFeedView, "_pull_problem", return_value=None):
            self.assertEqual(self._feed(pinned + 3).status_code, 200)

        self.assertIsNone(self._pinned())

    def test_registering_a_pending_binding_drops_any_old_position(self):
        record_applied_position(self.binding, 4)
        SyncBinding.objects.filter(pk=self.binding.pk).update(
            status=SyncBindingStatus.PENDING.value,
        )

        response = self.client.post(
            reverse("api_sync_connections"),
            data={"instance_key": self.binding.instance_key},
            format="json",
        )

        self.assertTrue(response.json()["resnapshot_required"])
        self.assertIsNone(self._pinned())

    def test_a_second_live_binding_keeps_the_log_and_the_position(self):
        """Disabling one client must not reset another that never lost changes."""
        other = make_pull_binding(self.user, "second")
        self._watch(self._movie(1))
        pinned = self._snapshot().json()["resume_cursor"]

        deactivate_binding(other)

        self.assertEqual(self._feed(pinned).status_code, 200)


class SnapshotCheckpointTests(PullSyncTestCase):
    """The snapshot pins the sequence the named feed resumes from."""

    def test_the_first_page_pins_the_resume_cursor_as_the_checkpoint(self):
        self._watch(self._movie(1))
        self._watch(self._movie(2))

        payload = self._snapshot().json()

        self.assertEqual(self._pinned().last_sequence, payload["resume_cursor"])
        self.assertGreater(payload["resume_cursor"], 0)

    def test_a_pinned_snapshot_holds_back_compaction(self):
        for number in range(3):
            self._watch(self._movie(number))
        payload = self._snapshot().json()

        self.assertEqual(
            compaction_watermark(self.user),
            payload["resume_cursor"],
        )

    def test_cursor_zero_is_expired_once_the_early_log_is_compacted(self):
        payload = self._snapshot().json()
        self.assertEqual(payload["resume_cursor"], 0)
        self.assertEqual(self._pinned().last_sequence, 0)
        for number in range(3):
            self._watch(self._movie(number))
        WatchStateChange.objects.filter(user=self.user, sequence__lte=2).delete()

        response = self._feed(0)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "cursor_expired")

    def test_cursor_zero_is_still_served_when_nothing_was_compacted(self):
        self._snapshot()
        self._watch(self._movie(1))

        response = self._feed(0)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_legacy_unnamed_cursor_zero_is_served_after_compaction(self):
        for number in range(3):
            self._watch(self._movie(number))
        WatchStateChange.objects.filter(user=self.user, sequence__lte=2).delete()

        response = self.client.get(self.feed_url, {"cursor": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_a_resnapshot_at_the_same_sequence_refreshes_the_pin(self):
        self._snapshot()
        SyncCheckpoint.objects.filter(binding=self.binding).update(
            updated_at=_dt(1),
        )

        self._snapshot()

        self.assertGreater(self._pinned().updated_at, _dt(2))

    def test_a_forged_resume_cursor_on_a_later_page_is_refused(self):
        for number in range(3):
            self._watch(self._movie(number))
        first = self._snapshot({"limit": 1}).json()

        response = self._snapshot(
            {
                "cursor": first["next_cursor"],
                "resume_cursor": first["resume_cursor"] + 50,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_resume_cursor")

    def test_a_later_page_after_the_pin_was_dropped_must_restart(self):
        for number in range(3):
            self._watch(self._movie(number))
        first = self._snapshot({"limit": 1}).json()
        SyncCheckpoint.objects.filter(binding=self.binding).delete()

        response = self._snapshot(
            {
                "cursor": first["next_cursor"],
                "resume_cursor": first["resume_cursor"],
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "cursor_expired")

    def test_a_later_page_does_not_move_the_pin(self):
        for number in range(3):
            self._watch(self._movie(number))
        first = self._snapshot({"limit": 1}).json()
        pinned = self._pinned().last_sequence

        self._snapshot(
            {
                "cursor": first["next_cursor"],
                "resume_cursor": first["resume_cursor"],
            },
        )

        self.assertEqual(self._pinned().last_sequence, pinned)


class WatchedTimestampAndNumberingTests(PullSyncTestCase):
    """Field names line up, and custom numbering is flagged so clients can skip it."""

    def test_snapshot_and_feed_carry_both_timestamp_names(self):
        movie = self._movie(1)
        self._watch(movie)

        snapshot_row = self._snapshot().json()["results"][0]
        # The pinned snapshot above makes the named feed servable from 0.
        feed_row = self._feed(0).json()["results"][0]

        self.assertEqual(snapshot_row["watched_at"], snapshot_row["last_watched_at"])
        self.assertIsNotNone(snapshot_row["watched_at"])
        self.assertEqual(feed_row["last_watched_at"], feed_row["watched_at"])
        self.assertIsNotNone(feed_row["last_watched_at"])

    def test_a_provider_numbered_episode_is_marked_provider(self):
        show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        episode = Item.objects.create(
            media_id=show.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            season_number=1,
            episode_number=1,
        )
        self._watch(episode)

        row = self._snapshot().json()["results"][0]

        self.assertEqual(row["numbering"], "provider")
        self.assertIsNone(row["episode_order_id"])

    def test_a_custom_ordered_episode_is_marked_custom_in_both_surfaces(self):
        show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        order = persist_order(
            show,
            Sources.TMDB.value,
            "1396",
            "aired",
            "TMDB (Aired)",
            {
                "episodes": [
                    {
                        "provider_episode_id": "new-1",
                        "season_number": 1,
                        "episode_number": 1,
                        "title": "Pilot",
                        "image": "",
                    },
                ],
            },
        )
        episode = Item.objects.create(
            media_id=show.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            season_number=1,
            episode_number=1,
            episode_order=order,
        )
        self._watch(episode)

        snapshot_row = self._snapshot().json()["results"][0]
        feed_row = self._feed(0).json()["results"][0]

        for row in (snapshot_row, feed_row):
            self.assertEqual(row["numbering"], "custom")
            self.assertEqual(row["episode_order_id"], order.pk)


class ProjectionRepairGateTests(PullSyncTestCase):
    """While the projection is being repaired the snapshot would be short."""

    def _repair_running(self):
        BackfillReconcileState.objects.filter(key=REPAIR_KEY).update(
            completed_at=None,
        )

    def test_a_snapshot_waits_for_the_repair_with_retry_after(self):
        self._repair_running()

        response = self._snapshot()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "projection_incomplete")
        self.assertIn("Retry-After", response)
        self.assertIsNone(self._pinned())

    def test_a_repair_for_an_older_version_still_counts_as_incomplete(self):
        BackfillReconcileState.objects.filter(key=REPAIR_KEY).update(
            strategy_version=REPAIR_VERSION - 1,
        )

        self.assertEqual(self._snapshot().status_code, 503)

    def test_a_per_user_completion_is_enough(self):
        self._repair_running()
        BackfillReconcileState.objects.create(
            key=f"{REPAIR_KEY}_user_{self.user.pk}",
            strategy_version=REPAIR_VERSION,
            completed_at=timezone.now(),
        )

        self.assertEqual(self._snapshot().status_code, 200)

    def test_a_named_feed_forces_a_resnapshot_while_the_repair_runs(self):
        pinned = self._snapshot().json()["resume_cursor"]
        self._repair_running()

        response = self._feed(pinned)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "cursor_expired")
        self.assertEqual(response.json()["reason"], "projection_incomplete")

    def test_finishing_a_users_repair_drops_pull_positions_taken_before(self):
        """Repair moves state without logging it, so older cursors are void."""
        self._snapshot()
        self.assertIsNotNone(self._pinned())
        BackfillReconcileState.objects.all().delete()

        repair_watch_state()

        self.assertIsNone(self._pinned())
        self.assertEqual(self._snapshot().status_code, 200)


@tag("slow", "benchmark")
class WatchedSnapshotScaleTests(PullSyncTestCase):
    """A large library costs one fixed set of queries per page, whatever the page."""

    WATCHED = 28_000
    TAIL = 4_000

    def setUp(self):
        super().setUp()
        items = Item.objects.bulk_create(
            Item(
                media_id=str(100_000 + number),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {number}",
            )
            for number in range(self.WATCHED + self.TAIL)
        )
        WatchState.objects.bulk_create(
            WatchState(
                user=self.user,
                item=item,
                watched=number < self.WATCHED,
                play_count=1 if number < self.WATCHED else 0,
                last_watched_at=_dt(1),
            )
            for number, item in enumerate(items)
        )

    def _page_queries(self, params):
        with CaptureQueriesContext(connection) as queries:
            response = self._snapshot(params)
        self.assertEqual(response.status_code, 200)
        return response.json(), [entry["sql"] for entry in queries]

    def test_every_page_costs_the_same_queries_and_the_walk_covers_the_library(self):
        first, first_sql = self._page_queries({"limit": 1000})
        later, later_sql = self._page_queries(
            {
                "limit": 1000,
                "cursor": first["next_cursor"],
                "resume_cursor": first["resume_cursor"],
            },
        )
        seen = len(first["results"]) + len(later["results"])
        cursor = later["next_cursor"]
        while True:
            page, _ = self._page_queries(
                {
                    "limit": 1000,
                    "cursor": cursor,
                    "resume_cursor": first["resume_cursor"],
                },
            )
            seen += len(page["results"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"]

        self.assertEqual(seen, self.WATCHED)
        # Measured at 28k watched rows, SQLite, movie pages: 11 queries on the
        # first page and 7 on later ones. Two are authentication, four are the
        # connection/emission/repair/pin gate, one is the page itself. The first
        # page also reads the sequence and creates the pin (4 queries in place
        # of the pin lookup); a page with episodes adds one query for the shows.
        self.assertLessEqual(len(first_sql), 11)
        self.assertLessEqual(len(later_sql), 7)
