"""The import preload must not hydrate item columns no importer reads (#1252).

Every file and API importer starts by loading the user's whole library through
``get_existing_media`` and ``get_existing_children``. ``Item.watch_providers``
is ~146 KiB a title in production, so hydrating it for every row of a large
library is what pushed a Trakt export import past the container's memory limit
before its first entry was written.
"""

import tracemalloc

from django.contrib.auth import get_user_model
from django.test import TestCase, tag

from app.models import TV, Episode, Item, MediaTypes, Movie, Season, Sources, Status
from integrations.imports import helpers


def _seed_library(user, titles, payload_bytes):
    """Create ``titles`` movies plus one show with ``titles`` episodes."""
    blob = "y" * payload_bytes
    heavy = {
        "synopsis": blob,
        "watch_providers": {"US": {"flatrate": [{"provider_name": blob}]}},
    }
    Item.objects.bulk_create(
        [
            Item(
                media_id=str(media_id),
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                library_media_type=MediaTypes.MOVIE.value,
                title=f"Movie {media_id}",
                image="https://example.com/movie.jpg",
                **heavy,
            )
            for media_id in range(titles)
        ],
    )
    Movie.objects.bulk_create(
        [
            Movie(item=item, user=user, status=Status.COMPLETED.value, progress=1)
            for item in Item.objects.filter(media_type=MediaTypes.MOVIE.value)
            .only("id")
        ],
    )

    show = {"media_id": "999999", "source": Sources.TMDB.value, "image": ""}
    tv_item = Item.objects.create(
        media_type=MediaTypes.TV.value, title="Show", **show, **heavy
    )
    season_item = Item.objects.create(
        media_type=MediaTypes.SEASON.value,
        title="Show",
        season_number=1,
        **show,
        **heavy,
    )
    tv = TV.objects.create(item=tv_item, user=user, status=Status.IN_PROGRESS.value)
    season = Season.objects.create(
        item=season_item,
        user=user,
        related_tv=tv,
        status=Status.IN_PROGRESS.value,
    )
    Item.objects.bulk_create(
        [
            Item(
                media_type=MediaTypes.EPISODE.value,
                library_media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=number,
                **show,
                **heavy,
            )
            for number in range(1, titles + 1)
        ],
    )
    Episode.objects.bulk_create(
        [
            Episode(item=item, related_season=season)
            for item in Item.objects.filter(media_type=MediaTypes.EPISODE.value)
            .only("id")
        ],
    )


def _preload(user):
    return helpers.get_existing_media(user), helpers.get_existing_children(user)


class ImportPreloadProjectionTests(TestCase):
    """The preloaded rows keep identity fields and defer the heavy ones."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="preload",
            password="pw12345",
        )
        _seed_library(self.user, titles=2, payload_bytes=64)

    def test_preload_defers_heavy_item_columns(self):
        """No preloaded item carries watch_providers or synopsis."""
        existing, children = _preload(self.user)

        movie = existing[MediaTypes.MOVIE.value][Sources.TMDB.value]["0"]
        tv = existing[MediaTypes.TV.value][Sources.TMDB.value]["999999"]
        season = children[MediaTypes.SEASON.value][Sources.TMDB.value][("999999", 1)]
        episode = children[MediaTypes.EPISODE.value][Sources.TMDB.value][
            ("999999", 1, 2)
        ]

        for media in (movie, tv, season, episode):
            deferred = media.item.get_deferred_fields()
            self.assertIn("watch_providers", deferred)
            self.assertIn("synopsis", deferred)
            self.assertNotIn("media_id", deferred)
            self.assertNotIn("title", deferred)

    def test_deferred_column_still_loads_on_access(self):
        """A reader of a deferred column gets the value, not an error."""
        existing, _ = _preload(self.user)
        movie = existing[MediaTypes.MOVIE.value][Sources.TMDB.value]["1"]

        self.assertEqual(movie.item.synopsis, "y" * 64)


@tag("slow", "benchmark")
class ImportPreloadMemoryBenchmark(TestCase):
    """Preload allocation must not scale with the heavy item columns."""

    TITLES = 300
    PAYLOAD_BYTES = 32 * 1024

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="preload-benchmark",
            password="pw12345",
        )
        _seed_library(self.user, self.TITLES, self.PAYLOAD_BYTES)

    @staticmethod
    def _peak_kib(callable_under_test):
        tracemalloc.start()
        tracemalloc.reset_peak()
        result = callable_under_test()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del result
        return round(peak / 1024)

    def _hydrated_control(self):
        # The pre-fix shape: every item column, for every preloaded row.
        return (
            list(Movie.objects.filter(user=self.user).select_related("item")),
            list(TV.objects.filter(user=self.user).select_related("item")),
            list(Season.objects.filter(user=self.user).select_related("item")),
            list(
                Episode.objects.filter(related_season__user=self.user).select_related(
                    "item",
                ),
            ),
        )

    def test_preload_peak_is_far_below_full_hydration(self):
        """Deferring the heavy columns removes most of the preload's allocation."""
        control = self._peak_kib(self._hydrated_control)
        preload = self._peak_kib(lambda: _preload(self.user))

        print(
            f"\nimport preload peak: {preload} KiB "
            f"(full hydration {control} KiB, {2 * self.TITLES} rows, "
            f"{self.PAYLOAD_BYTES // 1024} KiB payload)",
        )
        self.assertLess(preload, control / 4)
