"""The two per-minute maintenance tasks must be bounded and leave a trail."""

from unittest import mock

from django.test import TestCase

from app.tasks_interactive import reconcile_statistics_sync_task
from integrations.tasks._state_sync import sweep_watched_state_deliveries


class PeriodicTaskBoundsTests(TestCase):
    """A wedged run has to be killed, and a stalled one has to be visible."""

    def test_time_limits_are_set_and_ordered(self):
        for task in (reconcile_statistics_sync_task, sweep_watched_state_deliveries):
            self.assertTrue(0 < task.soft_time_limit < task.time_limit <= 300)

    def test_reconcile_logs_start_and_finish(self):
        with (
            mock.patch("app.statistics_sync.reconcile", return_value=2),
            self.assertLogs("app.tasks_interactive", "INFO") as logs,
        ):
            reconcile_statistics_sync_task()
        text = "\n".join(logs.output)
        self.assertIn("reconcile_statistics_sync start", text)
        self.assertIn("reconcile_statistics_sync finish queued=2", text)

    def test_sweep_logs_start_and_finish(self):
        with self.assertLogs("integrations.tasks._state_sync", "INFO") as logs:
            sweep_watched_state_deliveries()
        text = "\n".join(logs.output)
        self.assertIn("sweep_watched_state start", text)
        self.assertIn("sweep_watched_state finish swept=0", text)
