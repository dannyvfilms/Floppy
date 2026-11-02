import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import stats_reading
from app.models import Book, Item, MediaTypes, Sources, Status
from app.statistics_cache import get_statistics_data


class ReadingCompletionsTests(TestCase):
    """Issue #1379: "Books Finished" must count finished books, not reading days."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reader", password="password123"
        )

    def _book(self, media_id, status, start, end, pages=300, progress=None):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            title=f"Book {media_id}",
            number_of_pages=pages,
        )
        tz = timezone.get_current_timezone()
        return Book.objects.create(
            user=self.user,
            item=item,
            status=status,
            progress=pages if progress is None else progress,
            start_date=datetime.datetime(*start, 12, 0, tzinfo=tz),
            end_date=datetime.datetime(*end, 12, 0, tzinfo=tz),
        )

    def test_finished_counts_books_not_reading_days(self):
        # One book read over 30 days in 2023, one read in a single day in 2024,
        # one still in progress (must not count as finished).
        self._book("b1", Status.COMPLETED.value, (2023, 1, 1), (2023, 1, 30))
        self._book("b2", Status.COMPLETED.value, (2024, 5, 4), (2024, 5, 4))
        self._book("b3", Status.IN_PROGRESS.value, (2024, 6, 1), (2024, 6, 10), progress=100)

        data = get_statistics_data(self.user, start_date=None, end_date=None)
        book = data["book_consumption"]

        by_year = book["completion_charts"]["by_year"]
        self.assertEqual(by_year["labels"], ["2023", "2024"])
        self.assertEqual(by_year["datasets"][0]["data"], [1, 1])
        self.assertEqual(book["completions"]["total"], 2)


class ReadingRangePrefilterTests(TestCase):
    """The SQL prefilter must never drop a row the date predicate keeps."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reading-prefilter", password="password123"
        )
        tz = timezone.get_current_timezone()
        self.start = timezone.make_aware(datetime.datetime(2024, 1, 1), tz)
        self.end = timezone.make_aware(
            datetime.datetime(2024, 1, 31, 23, 59, 59), tz
        )

    def _book(self, media_id, start=None, end=None, created=None):
        tz = timezone.get_current_timezone()

        def dt(value):
            return (
                timezone.make_aware(datetime.datetime(*value, 12, 0), tz)
                if value
                else None
            )

        item = Item.objects.create(
            media_id=media_id,
            source=Sources.MANUAL.value,
            media_type=MediaTypes.BOOK.value,
            title=f"Book {media_id}",
            number_of_pages=300,
        )
        entry = Book.objects.create(
            user=self.user,
            item=item,
            status=Status.COMPLETED.value,
            progress=300,
            start_date=dt(start),
            end_date=dt(end),
        )
        if created:
            Book.objects.filter(pk=entry.pk).update(created_at=dt(created))
            entry.refresh_from_db()
        return entry

    def test_the_prefilter_is_a_superset_of_the_date_predicate(self):
        entries = {
            "inside": self._book("inside", (2024, 1, 5), (2024, 1, 10)),
            "before": self._book("before", (2023, 11, 1), (2023, 11, 2)),
            "after": self._book("after", (2024, 3, 1), (2024, 3, 2)),
            "spans_start": self._book(
                "spans-start", (2023, 12, 20), (2024, 1, 5)
            ),
            "start_only_inside": self._book("start-only-in", (2024, 1, 8), None),
            "end_only_inside": self._book("end-only-in", None, (2024, 1, 9)),
            "start_only_after": self._book("start-only-out", (2024, 4, 1), None),
            "end_only_before": self._book("end-only-out", None, (2023, 6, 1)),
            "undated_inside": self._book("undated-in", created=(2024, 1, 20)),
            "undated_before": self._book("undated-out", created=(2023, 6, 1)),
        }
        kept = {
            name
            for name, entry in entries.items()
            if stats_reading._reading_entry_in_range(entry, self.start, self.end)
        }
        narrowed = set(
            Book.objects.filter(
                stats_reading._reading_entry_range_filter(self.start, self.end)
            ).values_list("pk", flat=True)
        )

        self.assertEqual(
            kept,
            {
                "inside",
                "spans_start",
                "start_only_inside",
                "end_only_inside",
                "undated_inside",
            },
        )
        self.assertTrue(
            {entries[name].pk for name in kept} <= narrowed,
            "the prefilter dropped a row the date predicate keeps",
        )
        self.assertNotIn(entries["before"].pk, narrowed)
        self.assertNotIn(entries["after"].pk, narrowed)


class ReadingCompletionAggregationTests(TestCase):
    """Completion scans must retain entry lengths and latest-per-title dates."""

    def test_reading_types_preserve_bounded_and_all_time_completion_semantics(self):
        user = get_user_model().objects.create_user(username="completion-rollups")
        other = get_user_model().objects.create_user(username="other-reader")
        tz = timezone.get_current_timezone()

        def dt(year, month, day):
            return timezone.make_aware(datetime.datetime(year, month, day, 12), tz)

        for media_type in ("book", "comic", "manga"):
            with self.subTest(media_type=media_type):
                cache.clear()
                model = apps.get_model("app", media_type)
                items = Item.objects.bulk_create(
                    [
                        Item(
                            media_id=f"{media_type}-{index}",
                            source=Sources.MANUAL.value,
                            media_type=media_type,
                            title=f"Reading fixture {index}",
                            number_of_pages=300 if index != 2 else 0,
                        )
                        for index in range(5)
                    ]
                )
                rows = model.objects.bulk_create(
                    [
                        model(user=user, item=items[0], status=Status.COMPLETED.value,
                              progress=200, start_date=dt(2024, 1, 5), end_date=dt(2024, 1, 6)),
                        model(user=user, item=items[0], status=Status.COMPLETED.value,
                              progress=100, start_date=dt(2024, 1, 7), end_date=dt(2024, 1, 8)),
                        model(user=user, item=items[1], status=Status.COMPLETED.value,
                              progress=0, start_date=dt(2023, 12, 25), end_date=dt(2024, 1, 10)),
                        model(user=user, item=items[2], status=Status.COMPLETED.value,
                              progress=0),
                        model(user=user, item=items[3], status=Status.COMPLETED.value,
                              progress=400, end_date=dt(2023, 11, 1)),
                        model(user=user, item=items[4], status=Status.IN_PROGRESS.value,
                              progress=500, start_date=dt(2024, 1, 2), end_date=dt(2024, 1, 20)),
                        model(user=other, item=items[0], status=Status.COMPLETED.value,
                              progress=999, end_date=dt(2024, 1, 6)),
                    ]
                )
                model.objects.filter(pk=rows[3].pk).update(created_at=dt(2024, 1, 20))

                bounded = get_statistics_data(
                    user, dt(2024, 1, 1), dt(2024, 1, 31)
                )[f"{media_type}_consumption"]
                self.assertEqual(bounded["completions"]["total"], 3)
                self.assertEqual(sorted(bounded["completed_lengths"]), [100, 200, 300])
                self.assertEqual(bounded["highlights"]["average_length"], 200)
                self.assertEqual(
                    bounded["completion_charts"]["by_month"]["datasets"][0]["data"],
                    [3] + [0] * 11,
                )

                all_time = get_statistics_data(user, None, None)[f"{media_type}_consumption"]
                self.assertEqual(all_time["completions"]["total"], 4)
                self.assertEqual(sorted(all_time["completed_lengths"]), [100, 200, 300, 400])
