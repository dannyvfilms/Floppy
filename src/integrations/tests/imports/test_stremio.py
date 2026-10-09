import base64
import zlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.dateparse import parse_datetime
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
from app.services.grouped_anime import GroupedAnimeMatch
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
        """A shifted video list is realigned rather than discarded.

        The bitfield is positional, but the anchor pins bit ``length - 1`` to
        a known video, so the offset is recoverable. Two episodes inserted
        ahead of the anchor shift every original index by two.
        """
        video_ids = [f"tt1:1:{episode}" for episode in range(1, 6)]
        serialized = encode_watched_bitfield(video_ids, {"tt1:1:1", "tt1:1:3"})

        shifted = ["tt1:0:1", "tt1:0:2", *video_ids]
        watched, anchored = stremio.decode_watched_bitfield(serialized, shifted)

        self.assertTrue(anchored)
        self.assertEqual(watched, {"tt1:1:1", "tt1:1:3"})

    def test_absent_anchor_is_reported_unaligned(self):
        """With no anchor in the list there is no reference point at all.

        ``anchored`` is False so the caller falls back to the last-watched
        video instead of trusting positions it cannot verify.
        """
        video_ids = [f"tt1:1:{episode}" for episode in range(1, 6)]
        serialized = encode_watched_bitfield(video_ids, {"tt1:1:1"})

        other_show = [f"tt2:1:{episode}" for episode in range(1, 6)]
        watched, anchored = stremio.decode_watched_bitfield(serialized, other_show)

        self.assertFalse(anchored)
        self.assertEqual(watched, {"tt2:1:1"})

    def test_bits_aligned_before_the_list_are_dropped(self):
        """An alignment that pushes a bit past the start drops it.

        The leading episodes can leave the list while the anchor stays, so the
        offset is negative; those bits describe videos the list no longer
        has.
        """
        video_ids = [f"tt1:1:{episode}" for episode in range(1, 6)]
        serialized = encode_watched_bitfield(
            video_ids,
            {"tt1:1:1", "tt1:1:3", "tt1:1:5"},
        )

        # The first two episodes are gone; the anchor keeps its place.
        trimmed = video_ids[2:]
        watched, anchored = stremio.decode_watched_bitfield(serialized, trimmed)

        self.assertTrue(anchored)
        self.assertEqual(watched, {"tt1:1:3", "tt1:1:5"})

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


