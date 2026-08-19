"""Before/after benchmark for the global history API."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
from ast import literal_eval
from collections import Counter
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import tag
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from app import history_cache
from app.history_cache_utils import _normalize_logging_style
from app.models import (
    TV,
    Anime,
    BoardGame,
    Book,
    Comic,
    Episode,
    Game,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Music,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Season,
    Sources,
    Status,
)

RUNS = max(int(os.environ.get("HISTORY_BENCHMARK_RUNS", "7")), 7)


def _percentile(values, percentile):
    ordered = sorted(values)
    index = min(math.ceil(percentile * len(ordered)) - 1, len(ordered) - 1)
    return ordered[max(index, 0)]


def _summary(samples):
    return {
        "count": len(samples),
        "duration_ms_median": round(statistics.median(s["duration_ms"] for s in samples), 2),
        "duration_ms_p90": round(_percentile([s["duration_ms"] for s in samples], 0.9), 2),
        "duration_ms_min": round(min(s["duration_ms"] for s in samples), 2),
        "duration_ms_max": round(max(s["duration_ms"] for s in samples), 2),
        "query_count_median": round(statistics.median(s["query_count"] for s in samples), 2),
        "sql_time_ms_median": round(statistics.median(s["sql_time_ms"] for s in samples), 2),
        "rss_kb_delta_median": round(statistics.median(s["rss_kb_delta"] for s in samples), 2),
        "response_bytes": samples[-1]["response_bytes"],
        "status": samples[-1]["status"],
        "result_day_count": samples[-1]["result_day_count"],
        "entry_counts": samples[-1]["entry_counts"],
        "category_rows_processed": samples[-1]["category_rows_processed"],
        "history_logs": samples[-1].get("history_logs", {}),
    }


@tag("slow", "benchmark")
class HistoryApiBenchmarkTests(APITestCase):
    """Print comparable legacy-builder and optimized API measurements."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="history-benchmark",
            password="12345",
        )
        cls.base_date = datetime(2018, 1, 1, tzinfo=UTC)

        tv_item = Item.objects.create(
            media_id="history-benchmark-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="History Benchmark Show",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=cls.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="history-benchmark-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="History Benchmark Show Season 1",
        )
        season = Season.objects.create(
            item=season_item,
            user=cls.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

        episode_count = 3370
        episode_items = [
            Item(
                media_id="history-benchmark-show",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=index + 1,
                title=f"History Benchmark Episode {index + 1}",
            )
            for index in range(episode_count)
        ]
        episode_items = Item.objects.bulk_create(episode_items, batch_size=1000)
        Episode.objects.bulk_create(
            [
                Episode(
                    item=item,
                    related_season=season,
                    end_date=cls.base_date + timedelta(days=index % 2759),
                )
                for index, item in enumerate(episode_items)
            ],
            batch_size=1000,
        )

        movie_items = Item.objects.bulk_create(
            [
                Item(
                    media_id=f"history-benchmark-movie-{index}",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"History Benchmark Movie {index}",
                )
                for index in range(280)
            ],
            batch_size=1000,
        )
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=cls.user,
                    end_date=cls.base_date + timedelta(
                        days=2758 - (index % 10),
                    ),
                )
                for index, item in enumerate(movie_items)
            ],
            batch_size=1000,
        )

        game_items = Item.objects.bulk_create(
            [
                Item(
                    media_id=f"history-benchmark-game-{index}",
                    source=Sources.IGDB.value,
                    media_type=MediaTypes.GAME.value,
                    title=f"History Benchmark Game {index}",
                )
                for index in range(2479)
            ],
            batch_size=1000,
        )
        Game.objects.bulk_create(
            [
                Game(
                    item=item,
                    user=cls.user,
                    progress=60,
                    start_date=cls.base_date + timedelta(days=index % 2759),
                    end_date=cls.base_date + timedelta(days=index % 2759),
                )
                for index, item in enumerate(game_items)
            ],
            batch_size=1000,
        )

        sentinel_date = cls.base_date + timedelta(days=2758)
        sentinel_models = (
            (Book, MediaTypes.BOOK.value, "History Benchmark Book"),
            (Comic, MediaTypes.COMIC.value, "History Benchmark Comic"),
            (Manga, MediaTypes.MANGA.value, "History Benchmark Manga"),
            (Anime, MediaTypes.ANIME.value, "History Benchmark Anime"),
            (Music, MediaTypes.MUSIC.value, "History Benchmark Music"),
            (BoardGame, MediaTypes.BOARDGAME.value, "History Benchmark Board Game"),
        )
        for model, media_type, title in sentinel_models:
            item = Item.objects.create(
                media_id=f"history-benchmark-{media_type}",
                source=Sources.MANUAL.value,
                media_type=media_type,
                title=title,
                runtime_minutes=3,
            )
            model.objects.create(
                item=item,
                user=cls.user,
                status=Status.COMPLETED.value,
                progress=1,
                start_date=sentinel_date,
                end_date=sentinel_date,
            )

        podcast_show = PodcastShow.objects.create(
            podcast_uuid="history-benchmark-show",
            source=Sources.POCKETCASTS.value,
            title="History Benchmark Podcast",
        )
        podcast_episode = PodcastEpisode.objects.create(
            show=podcast_show,
            episode_uuid="history-benchmark-episode",
            title="History Benchmark Podcast Episode",
            published=sentinel_date,
        )
        podcast_item = Item.objects.create(
            media_id="history-benchmark-podcast",
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title="History Benchmark Podcast Episode",
            runtime_minutes=3,
        )
        Podcast.objects.create(
            item=podcast_item,
            user=cls.user,
            show=podcast_show,
            episode=podcast_episode,
            status=Status.COMPLETED.value,
            progress=1,
            start_date=sentinel_date,
            end_date=sentinel_date,
        )

    def setUp(self):
        cache.clear()
        self.client.credentials(HTTP_X_API_KEY=self.user.token)

    def _result_counts(self, days):
        return dict(
            sorted(
                Counter(
                    entry["media_type"]
                    for day in days
                    for entry in day.get("entries", [])
                ).items(),
            ),
        )

    def _history_log_metrics(self, records):
        metrics = {}
        category_patterns = {
            "episodes": r"history_build_episodes .*count=(\d+) elapsed_ms=([\d.]+)",
            "movies": r"history_build_movies .*qs_count=(\d+) .*elapsed_ms=([\d.]+)",
            "music": r"history_build_music .*music_entries=(\d+) .*entries=(\d+) elapsed_ms=([\d.]+)",
            "podcasts": r"history_build_podcasts .*history_records=(\d+) .*entries=(\d+) elapsed_ms=([\d.]+)",
            "games": r"history_build_games .*games=(\d+) .*entries_games=(\d+) .*elapsed_ms=([\d.]+)",
        }
        for record in records:
            for category, pattern in category_patterns.items():
                match = re.search(pattern, record)
                if match:
                    values = [
                        float(value) if index == len(match.groups()) - 1 else int(value)
                        for index, value in enumerate(match.groups())
                    ]
                    metrics[category] = values
            end_match = re.search(r"history_build_end .*entry_counts=(\{.*\}) elapsed_ms=([\d.]+) .*rss_kb_delta=([-\d]+|None)", record)
            if end_match:
                rss_delta = end_match.group(3)
                metrics["end"] = {
                    "entry_counts": literal_eval(end_match.group(1)),
                    "elapsed_ms": float(end_match.group(2)),
                    "rss_kb_delta": None if rss_delta == "None" else int(rss_delta),
                }
        return metrics

    def _category_rows_processed(self, history_logs):
        """Flatten category counts from the existing builder log fields."""
        category_rows = {}
        for category, values in history_logs.items():
            if category == "end":
                continue
            category_rows[category] = values[0]
        return category_rows

    def _measure_legacy_builder(self):
        started_at = time.perf_counter()
        rss_start = history_cache._get_rss_kb()
        with self.assertLogs(level="INFO") as log_records:
            with CaptureQueriesContext(connection) as captured_queries:
                days = history_cache.build_history_days(self.user)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        rss_end = history_cache._get_rss_kb()
        return {
            "duration_ms": elapsed_ms,
            "query_count": len(captured_queries.captured_queries),
            "sql_time_ms": sum(
                float(query.get("time") or 0) * 1000
                for query in captured_queries.captured_queries
            ),
            "rss_kb_delta": (rss_end - rss_start)
            if rss_start is not None and rss_end is not None
            else 0,
            "response_bytes": len(json.dumps(days[:3], default=str).encode()),
            "status": 200,
            "result_day_count": len(days[:3]),
            "entry_counts": self._result_counts(days[:3]),
            "category_rows_processed": self._category_rows_processed(
                self._history_log_metrics(log_records.output),
            ),
            "history_logs": self._history_log_metrics(log_records.output),
        }

    def _measure_api(self):
        started_at = time.perf_counter()
        rss_start = history_cache._get_rss_kb()
        with self.assertLogs(level="INFO") as log_records:
            with CaptureQueriesContext(connection) as captured_queries:
                response = self.client.get(
                    "/api/v1/history/?limit=3&types=episodes,movies",
                )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        rss_end = history_cache._get_rss_kb()
        payload = response.json()
        return {
            "duration_ms": elapsed_ms,
            "query_count": len(captured_queries.captured_queries),
            "sql_time_ms": sum(
                float(query.get("time") or 0) * 1000
                for query in captured_queries.captured_queries
            ),
            "rss_kb_delta": (rss_end - rss_start)
            if rss_start is not None and rss_end is not None
            else 0,
            "response_bytes": len(response.content),
            "status": response.status_code,
            "result_day_count": len(payload.get("results", [])),
            "entry_counts": self._result_counts(payload.get("results", [])),
            "category_rows_processed": self._category_rows_processed(
                self._history_log_metrics(log_records.output),
            ),
            "history_logs": self._history_log_metrics(log_records.output),
        }

    def _warm_shared_day_payloads(self):
        """Prime only the first API page with complete shared day payloads."""
        logging_style = _normalize_logging_style(None, self.user)
        index_days = history_cache.build_history_index(
            self.user,
            logging_style_override=logging_style,
        )
        history_cache.cache_history_index(
            self.user.id,
            logging_style,
            index_days,
        )
        for day_key in index_days[:3]:
            day_payload = history_cache.build_history_day(
                self.user,
                day_key,
                logging_style_override=logging_style,
            )
            if day_payload:
                history_cache._cache_history_day_payload(
                    self.user.id,
                    logging_style,
                    day_key,
                    day_payload,
                )

    def test_history_api_benchmark(self):
        """Print legacy, cold optimized, and warm optimized measurements."""
        for _ in range(2):
            self._measure_legacy_builder()
        legacy_samples = [self._measure_legacy_builder() for _ in range(RUNS)]

        cold_samples = []
        for _ in range(RUNS):
            cache.clear()
            cold_samples.append(self._measure_api())

        cache.clear()
        self._warm_shared_day_payloads()
        for _ in range(2):
            self._measure_api()
        warm_samples = [self._measure_api() for _ in range(RUNS)]

        print(
            json.dumps(
                {
                    "profile": {
                        "episodes": 3370,
                        "movies": 280,
                        "games": 2479,
                        "requested_types": ["episode", "movie"],
                        "limit": 3,
                    },
                    "legacy_full_builder": _summary(legacy_samples),
                    "optimized_cold_api": _summary(cold_samples),
                    "optimized_warm_api": _summary(warm_samples),
                },
                sort_keys=True,
            ),
        )
