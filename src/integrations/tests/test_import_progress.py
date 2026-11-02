"""Progress stays timely without a Redis write for every imported row."""

from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.test import SimpleTestCase, tag

from integrations import import_progress


class ImportProgressTests(SimpleTestCase):
    """Exercise stage, row and elapsed-time publication boundaries."""

    def setUp(self):
        self.cache = patch.object(import_progress, "cache").start()
        self.clock = patch.object(import_progress.time, "monotonic", return_value=0).start()
        self.addCleanup(patch.stopall)

    @tag("slow", "benchmark")
    def test_large_history_has_bounded_writes_and_final_count(self):
        with import_progress.tracking("history"):
            for current in range(1, 80_850):
                import_progress.report(current, 80_849, "history")
            self.assertEqual(self.cache.set.call_count, 325)
            self.assertEqual(self.cache.set.call_args.args[1]["current"], 80_849)
        self.cache.delete.assert_called_once_with("import_progress:history")

    def test_interval_stage_and_reset_are_immediate(self):
        with import_progress.tracking("history"):
            import_progress.report(1, None, "gathering")
            import_progress.report(2, None, "gathering")
            self.assertEqual(self.cache.set.call_count, 1)
            self.clock.return_value = 1
            import_progress.report(2, None, "gathering")
            import_progress.report(2, 100, "gathering")
            import_progress.report(2, 100, "history")
            import_progress.report(1, 100, "history")
            self.assertEqual(self.cache.set.call_count, 5)

    def test_terminal_unknown_total_and_zero_total(self):
        with import_progress.tracking("history"):
            import_progress.report(0, None, "gathering")
            import_progress.report(1, None, "gathering")
            self.assertEqual(self.cache.set.call_count, 1)
            import_progress.report(0, 0, "history")
            import_progress.report(1, 2, "history")
            import_progress.report(2, 2, "history")
            import_progress.report(2, 2, "history")
            self.assertEqual(self.cache.set.call_count, 4)

    def test_nested_tracking_restores_outer_progress_and_run_id(self):
        with import_progress.tracking("outer", 10):
            import_progress.report(1, 1000, "history")
            with import_progress.tracking("inner", 20):
                import_progress.report(1, 1000, "history")
                self.assertEqual(import_progress.get_current_import_run_id(), 20)
            self.assertEqual(import_progress.get_current_import_run_id(), 10)
            import_progress.report(2, 1000, "history")
        self.assertEqual(self.cache.set.call_count, 2)
        self.assertIsNone(import_progress.get_current_import_run_id())

    def test_failure_and_cancellation_remove_progress(self):
        for exception in (ValueError("failure"), SoftTimeLimitExceeded()):
            with self.subTest(exception=type(exception).__name__):
                with self.assertRaises(type(exception)), import_progress.tracking("failed"):
                    import_progress.report(1, 100, "history")
                    raise exception
                self.cache.delete.assert_called_with("import_progress:failed")
        import_progress.report(5, 10, "outside")
        self.assertEqual(self.cache.set.call_count, 2)

    def test_failed_cache_write_is_not_recorded_as_published(self):
        with import_progress.tracking("history"):
            self.cache.set.side_effect = [RuntimeError("unavailable"), None]
            with self.assertRaises(RuntimeError):
                import_progress.report(1, 100, "history")
            import_progress.report(2, 100, "history")
            self.assertEqual(self.cache.set.call_count, 2)
