"""Regressions for terminal-failure churn in the metadata backfill.

Production evidence (2026-09-14): one startup pass processed 150 items in 144
seconds and 148 of them failed, overwhelmingly MusicBrainz 400/404 for
recording ids that do not exist. Those items can never grow a release date or
a status, so they sorted to the front of both backfill queues - which order by
oldest ``metadata_fetched_at`` - and were re-fetched on every cycle forever.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import tasks, tasks_episode
from app.interactive_requests import INTERACTIVE_REQUEST_CACHE_KEY
from app.models import (
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
)
from app.providers.services import ProviderAPIError, ProviderNotConfiguredError
from app.tasks_backfill_state import (
    RELEASE_BACKFILL_VERSION,
    MalformedItemIdentityError,
    is_terminal_backfill_error,
    reset_backfill_state_for_identity_change,
)


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def _provider_error(status_code):
    error = Exception("provider said no")
    error.response = _Response(status_code)
    return ProviderAPIError(Sources.MUSICBRAINZ.value, error)


def _music_item(media_id="mbid-dead"):
    """A music item that has been fetched once and has no release date."""
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MUSICBRAINZ.value,
        media_type=MediaTypes.MUSIC.value,
        title="Unresolvable Recording",
        metadata_fetched_at=timezone.now(),
    )


class TerminalErrorClassificationTests(TestCase):
    def test_provider_404_is_terminal(self):
        self.assertTrue(is_terminal_backfill_error(_provider_error(404)))

    def test_provider_400_is_terminal(self):
        self.assertTrue(is_terminal_backfill_error(_provider_error(400)))

    def test_provider_5xx_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(503)))

    def test_provider_429_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(429)))

    def test_missing_credentials_is_transient(self):
        """A 401/403 is usually a key the operator can still fix."""
        self.assertFalse(is_terminal_backfill_error(_provider_error(401)))
        self.assertFalse(is_terminal_backfill_error(_provider_error(403)))

    def test_unreachable_provider_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(None)))

    def test_invalid_identifier_is_terminal(self):
        """A season row with no season number is bad data, not an outage."""
        self.assertTrue(
            is_terminal_backfill_error(
                MalformedItemIdentityError("season item missing season_number"),
            ),
        )

    def test_unconfigured_provider_is_transient(self):
        """tvdb._request raises a bare ValueError when credentials are unset.

        Retiring every TVDB item because a key lapsed is exactly the failure
        this classification exists to avoid, so a bare ValueError must not be
        read as "this identifier is wrong".
        """
        self.assertFalse(is_terminal_backfill_error(ValueError("TVDB is not configured")))
        self.assertFalse(
            is_terminal_backfill_error(
                ProviderNotConfiguredError(Sources.TVDB.value, "TVDB is not configured"),
            ),
        )

    def test_an_unanticipated_exception_is_transient(self):
        """Anything this code did not plan for stays retryable.

        Wrongly retrying costs one request; wrongly retiring loses the item
        silently and permanently.
        """
        self.assertFalse(is_terminal_backfill_error(KeyError("results")))
        self.assertFalse(is_terminal_backfill_error(TypeError("NoneType")))
        self.assertFalse(is_terminal_backfill_error(RuntimeError("boom")))


class ReleaseBackfillChurnTests(TestCase):
    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_terminal_failure_drops_out_of_the_release_queue(self):
        item = _music_item()
        self.assertIn(item, tasks._release_items_queryset())

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_provider_error(404),
        ) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertTrue(state.give_up)
        self.assertNotIn(item, tasks._release_items_queryset())

    def test_transient_failure_stays_retryable(self):
        item = _music_item()

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_provider_error(503),
        ) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

            # Backed off, not given up.
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)

        MetadataBackfillState.objects.filter(pk=state.pk).update(
            next_retry_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assertIn(item, tasks._release_items_queryset())

    def test_successful_fetch_without_a_release_date_backs_off_rather_than_repeats(
        self,
    ):
        """The provider answered; it simply has no date. That can change later."""
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", return_value={}) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertEqual(fetch.call_count, 1)
        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)

    def test_backfill_version_bump_reopens_a_terminal_item(self):
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._release_items_queryset())

        with patch(
            "app.tasks.RELEASE_BACKFILL_VERSION",
            RELEASE_BACKFILL_VERSION + 1,
        ):
            self.assertIn(item, tasks._release_items_queryset())

    def test_source_id_change_reopens_a_terminal_item(self):
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._release_items_queryset())

        Item.objects.filter(pk=item.pk).update(media_id="mbid-relinked")
        reset_backfill_state_for_identity_change([item])

        self.assertIn(item, tasks._release_items_queryset())


class StatusBackfillChurnTests(TestCase):
    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_terminal_failure_drops_out_of_the_status_queue(self):
        item = Item.objects.create(
            media_id="999999999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Deleted Upstream",
            release_datetime=timezone.now(),
            metadata_fetched_at=timezone.now(),
        )
        self.assertIn(item, tasks._status_items_queryset())

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._status_items_queryset())


class UnconfiguredProviderStaysRetryableTests(TestCase):
    """End-to-end guard for the bug the classifier fix addresses."""

    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_lapsed_tvdb_credentials_do_not_retire_the_item(self):
        item = Item.objects.create(
            media_id="tvdb-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="A Show",
            metadata_fetched_at=timezone.now(),
        )

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=ValueError("TVDB is not configured"),
        ):
            tasks.backfill_item_metadata_task(batch_size=5)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)

        # Credentials restored: the item comes back once the retry falls due.
        MetadataBackfillState.objects.filter(pk=state.pk).update(
            next_retry_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assertIn(item, tasks._release_items_queryset())


class EpisodeRuntimeTerminalFailureTests(TestCase):
    """A dead TMDB show id must not be re-fetched by every nightly backfill.

    Production evidence (2026-10-20): one install logged 120 TMDB 404s from
    the episode-runtime backfill for TV ids that do not exist. The season
    raised before any per-episode state was written, so the same seasons were
    selected, and failed, again the next night.
    """

    def _episode(self, media_id="3925833", number=1):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=number,
            title=f"Episode {number}",
        )

    def test_404_is_recorded_as_terminal_and_leaves_the_queue(self):
        episode = self._episode()
        season_keys = [("3925833", Sources.TMDB.value, 1)]

        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=_provider_error(404),
        ) as fetch:
            tasks_episode.populate_episode_runtime_data(season_keys)
            tasks_episode.populate_episode_runtime_data(season_keys)

        self.assertEqual(fetch.call_count, 1)
        state = MetadataBackfillState.objects.get(
            item=episode,
            field=MetadataBackfillField.RUNTIME,
        )
        self.assertTrue(state.give_up)
        self.assertTrue(state.terminal)
        self.assertNotIn(
            episode,
            tasks._episode_runtime_items_queryset(),
        )

    def test_transient_provider_error_stays_retryable(self):
        episode = self._episode(media_id="500")
        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=_provider_error(503),
        ):
            tasks_episode.populate_episode_runtime_data(
                [("500", Sources.TMDB.value, 1)],
            )

        state = MetadataBackfillState.objects.get(
            item=episode,
            field=MetadataBackfillField.RUNTIME,
        )
        self.assertFalse(state.give_up)
        self.assertFalse(state.terminal)
        self.assertIsNotNone(state.next_retry_at)

    def test_stale_reset_does_not_reopen_a_terminal_verdict(self):
        episode = self._episode()
        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=_provider_error(404),
        ):
            tasks_episode.populate_episode_runtime_data(
                [("3925833", Sources.TMDB.value, 1)],
            )

        MetadataBackfillState.objects.filter(item=episode).update(
            last_attempt_at=timezone.now() - timezone.timedelta(days=8),
        )

        self.assertEqual(tasks._reset_stale_give_up_episode_runtimes(), 0)
        state = MetadataBackfillState.objects.get(item=episode)
        self.assertTrue(state.give_up)
        self.assertTrue(state.terminal)

    def test_identity_change_reopens_a_terminal_verdict(self):
        episode = self._episode()
        with patch(
            "app.providers.services.get_media_metadata",
            side_effect=_provider_error(404),
        ):
            tasks_episode.populate_episode_runtime_data(
                [("3925833", Sources.TMDB.value, 1)],
            )

        reset_backfill_state_for_identity_change([episode])

        state = MetadataBackfillState.objects.get(item=episode)
        self.assertFalse(state.give_up)
        self.assertFalse(state.terminal)
