"""History spooling preserves chronology and closes private temporary data."""

import gc
import json
import tracemalloc
from unittest.mock import patch

from django.test import SimpleTestCase, tag

from integrations.imports.helpers import MediaImportError
from integrations.imports.history_pages import HistoryPages
from integrations.imports.trakt import TraktImporter


class HistoryPagesTests(SimpleTestCase):
    """Exercise the real retrieval seam without database/provider dependencies."""

    def importer(self, oauth=False):
        importer = TraktImporter.__new__(TraktImporter)
        importer.username = "test"
        importer.user_base_url = "https://api.trakt.tv/users/test"
        importer.is_oauth_import = oauth
        importer.warnings = []
        return importer

    def test_reverse_preserves_page_order_duplicates_and_unicode(self):
        pages = HistoryPages()
        self.addCleanup(pages.close)
        entries = [{"id": i, "title": "日本語"} for i in [5, 4, 4, 2, 1]]
        pages.extend(entries[:2])
        pages.extend(entries[2:])
        self.assertEqual(len(pages), 5)
        self.assertEqual(list(reversed(pages)), list(reversed(entries)))
        self.assertEqual(list(reversed(pages)), list(reversed(entries)))

    def test_history_retrieval_spools_but_other_stages_return_lists(self):
        importer = self.importer()
        for label, expected_type in [("history entries", HistoryPages), ("ratings", list)]:
            with self.subTest(label=label), patch.object(
                importer, "_make_api_request", side_effect=[[{"id": 2}], [{"id": 1}], []],
            ):
                result = importer._get_paginated_data("https://example.com", label)
                self.assertIsInstance(result, expected_type)
                self.assertEqual(list(reversed(result)), [{"id": 1}, {"id": 2}])
                if isinstance(result, HistoryPages):
                    result.close()

    def test_retrieval_failure_closes_archive(self):
        importer = self.importer()
        with patch.object(importer, "_make_api_request", side_effect=RuntimeError("failed")):
            with patch.object(HistoryPages, "close", autospec=True, side_effect=HistoryPages.close) as close:
                with self.assertRaises(RuntimeError):
                    importer._get_paginated_data("https://example.com", "history entries")
                close.assert_called_once()
                self.assertTrue(close.call_args.args[0]._file.closed)

    def test_processing_failure_closes_archive(self):
        importer = self.importer()
        for error in [MediaImportError("stop"), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                pages = HistoryPages()
                pages.extend([{"type": "movie", "movie": {"title": "title"}, "watched_at": "2025-01-01"}])
                with (
                    patch.object(importer, "_get_paginated_data", return_value=pages),
                    patch.object(importer, "process_watched_movie", side_effect=error),
                    self.assertRaises(type(error)),
                ):
                    importer.process_history()
                self.assertTrue(pages._file.closed)

    def test_oauth_fallback_closes_both_archives(self):
        importer = self.importer(oauth=True)
        empty, fallback = HistoryPages(), HistoryPages()
        entry = {"type": "movie", "movie": {"title": "title"}, "watched_at": "2025-01-01"}
        fallback.extend([entry])
        with (
            patch.object(importer, "_get_paginated_data", side_effect=[empty, fallback]),
            patch.object(importer, "process_watched_movie") as process,
        ):
            importer.process_history()
        process.assert_called_once_with(entry)
        self.assertTrue(empty._file.closed)
        self.assertTrue(fallback._file.closed)

    def test_mocked_list_seam_still_processes_oldest_first(self):
        importer = self.importer()
        entries = [{"type": "movie", "movie": {"title": "title"}, "watched_at": str(i)} for i in [3, 2, 1]]
        with (
            patch.object(importer, "_get_paginated_data", return_value=entries),
            patch.object(importer, "process_watched_movie") as process,
        ):
            importer.process_history()
        self.assertEqual([call.args[0] for call in process.call_args_list], list(reversed(entries)))


@tag("slow", "benchmark")
class HistoryPagesMemoryTests(SimpleTestCase):
    """Retained payload memory stays bounded by a decoded page, not watch count."""

    def test_large_histories_keep_only_page_descriptors(self):
        encoded = json.dumps([
            {"id": i, "watched_at": "2025-01-01T00:00:00Z", "show": {"title": "Test show", "ids": {"tmdb": i}}, "episode": {"season": 1, "number": i}}
            for i in range(1000)
        ])
        for count in [10000, 50000, 80849, 200000]:
            with self.subTest(entries=count):
                gc.collect()
                tracemalloc.start()
                pages = HistoryPages()
                try:
                    for start in range(0, count, 1000):
                        pages.extend(json.loads(encoded)[:min(1000, count - start)])
                    retained, _ = tracemalloc.get_traced_memory()
                    self.assertEqual(len(pages), count)
                    self.assertLess(retained, 256 * 1024)
                    self.assertEqual(sum(1 for _ in reversed(pages)), count)
                    _, peak = tracemalloc.get_traced_memory()
                    self.assertLess(peak, 4 * 1024 * 1024)
                finally:
                    pages.close()
                    tracemalloc.stop()
