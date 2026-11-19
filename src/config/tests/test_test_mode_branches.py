"""Every production branch on test mode is listed, with the test that covers it.

``config.test_settings`` sets ``TESTING`` and eager Celery, and production code
that checks either one runs a different path in the suite than on a server. A
fault in the skipped path ships under a green suite: #1827 was a task module
the worker never imported, invisible because eager tests call the function
directly. So each such line is listed here with either the test that turns the
flag off and checks the production path, or the reason it is a test double.
"""

import importlib
import re
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SRC = Path(settings.BASE_DIR)
SKIPPED_PARTS = {"tests", "migrations", "node_modules", "static", "__pycache__"}
TEST_MODE = re.compile(
    r"\bTESTING\b|\bCELERY_TASK_ALWAYS_EAGER\b|\bIS_PROD\b"
    r"|sys\.argv.*[\"']test[\"']|[\"']test[\"'].*sys\.argv",
)

# A dotted test name, or "double: <why the test path is a stand-in>".
DOUBLE = "double: "
STARTUP = (
    "double: start-up warmups and schedules; out of scope beyond listing. "
    "Production branch: app.tests.test_app_startup.AppStartupTests"
)

# (file, stripped line) -> (occurrences, covering test or reason)
EXPECTED = {
    ("app/apps.py", "if not settings.TESTING:"): (1, STARTUP),
    ("app/apps.py", "not settings.TESTING"): (3, STARTUP),
    (
        "app/apps.py",
        "if not settings.TESTING and not is_celery_worker and not is_runserver_parent:",
    ): (1, STARTUP),
    ("app/discover/service.py", 'if getattr(settings, "TESTING", False):'): (
        1,
        "app.tests.discover.test_refresh_coalescing.RowRefreshCoalescingTests"
        ".test_a_row_waiting_in_the_queue_is_not_queued_again",
    ),
    ("app/discover/tab_cache.py", 'if getattr(settings, "TESTING", False):'): (
        1,
        "app.tests.test_production_branches.DiscoverTabRefreshProductionTests"
        ".test_schedule_tab_refresh_queues_the_rebuild",
    ),
    ("app/models/item.py", "if settings.TESTING:"): (
        1,
        "app.tests.test_production_branches.FetchReleasesProductionTests"
        ".test_delayed_fetch_queues_reload_calendar_for_the_item",
    ),
    ("app/providers/services.py", "if settings.TESTING:"): (
        1,
        "double: fakeredis for the provider rate limiter. Production branch: "
        "app.tests.test_redis_settings.ProviderLimiterRedisSettingsTests",
    ),
    (
        "app/season_details_views.py",
        "if created_any_episode and not settings.TESTING:",
    ): (
        1,
        "app.tests.test_production_branches.SeasonEpisodeRuntimeBackfillProductionTests"
        ".test_first_view_queues_one_backfill_for_the_season",
    ),
    ("app/signals.py", 'if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):'): (
        1,
        "lists.tests.test_smart_list_sync_deferral.MediaSaveDefersSmartListSyncTests"
        ".test_save_queues_task_and_membership_follows",
    ),
    ("app/signals.py", "if settings.TESTING:"): (
        1,
        "app.tests.test_signals.ItemSignalTests"
        ".test_item_save_requeues_tmdb_tv_genre_backfill_on_identity_change",
    ),
    # Prompt 35 narrowed the Statistics eager path and tested it.
    (
        "app/statistics_cache.py",
        'getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)',
    ): (
        1,
        "app.tests.test_statistics_cache.RequestPathDayBuildTests"
        ".test_minutes_by_type_schedules_background_build",
    ),
    ("app/statistics_cache.py", 'or getattr(settings, "TESTING", False),'): (
        1,
        "app.tests.test_statistics_cache.StatisticsRefreshSchedulingTests"
        ".test_background_sync_runs_on_the_bulk_lane_but_keeps_its_priority",
    ),
    (
        "app/statistics_sync.py",
        'getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)',
    ): (
        1,
        "app.tests.test_statistics_sync.MarkingTests"
        ".test_inline_refresh_defers_to_active_sync",
    ),
    ("app/statistics_sync.py", 'or getattr(settings, "TESTING", False),'): (
        1,
        "app.tests.test_statistics_sync.MarkingTests"
        ".test_inline_refresh_defers_to_active_sync",
    ),
    (
        "app/task_cooperation.py",
        'if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):',
    ): (
        1,
        "app.tests.test_task_cooperation.HigherPriorityTaskWaitingTests"
        ".test_reports_a_queued_task",
    ),
    ("config/settings.py", "TESTING = False"): (
        1,
        "double: the flag's production default; config.test_settings sets it",
    ),
    (
        "config/settings.py",
        'IS_PROD = not any(cmd in sys.argv for cmd in ("runserver", "test"))',
    ): (1, "double: local runs serve static files and skip the proxy IP header"),
    ("config/settings.py", "if IS_PROD:"): (
        1,
        "double: the proxy client IP header is only trusted behind nginx",
    ),
    ("config/urls.py", "if not settings.IS_PROD:"): (
        1,
        "double: local runs serve static files without nginx",
    ),
    ("events/apps.py", "if settings.TESTING:"): (
        1,
        "double: reload_calendar.delay is a mock in tests. Production branch: "
        "app.tests.test_production_branches.FetchReleasesProductionTests",
    ),
    (
        "integrations/anime_mapping.py",
        "if settings.TESTING and TEST_FIXTURE_PATH.exists():",
    ): (
        1,
        "double: a fixture file instead of the pinned download. Production "
        "branch: integrations.tests.test_anime_mapping.AnimeMappingSnapshotTests"
        ".test_digest_mismatch_is_rejected",
    ),
    ("integrations/anime_mapping.py", "if settings.TESTING:"): (
        1,
        "integrations.tests.test_anime_mapping.AnimeMappingSnapshotTests"
        ".test_digest_mismatch_is_rejected",
    ),
    (
        "integrations/imports/audiobookshelf.py",
        "self.enable_provider_enrichment = not settings.TESTING",
    ): (
        1,
        "integrations.tests.imports.test_provider_enrichment_production"
        ".ProviderEnrichmentSwitchTests.test_production_importers_enrich",
    ),
    (
        "integrations/imports/helpers.py",
        "if settings.TESTING or app_signals.media_change_side_effects_suppressed():",
    ): (
        1,
        "integrations.tests.test_import_provenance.ImportRunProvenanceTests"
        ".test_import_boundary_defers_production_enrichment_and_cleans_up_on_failure",
    ),
    (
        "integrations/imports/koreader.py",
        "self.enable_provider_enrichment = not settings.TESTING",
    ): (
        1,
        "integrations.tests.imports.test_provider_enrichment_production"
        ".ProviderEnrichmentSwitchTests.test_production_importers_enrich",
    ),
    (
        "integrations/imports/reading_server.py",
        "self.enable_provider_enrichment = not settings.TESTING",
    ): (
        1,
        "integrations.tests.imports.test_provider_enrichment_production"
        ".ProviderEnrichmentSwitchTests.test_production_importers_enrich",
    ),
    (
        "integrations/imports/storyteller.py",
        "self.enable_provider_enrichment = not settings.TESTING",
    ): (
        1,
        "integrations.tests.imports.test_provider_enrichment_production"
        ".ProviderEnrichmentSwitchTests.test_production_importers_enrich",
    ),
    ("manage.py", 'if "test" in sys.argv:'): (
        1,
        "double: selects config.test_settings for manage.py test",
    ),
    ("users/signals.py", 'if getattr(settings, "TESTING", False):'): (
        1,
        "users.tests.test_demo.DemoDefaultTests"
        ".test_signal_provisions_when_explicitly_enabled",
    ),
}

