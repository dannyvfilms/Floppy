"""Writes that skip model signals still refresh what the user sees next.

Two halves:

* ``ListedSitesGuardTests`` scans the source tree for tracking writes that
  skip signals and fails when one is not in
  ``app.bulk_write_refresh.BULK_WRITE_SITES``, or when a row there no longer
  matches a write.
* The behaviour tests warm a user's library page, Home and a Statistics range,
  make the change through its public entry (a view or a service), and check the
  next read cannot be served from before the change: the warmed page entries
  are gone, Statistics counted a change, and History retired its cached days.

Contract: docs/architecture/view-caches.md ("When a write path must call it").
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app import bulk_write_refresh, cache_utils
from app.history_cache_utils import HISTORY_LOGGING_STYLES, _current_history_era
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    StatisticsSyncState,
    Status,
)
from app.services.metadata_resolution import MetadataResolutionResult
from app.tests import bulk_write_scan
from app.tests.views.test_episode_bulk_save import (
    _season_episode,
    _tv_base_payload,
    _tv_with_seasons_payload,
)
from users.models import HomeScreenRow

UNLISTED_MESSAGE = (
    "This writes tracking rows without a model save. Say in "
    "app/bulk_write_refresh.py (BULK_WRITE_SITES) how the library pages, "
    "Statistics and History learn about it. See docs/architecture/view-caches.md."
)


class ListedSitesGuardTests(TestCase):
    """Every bulk tracking write is listed with how each reader refreshes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sites = bulk_write_scan.scan()

    def test_every_site_is_listed(self):
        listed = set(bulk_write_refresh.BULK_WRITE_SITES)
        unlisted = [site for site in self.sites if site.key not in listed]
        if unlisted:
            self.fail(
                UNLISTED_MESSAGE
                + "\n"
                + "\n".join(
                    f"  {site.module}:{site.line} {site.function} writes "
                    f"{site.model} ({site.kind})"
                    for site in unlisted
                )
            )

    def test_every_row_still_names_a_write(self):
        found = bulk_write_scan.site_keys(self.sites)
        stale = sorted(set(bulk_write_refresh.BULK_WRITE_SITES) - found)
        if stale:
            self.fail(
                "These rows in app/bulk_write_refresh.py no longer match a write "
                "(moved, renamed or removed). Update or delete them:\n"
                + "\n".join(f"  {row}" for row in stale)
            )

    def test_every_row_answers_for_each_reader(self):
        for key, refresh in bulk_write_refresh.BULK_WRITE_SITES.items():
            with self.subTest(site=key):
                for reader in bulk_write_refresh.READERS:
                    self.assertTrue(
                        getattr(refresh, reader).strip(),
                        f"{key} does not say how {reader} learns about the write.",
                    )

    def test_scan_finds_a_new_queryset_update(self):
        """The scan sees the shape the guard exists for."""
        import ast

        source = (
            "def view(request):\n"
            "    Movie.objects.filter(user=request.user).update(status='Completed')\n"
            "    qs = Episode.objects.filter(pk=1)\n"
            "    qs.update(score=3)\n"
            "    seasons = Season.objects.filter(pk=1)\n"
            "    seasons.bulk_update([], ['status'])\n"
            "    settings = {}\n"
            "    settings.update(a=1)\n"
        )
        scanner = bulk_write_scan._FunctionScanner(
            "app/probe.py",
            bulk_write_scan.tracker_model_names(),
            {},
        )
        scanner.visit(ast.parse(source))
        self.assertEqual(
            sorted((site.function, site.model) for site in scanner.sites),
            [("view", "Episode"), ("view", "Movie"), ("view", "Season")],
        )


def _resolution(media_id):
    return MetadataResolutionResult(
        display_provider=Sources.TMDB.value,
        identity_provider=Sources.TMDB.value,
        mapping_status="identity",
        header_metadata={},
        grouped_preview=None,
        provider_media_id=media_id,
    )


