import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, PeriodicTask


class ExportScheduleTests(TestCase):
    """Tests for combined one-time export and recurring export schedule flow."""

    def setUp(self):
        """Create and login user for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_export_once_returns_csv_without_schedule(self):
        """One-time export should return CSV response and not create a schedule."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {
                "frequency": "once",
                "media_types": ["tv", "movie"],
                "include_lists": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertEqual(PeriodicTask.objects.count(), 0)

    @patch("users.views.exports.generate_rows", return_value=iter(()))
    def test_export_once_allows_lists_only(self, generate_rows):
        """No media types with Lists enabled exports a valid subset."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {"frequency": "once", "include_lists": "on"},
        )
        list(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        generate_rows.assert_called_once_with(
            self.user,
            media_types=[],
            include_lists=True,
            include_collection=False,
        )
        self.assertEqual(PeriodicTask.objects.count(), 0)

    @patch("users.views.exports.generate_rows", return_value=iter(()))
    def test_export_once_allows_collection_only(self, generate_rows):
        """No media types with Collection enabled exports a valid subset."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {"frequency": "once", "include_collection": "on"},
        )
        list(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        generate_rows.assert_called_once_with(
            self.user,
            media_types=[],
            include_lists=False,
            include_collection=True,
        )
        self.assertEqual(PeriodicTask.objects.count(), 0)

    @patch("users.views.exports.generate_rows", return_value=iter(()))
    def test_export_once_allows_media_only(self, generate_rows):
        """Selected media types remain valid when Lists and Collection are off."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {"frequency": "once", "media_types": ["movie"]},
        )
        list(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        generate_rows.assert_called_once_with(
            self.user,
            media_types=["movie"],
            include_lists=False,
            include_collection=False,
        )
        self.assertEqual(PeriodicTask.objects.count(), 0)

    def test_export_rejects_empty_selection(self):
        """An export with no selected content is rejected without a schedule."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {"frequency": "once"},
        )

        self.assertRedirects(response, reverse("export_data"))
        self.assertEqual(PeriodicTask.objects.count(), 0)
        self.assertIn(
            "Select at least one media type, Custom Lists, or Collection to export.",
            [str(message) for message in get_messages(response.wsgi_request)],
        )

    @patch("users.views.exports.generate_rows", return_value=iter(()))
    def test_recurring_subset_export_persists_empty_media_types(self, generate_rows):
        """A recurring subset keeps the same no-media selection as its first export."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {
                "frequency": "daily",
                "time": "04:30",
                "include_collection": "on",
            },
        )
        list(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        generate_rows.assert_called_once_with(
            self.user,
            media_types=[],
            include_lists=False,
            include_collection=True,
        )
        task = PeriodicTask.objects.get()
        self.assertEqual(json.loads(task.kwargs)["media_types"], [])
        self.assertTrue(json.loads(task.kwargs)["include_collection"])

    def test_export_page_describes_and_blocks_empty_selection(self):
        """The export page explains valid selections and disables empty submits."""
        response = self.client.get(reverse("export_data"))

        self.assertContains(
            response,
            "Keep at least one media type, Custom Lists, or Collection enabled.",
        )
        self.assertContains(response, 'x-bind:disabled="!exportContentSelected"')
        self.assertNotContains(response, "Uncheck everything to export all data.")

    def test_export_page_distinguishes_all_and_subset_schedules(self):
        """Scheduled export details distinguish all-media and no-media subsets."""
        crontab = CrontabSchedule.objects.create(
            minute="0",
            hour="4",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone="UTC",
        )
        PeriodicTask.objects.create(
            name="All media export",
            task="Scheduled backup export",
            crontab=crontab,
            kwargs=json.dumps(
                {
                    "user_id": self.user.id,
                    "media_types": None,
                    "include_lists": True,
                    "include_collection": True,
                },
            ),
            enabled=True,
        )
        PeriodicTask.objects.create(
            name="Collection-only export",
            task="Scheduled backup export",
            crontab=crontab,
            kwargs=json.dumps(
                {
                    "user_id": self.user.id,
                    "media_types": [],
                    "include_lists": False,
                    "include_collection": True,
                },
            ),
            enabled=True,
        )

        response = self.client.get(reverse("export_data"))

        self.assertContains(response, "Media Types: All")
        self.assertContains(response, "Media Types: None (Lists/Collection only)")
        self.assertContains(response, "Collection: Included")

    def test_recurring_export_creates_schedule_and_returns_csv(self):
        """Recurring export should create schedule and return immediate CSV."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {
                "frequency": "daily",
                "time": "04:30",
                "media_types": ["tv", "movie"],
                "include_lists": "on",
                "include_collection": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", response["Content-Disposition"])

        self.assertEqual(PeriodicTask.objects.count(), 1)
        task = PeriodicTask.objects.first()
        self.assertEqual(task.task, "Scheduled backup export")
        self.assertIn('"user_id"', task.kwargs)
        self.assertIn('"media_types": ["tv", "movie"]', task.kwargs)
        self.assertIn('"include_lists": true', task.kwargs)
        self.assertIn('"include_collection": true', task.kwargs)

    def test_invalid_frequency_redirects_without_schedule(self):
        """Invalid frequency should redirect and avoid schedule creation."""
        response = self.client.post(
            reverse("create_export_schedule"),
            {
                "frequency": "monthly",
                "time": "04:30",
                "media_types": ["movie"],
            },
        )

        self.assertRedirects(response, reverse("export_data"))
        self.assertEqual(PeriodicTask.objects.count(), 0)
