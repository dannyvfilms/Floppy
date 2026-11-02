from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import mangabaka, services


def _tag(name, name_path, series_count, **flags):
    return {"name": name, "name_path": name_path, "series_count": series_count, **flags}


def _series(**overrides):
    series = {
        "id": 84926,
        "state": "active",
        "canonical_url": "https://mangabaka.org/series/84926/Berserk",
        "title": "Berserk",
        "cover": {
            "raw": {"url": "https://cdn.mangabaka.org/raw.jpg"},
            "x350": {"x1": "https://cdn.mangabaka.org/350.jpg", "x2": None},
        },
        "authors": ["MIURA Kentarou"],
        "artists": ["MIURA Kentarou"],
        "description": "Guts, a former mercenary.",
        "status": "releasing",
        "type": "manga",
        "rating": 91.46,
        "total_chapters": "380",
        "published": {"start_date": "1989-08-25", "end_date": None},
        "genres": ["action", "boys_love"],
        "tags_v2": [
            _tag("Dark Fantasy", "Themes > Dark Fantasy", 3000),
            _tag("Demons", "Character Types > Demons", 5151),
            _tag("Hero Dies", "Themes > Hero Dies", 4000, is_spoiler=True),
            _tag("Action", "Genres > Action", 9000, is_genre=True),
            _tag("Gore", "Sexual Content > Gore", 5000),
            _tag("Sex Slave", "Character Types > Victims > Sex Slave", 5000),
            _tag("Rare", "Themes > Rare", 10),
            _tag("Ongoing", "Work Info > Ongoing", 9000),
        ],
    }
    series.update(overrides)
    return series


def _search_page(count=1, rows=None, next_page=None):
    return {
        "status": 200,
        "pagination": {"count": count, "page": 1, "limit": 30, "next": next_page},
        "data": [_series()] if rows is None else rows,
    }


def _route(*, series=None, similar=None, related=None):
    """Answer by URL, since one detail page makes several MangaBaka requests."""

    def respond(_provider, _method, url, **_kwargs):
        if url.endswith("/similar"):
            return {"status": 200, "data": similar or []}
        series_id = url.rsplit("/", 1)[1]
        if series_id in (related or {}):
            return {"status": 200, "data": related[series_id]}
        return {"status": 200, "data": series}

    return respond


