"""Cover the container memory sampler, which lives outside the Django tree.

``scripts/`` is not a package and is not copied into the runtime image, so the
sampler is loaded by path. Every filesystem read it does goes through the
module's own ``_read_text``/``_list_dir`` helpers, which these tests patch
instead of building a fake ``/proc`` on disk: the suite runs as root in some
containers, where ``chmod 000`` denies nothing and a permissions test would
quietly assert nothing at all.
"""

import importlib.util
import sys
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase

# Two classes below deliberately take a real sample instead of a constructed
# one. That needs the host's own /proc and /sys/fs/cgroup, which exist on Linux
# (CI, and the containers this sampler actually runs in) and nowhere else.
_ON_LINUX = skipUnless(sys.platform == "linux", "needs a real /proc and cgroup")

# Linux alone is not enough: cgroup v2 exposes no controller files on the root
# cgroup, so a runner that is not itself inside a container has neither
# /sys/fs/cgroup/memory.current (v2) nor /sys/fs/cgroup/memory/ (v1). GitHub's
# runners are exactly that, which is why these four tests have been failing on
# CI. The sampler now reports absent accounting as unknown instead of raising;
# these tests assert on a real measured sample, so they need a host that
# actually accounts memory.
_HAS_CGROUP_MEMORY = (
    Path("/sys/fs/cgroup/memory.current").exists()
    or Path("/sys/fs/cgroup/memory/memory.usage_in_bytes").exists()
)
_WITH_CGROUP_MEMORY = skipUnless(
    _HAS_CGROUP_MEMORY,
    "needs a host cgroup that accounts memory",
)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "container_memory_sample.py"
_spec = importlib.util.spec_from_file_location("container_memory_sample", _SCRIPT)
sampler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sampler)

ROLLUP = """55d2c5c00000-7ffd0f7ff000 ---p 00000000 00:00 0 [rollup]
Rss:               20480 kB
Pss:               12288 kB
Shared_Clean:       4096 kB
Shared_Dirty:       2048 kB
Private_Clean:      1024 kB
Private_Dirty:      7168 kB
Pss_Anon:           8192 kB
Pss_File:           4096 kB
Pss_Shmem:             0 kB
"""

# A pre-4.14 kernel reports no Pss_Anon/Pss_File/Pss_Shmem at all.
ROLLUP_LEGACY = """55d2c5c00000-7ffd0f7ff000 ---p 00000000 00:00 0 [rollup]
Rss:               20480 kB
Pss:               12288 kB
Shared_Clean:       4096 kB
Shared_Dirty:       2048 kB
Private_Clean:      1024 kB
Private_Dirty:      7168 kB
"""


def process(pid, name, argv0, **overrides):
    """Return a classified-shape process dict for the roll-up tests."""
    base = {
        "pid": pid,
        "ppid": 1,
        "name": name,
        "argv0": argv0,
        "measurement": "full",
        "fd_count": 10,
        "uptime_seconds": 5.0,
        "is_beat": False,
        "worker_queue": "",
        "pss_kib": 100,
        "rss_kib": 200,
        "private_kib": 80,
        "shared_clean_kib": 10,
        "shared_dirty_kib": 10,
        "pss_anon_kib": 60,
        "pss_file_kib": 40,
        "pss_shmem_kib": 0,
    }
    base.update(overrides)
    return base


