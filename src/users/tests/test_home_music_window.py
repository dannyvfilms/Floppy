"""Home music shelves sort the whole library but only persist the shown window."""

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import Item, MediaTypes, Sources, Status
from app.models.music import Album, AlbumTracker, Artist, ArtistTracker
from users import home_screen

COUNT = int(os.environ.get("HOME_WINDOW_COUNT", "120"))


class MusicWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="w", password="pw")
        base = datetime(2024, 1, 1, tzinfo=UTC)
        artists = Artist.objects.bulk_create(
            [Artist(name=f"Artist {i:05d}") for i in range(COUNT)]
        )
        albums = Album.objects.bulk_create(
            [Album(title=f"Album {i:05d}", artist=artists[i]) for i in range(COUNT)]
        )
        AlbumTracker.objects.bulk_create(
            [
                AlbumTracker(
                    user=cls.user,
                    album=album,
                    status=Status.COMPLETED.value,
                    end_date=base + timedelta(hours=(i * 7919) % COUNT),
                )
                for i, album in enumerate(albums)
            ]
        )
        ArtistTracker.objects.bulk_create(
            [
                ArtistTracker(
                    user=cls.user, artist=artist, status=Status.COMPLETED.value
                )
                for artist in artists
            ]
        )

    def _shell_count(self):
        return Item.objects.filter(
            source=Sources.MANUAL.value, media_type=MediaTypes.MUSIC.value
        ).count()

    def test_window_matches_full_order_and_persists_only_window(self):
        for build, sort in (
            (home_screen._build_album_home_entries, "title"),
            (home_screen._build_album_home_entries, "recent"),
            (home_screen._build_artist_home_entries, "title"),
        ):
            Item.objects.filter(media_type=MediaTypes.MUSIC.value).delete()
            with CaptureQueriesContext(connection) as fctx:
                fstart = time.process_time()
                full, total = build(self.user, {}, sort, "desc", 0, COUNT)
                fcpu = time.process_time() - fstart
            Item.objects.filter(media_type=MediaTypes.MUSIC.value).delete()
            with CaptureQueriesContext(connection) as ctx:
                start = time.process_time()
                window, total_w = build(self.user, {}, sort, "desc", 10, 14)
                cpu = time.process_time() - start
            self.assertEqual(total, total_w)
            self.assertEqual(
                [e.item.media_id for e in window],
                [e.item.media_id for e in full[10:24]],
            )
            self.assertEqual(self._shell_count(), 14)
            self.assertTrue(all(e.item.pk for e in window))
            report = os.environ.get("HOME_WINDOW_REPORT")
            if report:
                with Path(report).open("a") as fh:
                    fh.write(
                        f"{build.__name__} {sort} n={COUNT} "
                        f"all_persisted(old-equivalent): queries={len(fctx)} "
                        f"cpu={fcpu:.3f}s | window: queries={len(ctx)} "
                        f"cpu={cpu:.3f}s\n"
                    )
