from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import mangabaka, services

SEARCH_ITEM = {
    "id": 20703,
    "title": "Overlord",
    "type": "manga",
    "year": 2014,
    "content_rating": "suggestive",
    "genres": ["action", "adventure", "fantasy"],
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/b/3/5/3/3/7/0/5/0e6c"},
        "x250": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc"},
    },
}

RELATED_SERIES = {
    "id": 5469,
    "title": "Overlord New World",
    "type": "manga",
    "year": 2024,
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/related/5469"},
        "x350": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x350@1/rel"},
    },
}

# The /similar envelope: rows carry the full series object plus a similarity
# score, so no follow-up fetch is needed.
SIMILAR_RESPONSE = {
    "status": 200,
    "data": [
        {
            "score": 0.42,
            "shared_tags_total": 20,
            "series": {
                "id": 9602,
                "title": "Sui's Great Adventure",
                "type": "manga",
                "year": 2018,
                "cover": {"x350": {"x1": "https://cdn.mangabaka.dev/x350/9602"}},
            },
        },
        {
            "score": 0.75,
            "shared_tags_total": 15,
            "series": {
                "id": 7777,
                "title": "Highest Scoring",
                "type": "manga",
                "year": 2020,
                "cover": {"x350": {"x1": "https://cdn.mangabaka.dev/x350/7777"}},
            },
        },
        {
            # An officially related series, which /similar also returns.
            "score": 0.60,
            "shared_tags_total": 12,
            "series": {
                "id": 5469,
                "title": "Overlord New World",
                "type": "manga",
                "year": 2024,
                "cover": {"x350": {"x1": "https://cdn.mangabaka.dev/x350/5469"}},
            },
        },
    ],
}


SERIES_DETAIL = {
    "id": 20703,
    "title": "Overlord",
    "type": "manga",
    "year": 2014,
    "status": "completed",
    "description": "Momonga stays logged in after the servers go dark.",
    "genres": ["action", "adventure", "fantasy"],
    "rating": 79.55,
    "total_chapters": "91",
    "final_volume": "19",
    "authors": ["Kugane Maruyama", "Oshio Satoshi"],
    "artists": ["Fugin Miyama"],
    "canonical_url": "https://mangabaka.org/manga/20703/Overlord",
    "cover": {
        "raw": {"url": "https://images.mangabaka.dev/b/3/5/3/3/7/0/5/0e6c"},
        "x250": {"x1": "https://cdn.mangabaka.dev/imgproxy/plain/x250@1/abc"},
    },
    "content_rating": "suggestive",
    "relationships_v2": [
        {
            "to_series_id": 5469,
            "relation_type": "sequel",
        },
    ],
}


def _tag(name, path, count, *, genre=False, spoiler=False):
    return {
        "name": name,
        "name_path": path,
        "series_count": count,
        "is_genre": genre,
        "is_spoiler": spoiler,
    }


# Every entry here is a real tags_v2 row taken from live MangaBaka payloads, so
# the curation rules are pinned against the shapes that actually exposed the
# problems: a genre duplicate, a spoiler, explicit tags whose content_rating is
# "safe", and a low-count tag that is structural noise.
SERIES_DETAIL["tags_v2"] = [
    _tag("Female Lead", "Character Types > Female Lead", 23348),
    _tag("Male Lead", "Character Types > Male Lead", 22990),
    _tag("Isekai", "Settings > Isekai", 8963),
    _tag("Nobility", "Themes > Social Issues > Nobility", 5710),
    _tag("Demons", "Species & Creatures > Supernatural Beings > Demons", 5151),
    _tag("Murder", "Activities > Crimes > Murder", 3681),
    _tag("Heretic", "Character Archetype > Heretic", 6),
    # Counts are deliberately raised above the gate for the sensitive rows.
    # At their real series_counts (Child Abuse 778, Vore 57, Sex Slave 588) the
    # count filter alone would exclude them, so those assertions would pass even
    # with the namespace and Victims rules deleted. Above the gate, each one is
    # excluded only because the rule under test caught it.
    _tag("Child Abuse", "Sexual Content > Child Abuse", 1200),
    _tag("Vore", "Sexual Content > Vore", 1100),
    _tag("Rape", "Sexual Content > Sexual Acts > Rape", 6764),
    _tag("Adapted to Anime", "Derivative Work > Adaptations > Adapted to Anime", 4421),
    _tag("Seinen", "Audience Demographics > Male Oriented > Seinen", 35559),
    _tag("Fantasy", "Settings > Fantasy", 59465, genre=True),
    _tag("Magic", "World Building > Magic", 8358, spoiler=True),
    # Sits outside the "Sexual Content" namespace, so only a path-segment check
    # catches it.
    _tag("Sex Slave", "Character Types > Victims > Sex Slave", 9000),
    _tag("Travel", "Activities > Leisure > Travel", 1500),
]


