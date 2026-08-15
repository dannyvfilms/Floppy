import requests
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone

from app import metadata_snapshots, network_policy
from app.models import Item, MediaTypes, MetadataSnapshot, Sources
from app.providers import services


@override_settings(
    FLOPPY_METADATA_FAILURE_RETRY_SECONDS=0,
    FLOPPY_METADATA_FRESH_SECONDS=3600,
    FLOPPY_METADATA_MAX_PAYLOAD_BYTES=2_097_152,
    FLOPPY_METADATA_MERGE_MODE="preserve",
    FLOPPY_METADATA_PERSIST_MODE="all",
    FLOPPY_METADATA_READ_MODE="local-first",
    FLOPPY_METADATA_REFRESH_LEASE_SECONDS=60,
    FLOPPY_METADATA_REFRESH_MODE="blocking",
    FLOPPY_NETWORK_MODE="online",
)
class MetadataSnapshotTests(TestCase):
    def setUp(self):
        network_policy.install_provider_network_guard()
        metadata_snapshots.install_metadata_snapshot_guard()
        MetadataSnapshot.objects.all().delete()

    @staticmethod
    def _identity(media_id="1"):
        return metadata_snapshots.build_metadata_identity(
            MediaTypes.MOVIE.value,
            media_id,
            Sources.TMDB.value,
        )

    @staticmethod
    def _complete_payload(title="Stored title", synopsis="Stored synopsis"):
        return {
            "cast": [],
            "crew": [],
            "details": {"runtime_minutes": 120},
            "image": "https://example.invalid/poster.jpg",
            "media_id": "1",
            "media_type": MediaTypes.MOVIE.value,
            "original_title": title,
            "source": Sources.TMDB.value,
            "synopsis": synopsis,
            "title": title,
        }

    def _save_ready_snapshot(self, *, payload=None, fetched_at=None, media_id="1"):
        identity = self._identity(media_id)
        return metadata_snapshots._save_snapshot(
            identity,
            payload or self._complete_payload(),
            policy=metadata_snapshots.get_metadata_policy(),
            state=MetadataSnapshot.State.READY,
            origin=MetadataSnapshot.Origin.PROVIDER,
            fetched_at=fetched_at or timezone.now(),
        )

    @override_settings(
        FLOPPY_METADATA_READ_MODE="local-only",
        FLOPPY_NETWORK_MODE="offline",
    )
    @patch("app.providers.tmdb.movie")
    def test_item_created_by_import_is_available_without_provider_call(
        self,
        mock_movie,
    ):
        item = Item.objects.create(
            media_id="local-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Local title",
            original_title="Local title",
            localized_title="Local title",
            synopsis="Local synopsis",
            image="https://example.invalid/local.jpg",
            genres=["Drama"],
        )

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            item.media_id,
            item.source,
        )

        mock_movie.assert_not_called()
        self.assertEqual(result["title"], "Local title")
        self.assertEqual(result["synopsis"], "Local synopsis")
        self.assertEqual(result["genres"], ["Drama"])
        self.assertEqual(result["_floppy_cache"]["source"], "snapshot")
        self.assertIn(
            result["_floppy_cache"]["state"],
            {"local-only", "blocked-local-copy"},
        )
        self.assertTrue(
            MetadataSnapshot.objects.filter(
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                media_id="local-1",
            ).exists(),
        )

    @patch("app.providers.tmdb.movie")
    def test_fresh_snapshot_skips_provider(self, mock_movie):
        self._save_ready_snapshot()

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
        )

        mock_movie.assert_not_called()
        self.assertEqual(result["title"], "Stored title")
        self.assertFalse(result["_floppy_cache"]["stale"])
        self.assertEqual(result["_floppy_cache"]["source"], "snapshot")

    @patch("app.providers.tmdb.movie")
    def test_forced_refresh_bypasses_fresh_snapshot(self, mock_movie):
        self._save_ready_snapshot()
        mock_movie.return_value = self._complete_payload(title="Refreshed title")

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
            _floppy_refresh=True,
        )

        mock_movie.assert_called_once()
        self.assertEqual(result["title"], "Refreshed title")
        self.assertEqual(result["_floppy_cache"]["source"], "provider")
        self.assertEqual(
            MetadataSnapshot.objects.get(cache_key=self._identity().cache_key).payload[
                "title"
            ],
            "Refreshed title",
        )

    @patch("app.providers.tmdb.movie")
    def test_failed_refresh_keeps_last_known_good_payload(self, mock_movie):
        self._save_ready_snapshot(
            fetched_at=timezone.now() - timezone.timedelta(days=2),
        )
        mock_movie.side_effect = services.ProviderAPIError(
            Sources.TMDB.value,
            requests.exceptions.ConnectionError("network unavailable"),
        )

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
            _floppy_refresh=True,
        )

        snapshot = MetadataSnapshot.objects.get(cache_key=self._identity().cache_key)
        self.assertEqual(result["title"], "Stored title")
        self.assertEqual(snapshot.payload["title"], "Stored title")
        self.assertEqual(snapshot.state, MetadataSnapshot.State.FAILED)
        self.assertEqual(result["_floppy_cache"]["state"], "failed-local-copy")
        self.assertNotIn("network unavailable", snapshot.failure_code)

    @patch("app.providers.tmdb.movie")
    def test_partial_refresh_does_not_erase_known_values(self, mock_movie):
        self._save_ready_snapshot()
        incoming = self._complete_payload(title="New title", synopsis="")
        incoming["details"] = {}
        mock_movie.return_value = incoming

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
            _floppy_refresh=True,
        )

        snapshot = MetadataSnapshot.objects.get(cache_key=self._identity().cache_key)
        self.assertEqual(result["title"], "New title")
        self.assertEqual(result["synopsis"], "Stored synopsis")
        self.assertEqual(snapshot.payload["synopsis"], "Stored synopsis")
        self.assertEqual(snapshot.payload["details"]["runtime_minutes"], 120)

    @override_settings(FLOPPY_METADATA_REFRESH_MODE="background")
    @patch("app.tasks_metadata_snapshots.refresh_metadata_snapshot.apply_async")
    @patch("app.providers.tmdb.movie")
    def test_stale_snapshot_returns_before_background_refresh(
        self,
        mock_movie,
        mock_apply_async,
    ):
        self._save_ready_snapshot(
            fetched_at=timezone.now() - timezone.timedelta(days=2),
        )

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
        )

        mock_movie.assert_not_called()
        mock_apply_async.assert_called_once()
        self.assertEqual(result["title"], "Stored title")
        self.assertTrue(result["_floppy_cache"]["stale"])
        self.assertTrue(result["_floppy_cache"]["refresh_queued"])

    @override_settings(FLOPPY_METADATA_REFRESH_MODE="background")
    @patch(
        "app.tasks_metadata_snapshots.refresh_metadata_snapshot.apply_async",
        side_effect=RuntimeError("broker unavailable"),
    )
    @patch("app.providers.tmdb.movie")
    def test_queue_failure_still_returns_local_payload(
        self,
        mock_movie,
        mock_apply_async,
    ):
        self._save_ready_snapshot(
            fetched_at=timezone.now() - timezone.timedelta(days=2),
        )

        result = services.get_media_metadata(
            MediaTypes.MOVIE.value,
            "1",
            Sources.TMDB.value,
        )

        mock_movie.assert_not_called()
        mock_apply_async.assert_called_once()
        self.assertEqual(result["title"], "Stored title")
        self.assertFalse(result["_floppy_cache"]["refresh_queued"])
        self.assertEqual(
            MetadataSnapshot.objects.get(cache_key=self._identity().cache_key).state,
            MetadataSnapshot.State.FAILED,
        )

    @override_settings(
        FLOPPY_METADATA_FRESH_OVERRIDES="tmdb=60,tmdb/tv=10",
    )
    def test_freshness_overrides_use_exact_provider_and_media_type(self):
        policy = metadata_snapshots.get_metadata_policy()

        self.assertEqual(policy.freshness_seconds_for("tmdb", "tv"), 10)
        self.assertEqual(policy.freshness_seconds_for("tmdb", "movie"), 60)
        self.assertEqual(policy.freshness_seconds_for("tvdb", "tv"), 3600)

    @override_settings(FLOPPY_METADATA_FRESH_OVERRIDES="tmdb.example=10")
    def test_invalid_freshness_selector_fails_closed(self):
        with self.assertRaises(ImproperlyConfigured):
            metadata_snapshots.get_metadata_policy()

    def test_snapshot_payload_removes_secret_shaped_fields(self):
        payload, _, _ = metadata_snapshots.sanitize_metadata_payload(
            {
                "api_key": "secret-api-key",
                "nested": {
                    "authorization": "Bearer secret",
                    "title": "Safe title",
                },
                "title": "Safe title",
            },
            max_payload_bytes=4096,
        )

        self.assertNotIn("api_key", payload)
        self.assertNotIn("authorization", payload["nested"])
        self.assertEqual(payload["title"], "Safe title")

    def test_oversized_payload_is_rejected_before_database_write(self):
        with self.assertRaises(metadata_snapshots.MetadataSnapshotRejected) as raised:
            metadata_snapshots.sanitize_metadata_payload(
                {"title": "x" * 4096},
                max_payload_bytes=1024,
            )

        self.assertEqual(raised.exception.code, "payload_too_large")
