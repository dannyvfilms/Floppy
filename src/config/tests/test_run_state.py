import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from config import run_state

MIB = 1024 * 1024


class RunStateTests(SimpleTestCase):
    """Crash markers: an unclean stop must be reported on the next start."""

    def setUp(self):
        """Point the run state at an empty log directory."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log_dir = Path(tmp.name)
        override = override_settings(LOG_DIR=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        # Keep the heartbeat thread from starting; the tests drive beats directly.
        patcher = mock.patch.object(run_state.threading.Thread, "start")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_start_writes_an_unclean_state_and_stop_marks_it_clean(self):
        """A run is unclean until gunicorn's exit hook says otherwise."""
        run_state.start()
        self.assertFalse(run_state.read_state()["clean"])

        run_state.stop()
        self.assertTrue(run_state.read_state()["clean"])

    def test_unclean_previous_run_is_reported_with_its_last_heartbeat(self):
        """A state never marked clean means the last run was killed."""
        (self.log_dir / run_state.STATE_NAME).write_text(
            json.dumps(
                {
                    "clean": False,
                    "started_at": "2026-10-01T03:00:00+00:00",
                    "last_heartbeat": "2026-10-01T03:42:00+00:00",
                    "memory": 1950 * MIB,
                    "memory_limit": 2048 * MIB,
                    "memory_peak": 2040 * MIB,
                },
            ),
        )

        with self.assertLogs("config.run_state", "WARNING") as logs:
            run_state.start()

        message = logs.output[0]
        self.assertIn("without a clean shutdown", message)
        self.assertIn("2026-10-01T03:42:00+00:00", message)
        self.assertIn("1950MiB of 2048MiB", message)
        self.assertIn("likely an OOM kill", message)
        self.assertEqual(
            run_state.read_state()["last_unclean_at"],
            "2026-10-01T03:42:00+00:00",
        )

    def test_unclean_exit_far_from_the_limit_points_at_how_to_check_for_oom(self):
        """Without memory pressure the log says where to look instead."""
        text = run_state.describe_unclean_exit(
            {"memory": 300 * MIB, "memory_limit": 2048 * MIB},
        )

        self.assertNotIn("likely an OOM kill", text)
        self.assertIn("OOMKilled", text)

    def test_clean_previous_run_logs_no_warning_and_keeps_last_unclean_time(self):
        """A clean stop is info only, and history of past crashes is kept."""
        (self.log_dir / run_state.STATE_NAME).write_text(
            json.dumps(
                {
                    "clean": True,
                    "last_heartbeat": "2026-10-02T00:00:00+00:00",
                    "last_unclean_at": "2026-09-30T12:00:00+00:00",
                },
            ),
        )

        with self.assertNoLogs("config.run_state", "WARNING"):
            run_state.start()

        self.assertEqual(
            run_state.read_state()["last_unclean_at"],
            "2026-09-30T12:00:00+00:00",
        )

    def test_unwritable_log_directory_never_raises(self):
        """Diagnostics must not stop Floppy from starting."""
        with override_settings(LOG_DIR=str(self.log_dir / "missing" / "dir")):
            run_state.start()
            run_state.stop()
            self.assertIsNone(run_state.read_state())


class StopSignalTests(SimpleTestCase):
    """A stop asked for from outside must read as one, not as a crash."""

    def setUp(self):
        """Point the run state at an empty log directory."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log_dir = Path(tmp.name)
        override = override_settings(LOG_DIR=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        patcher = mock.patch.object(run_state.threading.Thread, "start")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_requested_stop_is_named_on_the_next_start(self):
        """SIGTERM then a clean exit logs who stopped it, as info."""
        run_state.start()
        run_state.note_stop_signal("SIGTERM")
        run_state.stop()

        with self.assertLogs("config.run_state", "INFO") as logs:
            run_state.start()

        self.assertIn("stopped by SIGTERM", logs.output[0])
        self.assertIn("not a crash", logs.output[0])
        self.assertNotIn("without a clean shutdown", logs.output[0])

    def test_stop_signal_alone_does_not_mark_the_run_clean(self):
        """Until shutdown finishes, a kill must still look like a kill."""
        run_state.start()
        run_state.note_stop_signal("SIGTERM")

        state = run_state.read_state()
        self.assertFalse(state["clean"])
        self.assertEqual(state["stop_signal"], "SIGTERM")

    def test_stop_cut_short_names_the_request_and_the_grace_period(self):
        """A kill after SIGTERM points at Docker's stop timeout."""
        run_state.start()
        run_state.note_stop_signal("SIGTERM")

        with self.assertLogs("config.run_state", "WARNING") as logs:
            run_state.start()

        self.assertIn("without a clean shutdown", logs.output[0])
        self.assertIn("A stop was requested (SIGTERM", logs.output[0])
        self.assertIn("stop_grace_period", logs.output[0])

    def test_unclean_exit_without_a_signal_still_mentions_the_grace_period(self):
        """If SIGTERM never reached gunicorn, the hint is still given."""
        text = run_state.describe_unclean_exit({"memory": 300 * MIB})

        self.assertIn("stop_grace_period", text)
        self.assertNotIn("A stop was requested", text)

    def test_the_next_run_does_not_inherit_the_old_stop_signal(self):
        run_state.start()
        run_state.note_stop_signal("SIGTERM")
        run_state.stop()
        run_state.start()
        run_state.stop()

        with self.assertLogs("config.run_state", "INFO") as logs:
            run_state.start()

        self.assertIn("shut down cleanly", logs.output[0])

    def test_noting_a_signal_before_start_does_nothing(self):
        run_state._state.clear()
        run_state.note_stop_signal("SIGTERM")

        self.assertIsNone(run_state.read_state())
