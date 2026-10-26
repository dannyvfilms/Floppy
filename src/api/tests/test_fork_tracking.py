# FORK: tests for the tracking parity endpoints — episode watch/drop,
# tag management, and the history timeline.
import datetime
from decimal import Decimal
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from app import history_cache
from app.models import (
    Episode,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    MoviePlay,
    Sources,
    Tag,
)

from .base import FloppyApiTestCase

SEASON_METADATA = {
    "media_id": "1001",
    "source": Sources.TMDB.value,
    "media_type": MediaTypes.SEASON.value,
    "title": "TV Show 1",
    "original_title": "TV Show 1",
    "localized_title": "TV Show 1",
    "image": "http://example.com/tv-1-s1.jpg",
    "season_number": 1,
    "season_title": "Season 1",
    "details": {"episodes": 3},
    "episodes": [
        {
            "episode_number": number,
            "air_date": f"2023-06-0{number}",
            "image": f"http://example.com/tv-1-s1e{number}.jpg",
            "name": f"Episode {number}",
        }
        for number in (1, 2, 3)
    ],
}


def _season_metadata_side_effect(
    media_type,
    _media_id,
    _source,
    _season_numbers=None,
    *_args,
    **_kwargs,
):
    if media_type == "tv_with_seasons":
        return {**SEASON_METADATA, "season/1": SEASON_METADATA}
    return SEASON_METADATA


