"""A status the user set by hand must survive automatic sync paths.

Regression tests for #361, #375 and #1133: shows the user had marked Dropped,
Paused or Completed (or deleted) kept coming back as In progress overnight.
Each earlier fix guarded one path; these tests pin every automatic path that
could still undo the user's choice, plus the real-play cases that are allowed
to reopen a show.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    DeletedMedia,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from integrations.imports import helpers, stremio
from integrations.imports.trakt import TraktImporter
from integrations.models import StremioAccount
from integrations.tests.imports.test_stremio import (
    encode_watched_bitfield,
    fake_tmdb_find,
    fake_tv_with_seasons,
)
from integrations.webhooks.stremio import StremioWebhookProcessor

SHOW_ID = "1396"
SHOW_IMDB = "tt0903747"
HELD_STATUSES = (Status.DROPPED.value, Status.PAUSED.value)
# Provider metadata for a show/season with nothing left to fan out.
NO_NEW_SEASONS = {"episodes": [], "max_progress": 0, "related": {"seasons": []}}


def _tracked_show(user, status, *, season_numbers=(1,), season_status=None):
    tv_item, _ = Item.objects.get_or_create(
        media_id=SHOW_ID,
        source=Sources.TMDB.value,
        media_type=MediaTypes.TV.value,
        defaults={"title": "Breaking Bad", "image": "http://example.com/s.jpg"},
    )
    tv = TV.objects.create(item=tv_item, user=user, status=status)
    for number in season_numbers:
        season_item, _ = Item.objects.get_or_create(
            media_id=SHOW_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=number,
            defaults={"title": "Breaking Bad", "image": "http://example.com/s.jpg"},
        )
        Season.objects.create(
            item=season_item,
            user=user,
            related_tv=tv,
            status=season_status or status,
        )
    return tv


def _webhook_tv_metadata(media_id, season_numbers, *_args, **_kwargs):
    metadata = {
        "media_id": media_id,
        "title": "Breaking Bad",
        "image": "http://example.com/show.jpg",
    }
    for number in season_numbers:
        metadata[f"season/{number}"] = {
            "image": "http://example.com/season.jpg",
            "episodes": [{"episode_number": 1}, {"episode_number": 2}],
        }
    return metadata


class WebhookRespectsUserStatusTests(TestCase):
    """Scrobble webhooks (Stremio start pings in particular)."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    def _ping(self, *, verified=False, season=1, episode=1):
        payload = {"id": f"{SHOW_IMDB}:{season}:{episode}", "type": "series"}
        if verified:
            payload["_floppy_verified_completion"] = True
        with (
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=_webhook_tv_metadata,
            ),
            patch(
                "app.providers.services.get_media_metadata",
                return_value=NO_NEW_SEASONS,
            ),
        ):
            StremioWebhookProcessor()._handle_tv_episode(
                SHOW_ID, season, episode, payload, self.user,
            )

    def test_start_ping_keeps_held_show_and_season_status(self):
        """A playback-start ping proves nothing was watched; status stays."""
        for status in (*HELD_STATUSES, Status.COMPLETED.value):
            with self.subTest(status=status):
                TV.objects.filter(user=self.user).delete()
                DeletedMedia.objects.all().delete()
                tv = _tracked_show(self.user, status)

                self._ping()

                tv.refresh_from_db()
                self.assertEqual(tv.status, status)
                self.assertEqual(tv.seasons.get().status, status)

    def test_start_ping_does_not_revive_deleted_show(self):
        """A start ping for a show the user deleted must not recreate it."""
        _tracked_show(self.user, Status.DROPPED.value).delete()
        self.assertTrue(DeletedMedia.objects.filter(media_id=SHOW_ID).exists())

        self._ping()

        self.assertFalse(TV.objects.filter(user=self.user).exists())
        self.assertTrue(DeletedMedia.objects.filter(media_id=SHOW_ID).exists())

    def test_start_ping_does_not_revive_show_deleted_under_another_provider(self):
        """A show deleted as TVDB stays deleted when a ping resolves it via TMDB."""
        DeletedMedia.objects.create(
            user=self.user,
            media_type=MediaTypes.TV.value,
            source=Sources.TVDB.value,
            media_id="81189",
        )

        with patch(
            "app.providers.tmdb.tv_with_seasons",
            side_effect=lambda *args, **kwargs: {
                **_webhook_tv_metadata(*args, **kwargs),
                "tvdb_id": "81189",
            },
        ):
            StremioWebhookProcessor()._handle_tv_episode(
                SHOW_ID,
                1,
                1,
                {"id": f"{SHOW_IMDB}:1:1", "type": "series"},
                self.user,
            )

        self.assertFalse(TV.objects.filter(user=self.user).exists())

    def test_start_ping_still_starts_a_planned_show(self):
        """Planning is not a held status: a start ping moves it along."""
        tv = _tracked_show(self.user, Status.PLANNING.value)

        self._ping()

        tv.refresh_from_db()
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)

    def test_verified_play_reopens_dropped_show(self):
        """A verified, real play is the user watching again: it may reopen."""
        tv = _tracked_show(self.user, Status.DROPPED.value)

        self._ping(verified=True)

        tv.refresh_from_db()
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)


