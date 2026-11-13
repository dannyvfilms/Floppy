"""A season's episode total is a count, not its last episode number (#1754)."""

from django.test import SimpleTestCase

from integrations.imports import helpers


def _season(first, last):
    return {
        "max_progress": last - first + 1,
        "last_episode_number": last,
        "episodes": [{"episode_number": n} for n in range(first, last + 1)],
    }


class SeasonEpisodeNumberHelperTests(SimpleTestCase):
    """Completion checks compare against the real last episode number."""

    def test_last_episode_number_for_continued_numbering(self):
        self.assertEqual(helpers.season_last_episode_number(_season(51, 100)), 100)

    def test_last_episode_number_falls_back_to_episode_list(self):
        metadata = _season(51, 100)
        del metadata["last_episode_number"]
        self.assertEqual(helpers.season_last_episode_number(metadata), 100)

    def test_last_episode_number_falls_back_to_max_progress(self):
        self.assertEqual(helpers.season_last_episode_number({"max_progress": 12}), 12)

    def test_episode_numbers_for_continued_numbering(self):
        self.assertEqual(
            helpers.season_episode_numbers(_season(51, 100)),
            set(range(51, 101)),
        )

    def test_episode_numbers_without_episode_list(self):
        self.assertEqual(
            helpers.season_episode_numbers({"max_progress": 3}),
            {1, 2, 3},
        )


class ProcessSeasonTests(SimpleTestCase):
    """Provider season metadata counts episodes."""

    def test_tmdb_season_counts_episodes_with_continued_numbering(self):
        from app.providers import tmdb

        response = {
            "name": "Season 2",
            "season_number": 2,
            "overview": "",
            "poster_path": None,
            "vote_average": 0,
            "air_date": "2020-01-01",
            "episodes": [
                {
                    "episode_number": n,
                    "runtime": 24,
                    "vote_count": 0,
                    "air_date": "2020-01-01",
                }
                for n in range(51, 101)
            ],
        }

        metadata = tmdb.process_season(response, {})

        self.assertEqual(metadata["max_progress"], 50)
        self.assertEqual(metadata["last_episode_number"], 100)
        self.assertEqual(metadata["details"]["episodes"], 50)
