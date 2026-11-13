import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from app.tasks_db_warm import warm_database_page_cache


class WarmDatabasePageCacheTests(SimpleTestCase):
    def _databases(self, path):
        return {"default": {"NAME": path}}

    def test_reads_budget_and_reports_throughput(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "db.sqlite3"
            path.write_bytes(b"x" * (3 * 1024 * 1024))
            with override_settings(
                DATABASES=self._databases(str(path)),
                DB_WARM_MAX_MIB=2,
                DB_WARM_PAUSE_MS=0,
            ):
                result = warm_database_page_cache()
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(result["warmed_bytes"], 2 * 1024 * 1024)
        self.assertGreater(result["warmed_bytes"], 0)

    @override_settings(DB_WARM_ENABLED=False)
    def test_disabled_skips(self):
        self.assertEqual(warm_database_page_cache()["reason"], "disabled")

    def test_missing_file_skips(self):
        with override_settings(DATABASES=self._databases("/nonexistent/db.sqlite3")):
            self.assertEqual(warm_database_page_cache()["reason"], "missing")


class WarmOnWorkerStartTests(SimpleTestCase):
    """A restart is when the cache is coldest, so the worker warms at once."""

    def test_background_worker_queues_a_warm(self):
        from config import celery

        with (
            mock.patch.dict("os.environ", {"FLOPPY_PROCESS_ROLE": "background"}),
            mock.patch.object(celery.app, "send_task") as send_task,
        ):
            celery._warm_database_on_start()
        send_task.assert_called_once_with(
            "Warm database page cache",
            ignore_result=True,
        )

    def test_interactive_worker_does_not(self):
        from config import celery

        with (
            mock.patch.dict("os.environ", {"FLOPPY_PROCESS_ROLE": "interactive"}),
            mock.patch.object(celery.app, "send_task") as send_task,
        ):
            celery._warm_database_on_start()
        send_task.assert_not_called()

    def test_a_broker_error_does_not_stop_the_worker(self):
        from config import celery

        with (
            mock.patch.dict("os.environ", {"FLOPPY_PROCESS_ROLE": "background"}),
            mock.patch.object(celery.app, "send_task", side_effect=OSError("down")),
        ):
            celery._warm_database_on_start()
