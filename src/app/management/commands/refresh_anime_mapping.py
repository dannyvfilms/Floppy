"""Manually fetch and validate a pinned Kometa Anime-IDs revision."""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError

from integrations import anime_mapping

REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class Command(BaseCommand):
    """Build a versioned mapping snapshot without changing application code."""

    help = "Fetch, validate, and cache a pinned Anime-IDs mapping snapshot"

    def add_arguments(self, parser):
        """Add revision and activation options."""
        parser.add_argument(
            "--revision",
            default=anime_mapping.APPROVED_REVISION,
            help="40-character Anime-IDs commit revision",
        )
        parser.add_argument(
            "--expected-digest",
            default=None,
            help="Expected canonical JSON SHA256 digest",
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Mark this validated snapshot as the last-known-good fallback",
        )

    def handle(self, *_args, **options):
        """Fetch and report one validated mapping snapshot."""
        revision = options["revision"].strip().lower()
        if not REVISION_PATTERN.fullmatch(revision):
            message = "--revision must be a 40-character lowercase commit SHA"
            raise CommandError(message)

        expected_digest = options["expected_digest"]
        if expected_digest and not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            message = "--expected-digest must be a 64-character SHA256 digest"
            raise CommandError(message)

        try:
            snapshot = anime_mapping.refresh_mapping_snapshot(
                revision,
                expected_digest=expected_digest,
                activate=options["activate"],
            )
        except Exception as error:
            message = f"Anime-IDs refresh failed: {error}"
            raise CommandError(message) from error

        output = (
            f"Validated Anime-IDs snapshot: revision={snapshot.revision} "
            f"digest={snapshot.digest} entries={snapshot.entry_count} "
            f"groups={len(snapshot.groups)} activated={options['activate']}"
        )
        self.stdout.write(
            self.style.SUCCESS(output),
        )