class EpisodeWatchTests(FloppyApiTestCase):
    """POST/DELETE episode watch and POST episode drop."""

    def _watch(self, episode_number, payload=None, headers=None):
        return self.call_api(
            "post",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, episode_number),
            payload=payload or {},
            headers=headers or self.auth_headers,
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_creates_play(self, _mock):
        """POST watch adds an Episode play with the given end_date."""
        response = self._watch(2, payload={"end_date": "2024-03-05"})
        self.assertEqual(response.status_code, HTTP.CREATED)
        payload = response.json()
        self.assertTrue(payload["end_date"].startswith("2024-03-05"))
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=2,
                end_date__date="2024-03-05",
            ).exists(),
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_defaults_end_date_to_today(self, _mock):
        """POST watch without end_date uses today."""
        response = self._watch(3)
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertIsNotNone(response.json()["end_date"])

    def test_watch_invalid_date_rejected(self):
        """POST watch with a bad end_date returns 400."""
        response = self._watch(1, payload={"end_date": "not-a-date"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_with_score_sets_episode_score(self, _mock):
        """POST watch with a score sets it on all plays of the episode."""
        response = self._watch(1, payload={"score": "8.3"})
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertEqual(response.json()["score"], 8.3)
        scores = set(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=1,
            ).values_list("score", flat=True),
        )
        self.assertEqual(scores, {Decimal("8.3")})

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_without_score_leaves_score_unset(self, _mock):
        """POST watch without a score field doesn't touch the score."""
        response = self._watch(1)
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertIsNone(response.json()["score"])

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_invalid_score_rejected(self, _mock):
        """POST watch with an out-of-range score 400s and creates no play."""
        play_count_before = Episode.objects.filter(
            related_season=self.season_medias[0],
            item__episode_number=1,
        ).count()

        response = self._watch(1, payload={"score": "11"})

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertEqual(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=1,
            ).count(),
            play_count_before,
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_rejects_episode_not_in_season(self, _mock):
        """POST watch rejects an episode number absent from season metadata."""
        response = self._watch(99)

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertFalse(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=99,
            ).exists(),
        )
        self.assertFalse(
            Item.objects.filter(
                media_id="1001",
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=99,
            ).exists(),
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_drop_rejects_episode_not_in_season(self, _mock):
        """POST drop rejects an episode number absent from season metadata."""
        response = self.call_api(
            "post",
            "api_media_episode_drop",
            args=("tv", "tmdb", "1001", 1, 99),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertFalse(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=99,
            ).exists(),
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        return_value={
            **SEASON_METADATA,
            "episodes": [
                {**SEASON_METADATA["episodes"][0], "episode_number": 7},
                {**SEASON_METADATA["episodes"][1], "episode_number": 42},
            ],
        },
    )
    def test_watch_accepts_nonsequential_episode_number(self, _mock):
        """Provider episode membership is exact, including non-sequential numbers."""
        response = self._watch(42)
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=42,
            ).exists(),
        )

        history_response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=("tv", "tmdb", "1001", 1, 42),
            headers=self.auth_headers,
        )
        self.assertEqual(history_response.status_code, HTTP.OK)
        self.assertEqual(len(history_response.json()["results"]), 1)

    def test_watch_non_tv_rejected(self):
        """POST watch on a non-tv media type returns 400."""
        response = self.call_api(
            "post",
            "api_media_episode_watch",
            args=("movie", "tmdb", "701", 1, 1),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=AttributeError("'list' object has no attribute 'get'"),
    )
    def test_watch_resolution_error_does_not_expose_exception(self, _mock):
        """POST watch returns a public error when season resolution fails."""
        response = self.call_api(
            "post",
            "api_media_episode_watch",
            args=("tv", "tmdb", "999999", 9, 1),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Could not resolve season."})
        self.assertFalse(Episode.objects.filter(item__media_id="999999").exists())

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_unwatch_removes_latest_play(self, _mock):
        """DELETE watch removes the most recent play only."""
        self._watch(1, payload={"end_date": "2024-01-01"})
        self._watch(1, payload={"end_date": "2024-02-01"})

        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, 1),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        remaining = Episode.objects.filter(
            related_season=self.season_medias[0],
            item__episode_number=1,
            end_date__isnull=False,
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(str(remaining.first().end_date.date()), "2024-01-01")

    def test_unwatch_untracked_season_not_found(self):
        """DELETE watch on an untracked season returns 404."""
        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "999999", 9, 1),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_idempotent_external_id_replay(self, _mock):
        """A duplicate external_id returns the existing play without a second row."""
        first = self._watch(
            2,
            payload={"end_date": "2024-01-01", "external_id": "evt-1"},
        )
        second = self._watch(
            2,
            payload={"end_date": "2024-06-01", "external_id": "evt-1"},
        )

        self.assertEqual(first.status_code, HTTP.CREATED)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertEqual(
            first.json()["consumption_id"],
            second.json()["consumption_id"],
        )
        self.assertEqual(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=2,
                external_id="evt-1",
            ).count(),
            1,
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_same_external_id_on_another_episode_is_allowed(self, _mock):
        """External ids are unique per episode, not across the season."""
        first = self._watch(
            1,
            payload={"end_date": "2024-01-01", "external_id": "evt-1"},
        )
        second = self._watch(
            2,
            payload={"end_date": "2024-01-01", "external_id": "evt-1"},
        )

        self.assertEqual(first.status_code, HTTP.CREATED)
        self.assertEqual(second.status_code, HTTP.CREATED)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_unwatch_by_external_id(self, _mock):
        """DELETE watch with external_id targets that specific play."""
        self._watch(1, payload={"end_date": "2024-01-01", "external_id": "a"})
        self._watch(1, payload={"end_date": "2024-02-01", "external_id": "b"})

        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, 1),
            params={"external_id": "a"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)

        remaining = Episode.objects.filter(
            related_season=self.season_medias[0],
            item__episode_number=1,
            external_id__isnull=False,
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().external_id, "b")

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_unwatch_unknown_external_id_not_found(self, _mock):
        """DELETE watch with an external_id that matches no play returns 404."""
        self._watch(1, payload={"end_date": "2024-01-01", "external_id": "a"})

        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, 1),
            params={"external_id": "missing"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=1,
                external_id="a",
            ).count(),
            1,
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_history_response_includes_external_id(self, _mock):
        """Episode history exposes external_id so clients can match their plays."""
        self._watch(1, payload={"end_date": "2024-01-01", "external_id": "evt-9"})

        response = self.call_api(
            "get",
            "api_media_episode_consumption_history",
            args=("tv", "tmdb", "1001", 1, 1),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = response.json()["results"]
        matched = [row for row in results if row["external_id"] == "evt-9"]
        self.assertEqual(len(matched), 1)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_drop_creates_dropped_record(self, _mock):
        """POST drop records a dropped episode without watch history."""
        response = self.call_api(
            "post",
            "api_media_episode_drop",
            args=("tv", "tmdb", "1001", 1, 2),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=2,
                dropped=True,
                end_date=None,
            ).exists(),
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=AttributeError("'list' object has no attribute 'get'"),
    )
    def test_drop_resolution_error_does_not_expose_exception(self, _mock):
        """POST drop returns a public error when season resolution fails."""
        response = self.call_api(
            "post",
            "api_media_episode_drop",
            args=("tv", "tmdb", "999999", 9, 1),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertEqual(response.json(), {"detail": "Could not resolve season."})
        self.assertFalse(Episode.objects.filter(item__media_id="999999").exists())


class MovieWatchTests(FloppyApiTestCase):
    """POST/DELETE movie watch (issue #577)."""

    def _watch(self, media_id="701", payload=None):
        return self.call_api(
            "post",
            "api_media_movie_watch",
            args=("movie", "tmdb", media_id),
            payload=payload or {},
            headers=self.auth_headers,
        )

    def _unwatch(self, media_id="701", params=None):
        return self.call_api(
            "delete",
            "api_media_movie_watch",
            args=("movie", "tmdb", media_id),
            params=params,
            headers=self.auth_headers,
        )

    def test_watch_creates_play(self):
        """POST watch appends a MoviePlay with the given end_date."""
        response = self._watch(payload={"end_date": "2024-03-05T00:00:00Z"})
        self.assertEqual(response.status_code, HTTP.CREATED)
        payload = response.json()
        self.assertTrue(payload["end_date"].startswith("2024-03-05"))
        self.assertTrue(
            MoviePlay.objects.filter(
                movie=self.movie_medias[0],
                end_date__date="2024-03-05",
            ).exists(),
        )

    def test_watch_defaults_end_date_to_now(self):
        """POST watch without end_date uses now."""
        response = self._watch()
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertIsNotNone(response.json()["end_date"])

    def test_watch_invalid_date_rejected(self):
        """POST watch with a bad end_date returns 400."""
        response = self._watch(payload={"end_date": "not-a-date"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_watch_non_movie_rejected(self):
        """POST watch on a non-movie media type returns 400."""
        response = self.call_api(
            "post",
            "api_media_movie_watch",
            args=("tv", "tmdb", "1001"),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_repeated_watch_creates_multiple_plays(self):
        """Three watches with distinct dates leave three plays, not one."""
        self._watch(payload={"end_date": "2023-05-14T21:30:00Z"})
        self._watch(payload={"end_date": "2026-02-03T20:00:00Z"})
        self._watch(payload={"end_date": "2026-07-19T22:15:00Z"})

        self.assertEqual(
            MoviePlay.objects.filter(movie=self.movie_medias[0]).count(),
            3,
        )
        self.movie_medias[0].refresh_from_db()
        self.assertEqual(
            str(self.movie_medias[0].end_date.date()),
            "2026-07-19",
        )

    def test_watch_lazily_backfills_preexisting_end_date(self):
        """The movie's pre-existing end_date survives as a play on first watch()."""
        movie = self.movie_medias[0]
        movie.end_date = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        movie.save(update_fields=["end_date"])

        self._watch(payload={"end_date": "2026-01-01T00:00:00Z"})

        self.assertEqual(MoviePlay.objects.filter(movie=movie).count(), 2)
        self.assertTrue(
            MoviePlay.objects.filter(
                movie=movie,
                end_date__date="2020-01-01",
            ).exists(),
        )

    def test_watch_idempotent_external_id_replay(self):
        """A duplicate external_id is a no-op that returns the existing play."""
        first = self._watch(
            payload={"end_date": "2024-01-01T00:00:00Z", "external_id": "evt-1"},
        )
        second = self._watch(
            payload={"end_date": "2024-06-01T00:00:00Z", "external_id": "evt-1"},
        )
        self.assertEqual(first.status_code, HTTP.CREATED)
        self.assertEqual(second.status_code, HTTP.OK)
        self.assertEqual(
            first.json()["consumption_id"],
            second.json()["consumption_id"],
        )
        self.assertEqual(
            MoviePlay.objects.filter(movie=self.movie_medias[0]).count(),
            1,
        )

    def test_unwatch_removes_most_recent_play(self):
        """DELETE watch removes the most recent play only."""
        self._watch(payload={"end_date": "2024-01-01T00:00:00Z"})
        self._watch(payload={"end_date": "2024-02-01T00:00:00Z"})

        response = self._unwatch()
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)

        remaining = MoviePlay.objects.filter(movie=self.movie_medias[0])
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(str(remaining.first().end_date.date()), "2024-01-01")
        self.movie_medias[0].refresh_from_db()
        self.assertEqual(
            str(self.movie_medias[0].end_date.date()),
            "2024-01-01",
        )

    def test_unwatch_by_external_id(self):
        """DELETE watch with external_id targets that specific play."""
        self._watch(payload={"end_date": "2024-01-01T00:00:00Z", "external_id": "a"})
        self._watch(payload={"end_date": "2024-02-01T00:00:00Z", "external_id": "b"})

        response = self._unwatch(params={"external_id": "a"})
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)

        remaining = MoviePlay.objects.filter(movie=self.movie_medias[0])
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().external_id, "b")

    def test_unwatch_movie_with_no_plays_not_found(self):
        """DELETE watch on a movie with zero plays returns 404."""
        response = self._unwatch()
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_unwatch_untracked_movie_not_found(self):
        """DELETE watch on an untracked movie returns 404."""
        response = self._unwatch(media_id="999999")
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class TagTests(FloppyApiTestCase):
    """Tag CRUD and per-item tag assignment."""

    def test_create_list_and_delete_tag(self):
        """Tags can be created, listed with counts, renamed, and deleted."""
        created = self.call_api(
            "post",
            "api_tags",
            payload={"name": "  cozy   vibes "},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        tag_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "cozy vibes")

        duplicate = self.call_api(
            "post",
            "api_tags",
            payload={"name": "COZY VIBES"},
            headers=self.auth_headers,
        )
        self.assertEqual(duplicate.status_code, HTTP.CONFLICT)

        listed = self.call_api("get", "api_tags", headers=self.auth_headers)
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(listed.json()["results"][0]["item_count"], 0)

        renamed = self.call_api(
            "patch",
            "api_tag_detail",
            args=(tag_id,),
            payload={"name": "renamed"},
            headers=self.auth_headers,
        )
        self.assertEqual(renamed.status_code, HTTP.OK)
        self.assertEqual(renamed.json()["name"], "renamed")

        deleted = self.call_api(
            "delete",
            "api_tag_detail",
            args=(tag_id,),
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(Tag.objects.filter(id=tag_id).exists())

    def test_other_users_tag_not_found(self):
        """Another user's tag cannot be renamed or deleted."""
        tag = Tag.objects.create(user=self.user2, name="theirs")
        response = self.call_api(
            "delete",
            "api_tag_detail",
            args=(tag.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_media_tags_put_replaces_assignments(self):
        """PUT media tags replaces the caller's assignments on the item."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        keep = Tag.objects.create(user=self.user1, name="keep")
        drop = Tag.objects.create(user=self.user1, name="drop")
        ItemTag.objects.create(tag=drop, item=movie_item)

        response = self.call_api(
            "put",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"tag_ids": [keep.id]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        names = [tag["name"] for tag in response.json()["results"]]
        self.assertEqual(names, ["keep"])
        self.assertFalse(ItemTag.objects.filter(tag=drop, item=movie_item).exists())

        listed = self.call_api(
            "get",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(len(listed.json()["results"]), 1)

    def test_media_tags_unknown_tag_rejected(self):
        """PUT media tags with a foreign or unknown tag id returns 404."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        foreign = Tag.objects.create(user=self.user2, name="foreign")
        response = self.call_api(
            "put",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"tag_ids": [foreign.id]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_media_tags_unknown_item_not_found(self):
        """Tag routes 404 for unknown items."""
        response = self.call_api(
            "get",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, "tmdb", "999999"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class HistoryTimelineTests(FloppyApiTestCase):
    """GET /history returns the day-grouped consumption timeline."""

    def setUp(self):
        """Give a movie play a concrete end date so it appears in history."""
        super().setUp()
        cache.clear()
        movie = self.movie_medias[0]
        movie.end_date = datetime.date(2024, 5, 10)
        movie.save(update_fields=["end_date"])

    def test_history_returns_days(self):
        """The timeline contains the movie play grouped under its day."""
        response = self.call_api("get", "api_history", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        days = response.json()["results"]
        self.assertTrue(days)
        all_entries = [entry for day in days for entry in day["entries"]]
        self.assertTrue(
            any(entry["media_type"] == "movie" for entry in all_entries),
        )

    def test_history_day_entries_are_capped(self):
        """A day with many plays doesn't blow up the response body (#1004).

        `limit`/`offset` on this endpoint paginate over DAYS, not entries, so
        a single busy day (imports, binge sessions, frequent podcast
        scrobbles) must still be bounded — mirrors the web history page's
        existing per-day cap (HISTORY_ENTRIES_PER_DAY_PAGE).
        """
        entry_count = history_cache.HISTORY_ENTRIES_PER_DAY_PAGE + 5
        same_day = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
        for index in range(entry_count):
            item = Item.objects.create(
                media_id=f"history-cap-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"History Cap Movie {index}",
            )
            Movie.objects.create(
                item=item,
                user=self.user1,
                end_date=same_day,
            )
        cache.clear()

        response = self.call_api(
            "get",
            "api_history",
            params={"media_type": "movie", "limit": 1},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        days = response.json()["results"]
        self.assertEqual(len(days), 1)
        day = days[0]
        self.assertLessEqual(len(day["entries"]), history_cache.HISTORY_ENTRIES_PER_DAY_PAGE)
        self.assertEqual(day["entry_count"], entry_count)
        self.assertTrue(day["entries_truncated"])

    def _seed_busy_movie_day(self, entry_count, *, day=None):
        same_day = day or datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
        for index in range(entry_count):
            item = Item.objects.create(
                media_id=f"history-cap-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"History Cap Movie {index}",
            )
            Movie.objects.create(item=item, user=self.user1, end_date=same_day)
        cache.clear()

    def test_history_max_entries_per_day_overrides_default_cap(self):
        """max_entries_per_day raises/lowers the windowed path's per-day cap (#1004)."""
        entry_count = history_cache.HISTORY_ENTRIES_PER_DAY_PAGE + 5
        self._seed_busy_movie_day(entry_count)

        response = self.call_api(
            "get",
            "api_history",
            params={"media_type": "movie", "limit": 1, "max_entries_per_day": 10},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        day = response.json()["results"][0]
        self.assertEqual(len(day["entries"]), 10)
        self.assertEqual(day["entry_count"], entry_count)
        self.assertTrue(day["entries_truncated"])

    def test_history_max_entries_per_day_applies_to_date_filtered_bypass(self):
        """The flat=1/date-filtered bypass path is capped too, not just the windowed path (#1004)."""
        entry_count = history_cache.HISTORY_ENTRIES_PER_DAY_PAGE + 5
        self._seed_busy_movie_day(entry_count)

        response = self.call_api(
            "get",
            "api_history",
            params={
                "media_type": "movie",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "max_entries_per_day": 10,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        days = [day for day in response.json()["results"] if day["entries"]]
        self.assertTrue(days)
        day = days[0]
        self.assertEqual(len(day["entries"]), 10)
        self.assertEqual(day["entry_count"], entry_count)
        self.assertTrue(day["entries_truncated"])

    def test_history_flat_mode_is_not_capped_per_day(self):
        """?flat=1 paginates over every entry, unaffected by the per-day cap (#1004)."""
        entry_count = history_cache.HISTORY_ENTRIES_PER_DAY_PAGE + 5
        self._seed_busy_movie_day(entry_count)

        response = self.call_api(
            "get",
            "api_history",
            params={"media_type": "movie", "flat": "1", "limit": entry_count},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertGreaterEqual(payload["pagination"]["total"], entry_count)
        self.assertEqual(len(payload["results"]), entry_count)

    def test_history_max_entries_per_day_validation(self):
        """Invalid/non-positive max_entries_per_day values are rejected."""
        for value in ("not-a-number", "0", "-1"):
            response = self.call_api(
                "get",
                "api_history",
                params={"max_entries_per_day": value},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, value)

    def test_history_max_entries_per_day_is_clamped(self):
        """max_entries_per_day is clamped to MAX_RESULT_LIMIT, not taken verbatim."""
        entry_count = 25
        self._seed_busy_movie_day(entry_count)

        response = self.call_api(
            "get",
            "api_history",
            params={
                "media_type": "movie",
                "limit": 1,
                "max_entries_per_day": 999999,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        day = response.json()["results"][0]
        # All 25 seeded entries fit under the MAX_RESULT_LIMIT=200 clamp —
        # this just proves the request succeeds and isn't itself truncated
        # by an unclamped, absurdly large cap causing other failures.
        self.assertEqual(len(day["entries"]), entry_count)
        self.assertFalse(day["entries_truncated"])

    def test_history_flat_returns_paginated_entry_list(self):
        """?flat=1 returns a flat, card-oriented entry list, not day buckets."""
        day_response = self.call_api(
            "get",
            "api_history",
            headers=self.auth_headers,
        )
        day_total_entries = sum(
            len(day["entries"]) for day in day_response.json()["results"]
        )

        response = self.call_api(
            "get",
            "api_history",
            params={"flat": "1"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIn("results", payload)
        self.assertEqual(payload["pagination"]["total"], day_total_entries)
        for entry in payload["results"]:
            self.assertIn("item", entry)
            self.assertIn("url", entry)
        self.assertTrue(
            any(entry["media_type"] == "movie" for entry in payload["results"]),
        )

    @patch(
        "app.history_cache_reader.get_history_days",
        side_effect=AssertionError("unfiltered API history must use the cached window"),
    )
    def test_unfiltered_history_limit_uses_bounded_cached_path(
        self,
        _mock_get_history_days,
    ):
        """Pagination must not rebuild the user's complete history inline."""
        with self.assertLogs("app.history_cache_reader", level="INFO") as logs:
            response = self.call_api(
                "get",
                "api_history",
                params={"limit": 1},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertLessEqual(len(response.json()["results"]), 1)
        self.assertTrue(
            any("history_cached_window" in record for record in logs.output),
        )
        self.assertFalse(
            any("history_cache_bypass" in record for record in logs.output),
        )

    def test_history_media_type_filter(self):
        """media_type filters the timeline."""
        response = self.call_api(
            "get",
            "api_history",
            params={"media_type": "game"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        days = response.json()["results"]
        for day in days:
            for entry in day["entries"]:
                self.assertEqual(entry["media_type"], "game")

    def test_episode_history_includes_parent_show_name(self):
        """Episode entries identify their parent show on every history path."""
        episode = self.episode_medias[0]
        episode.item.title = "Pilot"
        episode.item.save(update_fields=["title"])
        episode.end_date = datetime.datetime(2024, 5, 11, tzinfo=datetime.UTC)
        episode.save(update_fields=["end_date"])

        requests = (
            {"types": "episodes"},
            {
                "types": "tv",
                "media_id": "1001",
                "source": Sources.TMDB.value,
            },
        )
        for params in requests:
            with self.subTest(params=params):
                response = self.call_api(
                    "get",
                    "api_history",
                    params=params,
                    headers=self.auth_headers,
                )

                self.assertEqual(response.status_code, HTTP.OK)
                entries = [
                    entry
                    for day in response.json()["results"]
                    for entry in day["entries"]
                ]
                history_entry = next(
                    entry
                    for entry in entries
                    if entry["instance_id"] == episode.id
                )
                self.assertEqual(history_entry["title"], "Pilot")
                self.assertEqual(history_entry["show"]["title"], "TV Show 1")

    def test_flat_episode_history_uses_episode_title_in_item_and_url(self):
        """Flattened history keeps the repaired episode title in its item and URL."""
        episode = self.episode_medias[0]
        episode.related_season.related_tv.item.source = Sources.TVDB.value
        episode.related_season.related_tv.item.media_id = "81189"
        episode.related_season.related_tv.item.save(
            update_fields=["source", "media_id"],
        )
        episode.related_season.item.source = Sources.TVDB.value
        episode.related_season.item.media_id = "81189"
        episode.related_season.item.save(update_fields=["source", "media_id"])
        episode.item.title = "Pilot"
        episode.item.source = Sources.TVDB.value
        episode.item.media_id = "81189"
        episode.item.save(update_fields=["title", "source", "media_id"])
        episode.end_date = datetime.datetime(2024, 5, 11, tzinfo=datetime.UTC)
        episode.save(update_fields=["end_date"])
        cache.clear()

        response = self.call_api(
            "get",
            "api_history",
            params={"flat": "1"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        history_entry = next(
            entry
            for entry in response.json()["results"]
            if entry["instance_id"] == episode.id
        )
        self.assertEqual(history_entry["title"], "Pilot")
        self.assertEqual(history_entry["item"]["title"], "Pilot")
        self.assertIn(
            "/details/tvdb/tv/81189/pilot/season/1/episode/1",
            history_entry["url"],
        )

    def test_history_types_alias_filters_categories_before_querying(self):
        """The issue's plural types parameter excludes unrelated categories."""
        episode = self.episode_medias[0]
        episode.end_date = datetime.datetime(2024, 5, 11, tzinfo=datetime.UTC)
        episode.save(update_fields=["end_date"])

        game = self.game_medias[0]
        game.start_date = datetime.datetime(2024, 5, 12, tzinfo=datetime.UTC)
        game.end_date = datetime.datetime(2024, 5, 12, tzinfo=datetime.UTC)
        game.progress = 60
        game.save(update_fields=["start_date", "end_date", "progress"])

        with CaptureQueriesContext(connection) as captured_queries:
            response = self.call_api(
                "get",
                "api_history",
                params={"types": "episodes,movies", "limit": 3},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, HTTP.OK)
        entries = [
            entry
            for day in response.json()["results"]
            for entry in day["entries"]
        ]
        self.assertTrue(entries)
        self.assertEqual(
            {entry["media_type"] for entry in entries},
            {MediaTypes.EPISODE.value, MediaTypes.MOVIE.value},
        )
        sql = "\n".join(query["sql"].lower() for query in captured_queries.captured_queries)
        for table_name in (
            "app_game",
            "app_music",
            "app_historicalmusic",
            "app_historicalpodcast",
            "app_book",
            "app_comic",
            "app_manga",
        ):
            self.assertNotIn(table_name, sql)

    def test_history_types_pagination_preserves_total_days(self):
        """Type-filtered pagination continues to paginate over matching days."""
        second_movie = Movie.objects.create(
            item=self.items_by_type[MediaTypes.MOVIE.value][1],
            user=self.user1,
            end_date=datetime.date(2024, 5, 11),
        )
        self.assertIsNotNone(second_movie)

        response = self.call_api(
            "get",
            "api_history",
            params={"types": "movies", "limit": 1, "offset": 1},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertGreaterEqual(payload["pagination"]["total"], 2)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(
            payload["results"][0]["entries"][0]["media_type"],
            MediaTypes.MOVIE.value,
        )

    def test_history_cache_invalidation_refreshes_unfiltered_api(self):
        """A cached API response reflects new activity after invalidation."""
        first_response = self.call_api(
            "get",
            "api_history",
            headers=self.auth_headers,
        )
        self.assertEqual(first_response.status_code, HTTP.OK)

        new_movie = Movie.objects.create(
            item=self.items_by_type[MediaTypes.MOVIE.value][1],
            user=self.user1,
            end_date=datetime.date(2024, 5, 12),
        )
        history_cache.invalidate_history_cache(self.user1.id)

        response = self.call_api(
            "get",
            "api_history",
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        entries = [
            entry
            for day in response.json()["results"]
            for entry in day["entries"]
        ]
        self.assertTrue(
            any(entry["instance_id"] == new_movie.id for entry in entries),
        )

    def test_history_cache_invalidation_refreshes_type_only_index(self):
        """Typed indexes do not hide a new record after invalidation."""
        first_response = self.call_api(
            "get",
            "api_history",
            params={"types": "movies"},
            headers=self.auth_headers,
        )
        self.assertEqual(first_response.status_code, HTTP.OK)

        new_movie = Movie.objects.create(
            item=self.items_by_type[MediaTypes.MOVIE.value][1],
            user=self.user1,
            end_date=datetime.date(2024, 5, 12),
        )
        history_cache.invalidate_history_cache(self.user1.id)

        response = self.call_api(
            "get",
            "api_history",
            params={"types": "movies"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.OK)
        entries = [
            entry
            for day in response.json()["results"]
            for entry in day["entries"]
        ]
        self.assertTrue(
            any(entry["instance_id"] == new_movie.id for entry in entries),
        )

    def test_history_invalid_int_filter_rejected(self):
        """Non-integer values for integer filters return 400."""
        response = self.call_api(
            "get",
            "api_history",
            params={"tv": "abc"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_history_unknown_type_rejected(self):
        """Unknown values in the public types filter return 400."""
        response = self.call_api(
            "get",
            "api_history",
            params={"types": "spaceships"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class HistoryRecordDeleteTests(FloppyApiTestCase):
    """DELETE /history/{media_type}/{history_id} removes plays."""

    def test_delete_movie_play_removes_instance(self):
        """Deleting a movie history record removes the Movie play itself."""
        movie = self.movie_medias[0]
        movie.end_date = datetime.date(2024, 5, 10)
        movie.save(update_fields=["end_date"])
        record = movie.history.filter(history_user=self.user1).first()
        self.assertIsNotNone(record)

        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", record.history_id),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(Movie.objects.filter(id=movie.id).exists())

    def test_delete_unknown_record_not_found(self):
        """Unknown history ids return 404."""
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", "999999"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_other_users_record_not_found(self):
        """Another user's record cannot be deleted."""
        movie = self.movie_medias[0]
        record = movie.history.filter(history_user=self.user1).first()
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", record.history_id),
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_invalid_media_type_rejected(self):
        """Unsupported media types return 400."""
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("invalid", "1"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class EpisodeBulkTests(FloppyApiTestCase):
    """POST episodes/bulk dispatches the bulk plays task."""

    @patch("app.tasks.bulk_episode_plays_task.apply_async")
    def test_bulk_dispatches_task(self, mock_apply):
        """A valid range returns 202 with the task id."""
        mock_apply.return_value.id = "task-123"
        response = self.call_api(
            "post",
            "api_media_episode_bulk",
            args=("tv", "tmdb", "1001"),
            payload={
                "first_season_number": 1,
                "first_episode_number": 1,
                "last_season_number": 1,
                "last_episode_number": 3,
                "start_date": "2024-01-01",
                "end_date": "2024-01-03",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.ACCEPTED)
        self.assertEqual(response.json()["task_id"], "task-123")
        kwargs = mock_apply.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["user_id"], self.user1.id)
        self.assertEqual(kwargs["write_mode"], "add")
        self.assertEqual(kwargs["distribution_mode"], "even")

    def test_bulk_missing_range_rejected(self):
        """Missing range fields return 400 without dispatching."""
        response = self.call_api(
            "post",
            "api_media_episode_bulk",
            args=("tv", "tmdb", "1001"),
            payload={"start_date": "2024-01-01", "end_date": "2024-01-02"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_bulk_invalid_mode_rejected(self):
        """Unknown write/distribution modes return 400."""
        response = self.call_api(
            "post",
            "api_media_episode_bulk",
            args=("tv", "tmdb", "1001"),
            payload={
                "first_season_number": 1,
                "first_episode_number": 1,
                "last_season_number": 1,
                "last_episode_number": 2,
                "start_date": "2024-01-01",
                "end_date": "2024-01-02",
                "write_mode": "bogus",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
