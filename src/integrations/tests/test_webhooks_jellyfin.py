import json
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings, tag
from django.urls import reverse

from app import live_playback
from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor


class JellyfinWebhookTests(TestCase):
    """Tests for Jellyfin webhook."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "testuser", "token": "test-token"}
        self.user = get_user_model().objects.create_superuser(**self.credentials)
        self.url = reverse("jellyfin_webhook", kwargs={"token": "test-token"})

    def tearDown(self):
        """Clear cached playback state created by webhook tests."""
        live_playback.clear_user_playback_state(self.user.id)

    def test_invalid_token(self):
        """Test webhook with invalid token returns 401."""
        url = reverse("jellyfin_webhook", kwargs={"token": "invalid-token"})
        response = self.client.post(url, data={}, content_type="application/json")
        self.assertEqual(response.status_code, 401)

    @tag("network")
    def test_tv_episode_mark_played(self):
        """Test webhook handles TV episode mark played event."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
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

    @tag("network")
    def test_movie_mark_played(self):
        """Test webhook handles movie mark played event."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        # Verify movie was created and marked as completed
        movie = Movie.objects.get(
            item__media_id="603",
            user=self.user,
        )
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

    @patch("app.providers.tmdb.movie")
    @patch("app.models.Movie.process_status")
    def test_movie_mark_played_uses_jellyfin_last_played_date(
        self,
        _mock_process_status,
        mock_movie,
    ):
        """Completed Jellyfin plays retain Jellyfin's actual completion time."""
        mock_movie.return_value = {
            "title": "The Matrix",
            "image": "",
            "max_progress": 1,
            "provider_external_ids": {},
        }
        payload = {
            "Event": "Stop",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {
                    "Played": True,
                    "LastPlayedDate": "2026-08-06T15:30:00.0000000Z",
                },
            },
        }

        JellyfinWebhookProcessor().process_payload(payload, self.user)

        movie = Movie.objects.get(item__media_id="603", user=self.user)
        self.assertEqual(
            movie.end_date,
            datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
        )

    @tag("network")
    @patch("app.providers.mal.anime")
    @patch("app.providers.tmdb.find")
    def test_anime_movie_mark_played(self, mock_tmdb_find, mock_mal_anime):
        """Test webhook handles movie mark played event."""
        mock_tmdb_find.return_value = {
            "movie_results": [{"id": 10494}],
        }
        mock_mal_anime.return_value = {
            "media_id": "437",
            "title": "Perfect Blue",
            "image": "https://example.com/perfect-blue.jpg",
            "max_progress": 1,
        }
        payload = {
            "Event": "Stop",
            "Item": {
                "Name": "Perfect Blue",
                "ProductionYear": 1997,
                "Type": "Movie",
                "ProviderIds": {"Imdb": "tt0156887"},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        # Verify movie was created and marked as completed
        movie = Anime.objects.get(
            item__media_id="437",
            user=self.user,
        )
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

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
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The Journey's End",
                "ProviderIds": {
                    "Tvdb": "9350138",
                    "Imdb": "tt23861604",
                },
                "UserData": {"Played": True},
                "SeriesName": "Frieren: Beyond Journey's End",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        # Verify anime was created and marked as in progress
        anime = Anime.objects.get(
            item__media_id="52991",
            user=self.user,
        )
        self.assertEqual(anime.status, Status.IN_PROGRESS.value)
        self.assertEqual(anime.progress, 1)

    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data")
    @patch("app.providers.mal.anime")
    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_anime_episode_prefers_tmdb_mapping_for_later_season(
        self,
        mock_find,
        mock_tv_with_seasons,
        mock_mal_anime,
        mock_load_mapping_data,
    ):
        """TMDB grouped-anime mappings should win when TVDB mapping disagrees."""
        mock_find.return_value = {
            "tv_episode_results": [
                {
                    "show_id": 12345,
                    "season_number": 2,
                    "episode_number": 11,
                },
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": "12345",
            "title": "Hell's Paradise",
            "tvdb_id": "402474",
            "season/2": {"episodes": [{"episode_number": 11}]},
        }
        # AniBridge v3 only carries the (wrong for this grouped show) TVDB
        # season mapping; the correct TMDB-season mapping is a stored
        # provider link, which the webhook must prefer.
        mock_load_mapping_data.return_value = {
            "tvdb_show:402474:s2": {"mal:46569": {"1-12": "1-12"}},
        }
        grouped_item = Item.objects.create(
            media_id="60067",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Hell's Paradise 2nd Season",
            image="https://example.com/hells-paradise-s2.jpg",
        )
        ItemProviderLink.objects.create(
            item=grouped_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="12345",
            season_number=2,
            episode_offset=0,
        )

        def mal_side_effect(media_id):
            if str(media_id) == "60067":
                return {
                    "media_id": "60067",
                    "title": "Hell's Paradise 2nd Season",
                    "image": "https://example.com/hells-paradise-s2.jpg",
                    "max_progress": 12,
                }
            if str(media_id) == "46569":
                return {
                    "media_id": "46569",
                    "title": "Hell's Paradise",
                    "image": "https://example.com/hells-paradise-s1.jpg",
                    "max_progress": 13,
                }
            msg = f"Unexpected MAL ID requested: {media_id}"
            raise AssertionError(msg)

        mock_mal_anime.side_effect = mal_side_effect

        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "Episode 11",
                "ProviderIds": {
                    "Tmdb": "12345",
                    "Tvdb": "402474",
                },
                "UserData": {"Played": True},
                "SeriesName": "Hell's Paradise",
                "ParentIndexNumber": 2,
                "IndexNumber": 11,
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        anime = Anime.objects.get(item__media_id="60067", user=self.user)
        self.assertEqual(anime.status, Status.IN_PROGRESS.value)
        self.assertEqual(anime.progress, 11)
        self.assertFalse(
            Anime.objects.filter(item__media_id="46569", user=self.user).exists(),
        )

    @patch("integrations.webhooks.base.BaseWebhookProcessor._handle_tv_episode")
    @patch("integrations.webhooks.anime_mappings.fetch_mapping_data")
    @patch("app.providers.mal.anime")
    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_anime_episode_falls_back_to_tv_when_mapping_progress_is_impossible(
        self,
        mock_find,
        mock_tv_with_seasons,
        mock_mal_anime,
        mock_load_mapping_data,
        mock_handle_tv_episode,
    ):
        """Impossible anime progress should not create a bogus flat anime entry."""
        mock_find.return_value = {
            "tv_episode_results": [
                {
                    "show_id": 12345,
                    "season_number": 2,
                    "episode_number": 11,
                },
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": "12345",
            "title": "Hell's Paradise",
            "tvdb_id": "402474",
            "season/2": {"episodes": [{"episode_number": 11}]},
        }
        # Season 2 mapping only covers episodes 14+, so episode 11 cannot be
        # mapped to a valid MAL episode.
        mock_load_mapping_data.return_value = {
            "tvdb_show:402474:s2": {"mal:46569": {"14-25": "1-12"}},
        }
        mock_mal_anime.return_value = {
            "media_id": "46569",
            "title": "Hell's Paradise",
            "image": "https://example.com/hells-paradise-s1.jpg",
            "max_progress": 13,
        }

        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "Episode 11",
                "ProviderIds": {
                    "Tvdb": "402474",
                },
                "UserData": {"Played": True},
                "SeriesName": "Hell's Paradise",
                "ParentIndexNumber": 2,
                "IndexNumber": 11,
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Anime.objects.count(), 0)
        mock_handle_tv_episode.assert_called_once()
        self.assertEqual(
            mock_handle_tv_episode.call_args.args[:3],
            (12345, 2, 11),
        )

    def test_ignored_event_types(self):
        """Test webhook ignores irrelevant event types."""
        payload = {
            "Event": "SomeOtherEvent",
            "Item": {
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "12345"},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    def test_missing_tmdb_id(self):
        """Test webhook handles missing TMDB ID gracefully."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "ProviderIds": {},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    @patch("app.providers.tvdb.series_tmdb_id")
    @patch("app.providers.tvdb.episode_by_id")
    @patch("integrations.webhooks.base.BaseWebhookProcessor._handle_tv_episode")
    def test_tvdb_episode_id_resolves_to_series_tmdb_id(
        self,
        mock_handle_tv_episode,
        mock_episode_by_id,
        mock_series_tmdb_id,
        mock_tmdb_find,
        mock_tv_with_seasons,
    ):
        """Jellyfin episode TVDB IDs should resolve through their series."""
        self.user.anime_enabled = False
        self.user.save(update_fields=["anime_enabled"])
        mock_tmdb_find.return_value = {
            "tv_episode_results": [],
            "tv_results": [],
        }
        mock_episode_by_id.return_value = {
            "episode_id": "11821802",
            "series_id": "407407",
            "season_number": 1,
            "episode_number": 3,
        }
        mock_series_tmdb_id.return_value = "124428"
        mock_tv_with_seasons.return_value = {
            "tvdb_id": "407407",
            "title": "B&B Vol Liefde",
            "season/1": {"episodes": []},
        }
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "Episode 3",
                "SeriesName": "B&B Vol Liefde",
                "ParentIndexNumber": 1,
                "IndexNumber": 3,
                "ProviderIds": {"Tvdb": "11821802"},
                "UserData": {"Played": True},
            },
        }

        processor = JellyfinWebhookProcessor()
        ids = processor._extract_external_ids(payload)
        processor._process_media(payload, self.user, ids)

        mock_handle_tv_episode.assert_called_once_with(
            "124428",
            1,
            3,
            payload,
            self.user,
        )
        mock_series_tmdb_id.assert_called_once_with("407407")

    @tag("network")
    def test_mark_unplayed(self):
        """Test webhook handles not finished events."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": False},
            },
        }
        self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        movie = Movie.objects.get(item__media_id="603")
        self.assertEqual(movie.progress, 0)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)

    def test_mark_played_event_ignored_when_disabled(self):
        """Test MarkPlayed events are ignored unless opted in by the user."""
        self.assertFalse(self.user.jellyfin_mark_played_enabled)
        payload = {
            "Event": "MarkPlayed",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    @tag("network")
    def test_mark_played_event_marks_movie_completed_when_enabled(self):
        """Test MarkPlayed events mark a movie as completed once opted in."""
        self.user.jellyfin_mark_played_enabled = True
        self.user.save(update_fields=["jellyfin_mark_played_enabled"])

        payload = {
            "Event": "MarkPlayed",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": False},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        movie = Movie.objects.get(item__media_id="603", user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

    @tag("network")
    def test_mark_unplayed_event_ignored_when_disabled(self):
        """Test MarkUnplayed events are ignored unless opted in by the user."""
        self.assertFalse(self.user.jellyfin_mark_unplayed_enabled)

        stop_payload = {
            "Event": "Stop",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": True},
            },
        }
        self.client.post(
            self.url,
            data=json.dumps(stop_payload),
            content_type="application/json",
        )
        self.assertEqual(Movie.objects.count(), 1)

        mark_unplayed_payload = dict(stop_payload, Event="MarkUnplayed")
        response = self.client.post(
            self.url,
            data=json.dumps(mark_unplayed_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 1)

    @tag("network")
    def test_mark_unplayed_event_deletes_movie_when_enabled(self):
        """Test MarkUnplayed events delete the tracked movie once opted in."""
        self.user.jellyfin_mark_unplayed_enabled = True
        self.user.save(update_fields=["jellyfin_mark_unplayed_enabled"])

        stop_payload = {
            "Event": "Stop",
            "Item": {
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": True},
            },
        }
        self.client.post(
            self.url,
            data=json.dumps(stop_payload),
            content_type="application/json",
        )
        self.assertEqual(Movie.objects.count(), 1)

        mark_unplayed_payload = dict(stop_payload, Event="MarkUnplayed")
        response = self.client.post(
            self.url,
            data=json.dumps(mark_unplayed_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movie.objects.count(), 0)

    @tag("network")
    def test_mark_unplayed_event_deletes_episode_when_enabled(self):
        """Test MarkUnplayed events delete the tracked episode once opted in."""
        self.user.jellyfin_mark_unplayed_enabled = True
        self.user.save(update_fields=["jellyfin_mark_unplayed_enabled"])

        stop_payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "UserData": {"Played": True},
            },
        }
        self.client.post(
            self.url,
            data=json.dumps(stop_payload),
            content_type="application/json",
        )
        episode = Episode.objects.get(
            item__media_id="1668",
            item__season_number=1,
            item__episode_number=1,
        )
        self.assertIsNotNone(episode)

        mark_unplayed_payload = dict(stop_payload, Event="MarkUnplayed")
        response = self.client.post(
            self.url,
            data=json.dumps(mark_unplayed_payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Episode.objects.filter(
                item__media_id="1668",
                item__season_number=1,
                item__episode_number=1,
            ).exists(),
        )

    @tag("network")
    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_tv_episode_uses_existing_tvdb_tracked_item(
        self,
        mock_find,
        mock_tv_with_seasons,
    ):
        """Webhook scrobble lands on an existing TVDB-tracked show rather than
        creating a duplicate TMDB-sourced item.
        """
        tvdb_show_id = "76669"
        tmdb_show_id = "1668"

        # Simulate a user who already tracks Friends via TVDB
        tvdb_item = Item.objects.create(
            media_id=tvdb_show_id,
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
            image="https://example.com/friends.jpg",
        )
        TV.objects.create(
            item=tvdb_item, user=self.user, status=Status.IN_PROGRESS.value
        )
        ItemProviderLink.objects.create(
            item=tvdb_item,
            provider=Sources.TVDB.value,
            provider_media_id=tvdb_show_id,
            provider_media_type=MediaTypes.TV.value,
        )

        mock_find.return_value = {
            "tv_episode_results": [
                {"show_id": int(tmdb_show_id), "season_number": 1, "episode_number": 1},
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": tmdb_show_id,
            "title": "Friends",
            "image": "https://example.com/friends.jpg",
            "tvdb_id": tvdb_show_id,
            "provider_external_ids": {"tmdb_id": tmdb_show_id, "tvdb_id": tvdb_show_id},
            "season/1": {
                "season_number": 1,
                "season_title": "Season 1",
                "synopsis": "",
                "image": "https://example.com/friends-s1.jpg",
                "max_progress": 24,
                "episodes": [
                    {
                        "episode_number": 1,
                        "runtime": 22,
                        "air_date": None,
                        "still_path": None,
                        "name": "The Pilot",
                        "overview": "",
                    }
                ],
                "details": {"episodes": 24},
                "providers": {},
            },
        }

        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The Pilot",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "ProviderIds": {"Tvdb": tvdb_show_id},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        # No new TMDB-sourced TV item should have been created
        self.assertFalse(
            Item.objects.filter(
                source=Sources.TMDB.value, media_type=MediaTypes.TV.value
            ).exists(),
        )

        # Season and episode items should be under the existing TVDB item
        season_item = Item.objects.get(
            source=Sources.TVDB.value,
            media_id=tvdb_show_id,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
        )
        episode = Episode.objects.get(
            related_season__item=season_item,
        )
        self.assertIsNotNone(episode.end_date)

    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_tv_and_season_provider_links_ignore_episode_level_ids(
        self,
        mock_find,
        mock_tv_with_seasons,
    ):
        """TV/Season provider links must use the validated show-level tvdb_id.

        Never the per-episode tvdb/imdb ids from the webhook payload
        (issue #326).
        """
        tmdb_show_id = "1668"
        show_level_tvdb_id = "76669"
        episode_tvdb_id = "303821"
        episode_imdb_id = "tt0583459"

        mock_find.return_value = {
            "tv_episode_results": [
                {"show_id": int(tmdb_show_id), "season_number": 1, "episode_number": 1},
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": tmdb_show_id,
            "title": "Friends",
            "image": "https://example.com/friends.jpg",
            "tvdb_id": show_level_tvdb_id,
            "season/1": {
                "season_number": 1,
                "season_title": "Season 1",
                "synopsis": "",
                "image": "https://example.com/friends-s1.jpg",
                "max_progress": 24,
                "episodes": [
                    {
                        "episode_number": 1,
                        "runtime": 22,
                        "air_date": None,
                        "still_path": None,
                        "name": "The Pilot",
                        "overview": "",
                    },
                ],
                "details": {"episodes": 24},
                "providers": {},
            },
        }

        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The Pilot",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "ProviderIds": {"Tvdb": episode_tvdb_id, "Imdb": episode_imdb_id},
                "UserData": {"Played": True},
            },
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        tv_item = Item.objects.get(
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            media_id=tmdb_show_id,
        )
        tv_tvdb_link = ItemProviderLink.objects.get(
            item=tv_item,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.TV.value,
        )
        self.assertEqual(tv_tvdb_link.provider_media_id, show_level_tvdb_id)
        self.assertNotEqual(tv_tvdb_link.provider_media_id, episode_tvdb_id)
        self.assertNotEqual(
            tv_item.provider_external_ids.get("imdb_id"),
            episode_imdb_id,
        )

        season_item = Item.objects.get(
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            media_id=tmdb_show_id,
            season_number=1,
        )
        self.assertFalse(
            ItemProviderLink.objects.filter(
                item=season_item,
                provider=Sources.TVDB.value,
                provider_media_type=MediaTypes.SEASON.value,
            ).exists(),
        )
        self.assertNotEqual(
            season_item.provider_external_ids.get("imdb_id"),
            episode_imdb_id,
        )

    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_second_episode_of_tracked_season_does_not_duplicate_season_item(
        self,
        mock_find,
        mock_tv_with_seasons,
    ):
        """A second played episode of a tracked season must reuse that season.

        Even with a different per-episode TVDB/IMDB id (as Jellyfin reports),
        it must not corrupt or duplicate the Season item (issue #326).
        """
        tmdb_show_id = "1668"
        show_level_tvdb_id = "76669"

        def find_side_effect(ext_id, ext_type):
            episode_number = 1 if ext_id == "303821" else 2
            return {
                "tv_episode_results": [
                    {
                        "show_id": int(tmdb_show_id),
                        "season_number": 1,
                        "episode_number": episode_number,
                    },
                ],
                "tv_results": [],
            }

        mock_find.side_effect = find_side_effect
        mock_tv_with_seasons.return_value = {
            "media_id": tmdb_show_id,
            "title": "Friends",
            "image": "https://example.com/friends.jpg",
            "tvdb_id": show_level_tvdb_id,
            "season/1": {
                "season_number": 1,
                "season_title": "Season 1",
                "synopsis": "",
                "image": "https://example.com/friends-s1.jpg",
                "max_progress": 24,
                "episodes": [
                    {
                        "episode_number": 1,
                        "runtime": 22,
                        "air_date": None,
                        "still_path": None,
                        "name": "The Pilot",
                        "overview": "",
                    },
                    {
                        "episode_number": 2,
                        "runtime": 22,
                        "air_date": None,
                        "still_path": None,
                        "name": "The One with the Sonogram at the End",
                        "overview": "",
                    },
                ],
                "details": {"episodes": 24},
                "providers": {},
            },
        }

        def make_payload(episode_number, name, tvdb_id, imdb_id):
            return {
                "Event": "Stop",
                "Item": {
                    "Type": "Episode",
                    "Name": name,
                    "SeriesName": "Friends",
                    "ParentIndexNumber": 1,
                    "IndexNumber": episode_number,
                    "ProviderIds": {"Tvdb": tvdb_id, "Imdb": imdb_id},
                    "UserData": {"Played": True},
                },
            }

        with self.assertNoLogs("app.db_retry", level="WARNING"):
            response_1 = self.client.post(
                self.url,
                data=json.dumps(
                    make_payload(1, "The Pilot", "303821", "tt0583459"),
                ),
                content_type="application/json",
            )
            response_2 = self.client.post(
                self.url,
                data=json.dumps(
                    make_payload(
                        2,
                        "The One with the Sonogram at the End",
                        "303822",
                        "tt0583460",
                    ),
                ),
                content_type="application/json",
            )

        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 200)

        self.assertEqual(
            Item.objects.filter(
                media_type=MediaTypes.SEASON.value,
                media_id=tmdb_show_id,
                season_number=1,
            ).count(),
            1,
        )
        season_item = Item.objects.get(
            media_type=MediaTypes.SEASON.value,
            media_id=tmdb_show_id,
            season_number=1,
        )
        self.assertEqual(
            Episode.objects.filter(related_season__item=season_item).count(),
            2,
        )

    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_webhook_heals_preexisting_stray_season_item_and_avoids_conflict(
        self,
        mock_find,
        mock_tv_with_seasons,
    ):
        """Reproduces the GitHub issue #326 follow-up report exactly.

        A pre-existing orphaned stray Season Item (different
        library_media_type bucket, no tracking data of its own) already sits
        in the DB for the same show/season as the real, tracked one. A
        webhook call must land on the real item, self-heal the stray away,
        and must NOT log a "Persistent IntegrityError" warning for the
        primary TMDB provider link — the exact symptom from the follow-up
        comment on issue #326.
        """
        tmdb_show_id = "1405"

        tv_item = Item.objects.create(
            media_id=tmdb_show_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Dexter",
            image="https://example.com/dexter.jpg",
        )
        TV.objects.create(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)

        canonical_season_item = Item.objects.create(
            media_id=tmdb_show_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.SEASON.value,
            title="Dexter",
            image="",
        )
        ItemProviderLink.objects.create(
            item=canonical_season_item,
            provider=Sources.TMDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            provider_media_id=tmdb_show_id,
            season_number=3,
        )
        # Orphaned stray from the earlier corruption — no Season/Episode data.
        Item.objects.create(
            media_id=tmdb_show_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=3,
            library_media_type=MediaTypes.ANIME.value,
            title="Dexter",
            image="",
        )

        mock_find.return_value = {
            "tv_episode_results": [
                {"show_id": int(tmdb_show_id), "season_number": 3, "episode_number": 8},
            ],
            "tv_results": [],
        }
        mock_tv_with_seasons.return_value = {
            "media_id": tmdb_show_id,
            "title": "Dexter",
            "image": "https://example.com/dexter.jpg",
            "tvdb_id": "385787",
            "season/3": {
                "season_number": 3,
                "season_title": "Season 3",
                "synopsis": "",
                "image": "https://example.com/dexter-s3.jpg",
                "max_progress": 12,
                "episodes": [
                    {
                        "episode_number": 8,
                        "runtime": 51,
                        "air_date": None,
                        "still_path": None,
                        "name": "Go Your Own Way",
                        "overview": "",
                    },
                ],
                "details": {"episodes": 12},
                "providers": {},
            },
        }

        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "Go Your Own Way",
                "SeriesName": "Dexter",
                "ParentIndexNumber": 3,
                "IndexNumber": 8,
                "ProviderIds": {"Tvdb": "385783", "Imdb": "tt1242117"},
                "UserData": {"Played": True},
            },
        }

        with self.assertNoLogs("app.db_retry", level="WARNING"):
            response = self.client.post(
                self.url,
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Item.objects.filter(
                media_id=tmdb_show_id,
                media_type=MediaTypes.SEASON.value,
                season_number=3,
            ).count(),
            1,
        )
        self.assertTrue(
            Item.objects.filter(pk=canonical_season_item.pk).exists(),
        )
        episode = Episode.objects.get(
            item__media_id=tmdb_show_id,
            item__season_number=3,
            item__episode_number=8,
        )
        self.assertIsNotNone(episode.end_date)

    @tag("network")
    def test_repeated_watch(self):
        """Test webhook handles repeated watches."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "ProductionYear": 1999,
                "Name": "The Matrix",
                "ProviderIds": {"Tmdb": "603"},
                "UserData": {"Played": True},
            },
        }

        # First watch
        self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Second watch
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        movie = Movie.objects.filter(item__media_id="603")
        self.assertEqual(movie.count(), 2)
        self.assertEqual(movie[0].status, Status.COMPLETED.value)
        self.assertEqual(movie[1].status, Status.COMPLETED.value)

    def test_extract_external_ids(self):
        """Test extracting external IDs from provider payload."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {
                    "Tmdb": "603",
                    "Tvdb": "169",
                },
            },
        }

        expected = {
            "tmdb_id": "603",
            "imdb_id": None,
            "tvdb_id": "169",
        }

        result = JellyfinWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)

    def test_extract_external_ids_empty(self):
        """Test handling empty provider payload."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
                "ProviderIds": {},
            },
        }

        expected = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
        }

        result = JellyfinWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)

    def test_extract_external_ids_missing(self):
        """Test handling missing ProviderIds."""
        payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Movie",
                "Name": "The Matrix",
                "ProductionYear": 1999,
            },
        }
        expected = {
            "tmdb_id": None,
            "imdb_id": None,
            "tvdb_id": None,
        }

        result = JellyfinWebhookProcessor()._extract_external_ids(payload)
        if result != expected:
            msg = f"Expected {expected}, got {result}"
            raise AssertionError(msg)

    @patch("app.providers.tmdb.find")
    def test_play_event_stores_live_playback_state(self, mock_find):
        """Play events should create live playback state for the home card."""
        mock_find.return_value = {
            "tv_episode_results": [
                {
                    "show_id": 1668,
                    "season_number": 1,
                    "episode_number": 1,
                },
            ],
            "tv_results": [],
        }

        payload = {
            "Event": "Play",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "Id": "jf-episode-1",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "RunTimeTicks": 26660000000,
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "UserData": {"Played": False},
            },
            "PlaybackPositionTicks": 14470000000,
        }

        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

        state = live_playback.get_user_playback_state(self.user.id)
        self.assertIsNotNone(state)
        self.assertEqual(state["media_type"], MediaTypes.EPISODE.value)
        self.assertEqual(state["media_id"], "1668")
        self.assertEqual(state["status"], live_playback.PLAYBACK_STATUS_PLAYING)
        self.assertEqual(state["season_number"], 1)
        self.assertEqual(state["episode_number"], 1)
        self.assertEqual(state["duration_seconds"], 2666)
        self.assertEqual(state["view_offset_seconds"], 1447)

    @patch("app.providers.tmdb.find")
    def test_pause_and_stop_events_update_live_playback_state(self, mock_find):
        """Pause should keep card state; stop should transition to stopped."""
        mock_find.return_value = {
            "tv_episode_results": [
                {
                    "show_id": 1668,
                    "season_number": 1,
                    "episode_number": 1,
                },
            ],
            "tv_results": [],
        }

        play_payload = {
            "Event": "Play",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "Id": "jf-episode-2",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "RunTimeTicks": 26660000000,
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "UserData": {"Played": False},
            },
            "PlaybackPositionTicks": 6000000000,
        }
        pause_payload = {
            "Event": "Pause",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "Id": "jf-episode-2",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "RunTimeTicks": 26660000000,
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "UserData": {"Played": False},
            },
            "PlaybackPositionTicks": 7210000000,
        }
        stop_payload = {
            "Event": "Stop",
            "Item": {
                "Type": "Episode",
                "Name": "The One Where Monica Gets a Roommate",
                "Id": "jf-episode-2",
                "SeriesName": "Friends",
                "ParentIndexNumber": 1,
                "IndexNumber": 1,
                "ProviderIds": {
                    "Tvdb": "303821",
                    "Imdb": "tt0583459",
                },
                "UserData": {"Played": True},
            },
        }

        # Play
        play_response = self.client.post(
            self.url,
            data=json.dumps(play_payload),
            content_type="application/json",
        )
        self.assertEqual(play_response.status_code, 200)

        # Pause
        pause_response = self.client.post(
            self.url,
            data=json.dumps(pause_payload),
            content_type="application/json",
        )
        self.assertEqual(pause_response.status_code, 200)

        paused_state = live_playback.get_user_playback_state(self.user.id)
        self.assertIsNotNone(paused_state)
        self.assertEqual(
            paused_state["status"],
            live_playback.PLAYBACK_STATUS_PAUSED,
        )
        self.assertEqual(paused_state["view_offset_seconds"], 721)

        # Stop
        stop_response = self.client.post(
            self.url,
            data=json.dumps(stop_payload),
            content_type="application/json",
        )
        self.assertEqual(stop_response.status_code, 200)

        stopped_state = live_playback.get_user_playback_state(self.user.id)
        self.assertIsNotNone(stopped_state)
        self.assertEqual(
            stopped_state["status"],
            live_playback.PLAYBACK_STATUS_STOPPED,
        )
