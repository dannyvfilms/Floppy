"""A queued webhook delivered twice must be saved once.

``process_webhook`` acknowledges its broker message only after it finishes
(``acks_late``), so a worker that dies mid-task gets the same message again
from the broker. The redelivery carries the same ``received_at`` and
``event_id`` but runs later: up to the broker's visibility timeout after the
first attempt. These tests run each provider's task twice with the same
arguments, the second time an hour later, and assert the second run adds no
tracking row, play, history row, watch-state change or outbound delivery.

The interrupted case makes the first attempt fail after its first write, as a
killed worker would, then runs the retry and asserts exactly one play.

See ``docs/architecture/webhook-delivery.md`` ("Redelivery").
"""

import json
from datetime import timedelta
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from app import live_playback
from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    MediaTypes,
    Movie,
    PlaybackProgress,
    Season,
    Sources,
    WatchStateChange,
    WatchStateSequence,
)
from integrations import tasks
from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_PUSH_UNPLAYED,
    CAPABILITY_WATCHED_READ,
    OutboundStateDelivery,
    SyncClientKind,
    SyncDirection,
)
from integrations.state import outbound
from integrations.state.identity import activate_binding, get_or_create_binding

# Past the broker's one-hour visibility timeout, when an unacknowledged
# message is handed to another worker.
REDELIVERY_DELAY = timedelta(hours=1, minutes=1)

MOVIE_METADATA = {
    "title": "The Matrix",
    "image": "",
    "max_progress": 1,
    "provider_external_ids": {},
}


def _tv_with_seasons(media_id, season_numbers, *_args, **_kwargs):
    seasons = {
        f"season/{number}": {
            "image": "",
            "episodes": [
                {"episode_number": 1, "runtime": 22},
                {"episode_number": 2, "runtime": 22},
            ],
        }
        for number in season_numbers
    }
    return {
        "media_id": str(media_id),
        "tvdb_id": 303821,
        "title": "Friends",
        "image": "",
        "related": {"seasons": [{"season_number": n} for n in season_numbers]},
        **seasons,
    }


class _OutboundAdapter:
    """Stands in for a provider that accepts every watched-state push."""

    CAPABILITIES = frozenset(
        {
            CAPABILITY_WATCHED_READ,
            CAPABILITY_WATCHED_PUSH_PLAYED,
            CAPABILITY_WATCHED_PUSH_UNPLAYED,
        },
    )


def _tmdb_find(external_id, external_source):
    if (str(external_id), external_source) in {
        ("303821", "tvdb_id"),
        ("tt0583459", "imdb_id"),
    }:
        return {
            "tv_episode_results": [
                {"show_id": 1668, "season_number": 1, "episode_number": 1},
            ],
            "tv_results": [],
            "movie_results": [],
        }
    return {"tv_episode_results": [], "tv_results": [], "movie_results": []}


# One completed play, one partial stop and one rating per provider, in the
# shape each receiver queues. Kodi and Emby send no rating event.
PLEX_MOVIE = {
    "event": "media.scrobble",
    "Account": {"title": "testuser"},
    "Metadata": {
        "type": "movie",
        "title": "The Matrix",
        "ratingKey": "plex-603",
        "duration": 8160000,
        "viewOffset": 7500000,
        "Guid": [{"id": "tmdb://603"}],
    },
}
PLEX_EPISODE = {
    "event": "media.scrobble",
    "Account": {"title": "testuser"},
    "Metadata": {
        "type": "episode",
        "grandparentTitle": "Friends",
        "ratingKey": "plex-ep-1",
        "parentIndex": 1,
        "index": 1,
        "Guid": [
            {"id": "imdb://tt0583459"},
            {"id": "tmdb://85987"},
            {"id": "tvdb://303821"},
        ],
    },
}
PLEX_PARTIAL = {
    "event": "media.stop",
    "Account": {"title": "testuser"},
    "Metadata": {
        **PLEX_MOVIE["Metadata"],
        "viewOffset": 1200000,
    },
}
PLEX_RATING = {
    "event": "media.rate",
    "Account": {"title": "testuser"},
    "Metadata": {
        "type": "movie",
        "title": "The Matrix",
        "ratingKey": "plex-603",
        "userRating": 8,
        "Guid": [{"id": "tmdb://603"}],
    },
}

