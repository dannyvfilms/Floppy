"""Exercise benchmark resource attribution without Docker or a user database."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def load_script(name):
    """Load the standalone opt-in benchmark scripts by file path."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sampler = load_script("container_memory_sample")
aging = load_script("memory_aging_report")


class ResourceExposureTests(SimpleTestCase):
    """Unknown ownership and missing accounting must stay explicit."""

    def test_pressure_has_numeric_totals_and_unavailable_is_null(self):
        """PSI totals retain microseconds and unsupported files are unknown."""
        with patch.object(
            sampler,
            "_read_text",
            return_value="some avg10=0.25 avg60=0.1 avg300=0.0 total=1200\n",
        ):
            self.assertEqual(sampler._pressure(Path("unused"))["some"]["total"], 1200)
        with patch.object(sampler, "_read_text", return_value=None):
            self.assertIsNone(sampler._pressure(Path("unused")))

    def test_global_cpu_excludes_guest_double_counting_and_reports_available_memory(
        self,
    ):
        """Global values remain independent of any declared cgroup ownership."""
        values = {
            "/proc/stat": "cpu 1 2 3 4 5 6 7 8 9 10\n",
            "/proc/meminfo": "MemTotal: 1024 kB\nMemAvailable: 200 kB\n",
        }
        with patch.object(
            sampler, "_read_text", side_effect=lambda path: values.get(str(path))
        ):
            global_resources = sampler._global_resources()
        self.assertEqual(sum(global_resources["cpu_ticks"].values()), 36)
        self.assertEqual(global_resources["memory_available_bytes"], 200 * 1024)
        self.assertIsNone(global_resources["swap_free_bytes"])
        self.assertIsNone(global_resources["pressure"]["cpu"])

    def test_process_cpu_uses_lifetime_ticks_and_rejects_pid_reuse(self):
        """CPU is absolute lifetime usage; crossed lifetimes are not combined."""
        fields = ["S", *[str(index) for index in range(4, 54)]]
        original = "7 (worker (child)) " + " ".join(fields)
        changed = fields.copy()
        changed[19] = "999"
        replacement = "7 (worker (child)) " + " ".join(changed)

        def capture(stat_records):
            records = iter(stat_records)

            def read(path):
                if path.name == "stat":
                    return next(records)
                if path.name == "status":
                    return "PPid: 1\nVmRSS: 10 kB\n"
                return None

            with (
                patch.object(sampler, "_read_text", side_effect=read),
                patch.object(sampler, "_read_bytes", return_value=b"python\0"),
                patch.object(sampler, "_list_dir", return_value=[]),
            ):
                return sampler._measure_process(Path("/proc/7"), 100, 200)

        process = capture([original, original])
        self.assertEqual(process["start_ticks"], 22)
        self.assertEqual(process["cpu_seconds"], (14 + 15) / 100)
        self.assertIsNone(capture([original, replacement]))

    def test_aging_restarts_track_for_reused_pid_and_boot(self):
        """A fresh worker cannot be interpreted as continuous retained growth."""
        samples = [
            {
                "at": index,
                "roles": {"worker": {"pss_kib": 100}},
                "resource_scope": {"boot_id": boot},
                "processes": [{"pid": 7, "start_ticks": start, "role": "worker"}],
            }
            for index, (boot, start) in enumerate((("a", 1), ("a", 2), ("b", 2)))
        ]
        self.assertEqual(len(aging.series(samples)), 3)
        self.assertTrue(
            all(len(track) == 1 for track in aging.series(samples).values())
        )

    def test_resource_delta_separates_owned_activity_and_unknown_external(self):
        """Support-service cgroup work is numeric; external ownership is unknown."""

        def sample(cpu, busy, stall):
            return {
                "resource_scope": {"boot_id": "fixed"},
                "clock_ticks_per_second": 100,
                "cpu_usage_usec": cpu,
                "global": {
                    "cpu_ticks": {"user": busy, "idle": 1000},
                    "pressure": {"cpu": {"some": {"total": stall}}},
                },
                "cgroup_pressure": {"cpu": {"some": {"total": stall}}},
            }

        before, after = sample(100, 10, 0), sample(2000100, 310, 250000)
        result = aging.resource_delta(before, after)
        self.assertEqual(result["cgroup_cpu_seconds"], 2)
        self.assertEqual(result["global_busy_cpu_seconds"], 3)
        self.assertEqual(
            result["pressure_stall_seconds"]["global"]["cpu"]["some"], 0.25
        )
        self.assertIsNone(result["external_cpu_seconds"])
        after["cpu_usage_usec"] = 0
        self.assertIsNone(aging.resource_delta(before, after)["cgroup_cpu_seconds"])
        after["resource_scope"]["boot_id"] = "replacement"
        self.assertIsNone(
            aging.resource_delta(before, after)["global_busy_cpu_seconds"]
        )

    def test_suspend_and_long_gaps_are_visible_without_cpu_subtraction(self):
        """Wall/boottime divergence is exposed and old records remain unknown."""
        samples = [
            {
                "exposure": {
                    "start": {
                        "wall_seconds": wall,
                        "monotonic_seconds": mono,
                        "boottime_seconds": wall,
                        "collector_cpu_seconds": 0.05,
                    },
                    "end": {"collector_cpu_seconds": 0.2},
                }
            }
            for wall, mono in ((10, 10), (130, 30))
        ]
        result = aging.exposure_summary(samples)
        self.assertEqual(result["max_wall_gap_seconds"], 120)
        self.assertEqual(result["max_suspend_exposure_seconds"], 100)
        self.assertEqual(result["sampler_capture_cpu_seconds"], 0.30000000000000004)
        legacy = aging.exposure_summary([{}, {}])
        self.assertEqual(legacy["missing_clock_intervals"], 1)
        self.assertIsNone(legacy["sampler_capture_cpu_seconds"])
