"""Regressions for the *unwrapped* provider failure path.

Production evidence (2026-09-20): passes were still reporting 150 processed /
149 errors every fifteen minutes, long after terminal-vs-transient handling
shipped. The cause was a gap between two deliberate designs.

``services.api_request`` re-raises a bare ``requests.exceptions.HTTPError`` for
any 4xx it does not retry, and leaves wrapping to each provider's
``handle_error``. Eleven provider modules have one; musicbrainz, trakt and
tvmaze did not. So a MusicBrainz 404 reached the backfill as a raw
``HTTPError``, which ``is_terminal_backfill_error`` did not recognise, and the
same dead recording ids were retried on every cycle forever.

Every pre-existing test constructs a ``ProviderAPIError`` by hand or patches
``_fetch_item_metadata``, so the raw path had no coverage at all. These tests
exercise the exception forms production actually emitted.
"""

from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import tasks
from app.interactive_requests import INTERACTIVE_REQUEST_CACHE_KEY
from app.models import (
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
)
from app.providers import musicbrainz
from app.providers.services import ProviderAPIError
from app.tasks_backfill_state import is_terminal_backfill_error


def _http_error(status_code):
    """A real ``HTTPError`` carrying a real ``Response``, as requests raises."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError("provider said no", response=response)


def _music_item(media_id="mbid-dead"):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MUSICBRAINZ.value,
        media_type=MediaTypes.MUSIC.value,
        title="Unresolvable Recording",
        metadata_fetched_at=timezone.now(),
    )


def _tmdb_movie(media_id="404404"):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.MOVIE.value,
        title="Unresolvable Movie",
        metadata_fetched_at=timezone.now(),
    )


class RawHTTPErrorClassificationTests(TestCase):
    def test_terminal_status_codes_are_terminal(self):
        for status_code in (400, 404, 410, 422):
            with self.subTest(status_code=status_code):
                self.assertTrue(is_terminal_backfill_error(_http_error(status_code)))

    def test_retryable_status_codes_stay_retryable(self):
        for status_code in (429, 500, 502, 503, 504):
            with self.subTest(status_code=status_code):
                self.assertFalse(is_terminal_backfill_error(_http_error(status_code)))

    def test_an_http_error_without_a_response_stays_retryable(self):
        self.assertFalse(
            is_terminal_backfill_error(requests.exceptions.HTTPError("no response")),
        )

    def test_network_failures_stay_retryable(self):
        for error in (
            requests.exceptions.ConnectionError("dns"),
            requests.exceptions.Timeout("slow"),
            requests.exceptions.RequestException("generic"),
        ):
            with self.subTest(error=type(error).__name__):
                self.assertFalse(is_terminal_backfill_error(error))

    def test_an_unrelated_exception_carrying_a_response_is_not_terminal(self):
        # Matching on a `.response` attribute rather than the concrete type
        # would retire items on any duck-typed exception.
        error = ValueError("TVDB is not configured")
        error.response = requests.Response()
        error.response.status_code = 404
        self.assertFalse(is_terminal_backfill_error(error))


class MusicBrainzErrorWrappingTests(TestCase):
    def test_a_404_is_wrapped_in_the_shared_provider_error(self):
        with patch(
            "app.providers.services.api_request",
            side_effect=_http_error(404),
        ):
            with self.assertRaises(ProviderAPIError) as caught:
                musicbrainz.recording("mbid-dead")

        self.assertEqual(caught.exception.status_code, 404)
        self.assertTrue(is_terminal_backfill_error(caught.exception))

    def test_a_503_is_wrapped_but_stays_retryable(self):
        with patch(
            "app.providers.services.api_request",
            side_effect=_http_error(503),
        ):
            with self.assertRaises(ProviderAPIError) as caught:
                musicbrainz.recording("mbid-flaky")

        self.assertFalse(is_terminal_backfill_error(caught.exception))


class RawHTTPErrorConvergenceTests(TestCase):
    """The end-to-end symptom: a dead id must stop being re-selected."""

    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_a_raw_404_converges_instead_of_rescanning(self):
        # Simulates a provider with no handle_error - trakt and tvmaze still
        # reach the task this way.
        item = _music_item()
        self.assertIn(item, tasks._release_items_queryset())

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_http_error(404),
        ) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

            # The second pass is the one production kept paying for.
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertTrue(state.give_up)
        self.assertNotIn(item, tasks._release_items_queryset())

    def test_a_raw_503_still_backs_off_rather_than_giving_up(self):
        item = _music_item()

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_http_error(503),
        ):
            tasks.backfill_item_metadata_task(batch_size=5)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)


class DiscoverTerminalityTests(TestCase):
    """DISCOVER was recorded without `terminal=`, so it never retired."""

    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_a_terminal_failure_retires_the_discover_field_too(self):
        item = _tmdb_movie()

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_http_error(404),
        ):
            tasks.backfill_item_metadata_task(batch_size=5)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.DISCOVER,
        )
        self.assertTrue(state.give_up)

    def test_a_transient_failure_leaves_discover_retryable(self):
        item = _tmdb_movie(media_id="503503")

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_http_error(503),
        ):
            tasks.backfill_item_metadata_task(batch_size=5)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.DISCOVER,
        )
        self.assertFalse(state.give_up)