def _http_error(status_code):
    error = requests.exceptions.HTTPError()
    error.response = MagicMock(status_code=status_code)
    return error


class TestMangaBakaSearch(TestCase):
    """Test MangaBaka search normalization and caching."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_returns_results(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 84, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        data = mangabaka.search("Overlord", 1)

        result = data["results"][0]
        self.assertEqual(result["media_id"], "20703")
        self.assertEqual(result["source"], "mangabaka")
        self.assertEqual(result["media_type"], "manga")
        self.assertEqual(result["title"], "Overlord")
        self.assertEqual(data["total_results"], 84)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_empty(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 0, "page": 1, "limit": 30},
            "data": [],
        }

        data = mangabaka.search("zzzz-no-match", 1)

        self.assertEqual(data["results"], [])
        self.assertEqual(data["total_results"], 0)

    @patch("app.providers.mangabaka.services.api_request")
    def test_search_caches(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        mangabaka.search("Overlord", 1)
        mangabaka.search("Overlord", 1)

        self.assertEqual(mock_api_request.call_count, 1)

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_filters_nsfw_by_default(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        mangabaka.search("Overlord", 1)

        _, kwargs = mock_api_request.call_args
        # erotica is included: it is where MangaBaka files BERSERK and other
        # mainstream seinen, not a measure of explicitness.
        self.assertEqual(
            kwargs["params"]["content_rating"],
            ["safe", "suggestive", "erotica"],
        )

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_keeps_erotica_tier_mainstream_titles(self, mock_api_request):
        """BERSERK-style entries are erotica-rated but must still be found.

        MangaBaka files BERSERK under erotica, so an exact-match filter built
        from the "clean" tiers alone hid the single most obvious result for a
        search of its own name.
        """
        berserk = {
            "id": 1692,
            "title": "BERSERK",
            "type": "manga",
            "year": 1989,
            "content_rating": "erotica",
            "genres": [
                "action", "adventure", "drama", "fantasy", "horror",
                "psychological", "mature", "seinen", "supernatural", "tragedy",
            ],
        }
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [berserk],
        }

        data = mangabaka.search("Berserk", 1)

        self.assertEqual([r["media_id"] for r in data["results"]], ["1692"])

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_drops_doujinshi_and_explicit_genres(self, mock_api_request):
        """The erotica tier admits fan works, so genres must filter them."""
        doujin = {
            "id": 33936,
            "title": "Berserk dj - Cruel",
            "type": "manga",
            "year": 2015,
            "content_rating": "safe",
            "genres": ["doujinshi", "shounen_ai"],
        }
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 2, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM, doujin],
        }

        data = mangabaka.search("Berserk", 1)

        self.assertEqual([r["media_id"] for r in data["results"]], ["20703"])

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_does_not_treat_adult_genre_as_explicit(self, mock_api_request):
        """"adult" is applied to mainstream titles, so it cannot gate anything.

        Berserk: The Flame Dragon Knight (suggestive) and Tantei Akechi wa
        Kyouransu (a mystery) both carry the "adult" genre on MangaBaka.
        """
        adult_rated = {
            "id": 82960,
            "title": "Berserk: The Flame Dragon Knight",
            "type": "manga",
            "year": 2015,
            "content_rating": "suggestive",
            "genres": ["action", "fantasy", "adult", "adventure", "mature"],
        }
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [adult_rated],
        }

        data = mangabaka.search("Berserk", 1)

        self.assertEqual([r["media_id"] for r in data["results"]], ["82960"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_search_nsfw_setting_drops_the_rating_filter(self, mock_api_request):
        """MU_NSFW=True lifts the content_rating filter entirely."""
        mock_api_request.return_value = {
            "status": 200,
            "pagination": {"count": 1, "page": 1, "limit": 30},
            "data": [SEARCH_ITEM],
        }

        mangabaka.search("Overlord", 1)

        _, kwargs = mock_api_request.call_args
        self.assertNotIn("content_rating", kwargs["params"])


class TestMangaBakaMetadata(TestCase):
    """Test MangaBaka series metadata normalization and caching."""

    def setUp(self):
        cache.clear()

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_metadata(self, mock_api_request):
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            {"status": 200, "data": RELATED_SERIES},
            SIMILAR_RESPONSE,
        ]

        data = mangabaka.manga("20703")

        self.assertEqual(data["media_id"], "20703")
        self.assertEqual(data["source"], "mangabaka")
        self.assertEqual(
            data["source_url"],
            "https://mangabaka.org/manga/20703/Overlord",
        )
        self.assertEqual(data["media_type"], MediaTypes.MANGA.value)
        self.assertEqual(data["title"], "Overlord")
        self.assertEqual(data["score"], round(79.55 / 10, 1))
        self.assertEqual(data["max_progress"], 91)
        self.assertEqual(data["details"]["format"], "manga")
        self.assertEqual(
            data["details"]["authors"],
            ["Kugane Maruyama", "Oshio Satoshi", "Fugin Miyama"],
        )
        self.assertEqual(data["genres"], ["Action", "Adventure", "Fantasy"])
        self.assertEqual(
            data["details"]["themes"],
            [
                "Female Lead",
                "Male Lead",
                "Isekai",
                "Nobility",
                "Demons",
                "Murder",
                "Travel",
            ],
        )
        # Sensitive rows are excluded by rule, not by their count: these are
        # ranked above several kept tags, so a count-only filter would show them.
        for excluded in ("Child Abuse", "Vore", "Rape", "Sex Slave"):
            self.assertNotIn(excluded, data["details"]["themes"])
        self.assertNotEqual(data["image"], settings.IMG_NONE)
        self.assertIsNone(data["score_count"])
        related = data["related"]["related_manga"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["title"], "Overlord New World")
        self.assertEqual(related[0]["media_id"], "5469")
        self.assertEqual(related[0]["relation_type"], "sequel")

        recommendations = data["related"]["recommendations"]
        # Sorted by score descending, and the officially-related series is
        # dropped because it already appears in the related grid above.
        self.assertEqual(
            [item["media_id"] for item in recommendations],
            ["7777", "9602"],
        )
        self.assertEqual(recommendations[0]["title"], "Highest Scoring")
        self.assertEqual(recommendations[0]["source"], Sources.MANGABAKA.value)
        self.assertEqual(recommendations[0]["media_type"], MediaTypes.MANGA.value)
        self.assertEqual(recommendations[0]["year"], 2020)
        self.assertNotEqual(recommendations[0]["image"], settings.IMG_NONE)

    @patch("app.providers.mangabaka.services.api_request")
    def test_manga_404(self, mock_api_request):
        mock_api_request.side_effect = _http_error(404)

        with self.assertRaises(services.ProviderAPIError) as cm:
            mangabaka.manga("999999999")

        self.assertEqual(cm.exception.provider, Sources.MANGABAKA.value)

    @patch("app.providers.mangabaka.services.api_request")
    def test_metadata_caches(self, mock_api_request):
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            {"status": 200, "data": RELATED_SERIES},
            SIMILAR_RESPONSE,
        ]

        mangabaka.manga("20703")
        mangabaka.manga("20703")

        # series + related-series + similar, then nothing on the second call.
        self.assertEqual(mock_api_request.call_count, 3)

    @patch("app.providers.mangabaka.services.api_request")
    def test_related_skips_failed_fetch(self, mock_api_request):
        mock_api_request.side_effect = [
            {"status": 200, "data": SERIES_DETAIL},
            _http_error(404),
            SIMILAR_RESPONSE,
        ]

        data = mangabaka.manga("20703")

        self.assertEqual(data["related"]["related_manga"], [])

    def test_related_keeps_only_official_types(self):
        relationships = [
            {"to_series_id": 1, "relation_type": "main"},
            {"to_series_id": 2, "relation_type": "side_story"},
            {"to_series_id": 3, "relation_type": "sequel"},
            {"to_series_id": 4, "relation_type": "prequel"},
            {"to_series_id": 5, "relation_type": "source"},
            {"to_series_id": 6, "relation_type": "spin_off"},
            {"to_series_id": 7, "relation_type": "parody"},
            {"to_series_id": 8, "relation_type": "other"},
            {"to_series_id": 9, "relation_type": None},
        ]

        with patch(
            "app.providers.mangabaka.services.api_request",
        ) as mock_api_request:
            mock_api_request.side_effect = lambda *a, **k: {
                "status": 200,
                "data": {
                    "id": 1,
                    "title": "Related",
                    "cover": {},
                    "year": 2020,
                },
            }

            related = mangabaka.get_related(relationships)

        self.assertEqual(len(related), 6)
        self.assertEqual(mock_api_request.call_count, 6)


class TestMangaBakaHelpers(TestCase):
    """Unit tests for MangaBaka normalization helpers."""

    def test_get_score_scales_from_100(self):
        self.assertEqual(mangabaka.get_score(79.55), 8.0)
        self.assertIsNone(mangabaka.get_score(0))
        self.assertIsNone(mangabaka.get_score(None))

    def test_parse_int_string(self):
        self.assertEqual(mangabaka._parse_int("91"), 91)
        self.assertIsNone(mangabaka._parse_int(None))
        self.assertIsNone(mangabaka._parse_int(""))

    def test_get_image_url_fallback(self):
        self.assertEqual(mangabaka.get_image_url({}), settings.IMG_NONE)
        self.assertEqual(
            mangabaka.get_image_url({"cover": {"raw": {"url": "https://x/y"}}}),
            "https://x/y",
        )
        series = {
            "cover": {
                "raw": {"url": "https://x/raw"},
                "x350": {"x1": "https://x/350"},
            },
        }
        self.assertEqual(mangabaka.get_image_url(series), "https://x/raw")
        self.assertEqual(
            mangabaka.get_image_url(series, thumbnail=True),
            "https://x/350",
        )

    def test_get_genres_normalizes_display(self):
        self.assertEqual(
            mangabaka.get_genres(["action", "slice_of_life", "school_life"]),
            ["Action", "Slice Of Life", "School Life"],
        )
        self.assertIsNone(mangabaka.get_genres([]))
        self.assertIsNone(mangabaka.get_genres(None))

    def test_get_tags_excludes_sexual_content_namespace(self):
        """The sexual-content namespace goes as a whole, not tag by tag.

        Its tags are the ones whose content_rating cannot be trusted: Child
        Abuse, Sexual Abuse and Pedophilia are all rated "safe", so a
        rating-based rule would emit explicit labels on an unauthenticated
        detail page.
        """
        themes = mangabaka.get_tags(SERIES_DETAIL)

        self.assertNotIn("Child Abuse", themes)
        self.assertNotIn("Vore", themes)
        self.assertNotIn("Rape", themes)

    def test_get_tags_excludes_victims_segment_outside_sexual_namespace(self):
        """"Sex Slave" is filed under Character Types > Victims.

        A rule that only inspected the leading namespace let it through, which
        is exactly the leak the namespace check was meant to prevent.
        """
        themes = mangabaka.get_tags(SERIES_DETAIL)

        self.assertNotIn("Sex Slave", themes)

    def test_get_tags_drops_publication_metadata_and_genre_duplicates(self):
        """Themes must describe the work, not how it was published."""
        themes = mangabaka.get_tags(SERIES_DETAIL)

        self.assertNotIn("Adapted to Anime", themes)
        self.assertNotIn("Seinen", themes)
        # Already shown by get_genres, so repeating it here is noise.
        self.assertNotIn("Fantasy", themes)
        self.assertNotIn("Magic", themes)

    def test_get_tags_keeps_deep_tags_and_orders_by_series_count(self):
        """Depth is not relevance: level-3/4 tags stay, rare tags do not."""
        themes = mangabaka.get_tags(SERIES_DETAIL)

        # Nobility (level 3) and Demons (level 3) are descriptive; a level cap
        # would have dropped them while keeping the uncapped first entry.
        self.assertIn("Nobility", themes)
        self.assertIn("Demons", themes)
        # Below the series_count gate, so too rare to describe a work.
        self.assertNotIn("Heretic", themes)
        self.assertEqual(themes[:3], ["Female Lead", "Male Lead", "Isekai"])
        # Just above the gate: flavour tags survive, unlike at the old 2000 cut.
        self.assertIn("Travel", themes)

    def test_get_tags_orders_most_common_first(self):
        series = {
            "tags_v2": [
                _tag("Rare", "Themes > Rare", 2100),
                _tag("Common", "Themes > Common", 40000),
            ],
        }

        self.assertEqual(mangabaka.get_tags(series), ["Common", "Rare"])

    def test_get_tags_handles_missing_or_malformed_tags(self):
        self.assertEqual(mangabaka.get_tags({}), [])
        self.assertEqual(mangabaka.get_tags({"tags_v2": None}), [])
        self.assertEqual(mangabaka.get_tags({"tags_v2": ["not-a-dict"]}), [])
        self.assertEqual(
            mangabaka.get_tags(
                {"tags_v2": [{"name": "", "name_path": "Themes", "series_count": 9000}]},
            ),
            [],
        )


class TestMangaBakaRecommendations(TestCase):
    """Unit tests for the tag-similar recommendation source."""

    def setUp(self):
        cache.clear()

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_sorted_by_score(self, mock_api_request):
        """The API's own order is not by score, so it must be re-sorted.

        Fixture scores are 0.75, 0.60 and 0.42, returned out of order.
        """
        mock_api_request.return_value = SIMILAR_RESPONSE

        results = mangabaka.get_recommendations("20703")

        self.assertEqual([r["media_id"] for r in results], ["7777", "5469", "9602"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_skip_officially_related(self, mock_api_request):
        """A related series must not also appear as a recommendation."""
        mock_api_request.return_value = SIMILAR_RESPONSE

        results = mangabaka.get_recommendations("20703", exclude_ids=["5469"])

        self.assertEqual([r["media_id"] for r in results], ["7777", "9602"])

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_gate_adult_tiers(self, mock_api_request):
        mock_api_request.return_value = SIMILAR_RESPONSE

        mangabaka.get_recommendations("20703")

        _, kwargs = mock_api_request.call_args
        self.assertEqual(
            kwargs["params"]["content_rating"],
            ["safe", "suggestive", "erotica"],
        )

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_omit_rating_filter_when_nsfw(self, mock_api_request):
        mock_api_request.return_value = SIMILAR_RESPONSE

        mangabaka.get_recommendations("20703")

        _, kwargs = mock_api_request.call_args
        self.assertIsNone(kwargs["params"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_return_empty_on_failure(self, mock_api_request):
        """A failed lookup degrades to no row rather than breaking the page."""
        mock_api_request.side_effect = _http_error(500)

        self.assertEqual(mangabaka.get_recommendations("20703"), [])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_skip_rows_without_a_series(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {"score": 0.9, "series": {"id": 1, "title": "Good"}},
                {"score": 0.8},
                {"score": 0.7, "series": None},
                {"score": 0.6, "series": {"title": "No id"}},
            ],
        }

        results = mangabaka.get_recommendations("20703")

        self.assertEqual([r["media_id"] for r in results], ["1"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_handle_missing_data_key(self, mock_api_request):
        mock_api_request.return_value = {"status": 200}

        self.assertEqual(mangabaka.get_recommendations("20703"), [])

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_drop_explicit_genres(self, mock_api_request):
        """Widening the tiers to erotica must not leak doujinshi into recs."""
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {
                    "score": 0.9,
                    "series": {
                        "id": 1,
                        "title": "Berserk dj - Cruel",
                        "genres": ["doujinshi", "shounen_ai"],
                    },
                },
                {
                    "score": 0.8,
                    "series": {
                        "id": 2,
                        "title": "BERSERK",
                        "content_rating": "erotica",
                        "genres": ["action", "seinen", "horror"],
                    },
                },
            ],
        }

        results = mangabaka.get_recommendations("20703")

        self.assertEqual([r["media_id"] for r in results], ["2"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_keep_explicit_genres_when_nsfw_enabled(
        self,
        mock_api_request,
    ):
        """MU_NSFW lifts the genre filter along with the rating filter."""
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {
                    "score": 0.9,
                    "series": {
                        "id": 1,
                        "title": "Berserk dj - Cruel",
                        "genres": ["doujinshi"],
                    },
                },
            ],
        }

        results = mangabaka.get_recommendations("20703")

        self.assertEqual([r["media_id"] for r in results], ["1"])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_recommendations_use_thumbnail_cover(self, mock_api_request):
        """Grids have no reason to pull the multi-megabyte raw cover."""
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {
                    "score": 0.5,
                    "series": {
                        "id": 2,
                        "title": "Covered",
                        "cover": {
                            "raw": {"url": "https://images.mangabaka.dev/raw"},
                            "x350": {"x1": "https://cdn.mangabaka.dev/x350/2"},
                        },
                    },
                },
            ],
        }

        results = mangabaka.get_recommendations("20703")

        self.assertEqual(results[0]["image"], "https://cdn.mangabaka.dev/x350/2")


class TestMangaBakaAuthorProfile(TestCase):
    """Unit tests for the author profile and its name-variant merging."""

    def setUp(self):
        cache.clear()

    def test_name_variants_cover_both_romanizations_and_orders(self):
        """MangaBaka credits one person under several spellings.

        Kentaro Miura appears as "MIURA Kentaro" (4 series) and "Kentarou
        Miura" (11 series) with no overlap, so both must be queried.
        """
        variants = mangabaka.author_name_variants("MIURA Kentaro")

        self.assertIn("MIURA Kentaro", variants)
        self.assertIn("Kentarou MIURA", variants)
        self.assertIn("MIURA Kentarou", variants)
        self.assertIn("Kentaro MIURA", variants)

    def test_name_variants_preserve_token_count(self):
        """Variants reorder and respell tokens; they never duplicate one.

        An earlier implementation concatenated instead of substituting and
        produced "MIURA Kentaro Kentaro".
        """
        variants = mangabaka.author_name_variants("MIURA Kentaro")

        for variant in variants:
            self.assertEqual(len(variant.split()), 2)
        # Expansion is not dictionary-driven, so some forms are unused words
        # ("MouRI"). They match nothing and are capped, but the real spellings
        # must still be present.
        self.assertIn("Kentarou MIURA", variants)
        self.assertIn("MIURA Kentarou", variants)

    def test_name_variants_short_vowel_expansion(self):
        """A short "o" must also be tried as the long "ou" spelling."""
        variants = mangabaka.author_name_variants("MORI Koji")

        self.assertIn("MORI Koji", variants)
        self.assertIn("MORI Kouji", variants)

    def test_name_variants_single_token_passes_through(self):
        """A one-word credit has no order or pairing to vary."""
        self.assertEqual(mangabaka.author_name_variants("Madhouse"), ["Madhouse"])
        self.assertEqual(mangabaka.author_name_variants(""), [])

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_merges_variants_without_duplicates(
        self,
        mock_api_request,
    ):
        """Each variant is queried; a series returned twice appears once.

        Also proves the exact-token check: a different person sharing the
        surname must not be listed under this author.
        """
        def respond(*_args, **kwargs):
            staff = kwargs["params"]["staff"]
            if "Kentarou" in staff:
                return {
                    "status": 200,
                    "data": [
                        {"id": 5858, "title": "Giganto Maxia",
                         "authors": ["Kentarou Miura"], "year": 2013},
                    ],
                }
            return {
                "status": 200,
                "data": [
                    {"id": 1692, "title": "BERSERK",
                     "authors": ["MIURA Kentaro"], "artists": ["MIURA Kentaro"],
                     "year": 1989},
                    # Same surname, different person.
                    {"id": 173, "title": "Blue Box",
                     "authors": ["Kouji Miura"], "year": 2021},
                ],
            }

        mock_api_request.side_effect = respond

        data = mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual(
            [entry["title"] for entry in data["bibliography"]],
            ["BERSERK", "Giganto Maxia"],
        )
        self.assertEqual(data["name"], "MIURA Kentaro")
        self.assertEqual(data["source"], Sources.MANGABAKA.value)
        self.assertEqual(data["known_for_department"], "Author")

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_deduplicates_series_across_variants(
        self,
        mock_api_request,
    ):
        """The same series credited under two spellings is listed once."""
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {"id": 1692, "title": "BERSERK",
                 "authors": ["MIURA Kentaro", "Kentarou Miura"], "year": 1989},
            ],
        }

        data = mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual(len(data["bibliography"]), 1)

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_tolerates_variant_failure(self, mock_api_request):
        """One failing variant must not lose the whole bibliography."""
        def respond(*_args, **kwargs):
            if "Kentarou" in kwargs["params"]["staff"]:
                raise _http_error(500)
            return {
                "status": 200,
                "data": [
                    {"id": 1692, "title": "BERSERK", "authors": ["MIURA Kentaro"]},
                ],
            }

        mock_api_request.side_effect = respond

        data = mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual([e["media_id"] for e in data["bibliography"]], ["1692"])

    @override_settings(MU_NSFW=False)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_gates_adult_tiers(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "data": [{"id": 1692, "title": "BERSERK", "authors": ["MIURA Kentaro"]}],
        }

        mangabaka.author_profile("MIURA Kentaro")

        _, kwargs = mock_api_request.call_args
        self.assertEqual(
            kwargs["params"]["content_rating"],
            ["safe", "suggestive", "erotica"],
        )

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_caches(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "data": [{"id": 1692, "title": "BERSERK", "authors": ["MIURA Kentaro"]}],
        }

        mangabaka.author_profile("MIURA Kentaro")
        calls_after_first = mock_api_request.call_count
        mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual(mock_api_request.call_count, calls_after_first)

    @override_settings(MU_NSFW=True)
    @patch("app.providers.mangabaka.services.api_request")
    def test_author_profile_skips_entries_without_a_title(self, mock_api_request):
        mock_api_request.return_value = {
            "status": 200,
            "data": [
                {"id": 1, "authors": ["MIURA Kentaro"]},
                {"id": 2, "title": "", "authors": ["MIURA Kentaro"]},
                {"id": 3, "title": "Good", "authors": ["MIURA Kentaro"]},
            ],
        }

        data = mangabaka.author_profile("MIURA Kentaro")

        self.assertEqual([e["media_id"] for e in data["bibliography"]], ["3"])
