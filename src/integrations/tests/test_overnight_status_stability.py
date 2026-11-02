"""One simulated night must not undo any status the user set (#1133).

The reporter's shows reverted "at midnight" and each earlier fix guarded only
the path it was looking at. This test doesn't pick paths: it rebuilds their
setup (Stremio connected with its recurring sync, a New-mode Trakt schedule,
shows they dropped, paused or deleted), then runs every task in the Celery
beat schedule plus every schedule the user owns, twice, and checks nothing
the user decided has moved. A new beat task has to be listed in SKIPPED_TASKS
with a reason or it runs here too.
"""

import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from app.models import (
    TV,
    DeletedMedia,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from config.celery import app as celery_app
from integrations.imports import helpers, stremio
from integrations.imports.trakt import TraktImporter
from integrations.models import StremioAccount
from integrations.tests.imports.test_stremio import (
    encode_watched_bitfield,
    fake_tmdb_find,
    fake_tv_with_seasons,
)

# Load every task module, as the background worker does.
celery_app.loader.import_default_modules()

# Beat tasks that only touch the filesystem or the broker, never media rows.
SKIPPED_TASKS = {
    "Write database snapshot": "writes a backup file to disk",
    "Cleanup image cache": "deletes cached image files",
    "Repair Celery broker bindings": "talks to the Redis broker only",
}

DROPPED_ID, DROPPED_IMDB = "1396", "tt0903747"
PAUSED_ID, PAUSED_IMDB = "87108", "tt7366338"
DELETED_ID = "555"


def _library_items():
    dropped_videos = [
        f"{DROPPED_IMDB}:{season}:{episode}"
        for season in (1, 2)
        for episode in range(1, 4)
    ]
    paused_videos = [f"{PAUSED_IMDB}:1:{episode}" for episode in range(1, 4)]
    videos = {DROPPED_IMDB: dropped_videos, PAUSED_IMDB: paused_videos}
    items = [
        {
            "_id": DROPPED_IMDB,
            "type": "series",
            "name": "Dropped show",
            "removed": False,
            "temp": False,
            "state": {
                # Stremio (fed by Trakt) still lists a newer season as watched.
                "watched": encode_watched_bitfield(
                    dropped_videos,
                    {f"{DROPPED_IMDB}:1:1", f"{DROPPED_IMDB}:2:1"},
                ),
                "lastWatched": "2026-09-01T00:00:00Z",
                "video_id": f"{DROPPED_IMDB}:2:1",
            },
        },
        {
            "_id": PAUSED_IMDB,
            "type": "series",
            "name": "Paused show",
            "removed": True,
            "temp": False,
            "state": {
                "watched": encode_watched_bitfield(
                    paused_videos,
                    set(paused_videos),
                ),
                "lastWatched": "2026-09-01T00:00:00Z",
                "video_id": paused_videos[-1],
            },
        },
        {
            "_id": f"tmdb:{DELETED_ID}",
            "type": "series",
            "name": "Deleted show",
            "removed": False,
            "temp": False,
            "state": {"timeOffset": 500000, "lastWatched": "2026-09-01T00:00:00Z"},
        },
    ]
    return items, videos


def _trakt_history():
    return [
        {
            "type": "episode",
            "episode": {"season": season, "number": 1, "title": "E1"},
            "show": {"title": "Show", "ids": {"tmdb": int(media_id)}},
            "watched_at": "2026-09-01T00:00:00.000Z",
        }
        for media_id, season in (
            (DROPPED_ID, 2),
            (PAUSED_ID, 1),
            (DELETED_ID, 1),
        )
    ]


def _trakt_paginated(_importer, endpoint, *_args, **_kwargs):
    return _trakt_history() if "history" in endpoint else []


def _trakt_metadata(media_type, *_args, **_kwargs):
    if media_type == MediaTypes.TV.value:
        return {"title": "Show", "image": "", "last_episode_season": 5}
    return {
        "title": "Season",
        "image": "",
        "episodes": [{"episode_number": n, "still_path": None} for n in (1, 2)],
        "max_progress": 2,
    }


class OvernightStatusStabilityTests(TestCase):
    """Run a whole night's schedule against a user's held statuses."""

    def setUp(self):
        """Recreate the reporter's setup."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        StremioAccount.objects.create(
            user=self.user,
            auth_key=helpers.encrypt("auth-key"),
        )
        self.dropped = self._show(DROPPED_ID, Status.DROPPED.value)
        self.paused = self._show(PAUSED_ID, Status.PAUSED.value)
        self._show(DELETED_ID, Status.IN_PROGRESS.value).delete()

        midnight = CrontabSchedule.objects.create(hour=0, minute=0)
        PeriodicTask.objects.create(
            name="Import from Trakt for u at 00:00 daily",
            task="Import from Trakt",
            crontab=midnight,
            kwargs=json.dumps(
                {
                    "username": "u",
                    "user_id": self.user.id,
                    "mode": "new",
                    "token": helpers.encrypt("token"),
                },
            ),
        )
        every_two_hours = IntervalSchedule.objects.create(
            every=2,
            period=IntervalSchedule.HOURS,
        )
        PeriodicTask.objects.create(
            name="Import from Stremio for u",
            task="Import from Stremio (Recurring)",
            interval=every_two_hours,
            kwargs=json.dumps({"user_id": self.user.id}),
        )

    def _show(self, media_id, status):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title=f"Show {media_id}",
        )
        tv = TV.objects.create(item=item, user=self.user, status=status)
        season_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title=f"Show {media_id}",
        )
        Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=status,
        )
        return tv

    def _run_night(self):
        """Run every beat task and every user schedule once; return their names."""
        library_items, videos = _library_items()
        ran = []
        with (
            patch(
                "integrations.imports.stremio.get_library_items",
                return_value=library_items,
            ),
            patch.object(
                stremio.StremioImporter,
                "_fetch_cinemeta_videos",
                return_value=videos,
            ),
            patch("app.providers.tmdb.find", side_effect=fake_tmdb_find),
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=lambda media_id, seasons, *_a, **_k: fake_tv_with_seasons(
                    media_id,
                    seasons,
                ),
            ),
            patch("app.providers.trakt.is_configured", return_value=False),
            patch.object(
                TraktImporter,
                "_get_paginated_data",
                autospec=True,
                side_effect=_trakt_paginated,
            ),
            patch.object(TraktImporter, "_make_api_request", return_value={}),
            patch.object(TraktImporter, "_get_metadata", side_effect=_trakt_metadata),
        ):
            for entry in settings.CELERY_BEAT_SCHEDULE.values():
                if entry["task"] in SKIPPED_TASKS:
                    continue
                celery_app.tasks[entry["task"]].apply(
                    args=entry.get("args", ()),
                    kwargs=entry.get("kwargs", {}),
                )
                ran.append(entry["task"])
            for schedule in PeriodicTask.objects.filter(
                kwargs__contains=f'"user_id": {self.user.id}',
            ):
                celery_app.tasks[schedule.task].apply(
                    kwargs=json.loads(schedule.kwargs),
                )
                ran.append(schedule.task)
        return ran

    def test_a_night_of_syncs_leaves_user_statuses_alone(self):
        """Dropped/paused shows stay put and a deleted show stays deleted."""
        for _ in range(2):
            ran = self._run_night()

        self.assertIn("Reload calendar", ran)
        self.assertIn("Import from Trakt", ran)
        self.assertIn("Import from Stremio (Recurring)", ran)
        # The syncs really ran: the newer season's play from Stremio/Trakt is
        # recorded, it just doesn't reopen the show.
        self.assertTrue(
            Episode.objects.filter(
                related_season__related_tv=self.dropped,
                item__season_number=2,
            ).exists(),
        )

        for tv, status in (
            (self.dropped, Status.DROPPED.value),
            (self.paused, Status.PAUSED.value),
        ):
            tv.refresh_from_db()
            self.assertEqual(tv.status, status, tv.item.media_id)
            self.assertFalse(
                tv.seasons.filter(status=Status.IN_PROGRESS.value).exists(),
                tv.item.media_id,
            )
        self.assertFalse(
            TV.objects.filter(user=self.user, item__media_id=DELETED_ID).exists(),
        )
        self.assertTrue(
            DeletedMedia.objects.filter(user=self.user, media_id=DELETED_ID).exists(),
        )

    def test_every_beat_task_is_run_or_explicitly_skipped(self):
        """A new scheduled task can't silently escape this night simulation."""
        registered = set(celery_app.tasks)
        for entry in settings.CELERY_BEAT_SCHEDULE.values():
            self.assertIn(entry["task"], registered)
