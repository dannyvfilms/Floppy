"""Tests for Audiobookshelf importer."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, call, patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    Book,
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)
from integrations import audiobookshelf_cover
from integrations.imports import helpers
from integrations.imports.audiobookshelf import (
    BOOK_REPAIR_COOLDOWN,
    TITLE_MATCH_THRESHOLD,
    AudiobookshelfAuthError,
    AudiobookshelfClient,
    AudiobookshelfClientError,
    AudiobookshelfImporter,
)
from integrations.imports.helpers import MediaImportError
from integrations.models import AudiobookshelfAccount


def cover_proxy_target(image_url):
    """Resolve a Floppy ABS cover-proxy URL back to (account_id, library_item_id)."""
    token = image_url.rsplit("/", 1)[-1]
    return audiobookshelf_cover.resolve_cover_proxy_token(token)


def podcast_progress(**overrides):
    """Return an ABS podcast episode progress entry."""
    return {
        "libraryItemId": "podcast-item",
        "episodeId": "ep-1",
        "mediaItemId": "ep-1",
        "mediaItemType": "podcastEpisode",
        "currentTime": 1200,
        "duration": 3000,
        "progress": 0.4,
        "isFinished": False,
        "lastUpdate": 2000,
        "startedAt": 1_700_000_000_000,
        "finishedAt": None,
        **overrides,
    }


def podcast_library_item(**overrides):
    """Return an expanded ABS podcast library item payload."""
    return {
        "id": "podcast-item",
        "mediaType": "podcast",
        "coverPath": "/metadata/items/podcast-item/cover.jpg",
        "media": {
            "id": "pod-1",
            "metadata": {
                "title": "Test Show",
                "author": "Test Network",
                "description": "A show.",
                "language": "en",
                "genres": ["Technology"],
                "feedUrl": "https://feed.example/rss.xml",
                "imageUrl": "https://feed.example/cover.jpg",
            },
            "episodes": [
                {
                    "id": "ep-1",
                    "title": "Episode 14",
                    "guid": "guid-1",
                    "enclosure": {
                        "url": "https://cdn.example/ep14.mp3",
                        "type": "audio/mpeg",
                    },
                    "season": "2",
                    "episode": "14",
                    "episodeType": "full",
                    "publishedAt": 1_699_516_800_000,
                    "duration": 3000.4,
                },
            ],
        },
        **overrides,
    }


class AudiobookshelfImporterTests(TestCase):
    """Validate ABS import mapping and filtering."""

    def setUp(self):
        """Create test user and connected ABS account."""
        self.user = get_user_model().objects.create_user(
            username="abs-user",
            password="pass",
        )
        AudiobookshelfAccount.objects.create(
            user=self.user,
            base_url="https://abs.example.com",
            api_token=helpers.encrypt("token"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_imports_audiobook_progress_as_book(self, mock_me, mock_item):
        """Import ABS audiobook progress into Book rows."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-1",
                    "currentTime": 3600,
                    "duration": 7200,
                    "progress": 0.5,
                    "isFinished": False,
                    "lastUpdate": 1000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 7200,
                "metadata": {
                    "title": "The Hobbit",
                    "authors": [{"name": "J.R.R. Tolkien"}],
                },
            },
            "coverPath": "https://img.example/hobbit.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")

        media = Book.objects.get(user=self.user)
        self.assertEqual(media.status, Status.IN_PROGRESS.value)
        self.assertEqual(media.progress, 60)
        self.assertEqual(media.entry_source, "audiobookshelf")
        self.assertEqual(media.item.source, Sources.AUDIOBOOKSHELF.value)
        self.assertEqual(media.item.media_type, MediaTypes.BOOK.value)
        self.assertEqual(media.item.runtime_minutes, 120)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_imports_podcast_episode_progress(self, mock_me, mock_item):
        """Import ABS podcast episode progress into Podcast rows."""
        mock_me.return_value = {"mediaProgress": [podcast_progress()]}
        mock_item.return_value = podcast_library_item()

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.PODCAST.value), 1)
        self.assertEqual(warnings, "")
        mock_item.assert_called_once_with("podcast-item", expanded=True)

        show = PodcastShow.objects.get()
        self.assertEqual(show.source, Sources.AUDIOBOOKSHELF.value)
        self.assertEqual(show.title, "Test Show")
        self.assertEqual(show.rss_feed_url, "https://feed.example/rss.xml")

        episode = PodcastEpisode.objects.get()
        self.assertEqual(episode.episode_uuid, "guid-1")
        self.assertEqual(episode.duration, 3000)
        self.assertEqual(episode.season_number, 2)
        self.assertEqual(episode.episode_number, 14)

        media = Podcast.objects.get(user=self.user)
        self.assertEqual(media.status, Status.IN_PROGRESS.value)
        self.assertEqual(media.played_up_to_seconds, 1200)
        self.assertEqual(media.entry_source, "audiobookshelf")
        self.assertEqual(media.progress, 20)
        self.assertEqual(media.last_seen_status, 2)
        self.assertIsNone(media.end_date)
        self.assertEqual(media.item.media_type, MediaTypes.PODCAST.value)
        self.assertEqual(media.item.media_id, "guid-1")
        self.assertTrue(
            PodcastShowTracker.objects.filter(user=self.user, show=show).exists(),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_imports_finished_podcast_episode_as_completed(self, mock_me, mock_item):
        """Map a finished ABS episode onto a completed Podcast row."""
        finished_at_ms = 1_700_003_600_000
        mock_me.return_value = {
            "mediaProgress": [
                podcast_progress(
                    currentTime=3000,
                    progress=1,
                    isFinished=True,
                    finishedAt=finished_at_ms,
                ),
            ],
        }
        mock_item.return_value = podcast_library_item()

        importer = AudiobookshelfImporter(self.user)
        counts, _ = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.PODCAST.value), 1)
        media = Podcast.objects.get(user=self.user)
        self.assertEqual(media.status, Status.COMPLETED.value)
        self.assertEqual(media.last_seen_status, 3)
        self.assertEqual(
            media.end_date,
            datetime.fromtimestamp(finished_at_ms / 1000, tz=UTC),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_skips_podcast_episode_without_listening_activity(self, mock_me, mock_item):
        """Ignore ABS rows that were touched but never played."""
        mock_me.return_value = {"mediaProgress": [podcast_progress(currentTime=0)]}
        mock_item.return_value = podcast_library_item()

        importer = AudiobookshelfImporter(self.user)
        counts, _ = importer.import_data()

        self.assertEqual(counts, {})
        self.assertFalse(Podcast.objects.exists())

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_podcast_episode_uuid_falls_back_to_enclosure_then_id(
        self,
        mock_me,
        mock_item,
    ):
        """Fall back to the enclosure URL, then the ABS episode id."""
        mock_me.return_value = {"mediaProgress": [podcast_progress()]}
        library_item = podcast_library_item()
        library_item["media"]["episodes"][0].pop("guid")
        mock_item.return_value = library_item

        AudiobookshelfImporter(self.user).import_data()
        self.assertEqual(
            PodcastEpisode.objects.get().episode_uuid,
            "https://cdn.example/ep14.mp3",
        )

        PodcastEpisode.objects.all().delete()
        PodcastShow.objects.all().delete()
        library_item["media"]["episodes"][0].pop("enclosure")
        mock_me.return_value = {"mediaProgress": [podcast_progress(lastUpdate=9000)]}

        AudiobookshelfImporter(self.user).import_data()
        self.assertEqual(PodcastEpisode.objects.get().episode_uuid, "abs_ep-1")

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_cursor_covers_podcast_entries(self, mock_me, mock_item):
        """Advance last_sync_ms past podcast progress so it is not replayed."""
        mock_me.return_value = {"mediaProgress": [podcast_progress(lastUpdate=5000)]}
        mock_item.return_value = podcast_library_item()

        AudiobookshelfImporter(self.user).import_data()

        account = AudiobookshelfAccount.objects.get(user=self.user)
        self.assertEqual(account.last_sync_ms, 5000)

        mock_item.reset_mock()
        counts, _ = AudiobookshelfImporter(self.user).import_data()
        self.assertEqual(counts, {})
        mock_item.assert_not_called()

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_updates_existing_in_progress_podcast_row(self, mock_me, mock_item):
        """Update the open row instead of creating a second play."""
        mock_me.return_value = {"mediaProgress": [podcast_progress()]}
        mock_item.return_value = podcast_library_item()
        AudiobookshelfImporter(self.user).import_data()

        mock_me.return_value = {
            "mediaProgress": [podcast_progress(currentTime=1800, lastUpdate=9000)],
        }
        AudiobookshelfImporter(self.user).import_data()

        media = Podcast.objects.get(user=self.user)
        self.assertEqual(media.played_up_to_seconds, 1800)
        self.assertEqual(media.progress, 30)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_reuses_existing_show_with_same_feed_url(self, mock_me, mock_item):
        """Attach to a show another integration already created for the feed."""
        existing = PodcastShow.objects.create(
            podcast_uuid="gp_existing",
            source=Sources.GPODDER.value,
            title="Test Show",
            rss_feed_url="https://feed.example/rss.xml",
        )
        mock_me.return_value = {"mediaProgress": [podcast_progress()]}
        mock_item.return_value = podcast_library_item()

        AudiobookshelfImporter(self.user).import_data()

        self.assertEqual(PodcastShow.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.source, Sources.GPODDER.value)
        self.assertEqual(
            Podcast.objects.get(user=self.user).item.source,
            Sources.GPODDER.value,
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_warns_when_episode_missing_from_library_item(self, mock_me, mock_item):
        """Warn instead of failing when ABS omits the episode."""
        mock_me.return_value = {"mediaProgress": [podcast_progress(episodeId="ep-404")]}
        mock_item.return_value = podcast_library_item()

        counts, warnings = AudiobookshelfImporter(self.user).import_data()

        self.assertEqual(counts, {})
        self.assertIn("ep-404", warnings)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_imports_mixed_book_and_podcast_payload(self, mock_me, mock_item):
        """Handle a payload containing both media types."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-1",
                    "currentTime": 3600,
                    "duration": 7200,
                    "isFinished": False,
                    "lastUpdate": 1000,
                },
                podcast_progress(),
            ],
        }

        def library_item(library_item_id, *, expanded=False):
            if library_item_id == "podcast-item":
                return podcast_library_item()
            return {
                "media": {
                    "duration": 7200,
                    "metadata": {"title": "The Hobbit"},
                },
            }

        mock_item.side_effect = library_item

        counts, _ = AudiobookshelfImporter(self.user).import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(counts.get(MediaTypes.PODCAST.value), 1)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_parses_millisecond_timestamps_for_started_and_finished(
        self,
        mock_me,
        mock_item,
    ):
        """Use UTC-aware datetimes when ABS returns millisecond timestamps."""
        started_at_ms = 1_700_000_000_000
        finished_at_ms = 1_700_003_600_000
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-2",
                    "currentTime": 7200,
                    "duration": 7200,
                    "progress": 1,
                    "isFinished": True,
                    "startedAt": started_at_ms,
                    "finishedAt": finished_at_ms,
                    "lastUpdate": finished_at_ms,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 7200,
                "metadata": {
                    "title": "Dune",
                    "authors": [{"name": "Frank Herbert"}],
                },
            },
            "coverPath": "https://img.example/dune.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")

        media = Book.objects.get(user=self.user)
        self.assertEqual(media.status, Status.COMPLETED.value)
        self.assertEqual(
            media.start_date,
            datetime.fromtimestamp(started_at_ms / 1000, tz=UTC),
        )
        self.assertEqual(
            media.end_date,
            datetime.fromtimestamp(finished_at_ms / 1000, tz=UTC),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_marks_completed_when_finished_at_exists_but_progress_is_zero(
        self,
        mock_me,
        mock_item,
    ):
        """A finished timestamp should map to completed even with reset progress."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-finished-ts",
                    "currentTime": 0,
                    "duration": 7200,
                    "progress": 0,
                    "isFinished": False,
                    "finishedAt": 1_700_003_600_000,
                    "lastUpdate": 1_700_003_600_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 7200,
                "metadata": {
                    "title": "Finished via Timestamp",
                    "authors": [{"name": "Example Author"}],
                },
            },
            "coverPath": "https://img.example/finished-ts.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user)
        self.assertEqual(media.status, Status.COMPLETED.value)
        self.assertEqual(media.progress, media.item.runtime_minutes)
        self.assertIsNotNone(media.end_date)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_keeps_planning_when_not_started_and_not_finished(
        self,
        mock_me,
        mock_item,
    ):
        """A zero-progress row without completion markers should remain planning."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-not-started",
                    "currentTime": 0,
                    "duration": 5400,
                    "progress": 0,
                    "isFinished": False,
                    "lastUpdate": 1_700_100_000_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 5400,
                "metadata": {
                    "title": "Not Started",
                    "authors": [{"name": "Example Author"}],
                },
            },
            "coverPath": "https://img.example/not-started.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user)
        self.assertEqual(media.status, Status.PLANNING.value)
        self.assertEqual(media.progress, 0)
        self.assertIsNone(media.end_date)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_respects_last_sync_cursor_and_updates_last_sync_ms(
        self,
        mock_me,
        mock_item,
    ):
        """Changed rows import first, and unchanged missing rows are repaired."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 1_500
        account.save(update_fields=["last_sync_ms", "updated_at"])

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "old-item",
                    "currentTime": 120,
                    "lastUpdate": 1_000,
                },
                {
                    "libraryItemId": "new-item",
                    "currentTime": 1_800,
                    "duration": 3_600,
                    "lastUpdate": 2_000,
                },
            ],
        }
        mock_item.side_effect = lambda library_item_id: {
            "media": {
                "duration": 3_600,
                "metadata": {
                    "title": "New Book"
                    if library_item_id == "new-item"
                    else "Old Book",
                    "authors": [{"name": "Brandon Sanderson"}],
                },
            },
            "coverPath": f"https://img.example/{library_item_id}.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 2)
        self.assertEqual(warnings, "")
        self.assertEqual(Book.objects.filter(user=self.user).count(), 2)
        self.assertCountEqual(
            Book.objects.filter(user=self.user).values_list("item__title", flat=True),
            ["New Book", "Old Book"],
        )
        self.user.audiobookshelf_account.refresh_from_db()
        self.assertEqual(self.user.audiobookshelf_account.last_sync_ms, 2_000)
        self.assertEqual(
            mock_item.call_args_list,
            [call("new-item"), call("old-item")],
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_repairs_unchanged_completed_item_missing_metadata_after_cursor_advance(
        self,
        mock_me,
        mock_item,
    ):
        """Repair unchanged completed ABS books when local metadata is sparse."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "completed-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="The Emperor's Soul",
            image=settings.IMG_NONE,
            authors=["Brandon Sanderson"],
            format="audiobook",
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.COMPLETED.value,
            progress=211,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "completed-item",
                    "currentTime": 12_660,
                    "duration": 12_660,
                    "progress": 1,
                    "isFinished": True,
                    "startedAt": 1_739_145_600_000,
                    "finishedAt": 1_739_923_200_000,
                    "lastUpdate": 1_500,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 12_660,
                "metadata": {
                    "title": "The Emperor's Soul",
                    "authors": [{"name": "Brandon Sanderson"}],
                    "isbn": "978-1-61696-058-2",
                },
            },
            "coverPath": "",
        }
        with (
            patch(
                "integrations.imports.audiobookshelf.services.search",
                return_value={
                    "results": [
                        {
                            "media_id": "314",
                            "source": Sources.HARDCOVER.value,
                            "title": "The Emperor's Soul",
                        },
                    ],
                },
            ) as mock_search,
            patch(
                "integrations.imports.audiobookshelf.services.get_media_metadata",
                return_value={
                    "media_id": "314",
                    "source": Sources.HARDCOVER.value,
                    "media_type": MediaTypes.BOOK.value,
                    "title": "The Emperor's Soul",
                    "image": "https://covers.example/emperor.jpg",
                    "genres": ["Fantasy"],
                    "details": {
                        "author": "Brandon Sanderson",
                        "publisher": "Subterranean Press",
                        "isbn": ["9781616960582"],
                        "publish_date": "2012-10-11",
                    },
                },
            ) as mock_get_media_metadata,
        ):
            importer = AudiobookshelfImporter(self.user)
            importer.enable_provider_enrichment = True
            counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")

        item.refresh_from_db()
        self.assertEqual(item.image, "https://covers.example/emperor.jpg")
        self.assertEqual(item.isbn, ["9781616960582"])
        self.assertEqual(item.publishers, "Subterranean Press")
        self.assertEqual(item.genres, ["Fantasy"])
        self.assertEqual(
            item.release_datetime,
            datetime(2012, 10, 11, tzinfo=UTC),
        )
        self.assertEqual(item.original_title, "The Emperor's Soul")
        self.assertEqual(item.localized_title, "The Emperor's Soul")
        self.assertIsNotNone(item.metadata_fetched_at)
        mock_item.assert_called_once_with("completed-item")
        mock_search.assert_called_once()
        mock_get_media_metadata.assert_called_once()

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_collects_warning_when_library_item_lookup_fails(self, mock_me, mock_item):
        """A failed item metadata fetch should not abort the whole import."""
        mock_me.return_value = {
            "mediaProgress": [
                {"libraryItemId": "broken-item", "lastUpdate": 3_000},
            ],
        }
        mock_item.side_effect = AudiobookshelfClientError("boom")

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts, {})
        self.assertIn("broken-item", warnings)
        self.assertFalse(Book.objects.filter(user=self.user).exists())

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_retries_unchanged_item_after_prior_lookup_failure(
        self,
        mock_me,
        mock_item,
    ):
        """A prior lookup failure should be retried on the next unchanged import."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "broken-item",
                    "currentTime": 1_200,
                    "duration": 3_600,
                    "lastUpdate": 3_000,
                },
            ],
        }
        mock_item.side_effect = [
            AudiobookshelfClientError("boom"),
            {
                "media": {
                    "duration": 3_600,
                    "metadata": {
                        "title": "Warbreaker",
                        "authors": [{"name": "Brandon Sanderson"}],
                        "isbn": "978-0-7653-2030-8",
                        "publisher": "Tor",
                        "genres": ["Fantasy"],
                    },
                },
                "coverPath": "https://img.example/warbreaker.jpg",
            },
        ]

        importer = AudiobookshelfImporter(self.user)
        first_counts, first_warnings = importer.import_data()

        self.assertEqual(first_counts, {})
        self.assertIn("broken-item", first_warnings)
        self.user.audiobookshelf_account.refresh_from_db()
        self.assertEqual(self.user.audiobookshelf_account.last_sync_ms, 3_000)
        self.assertFalse(
            Item.objects.filter(
                source=Sources.AUDIOBOOKSHELF.value,
                media_type=MediaTypes.BOOK.value,
            ).exists(),
        )

        importer = AudiobookshelfImporter(self.user)
        second_counts, second_warnings = importer.import_data()

        self.assertEqual(second_counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(second_warnings, "")
        self.assertEqual(mock_item.call_count, 2)

        item = Book.objects.get(user=self.user).item
        self.assertEqual(item.title, "Warbreaker")
        self.assertEqual(item.image, "https://img.example/warbreaker.jpg")
        self.assertEqual(item.isbn, ["9780765320308"])
        self.assertEqual(item.publishers, "Tor")
        self.assertEqual(item.genres, ["Fantasy"])
        self.assertIsNotNone(item.metadata_fetched_at)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_transient_network_error_skips_item_without_aborting_import(
        self,
        mock_me,
        mock_item,
    ):
        """A timeout on one item's fetch should not fail the whole import (#1047)."""
        mock_me.return_value = {
            "mediaProgress": [
                {"libraryItemId": "flaky-item", "lastUpdate": 3_000},
                {
                    "libraryItemId": "healthy-item",
                    "currentTime": 600,
                    "duration": 1_200,
                    "lastUpdate": 4_000,
                },
            ],
        }

        def fetch(library_item_id, **kwargs):
            if library_item_id == "flaky-item":
                raise requests.exceptions.ReadTimeout("handshake timed out")
            return {
                "media": {
                    "duration": 1_200,
                    "metadata": {
                        "title": "Healthy Book",
                        "authors": [{"name": "Some Author"}],
                    },
                },
                "coverPath": "https://img.example/healthy.jpg",
            }

        mock_item.side_effect = fetch

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertIn("flaky-item", warnings)
        healthy_media_id = importer._stable_media_id(
            "https://abs.example.com",
            "healthy-item",
        )
        self.assertTrue(
            Book.objects.filter(
                user=self.user,
                item__media_id=healthy_media_id,
            ).exists(),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_falls_back_to_item_title_and_plain_string_authors(
        self,
        mock_me,
        mock_item,
    ):
        """Importer should support string authors and top-level title fallback."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-3",
                    "currentTime": 300,
                    "lastUpdate": 5_000,
                },
            ],
        }
        mock_item.return_value = {
            "title": "Fallback Title",
            "media": {
                "metadata": {
                    "authors": [
                        "Author One",
                        {"name": "Author Two"},
                        {"name": ""},
                    ],
                },
            },
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")

        item = Book.objects.get(user=self.user).item
        self.assertEqual(item.title, "Fallback Title")
        self.assertEqual(item.authors, ["Author One", "Author Two"])

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_normalizes_relative_abs_cover_paths(self, mock_me, mock_item):
        """Relative Audiobookshelf cover paths should be converted to absolute URLs."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-4",
                    "currentTime": 1_200,
                    "lastUpdate": 6_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 3_600,
                "metadata": {
                    "title": "Words of Radiance",
                    "authors": [{"name": "Brandon Sanderson"}],
                },
            },
            "coverPath": "/api/items/item-4/cover",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        item = Book.objects.get(user=self.user).item
        # The raw ABS cover URL requires a bearer token a plain <img src>
        # can't attach, so it's served through Floppy's own proxy (#861).
        self.assertTrue(item.image.startswith("/import/audiobookshelf/cover/"))
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "item-4"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_normalizes_filesystem_cover_path_to_api_endpoint(self, mock_me, mock_item):
        """ABS filesystem coverPath should be mapped to the API cover endpoint."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-fs",
                    "currentTime": 600,
                    "lastUpdate": 9_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 3_600,
                "metadata": {
                    "title": "Filesystem Cover Book",
                    "authors": [{"name": "Test Author"}],
                },
            },
            "coverPath": "/metadata/items/item-fs/cover.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        item = Book.objects.get(user=self.user).item
        self.assertTrue(item.image.startswith("/import/audiobookshelf/cover/"))
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "item-fs"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_completed_book_progress_set_to_runtime_minutes(self, mock_me, mock_item):
        """Finished books preserve actual listened time; runtime_minutes only fills in when currentTime is zero."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-partial-finished",
                    "currentTime": 3_400,
                    "duration": 3_600,
                    "progress": 0.944,
                    "isFinished": True,
                    "lastUpdate": 8_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 3_600,
                "metadata": {
                    "title": "Almost Finished Book",
                    "authors": [{"name": "Test Author"}],
                },
            },
            "coverPath": "https://img.example/partial.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        media = Book.objects.get(user=self.user)
        self.assertEqual(media.status, Status.COMPLETED.value)
        # currentTime=3400s → 56 min; actual listened time is preserved, not overridden to runtime_minutes
        self.assertEqual(media.progress, 3_400 // 60)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_stale_filesystem_cover_triggers_backfill_repair(self, mock_me, mock_item):
        """Items with old metadata-path cover URLs should be repaired on next sync."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 9_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "stale-cover-item")
        Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Stale Cover Book",
            original_title="Stale Cover Book",
            localized_title="Stale Cover Book",
            # Stale URL stored before the URL normalisation fix
            image="https://abs.example.com/metadata/items/stale-cover-item/cover.jpg",
            authors=["Test Author"],
            isbn=["9780000000000"],
            publishers="Test Publisher",
            genres=["Fiction"],
            release_datetime=timezone.now(),
            format="audiobook",
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "stale-cover-item",
                    "currentTime": 1_200,
                    "duration": 3_600,
                    "lastUpdate": 5_000,  # < last_sync_ms → unchanged entry
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 3_600,
                "metadata": {
                    "title": "Stale Cover Book",
                    "authors": [{"name": "Test Author"}],
                },
            },
            "coverPath": "/api/items/stale-cover-item/cover",
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        mock_item.assert_called_once_with("stale-cover-item")
        item = Book.objects.get(user=self.user).item
        # URL should be re-repaired into Floppy's authenticated cover proxy,
        # not left as a raw ABS URL the browser can't load (#861).
        self.assertTrue(item.image.startswith("/import/audiobookshelf/cover/"))
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "stale-cover-item"),
        )

    @patch("integrations.imports.audiobookshelf.services.get_media_metadata")
    @patch("integrations.imports.audiobookshelf.services.search")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_enriches_missing_cover_from_book_provider(
        self,
        mock_me,
        mock_item,
        mock_search,
        mock_get_media_metadata,
    ):
        """Importer should enrich ABS books when Audiobookshelf has no cover."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-5",
                    "currentTime": 2_400,
                    "lastUpdate": 7_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 4_800,
                "metadata": {
                    "title": "Mistborn",
                    "isbn": "978-0-7653-1178-8",
                },
            },
            "coverPath": "",
        }

        mock_search.return_value = {
            "results": [
                {
                    "media_id": "314",
                    "source": Sources.HARDCOVER.value,
                    "title": "Mistborn: The Final Empire",
                },
            ],
        }
        mock_get_media_metadata.return_value = {
            "media_id": "314",
            "source": Sources.HARDCOVER.value,
            "media_type": MediaTypes.BOOK.value,
            "title": "Mistborn: The Final Empire",
            "image": "https://covers.example/mistborn.jpg",
            "max_progress": 541,
            "genres": ["Fantasy"],
            "series_name": "Mistborn",
            "series_position": 1,
            "details": {
                "author": "Brandon Sanderson",
                "publisher": "Tor",
                "isbn": ["9780765311788"],
                "publish_date": "2006-07-17",
            },
        }

        importer = AudiobookshelfImporter(self.user)
        importer.enable_provider_enrichment = True
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        item = Book.objects.get(user=self.user).item
        self.assertEqual(item.image, "https://covers.example/mistborn.jpg")
        self.assertEqual(item.authors, ["Brandon Sanderson"])
        self.assertEqual(item.isbn, ["9780765311788"])
        self.assertEqual(item.publishers, "Tor")
        self.assertEqual(item.genres, ["Fantasy"])
        self.assertEqual(item.series_name, "Mistborn")
        self.assertEqual(item.series_position, 1)
        self.assertEqual(
            item.release_datetime,
            datetime(2006, 7, 17, tzinfo=UTC),
        )

        mock_search.assert_called_once_with(
            MediaTypes.BOOK.value,
            "9780765311788",
            1,
            Sources.HARDCOVER.value,
        )
        mock_get_media_metadata.assert_any_call(
            MediaTypes.BOOK.value,
            "314",
            Sources.HARDCOVER.value,
        )

    @patch("integrations.imports.audiobookshelf.services.get_media_metadata")
    @patch("integrations.imports.audiobookshelf.services.search")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_keeps_abs_cover_when_provider_match_has_no_image(
        self,
        mock_me,
        mock_item,
        mock_search,
        mock_get_media_metadata,
    ):
        """A coverless provider match must not blank out a working ABS cover (#861)."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-6",
                    "currentTime": 600,
                    "lastUpdate": 8_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 4_800,
                "metadata": {
                    "title": "Coverless Match",
                    "isbn": "978-0-7653-1178-8",
                },
            },
            "coverPath": "/api/items/item-6/cover",
        }
        mock_search.return_value = {
            "results": [
                {
                    "media_id": "500",
                    "source": Sources.HARDCOVER.value,
                    "title": "Coverless Match",
                },
            ],
        }
        # Hardcover matched the title but has no cached_image, so it
        # returns settings.IMG_NONE for "image" instead of a real URL.
        mock_get_media_metadata.return_value = {
            "media_id": "500",
            "source": Sources.HARDCOVER.value,
            "media_type": MediaTypes.BOOK.value,
            "title": "Coverless Match",
            "image": settings.IMG_NONE,
            "max_progress": 541,
            "genres": ["Fantasy"],
            "details": {
                "author": "Some Author",
                "isbn": ["9780765311788"],
            },
        }

        importer = AudiobookshelfImporter(self.user)
        importer.enable_provider_enrichment = True
        counts, warnings = importer.import_data()

        self.assertEqual(counts.get(MediaTypes.BOOK.value), 1)
        self.assertEqual(warnings, "")
        item = Book.objects.get(user=self.user).item
        self.assertNotEqual(item.image, settings.IMG_NONE)
        self.assertTrue(item.image.startswith("/import/audiobookshelf/cover/"))
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "item-6"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_repairs_cover_proxy_url_with_an_unverifiable_token(
        self,
        mock_me,
        mock_item,
    ):
        """Rotating SECRET_KEY invalidates every stored cover token at once.

        Nothing else would ever rewrite them, so every ABS poster would break
        permanently - the same symptom as #861, from a different cause.
        """
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "rotated-key-item")
        stale = audiobookshelf_cover.build_cover_proxy_url(
            account.id,
            "rotated-key-item",
        )
        # Same shape, signature from another key.
        stale = stale.rsplit(":", 1)[0] + ":signature-from-a-previous-secret"
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Rotated Key",
            original_title="Rotated Key",
            localized_title="Rotated Key",
            image=stale,
            authors=["Some Author"],
            publishers="Some Publisher",
            genres=["Thriller"],
            release_datetime=datetime(2020, 1, 1, tzinfo=UTC),
            format="audiobook",
            metadata_fetched_at=timezone.now(),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "rotated-key-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 12_000,
                "coverPath": "/metadata/items/rotated-key-item/cover.jpg",
                "metadata": {"title": "Rotated Key"},
            },
        }

        AudiobookshelfImporter(self.user).import_data()

        item.refresh_from_db()
        self.assertNotEqual(item.image, stale)
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "rotated-key-item"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_reads_cover_path_nested_under_media(self, mock_me, mock_item):
        """ABS reports coverPath under media on some versions (#861)."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "media-cover-item",
                    "currentTime": 600,
                    "lastUpdate": 9_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 4_800,
                "coverPath": "/metadata/items/media-cover-item/cover.jpg",
                "metadata": {"title": "Nested Cover"},
            },
        }

        AudiobookshelfImporter(self.user).import_data()

        item = Book.objects.get(user=self.user).item
        self.assertNotEqual(item.image, settings.IMG_NONE)
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "media-cover-item"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_reads_cover_from_library_files(self, mock_me, mock_item):
        """An image entry in libraryFiles is still a cover ABS can serve."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "libfile-item",
                    "currentTime": 600,
                    "lastUpdate": 9_100,
                },
            ],
        }
        mock_item.return_value = {
            "media": {"duration": 4_800, "metadata": {"title": "Library File Cover"}},
            "libraryFiles": [
                {"fileType": "audio", "metadata": {"path": "/books/x/track1.m4b"}},
                {"fileType": "image", "metadata": {"path": "/books/x/cover.jpg"}},
            ],
        }

        AudiobookshelfImporter(self.user).import_data()

        item = Book.objects.get(user=self.user).item
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "libfile-item"),
        )

    @patch("integrations.imports.audiobookshelf.services.get_media_metadata")
    @patch("integrations.imports.audiobookshelf.services.search")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_provider_cover_does_not_override_abs_cover(
        self,
        mock_me,
        mock_item,
        mock_search,
        mock_get_media_metadata,
    ):
        """The user's own ABS artwork wins over a provider cover (#861).

        A provider match carrying a dead or simply wrong cover URL used to
        replace a perfectly good Audiobookshelf cover, which is what made
        *some* posters disappear while others were fine.
        """
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "abs-art-item",
                    "currentTime": 600,
                    "lastUpdate": 9_200,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 4_800,
                "metadata": {
                    "title": "Owned Artwork",
                    "isbn": "978-0-7653-1178-8",
                },
            },
            "coverPath": "/metadata/items/abs-art-item/cover.jpg",
        }
        mock_search.return_value = {
            "results": [
                {
                    "media_id": "600",
                    "source": Sources.HARDCOVER.value,
                    "title": "Owned Artwork",
                },
            ],
        }
        mock_get_media_metadata.return_value = {
            "media_id": "600",
            "source": Sources.HARDCOVER.value,
            "media_type": MediaTypes.BOOK.value,
            "title": "Owned Artwork",
            "image": "https://covers.example/some-other-book.jpg",
            "max_progress": 400,
            "genres": ["Fantasy"],
            "details": {
                "author": "Some Author",
                "publisher": "Tor",
                "isbn": ["9780765311788"],
            },
        }

        importer = AudiobookshelfImporter(self.user)
        importer.enable_provider_enrichment = True
        importer.import_data()

        item = Book.objects.get(user=self.user).item
        account = self.user.audiobookshelf_account
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "abs-art-item"),
        )
        # Enrichment still ran - only the cover preference changed.
        self.assertEqual(item.genres, ["Fantasy"])
        self.assertEqual(item.publishers, "Tor")

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_repairs_placeholder_cover_from_before_the_fix(self, mock_me, mock_item):
        """A row stuck on IMG_NONE heals once the cover cooldown has passed."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "blank-cover-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Der Heimweg",
            original_title="Der Heimweg",
            localized_title="Der Heimweg",
            image=settings.IMG_NONE,
            authors=["Sebastian Fitzek"],
            publishers="Audible Studios",
            genres=["Psychothriller"],
            release_datetime=datetime(2020, 1, 1, tzinfo=UTC),
            format="audiobook",
            metadata_fetched_at=timezone.now() - timedelta(days=2),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "blank-cover-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 12_000,
                "coverPath": "/metadata/items/blank-cover-item/cover.jpg",
                "metadata": {"title": "Der Heimweg"},
            },
        }

        AudiobookshelfImporter(self.user).import_data()

        item.refresh_from_db()
        self.assertEqual(
            cover_proxy_target(item.image),
            (str(account.id), "blank-cover-item"),
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_does_not_re_repair_placeholder_cover_within_cooldown(
        self,
        mock_me,
        mock_item,
    ):
        """An item ABS has no artwork for must not re-repair on every sync."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "artless-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Artless",
            original_title="Artless",
            localized_title="Artless",
            image=settings.IMG_NONE,
            authors=["Some Author"],
            publishers="Some Publisher",
            genres=["Thriller"],
            release_datetime=datetime(2020, 1, 1, tzinfo=UTC),
            format="audiobook",
            metadata_fetched_at=timezone.now(),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "artless-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }

        counts, warnings = AudiobookshelfImporter(self.user).import_data()

        self.assertEqual(counts, {})
        self.assertEqual(warnings, "")
        mock_item.assert_not_called()

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_thin_metadata_is_not_re_repaired_within_cooldown(
        self,
        mock_me,
        mock_item,
    ):
        """Books the providers cannot match must not re-query them forever."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "unmatchable-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Unmatchable",
            original_title="Unmatchable",
            localized_title="Unmatchable",
            image=audiobookshelf_cover.build_cover_proxy_url(
                account.id,
                "unmatchable-item",
            ),
            authors=["Some Author"],
            publishers="",
            genres=[],
            release_datetime=None,
            format="audiobook",
            metadata_fetched_at=timezone.now(),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "unmatchable-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }

        counts, warnings = AudiobookshelfImporter(self.user).import_data()

        self.assertEqual(counts, {})
        self.assertEqual(warnings, "")
        mock_item.assert_not_called()

        # ...but it is retried once the cooldown lapses.
        item.metadata_fetched_at = timezone.now() - (BOOK_REPAIR_COOLDOWN + timedelta(days=1))
        item.save(update_fields=["metadata_fetched_at"])
        mock_item.return_value = {
            "media": {"duration": 12_000, "metadata": {"title": "Unmatchable"}},
        }

        AudiobookshelfImporter(self.user).import_data()

        mock_item.assert_called_once_with("unmatchable-item")

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_marks_connection_broken_on_auth_error(self, mock_me):
        """Auth failures should mark the account as broken and raise import error."""
        mock_me.side_effect = AudiobookshelfAuthError(
            "Audiobookshelf token is invalid or expired",
        )

        importer = AudiobookshelfImporter(self.user)

        with self.assertRaises(MediaImportError):
            importer.import_data()

        self.user.audiobookshelf_account.refresh_from_db()
        self.assertTrue(self.user.audiobookshelf_account.connection_broken)
        self.assertIn(
            "invalid or expired",
            self.user.audiobookshelf_account.last_error_message,
        )

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_unresponsive_server_is_a_clear_error_not_a_broken_account(
        self,
        mock_me,
    ):
        """A timeout reports a readable error without marking the account broken."""
        mock_me.side_effect = requests.exceptions.ReadTimeout("Read timed out.")

        with self.assertRaises(MediaImportError) as raised:
            AudiobookshelfImporter(self.user).import_data()

        self.assertIn("did not respond", str(raised.exception))
        account = self.user.audiobookshelf_account
        account.refresh_from_db()
        self.assertFalse(account.connection_broken)
        self.assertIn("did not respond", account.last_error_message)

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_does_not_refetch_unchanged_books_that_are_already_hydrated(
        self,
        mock_me,
        mock_item,
    ):
        """Healthy unchanged ABS books should not trigger repair lookups."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "healthy-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="The Blade Itself",
            original_title="The Blade Itself",
            localized_title="The Blade Itself",
            image="https://covers.example/blade.jpg",
            authors=["Joe Abercrombie"],
            isbn=["9780316387310"],
            publishers="Orbit",
            genres=["Fantasy"],
            release_datetime=datetime(2006, 5, 4, tzinfo=UTC),
            format="audiobook",
            metadata_fetched_at=timezone.now(),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "healthy-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts, {})
        self.assertEqual(warnings, "")
        mock_item.assert_not_called()

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_release_date_falls_back_to_abs_published_year(
        self,
        mock_me,
        mock_item,
    ):
        """ABS publishedYear should set the release date without a provider."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "year-item",
                    "currentTime": 600,
                    "duration": 7_200,
                    "lastUpdate": 1_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 7_200,
                "metadata": {
                    "title": "Zeitbruch",
                    "authors": [{"name": "Tom Hillenbrand"}],
                    "publisher": "Ronin Hörverlag",
                    "genres": ["Science Fiction"],
                    "publishedYear": "2021",
                },
            },
            "coverPath": "https://covers.example/zeitbruch.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        importer.import_data()

        item = Book.objects.get(user=self.user).item
        self.assertEqual(item.release_datetime, datetime(2021, 1, 1, tzinfo=UTC))

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_release_date_parses_day_month_year_published_year(
        self,
        mock_me,
        mock_item,
    ):
        """ABS sometimes puts a full date in publishedYear."""
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "date-item",
                    "currentTime": 600,
                    "duration": 7_200,
                    "lastUpdate": 1_000,
                },
            ],
        }
        mock_item.return_value = {
            "media": {
                "duration": 7_200,
                "metadata": {
                    "title": "Freiheitsgeld",
                    "authors": [{"name": "Andreas Eschbach"}],
                    "publisher": "BASTEI LÜBBE",
                    "genres": ["Thriller"],
                    "publishedYear": "26-Aug-2022",
                },
            },
            "coverPath": "https://covers.example/freiheitsgeld.jpg",
        }

        importer = AudiobookshelfImporter(self.user)
        importer.import_data()

        item = Book.objects.get(user=self.user).item
        self.assertEqual(item.release_datetime, datetime(2022, 8, 26, tzinfo=UTC))

    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
    @patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
    def test_does_not_repair_hydrated_book_without_isbn(self, mock_me, mock_item):
        """Audiobooks without an ISBN are healthy and must not be re-repaired."""
        account = self.user.audiobookshelf_account
        account.last_sync_ms = 2_000
        account.save(update_fields=["last_sync_ms", "updated_at"])

        importer = AudiobookshelfImporter(self.user)
        media_id = importer._stable_media_id(account.base_url, "no-isbn-item")
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.AUDIOBOOKSHELF.value,
            media_type=MediaTypes.BOOK.value,
            title="Der Heimweg",
            original_title="Der Heimweg",
            localized_title="Der Heimweg",
            image="https://covers.example/heimweg.jpg",
            authors=["Sebastian Fitzek"],
            isbn=[],
            publishers="Audible Studios",
            genres=["Psychothriller"],
            release_datetime=datetime(2020, 1, 1, tzinfo=UTC),
            format="audiobook",
            metadata_fetched_at=timezone.now(),
        )
        Book.objects.create(
            user=self.user,
            item=item,
            status=Status.IN_PROGRESS.value,
            progress=60,
        )

        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "no-isbn-item",
                    "currentTime": 3_600,
                    "duration": 12_000,
                    "lastUpdate": 1_500,
                },
            ],
        }

        importer = AudiobookshelfImporter(self.user)
        counts, warnings = importer.import_data()

        self.assertEqual(counts, {})
        self.assertEqual(warnings, "")
        mock_item.assert_not_called()


