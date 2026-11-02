import tempfile
from pathlib import Path

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