def fake_tv_with_seasons_with_future_episode(media_id, season_numbers):
    """Return TV metadata with an extra episode beyond max_progress."""
    metadata = fake_tv_with_seasons(media_id, season_numbers)
    for season_number in season_numbers:
        metadata[f"season/{season_number}"]["episodes"].append(
            {"episode_number": 4, "still_path": "/e4.jpg"},
        )
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
        tmdb_tv_with_seasons=None,
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
                side_effect=tmdb_tv_with_seasons or fake_tv_with_seasons,
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

    def test_cinemeta_skips_malformed_series_entries(self):
        """Malformed series metadata is summarized without blocking valid data."""
        importer = stremio.StremioImporter(self.user, "new")
        response = {
            "metasDetailed": [
                None,
                "private-provider-payload",
                {"videos": []},
                {
                    "id": "tt0903747",
                    "videos": [{"id": "tt0903747:1:1"}],
                },
            ],
        }

        with patch(
            "app.providers.services.api_request",
            return_value=response,
        ):
            videos = importer._fetch_cinemeta_videos(["tt0903747"])

        self.assertEqual(videos, {"tt0903747": ["tt0903747:1:1"]})
        self.assertEqual(
            importer.warnings,
            ["Cinemeta skipped 3 malformed series entries."],
        )
        self.assertNotIn("private-provider-payload", importer.warnings[0])

    def test_cinemeta_accepts_string_ids_and_skips_malformed_videos(self):
        """Valid video IDs survive malformed siblings in the same response."""
        importer = stremio.StremioImporter(self.user, "new")
        response = {
            "metasDetailed": [
                {
                    "id": "tt0903747",
                    "videos": [
                        "tt0903747:1:1",
                        {"id": "tt0903747:1:2"},
                        None,
                        7,
                        {},
                        {"id": ""},
                    ],
                },
                {
                    "id": "tt7366338",
                    "videos": [{"id": "tt7366338:1:1"}],
                },
                {"id": "tt1234567", "videos": "not-a-list"},
            ],
        }

        with patch(
            "app.providers.services.api_request",
            return_value=response,
        ):
            videos = importer._fetch_cinemeta_videos(
                ["tt0903747", "tt7366338"],
            )

        self.assertEqual(
            videos,
            {
                "tt0903747": ["tt0903747:1:1", "tt0903747:1:2"],
                "tt7366338": ["tt7366338:1:1"],
                "tt1234567": [],
            },
        )
        self.assertEqual(
            importer.warnings,
            [
                "tt0903747: Cinemeta skipped 4 malformed video entries.",
                "tt1234567: Cinemeta returned a malformed video list; skipped.",
            ],
        )

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

    def test_series_bitfield_realigns_when_cinemeta_inserts_an_episode(self):
        """Episodes added ahead of the anchor do not shift watched state.

        The bitfield indexes the video list as it stood when it was written.
        Reading bit *i* as video *i* after an insertion credits the wrong
        episodes — here the special that Cinemeta now lists first, instead of
        the two the user watched.
        """
        original = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        serialized = encode_watched_bitfield(
            original,
            {"tt0903747:1:1", "tt0903747:1:2"},
        )
        current = ["tt0903747:0:1", *original]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": serialized,
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]

        imported_counts, warnings = self._run_import(
            library_items,
            cinemeta_videos={"tt0903747": current},
        )

        self.assertEqual(warnings, "")
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 2)
        self.assertEqual(
            set(
                Episode.objects.filter(item__media_id="1396").values_list(
                    "item__episode_number",
                    flat=True,
                ),
            ),
            {1, 2},
        )

    def test_series_with_an_empty_bitfield_keeps_the_last_watched_episode(self):
        """An empty bitfield asserts nothing, so the fallback still applies.

        Stremio writes one for a series whose state carries a `video_id` and
        `timesWatched` but no per-episode bits — Dexter and Naked Attraction
        are live examples. The anchor resolves, so a decoder that returned the
        empty set would silently drop the only episode the state names.
        """
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "removed": False,
                "temp": False,
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set()),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:3",
                    "timesWatched": 1,
                },
            },
        ]

        imported_counts, warnings = self._run_import(
            library_items,
            cinemeta_videos={"tt0903747": video_ids},
        )

        self.assertEqual(warnings, "")
        self.assertEqual(imported_counts[MediaTypes.EPISODE.value], 1)
        self.assertEqual(
            set(
                Episode.objects.filter(item__media_id="1396").values_list(
                    "item__episode_number",
                    flat=True,
                ),
            ),
            {3},
        )

    def test_series_bitfield_gaps_do_not_complete_season(self):
        """A final watched episode does not hide gaps in the season."""
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 4)]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "state": {
                    "watched": encode_watched_bitfield(
                        video_ids,
                        {"tt0903747:1:1", "tt0903747:1:3"},
                    ),
                    "lastWatched": "2023-01-02T00:00:00Z",
                    "video_id": "tt0903747:1:2",
                },
            },
        ]

        self._run_import(
            library_items,
            cinemeta_videos={"tt0903747": video_ids},
        )

        season = Season.objects.get(item__media_id="1396")
        self.assertEqual(season.status, Status.IN_PROGRESS.value)
        self.assertEqual(
            set(
                Episode.objects.filter(item__media_id="1396").values_list(
                    "item__episode_number",
                    flat=True,
                ),
            ),
            {1, 3},
        )

    def test_existing_season_completion_does_not_fan_out_unwatched_episodes(self):
        """Stremio completion never creates episodes absent from its bitfield."""
        video_ids = [f"tt0903747:1:{episode}" for episode in range(1, 5)]
        first_sync_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "state": {
                    "watched": encode_watched_bitfield(
                        video_ids,
                        {"tt0903747:1:1", "tt0903747:1:2"},
                    ),
                    "lastWatched": "2023-01-01T00:00:00Z",
                },
            },
        ]
        self._run_import(
            first_sync_items,
            cinemeta_videos={"tt0903747": video_ids},
            tmdb_tv_with_seasons=fake_tv_with_seasons_with_future_episode,
        )

        second_sync_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Breaking Bad",
                "state": {
                    "watched": encode_watched_bitfield(
                        video_ids,
                        {
                            "tt0903747:1:1",
                            "tt0903747:1:2",
                            "tt0903747:1:3",
                        },
                    ),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]
        self._run_import(
            second_sync_items,
            cinemeta_videos={"tt0903747": video_ids},
            tmdb_tv_with_seasons=fake_tv_with_seasons_with_future_episode,
        )

        season = Season.objects.get(item__media_id="1396")
        self.assertEqual(season.status, Status.COMPLETED.value)
        self.assertEqual(Episode.objects.filter(item__media_id="1396").count(), 3)
        self.assertEqual(
            set(
                Episode.objects.filter(item__media_id="1396").values_list(
                    "item__episode_number",
                    flat=True,
                ),
            ),
            {1, 2, 3},
        )

    def test_exact_anime_series_uses_grouped_buckets(self):
        """An exact anime match imports Stremio history into grouped buckets."""
        video_ids = ["tt0903747:1:1"]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Anime Show",
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]
        match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre",
            tmdb_id="1396",
            tvdb_id="7001",
            mal_ids=("12345",),
        )

        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=match,
        ):
            imported_counts, warnings = self._run_import(
                library_items,
                cinemeta_videos={"tt0903747": video_ids},
            )

        self.assertEqual(warnings, "")
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(
            Item.objects.get(media_id="1396", media_type=MediaTypes.TV.value)
            .library_media_type,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            Item.objects.get(
                media_id="1396",
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ).library_media_type,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            Item.objects.get(
                media_id="1396",
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=1,
            ).library_media_type,
            MediaTypes.ANIME.value,
        )

    def test_mal_preferring_user_skips_the_series_rather_than_importing_to_tv(self):
        """A TMDB series cannot populate a flat MAL library, so skip it.

        Importing it as TV instead would track the show in both libraries -
        the duplicate this whole rule exists to prevent.
        """
        self.user.anime_metadata_source_default = Sources.MAL.value
        self.user.save(update_fields=["anime_metadata_source_default"])

        video_ids = ["tt0903747:1:1"]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Anime Show",
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]
        match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre",
            tmdb_id="1396",
            mal_ids=("12345",),
        )

        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=match,
        ):
            _, warnings = self._run_import(
                library_items,
                cinemeta_videos={"tt0903747": video_ids},
            )

        self.assertIn("skipped", warnings)
        self.assertFalse(
            Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.TV.value,
            ).exists(),
        )
        self.assertEqual(TV.objects.filter(user=self.user).count(), 0)

    def test_existing_grouped_home_wins_when_the_snapshot_failed_to_load(self):
        """Stickiness must survive a mapping outage, or the show splits in two."""
        grouped_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Show",
            image="",
        )
        # Already Completed, so the sync has no forward progress to write and
        # cannot trip the completion fan-out.
        TV.objects.create(
            item=grouped_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        video_ids = ["tt0903747:1:1"]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Anime Show",
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
        ]

        with patch(
            "integrations.anime_mapping.load_mapping_snapshot",
            side_effect=OSError("mapping unavailable"),
        ), patch(
            "app.services.grouped_anime.classify_tv_metadata",
        ) as mock_classify:
            self._run_import(
                library_items,
                cinemeta_videos={"tt0903747": video_ids},
            )

        # The classifier never ran, yet the show stayed in the anime bucket.
        mock_classify.assert_not_called()
        grouped_item.refresh_from_db()
        self.assertEqual(
            grouped_item.library_media_type,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            Item.objects.filter(
                media_id="1396",
                media_type=MediaTypes.TV.value,
            ).count(),
            1,
        )

    def test_one_run_does_not_open_both_a_grouped_and_a_flat_home(self):
        """Rows are buffered until the end of a run, so the cache must carry it.

        A series entry and a kitsu entry for the same show would otherwise each
        create their own home and never see the other.
        """
        video_ids = ["tt0903747:1:1"]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Anime Show",
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
            {
                "_id": "kitsu:12345",
                "type": "series",
                "name": "Anime Show",
                "state": {"lastWatched": "2023-01-03T00:00:00Z"},
            },
        ]
        match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre",
            tmdb_id="1396",
            mal_ids=("12345",),
        )

        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=match,
        ), patch.object(
            stremio.StremioImporter,
            "_resolve_mal_id",
            return_value=12345,
        ):
            _, warnings = self._run_import(
                library_items,
                cinemeta_videos={"tt0903747": video_ids},
            )

        self.assertIn("already imported as grouped anime", warnings)
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 0)
        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)

    def test_two_entries_promoted_to_same_grouped_anime_show_do_not_duplicate_season(
        self,
    ):
        """Two Stremio entries unified by grouped-anime promotion share one Season.

        Regression test for #1003: when grouped-anime promotion unifies two
        distinct Stremio library entries onto the same TMDB show/season
        (e.g. multiple MAL seasons collapsed into one mapping_group_key),
        the importer must not queue two Season rows that collide on
        (related_tv, item) at bulk insert time.
        """
        video_ids = ["tt0903747:1:1"]
        other_video_ids = ["tt9999999:1:1"]
        library_items = [
            {
                "_id": "tt0903747",
                "type": "series",
                "name": "Anime Show Part 1",
                "state": {
                    "watched": encode_watched_bitfield(video_ids, set(video_ids)),
                    "lastWatched": "2023-01-02T00:00:00Z",
                },
            },
            {
                "_id": "tt9999999",
                "type": "series",
                "name": "Anime Show Part 2",
                "state": {
                    "watched": encode_watched_bitfield(
                        other_video_ids,
                        set(other_video_ids),
                    ),
                    "lastWatched": "2023-01-03T00:00:00Z",
                },
            },
        ]

        def tmdb_find_same_show(imdb_id, external_source):
            if imdb_id in {"tt0903747", "tt9999999"}:
                return {
                    "tv_results": [
                        {"id": 1396, "name": "Anime Show", "poster_path": "/bb.jpg"},
                    ],
                }
            return {}

        match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre_multiple_mal_seasons",
            tmdb_id="1396",
            tvdb_id="7001",
            mal_ids=("12345", "67890"),
        )

        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=match,
        ):
            _, warnings = self._run_import(
                library_items,
                cinemeta_videos={
                    "tt0903747": video_ids,
                    "tt9999999": other_video_ids,
                },
                tmdb_find=tmdb_find_same_show,
            )

        self.assertEqual(warnings, "")
        self.assertEqual(
            TV.objects.filter(item__media_id="1396").count(),
            1,
        )
        self.assertEqual(
            Season.objects.filter(
                item__media_id="1396",
                item__season_number=1,
            ).count(),
            1,
        )

        # A retry against the now-persisted library must stay idempotent.
        with patch(
            "app.services.grouped_anime.classify_tv_metadata",
            return_value=match,
        ):
            self._run_import(
                library_items,
                cinemeta_videos={
                    "tt0903747": video_ids,
                    "tt9999999": other_video_ids,
                },
                tmdb_find=tmdb_find_same_show,
            )

        self.assertEqual(TV.objects.filter(item__media_id="1396").count(), 1)
        self.assertEqual(
            Season.objects.filter(
                item__media_id="1396",
                item__season_number=1,
            ).count(),
            1,
        )

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

        historical_end_date = parse_datetime("2022-12-01T00:00:00Z")
        first_episode = Episode.objects.get(
            item__media_id="1396",
            item__episode_number=1,
        )
        Episode.objects.filter(pk=first_episode.pk).update(
            end_date=historical_end_date,
        )

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

        episodes = {
            episode.item.episode_number: episode
            for episode in Episode.objects.filter(item__media_id="1396")
        }
        self.assertEqual(episodes[1].end_date, historical_end_date)
        self.assertEqual(
            episodes[2].end_date,
            parse_datetime("2023-01-02T00:00:00Z"),
        )

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

    def test_invalid_session_marks_connection_broken(self):
        """Stremio's "Session does not exist" means the auth key is dead."""
        response = {"error": {"message": "Session does not exist", "code": 1}}
        with (
            patch("integrations.imports.stremio.services.api_request", return_value=response),
            self.assertRaises(helpers.ConnectionAuthError),
        ):
            stremio.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("Session does not exist", self.account.last_error_message)

    def test_other_api_error_records_error_without_breaking(self):
        """Any other envelope error says nothing about the auth key."""
        response = {"error": {"message": "Internal error", "code": 26}}
        with (
            patch("integrations.imports.stremio.services.api_request", return_value=response),
            self.assertRaises(helpers.MediaImportError),
        ):
            stremio.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertIn("Internal error", self.account.last_error_message)

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
