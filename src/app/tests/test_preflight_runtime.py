"""Cover the preflight runtime check.

This check is how an operator answers two questions without any access to the
container's internals: which build is running, and how many resident processes
it decided to start. It must never fail a boot -- everything it reports is
informational, so an override or a stale identity is a warning.
"""

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from app import preflight
from app.preflight import FAIL, OK, WARN, build_report, check_runtime
from config import runtime_profile


class RuntimeCheckTests(SimpleTestCase):
    """The check reports topology and identity, and warns without failing."""

    def setUp(self):
        """Point the file-backed inputs somewhere that does not exist."""
        missing = Path("/nonexistent/floppy-preflight-test")
        patcher = patch.object(preflight, "_BUILD_INFO_PATH", missing)
        patcher.start()
        self.addCleanup(patcher.stop)
        boot = patch.object(preflight, "_BOOT_SIZING_PATH", missing)
        boot.start()
        self.addCleanup(boot.stop)

    def test_reports_topology_without_an_override(self):
        """With nothing overridden the check passes and names the processes."""
        with patch.dict("os.environ", {}, clear=False) as _:
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertFalse(result.failed)
        self.assertEqual(result.facts["web_concurrency_source"], "auto")
        self.assertIn("gunicorn", result.facts["expected_programs"])

    def test_expected_programs_follow_the_queue_plan(self):
        """The process list is derived, so it cannot name a worker that is off.

        celery-discover is never started on any tier; a hand-written list would
        claim it is resident and send someone hunting for a process.
        """
        result = check_runtime()

        self.assertEqual(
            "celery-discover" in result.facts["expected_programs"],
            result.facts["start_discover_worker"],
        )

    def test_explicit_worker_count_warns_but_does_not_fail(self):
        """An override is reported against what the host would have chosen."""
        with patch.dict("os.environ", {"WEB_CONCURRENCY": "2"}, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertFalse(result.failed)
        self.assertEqual(result.facts["web_concurrency"], 2)
        self.assertEqual(result.facts["web_concurrency_default"], 1)
        self.assertEqual(result.facts["web_concurrency_source"], "override")
        self.assertIn("WEB_CONCURRENCY", result.fix)
        self.assertTrue(build_report([result])["ok"])

    def test_a_recorded_source_beats_an_inherited_value(self):
        """Supervisord's children inherit the value emit_env itself wrote.

        Without the recorded source every supervised process would read its own
        inherited WEB_CONCURRENCY as an operator override.
        """
        environment = {
            "WEB_CONCURRENCY": "1",
            "FLOPPY_WEB_CONCURRENCY_SOURCE": "auto",
        }
        with patch.dict("os.environ", environment, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["web_concurrency_source"], "auto")

    def test_unparseable_worker_count_warns(self):
        """A non-numeric value is silently ignored, so it has to be surfaced."""
        with patch.dict("os.environ", {"WEB_CONCURRENCY": "two"}, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertEqual(result.facts["web_concurrency_source"], "invalid")
        self.assertEqual(result.facts["web_concurrency"], 1)


class BuildIdentityTests(SimpleTestCase):
    """Identity has to say where it came from, not just what it is."""

    def _write_build_info(self, commit):
        """Point the check at a build-info file carrying this commit."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-build-info"
        path.write_text(f"VERSION=test\nCOMMIT_SHA={commit}\n")
        patcher = patch.object(preflight, "_BUILD_INFO_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def setUp(self):
        """Keep the boot-sizing file out of these cases."""
        patcher = patch.object(
            preflight,
            "_BOOT_SIZING_PATH",
            Path("/nonexistent/floppy-boot-sizing.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_git_checkout_is_reported_as_such(self):
        """Running from source is a different provenance from a built image."""
        self._write_build_info("deadbeef")
        with patch.object(preflight.settings, "LOCAL_COMMIT_SHA", "abc1234"):
            result = check_runtime()

        self.assertEqual(result.facts["identity_source"], "git-checkout")

    def test_image_identity_is_reported_when_there_is_no_checkout(self):
        """A built image has no .git, so the baked file is the only source."""
        self._write_build_info("abc1234")
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "COMMIT_SHA", "abc1234"),
        ):
            result = check_runtime()

        self.assertEqual(result.facts["identity_source"], "image")
        self.assertTrue(result.facts["build_info_matches_settings"])
        self.assertEqual(result.status, OK)

    def test_shadowed_identity_warns(self):
        """A stale COMMIT_SHA in the environment must not pass unnoticed.

        This is the failure a real deployment hit: an orchestrator's persisted
        environment shadowing the identity baked into the image.
        """
        self._write_build_info("abc1234")
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "COMMIT_SHA", "stale999"),
        ):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertFalse(result.failed)
        self.assertFalse(result.facts["build_info_matches_settings"])


class BootSizingTests(SimpleTestCase):
    """A docker exec re-probes the host; the boot record is the real answer."""

    def _write_boot_sizing(self, payload):
        """Point the check at a recorded boot sizing."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-boot-sizing.json"
        path.write_text(json.dumps(payload))
        patcher = patch.object(preflight, "_BOOT_SIZING_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        """Keep build info out of these cases."""
        # sizing_report uses an import-time profile, not later env changes.
        profile = replace(runtime_profile.PROFILE, tier="standard", overridden=True)
        profile_patch = patch.object(runtime_profile, "PROFILE", profile)
        profile_patch.start()
        self.addCleanup(profile_patch.stop)
        patcher = patch.object(
            preflight,
            "_BUILD_INFO_PATH",
            Path("/nonexistent/floppy-build-info"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_boot_sizing_is_reported(self):
        """The recorded decision rides along in the facts when it agrees."""
        self._write_boot_sizing({"tier": "standard", "web_concurrency": 1})
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["boot_sizing"]["tier"], "standard")

    def test_drifted_tier_warns(self):
        """Booting at one tier and detecting another is worth saying out loud."""
        self._write_boot_sizing({"tier": "minimal", "web_concurrency": 1})
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertNotEqual(result.status, FAIL)
        self.assertIn("minimal", result.cause)


class ShadowedIdentityTests(SimpleTestCase):
    """A stale VERSION in the environment must not be reported as the image.

    `docker exec` gives the new process the container's environment, not the
    corrected exports entrypoint.sh made in PID 1. The documented way to run
    this check is exactly that, so the baked values are the authoritative ones.
    """

    def setUp(self):
        """Point the check at a build-info file with a known identity."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-build-info"
        path.write_text("VERSION=v1.2.3\nCOMMIT_SHA=abc1234def\n")
        for attribute, value in (
            ("_BUILD_INFO_PATH", path),
            ("_BOOT_SIZING_PATH", Path("/nonexistent/floppy-boot-sizing.json")),
        ):
            patcher = patch.object(preflight, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_baked_identity_wins_over_a_shadowing_environment(self):
        """The report names the build in the image, not the stale override."""
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "VERSION", "stale-override"),
            patch.object(preflight.settings, "COMMIT_SHA", "999stale"),
            patch.object(preflight.settings, "COMMIT_SHA_SHORT", "999stal"),
        ):
            result = check_runtime()

        self.assertEqual(result.facts["identity_source"], "image")
        self.assertEqual(result.facts["version"], "v1.2.3")
        self.assertEqual(result.facts["commit"], "abc1234")
        self.assertIn("v1.2.3", result.summary)
        self.assertNotIn("stale-override", result.summary)

    def test_the_shadowed_values_stay_visible(self):
        """Both sides of the mismatch are reported, so it can be diagnosed."""
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "VERSION", "stale-override"),
            patch.object(preflight.settings, "COMMIT_SHA", "999stale"),
            patch.object(preflight.settings, "COMMIT_SHA_SHORT", "999stal"),
        ):
            result = check_runtime()

        self.assertEqual(result.facts["settings_version"], "stale-override")
        self.assertEqual(result.facts["settings_commit"], "999stal")
        self.assertFalse(result.facts["build_info_matches_settings"])
        self.assertEqual(result.status, WARN)

    def test_a_matching_build_reports_no_warning(self):
        """Identical baked and resolved identity is the ordinary case."""
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "VERSION", "v1.2.3"),
            patch.object(preflight.settings, "COMMIT_SHA", "abc1234def"),
            patch.object(preflight.settings, "COMMIT_SHA_SHORT", "abc1234"),
            patch.dict("os.environ", {}, clear=False),
        ):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertTrue(result.facts["build_info_matches_settings"])


