"""Tests for the Kavita reading progress sync."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import Book, Comic, ComicIssue, Item, Manga, MediaTypes, Sources, Status
from app.providers.services import ProviderAPIError
from integrations.imports import helpers, kavita
from integrations.models import ImportRun, KavitaAccount, KavitaLink

# Shapes follow Kavita's OpenAPI (v0.9.1.6): SeriesDto carries the external
# ids and pagesRead; SeriesDetailDto carries volumes/chapters with pagesRead.
MANGA, COMIC, BOOK = 0, 1, 2


def _series(series_id, *, name="One Piece", pages=100, pages_read=10, **extra):
    return {
        "id": series_id,
        "name": name,
        "pages": pages,
        "pagesRead": pages_read,
        "latestReadDate": "2026-09-20T12:00:00Z",
        "malId": 0,
        **extra,
    }


def _chapter(chapter_id, *, pages=20, pages_read=0, number=0, **extra):
    return {
        "id": chapter_id,
        "pages": pages,
        "pagesRead": pages_read,
        "maxNumber": number,
        "range": str(number),
        "lastReadingProgressUtc": "2026-09-20T12:00:00Z",
        **extra,
    }


def _detail(library_type, chapters):
    return {"libraryType": library_type, "volumes": [], "chapters": chapters}


class FakeKavita:
    """Route Kavita paths to canned payloads, recording each call."""

    def __init__(self, series, details):
        """Store the series list and per-series details to serve."""
        self.series = series
        self.details = details
        self.metadata = {}
        self.chapter_metadata = {}
        self.calls = []

    def __call__(self, service, method, url, **kwargs):
        path = url.split("kavita.local:5000", 1)[1]
        self.calls.append((method, path, kwargs))
        if path == "/api/Plugin/authenticate":
            return {"token": "jwt-token"}
        if path == "/api/Series/all-v2":
            return self.series if kwargs["params"]["PageNumber"] == 1 else []
        if path == "/api/Series/series-detail":
            return self.details[kwargs["params"]["seriesId"]]
        if path == "/api/Series/metadata":
            return self.metadata.get(kwargs["params"]["seriesId"], {})
        if path == "/api/Chapter":
            return self.chapter_metadata.get(kwargs["params"]["chapterId"], {})
        msg = f"unexpected {path}"
        raise AssertionError(msg)


class KavitaImporterTests(TestCase):
    """Cover what the sync writes and how it treats failures."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kavita-user")
        self.account = KavitaAccount.objects.create(
            user=self.user,
            base_url="https://kavita.local:5000/",
            api_key=helpers.encrypt("kavita-key"),
        )

    def _sync(self, series, details):
        fake = FakeKavita(series, details)
        with patch("integrations.imports.kavita.request_json", side_effect=fake):
            result = kavita.importer(None, self.user, "new")
        self.fake = fake
        return result

    def test_manga_with_mal_id_tracks_chapters_read(self):
        """A malId gives the series its MyAnimeList identity, no title guessing."""
        series = _series(1, malId=13, pages=60, pages_read=40)
        chapters = [
            _chapter(11, pages_read=20, number=1),
            _chapter(12, pages_read=20, number=2),
            _chapter(13, pages_read=0, number=3),
        ]

        counts, warnings = self._sync([series], {1: _detail(MANGA, chapters)})

        item = Item.objects.get(media_id="13")
        self.assertEqual(item.source, Sources.MAL.value)
        self.assertEqual(item.media_type, MediaTypes.MANGA.value)
        entry = Manga.objects.get(user=self.user, item=item)
        self.assertEqual(entry.progress, 2)
        self.assertEqual(entry.status, Status.IN_PROGRESS.value)
        self.assertEqual(entry.entry_source, "kavita")
        self.assertEqual(counts["created"], 1)
        self.assertEqual(counts[MediaTypes.MANGA.value], 1)
        self.assertEqual(warnings, "")

    def test_write_retries_when_sqlite_reports_a_lock(self):
        """A lock that fails the first write at once must not abort the sync."""
        real = QuerySet.update_or_create
        failures = []

        def locked_once(queryset, *args, **kwargs):
            if queryset.model is Manga and not failures:
                failures.append(1)
                raise OperationalError("database is locked")
            return real(queryset, *args, **kwargs)

        series = _series(1, malId=13, pages=60, pages_read=40)
        chapters = [_chapter(11, pages_read=20, number=1)]
        with (
            patch.object(QuerySet, "update_or_create", locked_once),
            patch("app.db_retry.time.sleep"),
        ):
            counts, _warnings = self._sync([series], {1: _detail(MANGA, chapters)})

        self.assertEqual(failures, [1])
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 1)
        self.assertEqual(counts["created"], 1)

    @patch(
        "integrations.imports.reading_server.import_progress.get_current_import_run_id"
    )
    def test_reading_progress_records_the_active_import_run(self, mock_run_id):
        run = ImportRun.objects.create(user=self.user, source="kavita")
        mock_run_id.return_value = run.id
        series = _series(2, name="Saga")
        chapters = [_chapter(21, pages_read=20, number=1, comicVineId="301")]

        self._sync([series], {2: _detail(COMIC, chapters)})

        issue = ComicIssue.objects.get(user=self.user, item__media_id="301")
        self.assertEqual(issue.import_run_id, run.id)

    def test_sync_authenticates_with_the_api_key_then_sends_the_token(self):
        self._sync([_series(1, malId=13)], {1: _detail(MANGA, [])})

        method, path, kwargs = self.fake.calls[0]
        self.assertEqual((method, path), ("post", "/api/Plugin/authenticate"))
        self.assertEqual(kwargs["params"]["apiKey"], "kavita-key")
        later = self.fake.calls[1:]
        self.assertTrue(later)
        for _method, _path, call_kwargs in later:
            self.assertEqual(
                call_kwargs["headers"],
                {"Authorization": "Bearer jwt-token"},
            )

    @patch("integrations.imports.kavita.KavitaImporter.import_data")
    def test_overwrite_mode_resets_incremental_cutoff(self, mock_import_data):
        self.account.last_sync_at = datetime(2026, 10, 8, tzinfo=UTC)
        self.account.save(update_fields=["last_sync_at"])
        mock_import_data.return_value = ({}, "")

        kavita.importer(None, self.user, "overwrite")

        self.account.refresh_from_db()
        self.assertIsNone(self.account.last_sync_at)
        mock_import_data.assert_called_once_with()

    def test_incremental_sync_uses_chapter_read_date_when_series_date_missing(self):
        self.account.last_sync_at = datetime(2026, 9, 15, tzinfo=UTC)
        self.account.save(update_fields=["last_sync_at"])
        series = _series(2, name="Saga", latestReadDate=None)
        chapters = [
            _chapter(
                21,
                pages_read=20,
                number=1,
                comicVineId="301",
                lastReadingProgressUtc=None,
            ),
        ]
        fake = FakeKavita([series], {2: _detail(COMIC, chapters)})
        fake.chapter_metadata[21] = {
            "lastReadingProgressUtc": "2026-09-20T12:00:00Z",
        }
        with patch("integrations.imports.kavita.request_json", side_effect=fake):
            kavita.importer(None, self.user, "new")

        issue = ComicIssue.objects.get(user=self.user, item__media_id="301")
        self.assertEqual(
            issue.end_date,
            datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        )

    def test_incremental_comic_sync_does_not_use_series_date_for_missing_chapter_date(
        self,
    ):
        self.account.last_sync_at = datetime(2026, 9, 15, tzinfo=UTC)
        self.account.save(update_fields=["last_sync_at"])
        series = _series(
            2,
            name="Saga",
            latestReadDate="2026-09-20T12:00:00Z",
        )
        chapters = [
            _chapter(
                21,
                pages_read=20,
                number=1,
                comicVineId="301",
                lastReadingProgressUtc=None,
            ),
        ]

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(ComicIssue.objects.exists())

    def test_fully_read_manga_is_completed_on_the_read_date(self):
        series = _series(1, malId=13, pages=40, pages_read=40)
        chapters = [
            _chapter(11, pages_read=20, number=1),
            _chapter(12, pages_read=20, number=2),
        ]

        self._sync([series], {1: _detail(MANGA, chapters)})

        entry = Manga.objects.get(user=self.user)
        self.assertEqual(entry.status, Status.COMPLETED.value)
        self.assertEqual(
            entry.end_date,
            datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        )

    def test_volume_only_manga_counts_volumes_read(self):
        """Without chapter numbers, progress is the number of chapters read."""
        series = _series(1, malId=13)
        chapters = [_chapter(11, pages_read=20), _chapter(12, pages_read=20)]

        self._sync([series], {1: _detail(MANGA, chapters)})

        self.assertEqual(Manga.objects.get(user=self.user).progress, 2)

    def test_manga_without_mal_id_becomes_a_local_entry(self):
        series = _series(1, aniListId=99)

        _counts, _warnings = self._sync([series], {1: _detail(MANGA, [])})

        item = Item.objects.get(title="One Piece")
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertTrue(Manga.objects.filter(user=self.user, item=item).exists())

    def test_unmatched_manga_is_skipped_when_create_missing_is_off(self):
        self.account.create_missing = False
        self.account.save()

        counts, warnings = self._sync([_series(1)], {1: _detail(MANGA, [])})

        self.assertFalse(Manga.objects.exists())
        self.assertEqual(counts["skipped"], 1)
        self.assertIn("Could not match Kavita item One Piece", warnings)

    def test_comic_chapters_track_issues_by_comic_vine_id(self):
        series = _series(2, name="Saga")
        chapters = [
            _chapter(21, pages_read=20, number=1, comicVineId="301"),
            _chapter(22, pages_read=5, number=2, comicVineId="302"),
            _chapter(23, pages_read=0, number=3, comicVineId="303"),
        ]

        counts, _warnings = self._sync([series], {2: _detail(COMIC, chapters)})

        done = ComicIssue.objects.get(user=self.user, item__media_id="301")
        self.assertEqual(done.item.source, Sources.COMICVINE.value)
        self.assertEqual(done.status, Status.COMPLETED.value)
        self.assertEqual(done.progress, 20)
        partial = ComicIssue.objects.get(user=self.user, item__media_id="302")
        self.assertEqual(partial.status, Status.IN_PROGRESS.value)
        self.assertEqual(partial.progress, 5)
        self.assertFalse(Item.objects.filter(media_id="303").exists())
        self.assertEqual(counts[MediaTypes.COMIC_ISSUE.value], 2)

    def test_comic_issue_read_date_is_updated_on_a_later_sync(self):
        series = _series(
            2,
            name="Saga",
            latestReadDate="2026-09-20T12:00:00Z",
        )
        chapters = [
            _chapter(
                21,
                pages_read=20,
                number=1,
                comicVineId="301",
                lastReadingProgressUtc="2026-09-19T12:00:00Z",
            ),
        ]
        self._sync([series], {2: _detail(COMIC, chapters)})

        self.account.last_sync_at = None
        self.account.save(update_fields=["last_sync_at"])
        chapters[0]["lastReadingProgressUtc"] = "2026-09-21T12:00:00Z"
        self._sync([series], {2: _detail(COMIC, chapters)})

        issue = ComicIssue.objects.get(user=self.user, item__media_id="301")
        self.assertEqual(
            issue.end_date,
            datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        )

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita.services.get_media_metadata")
    def test_comic_ids_enrich_items_and_track_the_series(
        self,
        mock_metadata,
    ):
        series = _series(2, name="Saga", pages=40, pages_read=40, comicVineId="900")
        chapters = [
            _chapter(21, pages_read=20, number=1, comicVineId="301"),
            _chapter(22, pages_read=20, number=2, comicVineId="302"),
        ]
        mock_metadata.side_effect = lambda media_type, media_id, source, **kwargs: {
            "media_id": media_id,
            "source": source,
            "media_type": media_type,
            "title": f"Enriched {media_id}",
            "image": "https://images.example/cover.jpg",
            "synopsis": "Provider synopsis",
            "max_progress": None,
            "max_issue_number": 2,
            "details": {"publisher": "Example Comics"},
        }

        self._sync([series], {2: _detail(COMIC, chapters)})

        comic = Comic.objects.get(user=self.user)
        self.assertEqual(comic.item.media_id, "900")
        self.assertEqual(comic.progress, 2)
        self.assertEqual(comic.status, Status.COMPLETED.value)
        issue = ComicIssue.objects.get(user=self.user, item__media_id="301")
        self.assertEqual(issue.item.title, "Enriched 301")
        self.assertEqual(issue.item.synopsis, "Provider synopsis")
        self.assertEqual(issue.item.publishers, "Example Comics")
        self.assertGreaterEqual(mock_metadata.call_count, 3)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita.services.get_media_metadata")
    def test_comicvine_urls_provide_series_and_issue_ids(self, mock_metadata):
        series = _series(
            2,
            name="Saga",
            pages=40,
            pages_read=20,
            comicVineId="https://comicvine.gamespot.com/volume/4050-900/",
        )
        chapters = [
            _chapter(
                21,
                pages_read=20,
                number=1,
                comicVineId="https://comicvine.gamespot.com/issue/4000-301/",
            ),
        ]
        mock_metadata.side_effect = lambda media_type, media_id, source, **kwargs: {
            "media_id": media_id,
            "source": source,
            "media_type": media_type,
            "title": f"Enriched {media_id}",
            "image": "https://images.example/cover.jpg",
            "synopsis": "Provider synopsis",
            "max_progress": None,
            "max_issue_number": 1,
            "details": {},
        }

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertTrue(
            Comic.objects.filter(user=self.user, item__media_id="900").exists(),
        )
        self.assertTrue(
            ComicIssue.objects.filter(
                user=self.user,
                item__media_id="301",
            ).exists(),
        )
        self.assertEqual(
            mock_metadata.call_args_list[0].args[:2],
            (MediaTypes.COMIC.value, "900"),
        )

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita.services.get_media_metadata")
    def test_comicvine_links_from_metadata_endpoint_provide_ids(self, mock_metadata):
        series = _series(2, name="Saga", pages=40, pages_read=20)
        chapters = [_chapter(21, pages_read=20, number=1)]
        mock_metadata.side_effect = lambda media_type, media_id, source, **kwargs: {
            "media_id": media_id,
            "source": source,
            "media_type": media_type,
            "title": f"Enriched {media_id}",
            "image": "https://images.example/cover.jpg",
            "synopsis": "Provider synopsis",
            "max_progress": None,
            "max_issue_number": 1,
            "details": {},
        }
        fake = FakeKavita([series], {2: _detail(COMIC, chapters)})
        fake.metadata[2] = {
            "webLinks": "https://comicvine.gamespot.com/volume/4050-900/",
        }
        fake.chapter_metadata[21] = {
            "comicVineId": None,
            "webLinks": "https://comicvine.gamespot.com/issue/4000-301/",
        }
        with patch("integrations.imports.kavita.request_json", side_effect=fake):
            kavita.importer(None, self.user, "new")

        self.assertTrue(
            Comic.objects.filter(user=self.user, item__media_id="900").exists()
        )
        self.assertTrue(
            ComicIssue.objects.filter(
                user=self.user,
                item__media_id="301",
            ).exists(),
        )

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch(
        "integrations.imports.kavita._search_issue_id",
        return_value="301",
    )
    @patch(
        "integrations.imports.kavita._search_volume_id",
        return_value="900",
    )
    @patch("integrations.imports.kavita.services.get_media_metadata")
    def test_comic_search_fallback_resolves_series_and_issue(
        self,
        mock_metadata,
        mock_volume,
        mock_issue,
    ):
        series = _series(2, name="Saga", pages=40, pages_read=20)
        chapters = [_chapter(21, pages_read=20, number=1)]
        mock_metadata.return_value = {
            "title": "Saga",
            "image": "https://images.example/cover.jpg",
            "synopsis": "Provider synopsis",
            "max_progress": None,
            "max_issue_number": 1,
            "details": {},
        }

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertTrue(
            Comic.objects.filter(user=self.user, item__media_id="900").exists(),
        )
        self.assertTrue(
            ComicIssue.objects.filter(user=self.user, item__media_id="301").exists(),
        )
        mock_volume.assert_called_once_with("Saga", self.user)
        mock_issue.assert_called_once_with("Saga", "1", self.user)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch(
        "integrations.imports.kavita._volume_issue_id",
        side_effect=ProviderAPIError("comicvine", requests.ConnectionError()),
    )
    @patch(
        "integrations.imports.kavita._search_issue_id",
        side_effect=ProviderAPIError("comicvine", requests.ConnectionError()),
    )
    def test_comic_provider_outage_skips_issue_without_creating_manual_item(
        self,
        _mock_volume_issue,
        _mock_issue,
    ):
        series = _series(2, name="Saga", comicVineId="900")
        chapters = [_chapter(21, pages_read=20, number=1)]

        counts, warnings = self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(
            ComicIssue.objects.filter(user=self.user).exists(),
        )
        self.assertNotIn("Saga #1", Item.objects.values_list("title", flat=True))
        self.assertEqual(counts["skipped"], 2)
        self.assertIn("Comic Vine unavailable; skipped Kavita issue Saga #1", warnings)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita.services.get_media_metadata")
    @patch("integrations.imports.kavita._volume_issue_id", return_value="301")
    def test_known_volume_resolves_issue_by_number(
        self,
        mock_volume_issue,
        mock_metadata,
    ):
        series = _series(
            2,
            name="Saga",
            comicVineId="900",
            pages=20,
            pages_read=20,
        )
        chapters = [_chapter(21, pages_read=20, number=1)]
        mock_metadata.side_effect = lambda media_type, media_id, source, **kwargs: {
            "media_id": media_id,
            "source": source,
            "media_type": media_type,
            "title": f"Enriched {media_id}",
            "image": "https://images.example/cover.jpg",
            "synopsis": "Provider synopsis",
            "max_progress": None,
            "max_issue_number": 1,
            "details": {},
        }

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertTrue(
            ComicIssue.objects.filter(user=self.user, item__media_id="301").exists(),
        )
        mock_volume_issue.assert_called_once_with("900", "1", self.user)

    @patch("integrations.imports.kavita._search_volume_id", return_value=None)
    @patch("integrations.imports.kavita._search_issue_id", return_value=None)
    def test_unmatched_comic_uses_manual_items_as_last_fallback(
        self,
        _mock_issue,
        _mock_volume,
    ):
        series = _series(2, name="Unmatched Saga")
        chapters = [_chapter(21, pages_read=20, number=1)]

        counts, _warnings = self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(Comic.objects.filter(user=self.user).exists())
        issue = ComicIssue.objects.get(user=self.user)
        self.assertEqual(issue.item.source, Sources.MANUAL.value)
        self.assertEqual(issue.item.title, "Unmatched Saga #1")
        self.assertEqual(counts["created"], 1)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita._search_issue_id", return_value=None)
    @patch("integrations.imports.kavita._search_volume_id", return_value=None)
    def test_unmatched_comic_issue_uses_manual_fallback_after_provider_matching(
        self,
        _mock_volume,
        _mock_issue,
    ):
        series = _series(2, name="Absolute Superman")
        chapters = [_chapter(21, pages_read=20, number=1)]

        self._sync([series], {2: _detail(COMIC, chapters)})

        issue = ComicIssue.objects.get(user=self.user)
        self.assertEqual(issue.item.source, Sources.MANUAL.value)
        self.assertEqual(issue.item.title, "Absolute Superman #1")
        self.assertFalse(
            Item.objects.filter(
                source=Sources.COMICVINE.value,
                media_type=MediaTypes.COMIC_ISSUE.value,
            ).exists(),
        )

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita._volume_issue_id", return_value=None)
    @patch("integrations.imports.kavita._search_volume_id", return_value="900")
    def test_known_comic_volume_does_not_create_manual_issue_on_unresolved_number(
        self,
        _mock_volume_search,
        _mock_issue,
    ):
        series = _series(2, name="Absolute Superman")
        chapters = [_chapter(21, pages_read=20, number=9)]

        counts, _warnings = self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(ComicIssue.objects.filter(user=self.user).exists())
        self.assertFalse(Item.objects.filter(title="Absolute Superman #9").exists())
        self.assertEqual(counts["skipped"], 2)

    def test_existing_comic_issue_title_is_reused_before_manual_fallback(self):
        existing = Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        series = _series(2, name="Saga", comicVineId="900")
        chapters = [_chapter(21, pages_read=20, number=1)]

        self._sync([series], {2: _detail(COMIC, chapters)})

        issue = ComicIssue.objects.get(user=self.user)
        self.assertEqual(issue.item_id, existing.id)
        self.assertEqual(
            Item.objects.filter(
                media_type=MediaTypes.COMIC_ISSUE.value,
                title="Saga #1",
            ).count(),
            1,
        )

    def test_explicit_comic_vine_id_beats_a_same_titled_issue_from_another_volume(
        self,
    ):
        other = Item.objects.create(
            media_id="111",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        series = _series(2, name="Saga")
        chapters = [_chapter(21, pages_read=20, number=1, comicVineId="4000-222")]

        self._sync([series], {2: _detail(COMIC, chapters)})

        issue = ComicIssue.objects.get(user=self.user)
        self.assertEqual(issue.item.media_id, "222")
        self.assertNotEqual(issue.item_id, other.id)

    def test_matching_comic_vine_id_reuses_the_same_titled_issue(self):
        existing = Item.objects.create(
            media_id="222",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )
        series = _series(2, name="Saga")
        chapters = [_chapter(21, pages_read=20, number=1, comicVineId="4000-222")]

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertEqual(ComicIssue.objects.get(user=self.user).item_id, existing.id)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita._volume_issue_id")
    def test_comic_vine_rate_limit_skips_issue_instead_of_aborting_import(
        self,
        mock_volume_issue,
    ):
        response = requests.Response()
        response.status_code = 429
        mock_volume_issue.side_effect = ProviderAPIError(
            "comicvine",
            requests.HTTPError(response=response),
        )
        series = _series(2, name="Saga", comicVineId="900")
        chapters = [_chapter(21, pages_read=20, number=1)]

        counts, warnings = self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(ComicIssue.objects.filter(user=self.user).exists())
        self.assertEqual(counts["skipped"], 2)
        self.assertIn("Comic Vine unavailable; skipped Kavita issue Saga #1", warnings)

    @patch("integrations.imports.kavita.settings.TESTING", False)
    @patch("integrations.imports.kavita._volume_issue_id", return_value="1114005")
    @patch("integrations.imports.kavita.services.get_media_metadata")
    def test_linked_manual_issue_is_upgraded_to_provider_item(
        self,
        mock_metadata,
        _mock_volume_issue,
    ):
        manual = Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Absolute Superman #8",
        )
        KavitaLink.objects.create(
            user=self.user,
            kavita_key="chapter:665",
            item=manual,
        )
        mock_metadata.return_value = {
            "media_id": "1114005",
            "source": Sources.COMICVINE.value,
            "media_type": MediaTypes.COMIC_ISSUE.value,
            "title": "Absolute Superman #8",
            "image": "cover.jpg",
            "synopsis": "Synopsis",
            "max_progress": None,
            "details": {},
        }
        series = _series(2, name="Absolute Superman", comicVineId="160860")
        chapters = [_chapter(665, pages_read=26, number=8)]

        self._sync([series], {2: _detail(COMIC, chapters)})

        self.assertFalse(
            ComicIssue.objects.filter(user=self.user, item=manual).exists()
        )
        self.assertTrue(
            ComicIssue.objects.filter(
                user=self.user, item__media_id="1114005"
            ).exists(),
        )
        manual.refresh_from_db()
        self.assertFalse(KavitaLink.objects.filter(item=manual).exists())

    def test_book_is_matched_by_isbn_and_tracks_pages(self):
        item = Item.objects.create(
            media_id="hc-1",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
            isbn=["9780441172719"],
        )
        Book.objects.create(user=self.user, item=item, status=Status.PLANNING.value)
        series = _series(3, name="A totally different title", pages=500, pages_read=120)
        chapters = [_chapter(31, pages=500, pages_read=120, isbn="978-0-441-17271-9")]

        self._sync([series], {3: _detail(BOOK, chapters)})

        entry = Book.objects.get(user=self.user, item=item)
        self.assertEqual(entry.progress, 120)
        self.assertEqual(entry.status, Status.IN_PROGRESS.value)

    def test_held_status_is_kept(self):
        item = Item.objects.create(
            media_id="13",
            source=Sources.MAL.value,
            media_type=MediaTypes.MANGA.value,
            title="One Piece",
        )
        Manga.objects.create(user=self.user, item=item, status=Status.PAUSED.value)

        self._sync([_series(1, malId=13)], {1: _detail(MANGA, [])})

        self.assertEqual(
            Manga.objects.get(user=self.user, item=item).status,
            Status.PAUSED.value,
        )

    def test_incremental_sync_skips_series_not_read_since(self):
        self._sync([_series(1, malId=13)], {1: _detail(MANGA, [])})
        self.account.refresh_from_db()
        self.assertIsNotNone(self.account.last_sync_at)

        self._sync([_series(1, malId=13)], {})

        self.assertNotIn(
            "/api/Series/series-detail",
            [path for _method, path, _kwargs in self.fake.calls],
        )

    def test_series_read_progress_filter_and_paging(self):
        self._sync([], {})

        _method, _path, kwargs = self.fake.calls[1]
        self.assertEqual(kwargs["json"]["statements"][0]["value"], "0")
        self.assertEqual(kwargs["params"], {"PageNumber": 1, "PageSize": 100})

    def test_rejected_key_marks_the_account_broken(self):
        response = MagicMock(status_code=401)
        with (
            patch(
                "integrations.imports.reading_server.requests.post",
                return_value=response,
            ),
            self.assertRaises(helpers.ConnectionAuthError),
        ):
            kavita.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertNotIn("kavita-key", self.account.last_error_message)

    def test_timeout_does_not_mark_the_account_broken(self):
        with (
            patch(
                "integrations.imports.reading_server.requests.post",
                side_effect=requests.Timeout("slow"),
            ),
            self.assertRaises(helpers.MediaImportError),
        ):
            kavita.importer(None, self.user, "new")

        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertNotIn("kavita-key", self.account.last_error_message)

    def test_authenticate_without_a_token_is_treated_as_a_rejected_key(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"username": "x"}
        with (
            patch(
                "integrations.imports.reading_server.requests.post",
                return_value=response,
            ),
            self.assertRaises(helpers.ConnectionAuthError),
        ):
            kavita.importer(None, self.user, "new")


