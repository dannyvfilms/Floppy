"""Tests for the progress lines written around every Celery task."""

from celery import shared_task
from django.test import TestCase

from app import task_progress


@shared_task(name="app.tests.task_progress_demo")
def _demo_task(secret_argument):
    return "done"


class TaskProgressTests(TestCase):
    """The lines show the task's life and never its arguments."""

    def test_task_writes_started_and_finished_lines(self):
        """Running a task logs a start and a finish with state and duration."""
        with self.assertLogs("floppy.progress", level="INFO") as captured:
            _demo_task.apply(args=["alice@example.com"])

        lines = [record.getMessage() for record in captured.records]
        started = [m for m in lines if "task_started name=app.tests.task_progress_demo" in m]
        finished = [m for m in lines if "task_finished name=app.tests.task_progress_demo" in m]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(finished), 1)
        self.assertIn("state=SUCCESS", finished[0])
        self.assertRegex(finished[0], r"duration_ms=\d+")
        self.assertTrue(all(m.startswith("[progress] ") for m in lines))

    def test_arguments_are_never_logged(self):
        """Task arguments can hold usernames or titles, so they stay out."""
        with self.assertLogs("floppy.progress", level="INFO") as captured:
            _demo_task.apply(args=["alice@example.com"])

        self.assertNotIn(
            "alice@example.com",
            " ".join(record.getMessage() for record in captured.records),
        )

    def test_finish_without_a_start_reports_unknown_duration(self):
        """A finish whose start was missed still logs, with duration -1."""
        task_progress._started.clear()
        with self.assertLogs("floppy.progress", level="INFO") as captured:
            task_progress._task_finished(task_id="abc12345", state="SUCCESS")

        self.assertIn("duration_ms=-1", captured.records[0].getMessage())