_JELLYFIN_MOVIE_ITEM = {
    "Id": "jf-603",
    "Name": "The Matrix",
    "Type": "Movie",
    "RunTimeTicks": 8160 * 10_000_000,
    "ProviderIds": {"Tmdb": "603"},
}
JELLYFIN_MOVIE = {
    "Event": "Stop",
    "Item": {**_JELLYFIN_MOVIE_ITEM, "UserData": {"Played": True}},
    "PlaybackPositionTicks": 8160 * 10_000_000,
}
JELLYFIN_EPISODE = {
    "Event": "Stop",
    "Item": {
        "Id": "jf-ep-1",
        "Type": "Episode",
        "Name": "The One Where Monica Gets a Roommate",
        "SeriesName": "Friends",
        "ParentIndexNumber": 1,
        "IndexNumber": 1,
        "ProviderIds": {"Tvdb": "303821", "Imdb": "tt0583459"},
        "UserData": {"Played": True},
    },
}
JELLYFIN_PARTIAL = {
    "Event": "Stop",
    "Item": {**_JELLYFIN_MOVIE_ITEM, "UserData": {"Played": False}},
    "PlaybackPositionTicks": 1200 * 10_000_000,
}
JELLYFIN_RATING = {
    "Event": "UserDataSaved",
    "SaveReason": "UpdateUserRating",
    "Item": {
        **_JELLYFIN_MOVIE_ITEM,
        "UserData": {"Played": True, "Rating": 8},
    },
}

_EMBY_MOVIE_ITEM = {
    "Id": "emby-603",
    "Name": "The Matrix",
    "Type": "Movie",
    "RunTimeTicks": 8160 * 10_000_000,
    "ProviderIds": {"Tmdb": "603"},
}
EMBY_MOVIE = {
    "Event": "playback.stop",
    "Item": _EMBY_MOVIE_ITEM,
    "PlaybackInfo": {
        "PlayedToCompletion": True,
        "PositionTicks": 8160 * 10_000_000,
    },
}
EMBY_EPISODE = {
    "Event": "playback.stop",
    "Item": {
        "Id": "emby-ep-1",
        "Type": "Episode",
        "Name": "The One Where Monica Gets a Roommate",
        "SeriesName": "Friends",
        "ParentIndexNumber": 1,
        "IndexNumber": 1,
        "ProviderIds": {"Tvdb": "303821", "Imdb": "tt0583459"},
    },
    "PlaybackInfo": {"PlayedToCompletion": True},
}
EMBY_PARTIAL = {
    "Event": "playback.stop",
    "Item": _EMBY_MOVIE_ITEM,
    "PlaybackInfo": {
        "PlayedToCompletion": False,
        "PositionTicks": 1200 * 10_000_000,
    },
}

KODI_MOVIE = {
    "event": "end",
    "mediaType": "movie",
    "title": "The Matrix",
    "year": 1999,
    "uniqueIds": {"tmdb": "603", "imdb": "tt0133093", "tvdb": None},
    "duration": 8160,
    "progress": {"time": 8160, "percent": 100.0},
}
KODI_EPISODE = {
    "event": "end",
    "mediaType": "episode",
    "title": "The One Where Monica Gets a Roommate",
    "tvShowTitle": "Friends",
    "season": 1,
    "episode": 1,
    "year": 1994,
    "uniqueIds": {"tmdb": None, "imdb": "tt0583459", "tvdb": "303821"},
    "duration": 1320,
    "progress": {"time": 1320, "percent": 100.0},
}
KODI_PARTIAL = {
    **KODI_MOVIE,
    "event": "stop",
    "progress": {"time": 1200, "percent": 14.7},
}

# Seerr rides the same task: a request adds the title to Planning.
SEERR_REQUEST = {
    "media_type": "movie",
    "media_tmdbid": "604",
    "media_status": "PENDING",
    "requestedBy_username": "alice",
}

CASES = (
    ("plex", "completed movie", PLEX_MOVIE),
    ("plex", "completed episode", PLEX_EPISODE),
    ("plex", "partial stop", PLEX_PARTIAL),
    ("plex", "rating", PLEX_RATING),
    ("jellyfin", "completed movie", JELLYFIN_MOVIE),
    ("jellyfin", "completed episode", JELLYFIN_EPISODE),
    ("jellyfin", "partial stop", JELLYFIN_PARTIAL),
    ("jellyfin", "rating", JELLYFIN_RATING),
    ("emby", "completed movie", EMBY_MOVIE),
    ("emby", "completed episode", EMBY_EPISODE),
    ("emby", "partial stop", EMBY_PARTIAL),
    ("kodi", "completed movie", KODI_MOVIE),
    ("kodi", "completed episode", KODI_EPISODE),
    ("kodi", "partial stop", KODI_PARTIAL),
    ("seerr", "request", SEERR_REQUEST),
)

