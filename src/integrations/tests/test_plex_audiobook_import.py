"""Tests for importing audiobooks kept in a Plex Music library."""

import logging
import tempfile
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from app import image_cache
from app.models import Book, Item, MediaTypes, Music, Sources, Status
from integrations import plex_cover
from integrations.imports.plex import PlexHistoryImporter
from integrations.models import PlexAccount

MINUTE_MS = 60 * 1000
MACHINE_ID = "machine-1"
SECTION_ID = "7"


def setUpModule():
    """Silence importer log noise for this module only."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.CRITICAL)


def tearDownModule():
    """Restore the importer logger level for other modules."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.NOTSET)


def section(title="Audiobooks", agent="com.plexapp.agents.audnexus"):
    """Return a Plex music section as list_sections would report it."""
    return {
        "id": SECTION_ID,
        "title": title,
        "type": "artist",
        "agent": agent,
        "scanner": "Plex Music Scanner",
        "server_name": "Home",
        "machine_identifier": MACHINE_ID,
        "uri": "http://plex.local:32400",
        "access_token": "token",
    }


def history_entry(rating_key="101", parent_key="100", title="Chapter 1"):
    """Return a Plex music history row for one chapter."""
    return {
        "type": "track",
        "ratingKey": rating_key,
        "parentRatingKey": parent_key,
        "grandparentTitle": "Franz Kafka",
        "parentTitle": "Der Prozess",
        "title": title,
        "index": 1,
        "accountID": "4441952",
        "viewedAt": 1735689600,
    }


def album(rating_key="100", genre="Hörbuch"):
    """Return Plex album metadata for an audiobook."""
    return {
        "ratingKey": rating_key,
        "type": "album",
        "title": "Der Prozess",
        "parentTitle": "Franz Kafka",
        "summary": "Josef K. wird eines Morgens verhaftet. " * 12,
        "thumb": f"/library/metadata/{rating_key}/thumb/1",
        "year": "1925",
        "Genre": [{"tag": genre}],
    }


def chapters(count=4, minutes=30, played=0):
    """Return album tracks, the first `played` of them fully listened to."""
    tracks = []
    for index in range(1, count + 1):
        track = {
            "ratingKey": str(100 + index),
            "title": f"Chapter {index}",
            "index": index,
            "duration": minutes * MINUTE_MS,
        }
        if index <= played:
            track["viewCount"] = 1
            track["lastViewedAt"] = 1735689600
        tracks.append(track)
    return tracks


def music_album():
    """Return a normal music album that Plex matched to MusicBrainz."""
    return {
        "ratingKey": "200",
        "type": "album",
        "title": "Kind of Blue",
        "parentTitle": "Miles Davis",
        "Genre": [{"tag": "Jazz"}],
        "Guid": [{"id": "mbid://album/abc"}],
    }


def songs(count=5, minutes=6):
    """Return normal music tracks carrying MusicBrainz GUIDs."""
    return [
        {
            "ratingKey": str(200 + index),
            "title": f"Song {index}",
            "index": index,
            "duration": minutes * MINUTE_MS,
            "Guid": [{"id": f"mbid://recording/{index}"}],
        }
        for index in range(1, count + 1)
    ]


