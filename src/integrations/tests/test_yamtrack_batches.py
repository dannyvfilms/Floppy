from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import TV, Episode, Movie, Season
from integrations.imports import yamtrack
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

MOCK_DATA = Path(__file__).resolve().parent / "mock_data"
MOVIE_HEADER = (
    "media_id,source,media_type,title,image,season_number,episode_number,"
    "score,progress,status,start_date,end_date,notes,progressed_at\n"
)


def _movie_csv(media_ids):
    """Build small metadata-complete movie rows for batch behavior tests."""
    rows = [
        f"{media_id},tmdb,movie,Movie {media_id},https://image/{media_id}.jpg,,,8,1,Completed,,,,"
        for media_id in media_ids
    ]
    return (MOVIE_HEADER + "\n".join(rows) + "\n").encode()


class YamtrackBatchImportTests(TestCase):
    """Yamtrack imports stream rows while retaining import semantics."""

    def setUp(self):
        """Use a deliberately small batch size to exercise flush boundaries."""
        self.user = get_user_model().objects.create_user(
            username="yamtrack-batches",
            password="password",
        )
        self.batch_size = patch(
            "integrations.imports.yamtrack.YAMTRACK_IMPORT_BATCH_SIZE",
            2,
        )
        self.batch_size.start()
        self.addCleanup(self.batch_size.stop)

    def test_dependency_ordering_survives_multiple_batches(self):
        fixture = MOCK_DATA / "import_yamtrack.csv"

        with fixture.open("rb") as file:
            counts, warnings = yamtrack.importer(file, self.user, "new")

        self.assertEqual(warnings, "")
        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            24,
        )
        self.assertEqual(counts["tv"], 1)
        self.assertEqual(counts["season"], 1)

    def test_duplicate_rows_across_batches_are_not_recreated(self):
        counts, warnings = yamtrack.importer(
            BytesIO(_movie_csv(["duplicate", "duplicate", "duplicate"])),
            self.user,
            "new",
        )

        self.assertEqual(warnings, "")
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(counts["movie"], 1)

    def test_overwrite_mode_replaces_rows_without_duplicate_media(self):
        first = yamtrack.importer(
            BytesIO(_movie_csv(["overwrite-1", "overwrite-2", "overwrite-3"])),
            self.user,
            "new",
        )
        self.assertEqual(first[1], "")

        counts, warnings = yamtrack.importer(
            BytesIO(_movie_csv(["overwrite-1", "overwrite-2", "overwrite-3"])),
            self.user,
            "overwrite",
        )

        self.assertEqual(warnings, "")
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 3)
        self.assertEqual(counts["movie"], 3)

    def test_invalid_utf8_is_reported_before_processing_rows(self):
        with self.assertRaises(MediaImportError):
            yamtrack.importer(
                BytesIO(MOVIE_HEADER.encode() + b"bad,tmdb,movie,\xff\n"),
                self.user,
                "new",
            )
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 0)

    def test_rows_flushed_before_a_later_batch_failure_remain_saved(self):
        original_process_row = yamtrack.YamtrackImporter._process_row

        def fail_on_third_row(importer, row):
            if row["media_id"] == "3":
                raise RuntimeError("later batch failed")
            return original_process_row(importer, row)

        with (
            patch.object(
                yamtrack.YamtrackImporter,
                "_process_row",
                autospec=True,
                side_effect=fail_on_third_row,
            ),
            self.assertRaises(MediaImportUnexpectedError),
        ):
            yamtrack.importer(
                BytesIO(_movie_csv(["1", "2", "3"])),
                self.user,
                "new",
            )

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 2)
