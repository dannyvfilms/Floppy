from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    CollectionEntry,
    Item,
    MediaTypes,
    Movie,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)
from app.providers import services
from app.search_views import get_saved_suggestions
from users.models import MetadataSourceDefaultChoices


class MediaSearchViewTests(TestCase):
    """Test the media search view."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("app.providers.services.search")
    def test_media_search_view(self, mock_search):
        """Test the media search view."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "238",
                    "title": "Test Movie",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/image.jpg",
                },
            ],
        }

        response = self.client.get(
            reverse("search") + "?media_type=movie&q=test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/search.html")

        self.user.refresh_from_db()
        self.assertEqual(self.user.last_search_type, MediaTypes.MOVIE.value)

        mock_search.assert_called_once_with(
            MediaTypes.MOVIE.value,
            "test",
            1,
            Sources.TMDB.value,
            language="en",
            user=self.user,
        )

    @patch("app.providers.services.search")
    def test_search_result_track_modal_is_cloaked(self, mock_search):
        """The track modal must not flash before Alpine hides it.

        media_card_list.html's overlay is a full-screen
        `fixed inset-0 bg-black/50` div; without x-cloak it renders visible
        until Alpine boots and applies x-show="trackOpen".
        """
        mock_search.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [
                {
                    "media_id": "238",
                    "title": "Test Movie",
                    "media_type": MediaTypes.MOVIE.value,
                    "source": Sources.TMDB.value,
                    "image": "http://example.com/image.jpg",
                },
            ],
        }

        response = self.client.get(
            reverse("search") + "?media_type=movie&q=test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.content.decode(),
            r'x-show="trackOpen"[^>]*\sx-cloak\b',
        )

    @patch("app.providers.services.search")
    def test_podcast_local_result_keeps_show_source(self, mock_search):
        """Local podcast search results must not be mislabeled as Pocket Casts."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        show = PodcastShow.objects.create(
            podcast_uuid="gp_abc123",
            source=Sources.GPODDER.value,
            title="Gpodder Show",
        )
        PodcastShowTracker.objects.create(
            user=self.user, show=show, status=Status.IN_PROGRESS.value
        )

        response = self.client.get(
            reverse("search") + "?media_type=podcast&q=Gpodder",
        )

        self.assertEqual(response.status_code, 200)
        local_results = response.context["local_results"]
        self.assertEqual(len(local_results), 1)
        self.assertEqual(local_results[0]["item"].source, Sources.GPODDER.value)

    @patch("app.providers.services.search")
    def test_music_search_view_uses_shared_template(
        self,
        mock_search,
    ):
        """Music search should render grouped artist/album sections."""
        artist = Artist.objects.create(name="Pentatonix")
        album = Album.objects.create(
            title="Evergreen",
            artist=artist,
            image="http://example.com/local-album.jpg",
        )
        ArtistTracker.objects.create(user=self.user, artist=artist, score=8.5)
        AlbumTracker.objects.create(user=self.user, album=album, score=9.0)

        mock_search.return_value = {
            "artists": [
                {
                    "artist_id": "mb-artist-1",
                    "name": "Pentatonix",
                    "type": "Group",
                    "begin_year": "2011",
                    "disambiguation": "",
                    "image": "http://example.com/remote-artist.jpg",
                },
            ],
            "releases": [
                {
                    "release_id": "mb-release-1",
                    "title": "A Pentatonix Christmas",
                    "artist_name": "Pentatonix",
                    "release_date": "2016-10-21",
                    "image": "http://example.com/remote-album.jpg",
                },
            ],
            "tracks": {
                "page": 1,
                "total_results": 0,
                "total_pages": 0,
                "results": [],
            },
        }

        response = self.client.get(
            reverse("search") + "?media_type=music&q=Pentatonix",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/search.html")
        self.assertContains(response, "In Your Library")
        self.assertContains(response, "Online Results")
        self.assertContains(response, "Evergreen")
        self.assertContains(response, "A Pentatonix Christmas")
        self.assertContains(response, "Pentatonix")
        self.assertContains(
            response,
            reverse(
                "music_artist_details",
                kwargs={
                    "artist_id": artist.id,
                    "artist_slug": "pentatonix",
                },
            ),
        )
        self.assertContains(
            response,
            reverse(
                "music_album_details",
                kwargs={
                    "artist_id": artist.id,
                    "artist_slug": "pentatonix",
                    "album_id": album.id,
                    "album_slug": "evergreen",
                },
            ),
        )
        self.assertContains(response, "http://example.com/remote-artist.jpg")
        self.assertContains(response, "http://example.com/remote-album.jpg")
        self.assertNotIn("Tracks</h3>", response.content.decode())

        mock_search.assert_called_once_with(
            MediaTypes.MUSIC.value,
            "Pentatonix",
            1,
            Sources.MUSICBRAINZ.value,
            language="en",
            user=self.user,
        )

    @patch("app.providers.services.search")
    def test_music_local_album_search_matches_artist_name(self, mock_search):
        """Music local albums should include artist-name matches."""
        artist = Artist.objects.create(name="Pentatonix")
        album = Album.objects.create(title="The Lucky Ones", artist=artist)
        AlbumTracker.objects.create(user=self.user, album=album)

        mock_search.return_value = {
            "artists": [],
            "releases": [],
            "tracks": {
                "page": 1,
                "total_results": 0,
                "total_pages": 0,
                "results": [],
            },
        }

        response = self.client.get(
            reverse("search") + "?media_type=music&q=Pentatonix",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Lucky Ones")

    @override_settings(TVDB_API_KEY="test-tvdb-key")
    @patch("app.providers.services.search")
    def test_anime_search_defaults_to_user_metadata_provider(self, mock_search):
        """Anime search should honor the user's configured default metadata source."""
        self.user.anime_metadata_source_default = MetadataSourceDefaultChoices.TVDB
        self.user.save(update_fields=["anime_metadata_source_default"])
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(
            reverse("search") + "?media_type=anime&q=chainsaw",
        )

        self.assertEqual(response.status_code, 200)
        mock_search.assert_called_once_with(
            MediaTypes.ANIME.value,
            "chainsaw",
            1,
            Sources.TVDB.value,
            language="en",
            user=self.user,
        )

    @override_settings(HARDCOVER_API="")
    @patch("app.providers.services.search")
    def test_book_search_falls_back_to_open_library(self, mock_search):
        """Book search must work out of the box without a Hardcover key (#1025)."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(reverse("search") + "?media_type=book&q=quo+vadis")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_search.call_args.args[3], Sources.OPENLIBRARY.value)
        self.assertNotIn(
            Sources.HARDCOVER,
            response.context["source_options"],
        )

    @override_settings(HARDCOVER_API="")
    @patch("app.providers.services.search")
    def test_an_explicit_hardcover_source_is_coerced(self, mock_search):
        """A bookmarked ?source=hardcover URL must not resurrect the dead path."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }

        response = self.client.get(
            reverse("search") + "?media_type=book&q=quo+vadis&source=hardcover",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_search.call_args.args[3], Sources.OPENLIBRARY.value)

    @patch("app.providers.services.search")
    def test_search_uses_interactive_request_scope(self, mock_search):
        """Rate-limit retries must fail fast, not block the request (#1001)."""

        def assert_interactive(*args, **kwargs):
            self.assertTrue(services._interactive_request.get())
            return {
                "page": 1,
                "total_results": 0,
                "total_pages": 0,
                "results": [],
            }

        mock_search.side_effect = assert_interactive

        response = self.client.get(
            reverse("search") + "?media_type=book&q=test",
        )

        self.assertEqual(response.status_code, 200)
        mock_search.assert_called_once()
        self.assertFalse(services._interactive_request.get())

    @patch("app.providers.services.search")
    def test_search_provider_error_renders_page_with_message(self, mock_search):
        """A provider failure (e.g. exhausted rate-limit retries) must not 500 (#1001)."""
        mock_search.side_effect = services.ProviderAPIError(
            Sources.HARDCOVER.value, Exception("boom")
        )

        response = self.client.get(
            reverse("search") + "?media_type=book&q=test",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "app/search.html")
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertIn("Hardcover", str(messages[0]))
        self.assertIn("unavailable", str(messages[0]))


