"""Answer one question, can this Floppy installation start.

The checks live here and the management command renders them, the same split
``redis_tuning`` and ``tune_redis`` already use. Keeping the decisions out of the
command means they return data instead of printing it, so a caller can use them
without a terminal.

Every check reports the same shape, and none of them repairs anything. The one
exception is migrations, which apply only when the operator asks for them.

Read the results as an operator reads them: a check that fails must say what
broke, why it broke, and what to do next. The last part is the reason this module
exists. A report that says "database: error" tells the operator only what they
already knew.

    paths ──── writable? a file and not a directory? space left?
      │
    config ─── does Django accept these settings?
      │
    database ─ sqlite: storage and relationships   postgres: reachable
      │            (bounded scan, no write lock, no repair)
      │
    migrations ─ anything pending?   (skipped when the database is unreachable,
      │                               because the query needs a connection)
      │
    redis ───── ping every distinct endpoint

Statuses are ``ok``, ``warn``, ``fail`` and ``skipped``. Only ``fail`` changes the
exit code. ``warn`` exists so the checks can report a hazard that does not stop
startup, such as a Redis server with no memory ceiling, without blocking a boot
that would otherwise succeed.
"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import redis
from django.conf import settings
from django.core import checks as django_checks
from django.db import DatabaseError, connections
from django.db.migrations.executor import MigrationExecutor

from app.log_safety import redact_secrets, safe_url
from app.redis_tuning import parse_size
from config.sqlite_integrity import IntegrityScanTimeoutError, inspect_database

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIPPED = "skipped"

# A fix an operator cannot run is not a fix, so every instruction says where to
# run it. The three scopes are true in every deployment: file ownership belongs
# to the machine, connection settings belong to whatever declares them, and the
# rest belongs to a shell that can reach manage.py. Only the wording inside a
# fix changes with the environment, which _where() handles.
HOST = "[HOST]"
CONFIG = "[CONFIG]"
FLOPPY = "[FLOPPY]"


# Each runtime leaves its own marker. Docker writes /.dockerenv, and Podman
# writes /run/.containerenv, which matters because Podman is common in the
# self-hosted setups Floppy runs in. Checking only the Docker file gives a
# Podman operator the advice meant for a bare install.
_CONTAINER_MARKERS = (Path("/.dockerenv"), Path("/run/.containerenv"))


def in_container() -> bool:
    """Report whether Floppy runs inside a container.

    Floppy also runs from source and as a packaged desktop application, where
    advice about compose files, PUID and PGID is wrong.
    """
    return any(marker.exists() for marker in _CONTAINER_MARKERS)


def _where(container: str, plain: str) -> str:
    """Return whichever instruction suits the environment Floppy runs in."""
    return container if in_container() else plain

# SQLite needs room for the database, its write-ahead log and a checkpoint. This
# is a floor for "the next write will not fail", not a capacity estimate.
_BYTES_PER_UNIT = 1024.0
MIN_FREE_BYTES = 64 * 1024 * 1024

DEFAULT_SCAN_TIMEOUT_SECONDS = 600.0

# An operator is waiting at a terminal. A dead endpoint must be reported in
# seconds, not after the long timeout a serving process can afford.
_NETWORK_TIMEOUT_SECONDS = 5

# The output shape that supervisors parse. Increment only when a key is removed
# or renamed. Added keys keep the same version.
REPORT_VERSION = 1

# Celery can use a broker this check has no client for. Only these are ours.
REDIS_SCHEMES = ("redis://", "rediss://", "unix://")


@dataclass(frozen=True)
class CheckResult:
    """What one check found, and what to do about it."""

    name: str
    status: str
    summary: str
    cause: str = ""
    fix: str = ""
    facts: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        """Report whether this result must stop a start."""
        return self.status == FAIL

    def as_dict(self) -> dict:
        """Return the result as the JSON report describes it."""
        payload = {"name": self.name, "status": self.status, "summary": self.summary}
        if self.cause:
            payload["cause"] = self.cause
        if self.fix:
            payload["fix"] = self.fix
        if self.facts:
            payload["facts"] = self.facts
        return payload


def clean(text: object) -> str:
    """Remove credentials from text that came from a library or the system."""
    return redact_secrets(str(text))


def _human_bytes(count: float) -> str:
    """Return a byte count an operator can read at a glance."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < _BYTES_PER_UNIT or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= _BYTES_PER_UNIT
    return f"{size:.1f} TB"