class AudiobookshelfTitleMatchingTests(TestCase):
    """Non-ASCII titles must still be comparable against provider results.

    _normalize_name used to be re.sub(r"[^a-z0-9]+", " ", value.lower()), which
    deleted every non-ASCII character: a Cyrillic or Japanese title normalised
    to the empty string and could never match anything (#861).
    """

    def setUp(self):
        """Create a connected account so the importer can be constructed."""
        self.user = get_user_model().objects.create_user(username="abs-titles")
        AudiobookshelfAccount.objects.create(
            user=self.user,
            base_url="https://abs.example.com",
            api_token=helpers.encrypt("token"),
        )
        self.importer = AudiobookshelfImporter(self.user)

    def test_folds_accents_instead_of_dropping_them(self):
        """German umlauts must not push a title below the match threshold."""
        self.assertEqual(self.importer._normalize_name("Zeitbrüch"), "zeitbruch")
        self.assertGreaterEqual(
            self.importer._title_similarity("Zeitbrüch", "Zeitbruch"),
            TITLE_MATCH_THRESHOLD,
        )

    def test_keeps_non_latin_scripts(self):
        """Cyrillic and CJK titles must normalise to something comparable."""
        for title in ("Война и мир", "ノルウェイの森"):
            with self.subTest(title=title):
                self.assertNotEqual(self.importer._normalize_name(title), "")
                self.assertGreaterEqual(
                    self.importer._title_similarity(title, title),
                    TITLE_MATCH_THRESHOLD,
                )

    def test_keeps_marks_that_change_the_word(self):
        """Folding marks off non-Latin scripts collapses distinct titles.

        NFKD decomposes Japanese dakuten and the Cyrillic yo, so stripping
        every combining mark scored different works as a perfect match and
        let a provider overwrite the item with another book's metadata
        (#1069 review).
        """
        collisions = (
            ("\u3070\u3057", "\u306f\u3057"),  # ba-shi vs ha-shi
            ("\u3071\u3057", "\u306f\u3057"),  # pa-shi vs ha-shi
            ("\u3071\u3057", "\u3070\u3057"),  # pa-shi vs ba-shi
            ("\u0432\u0441\u0451", "\u0432\u0441\u0435"),  # vsyo vs vse
        )
        for left, right in collisions:
            with self.subTest(left=left, right=right):
                self.assertNotEqual(
                    self.importer._normalize_name(left),
                    self.importer._normalize_name(right),
                )
                self.assertLess(
                    self.importer._title_similarity(left, right),
                    1.0,
                )

    def test_still_strips_punctuation_and_case(self):
        """The normalisation the ASCII form did must keep working."""
        self.assertEqual(
            self.importer._normalize_name("The Hobbit: There & Back_Again!"),
            "the hobbit there back again",
        )

    def test_unrelated_titles_still_score_low(self):
        """Keeping more characters must not make everything match."""
        self.assertLess(
            self.importer._title_similarity("Война и мир", "ノルウェイの森"),
            TITLE_MATCH_THRESHOLD,
        )


