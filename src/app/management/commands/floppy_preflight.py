"""Report whether this Floppy installation can start.

The checks live in ``app.preflight``. This command runs them, prints what they
found and sets the exit code, the same split ``tune_redis`` uses for
``app.redis_tuning``.

Run it when a container will not start:

    docker exec floppy python manage.py floppy_preflight

If the container is restarting instead of running, ``docker exec`` cannot attach
to it. Use a one-off container against the same volumes:

    docker compose run --rm floppy python manage.py floppy_preflight

Nothing is repaired. The only exception is ``--auto-migrate``, which applies
pending migrations because the operator asked for them.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

from django.core.management import call_command
from django.core.management.base import BaseCommand

from app.preflight import (
    DEFAULT_SCAN_TIMEOUT_SECONDS,
    FAIL,
    FLOPPY,
    OK,
    REPORT_VERSION,
    SKIPPED,
    WARN,
    CheckResult,
    build_report,
    check_migrations,
    clean,
    run_checks,
)

_LABEL = {OK: "ok", WARN: "warn", FAIL: "FAIL", SKIPPED: "skip"}
_NAME_WIDTH = 11
_STATUS_WIDTH = 6
_DETAIL_INDENT = " " * (_NAME_WIDTH + _STATUS_WIDTH)


class Command(BaseCommand):
    """Report deployment readiness without changing anything."""

    help = (
        "Report whether this installation can start: paths, settings, database, "
        "migrations and Redis. Reads only. --auto-migrate is the one exception."
    )

    # Django prints system check output to standard output, which would break the
    # JSON report. The checks still run: app.preflight.check_config invokes them
    # and reports their findings like every other check.
    requires_system_checks = []

    def add_arguments(self, parser):
        """Register command arguments."""
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print one JSON object and nothing else",
        )
        parser.add_argument(
            "--no-redis",
            action="store_true",
            help="Skip the Redis check",
        )
        parser.add_argument(
            "--auto-migrate",
            action="store_true",
            help="Apply pending migrations, then check again",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=DEFAULT_SCAN_TIMEOUT_SECONDS,
            metavar="SECONDS",
            help=(
                "Bound the database storage scan "
                f"(default: {DEFAULT_SCAN_TIMEOUT_SECONDS:g})"
            ),
        )

    def handle(self, *_args, **options):
        """Run the checks, report them, and exit non-zero if any of them failed."""
        as_json = options["json"]
        try:
            results = run_checks(
                include_redis=not options["no_redis"],
                timeout_seconds=options["timeout"],
            )
            if options["auto_migrate"]:
                results = self._apply_migrations(results)
        except Exception as error:
            # A supervisor that reads standard output must never receive an empty
            # string and a traceback on standard error. Report the failure in the
            # shape the caller asked for.
            self._emit(self._crash_report(error), as_json=as_json)
            sys.exit(1)

        report = build_report(results)
        self._emit(report, as_json=as_json)
        if not report["ok"]:
            sys.exit(1)

    def _crash_report(self, error: BaseException) -> dict:
        """Return a valid report for a failure that stopped the checks."""
        return {
            "ok": False,
            "version": REPORT_VERSION,
            "checks": [
                {
                    "name": "preflight",
                    "status": FAIL,
                    "summary": "the checks could not be completed",
                    "cause": f"{type(error).__name__}: {error}",
                }
            ],
        }

    def _apply_migrations(self, results):
        """Apply pending migrations, then check again that none remain.

        Everything the migration run prints is captured, because any of it would
        corrupt the JSON report. Passing ``stdout`` to ``call_command`` is not
        enough on its own: that only rebinds the stream the *command* writes to,
        and a data migration that calls ``print`` writes past it to the real
        standard output. ``lists.0004`` does exactly that to report its progress.
        Redirecting the stream itself catches both.
        """
        migrations = next(r for r in results if r.name == "migrations")
        # Anything other than a clean bill means there is work to do. A first
        # start reports "skipped", because asking an absent database about its
        # migrations would create it, and an operator who asked for migrations
        # on a first start means exactly this: build it.
        if migrations.status == OK:
            return results

        captured = io.StringIO()
        errors = io.StringIO()
        try:
            with redirect_stdout(captured):
                call_command("migrate", "--noinput", stdout=captured, stderr=errors)
        except Exception as error:
            # A migration can fail for reasons preflight cannot fix, such as an
            # inconsistent history or a lock. Replacing every result with one
            # crash line would throw away the paths, settings, database and
            # Redis answers the operator already has, so this stays a migration
            # failure and the rest of the report survives.
            rechecked = CheckResult(
                name="migrations",
                status=FAIL,
                summary="the migrations could not be applied",
                cause=clean(f"{type(error).__name__}: {error}"),
                fix=f"{FLOPPY} read the migration error above and correct it first",
            )
            return [rechecked if r.name == "migrations" else r for r in results]

        database = next(r for r in results if r.name == "database")
        rechecked = check_migrations(database_ok=not database.failed)
        return [rechecked if r.name == "migrations" else r for r in results]

    def _emit(self, report: dict, *, as_json: bool) -> None:
        """Write the report in the form the caller asked for."""
        if as_json:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return

        for check in report["checks"]:
            label = _LABEL.get(check["status"], check["status"])
            name = check["name"].ljust(_NAME_WIDTH)
            self.stdout.write(f"{name}{label.ljust(_STATUS_WIDTH)}{check['summary']}")
            if check.get("cause"):
                self.stdout.write(f"{_DETAIL_INDENT}cause: {check['cause']}")
            if check.get("fix"):
                self.stdout.write(f"{_DETAIL_INDENT}fix:   {check['fix']}")

        if report["ok"]:
            warned = any(c["status"] == WARN for c in report["checks"])
            verdict = "preflight: ok, with warnings" if warned else "preflight: ok"
            self.stdout.write(self.style.SUCCESS(verdict))
        else:
            failed = [c["name"] for c in report["checks"] if c["status"] == FAIL]
            self.stdout.write(
                self.style.ERROR(f"preflight: failed ({', '.join(failed)})")
            )
