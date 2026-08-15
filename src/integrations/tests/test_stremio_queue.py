from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from integrations import stremio_queue


class StremioQueueTests(SimpleTestCase):
    """Verify atomic, bounded per-user playback admission."""

    def setUp(self):
        cache.clear()

    def test_duplicate_and_cap_are_atomic(self):
        """Duplicates do not consume slots and the ninth item is limited."""
        members = [stremio_queue.member("series", f"tt123:{index}:1") for index in range(1, 10)]
        statuses = [
            stremio_queue.reserve_pending(7, queue_member)
            for queue_member in members
        ]

        self.assertEqual(statuses[:8], ["accepted"] * 8)
        self.assertEqual(statuses[8], "limited")
        self.assertEqual(stremio_queue.reserve_pending(7, members[0]), "duplicate")

    def test_release_allows_next_item(self):
        """Worker admission release returns one slot to the user."""
        members = [stremio_queue.member("movie", f"tt{index}") for index in range(8)]
        for queue_member in members:
            self.assertEqual(
                stremio_queue.reserve_pending(8, queue_member),
                "accepted",
            )
        self.assertEqual(stremio_queue.reserve_pending(8, "movie:tt999"), "limited")
        self.assertTrue(stremio_queue.release_pending(8, members[0]))
        self.assertEqual(stremio_queue.reserve_pending(8, "movie:tt999"), "accepted")

    def test_unavailable_redis_fails_closed(self):
        """A Redis outage does not turn the bounded queue into direct dispatch."""
        with patch.object(stremio_queue, "_client", return_value=None):
            self.assertEqual(
                stremio_queue.reserve_pending(9, "movie:tt1"),
                "unavailable",
            )
