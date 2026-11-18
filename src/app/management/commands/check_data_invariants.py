"""Report the data invariants Floppy should always satisfy.

The checks live in ``app.data_invariants``; this command runs them and prints
what they counted, the same split ``floppy_preflight`` uses for
``app.preflight``.

    python manage.py check_data_invariants
    python manage.py check_data_invariants --verbose --user 3
    python manage.py check_data_invariants --json

Reads only. It never writes, opens no transaction and queues no task, so it is
safe against a running instance. There is no repair mode.

Each count is marked ``always a fault`` or ``review``. The exit code is 0 unless
``--strict`` is given and a fault was found.
"""

from __future__ import annotations

import json
import sys
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app.data_invariants import (
    DEFAULT_EXAMPLES,
    FAULT,
    KIND_LABELS,
    REVIEW,
    run_checks,
)

REPORT_VERSION = 1
_NAME_WIDTH = 36
_COUNT_WIDTH = 9
_KIND_WIDTH = 16
_DETAIL_INDENT = " " * 4


class Command(BaseCommand):
    """Count data that breaks an invariant, without changing anything."""

    help = (
        "Count items, plays and trackers that break a data invariant. Reads only; "
        "nothing is repaired."
    )

    # System check output on standard output would break the JSON report.
    requires_system_checks = []

    def add_arguments(self, parser):
        """Register command arguments."""
        parser.add_argument("--json", action="store_true", help="Print one JSON object")
        parser.add_argument(
            "--user",
            type=int,
            metavar="ID",
            help="Only count data belonging to this user id",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help=f"Show up to {DEFAULT_EXAMPLES} example ids per check",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit 1 when any fault is found (review counts never fail)",
        )

    def handle(self, *_args, **options):
        """Run the checks and print them."""
        user_id = options["user"]
        if (
            user_id is not None
            and not get_user_model()._base_manager.filter(pk=user_id).exists()
        ):
            msg = f"No user with id {user_id}"
            raise CommandError(msg)

        verbose = options["verbose"] or options["verbosity"] >= 2  # noqa: PLR2004
        started = time.perf_counter()
        results = run_checks(
            user_id=user_id, examples=DEFAULT_EXAMPLES if verbose else 0
        )
        report = {
            "version": REPORT_VERSION,
            "user": user_id,
            "faults": sum(1 for r in results if r.failed),
            "seconds": round(time.perf_counter() - started, 3),
            "checks": [r.as_dict() for r in results],
        }

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        else:
            self._print(report, verbose=verbose)

        if options["strict"] and report["faults"]:
            sys.exit(1)

    def _print(self, report, *, verbose):
        scope = f"user {report['user']}" if report["user"] is not None else "all users"
        self.stdout.write(f"Data invariants ({scope})")
        for check in report["checks"]:
            label = KIND_LABELS[check["kind"]]
            if check["approximate"]:
                label += "~"
            line = (
                f"{check['name'].ljust(_NAME_WIDTH)}"
                f"{str(check['count']).rjust(_COUNT_WIDTH)}  "
                f"{label.ljust(_KIND_WIDTH)}{check['description']}"
            )
            if check["kind"] == FAULT and check["count"]:
                line = self.style.ERROR(line)
            elif check["kind"] == REVIEW and check["count"]:
                line = self.style.WARNING(line)
            self.stdout.write(line)
            if check["breakdown"] and check["count"]:
                parts = ", ".join(
                    f"{key} {value}" for key, value in check["breakdown"].items()
                )
                self.stdout.write(f"{_DETAIL_INDENT}{parts}")
            if verbose and check["examples"]:
                ids = ", ".join(str(i) for i in check["examples"])
                self.stdout.write(f"{_DETAIL_INDENT}{check['example_label']}: {ids}")
        self.stdout.write(
            f"{report['faults']} fault check(s) found data; "
            f"{report['seconds']:.2f} s. "
            "~ marks an approximate rule. Nothing was changed."
        )