class PlexAudiobookImportTestCase(TestCase):
    """Shared harness driving PlexHistoryImporter over a music library."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="listener")
        self.user.plex_usernames = "listener"
        self.user.book_enabled = True
        self.user.music_enabled = True
        self.user.save()
        self.account = PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
            plex_username="listener",
            plex_account_id="4441952",
            sections=[section()],
        )

    def run_import(
        self,
        *,
        entries,
        album_metadata,
        album_tracks,
        library_section=None,
        content_kind=None,
    ):
        """Run a full import over one music section with mocked Plex calls."""
        library_section = library_section or section()
        self.account.sections = [library_section]
        if content_kind:
            self.account.set_content_kind(MACHINE_ID, SECTION_ID, content_kind)
        self.account.save()

        importer = PlexHistoryImporter(
            user=self.user,
            account=self.account,
            mode="new",
            library=f"{MACHINE_ID}::{SECTION_ID}",
        )

        with (
            patch(
                "integrations.imports.plex.plex_api.list_resources",
                return_value=[
                    {
                        "name": "Home",
                        "machine_identifier": MACHINE_ID,
                        "owned": True,
                        "access_token": "token",
                        "connections": [{"uri": "http://plex.local:32400"}],
                    },
                ],
            ),
            patch(
                "integrations.imports.plex.plex_api.fetch_history",
                side_effect=[(entries, len(entries)), ([], len(entries))],
            ),
            patch(
                "integrations.imports.plex.plex_api.fetch_metadata",
                return_value=album_metadata,
            ),
            patch(
                "integrations.imports.plex.plex_api.fetch_children",
                return_value=album_tracks,
            ),
            patch(
                "integrations.imports.plex.plex_api.fetch_section_all_items",
                return_value=([], 0),
            ),
            patch("integrations.imports.plex.plex_api.list_users", return_value=[]),
        ):
            return importer.import_data()


class TestForcedAudiobookLibrary(PlexAudiobookImportTestCase):
    """A library the user flagged as Audiobooks imports as books."""

    def test_flagged_library_creates_a_book(self):
        self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=2),
            # Deliberately a library nothing would auto-detect.
            library_section=section(title="Music", agent="tv.plex.agents.music"),
            content_kind="audiobook",
        )

        item = Item.objects.get(
            source=Sources.PLEX.value,
            media_type=MediaTypes.BOOK.value,
        )
        self.assertEqual(item.title, "Der Prozess")
        self.assertEqual(item.authors, ["Franz Kafka"])
        self.assertEqual(item.format, "audiobook")
        self.assertEqual(item.runtime_minutes, 120)

        book = Book.objects.get(user=self.user, item=item)
        self.assertEqual(book.progress, 60)
        self.assertEqual(book.status, Status.IN_PROGRESS.value)
        self.assertEqual(book.entry_source, "plex")
        self.assertFalse(Music.objects.filter(user=self.user).exists())

    def test_finished_book_completes_at_full_runtime(self):
        self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=4),
            content_kind="audiobook",
        )

        book = Book.objects.get(user=self.user)
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.progress, 120)
        self.assertIsNotNone(book.end_date)

    def test_chapters_of_one_album_produce_one_book(self):
        entries = [
            history_entry(rating_key=str(100 + index), title=f"Chapter {index}")
            for index in range(1, 5)
        ]
        counts, _ = self.run_import(
            entries=entries,
            album_metadata=album(),
            album_tracks=chapters(played=4),
            content_kind="audiobook",
        )

        self.assertEqual(Book.objects.filter(user=self.user).count(), 1)
        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)

    def test_reimport_is_idempotent_and_advances_progress(self):
        self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=1),
            content_kind="audiobook",
        )
        first = Book.objects.get(user=self.user)
        self.assertEqual(first.progress, 30)

        self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=3),
            content_kind="audiobook",
        )

        self.assertEqual(Item.objects.filter(source=Sources.PLEX.value).count(), 1)
        self.assertEqual(Book.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Book.objects.get(user=self.user).progress, 90)

    def test_book_tracking_disabled_warns_instead_of_silently_skipping(self):
        self.user.book_enabled = False
        self.user.save()

        _, warnings = self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=2),
            content_kind="audiobook",
        )

        self.assertFalse(Book.objects.filter(user=self.user).exists())
        self.assertIn("book tracking is disabled", warnings)


class TestAutoDetectedAudiobooks(PlexAudiobookImportTestCase):
    """Auto mode decides per album, and says so in the summary."""

    def test_audiobook_album_is_detected(self):
        _, warnings = self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=2),
        )

        self.assertTrue(
            Book.objects.filter(user=self.user, item__source=Sources.PLEX.value).exists(),
        )
        self.assertIn("Detected 1 audiobook(s)", warnings)

    def test_music_album_still_imports_as_music(self):
        entry = history_entry(rating_key="201", parent_key="200", title="Song 1")
        entry["grandparentTitle"] = "Miles Davis"
        entry["parentTitle"] = "Kind of Blue"

        self.run_import(
            entries=[entry],
            album_metadata=music_album(),
            album_tracks=songs(),
            library_section=section(title="Music", agent="tv.plex.agents.music"),
        )

        self.assertFalse(
            Item.objects.filter(
                source=Sources.PLEX.value,
                media_type=MediaTypes.BOOK.value,
            ).exists(),
        )

    def test_music_content_kind_never_creates_books(self):
        """An explicit Music choice overrides even an obvious audiobook."""
        self.run_import(
            entries=[history_entry()],
            album_metadata=album(),
            album_tracks=chapters(played=2),
            content_kind="music",
        )

        self.assertFalse(
            Item.objects.filter(
                source=Sources.PLEX.value,
                media_type=MediaTypes.BOOK.value,
            ).exists(),
        )


class TestAlbumCacheScoping(PlexAudiobookImportTestCase):
    """Album caches must be scoped to the server the rating key came from."""

    def _importer(self):
        return PlexHistoryImporter(
            user=self.user,
            account=self.account,
            mode="new",
            library="all",
        )

    def test_same_rating_key_on_two_servers_is_classified_separately(self):
        """Plex rating keys are only unique within a server.

        An "all libraries" import spanning two servers would otherwise let the
        second album inherit the first one's verdict, misrouting music or
        dropping a book.
        """
        importer = self._importer()
        importer._current_section_content_kind = "audiobook"

        importer._current_section_machine_id = "server-a"
        self.assertTrue(importer._should_import_as_audiobook(history_entry()))

        # Same album rating key, different server, explicitly kept as music.
        importer._current_section_machine_id = "server-b"
        importer._current_section_content_kind = "music"
        self.assertFalse(importer._should_import_as_audiobook(history_entry()))

        self.assertEqual(
            set(importer._audiobook_album_verdicts),
            {("server-a", "100")},
        )

    def test_same_album_upserts_once_per_server(self):
        """The already-seen set is server-scoped for the same reason."""
        importer = self._importer()
        importer._current_section_machine_id = "server-a"
        self.assertEqual(importer._album_cache_key("100"), ("server-a", "100"))

        importer._current_section_machine_id = "server-b"
        self.assertEqual(importer._album_cache_key("100"), ("server-b", "100"))

    def test_rating_key_paths_are_normalized(self):
        """A `parentKey` arrives as a path; the numeric key identifies it."""
        importer = self._importer()
        importer._current_section_machine_id = "server-a"
        self.assertEqual(
            importer._album_cache_key("/library/metadata/100"),
            ("server-a", "100"),
        )


class PlexCoverProxyUrlCeleryTests(TestCase):
    """build_cover_proxy_url must work from a Celery worker (#1199).

    The scheduled/manual Plex import runs inside a Celery worker, whose
    ROOT_URLCONF is deliberately empty since it never serves HTTP. reverse()
    must not depend on that setting the way the Plex webhook view (a real
    request) implicitly does.
    """

    @override_settings(ROOT_URLCONF="config.celery_urls")
    def test_builds_url_under_the_empty_celery_urlconf(self):
        url = plex_cover.build_cover_proxy_url(1, MACHINE_ID, "/library/metadata/1")
        self.assertTrue(url.startswith(plex_cover.PROXY_PATH_PREFIX))

    @override_settings(ROOT_URLCONF="config.celery_urls", FORCE_SCRIPT_NAME="/floppy")
    def test_applies_base_url_subpath_when_no_request_set_it(self):
        url = plex_cover.build_cover_proxy_url(1, MACHINE_ID, "/library/metadata/1")
        self.assertTrue(url.startswith("/floppy" + plex_cover.PROXY_PATH_PREFIX))


class PlexCoverStoredCopyTests(TestCase):
    """Plex covers keep a last good copy like Audiobookshelf ones (#1307)."""

    def setUp(self):
        data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(data_dir.cleanup)
        settings_override = override_settings(FLOPPY_DATA_DIR=data_dir.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        user = get_user_model().objects.create_user(username="plex-cover")
        self.account = PlexAccount.objects.create(
            user=user,
            plex_token="token",
            plex_username="listener",
            plex_account_id="1",
            sections=[section()],
        )
        self.url = plex_cover.build_cover_proxy_url(
            self.account.id,
            MACHINE_ID,
            "/library/metadata/1/thumb/1",
        )
        connection = patch(
            "integrations.views.plex_api.connection_for_machine",
            return_value=("http://plex.local:32400", "server-token"),
        )
        connection.start()
        self.addCleanup(connection.stop)

    @patch("integrations.views.requests.get")
    def test_stored_cover_is_served_while_plex_is_down(self, mock_get):
        upstream = Mock(status_code=200, headers={"Content-Type": "image/jpeg"})
        upstream.iter_content = lambda chunk_size: iter([b"plex-cover"])
        mock_get.return_value = upstream
        self.assertEqual(self.client.get(self.url).content, b"plex-cover")
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")

        with patch.object(image_cache, "STORED_COVER_FRESH_SECONDS", 0):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"plex-cover")
        self.assertEqual(mock_get.call_count, 2)

    @patch("integrations.views.requests.get")
    def test_missing_cover_is_still_a_404(self, mock_get):
        mock_get.side_effect = requests.ReadTimeout("Read timed out.")

        self.assertEqual(self.client.get(self.url).status_code, 404)