def _probe_writable(path: Path) -> str | None:
    """Return why a directory cannot be written to, or None when it can be.

    A real file is created and removed. Permission bits alone do not prove a
    write will succeed: a read-only mount reports the same bits it had when it
    was writable.
    """
    probe = path / ".floppy-preflight-probe"
    try:
        probe.touch()
    except OSError as error:
        return str(error)
    probe.unlink(missing_ok=True)
    return None


def _probe_write_file(path: Path) -> str | None:
    """Return why an existing file cannot be written to, or None when it can be.

    Opened for append so nothing is added and nothing is truncated.
    """
    try:
        with path.open("a"):
            pass
    except OSError as error:
        return str(error)
    return None


def check_paths() -> CheckResult:
    """Report the configured directories and whether Floppy can write to them.

    ``os.access`` answers a narrower question than it appears to. It reports the
    permission bits, so it returns true for a full disk, and it says nothing
    about what kind of thing is at the path. Docker creates a *directory* when a
    bind mount names a file that does not exist yet, which is a routine way to
    arrive at a database path that can never open.
    """
    data_dir = Path(settings.FLOPPY_DATA_DIR)
    db_path = Path(settings.FLOPPY_DB_PATH)
    log_dir = Path(settings.LOG_DIR)
    facts = {
        "data_dir": str(data_dir),
        "database_path": str(db_path),
        "log_dir": str(log_dir),
    }

    if settings.USING_SQLITE_DATABASE and db_path.is_dir():
        return CheckResult(
            name="paths",
            status=FAIL,
            summary=f"{db_path} is a directory, not a database file",
            cause=(
                "a bind mount named this path before the file existed, so Docker "
                "created a directory there"
            ),
            fix=_where(
                f"{HOST} remove the directory, create an empty file in its "
                "place, then recreate the container",
                f"{HOST} remove the directory and create an empty file in its "
                "place",
            ),
            facts=facts,
        )

    required = [("data directory", data_dir), ("log directory", log_dir)]
    if settings.USING_SQLITE_DATABASE:
        required.append(("database directory", db_path.parent))

    # An existing database file needs its own check. Every check here reads, and
    # so does the integrity scan, so a file that is readable but not writable
    # passes all of them and then fails on the first write after boot.
    if settings.USING_SQLITE_DATABASE and db_path.is_file():
        unwritable = _probe_write_file(db_path)
        if unwritable is not None:
            return CheckResult(
                name="paths",
                status=FAIL,
                summary=f"the database file {db_path} is not writable",
                cause=clean(unwritable),
                fix=_where(
                    f"{HOST} give the file to the container's user (PUID and "
                    "PGID, 1000 by default), including its -wal and -shm files",
                    f"{HOST} give the file to the user that runs Floppy, "
                    "including its -wal and -shm files",
                ),
                facts=facts,
            )

    for label, path in required:
        if not path.exists():
            return CheckResult(
                name="paths",
                status=FAIL,
                summary=f"{label} {path} does not exist",
                cause="the volume is not mounted, or the path is misspelled",
                fix=_where(
                    f"{CONFIG} check the volume mapping for {path}",
                    f"{CONFIG} create {path}, or correct the configured path",
                ),
                facts=facts,
            )
        reason = _probe_writable(path)
        if reason is not None:
            return CheckResult(
                name="paths",
                status=FAIL,
                summary=f"{label} {path} is not writable",
                cause=clean(reason),
                fix=_where(
                    f"{HOST} give the mapped directory to the container's user "
                    "(PUID and PGID, 1000 by default)",
                    f"{HOST} give this directory to the user that runs Floppy",
                ),
                facts=facts,
            )

    # The database can sit on a different volume from the data directory, and
    # it is the one that matters first.
    measured = db_path.parent if settings.USING_SQLITE_DATABASE else data_dir
    free = shutil.disk_usage(measured).free
    facts["free_bytes"] = free
    facts["free_on"] = str(measured)
    if free < MIN_FREE_BYTES:
        return CheckResult(
            name="paths",
            status=FAIL,
            summary=f"{measured} has {_human_bytes(free)} free",
            cause=(
                f"less than {_human_bytes(MIN_FREE_BYTES)}; the next write to the "
                "database or its log will fail"
            ),
            fix=f"{HOST} free space on the volume that holds {measured}",
            facts=facts,
        )

    return CheckResult(
        name="paths",
        status=OK,
        summary=f"{data_dir} ({_human_bytes(free)} free)",
        facts=facts,
    )


