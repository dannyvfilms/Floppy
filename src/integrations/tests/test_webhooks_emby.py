import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, tag
from django.urls import reverse
from django.utils import timezone

from app import live_playback
from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Season,
    Status,
)
from integrations import tasks
from integrations.webhooks.emby import EmbyWebhookProcessor


class EmbyWebhookTests(TestCase):
    """Tests for Emby webhook."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "testuser", "token": "test-token"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        self.url = reverse("emby_webhook", kwargs={"token": "test-token"})

    def tearDown(self):
        """Clear cached playback state created by webhook tests."""
        live_playback.clear_user_playback_state(self.user.id)

    @patch("app.providers.tmdb.movie")
    def test_late_partial_stop_from_the_same_second_does_not_undo_completion(
        self,
        mock_movie,
    ):
        """A stop's receipt time reaches the durable row, not just the card.

        Emby sends only start and stop, and start writes no durable progress,
        so an earlier partial stop is the late event that can reset completion.
        """
        mock_movie.return_value = {
            "title": "Zombie",
            "image": "",
            "max_progress": 1,
            "provider_external_ids": {},
        }
        item = {
            "Id": "emby-order",
            "Name": "Zombie",
            "Type": "Movie",
            "RunTimeTicks": 54000000000,
            "ProviderIds": {"Tmdb": "7219"},
        }
        second = timezone.now().replace(microsecond=0) - timedelta(seconds=5)
        stop_received = second + timedelta(milliseconds=900)

        def send(event, playback_info, received, event_id):
            tasks.process_webhook(
                "emby",
                {"Event": event, "Item": item, "PlaybackInfo": playback_info},
                self.user.id,
                received_at=received.isoformat(),
                event_id=event_id,
            )

        send(
            "playback.start",
            {"PositionTicks": 0},
            second - timedelta(seconds=60),
            "emby-start",
        )
        send(
            "playback.stop",
            {"PlayedToCompletion": True, "PositionTicks": 53000000000},
            stop_received,
            "emby-stop",
        )
        movie = Movie.objects.get(item__media_id="7219", user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)

        # Received before the completed stop, processed after it.
        send(
            "playback.stop",
            {"PlayedToCompletion": False, "PositionTicks": 16200000000},
            second + timedelta(milliseconds=100),
            "emby-stop-late",
        )

        progress = PlaybackProgress.objects.get(user=self.user, item=movie.item)
        self.assertTrue(progress.completed)
        self.assertEqual(progress.position_seconds, 5300)
        self.assertEqual(progress.last_event_at, stop_received)
        state = live_playback.get_user_playback_state(self.user.id)
        self.assertEqual(state["status"], live_playback.PLAYBACK_STATUS_STOPPED)
        self.assertEqual(state["event_ts"], stop_received.timestamp())

    def test_invalid_token(self):
        """Test webhook with invalid token returns 401."""
        url = reverse("emby_webhook", kwargs={"token": "invalid-token"})
        response = self.client.post(url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_debug_logging_omits_account_and_activity_values(self):
        payload = {
            "Event": "unsupported",
            "User": {"Name": "private-account"},
            "Item": {"Name": "private-media", "Path": "/private/library/file"},
        }
        with self.assertLogs("integrations.webhooks.emby", level="DEBUG") as logs:
            EmbyWebhookProcessor().process_payload(payload, self.user)
        output = " ".join(logs.output)
        for value in ("private-account", "private-media", "/private/library/file"):
            self.assertNotIn(value, output)
        self.assertIn("item_keys", output)

    @tag("network")
    def test_tv_episode_mark_played(self):
        """Test webhook handles TV episode mark played event."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "ProductionYear": 1994,
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)

        # Verify objects were created
        tv_item = Item.objects.get(media_type=MediaTypes.TV.value, media_id="1668")
        self.assertEqual(tv_item.title, "Friends")

        tv = TV.objects.get(item=tv_item, user=self.user)
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)

        season = Season.objects.get(
            item__media_id="1668",
            item__season_number=1,
        )
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

        episode = Episode.objects.get(
            item__media_id="1668",
            item__season_number=1,
            item__episode_number=1,
        )
        self.assertIsNotNone(episode.end_date)

    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data")
    @patch("app.providers.mal.anime")
    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_anime_episode_mark_played(
        self,
        mock_find,
        mock_tv_with_seasons,
        mock_mal_anime,
        mock_fetch_mapping_data,
    ):
        """Test webhook handles anime episode mark played event."""
        mock_find.return_value = {
            "tv_episode_results": [
                {"show_id": 209867, "season_number": 1, "episode_number": 1},
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": "209867",
            "title": "Frieren: Beyond Journey's End",
            "tvdb_id": 424536,
            "season/1": {"episodes": [{"episode_number": 1}]},
        }
        mock_fetch_mapping_data.return_value = {
            "tvdb_show:424536:s1": {"mal:52991": {"1-28": "1-28"}},
        }
        mock_mal_anime.return_value = {
            "media_id": "52991",
            "title": "Sousou no Frieren",
            "image": "https://example.com/frieren.jpg",
            "max_progress": 28,
        }
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Episode",
                "Name": "The Journey's End",
                "ProductionYear": 2003,
                "ProviderIds": {
                    "Tvdb": "9350138",
                    "Imdb": "tt23861604",
                },
                "SeriesName": "Frieren: Beyond Journey's End",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)

        # Verify anime was created and marked as in progress
        anime = Anime.objects.get(
            item__media_id="52991",
            user=self.user,
        )
        self.assertEqual(anime.status, Status.IN_PROGRESS.value)
        self.assertEqual(anime.progress, 1)

    @tag("network")
    def test_movie_mark_played(self):
        """Test webhook handles movie mark played event."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Imdb": "tt0133093",
                    "Tmdb": "603",
                    "Tvdb": "169",
                    "Official Website": "http://www.warnerbros.com/matrix",
                    "Wikidata": "Q83495",
                    "Wikipedia": "The_Matrix",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }
        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)

        # Verify movie was created and marked as completed
        movie = Movie.objects.get(
            item__media_id="603",
            user=self.user,
        )
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

    @tag("network")
    def test_anime_movie_mark_played(self):
        """Test webhook handles movie mark played event."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Movie",
                "Name": "Perfect Blue",
                "ProductionYear": 1997,
                "ProviderIds": {
                    "Imdb": "tt0156887",
                    "Tmdb": "10494",
                    "Tvdb": "3807",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)

        # Verify movie was created and marked as completed
        movie = Anime.objects.get(
            item__media_id="437",
            user=self.user,
        )
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

    def test_ignored_event_types(self):
        """Test webhook ignores irrelevant event types."""
        payload = {
            "Event": "playback.something_else",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Imdb": "tt0133093",
                    "Tmdb": "603",
                    "Tvdb": "169",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    def test_ignored_media_types(self):
        """Test webhook ignores irrelevant event types."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "SomethingElse",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Imdb": "tt0133093",
                    "Tmdb": "603",
                    "Tvdb": "169",
                    "Official Website": "http://www.warnerbros.com/matrix",
                    "Wikidata": "Q83495",
                    "Wikipedia": "The_Matrix",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    def test_missing_tmdb_id(self):
        """Test webhook handles missing TMDB ID gracefully."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {},
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }
        data = {
            "data": json.dumps(payload),
        }

        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    @tag("network")
    def test_repeated_watch(self):
        """Test webhook handles repeated watches."""
        payload = {
            "Event": "playback.stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Imdb": "tt0133093",
                    "Tmdb": "603",
                    "Tvdb": "169",
                    "Official Website": "http://www.warnerbros.com/matrix",
                    "Wikidata": "Q83495",
                    "Wikipedia": "The_Matrix",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        data = {
            "data": json.dumps(payload),
        }

        # First watch
        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        # Second watch
        response = self.client.post(
            self.url,
            data=data,
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        movie = Movie.objects.filter(item__media_id="603")
        self.assertEqual(movie.count(), 2)
        self.assertEqual(movie[0].status, Status.COMPLETED.value)
        self.assertEqual(movie[1].status, Status.COMPLETED.value)

    def test_extract_external_ids(self):
        """Test extracting external IDs from provider payload."""
        payload = {
            "Event": "playback.something_else",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Tmdb": "603",
                    "Tvdb": "169",
                },
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        expected = {
            "tmdb_id": "603",
            "imdb_id": None,
            "tvdb_id": "169",
        }

        result = EmbyWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)

    def test_extract_external_ids_empty(self):
        """Test handling empty provider payload."""
        payload = {
            "Event": "playback.something_else",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {},
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }

        expected = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
        }

        result = EmbyWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)

    def test_extract_external_ids_missing(self):
        """Test handling missing ProviderIds."""
        payload = {
            "Event": "playback.something_else",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
            },
            "PlaybackInfo": {
                "PlayedToCompletion": True,
            },
        }
        expected = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
        }

        result = EmbyWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)