class CollectedItemSearchTests(TestCase):
    """Search covers items in the user's Collection, not only tracked ones (#1270)."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _collect(self, **item_fields):
        item = Item.objects.create(image="http://example.com/i.jpg", **item_fields)
        CollectionEntry.objects.create(user=self.user, item=item)
        return item

    @patch("app.providers.services.search")
    def test_collected_untracked_movie_is_a_local_result(self, mock_search):
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        item = self._collect(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        other_user = get_user_model().objects.create_user(username="other")
        CollectionEntry.objects.create(
            user=other_user,
            item=Item.objects.create(
                media_id="604",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="The Matrix Reloaded",
                image="http://example.com/i.jpg",
            ),
        )

        response = self.client.get(reverse("search") + "?media_type=movie&q=matrix")

        self.assertEqual(
            [result["item"] for result in response.context["local_results"]],
            [item],
        )
        self.assertEqual(response.context["local_results_total"], 1)

    @patch("app.providers.services.search")
    def test_collected_episode_surfaces_its_show(self, mock_search):
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        show = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="http://example.com/i.jpg",
        )
        self._collect(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Breaking Bad",
            season_number=1,
            episode_number=1,
        )

        response = self.client.get(reverse("search") + "?media_type=tv&q=breaking")

        self.assertEqual(
            [result["item"] for result in response.context["local_results"]],
            [show],
        )

    @patch("app.providers.services.search")
    def test_tracked_and_collected_item_is_listed_once(self, mock_search):
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        item = self._collect(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        Movie.objects.create(user=self.user, item=item, status=Status.COMPLETED.value)

        response = self.client.get(reverse("search") + "?media_type=movie&q=matrix")

        self.assertEqual(len(response.context["local_results"]), 1)
        self.assertIsNotNone(response.context["local_results"][0]["media"])

    def test_collected_untracked_movie_is_suggested(self):
        self._collect(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )

        suggestions = get_saved_suggestions(self.user, MediaTypes.MOVIE.value, "matrix")

        self.assertEqual([s["title"] for s in suggestions], ["The Matrix"])

    def test_collected_match_sorts_ahead_of_tracked_before_the_limit(self):
        tracked = Item.objects.create(
            media_id="604",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix Reloaded",
            image="http://example.com/i.jpg",
        )
        Movie.objects.create(
            user=self.user, item=tracked, status=Status.COMPLETED.value
        )
        self._collect(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )

        suggestions = get_saved_suggestions(
            self.user, MediaTypes.MOVIE.value, "matrix", limit=1
        )

        self.assertEqual([s["title"] for s in suggestions], ["The Matrix"])

    @patch("app.providers.services.search")
    def test_large_episode_collection_still_returns_results(self, mock_search):
        """Many collected series must not blow SQLite's expression limits."""
        mock_search.return_value = {
            "page": 1,
            "total_results": 0,
            "total_pages": 0,
            "results": [],
        }
        shows = Item.objects.bulk_create(
            Item(
                media_id=str(1000 + n),
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Show {n}",
                image="http://example.com/i.jpg",
            )
            for n in range(1200)
        )
        episodes = Item.objects.bulk_create(
            Item(
                media_id=show.media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=show.title,
                image="http://example.com/i.jpg",
                season_number=1,
                episode_number=1,
            )
            for show in shows
        )
        CollectionEntry.objects.bulk_create(
            CollectionEntry(user=self.user, item=episode) for episode in episodes
        )

        response = self.client.get(reverse("search") + "?media_type=tv&q=Show 11")

        self.assertEqual(response.context["local_results_total"], 111)
        self.assertEqual(len(response.context["local_results"]), 24)