def check_config() -> CheckResult:
    """Run Django's own system checks and report their errors.

    The command stops Django from running these automatically, because their
    output would land on standard output and break the JSON report. Silence is
    not the goal though. A settings mistake stops a container from starting, and
    a report that says everything passed while the container dies is worse than
    no report, so the checks run here and their findings are reported like any
    other.
    """
    messages = django_checks.run_checks(include_deployment_checks=False)
    errors = [m for m in messages if m.level >= django_checks.ERROR]
    warnings = [
        m for m in messages if django_checks.WARNING <= m.level < django_checks.ERROR
    ]

    if errors:
        first = errors[0]
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        return CheckResult(
            name="config",
            status=FAIL,
            summary=f"{len(errors)} settings error(s){more}",
            cause=clean(f"{first.id or 'check'}: {first.msg}"),
            fix=_where(
                f"{CONFIG} correct the environment variables for this stack",
                f"{CONFIG} correct the environment variables or the .env file",
            ),
            facts={"errors": [clean(m.msg) for m in errors]},
        )

    if warnings:
        return CheckResult(
            name="config",
            status=WARN,
            summary=f"{len(warnings)} settings warning(s)",
            cause=clean(warnings[0].msg),
            facts={"warnings": [clean(m.msg) for m in warnings]},
        )

    return CheckResult(name="config", status=OK, summary="no settings errors")


# PostgreSQL answers these before it answers a query, so each one means the
# server is running and the operator should look somewhere other than the
# network. https://www.postgresql.org/docs/current/errcodes-appendix.html
_PG_AUTH_FAILED = "28P01"
_PG_NO_SUCH_USER = "28000"
_PG_NO_SUCH_DATABASE = "3D000"


def _check_postgres() -> CheckResult:
    """Report whether the configured PostgreSQL server answers.

    A refused connection and a refused password look the same to anyone reading
    "could not connect", but they send the operator to different places. The
    server reports which one it is, so this passes that on.
    """
    facts = {
        "engine": "postgresql",
        "host": settings.DATABASES["default"].get("HOST", ""),
    }
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError as error:
        # psycopg 3 calls it sqlstate and psycopg 2 calls it pgcode. Read both
        # rather than silently losing the distinction on one of them.
        cause = getattr(error, "__cause__", None)
        code = (
            getattr(cause, "sqlstate", None)
            or getattr(cause, "pgcode", None)
            or getattr(error, "pgcode", None)
        )
        if code in {_PG_AUTH_FAILED, _PG_NO_SUCH_USER}:
            return CheckResult(
                name="database",
                status=FAIL,
                summary="the database server refused the credentials",
                cause=clean(error),
                fix=f"{CONFIG} correct DB_USER and DB_PASSWORD",
                facts=facts,
            )
        if code == _PG_NO_SUCH_DATABASE:
            return CheckResult(
                name="database",
                status=FAIL,
                summary="the database server has no database of that name",
                cause=clean(error),
                fix=f"{CONFIG} create the database named in DB_NAME, or correct it",
                facts=facts,
            )
        return CheckResult(
            name="database",
            status=FAIL,
            summary="the database server did not answer",
            cause=clean(error),
            fix=f"{CONFIG} check DB_HOST, DB_PORT and that the server is running",
            facts=facts,
        )
    return CheckResult(
        name="database",
        status=OK,
        summary="postgresql answered",
        facts=facts,
    )


