"""Batched outbound delivery: dated plays, statuses, timing, and safe retries.

A destination such as WeTrakr takes many writes in one request and keeps each
play as a dated event. What these tests guard is the damage that shape allows:
a whole imported library sent as new activity, a rewatch replaced by a later
one, a retried request that becomes a second play, and a delivery stranded
because a request failed half way.
"""

import datetime
import logging
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
    WatchStateOrigin,
)
from app.services.watch_state import importing_watch_state, record_state_change
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    CAPABILITY_RATING_PUSH,
    CAPABILITY_STATUS_PUSH,
    OutboundDeliveryStatus,
    OutboundStateDelivery,
    SyncClientKind,
    SyncDeliverySchedule,
    SyncDirection,
)
from integrations.state import outbound
from integrations.state.adapters.base import (
    BATCH_DELIVERED,
    BATCH_FAILED,
    BATCH_RETRY,
    BATCH_SKIPPED,
    BatchResult,
    TerminalAdapterError,
    TransientAdapterError,
)
from integrations.state.identity import activate_binding, get_or_create_binding


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


def _dt(day, hour=12):
    return datetime.datetime(2026, 5, day, hour, tzinfo=datetime.UTC)


class FakeBatchAdapter:
    """A batch destination that records every request it is sent."""

    CAPABILITIES = frozenset(
        {CAPABILITY_PLAY_PUSH, CAPABILITY_STATUS_PUSH, CAPABILITY_RATING_PUSH},
    )
    BATCH_SIZE = 3
    ACCEPTS_IMPORTED_CHANGES = False

    def __init__(self):
        """Start with every item accepted."""
        self.requests = []
        self.error = None
        self.outcomes = {}

    def resolve_external_id(self, item):
        """Resolve every item to its TMDb id."""
        return item.media_id

    def normalize_rating(self, score):
        """Pass the score through."""
        return score

    def write_batch(self, items, *, idempotency_key):
        """Record the request, then fail or answer per item."""
        self.requests.append((idempotency_key, items))
        if self.error is not None:
            raise self.error
        return [
            self.outcomes.get(
                item.delivery_id,
                BatchResult(BATCH_DELIVERED, receipt=f"play-{item.delivery_id}"),
            )
            for item in items
        ]


class BatchTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.item = self._movie_item("3000")
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.WETRAKR.value,
            instance_key="wetrakr",
            profile_key="account-1",
        )
        activate_binding(
            self.binding,
            capabilities=[
                CAPABILITY_PLAY_PUSH,
                CAPABILITY_STATUS_PUSH,
                CAPABILITY_RATING_PUSH,
            ],
            directions=[SyncDirection.OUTBOUND.value],
        )
        self.adapter = FakeBatchAdapter()
        patcher = patch.object(outbound, "get_adapter", return_value=self.adapter)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _movie_item(self, media_id):
        item, _ = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": f"Film {media_id}"},
        )
        return item

    def _play(self, *, play_count=1, day=1, item=None, origin_key="local"):
        return record_state_change(
            self.user,
            item or self.item,
            watched=True,
            play_count=play_count,
            watched_at=_dt(day),
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key=origin_key,
        ).change

    def _make_due(self):
        OutboundStateDelivery.objects.update(next_attempt_at=None)

    def _deliveries(self, operation=None):
        deliveries = OutboundStateDelivery.objects.filter(binding=self.binding)
        if operation:
            deliveries = deliveries.filter(operation=operation)
        return deliveries.order_by("pk")


