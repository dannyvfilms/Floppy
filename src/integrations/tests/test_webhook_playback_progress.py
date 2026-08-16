from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.models import Item, MediaTypes, PlaybackProgress, Sources
from integrations.webhooks.emby import EmbyWebhookProcessor
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor
from integrations.webhooks.plex import PlexWebhookProcessor


class WebhookPlaybackProgressTests(TestCase):
    """Webhook stops persist progress against the processed Item."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="playback-user",
            plex_usernames="plex-user",
        )
        self.movie_item = Item.objects.create(
            media_id="701",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="https://example.com/matrix.jpg",
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_first_plex_stop_persists_after_media_processing(self):
        """A first stop can write after processing creates the Item."""
        Item.objects.filter(pk=self.movie_item.pk).delete()
        processor = PlexWebhookProcessor()

        def process_media(_payload, _user, _ids):
            return Item.objects.create(
                media_id="701",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="The Matrix",
                image="https://example.com/matrix.jpg",
            )

        payload = {
            "event": "media.stop",
            "Account": {"title": "plex-user"},
            "Metadata": {
                "type": "movie",
                "title": "The Matrix",
                "ratingKey": "plex-movie-1",
                "duration": 8_160_000,
                "viewOffset": 1_380_000,
                "Guid": [{"id": "tmdb://701"}],
            },
        }

        with (
            patch("app.live_playback._attach_resolved_image"),
            patch.object(processor, "_process_media", side_effect=process_media),
        ):
            processor.process_payload(payload, self.user)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.item.media_id, "701")
        self.assertEqual(progress.position_seconds, 1380)
        self.assertEqual(progress.duration_seconds, 8160)

    def test_cold_cache_plex_episode_stop_uses_exact_episode_item(self):
        """A cold cache cannot redirect an episode position to a show row."""
        episode_item = Item.objects.create(
            media_id="1416",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Four",
            image="https://example.com/episode.jpg",
            season_number=4,
            episode_number=4,
        )
        cache.clear()
        processor = PlexWebhookProcessor()
        payload = {
            "event": "media.stop",
            "Account": {"title": "plex-user"},
            "Metadata": {
                "type": "episode",
                "title": "Episode Four",
                "ratingKey": "plex-episode-1",
                "parentIndex": 4,
                "index": 4,
                "duration": 2_700_000,
                "viewOffset": 1_500_000,
                "Guid": [{"id": "tmdb://1416"}],
            },
        }

        with (
            patch("app.live_playback._attach_resolved_image"),
            patch.object(processor, "_process_media", return_value=episode_item),
        ):
            processor.process_payload(payload, self.user)

        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.item, episode_item)
        self.assertEqual(progress.position_seconds, 1500)

    def test_jellyfin_stop_uses_provider_completion_value(self):
        """Jellyfin Stop preserves both completed and incomplete states."""
        processor = JellyfinWebhookProcessor()
        for played in (True, False):
            with self.subTest(played=played):
                PlaybackProgress.objects.all().delete()
                payload = {
                    "Event": "Stop",
                    "Item": {
                        "Type": "Movie",
                        "Id": "jellyfin-movie-1",
                        "Name": "The Matrix",
                        "RunTimeTicks": 81_600_000_000,
                        "PlaybackPositionTicks": 13_800_000_000,
                        "ProviderIds": {"Tmdb": "701"},
                        "UserData": {"Played": played},
                    },
                }
                with (
                    patch("app.live_playback._attach_resolved_image"),
                    patch.object(
                        processor,
                        "_process_media",
                        return_value=self.movie_item,
                    ),
                ):
                    processor.process_payload(payload, self.user)

                self.assertEqual(
                    PlaybackProgress.objects.get(user=self.user).completed,
                    played,
                )

    def test_emby_stop_uses_provider_completion_value(self):
        """Emby Stop preserves both completed and incomplete states."""
        processor = EmbyWebhookProcessor()
        for played in (True, False):
            with self.subTest(played=played):
                PlaybackProgress.objects.all().delete()
                payload = {
                    "Event": "playback.stop",
                    "Item": {
                        "Type": "Movie",
                        "Id": "emby-movie-1",
                        "Name": "The Matrix",
                        "RunTimeTicks": 81_600_000_000,
                        "PlaybackPositionTicks": 13_800_000_000,
                        "ProviderIds": {"Tmdb": "701"},
                    },
                    "PlaybackInfo": {"PlayedToCompletion": played},
                }
                with (
                    patch("app.live_playback._attach_resolved_image"),
                    patch.object(
                        processor,
                        "_process_media",
                        return_value=self.movie_item,
                    ),
                ):
                    processor.process_payload(payload, self.user)

                self.assertEqual(
                    PlaybackProgress.objects.get(user=self.user).completed,
                    played,
                )