class ReaderRefreshMixin:
    """Warm the readers, make a change, and check none of them can go stale."""

    media_list_types = (MediaTypes.TV.value,)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="bulk-refresh", password="12345"
        )
        self.client.force_login(self.user)

    def warm_readers(self):
        """Read the library pages and Home so their entries are cached."""
        for media_type in self.media_list_types:
            self.assertEqual(
                self.client.get(reverse("medialist", args=[media_type])).status_code,
                200,
            )
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        # Home sends its shelves as separate requests once the page is up.
        for row_id in HomeScreenRow.objects.filter(
            user=self.user, enabled=True
        ).values_list("id", flat=True)[:3]:
            self.client.get(reverse("home_row_fragment", args=[row_id]))
        warmed = {
            "library page": self._registered(
                cache_utils._media_list_registry_key(self.user.id)
            ),
            "Home": self._registered(cache_utils._home_row_registry_key(self.user.id)),
        }
        for reader, keys in warmed.items():
            self.assertTrue(keys, f"Reading the {reader} cached nothing to go stale.")
        return {
            "views": warmed,
            "statistics": self._statistics_generation(),
            "history": self._history_eras(),
        }

    def assert_readers_refreshed(self, warmed, what, *, history=True, statistics=True):
        for reader, keys in warmed["views"].items():
            still_cached = [key for key in keys if cache.get(key) is not None]
            self.assertFalse(
                still_cached,
                f"After {what}, the {reader} would still show the cached copy "
                "from before the change.",
            )
        if statistics:
            self.assertGreater(
                self._statistics_generation(),
                warmed["statistics"],
                f"After {what}, Statistics was not told anything changed.",
            )
        if history:
            self.assertNotEqual(
                self._history_eras(),
                warmed["history"],
                f"After {what}, History kept its cached days from before the change.",
            )

    def _registered(self, registry_key):
        client = cache_utils._registry_client()
        if client is not None:
            members = client.smembers(cache.make_key(registry_key))
            keys = [key.decode() if isinstance(key, bytes) else key for key in members]
        else:
            keys = cache.get(registry_key) or ()
        return [key for key in keys if cache.get(key) is not None]

    def _statistics_generation(self):
        return (
            StatisticsSyncState.objects.filter(user=self.user)
            .values_list("generation", flat=True)
            .first()
            or 0
        )

    def _history_eras(self):
        return {
            style: _current_history_era(self.user.id, style)
            for style in HISTORY_LOGGING_STYLES
        }


SEASONS = [
    {
        "season_number": 1,
        "season_title": "Season 1",
        "episodes": [
            _season_episode(1, air_date="2024-01-01"),
            _season_episode(2, air_date="2024-01-02"),
        ],
    },
]


@override_settings(TRACK_TIME=True)
class BulkEpisodeSaveRefreshTests(ReaderRefreshMixin, TestCase):
    """Track episodes in bulk from a show's page."""

    def setUp(self):
        super().setUp()
        base = _tv_base_payload(
            "1396", Sources.TMDB.value, title="Bulk", seasons=SEASONS
        )
        full = _tv_with_seasons_payload(
            "1396", Sources.TMDB.value, title="Bulk", seasons=SEASONS
        )
        for target, kwargs in (
            (
                "app.providers.services.get_media_metadata",
                {
                    "side_effect": lambda media_type, *_a, **_k: (
                        full if media_type == "tv_with_seasons" else base
                    ),
                },
            ),
            (
                "app.views.metadata_resolution.resolve_detail_metadata",
                {
                    "return_value": _resolution("1396"),
                },
            ),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self):
        return self.client.post(
            reverse("episode_bulk_save") + "?next=/",
            {
                "media_id": "1396",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.TV.value,
                "library_media_type": MediaTypes.TV.value,
                "identity_media_type": "",
                "instance_id": "",
                "return_url": "/",
                "first_season_number": 1,
                "first_episode_number": 1,
                "last_season_number": 1,
                "last_episode_number": 2,
                "write_mode": "add",
                "distribution_mode": "even",
                "start_date": "2024-02-01T00:00",
                "end_date": "2024-02-01T00:00",
            },
            HTTP_HX_REQUEST="true",
        )

    def test_new_show_reaches_every_reader(self):
        warmed = self.warm_readers()
        self.assertEqual(self._post().status_code, 204)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 2
        )
        self.assert_readers_refreshed(warmed, "a bulk episode save")
        self.assertContains(
            self.client.get(reverse("medialist", args=[MediaTypes.TV.value])), "Bulk"
        )

    def test_more_plays_of_a_tracked_show_reach_every_reader(self):
        self.assertEqual(self._post().status_code, 204)
        warmed = self.warm_readers()
        self.assertEqual(self._post().status_code, 204)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 4
        )
        self.assert_readers_refreshed(warmed, "a second bulk episode save")


