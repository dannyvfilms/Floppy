"""Watchlist only and Collection only must mean the same thing for every source (#1133).

Plex and the Trakt collection CSV already read these modes. Every other source
used to treat them like a plain re-import that updates whatever it finds.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    Anime,
    CollectionEntry,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from integrations.imports import helpers, mal
from integrations.imports.trakt import TraktImporter
from integrations.tasks._media_imports import import_media

MOCK_DATA = Path(__file__).resolve().parent / "mock_data"
SHOW_ID = "1396"
MOVIE_ID = "603"


def _make_movie(user, media_id, status):
    item, _ = Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        defaults={"title": "The Matrix"},
    )
    return Movie.objects.create(item=item, user=user, status=status)


def _fake_importer(source, rows):
    """Build an importer that queues ``rows`` the way a real source does."""

    def importer(_identifier, user, mode):
        bulk_media = {MediaTypes.MOVIE.value: []}
        for media_id, status in rows:
            item, _ = Item.objects.get_or_create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                defaults={"title": media_id},
            )
            bulk_media[MediaTypes.MOVIE.value].append(
                Movie(item=item, user=user, status=status),
            )
        helpers.bulk_create_media(bulk_media, user)
        importer.seen_mode = mode
        return {MediaTypes.MOVIE.value: len(rows)}, ""

    importer.__module__ = f"integrations.imports.{source}"
    return importer


class SharedModeHandlingTests(TestCase):
    """Sources that have no stages of their own."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    def test_watchlist_keeps_only_planned_entries_and_runs_as_new(self):
        """Only the planned title lands, and it is handed over as a "new" import."""
        importer = _fake_importer(
            "steam",
            [("1", Status.PLANNING.value), ("2", Status.COMPLETED.value)],
        )

        import_media(importer, None, self.user.id, "watchlist")

        self.assertEqual(importer.seen_mode, "new")
        self.assertEqual(
            list(Movie.objects.filter(user=self.user).values_list("item__media_id", "status")),
            [("1", Status.PLANNING.value)],
        )

    def test_the_filter_does_not_leak_into_the_next_import(self):
        """A later "new" import saves everything again."""
        importer = _fake_importer("steam", [("2", Status.COMPLETED.value)])

        import_media(importer, None, self.user.id, "watchlist")
        import_media(importer, None, self.user.id, "new")

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    def test_collection_only_is_skipped_for_a_source_without_a_collection(self):
        """Nothing runs, and the message says why."""
        importer = _fake_importer("steam", [("1", Status.PLANNING.value)])

        message = import_media(importer, None, self.user.id, "update_collection")

        self.assertIn("no collection data", message)
        self.assertFalse(hasattr(importer, "seen_mode"))
        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    def test_a_source_that_reads_the_modes_itself_gets_them_untouched(self):
        """Plex, Trakt and the collection CSV keep their own rules."""
        for source in ("plex", "trakt_collection", "mdblist"):
            with self.subTest(source=source):
                importer = _fake_importer(source, [])

                import_media(importer, None, self.user.id, "update_collection")

                self.assertEqual(importer.seen_mode, "update_collection")

    def test_wetrakr_has_no_collection(self):
        """WeTrakr exports carry no ownership data."""
        importer = _fake_importer("wetrakr", [])

        message = import_media(importer, None, self.user.id, "update_collection")

        self.assertIn("no collection data", message)


class MyAnimeListModeTests(TestCase):
    """A real source end to end: MyAnimeList lists have a Plan to Watch status."""

    def setUp(self):
        """Create a user and canned MyAnimeList responses."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    def _responses(self):
        responses = []
        for name in ("import_mal_anime.json", "import_mal_manga.json"):
            response = MagicMock()
            response.json.return_value = json.loads((MOCK_DATA / name).read_text())
            responses.append(response)
        return responses

    def test_watchlist_imports_only_plan_to_watch(self):
        """Watching, finished and paused entries stay out."""
        with patch("requests.Session.get", side_effect=self._responses()):
            import_media(mal.importer, "someone", self.user.id, "watchlist")

        statuses = set(
            Anime.objects.filter(user=self.user).values_list("status", flat=True),
        )
        self.assertEqual(statuses, {Status.PLANNING.value})

    def test_watchlist_leaves_a_tracked_entry_alone(self):
        """A title already tracked keeps its status and score."""
        with patch("requests.Session.get", side_effect=self._responses()):
            import_media(mal.importer, "someone", self.user.id, "new")
        completed = Anime.objects.filter(
            user=self.user,
            status=Status.COMPLETED.value,
        ).first()
        completed.score = 9
        completed.save()
        planned_before = Anime.objects.filter(user=self.user).count()

        with patch("requests.Session.get", side_effect=self._responses()):
            import_media(mal.importer, "someone", self.user.id, "watchlist")

        completed.refresh_from_db()
        self.assertEqual((completed.status, completed.score), (Status.COMPLETED.value, 9))
        self.assertEqual(Anime.objects.filter(user=self.user).count(), planned_before)

    def test_collection_only_is_skipped(self):
        """MyAnimeList has no collection, so nothing is fetched."""
        with patch("requests.Session.get") as get:
            message = import_media(mal.importer, "someone", self.user.id, "update_collection")

        get.assert_not_called()
        self.assertIn("no collection data", message)


class _PlainTraktImporter(TraktImporter):
    """Runs Trakt's stages in-process, without the durable run bookkeeping."""