class KavitaViewTests(TestCase):
    """Cover connecting, syncing and disconnecting from the Import page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="kavita-viewer")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_kavita.delay")
    @patch("integrations.views.KavitaClient.healthcheck")
    def test_connect_creates_schedule_and_queues_import(
        self,
        mock_healthcheck,
        mock_delay,
    ):
        response = self.client.post(
            reverse("kavita_connect"),
            {
                "base_url": "https://kavita.local:5000",
                "api_key": "kavita-key",
                "sync_interval_minutes": "30",
            },
        )

        self.assertEqual(response.status_code, 302)
        account = KavitaAccount.objects.get(user=self.user)
        self.assertEqual(helpers.decrypt(account.api_key), "kavita-key")
        task = PeriodicTask.objects.get(task="Import from Kavita (Recurring)")
        self.assertEqual(task.interval.every, 30)
        self.assertIn(f'"user_id": {self.user.id}', task.kwargs)
        mock_healthcheck.assert_called_once()
        mock_delay.assert_called_once_with(user_id=self.user.id, mode="new")

    @patch("integrations.views.tasks.import_kavita.delay")
    @patch("integrations.imports.reading_server.requests.post")
    def test_connect_with_bad_key_saves_nothing(self, mock_post, mock_delay):
        mock_post.return_value = MagicMock(status_code=401)

        self.client.post(
            reverse("kavita_connect"),
            {"base_url": "https://kavita.local:5000", "api_key": "wrong"},
        )

        self.assertFalse(KavitaAccount.objects.exists())
        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_kavita.delay")
    @patch("integrations.views.KavitaClient.healthcheck")
    def test_sync_now_queues_and_disconnect_removes_everything(
        self,
        _healthcheck,
        mock_delay,
    ):
        self.client.post(
            reverse("kavita_connect"),
            {"base_url": "https://kavita.local:5000", "api_key": "kavita-key"},
        )
        self.client.post(reverse("import_kavita"))
        self.assertEqual(mock_delay.call_count, 2)

        self.client.post(reverse("kavita_disconnect"))

        self.assertFalse(KavitaAccount.objects.exists())
        self.assertFalse(
            PeriodicTask.objects.filter(task="Import from Kavita (Recurring)").exists(),
        )

    def test_sync_now_without_an_account_does_not_queue(self):
        with patch("integrations.views.tasks.import_kavita.delay") as mock_delay:
            self.client.post(reverse("import_kavita"))

        mock_delay.assert_not_called()

    @patch("integrations.views.tasks.import_kavita.delay")
    def test_refresh_now_queues_overwrite_mode(self, mock_delay):
        KavitaAccount.objects.create(
            user=self.user,
            base_url="https://kavita.local:5000",
            api_key=helpers.encrypt("kavita-key"),
        )

        self.client.post(reverse("refresh_kavita"))

        mock_delay.assert_called_once_with(user_id=self.user.id, mode="overwrite")

    def test_import_page_shows_kavita_and_komga(self):
        response = self.client.get(reverse("import_data"))

        self.assertContains(
            response,
            "Sync book, comic and manga reading progress from Kavita.",
        )
        self.assertContains(response, reverse("kavita_connect"))
        self.assertContains(response, reverse("komga_connect"))


class ProviderItemRaceTests(TestCase):
    """Cover two workers creating the same Comic Vine item."""

    def test_losing_the_create_race_returns_the_existing_item(self):
        user = get_user_model().objects.create_user(username="race-user")
        existing = Item.objects.create(
            media_id="222",
            source=Sources.COMICVINE.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title="Saga #1",
        )

        # The lookup ran before the other worker's row was committed.
        with patch("integrations.imports.kavita.find_item_across_buckets") as find:
            find.return_value = None
            item = kavita._provider_item(
                "222",
                MediaTypes.COMIC_ISSUE,
                "Saga #1",
                user,
                enrich=False,
            )

        self.assertEqual(item.pk, existing.pk)
        self.assertEqual(Item.objects.filter(media_id="222").count(), 1)


class ComicVineProviderErrorTests(SimpleTestCase):
    """Cover which Comic Vine failures the sync treats as temporary."""

    @staticmethod
    def _error(status_code):
        response = requests.Response()
        response.status_code = status_code
        return ProviderAPIError("comicvine", requests.HTTPError(response=response))

    def test_transient_failures_count_as_unavailable(self):
        for status_code in (408, 429, 500, 503):
            with self.subTest(status_code=status_code):
                self.assertTrue(kavita._provider_unavailable(self._error(status_code)))
        self.assertTrue(
            kavita._provider_unavailable(
                ProviderAPIError("comicvine", requests.ConnectionError()),
            ),
        )

    def test_permanent_failures_stay_fatal(self):
        for status_code in (400, 401, 403, 404):
            with self.subTest(status_code=status_code):
                self.assertFalse(kavita._provider_unavailable(self._error(status_code)))

    @patch("integrations.imports.kavita.comicvine.get_volume_issues")
    def test_volume_lookup_reads_every_page_of_issues(self, mock_issues):
        first_page = [
            {"media_id": str(n), "issue_number": str(n)} for n in range(1, 101)
        ]
        second_page = [{"media_id": "9101", "issue_number": "101"}]
        mock_issues.side_effect = [first_page, second_page]

        issue_id = kavita._volume_issue_id("900", "101", None)

        self.assertEqual(issue_id, "9101")
        self.assertEqual(
            [call.kwargs["offset"] for call in mock_issues.call_args_list],
            [0, 100],
        )

    @patch("integrations.imports.kavita.comicvine.get_volume_issues")
    def test_volume_lookup_stops_after_a_short_page(self, mock_issues):
        mock_issues.return_value = [{"media_id": "5", "issue_number": "5"}]

        self.assertEqual(kavita._volume_issue_id("900", "5", None), "5")
        mock_issues.assert_called_once()
