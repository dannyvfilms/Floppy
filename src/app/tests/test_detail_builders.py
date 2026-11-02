from django.test import TestCase

from app.detail_builders import (
    _build_detail_link_sections,
    _build_imdb_rating_context,
    _build_mal_rating_context,
    _build_series_graph_data,
)
from app.models import Item, ItemProviderLink, MediaTypes, Sources


class SeriesGraphBuilderTests(TestCase):
    """Focused coverage for the episode graph layout builder."""

    def test_include_unrated_preserves_episode_slots(self):
        """Unrated episodes should keep their grid positions during polling."""
        Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Special 1",
            season_number=0,
            episode_number=1,
            trakt_rating=9.0,
            trakt_rating_count=50,
        )
        Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 1",
            season_number=1,
            episode_number=1,
            trakt_rating=8.0,
            trakt_rating_count=100,
        )
        Item.objects.create(
            media_id="show-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 2",
            season_number=1,
            episode_number=2,
        )

        graph_data = _build_series_graph_data(
            Sources.TMDB.value,
            "show-1",
            use_trakt=True,
            include_unrated=True,
        )

        self.assertIsNotNone(graph_data)
        self.assertEqual([season["label"] for season in graph_data["seasons"]], ["S1"])
        self.assertEqual([row["ep"] for row in graph_data["episode_rows"]], [1, 2])
        self.assertEqual(graph_data["episode_rows"][0]["cells"][0]["score"], 8.0)
        self.assertIsNone(graph_data["episode_rows"][1]["cells"][0]["score"])

    def test_use_imdb_reads_imdb_rating_fields(self):
        Item.objects.create(
            media_id="show-2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode 1",
            season_number=1,
            episode_number=1,
            imdb_rating=9.1,
            imdb_rating_count=1234,
        )

        graph_data = _build_series_graph_data(
            Sources.TMDB.value,
            "show-2",
            use_imdb=True,
        )

        self.assertIsNotNone(graph_data)
        self.assertEqual(graph_data["episode_rows"][0]["cells"][0]["score"], 9.1)
        self.assertEqual(graph_data["episode_rows"][0]["cells"][0]["votes"], 1234)


class ImdbRatingContextTests(TestCase):
    """Focused coverage for the IMDb rating chip context builder."""

    def test_returns_none_without_rating_count(self):
        item = Item.objects.create(
            media_id="movie-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
        )

        self.assertIsNone(_build_imdb_rating_context(item, MediaTypes.MOVIE.value))

    def test_returns_rounded_rating_and_count(self):
        item = Item.objects.create(
            media_id="movie-2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Another Movie",
            imdb_rating=7.88,
            imdb_rating_count=54321,
        )

        context = _build_imdb_rating_context(item, MediaTypes.MOVIE.value)

        self.assertEqual(context, {"rating": 7.8, "rating_count": 54321})

    def test_returns_rounded_rating_and_count_for_season(self):
        item = Item.objects.create(
            media_id="season-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season 1",
            season_number=1,
            imdb_rating=8.0,
            imdb_rating_count=100,
        )

        context = _build_imdb_rating_context(item, MediaTypes.SEASON.value)

        self.assertEqual(context, {"rating": 8.0, "rating_count": 100})

    def test_returns_none_for_unsupported_media_type(self):
        item = Item.objects.create(
            media_id="game-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.GAME.value,
            title="A Game",
            imdb_rating=8.0,
            imdb_rating_count=100,
        )

        self.assertIsNone(_build_imdb_rating_context(item, MediaTypes.GAME.value))


class MalRatingContextTests(TestCase):
    """Focused coverage for the MyAnimeList rating chip context."""

    def test_returns_truncated_one_decimal_rating_for_anime(self):
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            mal_rating=8.78,
            mal_rating_count=1234,
        )

        self.assertEqual(
            _build_mal_rating_context(item, MediaTypes.ANIME.value),
            {"rating": 8.7, "rating_count": 1234},
        )

    def test_returns_none_without_rating_count_or_for_unsupported_media(self):
        unrated = Item.objects.create(
            media_id="52992",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Unrated Anime",
            mal_rating=8.0,
        )
        missing_score = Item.objects.create(
            media_id="52993",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime Without A Score",
            mal_rating_count=100,
        )
        manga = Item.objects.create(
            media_id="119735",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="Manga",
            mal_rating=8.0,
            mal_rating_count=100,
        )

        self.assertIsNone(
            _build_mal_rating_context(unrated, MediaTypes.ANIME.value)
        )
        self.assertIsNone(
            _build_mal_rating_context(missing_score, MediaTypes.ANIME.value)
        )
        self.assertIsNone(_build_mal_rating_context(manga, MediaTypes.MANGA.value))

    def test_supports_grouped_anime_using_the_tv_route(self):
        item = Item.objects.create(
            media_id="tv-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime",
            mal_rating=8.1,
            mal_rating_count=100,
        )

        self.assertEqual(
            _build_mal_rating_context(item, MediaTypes.TV.value),
            {"rating": 8.1, "rating_count": 100},
        )


