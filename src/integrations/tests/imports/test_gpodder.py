from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Sources,
    Status,
)
from integrations.imports import gpodder as gpodder_import
from integrations.imports.helpers import MediaImportError, encrypt
from integrations.models import GPodderAccount


class GPodderImporterTests(TestCase):
    """Tests for the GPodder importer."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="listener", password="pass"
        )
        self.account = GPodderAccount.objects.create(
            user=self.user,
            server_url=encrypt("https://gpodder.net"),
            username=encrypt("listener"),
            password=encrypt("secret"),
            device_id=f"yamtrack-{self.user.id}",
        )

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_initial_sync_creates_show_episode_and_progress(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {
            "title": "Example Show",
            "description": "Desc",
            "author": "Host",
        }
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": timezone.now(),
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:00:00Z",
                    "position": 120,
                    "total": 300,
                },
            ],
            77,
        )

        counts, warnings = gpodder_import.importer(None, self.user, "new")

        self.assertEqual(warnings, [])
        self.assertEqual(counts[MediaTypes.PODCAST.value], 1)
        show = PodcastShow.objects.get()
        self.assertEqual(show.source, Sources.GPODDER.value)
        item = Item.objects.get(
            source=Sources.GPODDER.value, media_type=MediaTypes.PODCAST.value
        )
        podcast = Podcast.objects.get(item=item, user=self.user)
        self.assertEqual(podcast.status, Status.IN_PROGRESS.value)
        self.assertEqual(podcast.played_up_to_seconds, 120)
        self.account.refresh_from_db()
        self.assertEqual(self.account.episode_actions_since, 77)

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_incremental_sync_updates_to_completion_and_stays_idempotent(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        now = timezone.now()
        show = PodcastShow.objects.create(
            podcast_uuid="gp_existing",
            source=Sources.GPODDER.value,
            title="Example Show",
            rss_feed_url="https://example.com/feed.xml",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="ep-1",
            title="Episode 1",
            audio_url="https://cdn.example.com/ep1.mp3",
            duration=300,
            published=now,
        )
        item = Item.objects.create(
            media_id="ep-1",
            source=Sources.GPODDER.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode 1",
            image="https://example.com/image.jpg",
            runtime_minutes=5,
            release_datetime=now,
        )
        Podcast.objects.create(
            user=self.user,
            item=item,
            show=show,
            episode=episode,
            status=Status.IN_PROGRESS.value,
            progress=2,
            played_up_to_seconds=120,
            last_seen_status=2,
        )

        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {"title": "Example Show"}
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": now,
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:05:00Z",
                    "position": 300,
                    "total": 300,
                },
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:05:00Z",
                    "position": 300,
                    "total": 300,
                },
            ],
            88,
        )

        counts, _ = gpodder_import.importer(None, self.user, "new")

        podcast = Podcast.objects.get(user=self.user, item=item)
        self.assertEqual(counts[MediaTypes.PODCAST.value], 1)
        self.assertEqual(podcast.status, Status.COMPLETED.value)
        self.assertEqual(
            podcast.end_date.isoformat().replace("+00:00", "Z"), "2026-01-01T12:05:00Z"
        )
        self.assertEqual(Podcast.objects.filter(user=self.user, item=item).count(), 1)

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_initial_sync_populates_show_and_item_artwork_from_rss(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {
            "title": "Example Show",
            "image": "https://example.com/art.jpg",
        }
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": timezone.now(),
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:00:00Z",
                    "position": 120,
                    "total": 300,
                },
            ],
            77,
        )

        gpodder_import.importer(None, self.user, "new")

        show = PodcastShow.objects.get()
        self.assertEqual(show.image, "https://example.com/art.jpg")
        item = Item.objects.get(
            source=Sources.GPODDER.value, media_type=MediaTypes.PODCAST.value
        )
        self.assertEqual(item.image, "https://example.com/art.jpg")

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_resync_backfills_item_image_once_show_gains_artwork(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        now = timezone.now()
        show = PodcastShow.objects.create(
            podcast_uuid="gp_existing",
            source=Sources.GPODDER.value,
            title="Example Show",
            rss_feed_url="https://example.com/feed.xml",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="ep-1",
            title="Episode 1",
            audio_url="https://cdn.example.com/ep1.mp3",
            duration=300,
            published=now,
        )
        item = Item.objects.create(
            media_id="ep-1",
            source=Sources.GPODDER.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode 1",
            image="",
            runtime_minutes=5,
            release_datetime=now,
        )
        Podcast.objects.create(
            user=self.user,
            item=item,
            show=show,
            episode=episode,
            status=Status.IN_PROGRESS.value,
            progress=2,
            played_up_to_seconds=120,
            last_seen_status=2,
        )

        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {
            "title": "Example Show",
            "image": "https://example.com/new-art.jpg",
        }
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": now,
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:05:00Z",
                    "position": 150,
                    "total": 300,
                },
            ],
            88,
        )

        gpodder_import.importer(None, self.user, "new")

        show.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(show.image, "https://example.com/new-art.jpg")
        self.assertEqual(item.image, "https://example.com/new-art.jpg")

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_resync_backfills_website_url_on_an_existing_show_and_episode(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        """Rows imported before podcast website links existed repair on re-sync.

        gPodder is the reporter's provider in issue #1014, and this importer
        never wrote website_url at all -- not on create and not on update -- so
        their links stayed blank however many times they synced.
        """
        now = timezone.now()
        show = PodcastShow.objects.create(
            podcast_uuid="gp_no_website",
            source=Sources.GPODDER.value,
            title="Example Show",
            rss_feed_url="https://example.com/feed.xml",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="ep-1",
            title="Episode 1",
            audio_url="https://cdn.example.com/ep1.mp3",
            duration=300,
            published=now,
        )

        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {
            "title": "Example Show",
            "website_url": "https://www.spreaker.com/show/example",
        }
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": now,
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
                "website_url": "https://www.spreaker.com/episode/one",
            },
        ]
        mock_fetch_actions.return_value = ([], 99)

        gpodder_import.importer(None, self.user, "new")

        show.refresh_from_db()
        episode.refresh_from_db()
        self.assertEqual(show.website_url, "https://www.spreaker.com/show/example")
        self.assertEqual(
            episode.website_url,
            "https://www.spreaker.com/episode/one",
        )

    @patch(
        "integrations.imports.gpodder.GPodderImporter._process_action",
        side_effect=RuntimeError("boom"),
    )
    @patch(
        "integrations.imports.gpodder.gpodder_api.fetch_episode_actions",
        return_value=(
            [
                {
                    "action": "play",
                    "timestamp": "2026-01-01T12:00:00Z",
                    "position": 120,
                    "total": 300,
                },
            ],
            91,
        ),
    )
    @patch(
        "integrations.imports.gpodder.gpodder_api.fetch_subscriptions", return_value=[]
    )
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    def test_failed_processing_does_not_advance_cursor(
        self,
        _mock_register_device,
        _mock_verify_login,
        _mock_fetch_subscriptions,
        _mock_fetch_episode_actions,
        _mock_process_action,
    ):
        with self.assertRaises(RuntimeError):
            gpodder_import.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertIsNone(self.account.episode_actions_since)

    @patch(
        "integrations.imports.gpodder.gpodder_api.verify_login",
        side_effect=gpodder_import.gpodder_api.GPodderAuthError("nope"),
    )
    def test_invalid_credentials_raise_media_import_error(self, _mock_verify_login):
        with self.assertRaises(MediaImportError):
            gpodder_import.importer(None, self.user, "new")

    def test_naive_timestamp_is_parsed_as_utc_not_local_time(self):
        importer = gpodder_import.GPodderImporter(self.user, "new")

        with timezone.override("America/New_York"):
            parsed = importer._parse_action_timestamp(
                {"timestamp": "2026-01-01T12:00:00"}
            )

        self.assertEqual(parsed, datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_recently_full_resynced_account_stays_incremental(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        self.account.episode_actions_since = 55
        self.account.last_full_resync_at = timezone.now()
        self.account.save(update_fields=["episode_actions_since", "last_full_resync_at"])

        mock_fetch_subscriptions.return_value = []
        mock_show_metadata.return_value = {}
        mock_fetch_rss_episodes.return_value = []
        mock_fetch_actions.return_value = ([], 55)

        gpodder_import.importer(None, self.user, "new")

        _, kwargs = mock_fetch_actions.call_args
        self.assertEqual(kwargs["since"], 55)

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_stale_cursor_triggers_full_resync_and_recovers_missed_completion(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        now = timezone.now()
        show = PodcastShow.objects.create(
            podcast_uuid="gp_existing",
            source=Sources.GPODDER.value,
            title="Voicemail Dump Truck",
            rss_feed_url="https://example.com/feed.xml",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="ep-1",
            title="Daymare.mp3 | Voicemail Dump Truck 221",
            audio_url="https://cdn.example.com/ep1.mp3",
            duration=4054,
            published=now,
        )
        item = Item.objects.create(
            media_id="ep-1",
            source=Sources.GPODDER.value,
            media_type=MediaTypes.PODCAST.value,
            title="Daymare.mp3 | Voicemail Dump Truck 221",
            image="https://example.com/image.jpg",
            runtime_minutes=67,
            release_datetime=now,
        )
        Podcast.objects.create(
            user=self.user,
            item=item,
            show=show,
            episode=episode,
            status=Status.IN_PROGRESS.value,
            progress=43,
            played_up_to_seconds=2639,
            last_seen_status=2,
        )

        self.account.episode_actions_since = 99
        self.account.last_full_resync_at = timezone.now() - timedelta(hours=25)
        self.account.save(update_fields=["episode_actions_since", "last_full_resync_at"])

        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {"title": "Voicemail Dump Truck"}
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Daymare.mp3 | Voicemail Dump Truck 221",
                "published": now,
                "duration": 4054,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        # The completing action shares its timestamp with an unrelated
        # "delete" action, mirroring the GPodder server payload from the
        # bug report where a boundary action like this was silently
        # excluded from incremental (since=<cursor>) fetches.
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-09-06T18:36:28Z",
                    "position": 926,
                    "total": 4054,
                },
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-09-06T18:55:56Z",
                    "position": 2639,
                    "total": 4054,
                },
                {
                    "action": "delete",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-09-06T19:11:52Z",
                },
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-09-06T19:11:52Z",
                    "position": 4054,
                    "total": 4054,
                },
            ],
            123,
        )

        gpodder_import.importer(None, self.user, "new")

        _, kwargs = mock_fetch_actions.call_args
        self.assertIsNone(kwargs["since"])

        self.assertEqual(Podcast.objects.filter(user=self.user, item=item).count(), 1)
        podcast = Podcast.objects.get(user=self.user, item=item)
        self.assertEqual(podcast.status, Status.COMPLETED.value)
        self.assertEqual(podcast.played_up_to_seconds, 4054)
        self.assertIsNotNone(podcast.end_date)

        self.account.refresh_from_db()
        self.assertEqual(self.account.episode_actions_since, 123)
        self.assertGreater(self.account.last_full_resync_at, now)

    @patch("integrations.imports.gpodder.gpodder_api.register_device")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_episode_actions")
    @patch("integrations.imports.gpodder.gpodder_api.fetch_subscriptions")
    @patch("integrations.imports.gpodder.gpodder_api.verify_login")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_episodes_from_rss")
    @patch("integrations.imports.gpodder.podcast_rss.fetch_show_metadata_from_rss")
    def test_full_resync_replay_does_not_duplicate_repeated_listens(
        self,
        mock_show_metadata,
        mock_fetch_rss_episodes,
        _mock_verify_login,
        mock_fetch_subscriptions,
        mock_fetch_actions,
        _mock_register_device,
    ):
        """A daily full resync must not recreate rows for older completions.

        Regression test for a full-history replay that only checked the
        single most-recently-created completed row: an older completion
        (from an earlier repeat listen) fell outside that row's dedup
        window and was recreated as a duplicate on every replay.
        """
        now = timezone.now()
        show = PodcastShow.objects.create(
            podcast_uuid="gp_existing",
            source=Sources.GPODDER.value,
            title="Example Show",
            rss_feed_url="https://example.com/feed.xml",
        )
        episode = PodcastEpisode.objects.create(
            show=show,
            episode_uuid="ep-1",
            title="Episode 1",
            audio_url="https://cdn.example.com/ep1.mp3",
            duration=300,
            published=now,
        )
        item = Item.objects.create(
            media_id="ep-1",
            source=Sources.GPODDER.value,
            media_type=MediaTypes.PODCAST.value,
            title="Episode 1",
            image="https://example.com/image.jpg",
            runtime_minutes=5,
            release_datetime=now,
        )
        # Two earlier, separate completed listens of the same episode.
        first_completion = Podcast.objects.create(
            user=self.user,
            item=item,
            show=show,
            episode=episode,
            status=Status.COMPLETED.value,
            progress=5,
            played_up_to_seconds=300,
            last_seen_status=3,
            end_date=datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC),
        )
        second_completion = Podcast.objects.create(
            user=self.user,
            item=item,
            show=show,
            episode=episode,
            status=Status.COMPLETED.value,
            progress=5,
            played_up_to_seconds=300,
            last_seen_status=3,
            end_date=datetime(2026, 2, 1, 12, 5, 0, tzinfo=UTC),
        )

        self.account.episode_actions_since = 200
        self.account.last_full_resync_at = timezone.now() - timedelta(hours=25)
        self.account.save(update_fields=["episode_actions_since", "last_full_resync_at"])

        mock_fetch_subscriptions.return_value = ["https://example.com/feed.xml"]
        mock_show_metadata.return_value = {"title": "Example Show"}
        mock_fetch_rss_episodes.return_value = [
            {
                "title": "Episode 1",
                "published": now,
                "duration": 300,
                "audio_url": "https://cdn.example.com/ep1.mp3",
                "guid": "ep-1",
            },
        ]
        mock_fetch_actions.return_value = (
            [
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-01-01T12:05:00Z",
                    "position": 300,
                    "total": 300,
                },
                {
                    "action": "play",
                    "podcast": "https://example.com/feed.xml",
                    "episode": "https://cdn.example.com/ep1.mp3",
                    "timestamp": "2026-02-01T12:05:00Z",
                    "position": 300,
                    "total": 300,
                },
            ],
            250,
        )

        gpodder_import.importer(None, self.user, "new")

        self.assertEqual(Podcast.objects.filter(user=self.user, item=item).count(), 2)
        first_completion.refresh_from_db()
        second_completion.refresh_from_db()
        self.assertEqual(first_completion.status, Status.COMPLETED.value)
        self.assertEqual(second_completion.status, Status.COMPLETED.value)
