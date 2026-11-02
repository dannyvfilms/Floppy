from django.test import SimpleTestCase


class TmdbAggregateCreditsTests(SimpleTestCase):
    """TMDB aggregate-credits parsing against malformed provider payloads."""

    def test_tmdb_aggregate_credits_normalization_handles_nested_and_malformed_roles(self):
        """TMDB aggregate credits with non-dict roles or nested lists normalize cleanly."""
        from app.providers import tmdb

        credits_data = {
            "cast": [
                {
                    "id": 101,
                    "name": "Diego Luna",
                    "roles": [
                        [{"character": "Cassian Andor", "episode_count": 24}],
                        {"character": "Cassian Jeron Andor", "episode_count": 12},
                        "malformed string entry",
                        None,
                    ],
                    "known_for_department": "Acting",
                    "gender": 2,
                    "order": 0,
                },
                {
                    "id": 102,
                    "name": "Stellan Skarsgard",
                    "roles": "invalid roles structure",
                    "known_for_department": "Acting",
                    "gender": 2,
                    "order": 1,
                },
            ],
            "crew": [
                {
                    "id": 201,
                    "name": "Tony Gilroy",
                    "jobs": [
                        [{"job": "Executive Producer", "department": "Production"}],
                        {"job": "Writer", "department": "Writing"},
                        123,
                    ],
                    "department": "Writing",
                    "gender": 2,
                    "order": 0,
                },
            ],
        }

        cast = tmdb.get_cast_credits(credits_data, is_aggregate=True)
        crew = tmdb.get_crew_credits(credits_data, is_aggregate=True)

        self.assertEqual(len(cast), 2)
        self.assertEqual(cast[0]["name"], "Diego Luna")
        self.assertIn(cast[0]["role"], ["Cassian Andor", "Cassian Jeron Andor"])
        self.assertEqual(cast[1]["name"], "Stellan Skarsgard")

        self.assertTrue(len(crew) >= 1)
        self.assertEqual(crew[0]["name"], "Tony Gilroy")
    def test_tmdb_credits_sorting_with_non_int_order(self):
        """get_cast_credits and get_crew_credits handle string/non-int order fields cleanly."""
        from app.providers import tmdb

        credits_data = {
            "cast": [
                {"id": 1, "name": "Actor A", "order": "invalid_string"},
                {"id": 2, "name": "Actor B", "order": 0},
            ],
            "crew": [
                {"id": 3, "name": "Crew A", "order": "invalid_string"},
                {"id": 4, "name": "Crew B", "order": 1},
            ],
        }

        cast = tmdb.get_cast_credits(credits_data, is_aggregate=True)
        crew = tmdb.get_crew_credits(credits_data, is_aggregate=True)
        self.assertEqual(len(cast), 2)
        self.assertEqual(cast[0]["name"], "Actor B")
        self.assertEqual(cast[1]["name"], "Actor A")
        self.assertEqual(len(crew), 2)