class MangaBakaProviderTests(TestCase):
    """MangaBaka provider parsing, filters and errors (API mocked)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_parses_results(self, mock_request):
        mock_request.return_value = _search_page(count=61)

        data = mangabaka.search("berserk", 2)

        self.assertEqual(data["page"], 2)
        self.assertEqual(data["total_results"], 61)
        self.assertEqual(
            data["results"],
            [
                {
                    "media_id": "84926",
                    "source": Sources.MANGABAKA.value,
                    "media_type": MediaTypes.MANGA.value,
                    "title": "Berserk",
                    "image": "https://cdn.mangabaka.org/350.jpg",
                    "year": 1989,
                },
            ],
        )
        params = mock_request.call_args.kwargs["params"]
        self.assertEqual(params["q"], "berserk")
        self.assertEqual(params["page"], 2)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_sends_user_agent_and_keeps_mainstream_erotica(self, mock_request):
        mock_request.return_value = _search_page()

        mangabaka.search("berserk", 1)

        kwargs = mock_request.call_args.kwargs
        # MangaBaka 403s the default python-requests User-Agent.
        self.assertEqual(kwargs["headers"], {"User-Agent": "Mozilla/5.0"})
        # Berserk is rated erotica, so that tier must stay visible.
        self.assertEqual(
            kwargs["params"]["content_rating"],
            ["safe", "suggestive", "erotica"],
        )

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_drops_novels_and_explicit_genres(self, mock_request):
        mock_request.return_value = _search_page(
            count=4,
            rows=[
                _series(id=1, title="Manga"),
                _series(id=2, title="Novel", type="novel"),
                _series(id=3, title="Fan work", genres=["doujinshi"]),
                _series(id=4, title="Mystery", genres=["adult", "mystery"]),
            ],
        )

        titles = [row["title"] for row in mangabaka.search("x", 1)["results"]]

        self.assertEqual(titles, ["Manga", "Mystery"])

    @override_settings(MANGABAKA_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_nsfw_setting_drops_the_adult_filter(self, mock_request):
        mock_request.return_value = _search_page(
            rows=[_series(id=3, title="Fan work", genres=["doujinshi"])],
        )

        results = mangabaka.search("berserk", 1)["results"]

        self.assertNotIn("content_rating", mock_request.call_args.kwargs["params"])
        self.assertEqual([row["title"] for row in results], ["Fan work"])

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_cached_per_nsfw_state(self, mock_request):
        mock_request.return_value = _search_page()

        mangabaka.search("probe", 1)
        mangabaka.search("probe", 1)
        with override_settings(MANGABAKA_NSFW=True):
            mangabaka.search("probe", 1)

        self.assertEqual(mock_request.call_count, 2)

    @patch("app.providers.mangabaka.services.api_request")
    def test_blank_search_makes_no_request(self, mock_request):
        data = mangabaka.search("  ", 1)

        self.assertEqual(data["results"], [])
        mock_request.assert_not_called()

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_without_cover_uses_placeholder(self, mock_request):
        page = _search_page()
        page["data"][0]["cover"] = {"raw": {"url": None}, "x350": {"x1": None}}
        page["data"][0]["published"] = {"start_date": None}
        page["data"][0]["year"] = 2001
        mock_request.return_value = page

        result = mangabaka.search("berserk", 1)["results"][0]

        self.assertEqual(result["image"], settings.IMG_NONE)
        self.assertEqual(result["year"], 2001)

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_metadata(self, mock_request):
        mock_request.side_effect = _route(series=_series())

        data = mangabaka.manga("84926")

        self.assertEqual(data["media_id"], "84926")
        self.assertEqual(data["source"], Sources.MANGABAKA.value)
        self.assertEqual(data["source_url"], "https://mangabaka.org/series/84926/Berserk")
        self.assertEqual(data["title"], "Berserk")
        self.assertEqual(data["synopsis"], "Guts, a former mercenary.")
        self.assertEqual(data["genres"], ["Action", "Boys Love"])
        self.assertEqual(data["score"], 9.1)
        self.assertIsNone(data["max_progress"])
        self.assertEqual(data["details"]["format"], "Manga")
        self.assertEqual(data["details"]["status"], "Releasing")
        self.assertEqual(data["details"]["start_date"], "1989-08-25")
        self.assertEqual(data["details"]["authors"], ["MIURA Kentarou"])
        # Spoiler, genre, sexual-content, victim, rare and work-info tags stay
        # out, and the most widely shared theme comes first.
        self.assertEqual(data["details"]["tags"], ["Demons", "Dark Fantasy"])
        self.assertEqual(
            data["authors_full"],
            [
                {
                    "person_id": "MIURA Kentarou",
                    "name": "MIURA Kentarou",
                    "image": settings.IMG_NONE,
                    "role": "Author",
                    "sort_order": 0,
                },
            ],
        )
        self.assertEqual(
            mock_request.call_args_list[0].kwargs["headers"],
            {"User-Agent": "Mozilla/5.0"},
        )
        self.assertEqual(
            mock_request.call_args_list[0].args[2],
            "https://api.mangabaka.org/v1/series/84926",
        )

    @patch("app.providers.mangabaka.services.api_request")
    def test_completed_series_sets_max_progress(self, mock_request):
        mock_request.side_effect = _route(
            series=_series(status="completed", total_chapters="71"),
        )

        self.assertEqual(mangabaka.manga("1")["max_progress"], 71)

    @patch("app.providers.mangabaka.services.api_request")
    def test_sparse_series_still_parses(self, mock_request):
        mock_request.side_effect = _route(
            series=_series(
                description=None,
                rating=None,
                genres=[],
                tags_v2=None,
                authors=None,
                artists=None,
                status="completed",
                total_chapters=None,
            ),
        )

        data = mangabaka.manga("2")

        self.assertEqual(data["synopsis"], "No synopsis available.")
        self.assertIsNone(data["score"])
        self.assertIsNone(data["genres"])
        self.assertIsNone(data["max_progress"])
        self.assertIsNone(data["details"]["tags"])
        self.assertEqual(data["authors_full"], [])
        self.assertIsNone(data["details"]["authors"])

    @patch("app.providers.mangabaka.services.api_request")
    def test_http_error_becomes_provider_error(self, mock_request):
        response = MagicMock(status_code=404)
        mock_request.side_effect = requests.exceptions.HTTPError(response=response)

        with self.assertRaises(services.ProviderAPIError):
            mangabaka.manga("999")

    @patch("app.providers.mangabaka.services.api_request")
    def test_direct_id_lookup_follows_search_filters(self, mock_request):
        cases = [
            (_series(), True, False),
            (_series(type="novel"), False, False),
            # Mainstream seinen such as Berserk is rated erotica.
            (_series(content_rating="erotica"), True, False),
            (_series(content_rating="pornographic"), False, True),
            (_series(genres=["doujinshi"]), False, True),
            (_series(content_rating="suggestive"), True, False),
        ]
        for series, searchable, nsfw_unlocks in cases:
            with self.subTest(type=series["type"], rating=series.get("content_rating")):
                cache.clear()
                mock_request.side_effect = _route(series=series)
                metadata = mangabaka.manga("1")

                self.assertEqual(mangabaka.is_searchable(metadata), searchable)
                with override_settings(MANGABAKA_NSFW=True):
                    self.assertEqual(
                        mangabaka.is_searchable(metadata),
                        searchable or nsfw_unlocks,
                    )

    @patch("app.providers.mangabaka.manga")
    def test_search_by_id_hides_filtered_series(self, mock_manga):
        mock_manga.return_value = {
            "title": "Adult Series",
            "details": {"format": "Manga", "content_rating": "Pornographic"},
        }

        result = services.search_by_id(
            MediaTypes.MANGA.value,
            "84926",
            Sources.MANGABAKA.value,
        )

        self.assertIsNone(result)


class MangaBakaRelatedTests(TestCase):
    """Related series, recommendations and author pages (API mocked)."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_related_and_recommendations(self, mock_request):
        mock_request.side_effect = _route(
            series=_series(
                relationships_v2=[
                    {"relation_type": "sequel", "to_series_id": 7},
                    {"relation_type": "adaptation", "to_series_id": 8},
                ],
            ),
            related={"7": _series(id=7, title="Sequel")},
            similar=[
                {"score": 0.2, "series": _series(id=11, title="Low")},
                {"score": 0.9, "series": _series(id=12, title="High")},
                {"score": 0.8, "series": _series(id=7, title="Sequel")},
                {"score": 0.7, "series": _series(id=13, title="Novel", type="novel")},
                {"score": 0.6, "series": _series(id=14, genres=["hentai"])},
            ],
        )

        related = mangabaka.manga("84926")["related"]

        self.assertEqual(
            [(row["media_id"], row["relation_type"]) for row in related["related_manga"]],
            [("7", "sequel")],
        )
        # Highest score first; the sequel, novel and explicit rows are dropped.
        self.assertEqual(
            [row["title"] for row in related["recommendations"]],
            ["High", "Low"],
        )

    @patch("app.providers.mangabaka.services.api_request")
    def test_related_failure_does_not_break_the_page(self, mock_request):
        def respond(_provider, _method, url, **_kwargs):
            if url.endswith(("/similar", "/7")):
                raise requests.exceptions.HTTPError(response=MagicMock(status_code=500))
            return {
                "status": 200,
                "data": _series(
                    relationships_v2=[{"relation_type": "sequel", "to_series_id": 7}],
                ),
            }

        mock_request.side_effect = respond

        related = mangabaka.manga("84926")["related"]

        self.assertEqual(related, {"related_manga": [], "recommendations": []})

    def test_author_name_variants_start_with_the_credited_name(self):
        variants = mangabaka.author_name_variants("MIURA Kentaro")

        self.assertEqual(variants[0], "MIURA Kentaro")
        self.assertIn("Kentarou MIURA", variants)
        self.assertLessEqual(len(variants), mangabaka.MAX_NAME_VARIANTS)
        self.assertEqual(mangabaka.author_name_variants("Oda"), ["Oda"])

    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_merges_spellings_and_skips_other_people(self, mock_request):
        by_staff = {
            "MIURA Kentaro": [_series(id=1, title="Short", authors=["MIURA Kentaro"], artists=[])],
            "Kentarou MIURA": [
                _series(id=2, title="Long", authors=["Kentarou Miura"], artists=[]),
                # Same surname, different person: an anthology credit.
                _series(
                    id=3,
                    title="Anthology",
                    authors=["Miura Taro"],
                    artists=[],
                ),
                # Already returned under the other spelling.
                _series(id=1, title="Short", authors=["MIURA Kentaro"], artists=[]),
            ],
        }

        def respond(_provider, _method, _url, params=None, **_kwargs):
            return _search_page(rows=by_staff.get(params["staff"], []))

        mock_request.side_effect = respond

        profile = mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual(
            [row["title"] for row in profile["bibliography"]],
            ["Short", "Long"],
        )
        self.assertEqual(profile["name"], "MIURA Kentaro")
        self.assertLessEqual(
            mock_request.call_count,
            mangabaka.MAX_BIBLIOGRAPHY_REQUESTS,
        )

    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_pages_and_respects_the_request_budget(self, mock_request):
        mock_request.return_value = _search_page(
            rows=[_series(authors=["Oda"])],
            next_page=2,
        )

        mangabaka.author_profile("Oda")

        self.assertEqual(
            mock_request.call_count,
            mangabaka.MAX_BIBLIOGRAPHY_REQUESTS,
        )
        self.assertEqual(
            [c.kwargs["params"]["page"] for c in mock_request.call_args_list[:3]],
            [1, 2, 3],
        )
