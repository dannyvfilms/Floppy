# Tests for detail-page endpoints that the existing fork tests did not
# exercise yet (season/episode collection entries, season
# scores, season/episode activity timelines).
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import (
    CollectionEntry,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

from .base import FloppyApiTestCase


class SeasonSubresourceTests(FloppyApiTestCase):
    """Shared season/episode fixtures for the detail sub-resource routes."""

    def setUp(self):
        super().setUp()
        patcher = patch("app.models.Item.fetch_releases", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.season_item = Item.objects.create(
            media_id="9100",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show - Season 2",
            image="https://example.com/s2.jpg",
            season_number=2,
        )
        self.episode_item = Item.objects.create(
            media_id="9101",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Show S2E4",
            image="https://example.com/s2e4.jpg",
            season_number=2,
            episode_number=4,
        )

    def tracked_season(self, user):
        return Season.objects.create(
            item=self.season_item,
            user=user,
            status=Status.IN_PROGRESS.value,
        )

    def tracked_episode(self, user, season_row):
        episode = Episode.objects.create(
            item=self.episode_item,
            related_season=season_row,
        )
        episode._history_user = user
        episode.notes = "seed"
        episode.save()
        return episode


class EpisodeCollectionEntriesTests(SeasonSubresourceTests):
    """GET /media/tv/[source]/[id]/[season]/[episode]/collection/entries/."""

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_media_episode_collection_entries",
            args=("tv", "tmdb", "9100", 2, 4),
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_non_tv_media_type_returns_400(self):
        response = self.call_api(
            "get",
            "api_media_episode_collection_entries",
            args=("movie", "tmdb", "9100", 2, 4),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("detail", response.json())

    def test_entries_are_scoped_to_the_caller(self):
        mine = CollectionEntry.objects.create(user=self.user1, item=self.episode_item)
        theirs = CollectionEntry.objects.create(user=self.user2, item=self.episode_item)
        response = self.call_api(
            "get",
            "api_media_episode_collection_entries",
            args=("tv", "tmdb", "9101", 2, 4),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        ids = [row["id"] for row in response.json()["results"]]
        self.assertEqual(ids, [mine.id])
        self.assertNotIn(theirs.id, ids)


class SeasonCollectionEntriesTests(SeasonSubresourceTests):
    """GET /media/tv/[source]/[id]/[season]/collection/entries/ happy path."""

    def test_returns_the_season_entries_with_stats(self):
        entry = CollectionEntry.objects.create(user=self.user1, item=self.season_item)
        CollectionEntry.objects.create(user=self.user2, item=self.season_item)
        response = self.call_api(
            "get",
            "api_media_season_collection_entries",
            args=("tv", "tmdb", "9100", 2),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual([row["id"] for row in payload["results"]], [entry.id])
        self.assertIn("stats", payload)

    def test_entries_are_scoped_to_the_caller(self):
        CollectionEntry.objects.create(user=self.user1, item=self.season_item)
        response = self.call_api(
            "get",
            "api_media_season_collection_entries",
            args=("tv", "tmdb", "9100", 2),
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["results"], [])

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_media_season_collection_entries",
            args=("tv", "tmdb", "9100", 2),
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)


class SeasonScoresTests(SeasonSubresourceTests):
    """GET /media/tv/[source]/[id]/[season]/scores/."""

    def setUp(self):
        super().setUp()
        self.season_item.provider_rating = 8.7
        self.season_item.provider_rating_count = 120
        self.season_item.save()

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_media_season_scores",
            args=("tv", "tmdb", "9100", 2),
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_stored_provider_score_is_reported(self):
        response = self.call_api(
            "get",
            "api_media_season_scores",
            args=("tv", "tmdb", "9100", 2),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        provider_chips = [chip for chip in payload["chips"] if chip["key"] == "provider"]
        self.assertEqual(len(provider_chips), 1)
        self.assertEqual(provider_chips[0]["rating"], 8.7)
        self.assertEqual(provider_chips[0]["count"], 120)
        # A season route has no series graph and no game lengths.
        self.assertEqual(payload["graphs"], {})
        self.assertIsNone(payload["gameLengths"])
        for key in ("provider", "trakt", "imdb", "mal", "opencritic"):
            self.assertIn(key, payload["logos"])


class SeasonActivityTimelineTests(SeasonSubresourceTests):
    """GET /media/tv/[source]/[id]/[season]/activity-timeline/."""

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_media_season_activity_timeline",
            args=("tv", "tmdb", "9100", 2),
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_tracked_season_history_forms_day_groups(self):
        season = self.tracked_season(self.user1)
        season._history_user = self.user1
        season.notes = "seed"
        season.save()
        response = self.call_api(
            "get",
            "api_media_season_activity_timeline",
            args=("tv", "tmdb", "9100", 2),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertFalse(payload["multipleInstances"])
        self.assertEqual(len(payload["days"]), 1)
        entries = payload["days"][0]["entries"]
        self.assertEqual(len(entries), 2)
        for row in entries:
            self.assertIn("id", row)
            self.assertIn("instanceId", row)
            self.assertIn("when", row)
            self.assertIn("date", row)
            self.assertIsInstance(row["changes"], list)
        self.assertEqual(entries[-1]["instance"], 1)

    def test_other_users_activity_is_not_shown(self):
        self.tracked_season(self.user1)
        theirs = self.tracked_season(self.user2)
        theirs._history_user = self.user2
        theirs.notes = "other-user-seed"
        theirs.save()
        response = self.call_api(
            "get",
            "api_media_season_activity_timeline",
            args=("tv", "tmdb", "9100", 2),
            headers=self.auth_headers,
        )
        payload = response.json()
        flattened = [row for day in payload["days"] for row in day["entries"]]
        season_ids = set(
            Season.objects.filter(user=self.user1).values_list("pk", flat=True)
        )
        for row in flattened:
            self.assertIn(row["instanceId"], season_ids)


class EpisodeActivityTimelineTests(SeasonSubresourceTests):
    """GET /media/tv/[source]/[id]/[season]/[episode]/activity-timeline/."""

    def test_requires_authentication(self):
        response = self.call_api(
            "get",
            "api_media_episode_activity_timeline",
            args=("tv", "tmdb", "9101", 2, 4),
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_untracked_episode_returns_empty_timeline(self):
        response = self.call_api(
            "get",
            "api_media_episode_activity_timeline",
            args=("tv", "tmdb", "9101", 2, 4),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json(), {"multipleInstances": False, "days": []})

    def test_tracked_episode_history_is_listed(self):
        season_row = self.tracked_season(self.user1)
        self.tracked_episode(self.user1, season_row)
        response = self.call_api(
            "get",
            "api_media_episode_activity_timeline",
            args=("tv", "tmdb", "9101", 2, 4),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertFalse(payload["multipleInstances"])
        self.assertEqual(len(payload["days"]), 1)
        self.assertTrue(payload["days"][0]["entries"])
        for row in payload["days"][0]["entries"]:
            self.assertIn("changes", row)
            self.assertIn("when", row)

    def test_other_users_activity_is_not_shown(self):
        season_row = self.tracked_season(self.user1)
        self.tracked_episode(self.user1, season_row)
        other_season = self.tracked_season(self.user2)
        self.tracked_episode(self.user2, other_season)
        response = self.call_api(
            "get",
            "api_media_episode_activity_timeline",
            args=("tv", "tmdb", "9101", 2, 4),
            headers=self.auth_headers2,
        )
        payload = response.json()
        flattened = [row for day in payload["days"] for row in day["entries"]]
        user2_episode_ids = set(
            Episode.objects.filter(item=self.episode_item, related_season=other_season)
            .values_list("pk", flat=True)
        )
        self.assertTrue(flattened)
        for row in flattened:
            self.assertIn(row["instanceId"], user2_episode_ids)