class StremioImportRespectsUserStatusTests(TestCase):
    """The recurring Stremio library import (runs every two hours)."""

    def setUp(self):
        """Create a user with a connected Stremio account."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        StremioAccount.objects.create(
            user=self.user,
            auth_key=helpers.encrypt("auth-key"),
        )

    def _run(self, watched_ids):
        video_ids = [
            f"{SHOW_IMDB}:{season}:{episode}"
            for season in (1, 2)
            for episode in range(1, 4)
        ]
        library_items = [
            {
                "_id": SHOW_IMDB,
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(watched_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": sorted(watched_ids)[-1],
                },
            },
        ]
        with (
            patch(
                "integrations.imports.stremio.get_library_items",
                return_value=library_items,
            ),
            patch.object(
                stremio.StremioImporter,
                "_fetch_cinemeta_videos",
                return_value={SHOW_IMDB: video_ids},
            ),
            patch("app.providers.tmdb.find", side_effect=fake_tmdb_find),
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=fake_tv_with_seasons,
            ),
            patch("app.providers.trakt.is_configured", return_value=False),
        ):
            return stremio.importer(None, self.user, "new")

    def test_import_does_not_revive_deleted_show(self):
        """A show the user deleted stays deleted even if Stremio has plays."""
        _tracked_show(self.user, Status.IN_PROGRESS.value).delete()

        self._run({f"{SHOW_IMDB}:1:1", f"{SHOW_IMDB}:1:2"})

        self.assertFalse(TV.objects.filter(user=self.user).exists())

    def test_new_season_under_held_show_keeps_the_show_off_the_shelf(self):
        """Plays of a new season must not open an In progress season."""
        for status in HELD_STATUSES:
            with self.subTest(status=status):
                TV.objects.filter(user=self.user).delete()
                DeletedMedia.objects.all().delete()
                tv = _tracked_show(self.user, status)

                self._run({f"{SHOW_IMDB}:1:1", f"{SHOW_IMDB}:2:1"})

                tv.refresh_from_db()
                self.assertEqual(tv.status, status)
                season_two = tv.seasons.get(item__season_number=2)
                self.assertEqual(season_two.status, status)


class TraktImportRespectsUserStatusTests(TestCase):
    """A recurring Trakt import in New mode."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    @staticmethod
    def _metadata(media_type, *_args, **_kwargs):
        if media_type == MediaTypes.TV.value:
            return {
                "title": "Breaking Bad",
                "image": "tv.jpg",
                "last_episode_season": 5,
                "max_progress": 10,
            }
        return {
            "title": "Season",
            "image": "season.jpg",
            "episodes": [
                {"episode_number": 1, "still_path": None},
                {"episode_number": 2, "still_path": None},
            ],
            "max_progress": 2,
        }

    def test_new_season_under_held_show_inherits_the_held_status(self):
        """Trakt history for a new season must not reopen a dropped show."""
        for status in HELD_STATUSES:
            with self.subTest(status=status):
                TV.objects.filter(user=self.user).delete()
                DeletedMedia.objects.all().delete()
                tv = _tracked_show(self.user, status)
                entry = {
                    "type": "episode",
                    "episode": {"season": 2, "number": 1, "title": "E1"},
                    "show": {"title": "Breaking Bad", "ids": {"tmdb": int(SHOW_ID)}},
                    "watched_at": "2023-01-02T00:00:00.000Z",
                }

                with patch.object(
                    TraktImporter,
                    "_get_metadata",
                    side_effect=self._metadata,
                ):
                    importer = TraktImporter("u", self.user, "new")
                    importer.process_watched_episode(entry)

                new_seasons = importer.bulk_media[MediaTypes.SEASON.value]
                self.assertEqual(importer.bulk_media[MediaTypes.TV.value], [])
                self.assertEqual([s.status for s in new_seasons], [status])
                self.assertEqual(importer.bulk_media[MediaTypes.TV.value], [])
                tv.refresh_from_db()
                self.assertEqual(tv.status, status)


    def test_season_watchlist_entry_reuses_the_tracked_show(self):
        """A season-level Trakt row must not queue a second, In progress show."""
        tv = _tracked_show(self.user, Status.DROPPED.value)

        with patch.object(TraktImporter, "_get_metadata", side_effect=self._metadata):
            importer = TraktImporter("u", self.user, "new")
            tv_obj = importer._get_tv_obj(SHOW_ID, {"title": "Breaking Bad"}, None)

        self.assertEqual(tv_obj.pk, tv.pk)
        self.assertEqual(tv_obj.status, Status.DROPPED.value)
        self.assertEqual(importer.bulk_media[MediaTypes.TV.value], [])

class ModelRecomputeRespectsUserStatusTests(TestCase):
    """Automatic next-season logic in the TV/Season models."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    def test_completing_a_season_does_not_reopen_held_show(self):
        """Finishing season 1 of a dropped show must not start season 2."""
        for status in HELD_STATUSES:
            with self.subTest(status=status):
                TV.objects.filter(user=self.user).delete()
                DeletedMedia.objects.all().delete()
                tv = _tracked_show(self.user, status, season_numbers=(1, 2))
                season_one = tv.seasons.get(item__season_number=1)

                with (
                    patch("app.models.item.Item.fetch_releases"),
                    patch(
                        "app.providers.services.get_media_metadata",
                        return_value=NO_NEW_SEASONS,
                    ),
                ):
                    season_one.status = Status.COMPLETED.value
                    season_one.save()

                tv.refresh_from_db()
                self.assertEqual(tv.status, status)
                self.assertEqual(
                    tv.seasons.get(item__season_number=2).status,
                    status,
                )