class ParseSmapsRollupTests(SimpleTestCase):
    """The rollup parser must degrade rather than invent numbers."""

    def test_full_rollup_is_parsed(self):
        """A modern rollup yields every counter, with Private_* summed."""
        values = sampler._parse_smaps_rollup(ROLLUP)

        self.assertEqual(values["pss_kib"], 12288)
        self.assertEqual(values["rss_kib"], 20480)
        self.assertEqual(values["private_kib"], 1024 + 7168)
        self.assertEqual(values["pss_anon_kib"], 8192)
        self.assertEqual(values["pss_file_kib"], 4096)
        self.assertEqual(values["shared_dirty_kib"], 2048)

    def test_missing_breakdown_is_null_not_zero(self):
        """A pre-4.14 kernel reports null for the PSS split, never zero."""
        values = sampler._parse_smaps_rollup(ROLLUP_LEGACY)

        self.assertEqual(values["pss_kib"], 12288)
        self.assertIsNone(values["pss_anon_kib"])
        self.assertIsNone(values["pss_file_kib"])
        self.assertIsNone(values["pss_shmem_kib"])

    def test_unreadable_rollup_is_rejected(self):
        """No Pss line means the rollup cannot be used at all."""
        self.assertIsNone(sampler._parse_smaps_rollup(None))
        self.assertIsNone(sampler._parse_smaps_rollup(""))
        self.assertIsNone(sampler._parse_smaps_rollup("header\nRss: 10 kB\n"))


class ParseStartTicksTests(SimpleTestCase):
    """Field 22 cannot be reached by splitting on whitespace."""

    def test_comm_containing_spaces_and_parens(self):
        """A comm with its own parentheses must not shift the field index."""
        # state is field 3; these stand in for fields 4 onward.
        fields = " ".join(str(index) for index in range(4, 54))
        stat = f"42 (celery (worker) :1) S {fields}"

        # state is field 3, so field 22 is the 20th value after comm.
        self.assertEqual(sampler._parse_start_ticks(stat), 22)

    def test_unparseable_stat_is_null(self):
        """A truncated or absent stat line yields None, not an exception."""
        self.assertIsNone(sampler._parse_start_ticks(None))
        self.assertIsNone(sampler._parse_start_ticks("42 (python) S 1 2 3"))


class MeasureProcessTests(SimpleTestCase):
    """The EACCES path is the reason the sampler is useful outside the bench."""

    DEFAULT_STATUS = "Name:\tpython\nPPid:\t7\nVmRSS:\t20480 kB\n"

    def _measure(self, rollup, status=DEFAULT_STATUS, fd_entries=("0", "1", "2")):
        reads = {
            "status": status,
            "smaps_rollup": rollup,
            "comm": "python\n",
            "stat": "99 (python) S " + " ".join(str(index) for index in range(3, 53)),
        }

        def fake_read_text(path):
            if path.name == "uptime":
                return "5000.0 4000.0\n"
            return reads.get(path.name)

        with (
            patch.object(sampler, "_read_text", side_effect=fake_read_text),
            patch.object(sampler, "_read_bytes", return_value=b"python\0"),
            patch.object(sampler, "_list_dir", return_value=list(fd_entries)),
        ):
            return sampler._measure_process(Path("/proc/99"), 100, 5000.0)

    def test_readable_rollup_is_fully_measured(self):
        """With the rollup readable every counter is populated."""
        measured = self._measure(ROLLUP)

        self.assertEqual(measured["measurement"], "full")
        self.assertEqual(measured["pss_kib"], 12288)
        self.assertEqual(measured["pss_anon_kib"], 8192)
        self.assertEqual(measured["fd_count"], 3)

    def test_denied_rollup_falls_back_to_vmrss(self):
        """Without CAP_SYS_PTRACE the process is still counted, via VmRSS.

        This is the whole point of reading /proc/<pid>/status rather than
        globbing smaps_rollup: a production container has no SYS_PTRACE, and
        the processes would otherwise vanish into unreadable_processes.
        """
        measured = self._measure(None)

        self.assertEqual(measured["measurement"], "rss-only")
        self.assertEqual(measured["rss_kib"], 20480)
        self.assertIsNone(measured["pss_kib"])
        self.assertIsNone(measured["pss_anon_kib"])
        self.assertIsNone(measured["private_kib"])

    def test_kernel_thread_is_not_a_process(self):
        """No VmRSS means a kernel thread, which holds no user-space memory."""
        measured = self._measure(ROLLUP, status="Name:\tkthreadd\nPPid:\t2\n")

        self.assertEqual(measured, "kernel-thread")

    def test_exited_process_is_unreadable(self):
        """A process that exits mid-scan yields None rather than raising."""
        self.assertIsNone(self._measure(ROLLUP, status=None))

    def test_denied_fd_directory_is_null(self):
        """An unreadable /proc/<pid>/fd reports null, never a count of zero."""
        with patch.object(sampler, "_list_dir", return_value=None):
            self.assertIsNone(sampler._fd_count(Path("/proc/99")))

    def test_uptime_is_derived_from_start_ticks(self):
        """Uptime is boot uptime minus the process start time in ticks."""
        measured = self._measure(ROLLUP)

        # start_ticks 22 at 100 ticks/s against 5000s of uptime.
        self.assertEqual(measured["uptime_seconds"], 4999.8)


