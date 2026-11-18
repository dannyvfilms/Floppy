"""Production branches that the test settings switch off.

``config.test_settings`` sets ``TESTING`` and runs Celery eagerly, and several
call sites return early or skip a task under it so that the suite does not run
provider work inline. Each test here turns the flag back off, records the task
call at the Celery boundary instead of running it, and asserts which task is
queued, with which arguments and on which queue (AGENTS.md, "Queue rule").
``config.tests.test_test_mode_branches`` lists every such site and its test.
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from app.discover import tab_cache
from app.models import Item, MediaTypes, Sources
from config.celery import app as celery_app


def queue_for(task_name):
    """Return the queue a task message is published to in production."""
    route = celery_app.amqp.router.route({}, task_name, (), {})
    queue = route.get("queue")
    return queue.name if queue is not None else celery_app.conf.task_default_queue


class FetchReleasesProductionTests(TestCase):
    """``Item.fetch_releases`` queues the calendar reload outside tests."""

    def setUp(self):
        self.movie = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="http://example.com/matrix.jpg",
        )

    @override_settings(TESTING=False)
    def test_delayed_fetch_queues_reload_calendar_for_the_item(self):
        from events import tasks as event_tasks

        with patch.object(event_tasks.reload_calendar, "apply_async") as apply_async:
            self.movie.fetch_releases(delay=True)

        apply_async.assert_called_once_with(
            kwargs={"item_ids": [self.movie.id]},
            countdown=3,
        )
        self.assertEqual(queue_for(event_tasks.reload_calendar.name), "celery")

    @override_settings(TESTING=False)
    def test_immediate_fetch_runs_reload_calendar_for_the_item(self):
        with patch("events.tasks.reload_calendar") as reload_calendar:
            self.movie.fetch_releases(delay=False)

        reload_calendar.assert_called_once_with(item_ids=[self.movie.id])
        reload_calendar.apply_async.assert_not_called()

    def test_test_mode_skips_the_reload(self):
        with patch("events.tasks.reload_calendar") as reload_calendar:
            self.movie.fetch_releases(delay=True)

        reload_calendar.assert_not_called()
        reload_calendar.apply_async.assert_not_called()


class SeasonEpisodeRuntimeBackfillProductionTests(TestCase):
    """A season page that creates episode rows queues their runtime backfill."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="season-viewer",
            password="12345",
        )
        self.client.force_login(self.user)
        self.url = reverse(
            "season_details",
            kwargs={
                "source": Sources.TMDB.value,
                "media_id": "1668",
                "title": "test-tv-show",
                "season_number": 1,
            },
        )

    @staticmethod
    def _metadata(*_args, **_kwargs):
        return {
            "title": "Test TV Show",
            "media_id": "1668",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "image": "http://example.com/image.jpg",
            "season/1": {
                "title": "Test TV Show",
                "season_title": "Season 1",
                "media_id": "1668",
                "media_type": MediaTypes.SEASON.value,
                "source": Sources.TMDB.value,
                "image": "http://example.com/season.jpg",
                "episodes": [
                    {"episode_number": 1, "name": "One", "air_date": "2023-01-01"},
                    {"episode_number": 2, "name": "Two", "air_date": "2023-01-08"},
                ],
            },
        }

    def _view_secondary(self):
        with (
            patch(
                "app.providers.services.get_media_metadata",
                side_effect=self._metadata,
            ),
            patch("app.providers.tmdb.process_episodes", return_value=[]),
            patch("app.providers.trakt.is_configured", return_value=False),
            patch("app.tasks_runtime.enqueue_episode_runtime_backfill") as enqueue,
        ):
            response = self.client.get(self.url, {"fragment": "secondary"})
        self.assertEqual(response.status_code, 200)
        return enqueue

    @override_settings(TESTING=False)
    def test_first_view_queues_one_backfill_for_the_season(self):
        enqueue = self._view_secondary()

        enqueue.assert_called_once_with([("1668", Sources.TMDB.value, 1)])
        self.assertEqual(
            Item.objects.filter(
                media_id="1668",
                media_type=MediaTypes.EPISODE.value,
            ).count(),
            2,
        )

    @override_settings(TESTING=False)
    def test_repeat_view_creates_nothing_and_queues_nothing(self):
        self._view_secondary()

        enqueue = self._view_secondary()

        enqueue.assert_not_called()

    def test_test_mode_skips_the_backfill(self):
        enqueue = self._view_secondary()

        enqueue.assert_not_called()


class DiscoverTabRefreshProductionTests(TestCase):
    """Outside tests a tab refresh is queued without the eager-refresh switch."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(username="discover-tab")

    @override_settings(TESTING=False, DISCOVER_TASKS_EAGER_REFRESH=False)
    def test_schedule_tab_refresh_queues_the_rebuild(self):
        from app.tasks import refresh_discover_tab_cache

        with patch.object(refresh_discover_tab_cache, "apply_async") as apply_async:
            scheduled = tab_cache.schedule_tab_refresh(
                self.user.id,
                "movie",
                show_more=False,
            )

        self.assertTrue(scheduled)
        apply_async.assert_called_once()
        call = apply_async.call_args.kwargs
        self.assertEqual(call["args"], [self.user.id, "movie"])
        self.assertEqual(
            call["kwargs"],
            {"show_more": False, "force": False, "clear_provider_cache": False},
        )
        self.assertEqual(
            call["priority"],
            settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )
        self.assertEqual(queue_for(refresh_discover_tab_cache.name), "discover")

    @override_settings(DISCOVER_TASKS_EAGER_REFRESH=False)
    def test_test_mode_reserves_without_queueing(self):
        from app.tasks import refresh_discover_tab_cache

        with patch.object(refresh_discover_tab_cache, "apply_async") as apply_async:
            scheduled = tab_cache.schedule_tab_refresh(
                self.user.id,
                "movie",
                show_more=False,
            )

        self.assertTrue(scheduled)
        apply_async.assert_not_called()