def check_database(
    *,
    timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS,
) -> CheckResult:
    """Report whether the database is present, readable and internally consistent.

    On SQLite this reaches the same verdict the startup check reaches, from the
    same primitives, without the repairs. Nothing is written, no incident report
    is published and no write lock is taken, so this is safe to run against a
    Floppy that is currently serving.

    PostgreSQL has no comparable check to run from here. Reachability is what
    this reports for it.
    """
    if not settings.USING_SQLITE_DATABASE:
        return _check_postgres()

    db_path = Path(settings.FLOPPY_DB_PATH)
    facts = {"engine": "sqlite", "path": str(db_path)}

    if db_path.is_dir():
        # The paths check already explained this one. Opening it here would only
        # add "the database file cannot be read" and advise restoring a backup,
        # which sends the operator to recover data that was never lost.
        return CheckResult(
            name="database",
            status=SKIPPED,
            summary="not checked; the database path is a directory",
            facts=facts,
        )

    if not db_path.exists():
        return CheckResult(
            name="database",
            status=OK,
            summary="no database file yet; migrations will create one",
            facts=facts,
        )

    try:
        verdict = inspect_database(str(db_path), timeout_seconds=timeout_seconds)
    except IntegrityScanTimeoutError as error:
        return CheckResult(
            name="database",
            status=FAIL,
            summary="the storage check did not finish in time",
            cause=clean(error),
            fix=(
                f"{FLOPPY} raise the bound with --timeout, or move the database "
                "to faster storage"
            ),
            facts=facts,
        )
    except sqlite3.DatabaseError as error:
        busy = getattr(error, "sqlite_errorcode", None) in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
        }
        if busy:
            return CheckResult(
                name="database",
                status=FAIL,
                summary="the database is locked by another process",
                cause=clean(error),
                fix=f"{FLOPPY} stop the other Floppy processes, then try again",
                facts=facts,
            )
        return CheckResult(
            name="database",
            status=FAIL,
            summary="the database file cannot be read",
            cause=clean(error),
            fix=(
                f"{HOST} restore the most recent backup; keep the -wal and -shm "
                "files with it"
            ),
            facts=facts,
        )

    if verdict["quick_check"] != "ok":
        return CheckResult(
            name="database",
            status=FAIL,
            summary="the database reports damaged storage",
            cause=clean(f"quick_check returned {verdict['quick_check']!r}"),
            fix=(
                f"{HOST} restore the most recent backup; keep the -wal and -shm "
                "files with it"
            ),
            facts=facts,
        )

    conflicts = verdict["conflicts"]
    if conflicts:
        total = conflicts["total_conflicts"]
        tables = sorted({group["table"] for group in conflicts["groups"]})
        facts["conflicts"] = total
        facts["tables"] = tables
        return CheckResult(
            name="database",
            status=FAIL,
            summary=f"{total} relationship conflict(s) in {', '.join(tables)}",
            cause="rows point at parent rows that no longer exist",
            fix=(
                f"{FLOPPY} restart Floppy; startup repairs what it safely can "
                "and writes a report beside the database for the rest"
            ),
            facts=facts,
        )

    return CheckResult(
        name="database",
        status=OK,
        summary="sqlite storage and relationships are intact",
        facts=facts,
    )


def check_migrations(*, database_ok: bool) -> CheckResult:
    """Report whether any migration is waiting to be applied.

    Planning migrations needs a working connection. When the database check has
    already failed, running this would replace that clear result with a
    connection error, so it reports that it was skipped instead.

    Opening a connection to a SQLite path that does not exist creates the file,
    and reading the migration state then creates a table inside it. Looking at
    an installation must not build part of it, so on a first start this reports
    the obvious answer instead of asking the database for it.
    """
    if not database_ok:
        return CheckResult(
            name="migrations",
            status=SKIPPED,
            summary="not checked; the database is unavailable",
        )

    if settings.USING_SQLITE_DATABASE and not Path(settings.FLOPPY_DB_PATH).exists():
        return CheckResult(
            name="migrations",
            status=SKIPPED,
            summary="not checked; every migration runs when the database is created",
        )

    try:
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except DatabaseError as error:
        return CheckResult(
            name="migrations",
            status=FAIL,
            summary="the migration state cannot be read",
            cause=clean(error),
            fix=f"{FLOPPY} run with --auto-migrate, or restart Floppy",
        )

    if plan:
        names = [f"{migration.app_label}.{migration.name}" for migration, _ in plan]
        return CheckResult(
            name="migrations",
            status=FAIL,
            summary=f"{len(plan)} migration(s) pending",
            cause=f"first pending: {names[0]}",
            fix=f"{FLOPPY} run with --auto-migrate, or restart Floppy",
            facts={"pending": names},
        )

    return CheckResult(name="migrations", status=OK, summary="none pending")


def redis_endpoints() -> dict[str, list[str]]:
    """Map each distinct Redis URL to the roles that use it.

    Floppy reads five Redis settings. They collapse to one server in the shipped
    stack and can be five different servers, so they are grouped by URL: one ping
    per server, and a failure names the roles that server carries.
    """
    roles = {
        "default": settings.REDIS_URL,
        "cache": settings.REDIS_CACHE_URL,
        "admin": settings.REDIS_ADMIN_URL,
        "celery broker": settings.CELERY_BROKER_URL,
        "celery results": settings.CELERY_RESULT_BACKEND,
    }
    grouped: dict[str, list[str]] = {}
    for role, url in roles.items():
        # Celery accepts brokers this check cannot speak to, such as RabbitMQ
        # and a database backend. Pinging those with a Redis client reports a
        # healthy stack as broken, so they are left to their own services.
        if url and str(url).startswith(REDIS_SCHEMES):
            grouped.setdefault(str(url), []).append(role)
    return grouped


