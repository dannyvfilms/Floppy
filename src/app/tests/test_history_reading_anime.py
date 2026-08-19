from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import history_cache
from app.models import Anime, Book, Item, MediaTypes, Sources, Status


def _patch_media_metadata(test_case):
    """Stop reading/anime model saves from making provider calls."""
    metadata_patch = patch(
        "app.models.media.providers.services.get_media_metadata",
        return_value={"max_progress": 1},
    )
    fetch_releases_patch = patch("app.models.Item.fetch_releases")
    metadata_patch.start()
    fetch_releases_patch.start()
    test_case.addCleanup(metadata_patch.stop)
    test_case.addCleanup(fetch_releases_patch.stop)


class ReadingAnimeHistoryDayTests(TestCase):
    """Books/comics/manga and flat anime should render on the History day view."""

    def setUp(self):
        cache.clear()
        _patch_media_metadata(self)
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="12345",
        )
        self.now = timezone.localtime().replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        self.day_key = history_cache.history_day_key(self.now)
        self.addCleanup(cache.clear)

    def _make(self, model, media_type, media_id, title, score):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=media_type,
            title=title,
            image="http://example.com/x.jpg",
        )
        return model.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            end_date=self.now,
            score=score,
        )

    def test_book_and_anime_render_with_score(self):
        self._make(Book, MediaTypes.BOOK.value, "book-1", "A Book", 9)
        self._make(Anime, MediaTypes.ANIME.value, "anime-1", "An Anime", 7)

        day = history_cache.build_history_day(self.user, self.day_key)
        self.assertIsNotNone(day)

        by_type = {e["media_type"]: e for e in day["entries"]}
        self.assertIn(MediaTypes.BOOK.value, by_type)
        self.assertIn(MediaTypes.ANIME.value, by_type)
        self.assertEqual(by_type[MediaTypes.BOOK.value]["score"], 9)
        self.assertEqual(by_type[MediaTypes.ANIME.value]["score"], 7)
        self.assertEqual(
            by_type[MediaTypes.ANIME.value]["status"], Status.COMPLETED.value
        )

    def test_reading_and_anime_in_uncached_general_timeline(self):
        # The non-cached builder (used for date-range/filtered views) must also
        # surface reading/anime in the general timeline, not only when filtered.
        self._make(Book, MediaTypes.BOOK.value, "book-3", "Timeline Book", 6)
        self._make(Anime, MediaTypes.ANIME.value, "anime-3", "Timeline Anime", 5)

        history_days = history_cache.build_history_days(self.user)
        seen_types = {
            entry["media_type"] for day in history_days for entry in day["entries"]
        }
        self.assertIn(MediaTypes.BOOK.value, seen_types)
        self.assertIn(MediaTypes.ANIME.value, seen_types)

    def test_history_page_renders_reading_and_anime(self):
        self._make(Book, MediaTypes.BOOK.value, "book-4", "Rendered Book", 9)
        self._make(Anime, MediaTypes.ANIME.value, "anime-4", "Rendered Anime", 7)

        self.client.force_login(self.user)
        from django.urls import reverse

        # Use a date range to force the synchronous (non-cached) builder so the
        # day cards are server-rendered inline rather than deferred to an async
        # month-cache refresh.
        day = self.now.date().isoformat()
        response = self.client.get(
            reverse("history"),
            {"start-date": day, "end-date": day},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Rendered Book", content)
        self.assertIn("Rendered Anime", content)

    def test_score_change_invalidates_history_day(self):
        book = self._make(Book, MediaTypes.BOOK.value, "book-2", "Rated Book", None)

        with patch(
            "app.signals.history_cache.invalidate_history_days"
        ) as mock_invalidate:
            book.score = 8
            book.save()

        mock_invalidate.assert_called()
        called_day_keys = set()
        for call in mock_invalidate.call_args_list:
            called_day_keys.update(call.kwargs.get("day_keys") or [])
        self.assertIn(self.day_key, called_day_keys)

    def test_reading_and_anime_days_reach_the_history_index(self):
        """A day whose only activity is reading must be an indexed history day.

        The cached month view only renders days the index lists, so a read on
        a day with no episode/movie/game/music activity was invisible in
        history even though build_history_day() rendered it correctly.
        """
        self._make(Book, MediaTypes.BOOK.value, "book-5", "Indexed Book", 8)

        day_keys = history_cache.build_history_index(self.user)

        self.assertIn(self.day_key, day_keys)

    def test_in_progress_reading_is_indexed_from_its_start_date(self):
        """An unfinished read is indexed on its start day, as the day builder renders it."""
        item = Item.objects.create(
            media_id="book-6",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            title="Started Book",
            image="http://example.com/x.jpg",
        )
        Book.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=1,
            start_date=self.now,
        )

        self.assertIn(self.day_key, history_cache.build_history_index(self.user))
