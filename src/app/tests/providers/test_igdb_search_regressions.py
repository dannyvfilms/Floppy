from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import MediaTypes, Sources
from app.providers import igdb

ALTERNATE_NAME_RESULTS = [
    {
        "name": "SearchResults",
        "result": [
            {
                "id": 119388,
                "name": "Halo: The Master Chief Collection",
            },
        ],
    },
    {"name": "TotalCount", "count": 1},
]

EMPTY_RESULTS = [
    {"name": "SearchResults", "result": []},
    {"name": "TotalCount", "count": 0},
]


class IgdbSearchConditionTests(TestCase):
    """Regression coverage for the IGDB alternative-name search condition."""

    def test_literal_condition_matches_names_and_alternative_names(self):
        """A literal query should match either the title or an alternate title."""
        condition = igdb._build_search_query_condition("Halo Infinite")

        self.assertEqual(
            condition,
            '(name ~ *"Halo Infinite"* | alternative_names.name ~ *"Halo Infinite"*)',
        )

    def test_literal_condition_escapes_quotes_in_both_clauses(self):
        """Both sides of the OR must escape user input, not just the name clause."""
        condition = igdb._build_search_query_condition('Rock "n" Roll')

        self.assertEqual(
            condition,
            '(name ~ *"Rock \\"n\\" Roll"* '
            '| alternative_names.name ~ *"Rock \\"n\\" Roll"*)',
        )

    def test_literal_condition_is_none_for_blank_query(self):
        """Blank queries must not build an unbounded alternative-name condition."""
        self.assertIsNone(igdb._build_search_query_condition("   "))

    def test_tokenized_condition_groups_each_term(self):
        """Each token needs its own OR group so the & join stays per-term."""
        condition = igdb._build_search_query_condition(
            "Shakedown Hawaii",
            tokenized=True,
        )

        self.assertEqual(
            condition,
            '(name ~ *"Shakedown"* | alternative_names.name ~ *"Shakedown"*)'
            ' & (name ~ *"Hawaii"* | alternative_names.name ~ *"Hawaii"*)',
        )

    def test_tokenized_condition_requires_minimum_terms(self):
        """Single-term queries still skip the tokenized fallback."""
        self.assertIsNone(
            igdb._build_search_query_condition("Halo", tokenized=True),
        )


class IgdbSearchMultiqueryTests(TestCase):
    """Regression coverage for the game_type filter used by IGDB search."""

    def test_multiquery_includes_port_game_type(self):
        """Ports (game_type 11) must stay inside the search filter."""
        multiquery = igdb._build_search_multiquery("Halo", 1)

        self.assertIn("game_type = (0,1,2,3,4,5,6,7,8,9,10,11)", multiquery)

    def test_game_type_filter_applies_to_results_and_count(self):
        """The count subquery must use the same filter as the results subquery."""
        multiquery = igdb._build_search_multiquery("Halo", 1)

        self.assertEqual(
            multiquery.count("game_type = (0,1,2,3,4,5,6,7,8,9,10,11)"),
            2,
        )
        self.assertEqual(
            multiquery.count(
                '(name ~ *"Halo"* | alternative_names.name ~ *"Halo"*)',
            ),
            2,
        )

    def test_port_game_type_maps_to_a_label(self):
        """A game_type the search now returns must render a format label."""
        self.assertEqual(igdb.get_game_type(11), "Port")

    @override_settings(IGDB_NSFW=False)
    def test_nsfw_filter_still_applies_alongside_new_conditions(self):
        """The adult-theme exclusion survives the alternative-name condition."""
        multiquery = igdb._build_search_multiquery("Halo", 1)

        self.assertIn(
            '(name ~ *"Halo"* | alternative_names.name ~ *"Halo"*) '
            "& game_type = (0,1,2,3,4,5,6,7,8,9,10,11) & themes != (42)",
            multiquery,
        )

    @override_settings(IGDB_NSFW=True)
    def test_nsfw_setting_drops_only_the_theme_filter(self):
        """Enabling NSFW must not also drop the game_type filter."""
        multiquery = igdb._build_search_multiquery("Halo", 1)

        self.assertNotIn("themes != (42)", multiquery)
        self.assertIn("game_type = (0,1,2,3,4,5,6,7,8,9,10,11)", multiquery)

    def test_multiquery_is_none_when_no_condition_can_be_built(self):
        """An unusable query must not fall through to a filter-only search."""
        self.assertIsNone(igdb._build_search_multiquery("   ", 1))
        self.assertIsNone(igdb._build_search_multiquery("Halo", 1, tokenized=True))