def _episode_metadata(media_type, *_args, **_kwargs):
    episodes = [
        {
            "episode_number": 1,
            "name": "One",
            "still_path": None,
            "air_date": "2024-01-01",
        },
        {
            "episode_number": 2,
            "name": "Two",
            "still_path": None,
            "air_date": "2024-01-02",
        },
    ]
    if media_type == "tv_with_seasons":
        return {"season/1": {"episodes": episodes}, "season/2": {"episodes": episodes}}
    return {"season_number": 1, "episodes": episodes, "_tvdb_episode_image_map": {}}


class ShowFixtureMixin(ReaderRefreshMixin):
    """A tracked show with one season and one watched episode."""

    def setUp(self):
        super().setUp()
        patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_episode_metadata,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_show(self, *, status=Status.IN_PROGRESS.value, media_id="77"):
        show_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Fixture Show",
        )
        tv = TV.objects.create(item=show_item, user=self.user, status=status)
        season_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Fixture Show",
        )
        season = Season.objects.create(
            item=season_item, user=self.user, related_tv=tv, status=status
        )
        episode_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="One",
            provider_episode_id="legacy-1",
        )
        watch = Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now() - datetime.timedelta(days=2),
        )
        return tv, season, watch


class StopRewatchRefreshTests(ShowFixtureMixin, TestCase):
    """Ending a season's rewatch (also the progress panel's Cancel)."""

    def test_stopping_a_rewatch_reaches_the_library_and_statistics(self):
        _tv, season, _watch = self.make_show()
        Season.objects.filter(pk=season.pk).update(
            rewatch_started_at=timezone.now() - datetime.timedelta(days=1)
        )
        season.refresh_from_db()
        warmed = self.warm_readers()
        season.stop_rewatch()
        season.refresh_from_db()
        self.assertIsNone(season.rewatch_started_at)
        self.assert_readers_refreshed(warmed, "ending a rewatch", history=False)


class EpisodeOrderRefreshTests(ShowFixtureMixin, TestCase):
    """Switching a show to another episode order, and undoing it."""

    def test_order_change_and_undo_reach_every_reader(self):
        from app.services.episode_ordering import (
            apply_change,
            persist_order,
            preview_change,
            revert_change,
        )

        tv, _season, watch = self.make_show(media_id="1396")
        order = persist_order(
            tv.item,
            Sources.TMDB.value,
            "1396",
            "aired",
            "TMDB (Aired)",
            {
                "episodes": [
                    {
                        "provider_episode_id": "new-1",
                        "season_number": 1,
                        "episode_number": 1,
                        "title": "Pilot",
                        "image": "",
                    }
                ]
            },
        )
        preview = preview_change(tv, order)
        warmed = self.warm_readers()
        apply_change(
            tv,
            order,
            token=preview["token"],
            resolutions=[{"watch_ids": [watch.pk], "episode_ids": ["new-1"]}],
        )
        self.assert_readers_refreshed(warmed, "changing the episode order")

        warmed = self.warm_readers()
        revert_change(tv)
        self.assert_readers_refreshed(warmed, "undoing the episode order change")