MESSAGE = (
    "Production code that behaves differently under test needs a test of the "
    "production branch. Add it and list it here."
)


def _production_files():
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC)
        if SKIPPED_PARTS.intersection(relative.parts):
            continue
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        yield relative, path


def scan_test_mode_branches():
    """Return how often each production line that checks test mode appears."""
    found = Counter()
    for relative, path in _production_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not TEST_MODE.search(stripped):
                continue
            found[(relative.as_posix(), stripped)] += 1
    return found


def _resolve(dotted):
    """Import the longest module prefix of a dotted test name, then getattr."""
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[split:]:
            target = getattr(target, attribute)
        return target
    message = f"no module in {dotted}"
    raise ModuleNotFoundError(message)


class TestModeBranchRatchetTests(SimpleTestCase):
    def test_every_test_mode_branch_is_listed(self):
        found = scan_test_mode_branches()
        expected = Counter({key: count for key, (count, _) in EXPECTED.items()})

        new = sorted((found - expected).elements())
        gone = sorted((expected - found).elements())

        self.assertEqual(
            new,
            [],
            f"{MESSAGE} Unlisted (file, line): {new}",
        )
        self.assertEqual(
            gone,
            [],
            f"These listed branches are gone; remove them from EXPECTED: {gone}",
        )

    def test_every_listed_test_exists(self):
        for key, (_, covered_by) in EXPECTED.items():
            with self.subTest(site=key):
                self.assertTrue(covered_by, "name the covering test or the reason")
                if covered_by.startswith(DOUBLE):
                    named = re.findall(
                        r"\b(?:app|config|integrations|lists|users)\.tests\.\S+",
                        covered_by,
                    )
                else:
                    named = [covered_by]
                for dotted in named:
                    _resolve(dotted.rstrip("."))

    def test_the_scan_finds_a_new_branch(self):
        """A throwaway ``if settings.TESTING: return`` is caught by the pattern."""
        self.assertTrue(TEST_MODE.search("if settings.TESTING: return"))
        self.assertTrue(
            TEST_MODE.search('if getattr(settings, "CELERY_TASK_ALWAYS_EAGER")')
        )
        self.assertFalse(TEST_MODE.search("TESTING_NOTES = 1"))
