"""Detect how much machine Floppy is running on, and size itself accordingly.

Floppy ships six Python processes in one container (nginx aside): a gunicorn
master plus its workers, three Celery workers, and beat. Each Celery worker
carries its own full Django import - ``preload_app`` only buys copy-on-write
savings for the gunicorn workers - so the fixed defaults that suit a NAS with
8 GB comfortably exceed a 2 GB VM, and on a host with swap disabled that is
not "slow", it is kernel reclaim thrashing with nowhere to page (issue #521).

This module is the single place that answers "how big is this host?", so
gunicorn, Celery, the beat schedule and the Redis budget all scale from one
decision instead of five hardcoded numbers.

Import constraints, both load-bearing:

* **No** ``django.*`` imports. ``config/gunicorn.py`` is read by gunicorn
  before ``django.setup()``, ``settings.py`` imports this while it is still
  being constructed, and ``entrypoint.sh`` shells out to ``emit_env()`` before
  anything is initialised.
* Every probe must degrade to ``None`` rather than raise. An unreadable
  ``/sys/fs/cgroup`` or an exotic ``/proc/meminfo`` must not stop the container
  from booting.

Memory detection deliberately consults ``/proc/meminfo`` as well as the cgroup
limit, taking whichever is smaller. When a user sets no ``mem_limit`` in
compose - the configuration in issue #521 - the cgroup reports "unlimited" and
``MemTotal`` is the *only* signal that the box has 2 GB. Conversely, a small
``mem_limit`` on a large host is visible only through the cgroup. Both paths
matter; neither is a fallback for the other.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

GIB = 1024**3
MIB = 1024**2

# cgroup v1 spells "no limit" as a page-aligned near-2**63 sentinel rather than
# a keyword, and the exact value varies with the kernel's page size, so treat
# anything implausibly large as absent.
_CGROUP_UNLIMITED_THRESHOLD = 2**62

_CGROUP_V2_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_MEMORY_MAX = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_SELF_STATM = Path("/proc/self/statm")

TIER_MINIMAL = "minimal"
TIER_CONSTRAINED = "constrained"
TIER_STANDARD = "standard"
TIERS = (TIER_MINIMAL, TIER_CONSTRAINED, TIER_STANDARD)

# Ordered weakest-first so "promote one tier stricter" is an index step.
_TIER_ORDER = (TIER_MINIMAL, TIER_CONSTRAINED, TIER_STANDARD)

# A "field" line in /proc/meminfo is "Name:  <value> kB" - three tokens once
# split, but two suffice to read the number.
_MEMINFO_MIN_FIELDS = 2
_CPU_MAX_FIELDS = 2
# Two cores can't keep the standard process set fed regardless of memory.
_LOW_CPU_COUNT = 2

MINIMAL_MEMORY_THRESHOLD = int(1.5 * GIB)
CONSTRAINED_MEMORY_THRESHOLD = 3 * GIB
# Above this, a missing swap file isn't a risk worth reducing throughput for:
# Floppy's resident footprint (~1.2 GB across its processes) is a small enough
# share that a spike can't exhaust the machine.
NO_SWAP_DERATE_CEILING = 6 * GIB


def _read_text(path: Path) -> str | None:
    """Return a stripped file's contents, or None if it can't be read."""
    try:
        return path.read_text().strip()
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _read_int(path: Path) -> int | None:
    """Return a file's contents parsed as an int, or None."""
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_cgroup_limit(path: Path) -> int | None:
    """Return a cgroup byte limit, treating "max" and the v1 sentinel as absent."""
    value = _read_int(path)
    if value is None or value <= 0 or value >= _CGROUP_UNLIMITED_THRESHOLD:
        return None
    return value


def _read_meminfo_kb(field: str) -> int | None:
    """Return a /proc/meminfo field in bytes, or None."""
    contents = _read_text(_PROC_MEMINFO)
    if not contents:
        return None
    prefix = f"{field}:"
    for line in contents.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line.split()
        if len(parts) < _MEMINFO_MIN_FIELDS:
            return None
        try:
            return int(parts[1]) * 1024
        except ValueError:
            return None
    return None


def detect_memory_bytes() -> int | None:
    """Return the memory Floppy may actually use, or None if undetectable.

    The minimum of every signal available: a cgroup limit caps what the
    container may use, and MemTotal caps what the host has to give. Either can
    be the binding constraint (see the module docstring).
    """
    candidates = [
        _read_cgroup_limit(_CGROUP_V2_MEMORY_MAX),
        _read_cgroup_limit(_CGROUP_V1_MEMORY_MAX),
        _read_meminfo_kb("MemTotal"),
    ]
    detected = [value for value in candidates if value]
    return min(detected) if detected else None


def detect_available_memory_bytes() -> int | None:
    """Return currently-available host memory, or None."""
    return _read_meminfo_kb("MemAvailable")