class PlayEnqueueTests(BatchTestCase):
    def test_a_new_play_is_queued_with_its_own_date(self):
        self._play(day=3)

        delivery = self._deliveries("play").get()
        self.assertEqual(delivery.payload["watched_at"], _dt(3).isoformat())
        self.assertEqual(delivery.status, OutboundDeliveryStatus.PENDING.value)

    def test_a_rewatch_is_a_second_play_not_a_replacement(self):
        self._play(play_count=1, day=1)
        self._play(play_count=2, day=5)

        deliveries = self._deliveries("play")
        self.assertEqual(deliveries.count(), 2)
        self.assertFalse(
            deliveries.filter(status=OutboundDeliveryStatus.SUPERSEDED.value).exists(),
        )

    def test_changing_a_date_is_not_another_play(self):
        self._play(play_count=1, day=1)
        self._play(play_count=1, day=2)

        self.assertEqual(self._deliveries("play").count(), 1)

    def test_an_unwatch_queues_no_play(self):
        self._play()
        record_state_change(
            self.user,
            self.item,
            watched=False,
            play_count=0,
            origin_kind=WatchStateOrigin.LOCAL_UI.value,
            origin_key="local",
        )

        self.assertEqual(self._deliveries("play").count(), 1)

    def test_no_play_without_the_approved_capability(self):
        activate_binding(
            self.binding,
            capabilities=[CAPABILITY_STATUS_PUSH],
            directions=[SyncDirection.OUTBOUND.value],
        )

        self._play()

        self.assertFalse(self._deliveries("play").exists())

    def test_an_imported_library_is_never_queued(self):
        """The reason this destination opts out of imports."""
        with importing_watch_state():
            for number, day in (("3000", 1), ("3001", 2)):
                Movie.objects.create(
                    item=self._movie_item(number),
                    user=self.user,
                    status=Status.COMPLETED.value,
                    end_date=_dt(day),
                )

        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_the_same_play_made_in_the_app_is_queued(self):
        self._play()

        self.assertEqual(self._deliveries("play").count(), 1)

    def test_a_play_reported_by_the_destination_is_not_sent_back(self):
        self._play(origin_key=self.binding.origin_key)

        self.assertFalse(OutboundStateDelivery.objects.exists())


class ScheduleTests(BatchTestCase):
    def test_live_deliveries_wait_only_a_short_window(self):
        before = timezone.now()
        self._play()

        wait = self._deliveries().get().next_attempt_at - before
        self.assertLessEqual(wait.total_seconds(), outbound.LIVE_BATCH_WINDOW_SECONDS + 5)
        self.assertGreater(wait.total_seconds(), 0)

    def test_hourly_deliveries_wait_for_the_next_hour(self):
        now = _dt(1, hour=10).replace(minute=25)

        self.assertEqual(
            outbound.release_time(SyncDeliverySchedule.HOURLY.value, now),
            _dt(1, hour=11),
        )

    def test_daily_deliveries_wait_for_the_next_midnight(self):
        self.assertEqual(
            outbound.release_time(SyncDeliverySchedule.DAILY.value, _dt(1, hour=23)),
            _dt(2, hour=0),
        )

    def test_a_held_delivery_is_not_sent_before_its_time(self):
        outbound.set_delivery_schedule(self.binding, SyncDeliverySchedule.DAILY.value)
        self._play()

        self.assertEqual(outbound.flush_binding(self.binding.pk), 0)
        self.assertEqual(self.adapter.requests, [])
        self.assertEqual(
            self._deliveries().get().status,
            OutboundDeliveryStatus.PENDING.value,
        )

    def test_switching_to_live_releases_what_was_waiting(self):
        outbound.set_delivery_schedule(self.binding, SyncDeliverySchedule.DAILY.value)
        self._play()

        outbound.set_delivery_schedule(self.binding, SyncDeliverySchedule.LIVE.value)

        wait = self._deliveries().get().next_attempt_at - timezone.now()
        self.assertLessEqual(wait.total_seconds(), outbound.LIVE_BATCH_WINDOW_SECONDS)


    def test_changing_the_schedule_does_not_shorten_a_backoff_the_provider_asked_for(self):
        self._play()
        backoff = timezone.now() + datetime.timedelta(hours=2)
        OutboundStateDelivery.objects.update(attempts=1, next_attempt_at=backoff)

        outbound.set_delivery_schedule(self.binding, SyncDeliverySchedule.LIVE.value)

        self.assertEqual(self._deliveries().get().next_attempt_at, backoff)


