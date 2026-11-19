"""Recorded server answers the Expo app's transport tests read (assignment 78).

Each recording under ``expo/app/data/__recorded__/`` is the real JSON
one endpoint returns for the sample library (``catalogue_fixtures``), in one
state the native screen cares about (tracked, untracked, empty). The
JavaScript transport tests feed these files through the real readers and
check the fields each screen uses, so a server change that renames, moves or
drops a field the app reads fails there.

This test regenerates every recording in memory and fails when a committed
file differs, the way ``npm run check:ui`` fails on a stale bundle. Changing
the shape of one of these endpoints therefore changes a file under
``expo/`` in the same pull request. Refresh, then read the diff:

    FLOPPY_RECORD_NATIVE=1 scripts/test.sh api.tests.test_native_recordings

Volatile values are fixed so a recording depends only on the code: id
sequences restart before the library is built, the clock is fixed, the CSRF token is removed, and every request starts with an empty
cache (a cached answer can carry keys a cold one leaves out; the cold one is
what a first visit sees).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.core.management.color import no_style
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from app.signals import suppress_media_change_side_effects
from app.tests import catalogue_fixtures as fx
from users.models import User

RECORDED_DIR = (
    Path(__file__).resolve().parents[3]
    / "expo"
    / "app"
    / "data"
    / "__recorded__"
)
REFRESH_COMMAND = (
    "FLOPPY_RECORD_NATIVE=1 scripts/test.sh api.tests.test_native_recordings"
)
# Every recording is made at this instant, so "today", relative dates and
# history days do not move with the calendar.
FROZEN_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

MOVIE = f"/api/v1/media/movie/tmdb/{fx.SAMPLE_MOVIE_ID}/detail/"


def recordings(library):
    """(file name, viewer, path, query) for each recorded answer.

    Paths and queries are the ones the native screens send: see the
    ``*TransportCore.js`` reader named in each comment.
    """
    user, empty = library.user, library.empty_user
    return (
        # detailTransportCore.trackingEntriesFromPayload, detailActions.mjs
        ("detail-movie-tracked", user, MOVIE, {}),
        ("detail-movie-untracked", empty, MOVIE, {}),
        # libraryTransportCore.mediaRowsFromPayload (LibraryScreen PAGE_LIMIT)
        ("library-movie", user, "/api/v1/media/movie/", {"limit": 30, "offset": 0}),
        (
            "library-movie-empty",
            empty,
            "/api/v1/media/movie/",
            {"limit": 30, "offset": 0},
        ),
        # listTransportCore.listSummaryFromPayload and listItemsFromPayload
        (
            "list-detail",
            user,
            f"/api/v1/lists/{library.custom_list.id}/",
            {"limit": 200, "offset": 0},
        ),
        # historyTransportCore.historyDaysFromPayload (HistoryScreen page sizes)
        (
            "history",
            user,
            "/api/v1/history/",
            {"limit": 31, "offset": 0, "max_entries_per_day": 30},
        ),
        (
            "history-empty",
            empty,
            "/api/v1/history/",
            {"limit": 31, "offset": 0, "max_entries_per_day": 30},
        ),
        # homeTransportCore.homeScreenFromPayload (HomeScreen PAGE_LIMIT)
        (
            "home",
            user,
            "/api/v1/home/",
            {"presentation": 1, "deferred": 1, "limit": 14},
        ),
        # homeTransportCore loadRow: Home defers every row, so the cards and
        # their tracking state arrive here. The row id comes from "home".
        ("home-row-movie", user, HOME_ROW, {"offset": 0, "limit": 14}),
    )


HOME_ROW = "/api/v1/home/row/{movie_row}/"


def movie_row_id(home):
    """The first Movies row id in a Home answer (``deferredGroups``)."""
    for group in home.get("deferredGroups", []) + home.get("groups", []):
        if group.get("mediaType") == "movie" and group.get("rowIds"):
            return group["rowIds"][0]
    return None


DROPPED_KEYS = {"csrf_token", "csrfToken", "csrf"}
# Card element ids end in a random ``uuid4().hex[:8]`` (``#track-movie-1-90d42f5b``).
RANDOM_SUFFIX = re.compile(r"^(#?[a-z][a-z0-9-]*)-[0-9a-f]{8}$")


def normalise(payload):
    """Drop CSRF tokens and random element-id suffixes.

    Everything else is fixed by the test setup (clock, id sequences, cache).
    """
    if isinstance(payload, str):
        return RANDOM_SUFFIX.sub(r"\1-random", payload)
    if isinstance(payload, dict):
        return {
            key: normalise(value)
            for key, value in payload.items()
            if key not in DROPPED_KEYS
        }
    if isinstance(payload, list):
        return [normalise(value) for value in payload]
    return payload


def frozen_clock():
    """Patches that make every "now" the server reads ``FROZEN_NOW``.

    ``timezone.now`` itself; ``MonitorField`` (``progressed_at``), which
    imported ``now`` by name; and each field whose default is ``timezone.now``,
    whose default Django caches on the field.
    """
    real_now = timezone.now
    patches = [
        patch("django.utils.timezone.now", return_value=FROZEN_NOW),
        patch("model_utils.fields.now", return_value=FROZEN_NOW),
    ]
    for model in apps.get_models():
        for model_field in model._meta.concrete_fields:
            if model_field.default is real_now:
                patches.append(
                    patch.dict(
                        model_field.__dict__, {"_get_default": lambda: FROZEN_NOW}
                    )
                )
    return patches


def restart_id_sequences():
    """Make the next database id of every table its largest id plus one.

    Ids then depend only on what this class creates, on SQLite and on
    PostgreSQL, whatever ran before it. Inside the class transaction, so
    SQLite undoes it afterwards; PostgreSQL keeps sequences at a safe value.
    """
    style = no_style()
    if connection.vendor == "sqlite":
        statements = connection.ops.sequence_reset_by_name_sql(
            style, connection.introspection.sequence_list()
        )
    else:
        statements = connection.ops.sequence_reset_sql(style, apps.get_models())
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def render(payload):
    return (
        json.dumps(normalise(payload), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


class NativeRecordingsTests(TestCase):
    """The committed recordings match what the server answers today."""

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)
        cls.addClassCleanup(logging.disable, logging.NOTSET)
        for clock in frozen_clock():
            clock.start()
            cls.addClassCleanup(clock.stop)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        restart_id_sequences()
        cls.user = User.objects.create_user(username="recorded", password="x")
        empty = User.objects.create_user(username="recorded-empty", password="x")
        with (
            patch("app.models.Item.fetch_releases", return_value=None),
            suppress_media_change_side_effects(),
        ):
            cls.library = fx.build_sample_library(
                cls.user, empty_user=empty, now=FROZEN_NOW
            )

    def setUp(self):
        for patcher in self.library.patchers():
            patcher.start()
            self.addCleanup(patcher.stop)

    def record(self):
        """{file name: rendered JSON} for every recording, from live requests."""
        rendered = {}
        answers = {}
        for name, viewer, template, query in recordings(self.library):
            path = template
            if template == HOME_ROW:
                path = template.format(movie_row=movie_row_id(answers["home"]))
            # A cold answer each time: a cached History day adds ``album`` and
            # ``show`` keys (null) that a freshly built one leaves out.
            cache.clear()
            response = self.client.get(path, query, headers={"X-Api-Key": viewer.token})
            self.assertEqual(
                response.status_code,
                200,
                f"{name}: {path} answered {response.status_code}",
            )
            answers[name] = response.json()
            rendered[f"{name}.json"] = render(answers[name])
        return rendered

    def test_recordings_are_fresh(self):
        rendered = self.record()
        if os.environ.get("FLOPPY_RECORD_NATIVE") == "1":
            RECORDED_DIR.mkdir(parents=True, exist_ok=True)
            for stale in RECORDED_DIR.glob("*.json"):
                if stale.name not in rendered:
                    stale.unlink()
            for name, text in rendered.items():
                (RECORDED_DIR / name).write_text(text, encoding="utf-8")
            return
        problems = []
        committed = {path.name for path in RECORDED_DIR.glob("*.json")}
        for name, text in rendered.items():
            path = RECORDED_DIR / name
            if not path.exists():
                problems.append(f"missing: {path.relative_to(RECORDED_DIR.parents[3])}")
            elif path.read_text(encoding="utf-8") != text:
                problems.append(f"stale: {path.relative_to(RECORDED_DIR.parents[3])}")
        problems += [
            f"no longer recorded: {name}" for name in sorted(committed - set(rendered))
        ]
        self.assertFalse(
            problems,
            "The Expo app's recorded server answers differ from what the server returns:\n  "
            + "\n  ".join(problems)
            + f"\nRefresh them with\n  {REFRESH_COMMAND}\n"
            "then read the diff: every changed field is one a native screen may read.",
        )

    def test_recording_is_repeatable(self):
        """Two recordings in a row are identical, so a stale file is a real change."""
        self.assertEqual(self.record(), self.record())