def _trakt_feed(_importer, endpoint, *_args, **_kwargs):
    show = {"title": "Breaking Bad", "ids": {"tmdb": int(SHOW_ID)}}
    movie = {"title": "The Matrix", "ids": {"tmdb": int(MOVIE_ID)}}
    when = "2026-01-01T00:00:00.000Z"
    if "history" in endpoint:
        return [{"type": "movie", "movie": movie, "watched_at": when}]
    if "watchlist" in endpoint:
        return [{"type": "show", "show": show, "listed_at": when}]
    if "collection/movies" in endpoint:
        return [
            {
                "collected_at": when,
                "movie": movie,
                "metadata": {"resolution": "uhd_4k"},
            },
        ]
    return []


def _trakt_metadata(media_type, *_args, **_kwargs):
    title = "Breaking Bad" if media_type == MediaTypes.TV.value else "The Matrix"
    return {"title": title, "image": "", "max_progress": 1}


class TraktModeTests(TestCase):
    """Trakt runs only the stage the mode names."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(username="u", password="p")

    def _run(self, mode):
        with (
            patch.object(
                _PlainTraktImporter,
                "_get_paginated_data",
                autospec=True,
                side_effect=_trakt_feed,
            ),
            patch.object(_PlainTraktImporter, "_make_api_request", return_value={}),
            patch.object(
                _PlainTraktImporter,
                "_get_metadata",
                side_effect=_trakt_metadata,
            ),
            patch("app.providers.trakt.is_configured", return_value=False),
        ):
            _PlainTraktImporter("u", self.user, mode).import_data()

    def test_watchlist_adds_planned_titles_and_no_history(self):
        """The watched movie is not imported; the watchlist show is Planning."""
        self._run("watchlist")

        self.assertFalse(Movie.objects.filter(user=self.user).exists())
        self.assertEqual(TV.objects.get(user=self.user).status, Status.PLANNING.value)
        self.assertFalse(CollectionEntry.objects.filter(user=self.user).exists())

    def test_watchlist_leaves_a_tracked_show_alone(self):
        """A show already being watched is not reset to Planning."""
        item = Item.objects.create(
            media_id=SHOW_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        TV.objects.create(item=item, user=self.user, status=Status.IN_PROGRESS.value)

        self._run("watchlist")

        self.assertEqual(TV.objects.get(user=self.user).status, Status.IN_PROGRESS.value)

    def test_update_collection_only_writes_collection_entries(self):
        """Owned copies are recorded; history and the watchlist are not read."""
        self._run("update_collection")

        self.assertEqual(
            CollectionEntry.objects.get(user=self.user).resolution,
            "uhd_4k",
        )
        self.assertFalse(Movie.objects.filter(user=self.user).exists())
        self.assertFalse(TV.objects.filter(user=self.user).exists())

    def test_update_collection_refreshes_an_existing_entry(self):
        """Same contract as the Trakt collection CSV: it updates what is there."""
        item = Item.objects.create(
            media_id=MOVIE_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
        )
        CollectionEntry.objects.create(user=self.user, item=item, resolution="hd_720p")

        self._run("update_collection")

        self.assertEqual(
            CollectionEntry.objects.get(user=self.user, item=item).resolution,
            "uhd_4k",
        )

    def test_a_full_import_still_runs_every_stage(self):
        """The default mode is unchanged."""
        self._run("new")

        self.assertTrue(Movie.objects.filter(user=self.user).exists())
        self.assertTrue(TV.objects.filter(user=self.user).exists())
        self.assertTrue(CollectionEntry.objects.filter(user=self.user).exists())