class FlushTests(BatchTestCase):
    def test_everything_due_leaves_in_one_request(self):
        self._play(item=self._movie_item("3001"))
        self._play(item=self._movie_item("3002"))
        self._make_due()

        sent = outbound.flush_binding(self.binding.pk)

        self.assertEqual(sent, 2)
        self.assertEqual(len(self.adapter.requests), 1)
        self.assertEqual(
            set(self._deliveries().values_list("status", flat=True)),
            {OutboundDeliveryStatus.DELIVERED.value},
        )

    def test_the_providers_receipt_is_kept_on_the_delivery(self):
        self._play()
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        delivery = self._deliveries().get()
        self.assertEqual(delivery.payload["receipt"], f"play-{delivery.pk}")
        self.assertEqual(delivery.payload["watched_at"], _dt(1).isoformat())

    def test_a_flush_records_when_it_last_sent(self):
        self._play()
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        self.binding.refresh_from_db()
        self.assertIsNotNone(self.binding.last_flushed_at)

    def test_a_flush_of_nothing_does_not_call_the_provider(self):
        self.assertEqual(outbound.flush_binding(self.binding.pk), 0)
        self.assertEqual(self.adapter.requests, [])

    def test_a_request_never_exceeds_the_providers_batch_size(self):
        for number in range(7):
            self._play(item=self._movie_item(f"4{number:03d}"))
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        sizes = [len(items) for _, items in self.adapter.requests]
        self.assertEqual(sizes, [3, 3, 1])

    def test_two_plays_of_one_item_are_sent_in_order_across_requests(self):
        self._play(play_count=1, day=1)
        self._play(play_count=2, day=5)
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        dates = [
            items[0].payload["watched_at"] for _, items in self.adapter.requests
        ]
        self.assertEqual(dates, [_dt(1).isoformat(), _dt(5).isoformat()])
        self.assertFalse(
            self._deliveries().exclude(
                status=OutboundDeliveryStatus.DELIVERED.value,
            ).exists(),
        )

    def test_an_unresolvable_item_is_skipped_and_the_rest_still_sent(self):
        good = self._movie_item("3001")
        self._play(item=good)
        self._play(item=self._movie_item("3002"))
        self._make_due()
        real = self.adapter.resolve_external_id
        self.adapter.resolve_external_id = lambda item: (
            None if item.media_id == "3002" else real(item)
        )

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(len(self.adapter.requests[0][1]), 1)
        self.assertEqual(
            self._deliveries().filter(item__media_id="3002").get().status,
            OutboundDeliveryStatus.SKIPPED.value,
        )

    def test_a_binding_that_is_switched_off_sends_nothing(self):
        self._play()
        self._make_due()
        self.binding.kill_switch = True
        self.binding.save()

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(self.adapter.requests, [])
        self.assertEqual(
            self._deliveries().get().status,
            OutboundDeliveryStatus.SKIPPED.value,
        )


class OutcomeTests(BatchTestCase):
    def _one_per_outcome(self):
        deliveries = []
        for number in range(4):
            self._play(item=self._movie_item(f"5{number:03d}"))
        self._make_due()
        deliveries = list(self._deliveries())
        self.adapter.outcomes = {
            deliveries[0].pk: BatchResult(BATCH_SKIPPED, error="not found"),
            deliveries[1].pk: BatchResult(BATCH_FAILED, error="rejected"),
            deliveries[2].pk: BatchResult(BATCH_RETRY, error="try later"),
        }
        outbound.flush_binding(self.binding.pk)
        return [OutboundStateDelivery.objects.get(pk=d.pk) for d in deliveries]

    def test_each_item_gets_its_own_outcome(self):
        skipped, failed, retry, delivered = self._one_per_outcome()

        self.assertEqual(skipped.status, OutboundDeliveryStatus.SKIPPED.value)
        self.assertEqual(skipped.last_error_message, "not found")
        self.assertEqual(failed.status, OutboundDeliveryStatus.FAILED.value)
        self.assertEqual(retry.status, OutboundDeliveryStatus.PENDING.value)
        self.assertEqual(delivered.status, OutboundDeliveryStatus.DELIVERED.value)

    def test_a_retry_outcome_waits_before_the_next_attempt(self):
        retry = self._one_per_outcome()[2]

        self.assertGreater(retry.next_attempt_at, timezone.now())

    def test_a_result_the_provider_left_out_is_retried_not_lost(self):
        self._play()
        self._make_due()
        self.adapter.write_batch = lambda items, *, idempotency_key: []

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(
            self._deliveries().get().status,
            OutboundDeliveryStatus.PENDING.value,
        )


