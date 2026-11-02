from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.history_cache_range_prefetch import HistoryRangePrefetch
from app.models import (
    Album,
    Artist,
    Item,
    MediaTypes,
    Music,
    Sources,
    Status,
    Track,
)
from app.signals import refresh_history_cache_on_music_change


class MusicHistoryConsistencyTests(TestCase):
    @patch("app.signals._handle_media_cache_change")
    def test_music_cache_invalidation_waits_for_commit(self, mock_handle_change):
        played_at = timezone.now().replace(second=0, microsecond=0)
        instance = SimpleNamespace(user_id=42, end_date=played_at)

        with self.captureOnCommitCallbacks(execute=True):
            refresh_history_cache_on_music_change(
                Music,
                instance,
                using="default",
            )
            mock_handle_change.assert_not_called()

        mock_handle_change.assert_called_once()
        args, kwargs = mock_handle_change.call_args
        self.assertEqual(args[:2], (42, MediaTypes.MUSIC.value))
        self.assertEqual(kwargs["reason"], "music_change")
        self.assertEqual(
            kwargs["statistics_day_values"],
            [history_cache.history_day_key(played_at)],
        )

    @patch("app.signals._handle_media_cache_change")
    def test_music_cache_invalidation_does_not_run_after_rollback(
        self, mock_handle_change
    ):
        instance = SimpleNamespace(user_id=42, end_date=timezone.now())
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    refresh_history_cache_on_music_change(
                        Music, instance, using="default"
                    )
                    raise RuntimeError("rollback")

        self.assertEqual(callbacks, [])
        mock_handle_change.assert_not_called()

    def test_history_day_prefers_current_music_relations(self):
        user = get_user_model().objects.create_user(
            username="music-history-consistency",
            password="12345",
        )
        stale_artist = Artist.objects.create(name="Stale Artist")
        stale_album = Album.objects.create(title="Stale Album", artist=stale_artist)
        stale_track = Track.objects.create(
            album=stale_album,
            title="Stale Track",
            track_number=1,
            duration_ms=120000,
        )
        current_artist = Artist.objects.create(name="Current Artist")
        current_album = Album.objects.create(
            title="Current Album",
            artist=current_artist,
        )
        current_track = Track.objects.create(
            album=current_album,
            title="Current Track",
            track_number=1,
            duration_ms=240000,
        )
        item = Item.objects.create(
            media_id="current-track",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Current Track",
        )
        played_at = timezone.now().replace(second=0, microsecond=0)
        music = Music.objects.create(
            item=item,
            user=user,
            album=current_album,
            artist=current_artist,
            track=current_track,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=played_at,
            end_date=played_at,
        )

        # Simulate the stale HistoricalMusic foreign keys that prompted the
        # original local fix while leaving the live Music relations correct.
        music.history.all().update(
            album_id=stale_album.id,
            track_id=stale_track.id,
        )

        day_key = history_cache.history_day_key(played_at)
        day = history_cache.build_history_day(
            user, day_key, "sessions", media_types=(MediaTypes.MUSIC.value,)
        )
        prefetch = HistoryRangePrefetch(
            user,
            [day_key],
            "sessions",
            {day_key: {MediaTypes.MUSIC.value}},
        )
        prefetched_day = history_cache.build_history_day(
            user, day_key, "sessions", media_types=(MediaTypes.MUSIC.value,),
            prefetch=prefetch,
        )
        self.assertEqual(prefetched_day, day)

        self.assertIsNotNone(day)
        music_entries = [
            entry
            for entry in day["entries"]
            if entry["media_type"] == MediaTypes.MUSIC.value
        ]
        self.assertEqual(len(music_entries), 1)
        self.assertEqual(music_entries[0]["title"], "Current Album")
        self.assertEqual(music_entries[0]["artist_name"], "Current Artist")
        self.assertEqual(music_entries[0]["runtime_minutes"], 4)
