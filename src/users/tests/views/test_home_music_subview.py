"""Smoke tests for music subview Home rows (albums/artists/tracks)."""

import json
import pickle
from dataclasses import dataclass
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.models import MediaTypes, Status
from app.models.music import Album, AlbumTracker, Artist, ArtistTracker
from users import home_screen
from users.models import (
    HomeScreenRow,
    HomeScreenRowTypeChoices,
    MediaStatusChoices,
)


@dataclass
class _FakeTrack:
    """Minimal stand-in for a Track: only the attributes the row builder reads."""

    album: object
    repeats: int
    last_played_at: object
    created_at: object


class MusicSubviewHomeTests(TestCase):
    def setUp(self):
        # Home row results are cached by row/user pk, which TestCase rollbacks
        # reuse across tests — clear to avoid stale empty-row sentinels.
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="musicfan",
            password="pw",
        )
        self.user.music_enabled = True
        self.user.save(update_fields=["music_enabled"])

        self.artist = Artist.objects.create(name="Queen", image="http://x/a.jpg")
        self.album = Album.objects.create(
            title="A Night at the Opera",
            artist=self.artist,
            image="http://x/al.jpg",
        )
        AlbumTracker.objects.create(
            user=self.user,
            album=self.album,
            status=Status.PLANNING.value,
        )
        ArtistTracker.objects.create(
            user=self.user,
            artist=self.artist,
            status=Status.IN_PROGRESS.value,
        )

    def _add_music_row(self, subview, status):
        return HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.MUSIC.value,
            position=10,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by="title",
            direction="asc",
            filters={"status": status, "subview": subview},
        )

    def _music_group(self, groups):
        return next(
            (g for g in groups if g["media_type"] == MediaTypes.MUSIC.value),
            None,
        )

    def test_albums_subview_surfaces_album_tracker(self):
        self._add_music_row("albums", Status.PLANNING.value)
        groups = home_screen.build_home_page_groups(self.user, items_limit=10)
        group = self._music_group(groups)
        self.assertIsNotNone(group, "music group should be present")
        titles = [entry.item.title for row in group["rows"] for entry in row["items"]]
        self.assertIn("A Night at the Opera", titles)

    def test_artists_subview_surfaces_artist_tracker(self):
        self._add_music_row("artists", Status.IN_PROGRESS.value)
        groups = home_screen.build_home_page_groups(self.user, items_limit=10)
        group = self._music_group(groups)
        self.assertIsNotNone(group)
        titles = [entry.item.title for row in group["rows"] for entry in row["items"]]
        self.assertIn("Queen", titles)

    def test_albums_status_filter_excludes_other_statuses(self):
        self._add_music_row("albums", Status.IN_PROGRESS.value)
        groups = home_screen.build_home_page_groups(self.user, items_limit=10)
        # No in-progress albums tracked, so the music group should be empty/absent.
        group = self._music_group(groups)
        self.assertIsNone(group)

    def test_validate_accepts_music_subview(self):
        normalized = home_screen.validate_library_row_filters(
            {"status": Status.PLANNING.value, "subview": "albums"},
            MediaTypes.MUSIC.value,
        )
        self.assertEqual(normalized["subview"], "albums")

    def test_validate_rejects_bad_subview(self):
        with self.assertRaises(home_screen.HomeScreenValidationError):
            home_screen.validate_library_row_filters(
                {"subview": "nonsense"},
                MediaTypes.MUSIC.value,
            )

    def test_subview_field_present_and_first_for_music(self):
        fields = home_screen.build_filter_field_data(self.user, MediaTypes.MUSIC.value)
        keys = [f["key"] for f in fields]
        self.assertEqual(keys[0], "subview")

    def test_subview_field_absent_for_non_music(self):
        fields = home_screen.build_filter_field_data(self.user, MediaTypes.MOVIE.value)
        self.assertNotIn("subview", [f["key"] for f in fields])

    def test_home_page_renders_album_card(self):
        self._add_music_row("albums", Status.PLANNING.value)
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A Night at the Opera")
        # Album cards carry the artist as the hover subtitle (mirrors the library).
        self.assertContains(response, "Queen")

    def test_recent_music_album_entries_are_picklable(self):
        # Regression test for #1122: the "Recently Played Music" row is cached
        # via django_redis, which pickles cache values. A locally-scoped
        # adapter class previously broke this with an unpicklable-object error.
        now = datetime(2024, 1, 1, tzinfo=UTC)
        track = _FakeTrack(
            album=self.album,
            repeats=3,
            last_played_at=now,
            created_at=now,
        )
        entries = home_screen._build_recent_music_album_entries([track])
        self.assertEqual(len(entries), 1)

        roundtripped = pickle.loads(pickle.dumps(entries))
        self.assertEqual(roundtripped[0].media.title, "A Night at the Opera")
        self.assertEqual(roundtripped[0].media.play_count, 3)

    def test_home_page_renders_artist_card(self):
        self._add_music_row("artists", Status.IN_PROGRESS.value)
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Queen")

    def test_settings_page_renders(self):
        """Lazy translated labels serialize while filter values stay canonical."""
        row = self._add_music_row("albums", Status.PLANNING.value)
        self.client.force_login(self.user)
        for language, last_listened_label, rating_label in (
            ("en", "Last Listened", "Rating"),
            ("de", "Zuletzt gehört", "Bewertung"),
        ):
            with self.subTest(language=language):
                self.user.ui_language = language
                self.user.save(update_fields=["ui_language"])
                response = self.client.get("/settings/home-screen")
                self.assertEqual(response.status_code, 200)
                sections = json.loads(response.context["home_screen_sections_json"])
                music = next(s for s in sections if s["media_type"] == "music")
                choices = {
                    choice["value"]: choice["label"]
                    for choice in music["sort_choices"]["library_query"]
                }
                self.assertEqual(choices["end_date"], last_listened_label)
                self.assertEqual(choices["score"], rating_label)
                music_row = next(r for r in music["rows"] if r["id"] == row.id)
                self.assertEqual(music_row["filters"]["status"], ["Planning"])
                self.assertEqual(music_row["filters"]["subview"], "albums")

    def test_destination_url_pins_status_all_for_all_status_row(self):
        row = self._add_music_row("tracks", MediaStatusChoices.ALL.value)
        url = home_screen.home_row_destination_url(row, self.user)
        self.assertIn(f"status={MediaStatusChoices.ALL.value}", url)
        self.assertIn("subview=tracks", url)

    def test_destination_url_passes_status_and_subview_for_albums(self):
        row = self._add_music_row("albums", Status.PLANNING.value)
        url = home_screen.home_row_destination_url(row, self.user)
        self.assertIn("status=Planning", url)
        self.assertIn("subview=albums", url)

    def test_albums_upcoming_sort_does_not_crash(self):
        row = self._add_music_row("albums", Status.PLANNING.value)
        row.sort_by = "upcoming"
        row.direction = "asc"
        entries = home_screen._library_query_entries(self.user, row)
        self.assertTrue(any(e.item.title == "A Night at the Opera" for e in entries))

    def test_row_title_includes_subview_label(self):
        title = home_screen.describe_library_query(
            {"status": Status.PLANNING.value, "subview": "albums"},
            self.user,
            MediaTypes.MUSIC.value,
        )
        self.assertIn("Albums", title)