class ProcessRoleTests(SimpleTestCase):
    """Role classification drives every roll-up, and had no coverage."""

    def _classify(self, processes):
        by_pid = {item["pid"]: item for item in processes}
        child_pids = {item["ppid"] for item in processes}
        return {
            item["pid"]: sampler._process_role(item, child_pids, by_pid)
            for item in processes
        }

    def test_gunicorn_and_nginx_masters_are_the_parents(self):
        """A process that is someone's parent is the master, whatever its pid."""
        roles = self._classify(
            [
                process(10, "gunicorn", "gunicorn", ppid=1),
                process(11, "gunicorn", "gunicorn", ppid=10),
                process(20, "nginx", "nginx", ppid=1),
                process(21, "nginx", "nginx", ppid=20),
            ],
        )

        self.assertEqual(roles[10], "gunicorn-master")
        self.assertEqual(roles[11], "gunicorn-worker")
        self.assertEqual(roles[20], "nginx-master")
        self.assertEqual(roles[21], "nginx-worker")

    def test_celery_roles_split_by_queue_and_beat_flag(self):
        """Beat is embedded in the background worker, so the flag decides."""
        roles = self._classify(
            [
                process(30, "celery", "celery", ppid=1, is_beat=True),
                process(31, "celery", "celery", ppid=30),
                process(40, "celery", "celery", ppid=1, worker_queue="interactive"),
                process(41, "celery", "celery", ppid=40),
            ],
        )

        self.assertEqual(roles[30], "celery-worker-beat")
        self.assertEqual(roles[31], "celery-worker-beat-child")
        self.assertEqual(roles[40], "celery-interactive-parent")
        self.assertEqual(roles[41], "celery-interactive-child")

    def test_supervisord_and_unknown_processes(self):
        """Anything unrecognised is reported rather than dropped."""
        roles = self._classify(
            [
                process(50, "supervisord", "supervisord", ppid=0),
                process(51, "redis-server", "redis-server", ppid=0),
            ],
        )

        self.assertEqual(roles[50], "supervisord")
        self.assertEqual(roles[51], "other")


