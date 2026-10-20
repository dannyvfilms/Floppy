import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app.discover.tab_cache import DISCOVER_TAB_PREFIX
from app.history_cache_utils import HISTORY_DAY_PREFIX, HISTORY_INDEX_PREFIX
from app.models import (
    TV,
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Book,
    DeletedMedia,
    DiscoverRowCache,
    DiscoverTasteProfile,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Music,
    MusicReleasePreference,
    Season,
    Sources,
    Status,
)
from app.statistics_cache import STATISTICS_CACHE_PREFIX, STATISTICS_DAY_PREFIX
from integrations.imports.helpers import decrypt


class TmdbProxyUpdateTests(TestCase):
    """Tests for the Advanced settings TMDB proxy field."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def tearDown(self):
        """Avoid leaking the tmdb proxy cache key between tests."""
        cache.delete("tmdb_proxy_url")
        super().tearDown()

    def test_update_tmdb_proxy_saves_encrypted_value(self):
        """Posting a proxy URL should save it encrypted and invalidate the cache."""
        cache.set("tmdb_proxy_url", "stale-value", 60)

        response = self.client.post(
            reverse("update_tmdb_proxy"),
            {"tmdb_proxy_url": "socks5://user:pass@host:1080"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.user.refresh_from_db()

        self.assertNotEqual(self.user.tmdb_proxy_url, "socks5://user:pass@host:1080")
        self.assertEqual(
            decrypt(self.user.tmdb_proxy_url),
            "socks5://user:pass@host:1080",
        )
        self.assertIsNone(cache.get("tmdb_proxy_url"))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("updated successfully", str(messages[0]))

    def test_update_tmdb_proxy_blank_clears_value(self):
        """Posting a blank value should clear the stored proxy URL."""
        from integrations.imports.helpers import encrypt

        self.user.tmdb_proxy_url = encrypt("socks5://host:1080")
        self.user.save(update_fields=["tmdb_proxy_url"])

        response = self.client.post(
            reverse("update_tmdb_proxy"),
            {"tmdb_proxy_url": ""},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.tmdb_proxy_url, "")

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("removed", str(messages[0]))

    def test_advanced_page_shows_configured_status(self):
        """The advanced page should reflect whether a proxy is configured."""
        response = self.client.get(reverse("advanced"))
        self.assertFalse(response.context["tmdb_proxy_configured"])

        from integrations.imports.helpers import encrypt

        self.user.tmdb_proxy_url = encrypt("socks5://host:1080")
        self.user.save(update_fields=["tmdb_proxy_url"])

        response = self.client.get(reverse("advanced"))
        self.assertTrue(response.context["tmdb_proxy_configured"])


class CacheClearButtonsTests(TestCase):
    """Tests for the per-cache clear buttons in Settings > Advanced."""

    def setUp(self):
        """Create two users so per-user clears can be checked for cross-talk."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        self.client.login(**self.credentials)

    def test_advanced_page_renders_cache_management_buttons_and_overlay(self):
        """The Advanced page should render a button and confirm copy per cache."""
        response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Cache Management")
        for key in ("search", "history", "statistics", "discover", "all"):
            self.assertContains(response, f"openConfirm('{key}')")
        self.assertContains(response, "Clear All Caches")
        # The "clear all" warning is the one place placeholder-value behavior
        # (statistics rebuilds async, unlike the others) needs to be called out.
        self.assertContains(response, "background task")

    def test_advanced_page_renders_media_type_delete_confirmation(self):
        """The Danger Zone should expose a typed confirmation for media deletion."""
        response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Danger Zone")
        self.assertContains(response, "Delete Selected Type")
        self.assertContains(response, "Type <strong>DELETE</strong> to confirm.")
        self.assertContains(response, "bulk_delete_by_media_type")
        self.assertContains(response, 'x-for="option in options"')
        self.assertContains(response, "bg-[var(--color-panel)]")
        self.assertContains(response, "selectedMediaType = option.value")
        self.assertContains(response, "label: 'Movies'")
        self.assertNotContains(response, "label: 'Episode'")

    def test_delete_media_type_only_deletes_current_users_rows_and_clears_caches(self):
        """Deleting a type removes all of this user's rows and leaves others alone."""
        mine_item = Item.objects.create(
            media_id="mine-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Mine",
        )
        mine_movie = Movie.objects.create(
            item=mine_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        other_item = Item.objects.create(
            media_id="other-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Other",
        )
        other_movie = Movie.objects.create(
            item=other_item,
            user=self.other_user,
            status=Status.PLANNING.value,
        )
        book_item = Item.objects.create(
            media_id="mine-book",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Mine Book",
        )
        Book.objects.create(
            item=book_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        history_key = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        stats_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        cache.set(history_key, {"entries": []}, None)
        cache.set(stats_key, {"total": 1}, None)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MOVIE.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Movie.objects.filter(id=mine_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=other_movie.id).exists())
        self.assertTrue(
            Book.objects.filter(user=self.user, item=book_item).exists(),
        )
        self.assertTrue(
            DeletedMedia.objects.filter(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
                media_id="mine-movie",
            ).exists(),
        )
        self.assertIsNone(cache.get(history_key))
        self.assertIsNone(cache.get(stats_key))

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Permanently deleted 1 Movie item", str(messages[0]))

    def test_delete_media_type_rejects_episode_and_unknown_types(self):
        """Derived Episodes and arbitrary values cannot reach apps.get_model."""
        for media_type in (MediaTypes.EPISODE.value, "not-a-real-type"):
            response = self.client.post(
                reverse("bulk_delete_by_media_type"),
                {"media_type": media_type},
            )

            self.assertRedirects(response, reverse("advanced"))
            messages = list(get_messages(response.wsgi_request))
            self.assertIn("Unknown media type", str(messages[-1]))

    def test_delete_anime_respects_grouped_library_rows(self):
        """Anime deletion includes grouped TV rows but TV deletion does not."""
        grouped_anime_item = Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime",
        )
        grouped_anime = TV.objects.create(
            item=grouped_anime_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        regular_tv_item = Item.objects.create(
            media_id="regular-tv",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Regular TV",
        )
        regular_tv = TV.objects.create(
            item=regular_tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.TV.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(TV.objects.filter(id=regular_tv.id).exists())
        self.assertTrue(TV.objects.filter(id=grouped_anime.id).exists())

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.ANIME.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(TV.objects.filter(id=grouped_anime.id).exists())

    def test_clear_history_cache_only_clears_current_user(self):
        """Clearing history cache must not touch another user's cached days."""
        mine = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        mine_index = f"{HISTORY_INDEX_PREFIX}_{self.user.id}_repeats"
        theirs = f"{HISTORY_DAY_PREFIX}_{self.other_user.id}_repeats_20260805"
        cache.set(mine, {"entries": ["eden"]}, None)
        cache.set(mine_index, {"days": ["20260805"]}, None)
        cache.set(theirs, {"entries": ["unaffected"]}, None)

        response = self.client.post(reverse("clear_history_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get(mine))
        self.assertIsNone(cache.get(mine_index))
        self.assertIsNotNone(cache.get(theirs))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("history cache entr", str(messages[0]))

    def test_clear_statistics_cache_clears_page_and_day_keys_for_current_user(self):
        """Clearing statistics cache must clear both the page and day payloads."""
        page_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        day_key = f"{STATISTICS_DAY_PREFIX}:{self.user.id}:2026-08-05"
        other_page_key = f"{STATISTICS_CACHE_PREFIX}_{self.other_user.id}_all_time"
        cache.set(page_key, {"total": 1}, None)
        cache.set(day_key, {"total": 1}, None)
        cache.set(other_page_key, {"total": 1}, None)

        response = self.client.post(reverse("clear_statistics_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get(page_key))
        self.assertIsNone(cache.get(day_key))
        self.assertIsNotNone(cache.get(other_page_key))

    def test_clear_discover_cache_deletes_rows_profile_and_tab_cache(self):
        """Clearing discover cache must clear DB rows, profile, and warm-tab keys."""
        DiscoverRowCache.objects.create(
            user=self.user,
            media_type="all",
            row_key="trending",
            payload={"items": []},
            expires_at=timezone.now(),
        )
        DiscoverTasteProfile.objects.create(
            user=self.user,
            media_type="all",
            expires_at=timezone.now(),
        )
        other_row = DiscoverRowCache.objects.create(
            user=self.other_user,
            media_type="all",
            row_key="trending",
            payload={"items": []},
            expires_at=timezone.now(),
        )
        tab_key = f"{DISCOVER_TAB_PREFIX}_{self.user.id}_all_False"
        cache.set(tab_key, {"rows": []}, None)

        response = self.client.post(reverse("clear_discover_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(DiscoverRowCache.objects.filter(user=self.user).exists())
        self.assertFalse(
            DiscoverTasteProfile.objects.filter(user=self.user).exists(),
        )
        self.assertIsNone(cache.get(tab_key))
        # Another user's row must survive.
        self.assertTrue(DiscoverRowCache.objects.filter(id=other_row.id).exists())

    def test_clear_all_caches_clears_search_and_current_users_own_caches(self):
        """Clear All must sweep search plus this user's history/stats/discover."""
        cache.set("search_tmdb_movie_batman_1", {"results": []}, None)
        history_key = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        stats_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        cache.set(history_key, {"entries": []}, None)
        cache.set(stats_key, {"total": 1}, None)
        DiscoverTasteProfile.objects.create(
            user=self.user,
            media_type="all",
            expires_at=timezone.now(),
        )

        response = self.client.post(reverse("clear_all_caches"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get("search_tmdb_movie_batman_1"))
        self.assertIsNone(cache.get(history_key))
        self.assertIsNone(cache.get(stats_key))
        self.assertFalse(
            DiscoverTasteProfile.objects.filter(user=self.user).exists(),
        )

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("search, history, statistics, and discover", str(messages[0]))

    def test_delete_media_type_without_metadata_flag_leaves_item_behind(self):
        """The default (unchecked) behavior must not change: Item rows survive."""
        item = Item.objects.create(
            media_id="orphan-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Orphan",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.PLANNING.value)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MOVIE.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertTrue(Item.objects.filter(id=item.id).exists())

    def test_delete_media_type_with_metadata_flag_removes_orphaned_item(self):
        """With delete_metadata=true, an Item with no other tracker is deleted."""
        item = Item.objects.create(
            media_id="orphan-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Orphan",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.PLANNING.value)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MOVIE.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Item.objects.filter(id=item.id).exists())
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Also removed 1 metadata entry", str(messages[0]))

    def test_delete_media_type_with_metadata_flag_keeps_item_tracked_by_other_user(self):
        """An Item still tracked by another user must survive metadata cleanup."""
        item = Item.objects.create(
            media_id="shared-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Shared",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        Movie.objects.create(
            item=item,
            user=self.other_user,
            status=Status.PLANNING.value,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MOVIE.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertTrue(Item.objects.filter(id=item.id).exists())

    def test_delete_tv_with_metadata_flag_cleans_up_seasons_and_episodes(self):
        """Deleting TV with metadata on also removes now-orphaned Season/Episode Items."""
        tv_item = Item.objects.create(
            media_id="tv-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(item=tv_item, user=self.user, status=Status.PLANNING.value)
        season_item = Item.objects.create(
            media_id="tv-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Show",
        )
        season = Season.objects.create(item=season_item, user=self.user, related_tv=tv)
        episode_item = Item.objects.create(
            media_id="tv-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Show",
        )
        Episode.objects.create(item=episode_item, related_season=season)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.TV.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Item.objects.filter(id=tv_item.id).exists())
        self.assertFalse(Item.objects.filter(id=season_item.id).exists())
        self.assertFalse(Item.objects.filter(id=episode_item.id).exists())

    def test_delete_music_with_metadata_flag_cleans_orphaned_artist_and_album(self):
        """Deleting music with metadata on also removes orphaned Artist/Album rows."""
        artist = Artist.objects.create(name="Orphan Artist")
        album = Album.objects.create(title="Orphan Album", artist=artist)
        item = Item.objects.create(
            media_id="orphan-track",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Track",
        )
        Music.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            artist=artist,
            album=album,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Item.objects.filter(id=item.id).exists())
        self.assertFalse(Album.objects.filter(id=album.id).exists())
        self.assertFalse(Artist.objects.filter(id=artist.id).exists())

    def test_delete_music_with_metadata_flag_keeps_artist_with_tracker(self):
        """An Artist/Album still followed via ArtistTracker/AlbumTracker survives."""
        artist = Artist.objects.create(name="Followed Artist")
        album = Album.objects.create(title="Followed Album", artist=artist)
        ArtistTracker.objects.create(user=self.other_user, artist=artist)
        AlbumTracker.objects.create(user=self.other_user, album=album)
        item = Item.objects.create(
            media_id="tracked-track",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Track",
        )
        Music.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            artist=artist,
            album=album,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertTrue(Album.objects.filter(id=album.id).exists())
        self.assertTrue(Artist.objects.filter(id=artist.id).exists())

    def _music_track(self, media_id, user, artist=None, album=None):
        """Create one tracked Music row backed by its own Item."""
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title=f"Track {media_id}",
        )
        return Music.objects.create(
            item=item,
            user=user,
            status=Status.COMPLETED.value,
            artist=artist,
            album=album,
        )

    def test_delete_music_removes_artist_and_album_trackers(self):
        """A music wipe clears the artist/album rows the library page lists."""
        artist = Artist.objects.create(name="Imported Artist")
        album = Album.objects.create(title="Imported Album", artist=artist)
        artist_tracker = ArtistTracker.objects.create(user=self.user, artist=artist)
        album_tracker = AlbumTracker.objects.create(user=self.user, album=album)
        preference = MusicReleasePreference.objects.create(
            user=self.user,
            album=album,
            release_id="00000000-0000-0000-0000-000000000001",
        )
        music = self._music_track("wiped-track", self.user, artist, album)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Music.objects.filter(id=music.id).exists())
        self.assertFalse(ArtistTracker.objects.filter(id=artist_tracker.id).exists())
        self.assertFalse(AlbumTracker.objects.filter(id=album_tracker.id).exists())
        self.assertFalse(
            MusicReleasePreference.objects.filter(id=preference.id).exists(),
        )

        message = str(next(iter(get_messages(response.wsgi_request))))
        self.assertIn("Permanently deleted 3 Music item(s)", message)
        self.assertIn("1 track, 1 album, 1 artist", message)

    def test_delete_music_with_only_trackers_reports_success(self):
        """Trackers with no Music rows left still count as something to delete.

        Regression test for #579: the user's Music rows were already gone, so
        the view counted zero and said "Nothing to delete for that media type."
        while every artist and album stayed on /medialist/music.
        """
        artist = Artist.objects.create(name="Stranded Artist")
        album = Album.objects.create(title="Stranded Album", artist=artist)
        ArtistTracker.objects.create(user=self.user, artist=artist)
        AlbumTracker.objects.create(user=self.user, album=album)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        message = str(next(iter(get_messages(response.wsgi_request))))
        self.assertNotIn("Nothing to delete", message)
        self.assertIn("Permanently deleted 2 Music item(s)", message)
        self.assertFalse(ArtistTracker.objects.filter(user=self.user).exists())
        self.assertFalse(AlbumTracker.objects.filter(user=self.user).exists())

    def test_delete_music_leaves_other_users_trackers_alone(self):
        """Another user following the same artist/album keeps their library."""
        artist = Artist.objects.create(name="Shared Artist")
        album = Album.objects.create(title="Shared Album", artist=artist)
        ArtistTracker.objects.create(user=self.user, artist=artist)
        AlbumTracker.objects.create(user=self.user, album=album)
        other_artist_tracker = ArtistTracker.objects.create(
            user=self.other_user,
            artist=artist,
        )
        other_album_tracker = AlbumTracker.objects.create(
            user=self.other_user,
            album=album,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(ArtistTracker.objects.filter(user=self.user).exists())
        self.assertTrue(
            ArtistTracker.objects.filter(id=other_artist_tracker.id).exists(),
        )
        self.assertTrue(
            AlbumTracker.objects.filter(id=other_album_tracker.id).exists(),
        )

    def test_delete_music_metadata_flag_cleans_catalog_behind_own_tracker(self):
        """The requesting user's own tracker no longer blocks catalog cleanup.

        Previously _delete_orphaned_music_catalog skipped any Artist/Album with
        a tracker, and the deleting user's own tracker was never removed -- so
        the catalog could never be cleaned up for a single-user instance.
        """
        artist = Artist.objects.create(name="Only Mine")
        album = Album.objects.create(title="Only Mine Album", artist=artist)
        ArtistTracker.objects.create(user=self.user, artist=artist)
        AlbumTracker.objects.create(user=self.user, album=album)
        music = self._music_track("own-track", self.user, artist, album)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Item.objects.filter(id=music.item_id).exists())
        self.assertFalse(Album.objects.filter(id=album.id).exists())
        self.assertFalse(Artist.objects.filter(id=artist.id).exists())

    def test_delete_music_metadata_flag_cleans_catalog_with_no_music_rows(self):
        """Orphan cleanup runs even when only tracker rows were deleted.

        The metadata checkbox promises to remove artists/albums with no
        remaining tracked entries. When the user has stranded trackers and no
        Music rows at all, there are no candidate Item ids, and the cleanup
        used to be skipped entirely -- leaving exactly the orphans the option
        said it would remove. That is the #579 library state.
        """
        artist = Artist.objects.create(name="Stranded Only")
        album = Album.objects.create(title="Stranded Only Album", artist=artist)
        ArtistTracker.objects.create(user=self.user, artist=artist)
        AlbumTracker.objects.create(user=self.user, album=album)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MUSIC.value, "delete_metadata": "true"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Album.objects.filter(id=album.id).exists())
        self.assertFalse(Artist.objects.filter(id=artist.id).exists())

    def test_cache_clear_views_require_post(self):
        """GET requests to any clear-cache endpoint must be rejected."""
        for url_name in (
            "clear_history_cache",
            "clear_statistics_cache",
            "clear_discover_cache",
            "clear_all_caches",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 405)


class ExportLogsTests(TestCase):
    """Tests for the sanitized log export on Settings > Advanced."""

    def setUp(self):
        """Create a user and an isolated log directory to read from."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        self.client.login(**self.credentials)

        log_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, log_dir, ignore_errors=True)
        self.log_file = log_dir / "floppy.log"

    @staticmethod
    def export_body(response):
        """Read the streamed download."""
        return b"".join(response.streaming_content).decode()

    def test_export_logs_denies_regular_users(self):
        """Instance-wide diagnostics must not disclose other users' activity."""
        self.user.is_superuser = False
        self.user.save(update_fields=["is_superuser"])

        response = self.client.get(reverse("export_logs"))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(
            self.client.get(reverse("advanced")),
            reverse("export_logs"),
        )

    def test_export_logs_requires_login(self):
        """Anonymous requests must pass through authentication middleware."""
        self.client.logout()
        response = self.client.get(reverse("export_logs"))
        self.assertEqual(response.status_code, 302)

    def test_export_logs_includes_rotated_backups_oldest_first(self):
        """The download should span rotated backups, not just the active file."""
        (self.log_file.with_suffix(".log.2")).write_text("oldest entry\n")
        (self.log_file.with_suffix(".log.1")).write_text("middle entry\n")
        self.log_file.write_text("newest entry\n")

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        body = self.export_body(response)
        self.assertLess(body.index("oldest entry"), body.index("middle entry"))
        self.assertLess(body.index("middle entry"), body.index("newest entry"))

    def test_export_logs_redacts_secrets_across_all_files(self):
        """Redaction must apply to rotated backups too, not just the active file."""
        (self.log_file.with_suffix(".log.1")).write_text(
            "Authorization: Bearer sk-secret-value\n"
        )
        self.log_file.write_text("plain entry\n")

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        self.assertNotIn("sk-secret-value", self.export_body(response))

    def test_export_logs_handles_missing_backups(self):
        """A fresh install with no rotated backups should still download fine."""
        self.log_file.write_text("only entry\n")

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("only entry", self.export_body(response))

    def test_export_logs_appends_supervisor_log_and_crash_tracebacks(self):
        """Process exits and fatal-signal tracebacks belong in the download."""
        self.log_file.write_text("app entry\n")
        (self.log_file.parent / "supervisord.log").write_text(
            "exited: gunicorn (terminated by SIGKILL; not expected)\n"
        )
        (self.log_file.parent / "faulthandler.log").write_text(
            "Fatal Python error: Segmentation fault\n"
        )

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        body = self.export_body(response)
        self.assertIn("===== supervisord.log =====", body)
        self.assertIn("terminated by SIGKILL", body)
        self.assertIn("Segmentation fault", body)
        self.assertLess(body.index("app entry"), body.index("terminated by SIGKILL"))

    def test_export_logs_includes_restart_history(self):
        """Each restart's cause belongs in the download, past floppy.log rotation."""
        self.log_file.write_text("app entry\n")
        (self.log_file.parent / "restart-history.log").write_text(
            "2026-10-14T18:46:10+00:00 Restart: previous run stopped cleanly.\n"
        )

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        body = self.export_body(response)
        self.assertIn("===== restart-history.log =====", body)
        self.assertIn("previous run stopped cleanly", body)

    def test_export_logs_skips_empty_crash_traceback_file(self):
        """faulthandler.log exists from the first start; an empty one is noise."""
        self.log_file.write_text("app entry\n")
        (self.log_file.parent / "faulthandler.log").write_text("")

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("export_logs"))

        self.assertNotIn("faulthandler.log", self.export_body(response))

    def test_advanced_page_shows_how_far_back_logs_go(self):
        """The page should say what period the download covers."""
        self.log_file.write_text("[2026-10-01 03:42:10 +0000] [1] [INFO] hello\n")

        with override_settings(LOG_FILE=str(self.log_file)):
            response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Covers 2026-10-01 03:42:10 onward.")
