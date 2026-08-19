import base64
import zlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations.imports import helpers, stremio
from integrations.models import StremioAccount


def encode_watched_bitfield(video_ids, watched_ids):
    """Build a serialized Stremio watched bitfield for tests."""
    buf = bytearray((len(video_ids) + 7) // 8)
    for index, video_id in enumerate(video_ids):
        if video_id in watched_ids:
            buf[index >> 3] |= 1 << (index & 7)
    packed = base64.b64encode(zlib.compress(bytes(buf))).decode()
    anchor = video_ids[-1]
    return f"{anchor}:{len(video_ids)}:{packed}"


class DecodeWatchedBitfieldTests(TestCase):
    """Test decoding the Stremio watched bitfield."""

    def test_decode_round_trip(self):
        """Watched bits map back to the same video ids."""
        video_ids = [f"tt1:1:{episode}" for episode in range(1, 12)]
        watched_ids = {"tt1:1:1", "tt1:1:3", "tt1:1:11"}

        serialized = encode_watched_bitfield(video_ids, watched_ids)
        watched, anchor_ok = stremio.decode_watched_bitfield(serialized, video_ids)

        self.assertTrue(anchor_ok)
        self.assertEqual(watched, watched_ids)

    def test_anchor_mismatch_flagged(self):
        """A shifted video list is reported so callers can fall back."""
        video_ids = [f"tt1:1:{episode}" for episode in range(1, 6)]
        serialized = encode_watched_bitfield(video_ids, {"tt1:1:1"})

        # Episode inserted before the anchor after the bitfield was written,
        # shifting every index.
        shifted = ["tt1:0:1", *video_ids]
        _, anchor_ok = stremio.decode_watched_bitfield(serialized, shifted)

        self.assertFalse(anchor_ok)

    def test_invalid_serialization_raises(self):
        """Malformed bitfields raise ValueError."""
        with self.assertRaises(ValueError):
            stremio.decode_watched_bitfield("garbage", ["tt1:1:1"])

    def test_anchor_id_with_colons(self):
        """Anchor video ids containing colons parse correctly."""
        video_ids = ["tt1:1:1", "tt1:1:2"]
        serialized = encode_watched_bitfield(video_ids, {"tt1:1:2"})
        watched, anchor_ok = stremio.decode_watched_bitfield(serialized, video_ids)

        self.assertTrue(anchor_ok)
        self.assertEqual(watched, {"tt1:1:2"})


def fake_tmdb_find(imdb_id, external_source):
    """Return a deterministic TMDB find payload keyed by IMDB id."""
    catalog = {
        "tt0111161": {
            "movie_results": [
                {
                    "id": 278,
                    "title": "The Shawshank Redemption",
                    "poster_path": "/shawshank.jpg",
                },
            ],
        },
        "tt0468569": {
            "movie_results": [
                {"id": 155, "title": "The Dark Knight", "poster_path": "/tdk.jpg"},
            ],
        },
        "tt0903747": {
            "tv_results": [
                {"id": 1396, "name": "Breaking Bad", "poster_path": "/bb.jpg"},
            ],
        },
        "tt7366338": {
            "tv_results": [
                {"id": 87108, "name": "Chernobyl", "poster_path": "/chernobyl.jpg"},
            ],
        },
    }
    return catalog.get(imdb_id, {})


def fake_tmdb_movie(media_id, language=None):
    """Return minimal TMDB movie metadata for a directly-known tmdb: id."""
    return {
        "title": f"Movie {media_id}",
        "image": f"http://example.com/movie-{media_id}.jpg",
        "max_progress": 1,
    }


def fake_trakt_lookup(external_id_type, external_id, *, media_type):
    """Return a deterministic Trakt external-id lookup payload."""
    catalog = {
        "1023371": {"external_ids": {"tmdb": 155}},
    }
    return catalog.get(str(external_id))


def fake_mal_anime(media_id):
    """Return minimal MAL anime metadata for a directly-known mal: id."""
    return {
        "title": f"Anime {media_id}",
        "image": f"http://example.com/anime-{media_id}.jpg",
    }


def fake_provider_api_request(provider, method, url, params=None, **kwargs):
    """Return deterministic Kitsu/AniList payloads for id-resolution tests."""
    if provider == "KITSU":
        kitsu_id = url.rsplit("/", 1)[-1]
        mal_by_kitsu = {"11": "20"}
        mal_id = mal_by_kitsu.get(kitsu_id)
        included = []
        if mal_id:
            included.append(
                {
                    "id": "1",
                    "type": "mappings",
                    "attributes": {
                        "externalSite": "myanimelist/anime",
                        "externalId": mal_id,
                    },
                },
            )
        return {"included": included}
    if provider == "ANILIST":
        anilist_id = (params or {}).get("variables", {}).get("id")
        mal_by_anilist = {101922: 21}
        return {"data": {"Media": {"idMal": mal_by_anilist.get(anilist_id)}}}
    msg = f"Unexpected provider {provider} in api_request mock"
    raise AssertionError(msg)


def fake_tv_with_seasons(media_id, season_numbers):
    """Return minimal TMDB TV metadata with the requested seasons."""
    metadata = {
        "title": f"Show {media_id}",
        "image": "http://example.com/show.jpg",
    }
    for season_number in season_numbers:
        metadata[f"season/{season_number}"] = {
            "image": "http://example.com/season.jpg",
            "max_progress": 3,
            "episodes": [
                {"episode_number": number, "still_path": f"/e{number}.jpg"}
                for number in range(1, 4)
            ],
        }
    return metadata


class ImportStremioTests(TestCase):
    """Test importing library watch state from Stremio."""

    def setUp(self):
        """Create a user with a connected Stremio account."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.account = StremioAccount.objects.create(
            user=self.user,
            auth_key=helpers.encrypt("auth-key"),
        )

    def _run_import(
        self,
        library_items,
        cinemeta_videos=None,
        mode="new",
        trakt_configured=False,
        tmdb_find=None,
    ):
        with (
            patch(
                "integrations.imports.stremio.get_library_items",
                return_value=library_items,
            ),
            patch.object(
                stremio.StremioImporter,
                "_fetch_cinemeta_videos",
                return_value=cinemeta_videos or {},
            ),
            patch("app.providers.tmdb.find", side_effect=tmdb_find or fake_tmdb_find),
            patch(
                "app.providers.tmdb.tv_with_seasons",
                side_effect=fake_tv_with_seasons,
            ),
            patch("app.providers.tmdb.movie", side_effect=fake_tmdb_movie),
            patch("app.providers.trakt.is_configured", return_value=trakt_configured),
            patch(
                "app.providers.trakt.lookup_by_external_id",
                side_effect=fake_trakt_lookup,
            ),
            patch("app.providers.mal.anime", side_effect=fake_mal_anime),
            patch(
                "app.providers.services.api_request",
                side_effect=fake_provider_api_request,
            ),
        ):
            return stremio.importer(None, self.user, mode)

    def test_movie_statuses(self):
        """Movies map to completed/in-progress/planning from watch state."""
        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": False,
                "temp": False,
                "state": {
                    "timesWatched": 1,
                    "lastWatched": "2023-02-01T00:00:00Z",
                },
            },
            {
                "_id": "tt0468569",
                "type": "movie",
                "name": "The Dark Knight",
                "removed": False,
                "temp": False,
                "state": {"timeOffset": 500000, "duration": 9000000},
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 2)
        self.assertEqual(warnings, "")

        completed = Movie.objects.get(item__media_id="278")
        self.assertEqual(completed.status, Status.COMPLETED.value)
        self.assertEqual(completed.progress, 1)
        self.assertIsNotNone(completed.end_date)

        in_progress = Movie.objects.get(item__media_id="155")
        self.assertEqual(in_progress.status, Status.IN_PROGRESS.value)
        self.assertEqual(in_progress.progress, 0)
        self.assertIsNone(in_progress.end_date)

    def test_planning_and_skipped_items(self):
        """Unwatched library items import as planning; removed ones are skipped."""
        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": False,
                "temp": False,
                "state": {},
            },
            {
                "_id": "tt0468569",
                "type": "movie",
                "name": "The Dark Knight",
                "removed": True,
                "temp": True,
                "state": {},
            },
            {
                "_id": "yt:abc123",
                "type": "movie",
                "name": "Some Channel Video",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1},
            },
            {
                "_id": "tt999",
                "type": "other",
                "name": "Unsupported",
                "state": {"timesWatched": 1},
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        movie = Movie.objects.get(item__media_id="278")
        self.assertEqual(movie.status, Status.PLANNING.value)
        self.assertIn("unsupported Stremio id 'yt:abc123'", warnings)
        self.assertFalse(Movie.objects.filter(item__media_id="155").exists())

    def test_removed_with_watch_state_imports(self):
        """Watched-but-removed items still import their watch history."""
        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": True,
                "temp": True,
                "state": {
                    "flaggedWatched": 1,
                    "lastWatched": "2023-02-01T00:00:00Z",
                },
            },
        ]

        imported_counts, _ = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        movie = Movie.objects.get(item__media_id="278")
        self.assertEqual(movie.status, Status.COMPLETED.value)

    def test_series_with_watched_bitfield(self):
        """Series create TV, season and episode rows from the bitfield."""
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        watched = {"tt0903747:1:1", "tt0903747:1:2"}
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, watched),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]

        imported_counts, warnings = self._run_import(
            library_items,
            cinemeta_videos={"tt0903747": video_ids},
        )

        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(imported_counts[MediaTypes.SEASON.value], 1)
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 2)
        self.assertEqual(warnings, "")

        tv_obj = TV.objects.get(item__media_id="1396")
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)

        season = Season.objects.get(item__media_id="1396")
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

        episode_numbers = set(
            Episode.objects.filter(item__media_id="1396").values_list(
                "item__episode_number",
                flat=True,
            ),
        )
        self.assertEqual(episode_numbers, {1, 2})

    def test_recurring_sync_advances_series_without_duplicating_episodes(self):
        """A re-sync of an already-tracked show adds new episodes only once.

        Regression test for #580: once an already-tracked TV show is no
        longer skipped outright by mode="new", re-syncing it must not
        re-append the episodes a prior sync already recorded (Episode rows
        have no per-item uniqueness - each row is a watch event).
        """
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]

        first_sync_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, {"tt0903747:1:1"}),
                    "lastWatched": "2023-01-01T00:00:00Z",
                    "video_id": "tt0903747:1:1",
                },
            },
        ]
        self._run_import(first_sync_items, cinemeta_videos={"tt0903747": video_ids})

        self.assertEqual(
            Episode.objects.filter(item__media_id="1396").count(),
            1,
        )
        tv_obj = TV.objects.get(item__media_id="1396")
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)

        second_sync_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(
                        video_ids,
                        {"tt0903747:1:1", "tt0903747:1:2"},
                    ),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]
        self._run_import(second_sync_items, cinemeta_videos={"tt0903747": video_ids})

        episode_numbers = set(
            Episode.objects.filter(item__media_id="1396").values_list(
                "item__episode_number",
                flat=True,
            ),
        )
        self.assertEqual(episode_numbers, {1, 2})
        self.assertEqual(Episode.objects.filter(item__media_id="1396").count(), 2)

        tv_obj.refresh_from_db()
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)
        season = Season.objects.get(item__media_id="1396")
        self.assertEqual(season.status, Status.IN_PROGRESS.value)

    def test_series_reuses_season_and_episode_items_from_shows_bucket(self):
        """Season/episode items already tracked in the show's bucket are reused."""
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        watched = {"tt0903747:1:1", "tt0903747:1:2"}
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, watched),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]

        # Simulate grouped anime already tracked by another importer: the show,
        # season, and episode all live in the 'anime' bucket rather than the
        # default 'tv'/'season'/'episode' ones this importer would otherwise use.
        tracked_tv = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Breaking Bad",
            image="http://example.com/show.jpg",
        )
        tracked_season = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            title="Breaking Bad Season 1",
            image="http://example.com/season.jpg",
        )
        tracked_episode = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            episode_number=1,
            title="Pilot",
            image="http://example.com/e1.jpg",
        )

        imported_counts, warnings = self._run_import(
            library_items,
            cinemeta_videos={"tt0903747": video_ids},
        )

        self.assertEqual(warnings, "")
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(imported_counts[MediaTypes.SEASON.value], 1)
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 2)

        # No duplicate rows forked in a different bucket.
        self.assertEqual(
            Item.objects.filter(media_id="1396", media_type=MediaTypes.TV.value).count(),
            1,
        )
        self.assertEqual(
            Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.SEASON.value,
            ).count(),
            1,
        )
        self.assertEqual(
            Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.EPISODE.value,
                episode_number=1,
            ).count(),
            1,
        )

        TV.objects.get(item=tracked_tv)
        Season.objects.get(item=tracked_season)
        Episode.objects.get(item=tracked_episode)

    def test_series_fully_watched_completed(self):
        """A series with every episode watched is completed."""
        video_ids = [f"tt7366338:1:{episode}" for episode in range(1, 4)]
        library_items = [
            {
                "_id": "tt7366338",
                "type": "series",
                "name": "Chernobyl",
                "removed": True,
                "temp": True,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]

        self._run_import(
            library_items,
            cinemeta_videos={"tt7366338": video_ids},
        )

        tv_obj = TV.objects.get(item__media_id="87108")
        self.assertEqual(tv_obj.status, Status.COMPLETED.value)
        season = Season.objects.get(item__media_id="87108")
        self.assertEqual(season.status, Status.COMPLETED.value)

    def test_series_without_cinemeta_falls_back_to_video_id(self):
        """When Cinemeta has no episode list, only the last video is imported."""
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": "tt0903747:1:2:3:opaque",
                    "video_id": "tt0903747:1:2",
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 1)
        self.assertIn("episode list unavailable from Cinemeta", warnings)
        episode = Episode.objects.get(item__media_id="1396")
        self.assertEqual(episode.item.episode_number, 2)

    def test_tmdb_namespaced_movie_imports_without_find_call(self):
        """A tmdb: id resolves directly, without any TMDB find lookup."""
        library_items = [
            {
                "_id": "tmdb:933260",
                "type": "movie",
                "name": "The Substance",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1, "lastWatched": "2024-01-01T00:00:00Z"},
            },
        ]

        def fail_if_called(*args, **kwargs):
            msg = "tmdb.find should not be called for a tmdb: id"
            raise AssertionError(msg)

        imported_counts, warnings = self._run_import(
            library_items,
            tmdb_find=fail_if_called,
        )

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(warnings, "")
        movie = Movie.objects.get(item__media_id="933260")
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.item.title, "Movie 933260")

    def test_tmdb_namespaced_series_imports_without_cinemeta(self):
        """A tmdb: series id resolves directly and skips the Cinemeta batch."""
        library_items = [
            {
                "_id": "tmdb:1396",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {"timeOffset": 500000, "lastWatched": "2024-01-01T00:00:00Z"},
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        # Only imdb-namespaced series ids are ever batched to Cinemeta, so a
        # tmdb: series never gets a video list; with no watched-episode
        # signal in state, status still derives from timeOffset alone.
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        tv = TV.objects.get(item__media_id="1396")
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)
        self.assertEqual(warnings, "")

    def test_tvdb_namespaced_series_resolves_via_find(self):
        """A tvdb: id resolves through TMDB's /find endpoint."""
        library_items = [
            {
                "_id": "tvdb:81189",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1, "lastWatched": "2024-01-01T00:00:00Z"},
            },
        ]

        def fake_find_with_tvdb(external_id, external_source):
            if external_source == "tvdb_id" and external_id == "81189":
                return {
                    "tv_results": [
                        {"id": 1396, "name": "Breaking Bad", "poster_path": "/bb.jpg"},
                    ],
                }
            return {}

        imported_counts, _ = self._run_import(
            library_items,
            tmdb_find=fake_find_with_tvdb,
        )

        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertTrue(TV.objects.filter(item__media_id="1396").exists())

    def test_trakt_namespaced_movie_resolves_when_configured(self):
        """A trakt: id resolves to a TMDB id via Trakt's external-id search."""
        library_items = [
            {
                "_id": "trakt:1023371",
                "type": "movie",
                "name": "Dragon Age: Absolution",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1, "lastWatched": "2024-01-01T00:00:00Z"},
            },
        ]

        imported_counts, warnings = self._run_import(
            library_items,
            trakt_configured=True,
        )

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(warnings, "")
        self.assertTrue(Movie.objects.filter(item__media_id="155").exists())

    def test_trakt_namespaced_movie_warns_when_not_configured(self):
        """A trakt: id degrades to a warning when Trakt isn't configured."""
        library_items = [
            {
                "_id": "trakt:1023371",
                "type": "movie",
                "name": "Dragon Age: Absolution",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1},
            },
        ]

        imported_counts, warnings = self._run_import(
            library_items,
            trakt_configured=False,
        )

        self.assertNotIn(MediaTypes.MOVIE.value, imported_counts)
        self.assertIn("couldn't find a match", warnings)

    def test_kitsu_namespaced_anime_resolves_to_mal(self):
        """A kitsu: id resolves to a MAL id via Kitsu's mappings."""
        library_items = [
            {
                "_id": "kitsu:11",
                "type": "series",
                "name": "Naruto",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1, "lastWatched": "2024-01-01T00:00:00Z"},
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.ANIME.value], 1)
        self.assertEqual(warnings, "")
        anime = Anime.objects.get(item__media_id="20")
        self.assertEqual(anime.status, Status.COMPLETED.value)
        self.assertEqual(anime.item.source, Sources.MAL.value)

    def test_mal_namespaced_anime_imports_directly(self):
        """A mal: id is used directly, no external resolution call."""
        library_items = [
            {
                "_id": "mal:21",
                "type": "series",
                "name": "One Piece",
                "removed": False,
                "temp": False,
                "state": {"timeOffset": 100},
            },
        ]

        imported_counts, _ = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.ANIME.value], 1)
        self.assertTrue(Anime.objects.filter(item__media_id="21").exists())

    def test_anilist_namespaced_anime_resolves_to_mal(self):
        """An anilist: id resolves to a MAL id via AniList's public GraphQL API."""
        library_items = [
            {
                "_id": "anilist:101922",
                "type": "series",
                "name": "Some Anime",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1},
            },
        ]

        imported_counts, warnings = self._run_import(library_items)

        self.assertEqual(imported_counts[MediaTypes.ANIME.value], 1)
        self.assertEqual(warnings, "")
        self.assertTrue(Anime.objects.filter(item__media_id="21").exists())

    def test_new_mode_skips_existing(self):
        """Mode "new" never overrides a user-finalized status like Dropped."""
        item, _ = Item.objects.get_or_create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Shawshank Redemption", "image": "none.svg"},
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.DROPPED.value,
        )

        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1},
            },
        ]
        imported_counts, _ = self._run_import(library_items, mode="new")

        self.assertNotIn(MediaTypes.MOVIE.value, imported_counts)
        movie = Movie.objects.get(item=item)
        self.assertEqual(movie.status, Status.DROPPED.value)

    def test_new_mode_advances_in_progress_movie_to_completed(self):
        """Mode "new" flips an already-tracked In progress movie to Completed.

        Regression test for #580: the Stremio webhook only ever marks a
        movie In progress on playback start and relies on the recurring
        (mode="new") library sync to pick up completion. Before this fix,
        should_process_media's blanket "new mode" skip meant an
        already-tracked movie's status was never recomputed.
        """
        item, _ = Item.objects.get_or_create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Shawshank Redemption", "image": "none.svg"},
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": False,
                "temp": False,
                "state": {
                    "timesWatched": 1,
                    "lastWatched": "2023-02-01T00:00:00Z",
                },
            },
        ]
        self._run_import(library_items, mode="new")

        movie = Movie.objects.get(item=item)
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.progress, 1)
        self.assertIsNotNone(movie.end_date)

    def test_overwrite_mode_replaces_existing(self):
        """Mode "overwrite" replaces existing media."""
        item, _ = Item.objects.get_or_create(
            media_id="278",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Shawshank Redemption", "image": "none.svg"},
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.DROPPED.value,
        )

        library_items = [
            {
                "_id": "tt0111161",
                "type": "movie",
                "name": "The Shawshank Redemption",
                "removed": False,
                "temp": False,
                "state": {"timesWatched": 1},
            },
        ]
        imported_counts, _ = self._run_import(library_items, mode="overwrite")

        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        movie = Movie.objects.get(item=item)
        self.assertEqual(movie.status, Status.COMPLETED.value)

    def test_import_updates_account_sync_state(self):
        """A successful import stamps last_sync_at and clears errors."""
        self.account.connection_broken = True
        self.account.last_error_message = "boom"
        self.account.save()

        self._run_import([])

        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)
        self.assertFalse(self.account.connection_broken)
        self.assertEqual(self.account.last_error_message, "")

    def test_api_error_marks_connection_broken(self):
        """An API failure marks the account broken."""
        with (
            patch(
                "integrations.imports.stremio.get_library_items",
                side_effect=helpers.MediaImportError("Stremio API error: bad session"),
            ),
            self.assertRaises(helpers.MediaImportError),
        ):
            stremio.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("bad session", self.account.last_error_message)

    def test_importer_requires_account(self):
        """Importing without a connected account raises."""
        self.account.delete()
        user = get_user_model().objects.get(pk=self.user.pk)
        with self.assertRaises(helpers.MediaImportError):
            stremio.importer(None, user, "new")


