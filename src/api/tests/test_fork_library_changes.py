"""Incremental sync of the media list: updated_at, updated_since, activity, deletions (#1527)."""

from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone

from app.models import TV, Episode, ItemTag, Movie, Season, Tag
from lists.models import CustomList, CustomListItem

from .base import FloppyApiTestCase


def _past(movie, days=10):
    """Age a row so a later change is visible against it."""
    Movie.objects.filter(pk=movie.pk).update(
        updated_at=timezone.now() - timedelta(days=days),
    )
    movie.refresh_from_db()


class UpdatedSinceTests(FloppyApiTestCase):
    """GET /media/ exposes updated_at and filters on it."""

    def setUp(self):
        super().setUp()
        self.movies = list(Movie.objects.filter(user=self.user1))
        for movie in self.movies:
            _past(movie)
        self.cutoff = (timezone.now() - timedelta(days=1)).isoformat()

    def _list(self, **params):
        return self.call_api(
            "get",
            "api_media_list",
            params={"media_type": "movie", "limit": 100, **params},
            headers=self.auth_headers,
        )

    def _ids(self, response):
        return {row["consumption_id"] for row in response.json()["results"]}

    def test_entries_expose_updated_at(self):
        """Every result carries updated_at."""
        results = self._list().json()["results"]
        self.assertTrue(results)
        self.assertTrue(all(row["updated_at"] for row in results))

    def test_filter_returns_only_changed_entries(self):
        """Only an entry edited after the cutoff is returned."""
        self.assertEqual(self._ids(self._list(updated_since=self.cutoff)), set())

        edited = self.movies[0]
        edited.notes = "changed"
        edited.save()

        self.assertEqual(
            self._ids(self._list(updated_since=self.cutoff)),
            {edited.pk},
        )

    def test_score_edit_moves_updated_at_unlike_sort_updated(self):
        """A score-only edit is found (sort=updated misses it)."""
        edited = self.movies[1]
        edited.score = 7
        edited.save(update_fields=["score"])
        self.assertIn(edited.pk, self._ids(self._list(updated_since=self.cutoff)))

    def test_queryset_update_moves_updated_at(self):
        """Bulk writers stamp rows too."""
        Movie.objects.filter(pk=self.movies[2].pk).update(notes="bulk")
        self.assertEqual(
            self._ids(self._list(updated_since=self.cutoff)),
            {self.movies[2].pk},
        )

    def test_list_and_tag_membership_move_updated_at(self):
        """Adding to a list or tagging counts as a change."""
        movie = self.movies[0]
        custom_list = CustomList.objects.create(name="L", owner=self.user1)
        CustomListItem.objects.create(item=movie.item, custom_list=custom_list)
        self.assertIn(movie.pk, self._ids(self._list(updated_since=self.cutoff)))

        _past(movie)
        tag = Tag.objects.create(user=self.user1, name="t")
        ItemTag.objects.create(tag=tag, item=movie.item)
        self.assertIn(movie.pk, self._ids(self._list(updated_since=self.cutoff)))

    def test_offset_with_plus_sign_is_accepted(self):
        """An unescaped + in a UTC offset (read as a space) still parses."""
        response = self.call_api(
            "get",
            "api_media_list",
            params={"updated_since": "2020-01-01T00:00:00+00:00"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        raw = self.client.get(
            "/api/v1/media/?updated_since=2020-01-01T00:00:00+00:00",
            **self.auth_headers,
        )
        self.assertEqual(raw.status_code, HTTP.OK)

    def test_invalid_value_is_rejected(self):
        """A bad datetime is a 400, not an unfiltered list."""
        response = self._list(updated_since="yesterday")
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class LibraryActivityTests(FloppyApiTestCase):
    """GET /library/activity/ and /library/deleted/."""

    def _activity(self):
        return self.call_api(
            "get", "api_library_activity", headers=self.auth_headers,
        ).json()["last_activity"]

    def test_activity_moves_on_edit_only(self):
        """The stamp is stable until something changes."""
        first = self._activity()
        self.assertEqual(first, self._activity())
        movie = Movie.objects.filter(user=self.user1).first()
        movie.notes = "x"
        movie.save()
        self.assertGreater(self._activity(), first)

    def test_deletion_is_reported_and_moves_activity(self):
        """A deleted entry shows in /deleted/ and bumps last_activity."""
        movie = Movie.objects.filter(user=self.user1).first()
        item = movie.item
        before = self._activity()
        movie.delete()

        self.assertGreaterEqual(self._activity(), before)
        response = self.call_api(
            "get", "api_library_deleted", headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = response.json()["results"]
        self.assertEqual(
            [(r["media_type"], r["source"], r["media_id"]) for r in results],
            [(item.media_type, item.source, item.media_id)],
        )

        future = (timezone.now() + timedelta(days=1)).isoformat()
        empty = self.call_api(
            "get",
            "api_library_deleted",
            params={"deleted_since": future},
            headers=self.auth_headers,
        )
        self.assertEqual(empty.json()["results"], [])

    def test_other_users_deletions_are_not_visible(self):
        """Tombstones are per account."""
        Movie.objects.filter(user=self.user1).first().delete()
        response = self.call_api(
            "get", "api_library_deleted", headers=self.auth_headers2,
        )
        self.assertEqual(response.json()["results"], [])


class SeasonAndEpisodeTests(FloppyApiTestCase):
    """Seasons are tombstoned; bulk episode writes still stamp their owners."""

    def setUp(self):
        super().setUp()
        self.season = Season.objects.filter(user=self.user1).first()
        self.tv = self.season.related_tv
        Season.objects.filter(pk=self.season.pk).update(
            updated_at=timezone.now() - timedelta(days=10),
        )
        TV.objects.filter(pk=self.tv.pk).update(
            updated_at=timezone.now() - timedelta(days=10),
        )
        self.cutoff = timezone.now() - timedelta(days=1)

    def test_season_deletion_is_reported_with_season_number(self):
        """Deleting a season is in the feed (DeletedMedia never covered it)."""
        item = self.season.item
        self.season.delete()
        response = self.call_api(
            "get", "api_library_deleted", headers=self.auth_headers,
        )
        self.assertIn(
            ("season", item.media_id, item.season_number),
            [
                (r["media_type"], r["media_id"], r["season_number"])
                for r in response.json()["results"]
            ],
        )

    def test_bulk_episode_update_stamps_season_and_show(self):
        """A queryset update of episodes moves the season and show."""
        episode = Episode.objects.create(
            related_season=self.season,
            item=self.items_by_type["episode"][0]
            if "episode" in self.items_by_type
            else self.season.item,
        )
        Season.objects.filter(pk=self.season.pk).update(
            updated_at=timezone.now() - timedelta(days=10),
        )
        TV.objects.filter(pk=self.tv.pk).update(
            updated_at=timezone.now() - timedelta(days=10),
        )
        Episode.objects.filter(pk=episode.pk).update(notes="bulk")
        self.season.refresh_from_db()
        self.tv.refresh_from_db()
        self.assertGreater(self.season.updated_at, self.cutoff)
        self.assertGreater(self.tv.updated_at, self.cutoff)
