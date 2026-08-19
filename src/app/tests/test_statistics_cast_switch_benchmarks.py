"""Benchmark the statistics cast-switch endpoint with representative credit data."""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app import statistics_cache
from app.models import (
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
    Sources,
    Status,
)


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.INFO)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


@tag("slow", "benchmark")
class StatisticsCastSwitchBenchmarkTests(TestCase):
    """Capture cast-switch timings before/after backend optimizations."""

    MOVIE_COUNT = 120
    CUSTOM_RANGE_DAYS = 45

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="cast-switch-benchmark",
            password="12345",
        )
        cls.user.movie_enabled = True
        cls.user.statistics_default_range = "All Time"
        cls.user.save(update_fields=["movie_enabled", "statistics_default_range"])

        cls.actors = [
            Person.objects.create(
                source=Sources.TMDB.value,
                source_person_id=str(7000 + index),
                name=f"Benchmark Actor {index + 1}",
                gender=PersonGender.MALE.value,
                known_for_department="Acting",
            )
            for index in range(6)
        ]

        watched_at = timezone.now()
        movie_rows = []
        credit_rows = []
        for index in range(cls.MOVIE_COUNT):
            item = Item.objects.create(
                media_id=str(10000 + index),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Benchmark Movie {index + 1}",
                image=f"http://example.com/movie-{index + 1}.jpg",
                runtime_minutes=90 + (index % 30),
            )
            movie_rows.append(
                Movie(
                    item=item,
                    user=cls.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    start_date=watched_at - timedelta(days=index + 1),
                    end_date=watched_at - timedelta(days=index + 1),
                ),
            )

            lead_actor = cls.actors[index % len(cls.actors)]
            support_actor = cls.actors[(index + 1) % len(cls.actors)]
            credit_rows.append(
                ItemPersonCredit(
                    item=item,
                    person=lead_actor,
                    role_type=CreditRoleType.CAST.value,
                    role="Lead",
                ),
            )
            credit_rows.append(
                ItemPersonCredit(
                    item=item,
                    person=support_actor,
                    role_type=CreditRoleType.CAST.value,
                    role="Support",
                ),
            )

        Movie.objects.bulk_create(movie_rows)
        ItemPersonCredit.objects.bulk_create(credit_rows)

    def setUp(self):
        cache.clear()
        statistics_cache.invalidate_statistics_cache(self.user.id)
        self.client.force_login(self.user)

    def _measure_switch(
        self,
        person: Person,
        *,
        range_name: str | None = "All Time",
        start_date: str | None = None,
        end_date: str | None = None,
        total_library_titles: int | None = None,
    ) -> dict[str, int | float | str]:
        payload = {
            "person_source": person.source,
            "person_id": person.source_person_id,
        }
        if range_name:
            payload["range_name"] = range_name
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        if total_library_titles is not None:
            payload["total_library_titles"] = total_library_titles

        started_at = time.perf_counter()
        with CaptureQueriesContext(connection) as captured_queries:
            response = self.client.post(
                reverse("select_featured_person"),
                payload,
            )
        duration_ms = (time.perf_counter() - started_at) * 1000
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, person.name, status_code=200)
        return {
            "person": person.name,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "queries": len(captured_queries.captured_queries),
            "response_bytes": len(response.content),
        }

    def test_select_featured_person_benchmarks(self):
        statistics_response = self.client.get(reverse("statistics"))
        self.assertEqual(statistics_response.status_code, 200)

        targets = self.actors[:3]
        first_round = [self._measure_switch(person) for person in targets]
        second_round = [self._measure_switch(person) for person in targets]

        payload = {
            "page_range": "All Time",
            "movie_count": self.MOVIE_COUNT,
            "first_round": first_round,
            "second_round": second_round,
            "first_round_avg_ms": round(
                sum(result["duration_ms"] for result in first_round) / len(first_round),
                2,
            ),
            "second_round_avg_ms": round(
                sum(result["duration_ms"] for result in second_round)
                / len(second_round),
                2,
            ),
            "first_round_avg_queries": round(
                sum(result["queries"] for result in first_round) / len(first_round),
                2,
            ),
            "second_round_avg_queries": round(
                sum(result["queries"] for result in second_round) / len(second_round),
                2,
            ),
        }
        print(json.dumps(payload, sort_keys=True))

        self.assertTrue(all(result["response_bytes"] > 0 for result in first_round))
        self.assertLessEqual(
            payload["second_round_avg_queries"], payload["first_round_avg_queries"]
        )

    def test_select_featured_person_custom_range_benchmarks(self):
        end_day = timezone.localdate()
        start_day = end_day - timedelta(days=self.CUSTOM_RANGE_DAYS)
        statistics_response = self.client.get(
            reverse("statistics"),
            {
                "start-date": start_day.isoformat(),
                "end-date": end_day.isoformat(),
                "compare": "none",
            },
        )
        self.assertEqual(statistics_response.status_code, 200)
        total_library_titles = statistics_response.context["media_count"]["total"]

        targets = self.actors[:3]
        first_round = [
            self._measure_switch(
                person,
                range_name=None,
                start_date=start_day.isoformat(),
                end_date=end_day.isoformat(),
                total_library_titles=total_library_titles,
            )
            for person in targets
        ]

        payload = {
            "page_range": "custom",
            "movie_count": self.MOVIE_COUNT,
            "custom_range_days": self.CUSTOM_RANGE_DAYS,
            "first_round": first_round,
            "first_round_avg_ms": round(
                sum(result["duration_ms"] for result in first_round) / len(first_round),
                2,
            ),
            "first_round_avg_queries": round(
                sum(result["queries"] for result in first_round) / len(first_round),
                2,
            ),
        }
        print(json.dumps(payload, sort_keys=True))

        self.assertTrue(all(result["response_bytes"] > 0 for result in first_round))