class ReopenShowRefreshTests(ShowFixtureMixin, TestCase):
    """A completed show reopens when the calendar finds a new season."""

    def test_reopened_show_reaches_the_library_and_statistics(self):
        from types import SimpleNamespace

        from events.calendar.tv import reopen_completed_tv_with_new_seasons

        tv, season, _watch = self.make_show()
        Season.objects.filter(pk=season.pk).update(status=Status.COMPLETED.value)
        new_season_item, _created = Item.objects.get_or_create(
            media_id="77",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            defaults={"title": "Fixture Show"},
        )
        Season.objects.filter(related_tv=tv, item=new_season_item).delete()
        TV.objects.filter(pk=tv.pk).update(status=Status.COMPLETED.value)
        warmed = self.warm_readers()
        reopen_completed_tv_with_new_seasons(
            tv.item,
            [new_season_item],
            [
                SimpleNamespace(
                    item=new_season_item,
                    datetime=timezone.now() + datetime.timedelta(days=30),
                )
            ],
        )
        tv.refresh_from_db()
        self.assertEqual(tv.status, Status.IN_PROGRESS.value)
        self.assert_readers_refreshed(warmed, "reopening a show", history=False)


class MovieFixtureMixin(ReaderRefreshMixin):
    media_list_types = (MediaTypes.MOVIE.value,)

    def make_movie(self, media_id="603", *, status=Status.IN_PROGRESS.value, **fields):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Film {media_id}",
        )
        return Movie.objects.create(item=item, user=self.user, status=status, **fields)


class AutoPauseRefreshTests(MovieFixtureMixin, TestCase):
    """The daily task that pauses items with no recent activity."""

    def test_paused_items_reach_the_library_and_statistics(self):
        from app.services import auto_pause

        movie = self.make_movie()
        Movie.objects.filter(pk=movie.pk).update(
            start_date=timezone.now() - datetime.timedelta(weeks=30),
        )
        self.user.auto_pause_in_progress_enabled = True
        self.user.auto_pause_rules = [{"library": "all", "weeks": 1}]
        self.user.save()
        warmed = self.warm_readers()
        self.assertEqual(auto_pause._process_user_rules(self.user, timezone.now()), 1)
        movie.refresh_from_db()
        self.assertEqual(movie.status, Status.PAUSED.value)
        self.assert_readers_refreshed(warmed, "auto-pause", history=False)


class BulkStatusRefreshTests(MovieFixtureMixin, TestCase):
    """Set the status of several selected items from the library page."""

    def test_bulk_status_reaches_every_reader(self):
        movie = self.make_movie()
        warmed = self.warm_readers()
        response = self.client.post(
            reverse("bulk_status_update"),
            {"item_ids": [movie.item_id], "status": Status.COMPLETED.value},
        )
        self.assertEqual(response.status_code, 200)
        movie.refresh_from_db()
        self.assertEqual(movie.status, Status.COMPLETED.value)
        # A status with no date is not a History entry.
        self.assert_readers_refreshed(warmed, "a bulk status update", history=False)


