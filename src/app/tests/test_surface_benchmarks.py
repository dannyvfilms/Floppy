"""Benchmark every page surface: time, queries and outbound HTTP per load.

Outbound HTTP is the number that matters most on a real instance: each
attempted provider call is a network round trip (or a timeout) the viewer
waits on. Ordinary tests block external HTTP, so an attempt here fails the
way an unreachable provider does in production, and this module counts it.

Run with ``scripts/test.sh --slow app.tests.test_surface_benchmarks``. Set
``FLOPPY_SURFACE_BENCH_OUT=/path/results.json`` to keep the numbers for a
before/after comparison.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from celery.app.task import Task
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import (
    Album,
    Artist,
    Item,
    MediaTypes,
    Music,
    PodcastEpisode,
    PodcastShow,
    Sources,
    Status,
)
from app.tests.test_query_counts import (
    seed_anime_library,
    seed_game_library,
    seed_movie_library,
    seed_tv_library,
)
from lists.models import CustomList, CustomListItem
from users.home_screen import ensure_home_screen_rows
from users.models import HomeScreenRow

WARM_RUNS = 3


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.WARNING)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


class _OutboundCounter:
    """Count every requests-level HTTP attempt made while active."""

    def __init__(self):
        self.hosts: list[str] = []
        self._original = None

    def __enter__(self):
        self._original = requests.sessions.Session.request
        original = self._original
        hosts = self.hosts

        def counting_request(session, method, url, *args, **kwargs):
            hosts.append(urlsplit(str(url)).hostname or "?")
            return original(session, method, url, *args, **kwargs)

        requests.sessions.Session.request = counting_request
        return self

    def __exit__(self, *exc):
        requests.sessions.Session.request = self._original


class _QueuedTasks:
    """Record tasks a request queues without running them.

    Test settings run Celery eagerly, which would bill a background task's
    work to the page that queued it. Production hands it to a worker, so the
    page cost here is the queueing, and the task names are reported.
    """

    def __init__(self):
        self.names: list[str] = []
        self._original = None

    def __enter__(self):
        self._original = Task.apply_async
        names = self.names

        def record_apply_async(task, *args, **kwargs):
            names.append(task.name)

        Task.apply_async = record_apply_async
        return self

    def __exit__(self, *exc):
        Task.apply_async = self._original


@tag("slow", "benchmark")
class SurfaceBenchmarkTests(TestCase):
    """Print cold and warm costs for every page a user can load."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="surfacebench",
            password="12345",
        )
        for flag in (
            "tv_enabled",
            "movie_enabled",
            "anime_enabled",
            "game_enabled",
            "music_enabled",
            "podcast_enabled",
        ):
            setattr(cls.user, flag, True)
        cls.user.save()
        seed_tv_library(cls.user)
        seed_movie_library(cls.user)
        seed_anime_library(cls.user)
        seed_game_library(cls.user)

        played_at = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        cls.artist = Artist.objects.create(
            name="Bench Artist",
            image="https://example.com/artist.jpg",
        )
        album = Album.objects.create(
            title="Bench Album",
            artist=cls.artist,
            image="https://example.com/album.jpg",
        )
        for track_index in range(12):
            track = Item.objects.create(
                media_id=f"bench-track-{track_index}",
                source=Sources.MUSICBRAINZ.value,
                media_type=MediaTypes.MUSIC.value,
                title=f"Bench Track {track_index}",
                image="https://example.com/album.jpg",
                runtime_minutes=4,
            )
            Music.objects.create(
                user=cls.user,
                item=track,
                artist=cls.artist,
                album=album,
                status=Status.COMPLETED.value,
                start_date=played_at,
                end_date=played_at,
            )

        cls.podcast_show = PodcastShow.objects.create(
            podcast_uuid="bench-show",
            title="Bench Podcast",
            rss_feed_url="https://feeds.example.com/bench.xml",
        )
        for episode_index in range(10):
            PodcastEpisode.objects.create(
                show=cls.podcast_show,
                episode_uuid=f"bench-episode-{episode_index}",
                title=f"Bench Episode {episode_index}",
            )

        cls.custom_list = CustomList.objects.create(
            name="Bench List",
            owner=cls.user,
        )
        CustomListItem.objects.bulk_create(
            [
                CustomListItem(
                    custom_list=cls.custom_list, item=item, added_by=cls.user
                )
                for item in Item.objects.filter(
                    media_type__in=[MediaTypes.MOVIE.value, MediaTypes.TV.value],
                ).order_by("id")[:12]
            ],
        )
        ensure_home_screen_rows(cls.user)
        cls.home_row = (
            HomeScreenRow.objects.filter(user=cls.user, enabled=True)
            .order_by("media_type", "position", "id")
            .first()
        )

        cls.movie_item = Item.objects.filter(media_type=MediaTypes.MOVIE.value).first()
        cls.tv_item = Item.objects.filter(media_type=MediaTypes.TV.value).first()

    def _surfaces(self) -> list[tuple[str, str, dict]]:
        movie = self.movie_item
        tv = self.tv_item
        htmx = {"HTTP_HX_REQUEST": "true"}
        return [
            ("home", "/", {}),
            (
                "home_row",
                reverse("home_row_fragment", args=[self.home_row.id]),
                htmx,
            ),
            ("medialist_movie", reverse("medialist", args=["movie"]), {}),
            ("medialist_tv", reverse("medialist", args=["tv"]), {}),
            ("medialist_anime", reverse("medialist", args=["anime"]), {}),
            ("medialist_game", reverse("medialist", args=["game"]), {}),
            ("medialist_season", reverse("medialist", args=["season"]), {}),
            ("medialist_music", reverse("medialist", args=["music"]), {}),
            (
                "details_movie",
                reverse(
                    "media_details",
                    args=[movie.source, "movie", movie.media_id, "bench"],
                ),
                {},
            ),
            (
                "details_tv",
                reverse("media_details", args=[tv.source, "tv", tv.media_id, "bench"]),
                {},
            ),
            (
                "season_details",
                reverse("season_details", args=[tv.source, tv.media_id, "bench", 1]),
                {},
            ),
            (
                "details_podcast",
                reverse(
                    "media_details",
                    args=["pocketcasts", "podcast", "bench-show", "bench"],
                ),
                {},
            ),
            (
                "music_artist",
                reverse(
                    "music_artist_details",
                    args=[self.artist.id, "bench-artist"],
                ),
                {},
            ),
            ("history", reverse("history"), {}),
            ("statistics", reverse("statistics"), {}),
            ("statistics_talent", reverse("statistics_talent_fragment"), htmx),
            ("cache_status", reverse("cache_status"), {}),
            ("search", reverse("search") + "?media_type=movie&q=bench", {}),
            ("discover", reverse("discover"), {}),
            ("lists", reverse("lists"), {}),
            (
                "list_detail",
                reverse("list_detail", args=[self.custom_list.public_reference]),
                {},
            ),
            ("calendar", reverse("calendar"), {}),
            (
                "calendar_download",
                reverse("download_calendar", args=[self.user.token]),
                {},
            ),
            ("collection", reverse("collection_list"), {}),
            ("tags", reverse("tag_index"), {}),
            ("providers", reverse("providers"), {}),
            ("jsi18n", reverse("javascript-catalog"), {}),
            ("serviceworker", reverse("service_worker"), {}),
        ]

    def _measure(self, path: str, **request_kwargs) -> dict[str, object]:
        # The debug query log is a bounded deque; a heavy page can overflow
        # it and make the next capture read as zero.
        connection.queries_log.clear()
        with (
            _QueuedTasks() as queued,
            _OutboundCounter() as outbound,
            CaptureQueriesContext(connection) as captured,
        ):
            started = time.perf_counter()
            response = self.client.get(path, **request_kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "status": response.status_code,
            "ms": elapsed_ms,
            "queries": len(captured.captured_queries),
            "outbound": len(outbound.hosts),
            "outbound_hosts": sorted(set(outbound.hosts)),
            "queued": sorted(set(queued.names)),
            "bytes": len(getattr(response, "content", b"") or b""),
        }

    def test_surface_benchmarks(self):
        results = []
        for label, path, request_kwargs in self._surfaces():
            cache.clear()
            self.client.force_login(self.user)
            cold = self._measure(path, **request_kwargs)
            warm_runs = [
                self._measure(path, **request_kwargs) for _ in range(WARM_RUNS)
            ]
            warm = warm_runs[-1]
            results.append(
                {
                    "surface": label,
                    "status": cold["status"],
                    "cold_ms": round(cold["ms"], 1),
                    "warm_ms": round(statistics.median(r["ms"] for r in warm_runs), 1),
                    "cold_queries": cold["queries"],
                    "warm_queries": warm["queries"],
                    "cold_outbound": cold["outbound"],
                    "warm_outbound": warm["outbound"],
                    "outbound_hosts": sorted(
                        set(cold["outbound_hosts"]) | set(warm["outbound_hosts"])
                    ),
                    "queued": cold["queued"],
                    "bytes": cold["bytes"],
                },
            )

        out_path = os.environ.get("FLOPPY_SURFACE_BENCH_OUT")
        if out_path:
            with Path(out_path).open("w", encoding="utf-8") as handle:
                json.dump(results, handle, indent=1, sort_keys=True)
        print(json.dumps(results, sort_keys=True))

        # 503 is the designed "provider unavailable" page: provider HTTP is
        # blocked here, so a page that cannot render without it reports that.
        for result in results:
            self.assertIn(result["status"], {200, 302, 400, 503}, result["surface"])