class AudiobookshelfClientRetryTests(TestCase):
    """Validate transient network error retry in AudiobookshelfClient._request."""

    def setUp(self):
        """Create a bare client."""
        self.client = AudiobookshelfClient("https://abs.example.com", "token")

    @patch("integrations.imports.audiobookshelf.time.sleep")
    @patch("integrations.imports.audiobookshelf.requests.get")
    def test_retries_transient_timeout_then_succeeds(self, mock_get, mock_sleep):
        """A read timeout should be retried instead of failing the whole request."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"ok": True}
        mock_get.side_effect = [
            requests.exceptions.ReadTimeout("handshake timed out"),
            response,
        ]

        result = self.client._request("/api/me")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("integrations.imports.audiobookshelf.time.sleep")
    @patch("integrations.imports.audiobookshelf.requests.get")
    def test_raises_after_exhausting_retries(self, mock_get, mock_sleep):
        """Persistent timeouts should still raise once retries are exhausted."""
        mock_get.side_effect = requests.exceptions.ReadTimeout("handshake timed out")

        with self.assertRaises(requests.exceptions.ReadTimeout):
            self.client._request("/api/me")

        self.assertEqual(mock_get.call_count, 3)


def _ms(moment):
    """Return an aware datetime as ABS epoch milliseconds."""
    return int(moment.timestamp() * 1000)


@patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_library_item")
@patch("integrations.imports.audiobookshelf.AudiobookshelfClient.get_me")
class AudiobookshelfHeldStatusTests(TestCase):
    """A status the user sets survives the next sync (#1316)."""

    def setUp(self):
        """Create a logged-in user with an ABS account."""
        self.credentials = {"username": "abs-held", "password": "pass"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        AudiobookshelfAccount.objects.create(
            user=self.user,
            base_url="https://abs.example.com",
            api_token=helpers.encrypt("token"),
        )

    def _sync(self, mock_me, mock_item, **entry):
        mock_me.return_value = {
            "mediaProgress": [
                {
                    "libraryItemId": "item-1",
                    "currentTime": 3600,
                    "duration": 7200,
                    "progress": 0.5,
                    "isFinished": False,
                    "lastUpdate": 1000,
                    **entry,
                },
            ],
        }
        mock_item.return_value = {
            "media": {"duration": 7200, "metadata": {"title": "The Hobbit"}},
        }
        AudiobookshelfImporter(self.user).import_data()
        return Book.objects.get(user=self.user)

    def _set_status_in_floppy(self, book, status):
        """Change the status through the track form, as the user does."""
        self.client.post(
            reverse("media_save"),
            {
                "media_id": book.item.media_id,
                "source": Sources.AUDIOBOOKSHELF.value,
                "media_type": MediaTypes.BOOK.value,
                "instance_id": book.id,
                "status": status,
                "progress": book.progress,
            },
        )
        book.refresh_from_db()
        self.assertEqual(book.status, status)

    def test_paused_survives_sync_of_earlier_listening(self, mock_me, mock_item):
        """Listening from before the pause does not undo it."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.PAUSED.value)

        before_pause = timezone.now() - timedelta(minutes=5)
        book = self._sync(
            mock_me,
            mock_item,
            currentTime=4200,
            lastUpdate=_ms(before_pause),
        )

        self.assertEqual(book.status, Status.PAUSED.value)
        self.assertEqual(book.progress, 70)

    def test_dropped_survives_sync_of_earlier_listening(self, mock_me, mock_item):
        """Dropped is held the same way as Paused."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.DROPPED.value)

        book = self._sync(
            mock_me,
            mock_item,
            lastUpdate=_ms(timezone.now() - timedelta(minutes=5)),
        )

        self.assertEqual(book.status, Status.DROPPED.value)

    def test_listening_after_pause_resumes(self, mock_me, mock_item):
        """Listening again after pausing puts the book back in progress."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.PAUSED.value)

        book = self._sync(
            mock_me,
            mock_item,
            currentTime=4200,
            lastUpdate=_ms(timezone.now() + timedelta(minutes=5)),
        )

        self.assertEqual(book.status, Status.IN_PROGRESS.value)

    def test_completed_in_floppy_is_not_unfinished_by_sync(self, mock_me, mock_item):
        """Marking a book finished in Floppy holds while ABS shows it unfinished."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.COMPLETED.value)
        completed = Book.objects.get(pk=book.pk)

        book = self._sync(
            mock_me,
            mock_item,
            lastUpdate=_ms(timezone.now() - timedelta(minutes=5)),
        )

        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.progress, completed.progress)
        self.assertEqual(book.end_date, completed.end_date)

    def test_finishing_in_abs_completes_a_paused_book(self, mock_me, mock_item):
        """A real finish always wins over a held status."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.PAUSED.value)

        book = self._sync(
            mock_me,
            mock_item,
            currentTime=7200,
            isFinished=True,
            lastUpdate=_ms(timezone.now() - timedelta(minutes=5)),
        )

        self.assertEqual(book.status, Status.COMPLETED.value)

    def test_repair_pass_keeps_held_status(self, mock_me, mock_item):
        """Re-repairing an unchanged book does not reset the user's status."""
        book = self._sync(mock_me, mock_item)
        self._set_status_in_floppy(book, Status.PAUSED.value)
        Item.objects.filter(pk=book.item_id).update(metadata_fetched_at=None)
        mock_item.reset_mock()

        book = self._sync(mock_me, mock_item)

        mock_item.assert_called_once()
        self.assertEqual(book.status, Status.PAUSED.value)
