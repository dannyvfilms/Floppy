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
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
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
    WatchStateSequence,
)
from app.services.watch_state import effective_state, record_state_change
from integrations.models import (
    CAPABILITY_WATCHED_READ,
    IntegrationToken,
    OutboundStateDelivery,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncBinding,
    SyncBindingStatus,
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
        self.show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            provider_external_ids={"tmdb_id": 1396, "imdb_id": "tt0903747"},
        )

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
            payload = self.client.get(self.snapshot_url, query).json()
            pages.append(payload)
            if not payload["has_more"]:
                break
            query["cursor"] = payload["next_cursor"]
            query["resume_cursor"] = payload["resume_cursor"]
        return [row for page in pages for row in page["results"]], pages

    def test_a_movie_row_is_compact(self):
        self._watch(self.item)

        payload = self.client.get(self.snapshot_url).json()

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
                    "title": "The Matrix",
                    "series_title": None,
                    "play_count": 1,
                    "last_watched_at": "2026-07-01T12:00:00Z",
                },
            ],
        )

    def test_an_episode_row_names_its_show_season_and_episode(self):
        self._watch(self._episode(2, 3))

        row = self.client.get(self.snapshot_url).json()["results"][0]

        self.assertEqual(row["media_type"], MediaTypes.EPISODE.value)
        self.assertEqual((row["season_number"], row["episode_number"]), (2, 3))
        self.assertEqual(row["ids"], {"tmdb": "1396", "imdb": "tt0903747"})
        self.assertEqual(row["series_title"], "Breaking Bad")

    def test_a_row_matches_the_change_feed_identity_for_the_same_item(self):
        self._watch(self._episode(2, 3))

        snapshot = self.client.get(self.snapshot_url).json()["results"][0]
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

        self.assertEqual(self.client.get(self.snapshot_url).json()["results"], [])

        self.client.credentials(HTTP_X_API_KEY=other.token)
        self.assertEqual(len(self.client.get(self.snapshot_url).json()["results"]), 1)

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
        payload = self.client.get(self.snapshot_url).json()

        self.assertEqual(payload["results"], [])
        self.assertFalse(payload["has_more"])
        self.assertEqual(payload["resume_cursor"], 0)

    def test_the_resume_cursor_is_the_sequence_when_the_snapshot_began(self):
        self._watch(self._movie(1))
        self._watch(self._movie(2))
        newest = WatchStateSequence.objects.get(user=self.user).last_sequence

        payload = self.client.get(self.snapshot_url).json()

        self.assertEqual(payload["resume_cursor"], newest)
        self.assertGreater(newest, 0)

    def test_a_change_between_pages_is_recovered_from_the_resume_cursor(self):
        """No gap: whatever moves after page one is in the feed from the cursor."""
        served = self._movie(1)
        untouched = self._movie(2)
        added_later = self._movie(3)
        self._watch(served)
        self._watch(untouched)
        first = self.client.get(self.snapshot_url, {"limit": 1}).json()
        resume = first["resume_cursor"]

        self._watch(served, watched=False)
        self._watch(added_later)
        second = self.client.get(
            self.snapshot_url,
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

        response = self.client.get(self.snapshot_url, {"cursor": 1})

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
                    self.client.get(self.snapshot_url, params).status_code,
                    400,
                )

    def test_an_oversized_limit_is_clamped(self):
        for number in range(3):
            self._watch(self._movie(number))

        response = self.client.get(self.snapshot_url, {"limit": 10_000_000})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 3)

    def test_a_page_costs_the_same_queries_however_many_rows_it_holds(self):
        def page_queries():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(self.snapshot_url)
            return len(queries)

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

        self.assertEqual(self.client.get(self.snapshot_url).status_code, 200)

    def test_a_token_without_sync_read_is_refused(self):
        _, secret = IntegrationToken.generate(
            user=self.user,
            name="Narrow",
            scopes=["catalog:read"],
        )
        self.client.credentials(HTTP_X_API_KEY=secret)

        self.assertEqual(self.client.get(self.snapshot_url).status_code, 403)

    def test_the_snapshot_requires_authentication(self):
        self.client.credentials()

        self.assertIn(self.client.get(self.snapshot_url).status_code, (401, 403))


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
        self.assertEqual(payload["capabilities"], [CAPABILITY_WATCHED_READ])
        self.assertEqual(payload["directions"], [SyncDirection.OUTBOUND.value])
        self.assertTrue(payload["origin_key"])
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

    def test_registering_again_restores_a_disabled_binding(self):
        first = self._register().json()
        SyncBinding.objects.filter(pk=first["id"]).update(
            status=SyncBindingStatus.DISABLED.value,
        )

        response = self._register()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SyncBindingStatus.ACTIVE.value)
        self.assertEqual(response.json()["origin_key"], first["origin_key"])

    def test_registering_does_not_override_a_kill_switch(self):
        first = self._register().json()
        SyncBinding.objects.filter(pk=first["id"]).update(kill_switch=True)

        response = self._register()

        self.assertEqual(response.status_code, 409)
        self.assertTrue(SyncBinding.objects.get(pk=first["id"]).kill_switch)

    def test_registering_leaves_an_already_broader_binding_alone(self):
        first = self._register().json()
        binding = SyncBinding.objects.get(pk=first["id"])
        binding.approved_capabilities = [CAPABILITY_WATCHED_READ, "play.push"]
        binding.save(update_fields=["approved_capabilities"])

        self._register()

        binding.refresh_from_db()
        self.assertEqual(
            binding.approved_capabilities,
            [CAPABILITY_WATCHED_READ, "play.push"],
        )

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

    def test_a_missing_or_malformed_instance_key_is_rejected(self):
        for body in (
            {},
            {"instance_key": ""},
            {"instance_key": "   "},
            {"instance_key": 12},
            {"instance_key": "x" * 256},
            {"instance_key": "kodi", "label": 5},
            {"instance_key": "kodi", "label": "x" * 256},
        ):
            with self.subTest(body=body):
                self.assertEqual(self._register(body).status_code, 400)
        self.assertFalse(SyncBinding.objects.filter(user=self.user).exists())

    def test_registration_requires_authentication(self):
        self.client.credentials()

        self.assertIn(self._register().status_code, (401, 403))

    def test_a_default_tracking_token_can_register(self):
        _, secret = IntegrationToken.generate(user=self.user, name="Kodi")
        self.client.credentials(HTTP_X_API_KEY=secret)

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
