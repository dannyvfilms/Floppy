# FORK: recurring-schedule coverage for the Audiobookshelf connect/import views.
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from integrations.models import AudiobookshelfAccount

BASE_URL = "https://audiobookshelf.example.com"
API_TOKEN = "abs-secret-token"


class AudiobookshelfScheduleTests(TestCase):
    """Connecting/importing keeps a minute-based recurring schedule in sync."""

    def setUp(self):
        """Create an authenticated user for Audiobookshelf view requests."""
        self.user = get_user_model().objects.create_user(username="abs-connect")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_creates_interval_schedule_immediately(
        self, mock_get_me, mock_import
    ):
        """Connecting (not just a manual import) schedules the recurring poll."""
        response = self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        mock_import.assert_called_once()

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertIsNotNone(task.interval)
        self.assertIsNone(task.crontab)
        self.assertEqual(task.interval.every, 15)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)
        self.assertTrue(task.enabled)

    @override_settings(AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES=5)
    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_honors_configured_interval(self, mock_get_me, mock_import):
        """The polling cadence respects AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES."""
        self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(task.interval.every, 5)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    def test_manual_import_migrates_legacy_crontab_schedule(self, mock_import):
        """A pre-existing 2-hour crontab schedule is converted, not duplicated."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name=f"Import from Audiobookshelf for {self.user.username} (every 2 hours)",
            task="Import from Audiobookshelf (Recurring)",
            crontab=crontab,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("import_audiobookshelf"))
        self.assertEqual(response.status_code, 302)

        tasks_for_user = PeriodicTask.objects.filter(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(tasks_for_user.count(), 1)
        task = tasks_for_user.get()
        self.assertIsNone(task.crontab)
        self.assertIsNotNone(task.interval)
        self.assertEqual(task.interval.every, 15)

    def test_disconnect_removes_schedule(self):
        """Disconnecting deletes the recurring periodic task."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.create(
            name="Import from Audiobookshelf for abs-connect (every 15 minutes)",
            task="Import from Audiobookshelf (Recurring)",
            interval=interval,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("audiobookshelf_disconnect"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Audiobookshelf (Recurring)",
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists()
        )
