"""Tests for the MangaBaka library importer."""

from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, Manga, MediaTypes, Sources, Status
from integrations.imports import helpers, mangabaka

RAW_TOKEN = "mb-test-token"


def series_payload(series_id, title="Some Manga", **overrides):
    """Return a MangaBaka series object as /my/library nests it."""
    payload = {
        "id": series_id,
        "title": title,
        "romanized_title": f"{title} (romaji)",
        "cover": {"raw": {"url": f"https://images.example/{series_id}.jpg"}},
        "total_chapters": "40",
    }
    payload.update(overrides)
    return payload


def entry_payload(series_id, state="reading", **overrides):
    """Return one /my/library data row."""
    payload = {
        "series_id": series_id,
        "Series": series_payload(series_id),
        "state": state,
        "rating": None,
        "progress_chapter": 0,
        "progress_volume": None,
        "number_of_rereads": None,
        "start_date": None,
        "finish_date": None,
        "note": None,
    }
    payload.update(overrides)
    return payload


def page_payload(entries, *, page=1, count=None, has_next=False):
    """Return a paginated /my/library response."""
    return {
        "status": 200,
        "pagination": {
            "count": count if count is not None else len(entries),
            "page": page,
            "limit": mangabaka.PAGE_SIZE,
            "next": "https://api.mangabaka.org/v1/my/library?page=2" if has_next else None,
            "previous": None,
        },
        "data": entries,
    }


