"""The WeTrakr file import carries its own, longer Celery limits."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from integrations.models import ImportRun
from integrations.tasks import _import_helpers, _media_imports


class WeTrakrImportTimeLimitTests(SimpleTestCase):
    def test_task_overrides_global_limit(self):
        task = _media_imports.import_wetrakr_export
        self.assertEqual(task.time_limit, _import_helpers.WETRAKR_IMPORT_TIME_LIMIT)
        self.assertEqual(
            task.soft_time_limit,
            _import_helpers.WETRAKR_IMPORT_SOFT_TIME_LIMIT,
        )
        self.assertLess(task.soft_time_limit, task.time_limit)
        self.assertGreater(task.time_limit, 30 * 60)

    def test_abandoned_after_is_per_source(self):
        helpers = _import_helpers
        base = 30 * 60
        self.assertEqual(helpers.abandoned_after_seconds("trakt", base), base + 300)
        self.assertEqual(
            helpers.abandoned_after_seconds("wetrakr", base),
            helpers.WETRAKR_IMPORT_TIME_LIMIT + 300,
        )


class AbandonedRunRecoveryTests(TestCase):
    def _run(self, source, minutes_ago):
        user = get_user_model().objects.create_user(
            username=f"u-{source}-{minutes_ago}", password="x",
        )
        run = ImportRun.objects.create(user=user, source=source)
        ImportRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        return run

    def test_wetrakr_run_gets_its_full_window(self):
        young = self._run("wetrakr", 60)  # past 35 min, inside 2h05
        old = self._run("wetrakr", 130)
        other = self._run("trakt", 60)
        with override_settings(CELERY_TASK_TIME_LIMIT=30 * 60):
            _import_helpers.close_abandoned_import_runs()
        status = {r.pk: ImportRun.objects.get(pk=r.pk).status for r in (young, old, other)}
        self.assertEqual(status[young.pk], ImportRun.Status.RUNNING)
        self.assertEqual(status[old.pk], ImportRun.Status.FAILED)
        self.assertEqual(status[other.pk], ImportRun.Status.FAILED)


class WeTrakrMetadataMemoTests(SimpleTestCase):
    """Interleaved shows and seasons must not be refetched from TMDB."""

    def _fetches(self, importer_cls):
        from unittest.mock import patch

        importer = object.__new__(importer_cls)
        importer.warnings = []
        calls = []

        def fake(media_type, media_id, source, **kwargs):
            calls.append((media_type, media_id, kwargs.get("season_numbers")))
            return {"title": str(media_id)}

        with patch(
            "integrations.imports.trakt.services.get_media_metadata",
            side_effect=fake,
        ):
            # 20 shows x 2 seasons, replayed in date order: every pass touches
            # every show and season before any is seen again.
            for _ in range(5):
                for show in range(20):
                    importer._get_metadata("tv", show, "t")
                    for season in (1, 2):
                        importer._get_metadata("season", show, "t", season)
        return len(calls)

    def test_wetrakr_fetches_each_show_and_season_once(self):
        from integrations.imports.wetrakr import WeTrakrImporter

        self.assertEqual(self._fetches(WeTrakrImporter), 20 * 3)

    def test_api_importer_keeps_small_memo(self):
        from integrations.imports.trakt import TraktImporter

        self.assertGreater(self._fetches(TraktImporter), 20 * 3)


class TitleSearchMemoTests(SimpleTestCase):
    def test_unresolved_show_is_searched_once_across_episodes(self):
        from unittest.mock import patch

        from integrations.imports.wetrakr import WeTrakrImporter

        importer = object.__new__(WeTrakrImporter)
        importer.warnings = []
        importer.external_reference_integration = None
        importer._get_trakt_reference = lambda *args, **kwargs: None
        with patch(
            "integrations.imports.trakt.services.search",
            return_value={"results": []},
        ) as search:
            for _ in range(50):
                importer._get_tmdb_id({"title": "Nope", "ids": {"tmdb": None}}, "tv")
        self.assertEqual(search.call_count, 1)
