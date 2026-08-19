"""Apply (or preview) Floppy's Redis memory ceiling."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from app.redis_tuning import derive_maxmemory_bytes, tune_redis
from config.runtime_profile import MIB, PROFILE


class Command(BaseCommand):
    """Set maxmemory and an eviction policy on Redis if it has none.

    Floppy already does this on startup; this command exists so the decision is
    inspectable when diagnosing a memory problem, and so an operator can apply
    it to a Redis that came up after Floppy did.
    """

    help = "Set a memory ceiling and eviction policy on Redis if none is configured"

    def add_arguments(self, parser):
        """Register command arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without issuing CONFIG SET",
        )

    def handle(self, *_args, **options):
        """Report the detected host profile and tune Redis accordingly."""
        dry_run = options["dry_run"]
        budget = derive_maxmemory_bytes()

        self.stdout.write(f"host: {PROFILE.describe()}")
        if budget is None:
            self.stdout.write("budget: none (Redis will be left untouched)")
        else:
            self.stdout.write(f"budget: {budget // MIB} MiB")

        summary = tune_redis(dry_run=dry_run)

        for label in ("applied", "skipped"):
            for key, value in summary[label].items():
                prefix = "would apply" if (dry_run and label == "applied") else label
                self.stdout.write(f"{prefix}: {key}={value}")

        for error in summary["errors"]:
            self.stdout.write(self.style.WARNING(f"error: {error}"))

        if summary["errors"]:
            self.stdout.write(
                self.style.WARNING(
                    "Redis could not be tuned from here. Set the limit on the "
                    "server instead, e.g. command: redis-server --appendonly yes "
                    '--save "" --maxmemory 256mb --maxmemory-policy volatile-lru',
                ),
            )
        elif summary["applied"] and not dry_run:
            self.stdout.write(self.style.SUCCESS("Redis tuned."))