class FailureTests(BatchTestCase):
    def test_a_transient_failure_retries_every_item_later(self):
        self._play()
        self._make_due()
        self.adapter.error = TransientAdapterError("down")

        outbound.flush_binding(self.binding.pk)

        delivery = self._deliveries().get()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.PENDING.value)
        self.assertEqual(delivery.attempts, 1)
        self.assertGreater(delivery.next_attempt_at, timezone.now())

    def test_the_wait_the_provider_asks_for_is_honoured(self):
        self._play()
        self._make_due()
        self.adapter.error = TransientAdapterError("slow down", retry_after=7200)

        outbound.flush_binding(self.binding.pk)

        wait = self._deliveries().get().next_attempt_at - timezone.now()
        self.assertGreater(wait.total_seconds(), 7000)

    def test_a_terminal_failure_fails_every_item(self):
        self._play()
        self._make_due()
        self.adapter.error = TerminalAdapterError("revoked")

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(
            self._deliveries().get().status,
            OutboundDeliveryStatus.FAILED.value,
        )

    def test_an_unexpected_error_does_not_strand_the_rows_in_flight(self):
        self._play()
        self._make_due()
        self.adapter.error = RuntimeError("boom")

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(
            self._deliveries().get().status,
            OutboundDeliveryStatus.PENDING.value,
        )

    def test_a_retried_set_is_sent_under_the_same_key(self):
        """The provider can only recognise a repeat if the key is the same."""
        self._play(item=self._movie_item("3001"))
        self._play(item=self._movie_item("3002"))
        self._make_due()
        self.adapter.error = TransientAdapterError("down")
        outbound.flush_binding(self.binding.pk)
        self.adapter.error = None
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        first_key, second_key = (key for key, _ in self.adapter.requests)
        self.assertEqual(first_key, second_key)

    def test_retries_that_fall_due_together_keep_the_key_each_was_sent_under(self):
        first, second = self._movie_item("3001"), self._movie_item("3002")
        self.adapter.error = TransientAdapterError("down")
        for item in (first, second):
            self._play(item=item)
            self._make_due()
            outbound.flush_binding(self.binding.pk)
        keys = [key for key, _ in self.adapter.requests]
        self.adapter.error = None
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        sent = self.adapter.requests[len(keys) :]
        self.assertEqual(sorted(key for key, _ in sent), sorted(set(keys)))
        self.assertEqual([len(items) for _, items in sent], [1, 1])

    def test_a_retry_keeps_its_key_when_a_member_has_dropped_out(self):
        first, second = self._movie_item("3001"), self._movie_item("3002")
        self._play(item=first)
        self._play(item=second)
        self._make_due()
        self.adapter.error = TransientAdapterError("down")
        outbound.flush_binding(self.binding.pk)
        original_key = self.adapter.requests[0][0]
        self.adapter.error = None
        self._deliveries().filter(item=second).update(
            status=OutboundDeliveryStatus.SKIPPED.value,
        )
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(self.adapter.requests[1][0], original_key)
        self.assertEqual(len(self.adapter.requests[1][1]), 1)

    def test_a_retry_is_not_mixed_into_new_work(self):
        self._play(item=self._movie_item("3001"))
        self._make_due()
        self.adapter.error = TransientAdapterError("down")
        outbound.flush_binding(self.binding.pk)
        self.adapter.error = None
        self._play(item=self._movie_item("3002"))
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        sizes = [len(items) for _, items in self.adapter.requests[1:]]
        self.assertEqual(sizes, [1, 1])


