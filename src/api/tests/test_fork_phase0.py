# FORK: tests for Phase 0 parity groundwork — consumption-history sorting
# and the Celery task-status endpoint.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814

from django_celery_results.models import TaskResult

from app.models import MediaTypes, Movie

from .base import FloppyApiTestCase


class HistorySortTests(FloppyApiTestCase):
    """Consumption-history endpoints accept an optional `sort` param."""

    def setUp(self):
        """Add a second play with distinct dates to an existing movie."""
        super().setUp()
        self.movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        first = self.movie_medias[0]
        first.start_date = datetime.date(2024, 1, 1)
        first.end_date = datetime.date(2024, 1, 2)
        first.save(update_fields=["start_date", "end_date"])
        Movie.objects.create(
            item=self.movie_item,
            user=self.user1,
            start_date=datetime.date(2025, 6, 1),
            end_date=datetime.date(2025, 6, 2),
        )

    def _get_history(self, params):
        return self.call_api(
            "get",
            "api_media_consumption_history",
            args=(
                MediaTypes.MOVIE.value,
                self.movie_item.source,
                self.movie_item.media_id,
            ),
            params=params,
            headers=self.auth_headers,
        )

    def test_sort_ascending(self):
        """sort=started orders plays oldest first."""
        response = self._get_history({"sort": "started"})
        self.assertEqual(response.status_code, HTTP.OK)
        starts = [row["start_date"] for row in response.json()["results"]]
        self.assertEqual(starts, sorted(starts))

    def test_sort_descending(self):
        """sort=-started orders plays newest first."""
        response = self._get_history({"sort": "-started"})
        self.assertEqual(response.status_code, HTTP.OK)
        starts = [row["start_date"] for row in response.json()["results"]]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_invalid_sort_rejected(self):
        """Unknown sort values return 400 with the valid vocabulary."""
        response = self._get_history({"sort": "bogus"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("Valid values", response.json()["detail"])

    def test_no_sort_keeps_default_behavior(self):
        """Omitting sort returns 200 with all plays."""
        response = self._get_history(None)
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 2)


class TaskStatusTests(FloppyApiTestCase):
    """GET /tasks/{task_id} reports Celery task state with ownership checks."""

    def test_unknown_task_reports_pending(self):
        """A task with no stored result reports PENDING."""
        response = self.call_api(
            "get",
            "api_task_status",
            args=("no-such-task",),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["status"], "PENDING")

    def test_owned_task_returns_record(self):
        """A stored result whose kwargs name the caller is returned."""
        TaskResult.objects.create(
            task_id="owned-task",
            task_name="integrations.tasks.import_mal",
            status="SUCCESS",
            task_kwargs=f"{{'user_id': {self.user1.id}, 'username': 'x'}}",
            result="'done'",
        )
        response = self.call_api(
            "get",
            "api_task_status",
            args=("owned-task",),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertEqual(payload["task_name"], "integrations.tasks.import_mal")

    def test_other_users_task_not_found(self):
        """A stored result owned by another user 404s."""
        TaskResult.objects.create(
            task_id="foreign-task",
            task_name="integrations.tasks.import_mal",
            status="SUCCESS",
            task_kwargs=f"{{'user_id': {self.user2.id}}}",
        )
        response = self.call_api(
            "get",
            "api_task_status",
            args=("foreign-task",),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_requires_auth(self):
        """Unauthenticated requests are rejected."""
        response = self.call_api("get", "api_task_status", args=("owned-task",))
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