class DetailLinkSectionsMalTests(TestCase):
    def test_adds_exact_mal_link_for_flat_anime(self):
        item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
        )

        sections = _build_detail_link_sections(
            {
                "source_url": "https://www.themoviedb.org/tv/52991",
                "media_id": "52991",
            },
            MediaTypes.ANIME.value,
            Sources.TMDB.value,
            Sources.TMDB.value,
            item=item,
        )

        external_entries = sections[-1]["entries"]
        self.assertEqual(
            [(entry["label"], entry["url"]) for entry in external_entries],
            [("MyAnimeList", "https://myanimelist.net/anime/52991")],
        )

    def test_does_not_add_mal_link_for_ambiguous_grouped_anime(self):
        item = Item.objects.create(
            media_id="tv-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Ambiguous Anime",
            provider_external_ids={"mal_id": "3"},
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.MAL.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="4",
        )

        sections = _build_detail_link_sections(
            {"source_url": "https://www.thetvdb.com/series/tv-1"},
            MediaTypes.ANIME.value,
            Sources.TVDB.value,
            Sources.TVDB.value,
            item=item,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["title"], "Source")


class OtherBookFormatsTests(TestCase):
    """Cross-format links between a user's ebook and audiobook of one work."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model

        cls.user = get_user_model().objects.create_user(username="reader", password="x")
        cls.other_user = get_user_model().objects.create_user(
            username="other", password="x",
        )

    def _book(self, media_id, source, fmt, user=None, **fields):
        from app.models import Book

        item = Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.BOOK.value,
            title=fields.pop("title", "Dune"),
            authors=fields.pop("authors", ["Frank Herbert"]),
            format=fmt,
            **fields,
        )
        Book.objects.create(user=user or self.user, item=item, status="Planning")
        return item

    def test_links_ebook_and_audiobook_of_same_work(self):
        from app.detail_builders import build_other_book_formats

        ebook = self._book("OL1", Sources.OPENLIBRARY.value, "ebook")
        audio = self._book("abs1", Sources.AUDIOBOOKSHELF.value, "audiobook")

        chips = build_other_book_formats(self.user, ebook)

        self.assertEqual([c["label"] for c in chips], ["Audiobook"])
        self.assertIn("abs1", chips[0]["href"])
        self.assertEqual(
            [c["label"] for c in build_other_book_formats(self.user, audio)],
            ["eBook"],
        )

    def test_matches_on_isbn_despite_title_difference(self):
        from app.detail_builders import build_other_book_formats

        ebook = self._book(
            "OL2", Sources.OPENLIBRARY.value, "ebook", isbn=["978-0-441-17271-9"],
        )
        self._book(
            "abs2",
            Sources.AUDIOBOOKSHELF.value,
            "audiobook",
            title="Dune (Unabridged)",
            authors=[],
            isbn=["9780441172719"],
        )

        self.assertEqual(len(build_other_book_formats(self.user, ebook)), 1)

    def test_same_title_different_author_is_not_linked(self):
        from app.detail_builders import build_other_book_formats

        ebook = self._book("OL3", Sources.OPENLIBRARY.value, "ebook")
        self._book(
            "abs3", Sources.AUDIOBOOKSHELF.value, "audiobook", authors=["Someone Else"],
        )

        self.assertEqual(build_other_book_formats(self.user, ebook), [])

    def test_ignores_other_users_books_and_never_merges_items(self):
        from app.detail_builders import build_other_book_formats

        ebook = self._book("OL4", Sources.OPENLIBRARY.value, "ebook")
        self._book(
            "abs4", Sources.AUDIOBOOKSHELF.value, "audiobook", user=self.other_user,
        )

        self.assertEqual(build_other_book_formats(self.user, ebook), [])
        self.assertEqual(Item.objects.filter(title="Dune").count(), 2)