def detect_swap_bytes() -> int | None:
    """Return total swap, or None if /proc/meminfo is unreadable.

    Zero is meaningfully different from None: a host that reports no swap has
    no shock absorber for a memory spike, which is what turns overcommitment
    into an unrecoverable hang rather than a slowdown.
    """
    return _read_meminfo_kb("SwapTotal")


def detect_cpus() -> int:
    """Return the effective CPU count, honouring a cgroup CPU quota."""
    quota_cpus = None

    cpu_max = _read_text(_CGROUP_V2_CPU_MAX)
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == _CPU_MAX_FIELDS and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
                if quota > 0 and period > 0:
                    quota_cpus = quota / period
            except ValueError:
                quota_cpus = None

    if quota_cpus is None:
        quota = _read_int(_CGROUP_V1_CPU_QUOTA)
        period = _read_int(_CGROUP_V1_CPU_PERIOD)
        if quota and period and quota > 0 and period > 0:
            quota_cpus = quota / period

    if quota_cpus is not None:
        return max(1, int(quota_cpus))

    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def current_rss_bytes() -> int | None:
    """Return this process's current RSS, or None.

    ``history_cache_utils._get_rss_kb()`` reports ``ru_maxrss``, which is the
    process *peak* and never falls, so it can't answer "how much am I using
    now". This reads the live value from /proc/self/statm instead.
    """
    contents = _read_text(_PROC_SELF_STATM)
    if not contents:
        return None
    parts = contents.split()
    if len(parts) < _MEMINFO_MIN_FIELDS:
        return None
    try:
        return int(parts[1]) * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None


def _tier_from_memory(memory_bytes: int | None) -> str:
    """Return the tier implied by memory alone."""
    if memory_bytes is None:
        # Never degrade on ignorance: an unreadable probe on a big host would
        # otherwise silently halve its throughput.
        return TIER_STANDARD
    if memory_bytes < MINIMAL_MEMORY_THRESHOLD:
        return TIER_MINIMAL
    if memory_bytes < CONSTRAINED_MEMORY_THRESHOLD:
        return TIER_CONSTRAINED
    return TIER_STANDARD


def _stricter(tier: str) -> str:
    """Return the next tier down, saturating at the strictest."""
    index = _TIER_ORDER.index(tier)
    return _TIER_ORDER[max(0, index - 1)]


def _env(name: str) -> str | None:
    """Read FLOPPY_<name>, falling back to the legacy YAMTRACK_<name>."""
    for prefix in ("FLOPPY_", "YAMTRACK_"):
        value = os.environ.get(f"{prefix}{name}")
        if value is not None and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True)
class ResourceProfile:
    """A single, immutable answer to "how big is this host?"."""

    tier: str
    memory_bytes: int | None
    available_bytes: int | None
    swap_bytes: int | None
    cpus: int
    overridden: bool
    notes: tuple[str, ...] = ()

    @property
    def is_constrained(self) -> bool:
        """Whether this host needs reduced defaults of any kind."""
        return self.tier in (TIER_MINIMAL, TIER_CONSTRAINED)

    def describe(self) -> str:
        """Return a one-line human-readable summary for logs."""

        def gib(value: int | None) -> str:
            return "unknown" if value is None else f"{value / GIB:.1f}GiB"

        parts = [
            f"tier={self.tier}",
            f"mem={gib(self.memory_bytes)}",
            f"swap={gib(self.swap_bytes)}",
            f"cpus={self.cpus}",
        ]
        if self.overridden:
            parts.append("source=override")
        if self.notes:
            parts.append(f"reasons={','.join(self.notes)}")
        return " ".join(parts)


def detect_profile() -> ResourceProfile:
    """Probe the host and derive its resource tier."""
    memory_bytes = detect_memory_bytes()
    swap_bytes = detect_swap_bytes()
    cpus = detect_cpus()

    override = (_env("RESOURCE_TIER") or "auto").lower()
    if override in TIERS:
        return ResourceProfile(
            tier=override,
            memory_bytes=memory_bytes,
            available_bytes=detect_available_memory_bytes(),
            swap_bytes=swap_bytes,
            cpus=cpus,
            overridden=True,
        )

    notes: list[str] = []
    if override != "auto":
        notes.append(f"ignored_invalid_override={override}")

    tier = _tier_from_memory(memory_bytes)
    if memory_bytes is None:
        notes.append("memory_undetected")

    # No swap means a memory spike has nowhere to go, which is the difference
    # between a slow host and a hung one (issue #521). Treat it as one tier less
    # headroom than the raw numbers suggest - but only where Floppy's own
    # footprint is a meaningful fraction of the machine. Running Docker without
    # swap is a common and sensible policy, and a 16 GB host doesn't need
    # de-rating just because it has none.
    if (
        swap_bytes == 0
        and memory_bytes is not None
        and memory_bytes < NO_SWAP_DERATE_CEILING
    ):
        stricter = _stricter(tier)
        if stricter != tier:
            notes.append("no_swap")
            tier = stricter

    # Two cores can't keep three Celery workers and two gunicorn workers fed
    # regardless of how the memory maths works out.
    if cpus <= _LOW_CPU_COUNT and memory_bytes is not None and memory_bytes < 4 * GIB:
        stricter = _stricter(tier)
        if stricter != tier:
            notes.append("low_cpu")
            tier = stricter

    return ResourceProfile(
        tier=tier,
        memory_bytes=memory_bytes,
        available_bytes=detect_available_memory_bytes(),
        swap_bytes=swap_bytes,
        cpus=cpus,
        overridden=False,
        notes=tuple(notes),
    )