class AggregatedWarningTests(SimpleTestCase):
    """Co-occurring problems must all be reported, not just the first.

    An older deployment template that pins WEB_CONCURRENCY is the same kind
    that carries a stale COMMIT_SHA, so this combination is the realistic one.
    """

    def setUp(self):
        """Give the check a build identity that disagrees with settings."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-build-info"
        path.write_text("VERSION=v2.0.0\nCOMMIT_SHA=realsha0\n")
        for attribute, value in (
            ("_BUILD_INFO_PATH", path),
            ("_BOOT_SIZING_PATH", Path("/nonexistent/floppy-boot-sizing.json")),
        ):
            patcher = patch.object(preflight, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_both_the_override_and_the_mismatch_are_reported(self):
        """Neither warning may mask the other."""
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "COMMIT_SHA", "stalesha"),
            patch.dict("os.environ", {"WEB_CONCURRENCY": "2"}, clear=False),
        ):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertIn("WEB_CONCURRENCY", result.cause)
        self.assertIn("shadowing", result.cause)
        self.assertIn("WEB_CONCURRENCY", result.fix)
        self.assertIn("COMMIT_SHA", result.fix)
        self.assertTrue(build_report([result])["ok"])


class RunningTopologyTests(SimpleTestCase):
    """Report the topology this container booted with, not a fresh probe.

    sizing_report() answers "what would a process starting now choose", which
    diverges from the running container once host memory, CPU quota or swap
    moves. The summary is what an operator reads, so it must not name a
    process that was never started.
    """

    def setUp(self):
        """Keep build info out of these cases."""
        # sizing_report uses an import-time profile, not later env changes.
        profile = replace(runtime_profile.PROFILE, tier="standard", overridden=True)
        profile_patch = patch.object(runtime_profile, "PROFILE", profile)
        profile_patch.start()
        self.addCleanup(profile_patch.stop)
        patcher = patch.object(
            preflight,
            "_BUILD_INFO_PATH",
            Path("/nonexistent/floppy-build-info"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_boot_sizing(self, payload):
        """Point the check at a recorded boot sizing."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-boot-sizing.json"
        path.write_text(json.dumps(payload))
        patcher = patch.object(preflight, "_BOOT_SIZING_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_summary_names_the_processes_that_were_started(self):
        """A worker absent at boot must not be listed as resident now."""
        self._write_boot_sizing({
            "tier": "minimal",
            "profile": "tier=minimal mem=1.0GiB",
            "web_concurrency": 1,
            "gunicorn_threads": 2,
            "expected_programs": ["nginx", "gunicorn", "celery"],
        })
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertIn("tier=minimal", result.summary)
        self.assertNotIn("celery-interactive", result.summary)
        self.assertEqual(
            result.facts["expected_programs"],
            ["nginx", "gunicorn", "celery"],
        )
        self.assertEqual(result.facts["gunicorn_threads"], 2)

    def test_the_fresh_probe_is_kept_for_comparison(self):
        """Drift is only diagnosable if both readings are reported."""
        self._write_boot_sizing({
            "tier": "minimal",
            "profile": "tier=minimal mem=1.0GiB",
            "expected_programs": ["nginx", "gunicorn", "celery"],
        })
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.facts["detected_sizing"]["tier"], "standard")
        self.assertIn(
            "celery-interactive",
            result.facts["detected_sizing"]["expected_programs"],
        )
        self.assertEqual(result.status, WARN)
        self.assertIn("booted at tier minimal", result.cause)

    def test_a_boot_record_missing_newer_keys_falls_back(self):
        """A record written by an older build must not break the check."""
        self._write_boot_sizing({"tier": "standard"})
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertIn("gunicorn", result.facts["expected_programs"])
        self.assertIsNotNone(result.facts["web_concurrency"])

    def test_without_a_boot_record_the_fresh_probe_is_used(self):
        """An install that never wrote one still reports a full topology."""
        patcher = patch.object(
            preflight,
            "_BOOT_SIZING_PATH",
            Path("/nonexistent/floppy-boot-sizing.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        result = check_runtime()

        self.assertNotIn("boot_sizing", result.facts)
        self.assertEqual(
            result.facts["expected_programs"],
            result.facts["detected_sizing"]["expected_programs"],
        )
