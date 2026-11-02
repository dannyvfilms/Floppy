from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from django_celery_results.models import TaskResult

from app import signals
from config.celery import app
from integrations import tasks


class StremioPeriodicImportVisibilityTests(TestCase):
    """Regression coverage for Stremio periodic-import visibility."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="stremio-visibility",
            password="12345",
        )
        self.crontab = CrontabSchedule.objects.create(
            minute="0",
            hour="0",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )

    def test_disabled_stremio_schedule_is_not_reported_or_mutated(self):
        """Reading import status must ignore and preserve a disabled schedule."""
        kwargs = f'{{"user_id": {self.user.id}}}'
        periodic_task = PeriodicTask.objects.create(
            name="Import from Stremio for test (every 2 hours)",
            task="Import from Stremio (Recurring)",
            kwargs=kwargs,
            crontab=self.crontab,
            enabled=False,
        )

        import_tasks = self.user.get_import_tasks()

        self.assertEqual(import_tasks["schedules"], [])

        periodic_task.refresh_from_db()
        self.assertFalse(periodic_task.enabled)
        self.assertEqual(periodic_task.task, "Import from Stremio (Recurring)")
        self.assertEqual(periodic_task.crontab_id, self.crontab.id)
        self.assertEqual(periodic_task.kwargs, kwargs)


class ImportTaskRegistryConsistencyTests(TestCase):
    """New import names appear without a separate registration."""

    def test_registered_recurring_imports_match_the_schedule_query(self):
        app.loader.import_default_modules()
        recurring = {name for name in app.tasks if name.endswith("(Recurring)")}
        self.assertIn(tasks.import_stremio_recurring.name, recurring)
        user = get_user_model().objects.create_user(username="registry-check")
        with patch("users.models.PeriodicTask.objects.filter") as periodic_filter:
            periodic_filter.return_value.select_related.return_value = []
            user.get_import_tasks()
        query = periodic_filter.call_args.args[1]
        for name in recurring:
            self.assertTrue(name.startswith("Import "), name)
        self.assertIn("task__startswith", str(query))

    def test_registered_import_functions_follow_the_tracking_convention(self):
        app.loader.import_default_modules()
        untracked = {
            name
            for name, task in app.tasks.items()
            if getattr(getattr(task, "run", None), "__name__", "").startswith("import_")
            and not signals._is_tracked_task(name)
        }
        self.assertEqual(untracked, set())

    def test_unmapped_import_is_published_and_visible_for_its_owner(self):
        user = get_user_model().objects.create_user(username="new-import-owner")
        other = get_user_model().objects.create_user(username="other-import-owner")
        task_id = "new-import-task"
        signals.create_task_result_on_publish(
            headers={
                "task": "Import from New Source",
                "id": task_id,
                "kwargsrepr": f"{{'user_id': {user.id}}}",
            }
        )
        self.assertEqual(TaskResult.objects.get(task_id=task_id).status, "PENDING")
        with patch("users.models.AsyncResult") as result:
            result.return_value.status = "PENDING"
            rows = user.get_import_tasks()["results"]
            self.assertEqual(other.get_import_tasks()["results"], [])
        self.assertEqual(rows[0]["source"], "New Source")
        sender = type("Sender", (), {"name": "Import from New Source"})()
        signals.update_task_result_on_failure(
            sender=sender,
            task_id=task_id,
            exception=ValueError("bad file"),
        )
        rows = user.get_import_tasks()["results"]
        self.assertEqual(rows[0]["status"], "FAILURE")
        self.assertIn("bad file", TaskResult.objects.get(task_id=task_id).result)

    def test_unmapped_import_schedule_is_visible(self):
        user = get_user_model().objects.create_user(username="schedule-owner")
        crontab = CrontabSchedule.objects.create(
            minute="0",
            hour="0",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name="Import from New Source",
            task="Import from New Source (Recurring)",
            kwargs=f'{{"user_id": {user.id}}}',
            crontab=crontab,
        )
        rows = user.get_import_tasks()["schedules"]
        self.assertEqual(rows[0]["source"], "New Source (Recurring)")
