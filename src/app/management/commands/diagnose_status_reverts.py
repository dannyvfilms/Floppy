"""Show what has been changing a user's show statuses, and what could.

Built for #1133: a user's Dropped/Completed shows kept reverting overnight
and nobody could tell which sync did it. Run inside the container with::

    python manage.py diagnose_status_reverts --user <username> [--days 3]

The output lists recent show/season status changes with the reason Floppy
recorded for each, the user's scheduled imports (with their mode), and how
many deleted shows are being kept deleted. It never prints tokens.
"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from app.models import TV, DeletedMedia, MediaTypes, Season


class Command(BaseCommand):
    """Report recent status changes and scheduled syncs for one user."""

    help = "Show recent TV/season status changes and the syncs that can make them"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument("--user", required=True, help="Username to inspect")
        parser.add_argument(
            "--days",
            type=int,
            default=3,
            help="How many days of status changes to show (default: 3)",
        )

    def handle(self, *args, **options):
        """Print the report."""
        user = get_user_model().objects.filter(username=options["user"]).first()
        if user is None:
            msg = f"No user named {options['user']!r}"
            raise CommandError(msg)
        since = timezone.now() - timedelta(days=options["days"])

        self._status_changes(user, since)
        self._schedules(user)
        deleted = DeletedMedia.objects.filter(
            user=user,
            media_type=MediaTypes.TV.value,
        ).count()
        self.stdout.write(f"\nDeleted shows kept deleted: {deleted}\n")

    def _status_changes(self, user, since):
        self.stdout.write(f"Status changes since {since:%Y-%m-%d %H:%M} (UTC)\n")
        rows = []
        # History rows don't keep the user or item, so look them up through
        # the user's live entries.
        labels = {
            TV: {
                tv.id: tv.item.title
                for tv in TV.objects.filter(user=user).select_related("item")
            },
            Season: {
                season.id: f"{season.item.title} S{season.item.season_number}"
                for season in Season.objects.filter(user=user).select_related("item")
            },
        }
        for model, model_labels in labels.items():
            history = model.history.model.objects.filter(
                id__in=model_labels,
            ).order_by("id", "history_date", "history_id")
            previous = {}
            for record in history.iterator():
                old = previous.get(record.id)
                previous[record.id] = record.status
                if record.history_date < since or old == record.status:
                    continue
                rows.append(
                    (
                        record.history_date,
                        model_labels[record.id],
                        old or "(created)",
                        record.status,
                        record.history_change_reason or "not recorded",
                    ),
                )
        if not rows:
            self.stdout.write("  none\n")
        for when, label, old, new, reason in sorted(rows):
            self.stdout.write(
                f"  {when:%Y-%m-%d %H:%M}  {label}: {old} -> {new}  [{reason}]\n",
            )

    def _schedules(self, user):
        self.stdout.write("\nScheduled syncs\n")
        found = False
        imports_by_task = {}
        for task in PeriodicTask.objects.select_related("crontab", "interval"):
            try:
                kwargs = json.loads(task.kwargs or "{}")
            except ValueError:
                continue
            if kwargs.get("user_id") != user.id:
                continue
            found = True
            imports_by_task[task.task] = imports_by_task.get(task.task, 0) + 1
            when = task.crontab or task.interval or "-"
            mode = kwargs.get("mode", "-")
            flag = "  <- rebuilds shows from the source" if mode == "overwrite" else ""
            self.stdout.write(
                f"  {task.task} | {when} | mode={mode} | "
                f"enabled={task.enabled}{flag}\n",
            )
        if not found:
            self.stdout.write("  none\n")
        for task_name, count in sorted(imports_by_task.items()):
            if count > 1:
                self.stdout.write(
                    f"  note: {count} schedules run {task_name!r}; "
                    "older ones keep running after a reconnect\n",
                )
