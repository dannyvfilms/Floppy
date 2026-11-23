"""Music artist and album subviews honour the menu's rating and date ranges.

The subviews read from ArtistTracker/AlbumTracker instead of the shared
library-query engine, so they ignored ``rating_min``/``rating_max`` and the
``*_from``/``*_to`` date ranges the filter menu sends: every row passed and the
controls did nothing (issue #2104). These tests lock the range semantics to
``app.library_query.filters``.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Status
from app.models.music import Album, AlbumTracker, Artist, ArtistTracker


class MusicRangeFilterTests(TestCase):
    """Rating, date added and release date narrow the artist/album lists."""

    def setUp(self):
        """Use an isolated cache and a signed-in library owner."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="music-ranges", password="test"
        )
        self.user.music_enabled = True
        self.user.save(update_fields=["music_enabled"])
        self.client.force_login(self.user)
        self.artist = Artist.objects.create(name="Alpha", image="http://x/a.jpg")
        self.album = Album.objects.create(
            title="Alpha", artist=self.artist, image="http://x/al.jpg"
        )

    def _titles(self, subview, **params):
        """Return the names the subview rendered under the given parameters."""
        response = self.client.get(
            reverse("medialist", args=["music"]),
            {"subview": subview, **params},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["media_list"]), response.context["result_count"])
        if subview == "albums":
            return [tracker.album.title for tracker in response.context["media_list"]]
        return [tracker.artist.name for tracker in response.context["media_list"]]

    def _artist_tracker(self, name, **fields):
        artist = Artist.objects.create(name=name, image="http://x/a.jpg")
        return ArtistTracker.objects.create(user=self.user, artist=artist, **fields)

    def _album_tracker(self, title, **fields):
        album = Album.objects.create(
            title=title, artist=self.artist, image="http://x/al.jpg"
        )
        return AlbumTracker.objects.create(user=self.user, album=album, **fields)

    def test_artist_rating_range_keeps_only_rows_inside_it(self):
        self._artist_tracker("Low", status=Status.COMPLETED.value, score=Decimal("5.0"))
        self._artist_tracker("High", status=Status.COMPLETED.value, score=Decimal("9.0"))
        self.assertEqual(self._titles("artists", rating_min="8"), ["High"])
        self.assertEqual(self._titles("artists", rating_max="6"), ["Low"])

    def test_artist_rating_range_drops_unrated_rows(self):
        self._artist_tracker("Rated", status=Status.COMPLETED.value, score=Decimal("9.0"))
        self._artist_tracker("Unrated", status=Status.COMPLETED.value)
        # A range asks for a score, so a row without one cannot match it.
        self.assertEqual(self._titles("artists", rating_min="1"), ["Rated"])

    def test_album_rating_range_keeps_only_rows_inside_it(self):
        self._album_tracker("Low", status=Status.COMPLETED.value, score=Decimal("5.0"))
        self._album_tracker("High", status=Status.COMPLETED.value, score=Decimal("9.0"))
        self.assertEqual(self._titles("albums", rating_min="8"), ["High"])
        self.assertEqual(self._titles("albums", rating_max="6"), ["Low"])

    def test_artist_date_added_range_uses_the_row_created_at(self):
        old = self._artist_tracker("Old", status=Status.COMPLETED.value)
        self._artist_tracker("New", status=Status.COMPLETED.value)
        ArtistTracker.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        today = timezone.localdate().isoformat()
        self.assertEqual(self._titles("artists", date_added_from=today), ["New"])

    def test_album_date_added_range_uses_the_row_created_at(self):
        old = self._album_tracker("Old", status=Status.COMPLETED.value)
        self._album_tracker("New", status=Status.COMPLETED.value)
        AlbumTracker.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        today = timezone.localdate().isoformat()
        self.assertEqual(self._titles("albums", date_added_from=today), ["New"])

    def test_album_release_date_range_uses_the_album_release_date(self):
        old = self._album_tracker("Old", status=Status.COMPLETED.value)
        new = self._album_tracker("New", status=Status.COMPLETED.value)
        Album.objects.filter(pk=old.album_id).update(
            release_date=timezone.localdate() - timedelta(days=400)
        )
        Album.objects.filter(pk=new.album_id).update(
            release_date=timezone.localdate() - timedelta(days=10)
        )
        today = timezone.localdate()
        self.assertEqual(
            self._titles(
                "albums",
                release_date_from=(today - timedelta(days=30)).isoformat(),
            ),
            ["New"],
        )

    def test_no_ranges_keeps_every_row(self):
        self._artist_tracker("Low", status=Status.COMPLETED.value, score=Decimal("5.0"))
        self._artist_tracker("Unrated", status=Status.COMPLETED.value)
        self.assertEqual(sorted(self._titles("artists")), ["Low", "Unrated"])
