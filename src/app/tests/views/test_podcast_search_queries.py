from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import (
    Item,
    MediaTypes,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)
from app.search_views import _local_podcast_results


class LocalPodcastResultsQueryTests(TestCase):
    """Local podcast search must not issue per-result queries or writes."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(
            username="podcaster",
            password="12345",
        )

    def _make_shows(self, count, *, with_items):
        for i in range(count):
            show = PodcastShow.objects.create(
                podcast_uuid=f"uuid-{i}",
                source=Sources.POCKETCASTS.value,
                title=f"Dune Show {i:02d}",
                image="http://example.com/a.jpg",
            )
            PodcastShowTracker.objects.create(
                user=self.user,
                show=show,
                status=Status.IN_PROGRESS.value,
            )
            if with_items:
                Item.objects.create(
                    media_id=show.podcast_uuid,
                    source=show.source,
                    media_type=MediaTypes.PODCAST.value,
                    title=show.title,
                    image="http://example.com/a.jpg",
                )

    def _queries(self, limit):
        with CaptureQueriesContext(connection) as ctx:
            results, total = _local_podcast_results(self.user, "Dune", limit)
        return results, total, ctx

    def test_existing_items_query_count_is_constant(self):
        """Already-present Items cost the same queries at 5 and 24 results."""
        self._make_shows(24, with_items=True)
        counts = []
        for limit in (5, 20, 24):
            results, total, ctx = self._queries(limit)
            self.assertEqual(len(results), limit)
            self.assertEqual(total, 24)
            counts.append(len(ctx))
        self.assertEqual(len(set(counts)), 1, counts)
        self.assertLessEqual(counts[0], 6)

    def test_existing_items_do_not_get_or_create_or_write(self):
        """Up-to-date Items are neither re-fetched one by one nor saved."""
        self._make_shows(10, with_items=True)
        with patch.object(
            Item.objects.__class__,
            "get_or_create",
            side_effect=AssertionError("get_or_create called"),
        ):
            _, _, ctx = self._queries(10)
        writes = [
            q for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE"))
        ]
        self.assertEqual(writes, [])

    def test_missing_items_are_created_and_stale_ones_updated(self):
        """Shell Items are created; stale title/image are refreshed."""
        self._make_shows(3, with_items=False)
        show = PodcastShow.objects.get(podcast_uuid="uuid-0")
        Item.objects.create(
            media_id=show.podcast_uuid,
            source=show.source,
            media_type=MediaTypes.PODCAST.value,
            title="Old title",
            image="http://example.com/old.jpg",
        )
        results, _, _ = self._queries(24)
        self.assertEqual(
            [r["item"].title for r in results],
            ["Dune Show 00", "Dune Show 01", "Dune Show 02"],
        )
        self.assertEqual(
            Item.objects.filter(media_type=MediaTypes.PODCAST.value).count(),
            3,
        )
        stale = Item.objects.get(media_id="uuid-0", media_type="podcast")
        self.assertEqual(stale.title, "Dune Show 00")
        self.assertEqual(stale.image, "http://example.com/a.jpg")
