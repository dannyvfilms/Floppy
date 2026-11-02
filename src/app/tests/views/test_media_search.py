from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from app.media_list_filters import media_list_entries_for_items
from app.models import (
    TV,
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldType,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
    Tag,
    Video,
)
from app.providers import services
from app.search_views import get_saved_suggestions
from app.templatetags.app_tags import get_search_media_types
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
    def test_video_search_lists_local_videos_without_a_provider_call(self, mock_search):
        """Videos have no provider, so only the user's own library is searched."""
        item = Item.objects.create(
            media_id="vid1",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="The Art of Sourdough",
            image="http://example.com/video.jpg",
        )
        Video.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        response = self.client.get(
            reverse("search"),
            {"media_type": MediaTypes.VIDEO.value, "q": "sourdough"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Art of Sourdough")
        mock_search.assert_not_called()

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
    def test_podcast_online_results_name_the_source_that_answered(self, mock_search):
        """The heading names the source the results came from, with an info tip."""
        result = {
            "media_id": "https://example.com/feed.xml",
            "source": Sources.GPODDER.value,
            "media_type": MediaTypes.PODCAST.value,
            "title": "Das Portal",
            "image": "https://example.com/portal.jpg",
        }
        mock_search.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [dict(result)],
            "fallback_source": Sources.PODCASTINDEX.value,
        }

        response = self.client.get(
            reverse("search")
            + f"?media_type=podcast&q=portal&source={Sources.POCKETCASTS.value}",
        )

        content = response.content.decode()
        self.assertContains(response, "Online Results (Podcast Index)")
        self.assertContains(response, "Pocket Casts had no match for this search")
        self.assertNotIn("Online Results (Pocket Casts)", content)

        # The view rewrites result dicts in place, so give the second search its own.
        mock_search.return_value = {
            "page": 1,
            "total_results": 1,
            "total_pages": 1,
            "results": [dict(result)],
        }
        response = self.client.get(
            reverse("search")
            + f"?media_type=podcast&q=portal&source={Sources.POCKETCASTS.value}",
        )
        self.assertContains(response, "Online Results (Pocket Casts)")
        self.assertContains(response, "These results come from Pocket Casts")

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

    @patch("app.providers.services.search")
    def test_search_not_configured_provider_explains_setup(self, mock_search):
        """A missing key must not read as a transient outage."""
        mock_search.side_effect = services.ProviderNotConfiguredError(
            Sources.IGDB.value,
            "IGDB is not configured. Add your Twitch application's client ID "
            "and secret in Settings → Metadata providers.",
        )

        response = self.client.get(
            reverse("search") + "?media_type=game&q=test",
        )

        self.assertEqual(response.status_code, 200)
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertIn("not configured", str(messages[0]))
        self.assertIn("Settings", str(messages[0]))
        self.assertNotIn("unavailable", str(messages[0]))


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
        Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            season_number=1,
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
        self.assertEqual(response.context["local_results_total"], 1)

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


class AllTypeSearchTests(TestCase):
    """The "All" search type searches the user's whole library, offline (#1160)."""

    def setUp(self):
        """Create a user and log in."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _item(self, media_type, title, media_id, source=Sources.TMDB.value):
        return Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=media_type,
            title=title,
            image="http://example.com/i.jpg",
        )

    def _library(self):
        """A match in several types, each reached a different way."""
        movie = self._item(MediaTypes.MOVIE.value, "Dune Movie", "1")
        Movie.objects.create(user=self.user, item=movie, status=Status.COMPLETED.value)
        collected = self._item(
            MediaTypes.BOOK.value, "Dune Novel", "2", Sources.OPENLIBRARY.value
        )
        CollectionEntry.objects.create(user=self.user, item=collected)
        tagged = self._item(MediaTypes.GAME.value, "Dune Game", "3", Sources.IGDB.value)
        tag = Tag.objects.create(user=self.user, name="sci-fi")
        ItemTag.objects.create(tag=tag, item=tagged)
        return movie, collected, tagged

    @patch("app.providers.services.search")
    def test_all_type_groups_library_matches_without_provider_calls(self, mock_search):
        movie, collected, tagged = self._library()
        self._item(MediaTypes.MOVIE.value, "Dune Untracked", "9")  # in nobody's library
        other = get_user_model().objects.create_user(username="other")
        Movie.objects.create(
            user=other,
            item=self._item(MediaTypes.MOVIE.value, "Dune Other", "8"),
            status=Status.COMPLETED.value,
        )

        response = self.client.get(reverse("search") + "?media_type=all&q=dune")

        self.assertEqual(response.status_code, 200)
        mock_search.assert_not_called()
        groups = {
            group["media_type"]: [r["item"] for r in group["results"]]
            for group in response.context["local_groups"]
        }
        self.assertEqual(
            groups,
            {
                MediaTypes.MOVIE.value: [movie],
                MediaTypes.BOOK.value: [collected],
                MediaTypes.GAME.value: [tagged],
            },
        )
        self.assertContains(response, "Dune Game")

    @patch("app.providers.services.search")
    def test_all_type_is_remembered_as_the_search_type(self, mock_search):
        self.client.get(reverse("search") + "?media_type=all&q=dune")

        self.user.refresh_from_db()
        self.assertEqual(self.user.last_search_type, "all")
        mock_search.assert_not_called()

    def test_all_type_includes_podcasts_and_music(self):
        show = PodcastShow.objects.create(
            podcast_uuid="p1", source=Sources.POCKETCASTS.value, title="Dune Podcast"
        )
        PodcastShowTracker.objects.create(
            user=self.user, show=show, status=Status.IN_PROGRESS.value
        )
        artist = Artist.objects.create(name="Dune Band")
        ArtistTracker.objects.create(user=self.user, artist=artist)

        response = self.client.get(reverse("search") + "?media_type=all&q=dune")

        groups = {g["media_type"]: g for g in response.context["local_groups"]}
        self.assertEqual(
            groups[MediaTypes.PODCAST.value]["results"][0]["item"].title,
            "Dune Podcast",
        )
        self.assertEqual(groups[MediaTypes.MUSIC.value]["artists"][0].artist, artist)

    def test_all_type_skips_disabled_media_types(self):
        self._library()
        self.user.book_enabled = False
        self.user.save()

        response = self.client.get(reverse("search") + "?media_type=all&q=dune")

        self.assertNotIn(
            MediaTypes.BOOK.value,
            [g["media_type"] for g in response.context["local_groups"]],
        )

    def test_all_type_with_no_match_shows_the_empty_state(self):
        response = self.client.get(reverse("search") + "?media_type=all&q=nothing")

        self.assertEqual(response.context["local_groups"], [])
        self.assertContains(response, "Nothing in your library matches")

    def test_search_type_dropdown_offers_all_first(self):
        search_types = get_search_media_types(self.user)

        self.assertEqual(search_types[0], {"display": "All", "value": "all"})
        self.assertIn(MediaTypes.MOVIE.value, [t["value"] for t in search_types])

    def test_suggestions_span_types_and_label_each_with_its_type(self):
        self._library()

        response = self.client.get(
            reverse("search_suggestions") + "?media_type=all&q=dune",
        )

        suggestions = response.context["suggestions"]
        self.assertEqual(
            sorted(s["title"] for s in suggestions),
            ["Dune Game", "Dune Movie", "Dune Novel"],
        )
        self.assertEqual(
            {s["title"]: s["subtitle"] for s in suggestions}["Dune Movie"],
            "Movie",
        )
        self.assertContains(response, "See all library results")

    def test_tagged_untracked_item_is_found_in_a_single_type_search(self):
        _movie, _collected, tagged = self._library()

        suggestions = get_saved_suggestions(self.user, MediaTypes.GAME.value, "dune")

        self.assertEqual([s["title"] for s in suggestions], [tagged.title])

    def test_all_type_includes_tagged_only_podcast_shows(self):
        item = self._item(
            MediaTypes.PODCAST.value,
            "Dune Cast",
            "pc1",
            Sources.POCKETCASTS.value,
        )
        ItemTag.objects.create(
            tag=Tag.objects.create(user=self.user, name="listen"), item=item
        )

        response = self.client.get(reverse("search") + "?media_type=all&q=dune")

        groups = {g["media_type"]: g for g in response.context["local_groups"]}
        self.assertEqual(
            [r["item"] for r in groups[MediaTypes.PODCAST.value]["results"]],
            [item],
        )

    def test_all_type_loads_only_one_page_per_type(self):
        """A common query must not hydrate every match in a large library."""
        for number in range(30):
            Movie.objects.create(
                user=self.user,
                item=self._item(
                    MediaTypes.MOVIE.value, f"Dune {number:02d}", str(number)
                ),
                status=Status.COMPLETED.value,
            )

        with patch(
            "app.search_views.media_list_entries_for_items",
            wraps=media_list_entries_for_items,
        ) as hydrate:
            response = self.client.get(reverse("search") + "?media_type=all&q=dune")

        group = response.context["local_groups"][0]
        self.assertEqual(group["total"], 30)
        self.assertEqual(len(group["results"]), 12)
        self.assertEqual(
            max(len(call.args[1]) for call in hydrate.call_args_list),
            12,
        )

    def test_statusless_media_is_searchable(self):
        """An imported rating with no status is in the library (#1270 gap)."""
        item = self._item(MediaTypes.MOVIE.value, "Dune Rated", "77")
        Movie.objects.create(user=self.user, item=item, status=None, score=7)

        suggestions = get_saved_suggestions(self.user, MediaTypes.MOVIE.value, "dune")

        self.assertEqual([s["title"] for s in suggestions], ["Dune Rated"])

    def test_grouped_anime_is_in_the_anime_library_not_tv(self):
        """Anime tracked as a TV show follows the user's anime library mode."""
        item = self._item(MediaTypes.TV.value, "Dune Anime", "a1")
        item.library_media_type = MediaTypes.ANIME.value
        item.save()
        TV.objects.create(user=self.user, item=item, status=Status.COMPLETED.value)
        CollectionEntry.objects.create(user=self.user, item=item)

        groups = {
            g["media_type"]: g
            for g in self.client.get(
                reverse("search") + "?media_type=all&q=dune",
            ).context["local_groups"]
        }

        self.assertNotIn(MediaTypes.TV.value, groups)
        self.assertEqual(get_saved_suggestions(self.user, "tv", "dune"), [])
        anime = groups[MediaTypes.ANIME.value]["results"][0]
        self.assertEqual(anime["item"], item)
        self.assertEqual(anime["media"].route_media_type, MediaTypes.ANIME.value)


class BarcodeOwnedSearchTests(TestCase):
    """A scanned barcode finds the volumes the user already owns (#809)."""

    def setUp(self):
        """Create a user owning one barcoded manga volume."""
        self.credentials = {"username": "scan", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        group = CollectionFieldGroup.objects.create(user=self.user, name="Shelf")
        self.field = CollectionField.objects.create(
            group=group,
            label="Barcode",
            field_type=CollectionFieldType.TEXT,
            media_types=[MediaTypes.MANGA.value],
        )
        self.item = Item.objects.create(
            media_id="series-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Owned Series",
            image="",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            custom_field_values={str(self.field.id): "978408873621112345"},
        )

    def search(self, query):
        """Return the local library results shown for *query*."""
        with patch(
            "app.providers.services.search",
            return_value={"page": 1, "total_results": 0, "total_pages": 0, "results": []},
        ):
            response = self.client.get(
                reverse("search"),
                {"media_type": "manga", "q": query},
            )
        self.assertEqual(response.status_code, 200)
        return [result["item"] for result in response.context["local_results"]]

    def test_scanned_barcode_finds_the_owned_item(self):
        """The stored barcode carries a supplement the scan does not read."""
        self.assertEqual(self.search("9784088736211"), [self.item])

    def test_hyphens_and_spaces_are_ignored(self):
        """A typed ISBN with separators still matches."""
        self.assertEqual(self.search("978-4-08-873621-1"), [self.item])

    def test_other_barcodes_find_nothing(self):
        """A different barcode does not match."""
        self.assertEqual(self.search("9780000000002"), [])

    def test_titles_are_not_treated_as_barcodes(self):
        """Ordinary text never queries the barcode field."""
        self.assertEqual(self.search("1984"), [])

    def test_other_users_barcodes_never_match(self):
        """Another user's collection is not searched."""
        other = get_user_model().objects.create_user(username="o", password="12345")
        self.client.logout()
        self.client.login(username="o", password="12345")
        self.assertEqual(self.search("9784088736211"), [])
        self.assertTrue(other.is_active)

    def test_camera_button_uses_the_real_comic_issue_type_value(self):
        """The search bar lists each type's own value, so Comic Issues scans too."""
        with patch(
            "app.providers.services.search",
            return_value={"page": 1, "total_results": 0, "total_pages": 0, "results": []},
        ):
            response = self.client.get(
                reverse("search"),
                {"media_type": MediaTypes.COMIC_ISSUE.value, "q": "x"},
            )

        scan_types = f"['book', 'manga', 'comic', '{MediaTypes.COMIC_ISSUE.value}']"
        self.assertContains(response, scan_types)
