"""Read the SQLite file sequentially so first page loads hit the page cache.

A cold library load reads b-tree pages in key order, which on a slow or
cache-starved disk is thousands of random reads. One sequential pass over the
file costs a fraction of that and leaves the pages in the OS cache for every
web worker. The pass is bounded (byte budget, no more than a fraction of the
memory currently available) and paced, so foreground requests keep their I/O.
It also logs the throughput it measured: a ``slow_disk`` line is the clear
signal that cold queries are waiting on storage rather than on Floppy.
"""

import logging
import os
import time
from pathlib import Path

from celery import shared_task
from django.conf import settings

from config.runtime_profile import detect_available_memory_bytes

logger = logging.getLogger(__name__)

CHUNK_BYTES = 4 * 1024 * 1024
MEMORY_FRACTION = 0.25


def _budget_bytes(file_size: int) -> int:
    budget = min(file_size, int(settings.DB_WARM_MAX_MIB) * 1024 * 1024)
    available = detect_available_memory_bytes()
    if available:
        budget = min(budget, int(available * MEMORY_FRACTION))
    return budget


@shared_task(name="Warm database page cache", ignore_result=True)
def warm_database_page_cache():
    """Read the head-of-file budget in paced chunks; no-op off SQLite."""
    if not settings.USING_SQLITE_DATABASE:
        return {"status": "skipped", "reason": "postgres"}
    if not settings.DB_WARM_ENABLED:
        return {"status": "skipped", "reason": "disabled"}

    path = str(settings.DATABASES["default"]["NAME"])
    try:
        file_size = Path(path).stat().st_size
    except OSError:
        return {"status": "skipped", "reason": "missing"}
    budget = _budget_bytes(file_size)
    pause = float(settings.DB_WARM_PAUSE_MS) / 1000

    started = time.perf_counter()
    done = 0
    slowest_ms = 0.0
    fd = os.open(path, os.O_RDONLY)
    try:
        while done < budget:
            chunk_started = time.perf_counter()
            data = os.pread(fd, min(CHUNK_BYTES, budget - done), done)
            if not data:
                break
            done += len(data)
            slowest_ms = max(slowest_ms, (time.perf_counter() - chunk_started) * 1000)
            if pause:
                time.sleep(pause)
    finally:
        os.close(fd)

    elapsed = max(time.perf_counter() - started - pause * (done / CHUNK_BYTES), 1e-6)
    mib_s = done / 1048576 / elapsed
    slow = mib_s < settings.DB_SLOW_DISK_MIB_PER_SECOND
    (logger.warning if slow else logger.info)(
        "%s warmed_mib=%s file_mib=%s duration_ms=%s read_mib_s=%.1f "
        "slowest_chunk_ms=%.0f",
        "slow_disk" if slow else "database_warm",
        done // 1048576,
        file_size // 1048576,
        round(elapsed * 1000),
        mib_s,
        slowest_ms,
    )
    return {"status": "ok", "warmed_bytes": done, "read_mib_s": round(mib_s, 1)}
