"""Keep SQLite planner statistics present so detail pages seek by item.

A database that has never been ANALYZEd has no ``sqlite_stat1``. The planner
then prefers a ``user_id`` index over the selective item index and walks every
row a user tracks (see ``USER-REPORTED/episode-page``: 81k VM steps for one
season row at 9k seasons). ``PRAGMA optimize`` with the "check every table"
bit analyses only tables that have no statistics or that changed
substantially, and ``analysis_limit`` bounds each ANALYZE to a sample, so a
steady-state run is close to free and the first run on a large database stays
bounded.
"""

import logging
import time

from celery import shared_task
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

# 0x10002 = "analyse if useful" (0x2) over every table, not only those the
# current connection happened to query (0x10000, SQLite 3.46+; older versions
# ignore the extra bit and optimise nothing, which is harmless).
OPTIMIZE_MASK = 0x10002


def _stat_rows(cursor) -> int:
    cursor.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1'",
    )
    if not cursor.fetchone()[0]:
        return 0
    cursor.execute("SELECT count(*) FROM sqlite_stat1")
    return cursor.fetchone()[0]


@shared_task(name="Optimize database planner statistics", ignore_result=True)
def optimize_database_statistics():
    """Refresh missing or stale ``sqlite_stat1`` rows; no-op off SQLite."""
    if not settings.USING_SQLITE_DATABASE:
        return {"status": "skipped", "reason": "postgres"}
    if not settings.DB_OPTIMIZE_ENABLED:
        return {"status": "skipped", "reason": "disabled"}

    started = time.perf_counter()
    with connection.cursor() as cursor:
        before = _stat_rows(cursor)
        cursor.execute(f"PRAGMA analysis_limit={int(settings.DB_OPTIMIZE_ANALYSIS_LIMIT)}")
        if before == 0:
            # Plain ANALYZE does not depend on the SQLite version honouring
            # the "check every table" bit of OPTIMIZE_MASK (older builds, as in
            # a local Python, optimise nothing and leave the planner blind).
            cursor.execute("ANALYZE")
        cursor.execute(f"PRAGMA optimize={OPTIMIZE_MASK}")
        after = _stat_rows(cursor)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(
        "optimize_database_statistics stat_rows_before=%s stat_rows_after=%s "
        "duration_ms=%s",
        before,
        after,
        duration_ms,
    )
    return {
        "status": "ok",
        "stat_rows_before": before,
        "stat_rows_after": after,
        "duration_ms": duration_ms,
    }