def http_error(status_code):
    """Return a requests HTTPError carrying a status code."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(response=response)


class ImportMangaBaka(TestCase):
    """Test importing a library from MangaBaka."""

    def setUp(self):
        """Create a user and an encrypted token for the tests."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.token = helpers.encrypt(RAW_TOKEN)

    def _run(self, payloads, mode="new"):
        """Run the importer with api_request stubbed to the given pages."""
        if isinstance(payloads, dict):
            payloads = [payloads]

        with patch("app.providers.services.api_request") as api_request:
            api_request.side_effect = payloads
            return mangabaka.importer(self.token, self.user, mode)

    def test_import_maps_entry_fields(self):
        """Every carried field lands on the row in Floppy's vocabulary."""
        self._run(
            page_payload(
                [
                    entry_payload(
                        12,
                        state="completed",
                        rating=90,
                        progress_chapter=40,
                        start_date="2024-01-02T00:00:00.000Z",
                        finish_date="2024-03-04T00:00:00.000Z",
                        note="a note",
                    ),
                ],
            ),
        )

        manga = Manga.objects.get(user=self.user)
        self.assertEqual(manga.status, Status.COMPLETED.value)
        self.assertEqual(manga.progress, 40)
        self.assertEqual(float(manga.score), 9.0)
        self.assertEqual(manga.notes, "a note")
        self.assertEqual(manga.start_date.date().isoformat(), "2024-01-02")
        self.assertEqual(manga.end_date.date().isoformat(), "2024-03-04")

        item = manga.item
        self.assertEqual(item.source, Sources.MANGABAKA.value)
        self.assertEqual(item.media_type, MediaTypes.MANGA.value)
        self.assertEqual(item.media_id, "12")
        self.assertEqual(item.title, "Some Manga")
        self.assertEqual(item.image, "https://images.example/12.jpg")

    def test_import_maps_every_documented_state(self):
        """Each MangaBaka state resolves to one of Floppy's five."""
        expected = {
            "reading": Status.IN_PROGRESS.value,
            "rereading": Status.IN_PROGRESS.value,
            "completed": Status.COMPLETED.value,
            "paused": Status.PAUSED.value,
            "dropped": Status.DROPPED.value,
            "considering": Status.PLANNING.value,
            "plan_to_read": Status.PLANNING.value,
        }
        entries = [
            entry_payload(index, state=state)
            for index, state in enumerate(expected, start=1)
        ]

        self._run(page_payload(entries))

        for index, state in enumerate(expected, start=1):
            manga = Manga.objects.get(user=self.user, item__media_id=str(index))
            self.assertEqual(manga.status, expected[state], state)

    def test_import_converts_100_point_rating_to_10_point_score(self):
        """MangaBaka rates 0-100 while Floppy's score field is 0-10."""
        self._run(
            page_payload(
                [
                    entry_payload(1, rating=100),
                    entry_payload(2, rating=45),
                    entry_payload(3, rating=None),
                ],
            ),
        )

        self.assertEqual(float(Manga.objects.get(item__media_id="1").score), 10.0)
        self.assertEqual(float(Manga.objects.get(item__media_id="2").score), 4.5)
        self.assertIsNone(Manga.objects.get(item__media_id="3").score)

    def test_import_follows_pagination(self):
        """Entries past the first page are imported too."""
        first = page_payload([entry_payload(1)], page=1, count=2, has_next=True)
        second = page_payload([entry_payload(2)], page=2, count=2)

        counts, _ = self._run([first, second])

        self.assertEqual(counts["manga"], 2)
        self.assertEqual(
            set(Manga.objects.filter(user=self.user).values_list("item__media_id", flat=True)),
            {"1", "2"},
        )

    def test_import_stops_when_a_page_reports_no_next(self):
        """A single-page library does not ask for a second page."""
        with patch("app.providers.services.api_request") as api_request:
            api_request.return_value = page_payload([entry_payload(1)])
            mangabaka.importer(self.token, self.user, "new")

        self.assertEqual(api_request.call_count, 1)

    def test_import_creates_a_row_per_reread(self):
        """Rereads become their own completed rows, as the other importers do."""
        self._run(
            page_payload(
                [entry_payload(1, state="reading", number_of_rereads=2, progress_chapter=5)],
            ),
        )

        rows = Manga.objects.filter(user=self.user)
        self.assertEqual(rows.count(), 3)
        self.assertEqual(
            rows.filter(status=Status.COMPLETED.value).count(),
            2,
        )
        self.assertEqual(
            rows.get(status=Status.IN_PROGRESS.value).progress,
            5,
        )

    def test_import_skips_existing_entries_in_new_mode(self):
        """'new' mode leaves an already-tracked series alone."""
        item = Item.objects.create(
            media_id="1",
            source=Sources.MANGABAKA.value,
            media_type=MediaTypes.MANGA.value,
            title="Already here",
        )
        Manga.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
            progress=0,
        )

        counts, _ = self._run(page_payload([entry_payload(1, state="completed")]))

        # Nothing was queued, so the importer reports no rows for any type.
        self.assertEqual(counts.get("manga", 0), 0)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 1)
        manga = Manga.objects.get(user=self.user)
        self.assertEqual(manga.status, Status.PLANNING.value)
        self.assertEqual(manga.item.title, "Already here")

    def test_import_rejects_a_missing_token(self):
        """Without a token there is no library to read."""
        with self.assertRaises(helpers.MediaImportError):
            mangabaka.importer(None, self.user, "new")

    def test_import_reports_a_rejected_token(self):
        """A 401 surfaces as an import error, not a traceback."""
        with patch("app.providers.services.api_request") as api_request:
            api_request.side_effect = http_error(401)
            with self.assertRaises(helpers.MediaImportError):
                mangabaka.importer(self.token, self.user, "new")

    def test_import_warns_on_an_unknown_state(self):
        """An unexpected state warns rather than silently mis-filing the row."""
        counts, warnings = self._run(
            page_payload([entry_payload(1, state="teleporting")]),
        )

        self.assertEqual(counts["manga"], 1)
        self.assertIn("teleporting", warnings)
        self.assertEqual(
            Manga.objects.get(user=self.user).status,
            Status.PLANNING.value,
        )

    def test_import_tolerates_a_missing_series_block(self):
        """A row with no series payload is skipped, not fatal."""
        entry = entry_payload(1)
        entry["Series"] = None
        entry["series_id"] = None

        counts, warnings = self._run(page_payload([entry]))

        self.assertEqual(counts.get("manga", 0), 0)
        self.assertIn("no series id", warnings)
