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

    def test_jellyfin_stop_falls_back_to_provider_completion_value(self):
        """Jellyfin Stop uses a strict Played value without progress."""
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

                self.assertEqual(processor._is_played(payload), played)
                self.assertFalse(
                    PlaybackProgress.objects.filter(user=self.user).exists(),
                )

    def test_jellyfin_stop_uses_progress_before_played_flag(self):
        """Valid Jellyfin progress decides completion, including exactly 80%."""
        processor = JellyfinWebhookProcessor()
        for position, completed in ((79, False), (80, True), (81, True)):
            with self.subTest(position=position):
                PlaybackProgress.objects.all().delete()
                payload = {
                    "Event": "Stop",
                    "Item": {
                        "Type": "Movie",
                        "Id": "jellyfin-movie-1",
                        "Name": "The Matrix",
                        "RunTimeTicks": 100 * 10_000_000,
                        "ProviderIds": {"Tmdb": "701"},
                        "UserData": {"Played": False},
                    },
                    "PlaybackPositionTicks": position * 10_000_000,
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

                progress = PlaybackProgress.objects.get(user=self.user)
                self.assertEqual(progress.position_seconds, position)
                self.assertEqual(progress.duration_seconds, 100)
                self.assertEqual(progress.completed, completed)

    def test_jellyfin_stop_invalid_progress_falls_back_to_strict_played(self):
        """Invalid progress falls back to a boolean Played value."""
        processor = JellyfinWebhookProcessor()
        cases = (
            ({"Played": True}, True),
            ({"Played": "true"}, False),
            ({}, False),
            (None, False),
        )
        for user_data, completed in cases:
            with self.subTest(user_data=user_data):
                item = {
                    "Type": "Movie",
                    "Id": "jellyfin-movie-1",
                    "Name": "The Matrix",
                    "RunTimeTicks": "malformed",
                    "ProviderIds": {"Tmdb": "701"},
                }
                if user_data is not None:
                    item["UserData"] = user_data
                payload = {
                    "Event": "Stop",
                    "Item": item,
                    "PlaybackPositionTicks": "malformed",
                }
                self.assertEqual(processor._is_played(payload), completed)

    def test_jellyfin_play_and_pause_never_count_as_completion(self):
        """Playback start and pause ignore even a stale played flag."""
        processor = JellyfinWebhookProcessor()
        for event in ("Play", "Pause"):
            with self.subTest(event=event):
                payload = {
                    "Event": event,
                    "Item": {
                        "Type": "Movie",
                        "UserData": {"Played": True},
                        "RunTimeTicks": 100 * 10_000_000,
                    },
                    "PlaybackPositionTicks": 100 * 10_000_000,
                }
                self.assertFalse(processor._is_played(payload))

    def test_jellyfin_pause_clears_stale_saved_completion(self):
        """A pause cannot leave durable progress completed."""
        processor = JellyfinWebhookProcessor()
        PlaybackProgress.objects.create(
            user=self.user,
            item=self.movie_item,
            position_seconds=80,
            duration_seconds=100,
            completed=True,
        )
        payload = {
            "Event": "Pause",
            "Item": {
                "Type": "Movie",
                "Id": "jellyfin-movie-1",
                "Name": "The Matrix",
                "RunTimeTicks": 100 * 10_000_000,
                "ProviderIds": {"Tmdb": "701"},
                "UserData": {"Played": True},
            },
            "PlaybackPositionTicks": 10 * 10_000_000,
        }
        with patch("app.live_playback._attach_resolved_image"):
            processor.process_payload(payload, self.user)

        progress = PlaybackProgress.objects.get(user=self.user, item=self.movie_item)
        self.assertEqual(progress.position_seconds, 10)
        self.assertFalse(progress.completed)

    def test_jellyfin_stop_preserves_zero_position_and_rejects_invalid_ticks(self):
        """Zero is a valid position; negative and boolean ticks are not."""
        processor = JellyfinWebhookProcessor()
        base = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "Id": "jellyfin-movie-1",
                "Name": "The Matrix",
                "ProviderIds": {"Tmdb": "701"},
                "UserData": {"Played": True},
                "PlaybackPositionTicks": 70 * 10_000_000,
            },
        }

        zero_payload = {
            **base,
            "Item": {**base["Item"], "RunTimeTicks": 100 * 10_000_000},
            "PlaybackPositionTicks": 0,
        }
        self.assertEqual(processor._get_playback_progress(zero_payload), (0, 100))
        self.assertFalse(processor._is_played(zero_payload))
        with (
            patch("app.live_playback._attach_resolved_image"),
            patch.object(
                processor,
                "_process_media",
                return_value=self.movie_item,
            ),
        ):
            processor.process_payload(zero_payload, self.user)
        progress = PlaybackProgress.objects.get(user=self.user)
        self.assertEqual(progress.position_seconds, 0)
        self.assertFalse(progress.completed)

        for position_ticks, duration_ticks, expected in (
            (-1, 100 * 10_000_000, (None, 100)),
            (True, 100 * 10_000_000, (None, 100)),
            (1, -1, (0, None)),
            (0, 1, (0, None)),
            (0, True, (0, None)),
        ):
            with self.subTest(
                position_ticks=position_ticks,
                duration_ticks=duration_ticks,
            ):
                payload = {
                    **base,
                    "Item": {
                        **base["Item"],
                        "RunTimeTicks": duration_ticks,
                        "UserData": {"Played": False},
                    },
                    "PlaybackPositionTicks": position_ticks,
                }
                self.assertEqual(processor._get_playback_progress(payload), expected)
                self.assertFalse(processor._is_played(payload))

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