class RollUpTests(SimpleTestCase):
    """A role containing an unmeasurable process has an unknowable total."""

    def test_measured_role_sums_every_counter(self):
        """Fully measured processes sum normally and count as measured."""
        roles = sampler._roll_up(
            [
                process(1, "gunicorn", "gunicorn", role="gunicorn-worker"),
                process(
                    2,
                    "gunicorn",
                    "gunicorn",
                    role="gunicorn-worker",
                    uptime_seconds=99.0,
                ),
            ],
        )
        worker = roles["gunicorn-worker"]

        self.assertEqual(worker["process_count"], 2)
        self.assertEqual(worker["measured_count"], 2)
        self.assertEqual(worker["rss_only_count"], 0)
        self.assertEqual(worker["pss_kib"], 200)
        self.assertEqual(worker["pss_anon_kib"], 120)
        self.assertEqual(worker["fd_count"], 20)
        self.assertEqual(worker["max_uptime_seconds"], 99.0)

    def test_mixed_role_reports_null_totals_but_keeps_rss(self):
        """One rss-only process makes PSS unknowable without hiding the role.

        RSS still sums, because it is the one counter both paths provide; the
        measured/rss-only counts are what keep that difference legible.
        """
        roles = sampler._roll_up(
            [
                process(1, "celery", "celery", role="celery-worker-parent"),
                process(
                    2,
                    "celery",
                    "celery",
                    role="celery-worker-parent",
                    measurement="rss-only",
                    pss_kib=None,
                    private_kib=None,
                    shared_clean_kib=None,
                    shared_dirty_kib=None,
                    pss_anon_kib=None,
                    pss_file_kib=None,
                    pss_shmem_kib=None,
                    fd_count=None,
                ),
            ],
        )
        parent = roles["celery-worker-parent"]

        self.assertEqual(parent["process_count"], 2)
        self.assertEqual(parent["measured_count"], 1)
        self.assertEqual(parent["rss_only_count"], 1)
        self.assertIsNone(parent["pss_kib"])
        self.assertIsNone(parent["pss_anon_kib"])
        self.assertEqual(parent["rss_kib"], 400)
        self.assertEqual(parent["fd_count"], 10)

    def test_role_names_its_largest_process(self):
        """A worker run with --beat parents two children of unlike size.

        Nothing outside those processes tells the prefork pool child from the
        embedded scheduler, so they share a role. The role must still name its
        largest member, or a pool child that has grown disappears into an
        average with a scheduler that has not.
        """
        roles = sampler._roll_up(
            [
                process(1, "celery", "celery", role="celery-worker-beat-child"),
                process(
                    2,
                    "celery",
                    "celery",
                    role="celery-worker-beat-child",
                    pss_kib=9000,
                ),
            ],
        )
        child = roles["celery-worker-beat-child"]

        self.assertEqual(child["pss_kib"], 9100)
        self.assertEqual(child["max_pss_kib"], 9000)
        self.assertEqual(child["max_pss_pid"], 2)

    def test_unmeasurable_role_names_no_largest_process(self):
        """With no PSS anywhere in the role there is no largest to name."""
        roles = sampler._roll_up(
            [
                process(
                    1,
                    "celery",
                    "celery",
                    role="celery-worker-child",
                    measurement="rss-only",
                    pss_kib=None,
                ),
            ],
        )
        child = roles["celery-worker-child"]

        self.assertIsNone(child["max_pss_kib"])
        self.assertIsNone(child["max_pss_pid"])


@_ON_LINUX
@_WITH_CGROUP_MEMORY
class PrivacyInvariantTests(SimpleTestCase):
    """Command lines carry deployment secrets and must never be emitted.

    ``is_beat`` and ``worker_queue`` are derived from cmdline to classify a
    process and are deleted before the sample is returned. A real sample is
    taken here rather than a constructed one, so a future edit that forgets to
    delete them fails this test.
    """

    EXPECTED_KEYS = {
        "pid",
        "ppid",
        "name",
        "argv0",
        "role",
        "measurement",
        "fd_count",
        "uptime_seconds",
        "start_ticks",
        "cpu_seconds",
        "pss_kib",
        "rss_kib",
        "private_kib",
        "shared_clean_kib",
        "shared_dirty_kib",
        "pss_anon_kib",
        "pss_file_kib",
        "pss_shmem_kib",
    }

    def test_no_command_arguments_reach_the_sample(self):
        """Every emitted process carries argv0 only, and no derived flags."""
        # Include this process as an application even when it is alone as PID 1.
        with patch.object(sampler.os, "getpid", return_value=-1):
            sampled = sampler.sample()

        self.assertTrue(sampled["processes"], "expected at least one process")
        for item in sampled["processes"]:
            self.assertEqual(set(item), self.EXPECTED_KEYS)
            self.assertNotIn("cmdline", item)
            self.assertNotIn("argv", item)

    def test_sampler_process_is_separated_and_scrubbed(self):
        """The sampler's own process is reported apart, without the flags."""
        sampled = sampler.sample()

        self.assertIsNotNone(sampled["sampler"])
        self.assertNotIn("is_beat", sampled["sampler"])
        self.assertNotIn("worker_queue", sampled["sampler"])
        self.assertNotIn(
            sampled["sampler"]["pid"],
            [item["pid"] for item in sampled["processes"]],
        )


