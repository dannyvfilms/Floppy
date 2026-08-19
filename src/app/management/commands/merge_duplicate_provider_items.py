"""Merge TMDB TV/season Items that duplicate an existing TVDB Item (#620).

Importers that only ever resolve shows via TMDB (Trakt, mdblist) can create a
second, independent `Item` tree for a show a TVDB-preferring user already
tracks, since nothing reconciled the two until now. This repairs libraries
that already accumulated such duplicates.

Read-only by default. Pass --apply to write. Matching is always via a
verified TVDB id resolution (see `app.services.item_merge`), never title -
an unresolvable or structurally-incompatible pair is left alone.
"""

from django.core.management.base import BaseCommand

from app.models import Item, MediaTypes, Sources
from app.providers import tvdb
from app.services import item_merge
from app.services.tv_provider_migration import migrate_tv_item_to_tvdb


class Command(BaseCommand):
    """Merge duplicate TMDB/TVDB Items for the same TV show."""

    help = (
        "Merge TMDB TV Items that duplicate an existing TVDB Item for the "
        "same show, folding watch history, tags, and other user data onto "
        "the TVDB item"
    )

    def add_arguments(self, parser):
        """Add command line arguments."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes (default is a read-only report)",
        )
        parser.add_argument(
            "--username",
            type=str,
            default=None,
            help="Only process shows tracked by this user",
        )

    def handle(self, *_args, **options):
        """Execute the command."""
        self.apply = options["apply"]

        if not tvdb.enabled():
            self.stdout.write("TVDB not configured; nothing to do.")
            return

        queryset = Item.objects.filter(
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
        ).exclude(library_media_type=MediaTypes.ANIME.value)
        if options["username"]:
            queryset = queryset.filter(
                tv__user__username=options["username"],
            ).distinct()

        items = list(queryset.order_by("media_id"))
        mode = "APPLYING" if self.apply else "DRY RUN (no changes written)"
        self.stdout.write(f"{mode} - checking {len(items)} TMDB TV item(s)\n")

        counts = {"merged": 0, "would_merge": 0, "skipped": 0, "errored": 0}
        for item in items:
            self._process_item(item, counts)

        self.stdout.write(
            "\nMerged: {merged}  Would merge: {would_merge}  "
            "Skipped: {skipped}  Errored: {errored}".format(**counts),
        )
        if not self.apply and counts["would_merge"]:
            self.stdout.write(
                self.style.WARNING("\nRe-run with --apply to write these changes."),
            )

    def _process_item(self, item, counts):
        """Check one TMDB show for a verified TVDB duplicate and act on it."""
        duplicate = item_merge.find_cross_provider_duplicate(item)
        if duplicate is None:
            counts["skipped"] += 1
            return

        label = f"{item.title} (TMDB {item.media_id} -> TVDB {duplicate.media_id})"

        if not self.apply:
            self.stdout.write(f"Would merge: {label}")
            counts["would_merge"] += 1
            return

        try:
            result = migrate_tv_item_to_tvdb(item)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Error merging {label}: {exc}"))
            counts["errored"] += 1
            return

        if result.migrated:
            self.stdout.write(f"Merged: {label}")
            counts["merged"] += 1
        else:
            self.stdout.write(f"Skipped {label}: {result.reason}")
            counts["skipped"] += 1
