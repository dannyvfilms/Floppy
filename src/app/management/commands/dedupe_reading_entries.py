"""Remove duplicate reading entries left behind by repeated imports.

A StoryGraph import running on a server whose timezone is not UTC compared a
locally parsed read date against a UTC one, so it recreated every dated read
on every run instead of skipping it. The importer no longer does that, but a
library that was imported more than once still carries the extra rows.

Two rows are duplicates when they belong to the same user and item, share a
status, and land on the same local calendar day. Only same-day rows are
touched, so a genuine re-read - the whole reason one item carries several
rows - is never merged away. The oldest row survives, but any score, notes,
progress or start date the losers carry is folded into it first, so nothing
the user typed is lost.

Read-only by default. Pass --apply to write.
"""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from app.models import Book, Comic, DeletedMedia, Manga

MODELS = {
    "book": Book,
    "comic": Comic,
    "manga": Manga,
}
MERGED_FIELDS = ("score", "notes", "progress", "start_date", "end_date")
MIN_GROUP_SIZE = 2


class Command(BaseCommand):
    """Collapse same-day duplicate reading entries."""

    help = (
        "Remove duplicate book/comic/manga entries that share a user, an item "
        "and a local calendar day, keeping the richest row"
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
            help="Only process entries belonging to this user",
        )
        parser.add_argument(
            "--media-type",
            choices=sorted(MODELS),
            default=None,
            help="Only process this media type (default: all reading types)",
        )

    def handle(self, *_args, **options):
        """Execute the command."""
        self.apply = options["apply"]

        users = get_user_model().objects.all()
        if options["username"]:
            users = users.filter(username=options["username"])
        users = list(users.order_by("username"))
        if not users:
            self.stdout.write("No matching users.")
            return

        media_types = (
            [options["media_type"]] if options["media_type"] else sorted(MODELS)
        )

        mode = "APPLYING" if self.apply else "DRY RUN (no changes written)"
        self.stdout.write(f"{mode}\n")

        removed = 0
        for user in users:
            for media_type in media_types:
                removed += self._process(user, MODELS[media_type], media_type)

        if not removed:
            self.stdout.write("No duplicate reading entries found.")
            return

        verb = "removed" if self.apply else "to remove"
        self.stdout.write(f"\nDuplicate rows {verb}: {removed}")
        if not self.apply:
            self.stdout.write(
                self.style.WARNING("\nRe-run with --apply to write these changes."),
            )

    def _process(self, user, model, media_type):
        """Collapse duplicates of one media type for one user."""
        groups = defaultdict(list)
        queryset = model.objects.filter(user=user).select_related("item")
        for entry in queryset.order_by("id"):
            day = timezone.localdate(entry.end_date) if entry.end_date else None
            groups[(entry.item_id, entry.status, day)].append(entry)

        removed = 0
        for (_item_id, _status, day), entries in groups.items():
            if len(entries) < MIN_GROUP_SIZE:
                continue

            keeper, losers = entries[0], entries[1:]
            self.stdout.write(
                f"{user.username}/{media_type}: {keeper.item.title} - "
                f"{len(losers)} duplicate row(s) on {day or 'no date'}, "
                f"keeping #{keeper.pk}",
            )
            removed += len(losers)

            if not self.apply:
                continue

            with transaction.atomic():
                self._merge(keeper, losers)
                model.objects.filter(pk__in=[loser.pk for loser in losers]).delete()
                # Deleting a tracked row records a tombstone so imports do not
                # recreate media the user threw away. That is the wrong signal
                # here: the item is still tracked by the keeper, and leaving the
                # tombstone would make later imports skip a book the user still
                # has.
                DeletedMedia.objects.filter(
                    user=user,
                    media_type=keeper.item.media_type,
                    source=keeper.item.source,
                    media_id=keeper.item.media_id,
                ).delete()

        return removed

    def _merge(self, keeper, losers):
        """Fold any value the keeper is missing in from the duplicate rows."""
        changed = []
        for field in MERGED_FIELDS:
            if getattr(keeper, field) not in (None, "", 0):
                continue
            for loser in losers:
                value = getattr(loser, field)
                if value not in (None, "", 0):
                    setattr(keeper, field, value)
                    changed.append(field)
                    break
        if changed:
            keeper.save(update_fields=changed)
