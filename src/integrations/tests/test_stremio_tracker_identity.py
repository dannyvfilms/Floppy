from django.contrib.auth import get_user_model
from django.test import TestCase

from app.mixins import disable_fetch_releases
from app.models import TV, Episode, Item, Movie, Season
from app.models.choices import MediaTypes, Sources, Status
from integrations import stremio_tracker

User = get_user_model()


class ResolveMediaIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="identity", password="x")

    def test_movie_resolves_directly(self):
        # How the Stremio importer stores a movie: numeric TMDB media_id, the
        # IMDB id (which is what Stremio sends) in provider_external_ids.
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="603",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                provider_external_ids={"imdb_id": "tt100"},
                title="A Movie",
                image="",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "movie",
            "tt100",
        )

        self.assertEqual(resolved, item)

    def test_unknown_movie_returns_none(self):
        """An id Floppy does not know is skipped, never guessed."""
        self.assertIsNone(
            stremio_tracker.resolve_media_identity(self.user, "movie", "tt999"),
        )

    def test_series_without_video_id_resolves_the_series(self):
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt200"},
                title="A Series",
                image="",
            )
            TV.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "series",
            "tt200",
        )

        self.assertEqual(resolved, item)

    def test_series_with_video_id_does_not_resolve_to_the_series(self):
        """The position belongs to the episode, not the series.

        Returning the series here would attribute every episode's position to
        one item — the most likely identity bug in the feature.
        """
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt300"},
                title="Another Series",
                image="",
            )
            TV.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "series",
            "tt300",
            video_id="tt300:1:2",
        )

        self.assertNotEqual(resolved, item)

    def test_malformed_video_id_returns_none(self):
        self.assertIsNone(
            stremio_tracker.resolve_media_identity(
                self.user,
                "series",
                "tt300",
                video_id="not-an-episode-id",
            ),
        )

    def test_series_with_video_id_resolves_the_episode_item(self):
        """Episode Items are keyed by series media_id + season/episode fields."""
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt400"},
                title="Episode Series",
                image="",
            )
            tv = TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            season_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
                title="Episode Series",
                image="",
            )
            season = Season.objects.create(
                item=season_item,
                related_tv=tv,
                user=self.user,
                status=Status.PLANNING.value,
            )
            episode_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=2,
                title="An Episode",
                image="",
            )
            # Seed the play row directly: Episode.save() would ask the provider
            # for season metadata, which the test network guard blocks.
            Episode.objects.bulk_create(
                [
                    Episode(
                        item=episode_item,
                        related_season=season,
                        end_date=None,
                    ),
                ],
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "series",
            "tt400",
            video_id="tt400:1:2",
        )

        self.assertEqual(resolved, episode_item)

    def test_episode_resolves_without_an_existing_play_row(self):
        """The first viewing of an episode must resolve, with no Episode row.

        ``Episode`` is a play row: nothing creates one for an episode the user
        has not played yet. Resolving through it dropped every position and
        play for a first viewing, which is exactly what the poll producer
        exists to capture.
        """
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt400"},
                title="Fresh Series",
                image="",
            )
            TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            )
            episode_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=2,
                title="Never Played",
                image="",
            )

        self.assertFalse(Episode.objects.filter(item=episode_item).exists())

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "series",
            "tt400",
            video_id="tt400:1:2",
        )

        self.assertEqual(resolved, episode_item)

    def test_imdb_source_item_resolves_by_media_id(self):
        """Some Items carry the IMDB id as media_id instead; both must match."""
        with disable_fetch_releases():
            item = Item.objects.create(
                media_id="tt999",
                source=Sources.IMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title="An IMDB Movie",
                image="",
            )
            Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "movie",
            "tt999",
        )

        self.assertEqual(resolved, item)

    def test_out_of_range_video_id_returns_none_without_raising(self):
        """A client-supplied video id must not bind an unbounded int into a query."""
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt400"},
                title="Out Of Range",
                image="",
            )
            TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        for video_id in (
            "tt400:1:999999999999999999999999",
            "tt400:1:0",
            "tt400:10000:1",
        ):
            with self.subTest(video_id=video_id):
                self.assertIsNone(
                    stremio_tracker.resolve_media_identity(
                        self.user,
                        "series",
                        "tt400",
                        video_id=video_id,
                    ),
                )

    def test_season_zero_specials_are_not_rejected_as_out_of_range(self):
        """Season 0 is Stremio's specials bucket, not a malformed coordinate.

        Rejecting it silently dropped every special. The episode still resolves
        to nothing here because Floppy has no season-0 rows, which is why the
        assertion is on the log-free path rather than on a resolved Item.
        """
        with disable_fetch_releases():
            series_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                provider_external_ids={"imdb_id": "tt400"},
                title="Specials Series",
                image="",
            )
            TV.objects.create(
                item=series_item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            season_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=0,
                title="Specials Series",
                image="",
            )
            season = Season.objects.create(
                item=season_item,
                related_tv=TV.objects.get(item=series_item, user=self.user),
                user=self.user,
                status=Status.PLANNING.value,
            )
            episode_item = Item.objects.create(
                media_id="1399",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=0,
                episode_number=1,
                title="A Special",
                image="",
            )
            Episode.objects.bulk_create(
                [Episode(item=episode_item, related_season=season, end_date=None)],
            )

        resolved = stremio_tracker.resolve_media_identity(
            self.user,
            "series",
            "tt400",
            video_id="tt400:0:1",
        )

        self.assertEqual(resolved, episode_item)
