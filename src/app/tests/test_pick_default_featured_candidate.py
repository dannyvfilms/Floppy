from django.test import SimpleTestCase

from app.stats_cast_crew import pick_default_featured_candidate


def _entry(name, *, plays=0, watched_minutes=0, unique_titles=0):
    return {
        "name": name,
        "source": "tmdb",
        "person_id": name,
        "plays": plays,
        "watched_minutes": watched_minutes,
        "unique_titles": unique_titles,
    }


def _top_talent():
    """Nolan North leads on time, Charles Martinet leads on unique titles."""
    nolan = _entry("Nolan North", plays=50, watched_minutes=598 * 60, unique_titles=5)
    charles = _entry(
        "Charles Martinet", plays=16, watched_minutes=40 * 60, unique_titles=16
    )
    plays_bucket = {
        "top_actors": [nolan, charles],
        "top_actresses": [],
        "top_directors": [],
        "top_writers": [],
    }
    return {
        "sort_by": "plays",
        "by_sort": {
            "plays": plays_bucket,
            "time": {
                "top_actors": [nolan, charles],
                "top_actresses": [],
                "top_directors": [],
                "top_writers": [],
            },
            "titles": {
                "top_actors": [nolan, charles],
                "top_actresses": [],
                "top_directors": [],
                "top_writers": [],
            },
        },
        # _aggregate_top_talent spreads the active sort's bucket at top level too.
        **plays_bucket,
    }


class PickDefaultFeaturedCandidateTests(SimpleTestCase):
    def test_time_sort_picks_the_person_with_the_most_watched_minutes(self):
        best = pick_default_featured_candidate(_top_talent(), sort_by="time")
        self.assertEqual(best["name"], "Nolan North")

    def test_titles_sort_picks_the_person_with_the_most_unique_titles(self):
        best = pick_default_featured_candidate(_top_talent(), sort_by="titles")
        self.assertEqual(best["name"], "Charles Martinet")

    def test_plays_sort_picks_the_person_with_the_most_plays(self):
        best = pick_default_featured_candidate(_top_talent(), sort_by="plays")
        self.assertEqual(best["name"], "Nolan North")

    def test_falls_back_to_plays_metric_for_unknown_sort_mode(self):
        best = pick_default_featured_candidate(_top_talent(), sort_by="bogus")
        self.assertEqual(best["name"], "Nolan North")

    def test_no_candidates_returns_none(self):
        empty = {"sort_by": "plays", "by_sort": {"plays": {}}}
        self.assertIsNone(pick_default_featured_candidate(empty))