@_ON_LINUX
@_WITH_CGROUP_MEMORY
class ReconciliationTests(SimpleTestCase):
    """The honesty flag is what stops a bound being read as a reconciliation."""

    def test_complete_sample_reports_totals_as_reconciled(self):
        """With every process measured, the PSS total is a real total."""
        with patch.object(sampler.os, "getpid", return_value=-1):
            sampled = sampler.sample()
        reconciliation = sampled["reconciliation"]

        # In a Floppy container every process in the cgroup is one Floppy
        # started, so every smaps_rollup is readable and the precondition
        # below always holds. A development sandbox can put a foreign
        # supervisor in the same cgroup whose rollup the sampler is not
        # allowed to read -- a fact about that host, not a defect here. Skip
        # on that, but only for a process the sampler could not classify:
        # an unreadable gunicorn or celery process is still a real failure,
        # which is the regression this test exists to catch.
        unmeasured = [item for item in sampled["processes"] if item["pss_kib"] is None]
        if unmeasured and all(item["role"] == "other" for item in unmeasured):
            names = ", ".join(sorted({item["name"] for item in unmeasured}))
            self.skipTest(f"host has unreadable foreign processes: {names}")

        self.assertEqual(sampled["rss_only_processes"], 0)
        self.assertTrue(reconciliation["process_pss_complete"])
        self.assertEqual(sampled["smaps_detail"], "full")
        self.assertGreater(reconciliation["process_pss_bytes"], 0)

    def test_denied_rollups_mark_the_total_incomplete(self):
        """When no rollup can be read, PSS is absent and the flag says so."""
        real_read_text = sampler._read_text

        def deny_rollup(path):
            return None if path.name == "smaps_rollup" else real_read_text(path)

        with (
            patch.object(sampler, "_read_text", side_effect=deny_rollup),
            patch.object(sampler.os, "getpid", return_value=-1),
        ):
            sampled = sampler.sample()

        self.assertEqual(sampled["measured_processes"], 0)
        self.assertGreater(sampled["rss_only_processes"], 0)
        self.assertEqual(sampled["smaps_detail"], "none")
        self.assertFalse(sampled["reconciliation"]["process_pss_complete"])
        self.assertGreater(
            sampled["reconciliation"]["unmeasured_process_rss_bytes"],
            0,
        )


class AbsentCgroupAccountingTests(SimpleTestCase):
    """A host with no cgroup memory accounting is a fact, not a crash.

    cgroup v2 exposes no controller files on the root cgroup, so a process
    outside a container on a v2 host sees neither layout. `_read_cgroup` used
    to read the v1 path unconditionally in that case and raise
    FileNotFoundError, taking the whole sample down.
    """

    def test_neither_layout_reports_unknown_rather_than_raising(self):
        # Point the reader at a tree containing neither layout, which is what
        # a v2 host outside a container looks like.
        with patch.object(sampler, "Path", lambda _: Path("/nonexistent-cgroup-root")):
            cgroup = sampler._read_cgroup()

        self.assertIsNone(cgroup["current_bytes"])
        self.assertIsNone(cgroup["peak_bytes"])
        self.assertIsNone(cgroup["oom"])
        self.assertIsNone(cgroup["oom_kill"])
        self.assertEqual(cgroup["memory_stat"], {})

    def test_an_unknown_bound_leaves_the_difference_unknown(self):
        """No bound means nothing to subtract from - not a total of zero."""
        unknown = {
            "current_bytes": None,
            "current_observed_bytes": None,
            "peak_bytes": None,
            "oom": None,
            "oom_kill": None,
            "events": None,
            "memory_stat": {},
        }
        with patch.object(sampler, "_read_cgroup", return_value=unknown):
            sampled = sampler.sample()

        reconciliation = sampled["reconciliation"]
        self.assertIsNone(reconciliation["cgroup_minus_process_pss_bytes"])
        self.assertIsNone(reconciliation["cgroup_minus_process_private_bytes"])