class StatusAndRatingTests(BatchTestCase):
    def test_saving_a_new_status_queues_it(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        delivery = self._deliveries("status").get()
        self.assertEqual(delivery.payload, {"status": Status.PLANNING.value})

        movie.status = Status.IN_PROGRESS.value
        movie.save()

        newest = self._deliveries("status").latest("target_revision")
        self.assertEqual(newest.payload, {"status": Status.IN_PROGRESS.value})

    def test_only_the_latest_waiting_status_is_kept(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        movie.status = Status.DROPPED.value
        movie.save()

        waiting = self._deliveries("status").filter(
            status=OutboundDeliveryStatus.PENDING.value,
        )
        self.assertEqual(waiting.get().payload, {"status": Status.DROPPED.value})

    def test_saving_without_a_status_change_queues_nothing_new(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        movie.notes = "a note"
        movie.save()

        self.assertEqual(self._deliveries("status").count(), 1)

    def test_imported_statuses_are_not_queued(self):
        with importing_watch_state():
            Movie.objects.create(
                item=self.item,
                user=self.user,
                status=Status.COMPLETED.value,
                end_date=_dt(1),
            )

        self.assertFalse(self._deliveries("status").exists())

    def test_a_rating_travels_in_the_batch_too(self):
        outbound.enqueue_rating_change(self.user, self.item, 8)
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        item = self.adapter.requests[0][1][0]
        self.assertEqual((item.operation, item.rating), ("rating", 8))


class StatusDurabilityTests(BatchTestCase):
    def test_a_status_whose_save_never_landed_is_not_sent(self):
        """The intent is recorded before the write, so a lost write leaves one."""
        outbound.enqueue_status_change(self.user, self.item, Status.DROPPED.value)
        self.assertEqual(self._deliveries("status").count(), 1)
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(self.adapter.requests, [])
        self.assertEqual(
            self._deliveries("status").get().status,
            OutboundDeliveryStatus.SUPERSEDED.value,
        )

    def test_a_status_that_was_written_is_sent(self):
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.DROPPED.value,
        )
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(len(self.adapter.requests), 1)

    def test_a_status_replaced_by_a_write_that_queued_nothing_is_not_sent(self):
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.DROPPED.value,
        )
        Movie.objects.filter(user=self.user, item=self.item).update(
            status=Status.PAUSED.value,
        )
        self._make_due()

        outbound.flush_binding(self.binding.pk)

        self.assertEqual(self.adapter.requests, [])

    def test_a_save_that_leaves_other_fields_alone_queues_no_status(self):
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        movie.status = Status.DROPPED.value

        movie.save(update_fields=["notes"])

        self.assertEqual(self._deliveries("status").count(), 1)


class SweepTests(BatchTestCase):
    def test_an_attempt_left_in_flight_before_the_upgrade_is_sent_again(self):
        """Rows from before ``claimed_at`` existed have no claim time."""
        self._play()
        delivery = self._deliveries().get()
        OutboundStateDelivery.objects.filter(pk=delivery.pk).update(
            status=OutboundDeliveryStatus.IN_FLIGHT.value,
            attempts=1,
            claimed_at=None,
            next_attempt_at=None,
            updated_at=timezone.now() - datetime.timedelta(hours=1),
        )

        outbound.sweep_due_deliveries()

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.DELIVERED.value)


    def test_an_attempt_abandoned_by_a_dead_worker_is_sent_again(self):
        self._play()
        delivery = self._deliveries().get()
        OutboundStateDelivery.objects.filter(pk=delivery.pk).update(
            status=OutboundDeliveryStatus.IN_FLIGHT.value,
            attempts=1,
            claimed_at=timezone.now() - datetime.timedelta(hours=1),
            next_attempt_at=None,
        )

        outbound.sweep_due_deliveries()

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.DELIVERED.value)
        self.assertEqual(delivery.attempts, 2)

    def test_an_attempt_still_running_is_left_alone(self):
        self._play()
        delivery = self._deliveries().get()
        OutboundStateDelivery.objects.filter(pk=delivery.pk).update(
            status=OutboundDeliveryStatus.IN_FLIGHT.value,
            attempts=1,
            claimed_at=timezone.now(),
        )

        outbound.sweep_due_deliveries()

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, OutboundDeliveryStatus.IN_FLIGHT.value)


    def test_the_sweep_flushes_a_batch_binding_once(self):
        self._play(item=self._movie_item("3001"))
        self._play(item=self._movie_item("3002"))
        self._make_due()

        outbound.sweep_due_deliveries()

        self.assertEqual(len(self.adapter.requests), 1)

    def test_the_sweep_leaves_held_deliveries_alone(self):
        outbound.set_delivery_schedule(self.binding, SyncDeliverySchedule.DAILY.value)
        self._play()

        outbound.sweep_due_deliveries()

        self.assertEqual(self.adapter.requests, [])
