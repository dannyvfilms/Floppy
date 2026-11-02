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


class RestartDescriptionTests(SimpleTestCase):
    """The start line says how the last run ended and what changed since."""

    previous = {
        "clean": True,
        "started_at": "2026-10-13T18:43:13+00:00",
        "last_heartbeat": "2026-10-14T18:40:01+00:00",
        "hostname": "d57ad038526c",
        "version": "v1",
    }
    current = {
        "started_at": "2026-10-14T18:46:10+00:00",
        "hostname": "d57ad038526c",
        "version": "v1",
        "container_started_at": "2026-10-14T18:45:56+00:00",
    }

    def test_clean_restart_of_the_same_container_names_everything(self):
        """A stop from outside shows as: clean, how long up and down, same container."""
        text = run_state.describe_restart(self.previous, self.current)

        self.assertIn("previous run stopped cleanly", text)
        self.assertIn("after 23h56m up", text)
        self.assertIn("down 6m09s before this start", text)
        self.assertIn("same container (d57ad038526c)", text)
        self.assertIn("version unchanged (v1)", text)
        self.assertIn("container process started 2026-10-14T18:45:56+00:00", text)
        self.assertIn("Floppy 14s later", text)

    def test_requested_stop_names_the_signal(self):
        """The restart line says which signal asked for the stop."""
        text = run_state.describe_restart(
            {**self.previous, "stop_signal": "SIGTERM"}, self.current
        )

        self.assertIn("previous run stopped cleanly after SIGTERM", text)

    def test_unclean_restart_new_container_and_new_version(self):
        """A crash, a recreated container and an update each read differently."""
        text = run_state.describe_restart(
            {**self.previous, "clean": False},
            {**self.current, "hostname": "abc123", "version": "v2"},
        )

        self.assertIn("ended WITHOUT a clean stop", text)
        self.assertIn("down at most", text)
        self.assertIn("new container (d57ad038526c -> abc123)", text)
        self.assertIn("version v1 -> v2", text)

    def test_missing_fields_are_left_out_instead_of_raising(self):
        """State written by an older release has no host or container times."""
        text = run_state.describe_restart({"clean": True}, {"started_at": "bad"})

        self.assertEqual(text, "Restart: previous run stopped cleanly.")


class RestartLoggingTests(SimpleTestCase):
    """start() logs the restart line and keeps a bounded history file."""

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

    def test_restart_is_logged_and_appended_to_the_history_file(self):
        """The line reaches floppy.log and survives its rotation."""
        run_state.start()
        run_state.stop()

        with self.assertLogs("config.run_state", "INFO") as logs:
            run_state.start()

        self.assertTrue(any("[run-state] Restart:" in line for line in logs.output))
        history = (self.log_dir / run_state.HISTORY_NAME).read_text().splitlines()
        self.assertEqual(len(history), 1)
        self.assertIn("Restart: previous run stopped cleanly", history[0])

    def test_first_start_has_no_restart_line(self):
        """There is no previous run to describe on a fresh install."""
        run_state.start()

        self.assertFalse((self.log_dir / run_state.HISTORY_NAME).exists())

    def test_history_keeps_only_the_latest_lines(self):
        """The file stays small however long the container lives."""
        with mock.patch.object(run_state, "HISTORY_MAX_LINES", 3):
            for number in range(5):
                run_state._append_history(f"line {number}")

        lines = (self.log_dir / run_state.HISTORY_NAME).read_text().splitlines()
        self.assertEqual(
            [line.split(" ", 1)[1] for line in lines],
            [
                "line 2",
                "line 3",
                "line 4",
            ],
        )

    def test_unwritable_history_never_raises(self):
        """Diagnostics must not stop Floppy from starting."""
        with override_settings(LOG_DIR=str(self.log_dir / "missing")):
            run_state._append_history("line")