def _memory_ceiling(client: redis.Redis) -> int | None:
    """Return the server's maxmemory in bytes, or None when it cannot be read.

    A managed Redis, or one whose access control forbids CONFIG, answers with an
    error. That is not worth reporting: it means the operator does not control
    this setting from here.
    """
    try:
        reported = client.config_get("maxmemory")
    except (redis.RedisError, OSError):
        return None
    return parse_size(reported.get("maxmemory"))


def check_redis() -> CheckResult:
    """Ping every distinct Redis endpoint and report the first that fails.

    Connection errors from the client library often quote the connection string,
    password included, so nothing from an exception reaches the report without
    being cleaned first.
    """
    grouped = redis_endpoints()
    if not grouped:
        return CheckResult(
            name="redis",
            status=SKIPPED,
            summary="no Redis endpoint is configured",
        )

    facts = {
        "endpoints": [
            {"url": safe_url(url), "roles": roles} for url, roles in grouped.items()
        ]
    }
    unbounded = []

    for url, roles in grouped.items():
        shown = safe_url(url)
        try:
            client = redis.from_url(
                url,
                socket_connect_timeout=_NETWORK_TIMEOUT_SECONDS,
                socket_timeout=_NETWORK_TIMEOUT_SECONDS,
            )
            client.ping()
        except (redis.AuthenticationError, redis.ResponseError) as error:
            # The server answered. Sending the operator to check whether it is
            # running would send them to the wrong place entirely.
            return CheckResult(
                name="redis",
                status=FAIL,
                summary=f"{shown} refused the credentials ({', '.join(roles)})",
                cause=clean(error),
                fix=_where(
                    f"{CONFIG} correct the password in REDIS_URL for this stack",
                    f"{CONFIG} correct the password in REDIS_URL",
                ),
                facts=facts,
            )
        except (redis.RedisError, OSError, ValueError) as error:
            return CheckResult(
                name="redis",
                status=FAIL,
                summary=f"cannot reach {shown} ({', '.join(roles)})",
                cause=clean(error),
                fix=_where(
                    f"{CONFIG} check that the Redis service is running and "
                    "reachable",
                    f"{CONFIG} check that Redis is running and that REDIS_URL "
                    "points at it",
                ),
                facts=facts,
            )
        if _memory_ceiling(client) == 0:
            unbounded.append(shown)
        with suppress(redis.RedisError, OSError):
            client.close()

    served = sum(len(roles) for roles in grouped.values())
    summary = f"{len(grouped)} endpoint(s) reachable, serving {served} role(s)"

    if unbounded:
        return CheckResult(
            name="redis",
            status=WARN,
            summary=summary,
            cause=(
                f"{', '.join(unbounded)} has no memory ceiling, so it can grow until "
                "the host runs out of memory"
            ),
            fix=(
                f"{CONFIG} start Redis with --maxmemory and --maxmemory-policy, "
                f"or run {FLOPPY} python manage.py tune_redis"
            ),
            facts=facts,
        )

    return CheckResult(name="redis", status=OK, summary=summary, facts=facts)


def run_checks(
    *,
    include_redis: bool = True,
    timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS,
) -> list[CheckResult]:
    """Run every check in order and return what each one found.

    Order matters. The cheap checks run first so an obvious problem is reported
    before an expensive scan starts, and the database result decides whether the
    migration check can run at all.
    """
    database = None
    results = [check_paths(), check_config()]
    database = check_database(timeout_seconds=timeout_seconds)
    results.append(database)
    results.append(check_migrations(database_ok=not database.failed))
    if include_redis:
        results.append(check_redis())
    else:
        results.append(
            CheckResult(name="redis", status=SKIPPED, summary="skipped on request")
        )
    return results


def build_report(results: list[CheckResult]) -> dict:
    """Return the machine-readable report for a set of results."""
    return {
        "ok": not any(result.failed for result in results),
        "version": REPORT_VERSION,
        "checks": [result.as_dict() for result in results],
    }