class IgdbSearchAlternativeNameTests(TestCase):
    """End-to-end regression coverage for alternative-name driven searches."""

    def setUp(self):
        """Clear the cache so searches do not share IGDB responses."""
        cache.clear()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_alternate_title_resolves_without_tokenized_fallback(
        self,
        mock_api_request,
        mock_get_access_token,
    ):
        """An alternate-title hit resolves on the literal attempt, with no retry."""
        mock_api_request.return_value = ALTERNATE_NAME_RESULTS

        response = igdb.search("MCC", 1)

        self.assertEqual(response["total_results"], 1)
        self.assertEqual(
            response["results"][0]["title"],
            "Halo: The Master Chief Collection",
        )
        self.assertEqual(mock_api_request.call_count, 1)
        self.assertIn(
            'alternative_names.name ~ *"MCC"*',
            mock_api_request.call_args.kwargs["data"],
        )
        mock_get_access_token.assert_called_once()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_tokenized_fallback_also_searches_alternative_names(
        self,
        mock_api_request,
        mock_get_access_token,
    ):
        """The fallback attempt keeps alternative-name matching for every term."""
        mock_api_request.side_effect = [EMPTY_RESULTS, ALTERNATE_NAME_RESULTS]

        response = igdb.search("Master Chief", 1)

        self.assertEqual(response["total_results"], 1)
        self.assertEqual(mock_api_request.call_count, 2)

        fallback_request = mock_api_request.call_args_list[1].kwargs["data"]
        self.assertIn('alternative_names.name ~ *"Master"*', fallback_request)
        self.assertIn('alternative_names.name ~ *"Chief"*', fallback_request)
        mock_get_access_token.assert_called_once()


class IgdbSearchCacheVersionTests(TestCase):
    """Regression coverage for the search cache bump that shipped the change."""

    def setUp(self):
        """Clear the cache so searches do not share IGDB responses."""
        cache.clear()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_search_ignores_results_cached_before_the_version_bump(
        self,
        mock_api_request,
        mock_get_access_token,
    ):
        """Pre-change caches must not keep serving name-only search results."""
        stale_key = f"search_v2_{Sources.IGDB.value}_{MediaTypes.GAME.value}_mcc_1"
        cache.set(
            stale_key,
            {"page": 1, "total_results": 0, "total_pages": 1, "results": []},
        )
        mock_api_request.return_value = ALTERNATE_NAME_RESULTS

        response = igdb.search("MCC", 1)

        self.assertEqual(response["total_results"], 1)
        self.assertEqual(mock_api_request.call_count, 1)
        mock_get_access_token.assert_called_once()

    @patch("app.providers.igdb.get_access_token", return_value="token")
    @patch("app.providers.igdb.services.api_request")
    def test_search_caches_under_the_current_version(
        self,
        mock_api_request,
        mock_get_access_token,
    ):
        """Repeat searches reuse the versioned cache entry instead of re-querying."""
        mock_api_request.return_value = ALTERNATE_NAME_RESULTS

        igdb.search("MCC", 1)
        igdb.search("MCC", 1)

        self.assertEqual(mock_api_request.call_count, 1)

        cache_key = (
            f"search_{igdb.IGDB_SEARCH_CACHE_VERSION}_{Sources.IGDB.value}_"
            f"{MediaTypes.GAME.value}_mcc_1"
        )
        self.assertIsNotNone(cache.get(cache_key))
        mock_get_access_token.assert_called_once()