class ImportRefreshTests(MovieFixtureMixin, TestCase):
    """Importers write in bulk; the import task announces once."""

    def _import(self, importer, *, scoped):
        from integrations.tasks import _media_imports

        with (
            patch.object(
                _media_imports, "DAY_SCOPED_IMPORTERS", (importer,) if scoped else ()
            ),
            patch.object(_media_imports.events.tasks.reload_calendar, "delay"),
        ):
            _media_imports.import_media(importer, None, self.user.id, "new")

    def _importer(self, rows):
        from integrations.imports import helpers

        def run(identifier, user, mode, **kwargs):
            helpers.bulk_create_media({MediaTypes.MOVIE.value: rows}, user)
            return {MediaTypes.MOVIE.value: len(rows)}, ""

        return run

    def _new_movie(self, media_id):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=f"Imported {media_id}",
        )
        return Movie(
            user=self.user,
            item=item,
            status=Status.COMPLETED.value,
            end_date=timezone.now() - datetime.timedelta(days=3),
        )

    def test_recurring_import_reaches_every_reader(self):
        self.make_movie()
        warmed = self.warm_readers()
        self._import(self._importer([self._new_movie("1")]), scoped=True)
        self.assert_readers_refreshed(warmed, "a recurring import")
        self.assertContains(
            self.client.get(reverse("medialist", args=[MediaTypes.MOVIE.value])),
            "Imported 1",
        )

    def test_one_off_import_reaches_every_reader(self):
        self.make_movie()
        warmed = self.warm_readers()
        self._import(self._importer([self._new_movie("2")]), scoped=False)
        self.assert_readers_refreshed(warmed, "a file import")

    def test_a_poll_that_found_nothing_clears_nothing(self):
        self.make_movie()
        warmed = self.warm_readers()
        self._import(self._importer([]), scoped=True)
        for reader, keys in warmed["views"].items():
            self.assertTrue(
                all(cache.get(key) is not None for key in keys),
                f"A poll that imported nothing cleared the {reader}.",
            )


class FilmMatchCorrectionRefreshTests(MovieFixtureMixin, TestCase):
    """Fix a wrong match: move a film to the right title."""

    def test_moved_film_reaches_every_reader(self):
        from integrations.match_corrections import (
            apply_match_correction,
            preview_match_correction,
        )

        source = self.make_movie(
            "101",
            status=Status.COMPLETED.value,
            end_date=timezone.now() - datetime.timedelta(days=4),
        ).item
        destination = Item.objects.create(
            media_id="202",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Right Film",
        )
        preview = preview_match_correction(self.user, source, destination)
        warmed = self.warm_readers()
        with patch("app.models.Item.fetch_releases"):
            apply_match_correction(
                self.user, source.pk, destination.pk, preview["token"]
            )
        self.assertTrue(Movie.objects.filter(user=self.user, item=destination).exists())
        self.assert_readers_refreshed(warmed, "a film match correction")
        self.assertContains(
            self.client.get(reverse("medialist", args=[MediaTypes.MOVIE.value])),
            "Right Film",
        )


@override_settings(TRACK_TIME=True)
class BulkShowPlaysRefreshTests(ReaderRefreshMixin, TestCase):
    """Add plays for every aired episode of selected shows."""

    def setUp(self):
        super().setUp()
        from app.services import bulk_show_plays

        for target, kwargs in (
            (
                "app.services.bulk_show_plays.services.get_media_metadata",
                {
                    "side_effect": lambda _route, media_id, source, *_a: (
                        _tv_with_seasons_payload(
                            media_id, source, title="Plays Show", seasons=SEASONS
                        )
                    )
                },
            ),
            (
                "app.services.bulk_show_plays.metadata_resolution.resolve_detail_metadata",
                {"side_effect": lambda *a, **k: _resolution(k["media_id"])},
            ),
            ("app.tasks.enqueue_credits_backfill_items", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertTrue(bulk_show_plays)

    def test_added_plays_reach_every_reader(self):
        item = Item.objects.create(
            media_id="100",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Plays Show",
        )
        TV.objects.create(item=item, user=self.user, status=Status.PLANNING.value)
        warmed = self.warm_readers()
        response = self.client.post(
            reverse("bulk_show_plays_start"),
            {
                "item_ids": [str(item.id)],
                "scope": "aired",
                "existing": "skip",
                "date_mode": "air_date",
                "dry_run": "0",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 2
        )
        self.assert_readers_refreshed(warmed, "adding plays to selected shows")
