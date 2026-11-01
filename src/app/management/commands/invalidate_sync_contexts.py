"""Explicitly invalidate reliable synchronization after restore or protocol reset."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app.services.sync_lock import invalidate_contexts, state_transaction


class Command(BaseCommand):
    """Rotate the per-user protocol generation after an explicit reset."""

    help = (
        "Invalidate contract=2 contexts without changing media or provider permissions."
    )

    def add_arguments(self, parser):
        """Require an explicit user selection."""
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--all-users", action="store_true")
        selector.add_argument("--user-id", type=int)

    def handle(self, *args, **options):
        """Invalidate contexts under the same barrier as strict readers."""
        users = get_user_model().objects.order_by("pk")
        if options["user_id"] is not None:
            users = users.filter(pk=options["user_id"])
            if not users.exists():
                message = "User does not exist."
                raise CommandError(message)
        count = 0
        for user_id in users.values_list("pk", flat=True).iterator():
            with state_transaction(user_id) as row:
                invalidate_contexts(row)
            count += 1
        self.stdout.write(f"Invalidated synchronization contexts for {count} user(s).")
