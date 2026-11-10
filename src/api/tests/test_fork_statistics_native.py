# FORK: statistics comparison, preferences, talent and featured-person
# endpoints the native Statistics screen uses.
from http import HTTPStatus as HTTP  # noqa: N814

from .base import FloppyApiTestCase


class StatisticsComparisonTests(FloppyApiTestCase):
    """The overview carries the Compare-to section and the media-type gate."""

    def _overview(self, **params):
        params.setdefault("start_date", "2024-01-01")
        params.setdefault("end_date", "2024-12-31")
        return self.call_api(
            "get",
            "api_statistics_overview",
            params=params,
            headers=self.auth_headers,
        )

    def test_previous_period_comparison_has_options_and_rows(self):
        """Compare=previous_period selects it and returns the three options."""
        payload = self._overview(compare="previous_period").json()
        comparison = payload["comparison"]
        self.assertEqual(comparison["selected"], "previous_period")
        self.assertEqual(
            {option["value"] for option in comparison["options"]},
            {"previous_period", "last_year", "none"},
        )
        self.assertTrue(comparison["rangeLabel"])
        self.assertIsInstance(comparison["rows"], list)

    def test_last_year_and_none(self):
        """Other modes are honoured; none carries no comparison label."""
        self.assertEqual(self._overview(compare="last_year").json()["comparison"]["selected"], "last_year")
        none = self._overview(compare="none").json()["comparison"]
        self.assertEqual(none["selected"], "none")
        for row in none["rows"]:
            self.assertEqual(row["comparisonLabel"], "")

    def test_all_time_has_no_comparison(self):
        """An unbounded range cannot be compared."""
        payload = self._overview(start_date="all", end_date="all").json()
        self.assertEqual(payload["comparison"]["selected"], "none")

    def test_named_range_resolves_on_the_server(self):
        """range_name picks the dates and the response names the range."""
        payload = self._overview(range_name="Last 30 Days", start_date="", end_date="").json()
        self.assertEqual(payload["range"]["range_name"], "Last 30 Days")
        self.assertTrue(payload["range"]["start_date"])
        all_time = self._overview(range_name="All Time", start_date="", end_date="").json()
        self.assertEqual(all_time["range"]["range_name"], "All Time")
        self.assertIsNone(all_time["range"]["start_date"])

    def test_total_activity_comparison_names_the_period(self):
        """The summary card's delta carries a period label."""
        payload = self._overview(range_name="This Month", start_date="", end_date="").json()
        total = payload["comparison"]["total"]
        self.assertEqual(total["periodLabel"], "last month")

    def test_media_type_gate_is_server_owned(self):
        """Available types are the enabled ones; selected is a subset."""
        gate = self._overview().json()["media_types"]
        self.assertTrue(gate["available"])
        self.assertTrue(set(gate["selected"]).issubset(set(gate["available"])))
        self.assertIn("range", self._overview().json())


class StatisticsPreferencesTests(FloppyApiTestCase):
    """GET/PATCH /statistics/preferences/."""

    def test_round_trip(self):
        """Saved choices read back."""
        response = self.call_api(
            "patch",
            "api_statistics_preferences",
            payload={
                "compare_mode": "last_year",
                "default_range": "Last 30 Days",
                "top_talent_sort_by": "time",
                "media_types": ["movie", "tv"],
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        read = self.call_api("get", "api_statistics_preferences", headers=self.auth_headers).json()
        self.assertEqual(read["compare_mode"], "last_year")
        self.assertEqual(read["default_range"], "Last 30 Days")
        self.assertEqual(read["top_talent_sort_by"], "time")
        self.assertEqual(set(read["media_types"]["selected"]), {"movie", "tv"})
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.statistics_compare_mode, "last_year")

    def test_display_preferences_round_trip(self):
        """The statistics modal's choices save through the same endpoint."""
        response = self.call_api(
            "patch",
            "api_statistics_preferences",
            payload={
                "activity_history_view": "stacked",
                "duration_format": "long_units",
                "week_start_day": "sunday",
                "rating_scale": "5",
                "stats_split_tv_anime": True,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        read = response.json()
        self.assertEqual(read["activity_history_view"], "stacked")
        self.assertEqual(read["week_start_day"], "sunday")
        self.assertTrue(read["stats_split_tv_anime"])
        self.assertIn("rating_scale", read["display_choices"])
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.rating_scale, "5")
        bad = self.call_api(
            "patch",
            "api_statistics_preferences",
            payload={"week_start_day": "friday"},
            headers=self.auth_headers,
        )
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)

    def test_non_string_choice_is_rejected(self):
        """A list or object value is a 400, not a server error."""
        for value in (["last_year"], {"a": 1}):
            response = self.call_api(
                "patch",
                "api_statistics_preferences",
                payload={"compare_mode": value},
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_invalid_values_are_rejected(self):
        """Unknown choices return 400 and change nothing."""
        for payload in (
            {"compare_mode": "bogus"},
            {"default_range": "Next Week"},
            {"genre_sort_by": "titles"},
            {"media_types": ["movie", "bogus"]},
        ):
            response = self.call_api(
                "patch",
                "api_statistics_preferences",
                payload=payload,
                headers=self.auth_headers,
            )
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, payload)

    def test_preferences_are_per_user(self):
        """One account's change does not touch another's."""
        self.call_api(
            "patch",
            "api_statistics_preferences",
            payload={"compare_mode": "none"},
            headers=self.auth_headers,
        )
        other = self.call_api("get", "api_statistics_preferences", headers=self.auth_headers2).json()
        self.assertNotEqual(other["compare_mode"], "none")


class StatisticsTalentTests(FloppyApiTestCase):
    """GET /statistics/talent/ and POST /statistics/featured-person/."""

    def test_talent_returns_json_sections(self):
        """The fragment's JSON keys are present."""
        response = self.call_api(
            "get",
            "api_statistics_talent",
            params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        payload = response.json()
        self.assertIn("talent", payload)
        self.assertIn("featuredPerson", payload)

    def test_featured_person_requires_identity(self):
        """Missing person fields return 400."""
        response = self.call_api(
            "post",
            "api_statistics_featured_person",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_unknown_person_is_404(self):
        """A person with no plays in range returns 404."""
        response = self.call_api(
            "post",
            "api_statistics_featured_person",
            payload={
                "person_source": "tmdb",
                "person_id": "999999",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
