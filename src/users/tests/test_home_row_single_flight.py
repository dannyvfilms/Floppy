"""Two requests for the same cold Home row build it once."""

import threading
import time
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from users import home_screen


class HomeRowSingleFlightTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = SimpleNamespace(id=7)
        self.row = SimpleNamespace(id=3)

    def _request(self, results):
        results.append(home_screen._cached_row_section(self.user, self.row, "movie", 14))

    def test_concurrent_cold_requests_build_once(self):
        builds = []

        def slow_build(*_args, **_kwargs):
            builds.append(1)
            time.sleep(0.4)
            return {"row_id": 3, "items": []}

        results = []
        with mock.patch.object(home_screen, "_build_row_section", side_effect=slow_build):
            first = threading.Thread(target=self._request, args=(results,))
            first.start()
            time.sleep(0.1)  # the first request is mid-build
            self._request(results)
            first.join()

        self.assertEqual(len(builds), 1)
        self.assertEqual(results, [{"row_id": 3, "items": []}] * 2)

    def test_a_stalled_builder_does_not_block_the_next_request(self):
        cache.set(f"{home_screen.cache_utils_key(self.user, self.row)}_building", 1, 30)
        with (
            mock.patch.object(home_screen, "_HOME_ROW_WAIT_SECONDS", 0.2),
            mock.patch.object(home_screen, "_build_row_section", return_value={"row_id": 3}) as build,
        ):
            section = home_screen._cached_row_section(self.user, self.row, "movie", 14)
        self.assertEqual(section, {"row_id": 3})
        build.assert_called_once()

    def test_refresh_bypasses_the_wait(self):
        cache.set(f"{home_screen.cache_utils_key(self.user, self.row)}_building", 1, 30)
        with mock.patch.object(home_screen, "_build_row_section", return_value={"row_id": 3}) as build:
            start = time.monotonic()
            home_screen._cached_row_section(self.user, self.row, "movie", 14, refresh=True)
        self.assertLess(time.monotonic() - start, 1)
        build.assert_called_once()

    def test_empty_row_result_is_shared_too(self):
        with mock.patch.object(home_screen, "_build_row_section", return_value=None) as build:
            self.assertIsNone(home_screen._cached_row_section(self.user, self.row, "movie", 14))
            self.assertIsNone(home_screen._cached_row_section(self.user, self.row, "movie", 14))
        build.assert_called_once()