TRACKED_MODELS = (Movie, Episode, Season, TV, Anime)


def _snapshot(user):
    """Everything a duplicate delivery could add, as comparable values."""
    rows = {
        model.__name__: sorted(
            model.objects.filter(
                **(
                    {"related_season__user": user}
                    if model is Episode
                    else {"user": user}
                )
            ).values_list("pk", flat=True)
        )
        for model in TRACKED_MODELS
    }
    history = {
        model.__name__: model.history.count()
        for model in TRACKED_MODELS
        if hasattr(model, "history")
    }
    progress = list(
        PlaybackProgress.objects.filter(user=user)
        .order_by("pk")
        .values_list("pk", "position_seconds", "completed")
    )
    return {
        "rows": rows,
        "history": history,
        "progress": progress,
        "changes": WatchStateChange.objects.filter(user=user).count(),
        "deliveries": OutboundStateDelivery.objects.filter(user=user).count(),
    }


class WebhookRedeliveryTests(TestCase):
    """Running one queued webhook twice writes it once, for every provider."""

    def setUp(self):
        """Create a user who emits watch-state changes to an outbound binding."""
        cache.clear()
        self.user = get_user_model().objects.create_superuser(
            username="testuser",
            token="test-token",
            plex_usernames="testuser",
        )
        self.user.jellyfin_mark_played_enabled = True
        self.user.jellyseerr_enabled = True
        self.user.jellyseerr_trigger_statuses = "PENDING"
        self.user.save(
            update_fields=[
                "jellyfin_mark_played_enabled",
                "jellyseerr_enabled",
                "jellyseerr_trigger_statuses",
            ]
        )
        WatchStateSequence.objects.update_or_create(
            user=self.user,
            defaults={"emit_changes": True},
        )
        # A second provider that hears about every change, so a duplicate
        # change would show up as a second outbound delivery.
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.GENERIC.value,
            instance_key="redelivery-test",
        )
        activate_binding(
            binding,
            capabilities=[
                CAPABILITY_WATCHED_READ,
                CAPABILITY_WATCHED_PUSH_PLAYED,
                CAPABILITY_WATCHED_PUSH_UNPLAYED,
            ],
            directions=[SyncDirection.OUTBOUND.value],
        )
        # A 30-minute runtime keeps the duplicate-play window shorter than
        # the redelivery delay, so only the receipt time can match the plays.
        Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            runtime_minutes=30,
        )
        for target, kwargs in (
            ("app.providers.tmdb.movie", {"return_value": MOVIE_METADATA}),
            (
                "app.providers.tmdb.tv",
                {"side_effect": lambda media_id: _tv_with_seasons(media_id, [1])},
            ),
            ("app.providers.tvdb.enabled", {"return_value": False}),
            (
                "app.providers.tmdb.search",
                {
                    "return_value": {
                        "results": [
                            {"media_id": "1668", "title": "Friends", "year": 1994},
                        ],
                    },
                },
            ),
            ("app.providers.tmdb.tv_with_seasons", {"side_effect": _tv_with_seasons}),
            ("app.providers.tmdb.find", {"side_effect": _tmdb_find}),
            ("app.live_playback._attach_resolved_image", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(outbound, "get_adapter", return_value=_OutboundAdapter())
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        """Clear the Now Playing card the webhooks left behind."""
        live_playback.clear_user_playback_state(self.user.id)

    def _deliver(self, provider, payload, received, event_id, *, at=None):
        """Run the task as the worker would, optionally at a later clock time."""
        kwargs = {"received_at": received.isoformat(), "event_id": event_id}
        args = (provider, json.loads(json.dumps(payload)), self.user.id)
        if at is None:
            return tasks.process_webhook(*args, **kwargs)
        with patch("django.utils.timezone.now", return_value=at):
            return tasks.process_webhook(*args, **kwargs)

    def test_second_delivery_writes_nothing(self):
        """The same message delivered again an hour later changes nothing."""
        for provider, label, payload in CASES:
            with self.subTest(provider=provider, case=label):
                received = timezone.now() - timedelta(seconds=2)
                event_id = f"{provider}-{label}"
                if label == "rating":
                    # A rating needs a tracked title to land on.
                    self._deliver(
                        provider,
                        PLEX_MOVIE if provider == "plex" else JELLYFIN_MOVIE,
                        received - timedelta(minutes=5),
                        f"{event_id}-setup",
                    )
                self._deliver(provider, payload, received, event_id)
                first = _snapshot(self.user)

                self._deliver(
                    provider,
                    payload,
                    received,
                    event_id,
                    at=timezone.now() + REDELIVERY_DELAY,
                )

                self.assertEqual(_snapshot(self.user), first)
                self.assertTrue(any(first["rows"].values()), "nothing was saved")
                if label.startswith("completed"):
                    # The outbound check is real: the first delivery queued
                    # one, and the repeat must not queue a second.
                    self.assertGreater(first["deliveries"], 0)
                self._reset()

    def test_retry_after_an_interrupted_attempt_saves_one_play(self):
        """A worker that dies after the first write leaves one play, not two."""
        for provider, label, payload in CASES:
            if not label.startswith("completed"):
                continue
            with self.subTest(provider=provider, case=label):
                received = timezone.now() - timedelta(seconds=2)
                event_id = f"{provider}-{label}-interrupted"
                with self.assertRaises(SystemExit):
                    self._crash_after_first_write(provider, payload, received, event_id)

                self._deliver(
                    provider,
                    payload,
                    received,
                    event_id,
                    at=timezone.now() + REDELIVERY_DELAY,
                )

                model = Movie if "movie" in label else Episode
                owner = (
                    {"user": self.user}
                    if model is Movie
                    else {"related_season__user": self.user}
                )
                self.assertEqual(model.objects.filter(**owner).count(), 1)
                self._reset()

    def _crash_after_first_write(self, provider, payload, received, event_id):
        """Run the task and stop it right after its first tracking row is saved."""
        from django.db.models.signals import post_save

        def stop(sender, **_kwargs):
            if sender in (Movie, Episode):
                raise SystemExit("worker lost")

        post_save.connect(stop, weak=False, dispatch_uid="redelivery-crash")
        try:
            self._deliver(provider, payload, received, event_id)
        finally:
            post_save.disconnect(dispatch_uid="redelivery-crash")

    def _reset(self):
        """Drop what one case wrote so the next starts from an empty library."""
        for model in TRACKED_MODELS:
            model.objects.filter(
                **(
                    {"related_season__user": self.user}
                    if model is Episode
                    else {"user": self.user}
                )
            ).delete()
        PlaybackProgress.objects.filter(user=self.user).delete()
        WatchStateChange.objects.filter(user=self.user).delete()
        OutboundStateDelivery.objects.filter(user=self.user).delete()
        live_playback.clear_user_playback_state(self.user.id)
        cache.clear()


class WebhookTaskOptionsTests(SimpleTestCase):
    """The task is acknowledged only after it finishes, and only this task."""

    @property
    def task(self):
        """The task as Floppy's own Celery app registers it.

        ``self.task`` is a proxy that resolves against the current
        app, which another test may have replaced.
        """
        from config.celery import app

        return app.tasks["Process media server webhook"]

    def test_message_is_acknowledged_after_the_task_finishes(self):
        self.assertTrue(self.task.acks_late)
        self.assertTrue(self.task.reject_on_worker_lost)

    def test_task_keeps_the_app_base_task(self):
        """The failure log must not drop the shared cancelled-task check."""
        from config.celery import FloppyTask

        self.assertIsInstance(self.task, FloppyTask)

    def test_redelivery_window_outlasts_a_running_task(self):
        """A slow task must not be handed to a second worker while it runs."""
        visibility = settings.CELERY_BROKER_TRANSPORT_OPTIONS["visibility_timeout"]
        self.assertGreater(visibility, self.task.time_limit)

    def test_late_acknowledgement_is_not_global(self):
        """Imports and rebuilds are long and not all repeat-safe."""
        self.assertFalse(getattr(settings, "CELERY_TASK_ACKS_LATE", False))


class WebhookTaskRetryTests(TestCase):
    """A timed-out attempt is retried, and a final failure is logged."""

    def setUp(self):
        """Create a user."""
        self.user = get_user_model().objects.create_user(
            username="retryuser",
            token="retry-token",
        )

    def _apply(self):
        return tasks.process_webhook.apply(
            args=("jellyfin", {"Event": "Stop"}, self.user.id),
            kwargs={"received_at": timezone.now().isoformat(), "event_id": "evt-1"},
        )

    @patch("integrations.tasks._webhook._process_webhook")
    def test_soft_time_limit_is_retried_then_logged_once(self, mock_process):
        mock_process.side_effect = SoftTimeLimitExceeded()

        with self.assertLogs("integrations.tasks", level="WARNING") as logs:
            result = self._apply()

        self.assertTrue(result.failed())
        self.assertEqual(mock_process.call_count, tasks.process_webhook.max_retries + 1)
        failed = [line for line in logs.output if "webhook_failed" in line]
        self.assertEqual(len(failed), 1)
        self.assertIn("event_id=evt-1", failed[0])
        self.assertIn("provider=jellyfin", failed[0])
        self.assertIn("outcome=error", failed[0])
        self.assertNotIn("Stop", failed[0])

    @patch("integrations.tasks._webhook._process_webhook")
    def test_timeout_then_success_is_not_logged_as_failed(self, mock_process):
        mock_process.side_effect = [SoftTimeLimitExceeded(), None]

        with self.assertNoLogs("integrations.tasks", level="WARNING"):
            result = self._apply()

        self.assertTrue(result.successful())
        self.assertEqual(mock_process.call_count, 2)


class WebhookStartCapTests(TestCase):
    """A message that keeps killing its worker is dropped after a few starts."""

    def setUp(self):
        """Create a user and clear start counters."""
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="capuser",
            token="cap-token",
        )

    @patch("integrations.tasks._webhook._process_webhook", return_value=None)
    def test_message_stops_after_too_many_starts(self, mock_process):
        from integrations.tasks._webhook import MAX_WEBHOOK_STARTS

        def run(task_id="task-cap"):
            # A redelivery keeps the Celery task id, so the count follows it.
            return tasks.process_webhook.apply(
                args=("jellyfin", {"Event": "Stop"}, self.user.id),
                kwargs={"event_id": "evt-cap"},
                task_id=task_id,
            )

        for _ in range(MAX_WEBHOOK_STARTS):
            run()
        self.assertEqual(mock_process.call_count, MAX_WEBHOOK_STARTS)

        with self.assertLogs("integrations.tasks", level="WARNING") as logs:
            run()
        self.assertEqual(mock_process.call_count, MAX_WEBHOOK_STARTS)
        self.assertIn("webhook_failed event_id=evt-cap", logs.output[0])
        self.assertIn("provider=jellyfin", logs.output[0])
        self.assertIn("error=TooManyDeliveries", logs.output[0])

        # Another message is counted on its own.
        run(task_id="task-other")
        self.assertEqual(mock_process.call_count, MAX_WEBHOOK_STARTS + 1)


class StremioRedeliveryTests(TestCase):
    """Stremio's three queued tasks are repeat-safe and keep a claimed play."""

    def setUp(self):
        """Create a user with a tracked movie Stremio knows by its IMDb id."""
        from app.mixins import disable_fetch_releases
        from integrations.models import StremioAccount
        from integrations.tests.test_stremio_playback import FakeRedis

        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(
            username="stremio-redelivery",
            password="x",
        )
        StremioAccount.objects.create(user=self.user, auth_key="encrypted")
        with disable_fetch_releases():
            self.item = Item.objects.create(
                media_id="603",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                provider_external_ids={"imdb_id": "tt0133093"},
                title="The Matrix",
                image="",
                runtime_minutes=30,
            )
        self.redis = FakeRedis()
        self.library = []
        self.queued = []
        for target, kwargs in (
            ("app.providers.tmdb.movie", {"return_value": MOVIE_METADATA}),
            (
                "app.providers.tmdb.find",
                {
                    "return_value": {
                        "movie_results": [{"id": 603}],
                        "tv_results": [],
                        "tv_episode_results": [],
                    },
                },
            ),
            ("app.live_playback._attach_resolved_image", {}),
            ("integrations.stremio_playback._client", {"return_value": self.redis}),
            (
                "integrations.stremio_playback.helpers.decrypt_or_raise",
                {"return_value": "auth"},
            ),
            (
                "integrations.stremio_playback.get_library_items",
                {"side_effect": lambda _auth, ids=None: self.library},
            ),
            (
                "integrations.tasks._webhook._schedule_verifier",
                {"side_effect": lambda *args: self.queued.append(args)},
            ),
            ("integrations.stremio_queue.release_pending", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        """Clear the Now Playing card."""
        live_playback.clear_user_playback_state(self.user.id)

    def _plays(self):
        return (
            sum(
                movie.plays.count()
                for movie in Movie.objects.filter(user=self.user, item=self.item)
            )
            + Movie.objects.filter(
                user=self.user, item=self.item, end_date__isnull=False
            )
            .exclude(plays__isnull=False)
            .count()
        )

    def _snapshot(self):
        return _snapshot(self.user) | {"plays": self._plays()}

    def test_tracker_events_delivered_twice_write_once(self):
        """Player and library events, repeated an hour later, change nothing."""
        cases = (
            ("player", "action=stop&currentTime=1750000&duration=1800000"),
            ("library", "action=watched"),
        )
        for kind, extra in cases:
            for session_cache in ("kept", "expired"):
                with self.subTest(kind=kind, session_cache=session_cache):
                    Movie.objects.create(item=self.item, user=self.user)
                    received = (timezone.now() - timedelta(seconds=2)).isoformat()
                    args = (kind, self.user.id, "movie", "tt0133093", extra, received)
                    status = tasks.process_stremio_tracker_event(*args)
                    self.assertEqual(status, "recorded")
                    first = self._snapshot()
                    self.assertGreater(first["plays"], 0)
                    if session_cache == "expired":
                        cache.clear()

                    with patch(
                        "django.utils.timezone.now",
                        return_value=timezone.now() + REDELIVERY_DELAY,
                    ):
                        tasks.process_stremio_tracker_event(*args)

                    self.assertEqual(self._snapshot(), first)
                    Movie.objects.filter(user=self.user).delete()
                    PlaybackProgress.objects.filter(user=self.user).delete()
                    cache.clear()

    def test_start_delivered_twice_keeps_one_session_and_a_verifier(self):
        """A redelivered start finds its session and leaves one live verifier."""
        payload = {"id": "tt0133093", "type": "movie"}
        tasks.process_stremio_webhook(payload, self.user.id, "movie:tt0133093")
        tasks.process_stremio_webhook(payload, self.user.id, "movie:tt0133093")

        sessions = [v for v in self.redis.values.values() if v.startswith("{")]
        self.assertEqual(len(sessions), 1)
        stored_id = json.loads(sessions[0])["id"]
        # The redelivery queued a spare verifier for a session it never stored;
        # that one stops at once, and the stored session has its own.
        self.assertIn((stored_id, 60, 0), self.queued)
        spare = next(args for args in self.queued if args[0] != stored_id)
        result = tasks.verify_stremio_playback(spare[0], revision=0)
        self.assertEqual(result["reason"], "session_inactive")
        self.assertEqual(self._plays(), 0)

    def test_verifier_lost_after_claiming_completion_still_saves_one_play(self):
        """The play survives a worker lost between claim and save."""
        tasks.process_stremio_webhook(
            {"id": "tt0133093", "type": "movie"}, self.user.id
        )
        session_id, _countdown, revision = self.queued[-1]
        now = timezone.now()

        def state(percent, flagged=0, watched_at=now):
            duration = 30 * 60 * 1000
            return [
                {
                    "_id": "tt0133093",
                    "state": {
                        "video_id": "tt0133093",
                        "duration": duration,
                        "timeWatched": duration * percent / 100,
                        "timeOffset": 0,
                        "flaggedWatched": flagged,
                        "timesWatched": 0,
                        "lastWatched": watched_at.isoformat(),
                    },
                }
            ]

        self.library = state(1)
        tasks.verify_stremio_playback(session_id, revision=revision)
        _sid, _countdown, revision = self.queued[-1]
        self.library = state(95, flagged=1, watched_at=now + timedelta(minutes=25))

        with (
            patch(
                "integrations.tasks._webhook._process_webhook",
                side_effect=SystemExit("worker lost"),
            ),
            self.assertRaises(SystemExit),
        ):
            tasks.verify_stremio_playback(session_id, revision=revision)
        self.assertEqual(self._plays(), 0)

        # The broker delivers the same message again, an hour later.
        with patch(
            "django.utils.timezone.now",
            return_value=timezone.now() + REDELIVERY_DELAY,
        ):
            result = tasks.verify_stremio_playback(session_id, revision=revision)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self._plays(), 1)

        # A second redelivery, now that the play is saved, does nothing.
        result = tasks.verify_stremio_playback(session_id, revision=revision)
        self.assertEqual(result["reason"], "session_inactive")
        self.assertEqual(self._plays(), 1)