class MemoryEvidenceTests(SimpleTestCase):
    """Memory lines carry what the OOM counter cannot on Synology kernels."""

    def read_from(self, files):
        """Return a stand-in for run_state._read serving the given paths."""
        return files.get

    def test_cgroup_v1_split_and_limit_hits(self):
        """Program memory, file cache and limit hits come from the v1 files."""
        files = {
            "/sys/fs/cgroup/memory/memory.stat": (
                "cache 100\nrss 5\ntotal_cache 1500\ntotal_rss 400\n"
            ),
            "/sys/fs/cgroup/memory/memory.failcnt": "27",
        }
        with mock.patch.object(run_state, "_read", self.read_from(files)):
            self.assertEqual(run_state._cgroup_split(), (400, 1500))
            self.assertEqual(run_state._limit_hits(), 27)

    def test_cgroup_v2_split_and_limit_hits(self):
        """The v2 files are read first when present."""
        files = {
            "/sys/fs/cgroup/memory.stat": "anon 300\nfile 900\n",
            "/sys/fs/cgroup/memory.events": "low 0\nhigh 0\nmax 4\noom 0\n",
        }
        with mock.patch.object(run_state, "_read", self.read_from(files)):
            self.assertEqual(run_state._cgroup_split(), (300, 900))
            self.assertEqual(run_state._limit_hits(), 4)

    def test_missing_cgroup_files_are_unknown_not_errors(self):
        """Outside a container every figure is simply unknown."""
        with mock.patch.object(run_state, "_read", self.read_from({})):
            self.assertEqual(run_state._cgroup_split(), (None, None))
            self.assertIsNone(run_state._limit_hits())
            self.assertIsNone(run_state._host_available())

    def test_host_available_memory_is_read_in_bytes(self):
        """MemAvailable is reported in kB by the kernel."""
        files = {"/proc/meminfo": "MemTotal: 8000000 kB\nMemAvailable: 2048 kB\n"}
        with mock.patch.object(run_state, "_read", self.read_from(files)):
            self.assertEqual(run_state._host_available(), 2048 * 1024)

    def test_memory_summary_names_the_new_figures(self):
        """The five-minute line in floppy.log shows the evidence."""
        sample = {
            "memory": 1900 * MIB,
            "memory_peak": 1983 * MIB,
            "memory_limit": 2048 * MIB,
            "oom_kills": None,
            "anon": 600 * MIB,
            "file_cache": 1300 * MIB,
            "limit_hits": 12,
            "host_available": 500 * MIB,
        }

        text = run_state._memory_summary(sample)

        self.assertIn("limit_hits=12", text)
        self.assertIn("anon=600MiB", text)
        self.assertIn("file_cache=1300MiB", text)
        self.assertIn("host_available=500MiB", text)

    def test_container_start_time_comes_from_pid_1(self):
        """PID 1 start ticks plus boot time give when Docker started the container."""
        stat = "1 (supervisord) S " + " ".join(["0"] * 18) + " 5000 0"
        texts = {"/proc/1/stat": stat, "/proc/stat": "cpu 1 2\nbtime 1000000000\n"}
        with (
            mock.patch.object(
                run_state.Path,
                "read_text",
                autospec=True,
                side_effect=lambda self: texts[str(self)],
            ),
            mock.patch.object(run_state.os, "sysconf", return_value=100),
        ):
            started = run_state._container_started_at()

        self.assertEqual(started, "2001-09-09T01:47:30+00:00")


class WorkerShutdownTests(SimpleTestCase):
    """A stopping Celery worker names the tasks it was running."""

    def test_running_tasks_are_listed_with_how_long_they_ran(self):
        """A shutdown mid-task is what Docker's ten second timeout kills."""
        request = mock.Mock(time_start=1000.0)
        request.name = "Refresh Discover Tab Cache"
        with (
            mock.patch("celery.worker.state.active_requests", {request}),
            mock.patch.object(run_state.time, "time", return_value=1260.0),
            self.assertLogs("config.run_state", "INFO") as logs,
        ):
            run_state.log_worker_shutdown("SIGTERM", "Warm")

        self.assertIn("signal=SIGTERM how=Warm", logs.output[0])
        self.assertIn("Refresh Discover Tab Cache (4m20s)", logs.output[0])

    def test_idle_worker_says_none(self):
        """No active task is a fact worth logging too."""
        with (
            mock.patch("celery.worker.state.active_requests", set()),
            self.assertLogs("config.run_state", "INFO") as logs,
        ):
            run_state.log_worker_shutdown("SIGTERM", "Warm")

        self.assertIn("running tasks: none", logs.output[0])
