from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import TV, Episode, Item, MediaTypes, Movie, Season, Sources, Status
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor


class GenericScrobbleHeuristicTests(TestCase):
    """Unit tests for GenericScrobbleProcessor's hook methods."""

    def setUp(self):
        """Instantiate the processor under test."""
        self.processor = GenericScrobbleProcessor()

    def test_get_media_type_translates_episode_to_tv(self):
        """The API's 'episode' vocabulary maps to the base class's TV routing."""
        self.assertEqual(
            self.processor._get_media_type({"media_type": "episode"}),
            MediaTypes.TV.value,
        )
        self.assertEqual(
            self.processor._get_media_type({"media_type": "movie"}),
            MediaTypes.MOVIE.value,
        )
        self.assertIsNone(
            self.processor._get_media_type({"media_type": "unknown"}),
        )

    def test_extract_external_ids_reads_normalized_ids(self):
        """Ids are read straight through from the already-normalized payload."""
        ids = self.processor._extract_external_ids(
            {"ids": {"tmdb": "603", "imdb": "tt0133093", "tvdb": None}},
        )
        self.assertEqual(
            ids,
            {"tmdb_id": "603", "imdb_id": "tt0133093", "tvdb_id": None},
        )

    def test_is_played_honors_explicit_completed_override(self):
        """An explicit 'completed' flag overrides the position/duration heuristic."""
        self.assertTrue(
            self.processor._is_played(
                {"completed": True, "position_seconds": 0, "duration_seconds": 5400},
            ),
        )
        self.assertFalse(
            self.processor._is_played(
                {
                    "completed": False,
                    "position_seconds": 5400,
                    "duration_seconds": 5400,
                },
            ),
        )

    def test_is_played_uses_buffer_when_duration_known(self):
        """Position within the scrobble buffer of duration counts as played."""
        self.assertTrue(
            self.processor._is_played(
                {"position_seconds": 5380, "duration_seconds": 5400},
            ),
        )
        self.assertFalse(
            self.processor._is_played(
                {"position_seconds": 100, "duration_seconds": 5400},
            ),
        )

    def test_is_played_uses_fallback_when_duration_missing(self):
        """Without duration, a long-enough position falls back to a fixed threshold."""
        self.assertTrue(
            self.processor._is_played({"position_seconds": 20 * 60}),
        )
        self.assertFalse(
            self.processor._is_played({"position_seconds": 60}),
        )

    def test_is_played_false_without_position(self):
        """No position data at all means not played."""
        self.assertFalse(self.processor._is_played({}))


class GenericScrobbleProcessPayloadTests(TestCase):
    """process_payload() end-to-end for movie and episode paths."""

    def setUp(self):
        """Create the user the scrobble events are attributed to."""
        self.user = get_user_model().objects.create_user(username="scrobble-user")
        self.processor = GenericScrobbleProcessor()

    def test_no_ids_is_a_noop(self):
        """A payload with no external ids never reaches TMDB resolution."""
        self.processor.process_payload(
            {"media_type": "movie", "ids": {}, "completed": True},
            self.user,
        )
        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    @tag("network")
    def test_movie_stop_marks_completed(self):
        """A completed movie stop event creates a completed Movie instance."""
        self.processor.process_payload(
            {
                "media_type": "movie",
                "ids": {"tmdb": "603"},
                "title": "The Matrix",
                "completed": True,
            },
            self.user,
        )

        movie = Movie.objects.get(item__media_id="603", user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)

    @tag("network")
    def test_movie_stop_without_completion_marks_in_progress(self):
        """A stop event without completion marks the movie in progress."""
        self.processor.process_payload(
            {
                "media_type": "movie",
                "ids": {"tmdb": "603"},
                "title": "The Matrix",
                "completed": False,
            },
            self.user,
        )

        movie = Movie.objects.get(item__media_id="603", user=self.user)
        self.assertEqual(movie.status, Status.IN_PROGRESS.value)
        self.assertEqual(movie.progress, 0)

    def test_movie_completion_prefers_pending_activity_row(self):
        """Scrobble completion upgrades Planning before older completed history."""
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        prior_completed = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        planning = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        with (
            patch(
                "app.providers.tmdb.movie",
                return_value={"title": "The Matrix", "image": ""},
            ),
            patch("app.services.metadata_resolution.upsert_provider_links"),
            patch(
                "app.providers.services.get_media_metadata",
                return_value={"max_progress": 1},
            ),
            patch("app.models.Item.fetch_releases"),
        ):
            self.processor.process_payload(
                {
                    "media_type": "movie",
                    "ids": {"tmdb": "603"},
                    "completed": True,
                },
                self.user,
            )

        planning.refresh_from_db()
        prior_completed.refresh_from_db()
        self.assertEqual(planning.status, Status.COMPLETED.value)
        self.assertIsNotNone(planning.end_date)
        self.assertEqual(prior_completed.status, Status.COMPLETED.value)
        self.assertEqual(Movie.objects.filter(item=item, user=self.user).count(), 2)

    @tag("network")
    def test_episode_stop_marks_episode_played(self):
        """A completed episode stop event resolves the show via tvdb/imdb."""
        self.processor.process_payload(
            {
                "media_type": "episode",
                "ids": {"tvdb": "303821", "imdb": "tt0583459"},
                "series_title": "Friends",
                "season_number": 1,
                "episode_number": 1,
                "completed": True,
            },
            self.user,
        )

        tv = TV.objects.get(item__media_id="1668", user=self.user)
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)

        season = Season.objects.get(item__media_id="1668", item__season_number=1)
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

        self.assertTrue(
            Episode.objects.filter(
                item__media_id="1668",
                item__season_number=1,
                item__episode_number=1,
            ).exists(),
        )

    def test_movie_resolution_failure_propagates(self):
        """A provider failure during resolution is not swallowed here."""
        with (
            patch(
                "app.providers.tmdb.movie",
                side_effect=RuntimeError("tmdb down"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.processor.process_payload(
                {
                    "media_type": "movie",
                    "ids": {"tmdb": "603"},
                    "completed": True,
                },
                self.user,
            )

        self.assertFalse(
            Item.objects.filter(
                media_id="603",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
            ).exists(),
        )
