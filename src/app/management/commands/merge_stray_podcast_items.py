"""Fold podcast Items filed under a search id into the tracked show's Item.

Quick-add on a custom list once stored a searched podcast under its provider
id (an iTunes id or feed URL) rather than the show's ``podcast_uuid``. The
second Item carried the list entry but none of the show's tracking, so lists
showed the wrong status, could not remove the row, or held the show twice.
List pages repair their own strays on view; this sweeps the whole library.

Only shows already stored are matched, so it never uses the network.
Read-only by default. Pass --apply to write.
"""

from django.core.management.base import BaseCommand

from app.services.podcast_import import merge_stray_podcast_items


class Command(BaseCommand):
    """Merge stray podcast show Items."""

    help = "Merge podcast Items stored under a search id into the show's Item"

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a read-only report)",
        )

    def handle(self, *_args, **options):
        """Execute the command."""
        if options["apply"]:
            count = merge_stray_podcast_items()
            self.stdout.write(f"Repaired {count} stray podcast item(s).")
            return
        # Dry run: repair inside a transaction that is always rolled back.
        from django.db import transaction

        with transaction.atomic():
            count = merge_stray_podcast_items()
            transaction.set_rollback(True)
        self.stdout.write(f"Would repair {count} stray podcast item(s).")
        if count:
            self.stdout.write(
                self.style.WARNING("Re-run with --apply to write these changes."),
            )