class StremioViewTests(TestCase):
    """Test the Stremio connect/disconnect/import views."""

    def setUp(self):
        """Create and log in a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("integrations.views.tasks.import_stremio.delay")
    @patch("integrations.views.stremio.login", return_value="auth-key")
    def test_connect_with_credentials(self, mock_login, mock_delay):
        """Connecting with email/password stores an encrypted auth key."""
        response = self.client.post(
            reverse("stremio_connect"),
            {"email": "user@example.com", "password": "hunter2"},
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_login.assert_called_once_with("user@example.com", "hunter2")
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

        account = StremioAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.auth_key), "auth-key")
        self.assertEqual(helpers.decrypt(account.email), "user@example.com")
        self.assertTrue(account.is_connected)

        self.assertTrue(
            PeriodicTask.objects.filter(
                task="Import from Stremio (Recurring)",
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists(),
        )

    @patch("integrations.views.tasks.import_stremio.delay")
    @patch("integrations.views.stremio.get_user", return_value={"email": "x"})
    def test_connect_with_auth_key(self, mock_get_user, mock_delay):
        """Connecting with a pasted auth key validates it via getUser."""
        response = self.client.post(
            reverse("stremio_connect"),
            {"auth_key": "pasted-key"},
        )

        self.assertRedirects(response, reverse("import_data"))
        mock_get_user.assert_called_once_with("pasted-key")
        mock_delay.assert_called_once()

        account = StremioAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.auth_key), "pasted-key")
        self.assertEqual(account.email, "")

    @patch(
        "integrations.views.stremio.login",
        side_effect=helpers.MediaImportError("Stremio API error: wrong password"),
    )
    def test_connect_bad_credentials(self, mock_login):
        """A failed login shows an error and stores nothing."""
        response = self.client.post(
            reverse("stremio_connect"),
            {"email": "user@example.com", "password": "wrong"},
            follow=True,
        )

        self.assertFalse(StremioAccount.objects.filter(user=self.user).exists())
        messages = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("Could not connect to Stremio" in m for m in messages))

    def test_connect_missing_fields(self):
        """Submitting neither credentials nor an auth key errors."""
        response = self.client.post(reverse("stremio_connect"), {}, follow=True)

        self.assertFalse(StremioAccount.objects.filter(user=self.user).exists())
        messages = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("email and password" in m for m in messages))

    @patch("integrations.views.tasks.import_stremio.delay")
    @patch("integrations.views.stremio.login", return_value="auth-key")
    def test_disconnect_removes_account_and_schedule(self, mock_login, mock_delay):
        """Disconnecting removes the account and its periodic task."""
        self.client.post(
            reverse("stremio_connect"),
            {"email": "user@example.com", "password": "hunter2"},
        )

        response = self.client.post(reverse("stremio_disconnect"))

        self.assertRedirects(response, reverse("import_data"))
        self.assertFalse(StremioAccount.objects.filter(user=self.user).exists())
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Stremio (Recurring)",
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists(),
        )

    def test_import_requires_account(self):
        """Sync Now without a connected account shows an error."""
        response = self.client.post(reverse("import_stremio"), follow=True)

        messages = [str(message) for message in response.context["messages"]]
        self.assertTrue(any("Connect Stremio" in m for m in messages))

    @patch("integrations.views.tasks.import_stremio.delay")
    def test_import_queues_task(self, mock_delay):
        """Sync Now queues the import task."""
        StremioAccount.objects.create(
            user=self.user,
            auth_key=helpers.encrypt("auth-key"),
        )

        response = self.client.post(reverse("import_stremio"))

        self.assertRedirects(response, reverse("import_data"))
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")