PROFILE = detect_profile()


def by_tier(minimal, constrained, standard, profile: ResourceProfile | None = None):
    """Return whichever of three values matches the active tier.

    Keeps tier-scaled settings readable at the call site:
    ``by_tier(50, 75, 150)`` rather than a dict lookup per setting.
    """
    tier = (profile or PROFILE).tier
    if tier == TIER_MINIMAL:
        return minimal
    if tier == TIER_CONSTRAINED:
        return constrained
    return standard


def web_concurrency(profile: ResourceProfile | None = None) -> int:
    """Return the gunicorn worker count for this host."""
    resolved = profile or PROFILE
    explicit = os.environ.get("WEB_CONCURRENCY")
    if explicit:
        try:
            return max(1, int(explicit))
        except ValueError:
            pass
    if resolved.tier == TIER_STANDARD:
        # gthread handles concurrent I/O in one preloaded worker. A second
        # worker mostly duplicates the resident Django import at idle.
        return 1
    return 1


def gunicorn_threads(profile: ResourceProfile | None = None) -> int:
    """Return the gunicorn thread count per worker for this host."""
    explicit = os.environ.get("GUNICORN_THREADS")
    if explicit:
        try:
            return max(1, int(explicit))
        except ValueError:
            pass
    return by_tier(2, 4, 4, profile)


def celery_queue_plan(profile: ResourceProfile | None = None) -> dict[str, str]:
    """Return which Celery workers to start, and what each consumes.

    The three-worker split exists so bulk backfills can never starve
    interactive webhook processing - see ``get_process_role`` in
    ``app/providers/services.py``. Each worker is a whole Django import, so on
    small hosts that isolation has to be traded away, but gradually:

    * standard and constrained: two - the Discover queue joins the background
      worker while the interactive worker stays isolated. This avoids a third
      resident Django import without allowing bulk work to block the UI.
    * minimal: one, consuming every queue. In-queue priority ordering takes
      over from cross-process isolation.
    """
    resolved = profile or PROFILE
    if resolved.tier == TIER_MINIMAL:
        return {
            "queues": "celery,interactive,discover",
            "role": "combined",
            "start_interactive": "false",
            "start_discover": "false",
        }
    if resolved.tier in (TIER_CONSTRAINED, TIER_STANDARD):
        return {
            "queues": "celery,discover",
            "role": "background",
            "start_interactive": "true",
            "start_discover": "false",
        }
    return {
        "queues": "celery",
        "role": "background",
        "start_interactive": "true",
        "start_discover": "true",
    }


def emit_env(profile: ResourceProfile | None = None) -> None:
    """Print shell ``export`` lines describing the sizing decision.

    ``entrypoint.sh`` evals this so the tier is probed exactly once per
    container rather than independently in each of the six supervised
    processes, which could otherwise disagree. Values the user set explicitly
    are echoed back unchanged - an operator's choice always wins.
    """
    resolved = profile or PROFILE
    plan = celery_queue_plan(resolved)
    exports = {
        "FLOPPY_RESOURCE_TIER": resolved.tier,
        "FLOPPY_CELERY_QUEUES": plan["queues"],
        "FLOPPY_CELERY_ROLE": plan["role"],
        "FLOPPY_START_INTERACTIVE_WORKER": plan["start_interactive"],
        "FLOPPY_START_DISCOVER_WORKER": plan["start_discover"],
        "WEB_CONCURRENCY": str(web_concurrency(resolved)),
        "GUNICORN_THREADS": str(gunicorn_threads(resolved)),
    }
    for key, value in exports.items():
        # stdout is eval'd by the shell; keep it exclusively export lines.
        print(f"export {key}='{value}'")  # noqa: T201  # this is the command's output
    summary = (
        f"[entrypoint] resources {resolved.describe()}"
        f" -> gunicorn {exports['WEB_CONCURRENCY']}x{exports['GUNICORN_THREADS']},"
        f' celery queues "{plan["queues"]}"'
    )
    print(summary, file=sys.stderr)  # noqa: T201  # surfaced in container logs
