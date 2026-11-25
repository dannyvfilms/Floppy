from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from integrations.models import LastFMAccount


class EditImportScheduleTests(TestCase):
    """Tests for the edit_import_schedule view."""

    def setUp(self):
        """Create user and schedules for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.crontab = CrontabSchedule.objects.create(
            minute="0",
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        self.task = PeriodicTask.objects.create(
            name="Import from Stremio for testuser (every 2 hours)",
            task="Import from Stremio (Recurring)",
            kwargs=f'{{"user_id": {self.user.id}}}',
            crontab=self.crontab,
            enabled=True,
        )

    def test_edit_to_interval(self):
        """A daily+ cadence becomes an IntervalSchedule."""
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": self.task.name, "frequency": "6h"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.interval.every, 360)
        self.assertEqual(self.task.interval.period, IntervalSchedule.MINUTES)
        self.assertIsNone(self.task.crontab)
        self.assertIsNone(self.task.last_run_at)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Import schedule updated", str(messages[0]))

    def test_edit_to_daily_time(self):
        """A daily cadence keeps a fixed local time on a crontab."""
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": self.task.name, "frequency": "daily", "time": "03:30"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.interval)
        self.assertEqual(self.task.crontab.hour, "3")
        self.assertEqual(self.task.crontab.minute, "30")
        self.assertEqual(self.task.crontab.day_of_week, "*")

    def test_edit_to_weekly(self):
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": self.task.name, "frequency": "weekly", "time": "09:00"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.crontab.day_of_week, "0")

    def test_edit_invalid_frequency(self):
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": self.task.name, "frequency": "bogus"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.crontab_id, self.crontab.id)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Invalid import frequency", str(messages[0]))

    def test_edit_invalid_time(self):
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": self.task.name, "frequency": "daily", "time": "25:99"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.crontab.hour, "*/2")

    def test_edit_other_user_task(self):
        other_user = get_user_model().objects.create_user(
            username="otheruser",
            password="testpass123",
        )
        other_task = PeriodicTask.objects.create(
            name="Import from Stremio for otheruser (every 2 hours)",
            task="Import from Stremio (Recurring)",
            kwargs=f'{{"user_id": {other_user.id}}}',
            crontab=self.crontab,
            enabled=True,
        )
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": other_task.name, "frequency": "1h"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        other_task.refresh_from_db()
        self.assertIsNone(other_task.interval)

    def test_edit_shared_lastfm_task_rejected(self):
        """The shared Last.fm poll cannot be retimed by one user."""
        LastFMAccount.objects.create(user=self.user, lastfm_username="testuser")
        interval = IntervalSchedule.objects.create(every=15, period=IntervalSchedule.MINUTES)
        lastfm_task = PeriodicTask.objects.create(
            name="Poll Last.fm for all users (every 15 minutes)",
            task="Poll Last.fm for all users",
            interval=interval,
            enabled=True,
        )
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": lastfm_task.name, "frequency": "1h"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        lastfm_task.refresh_from_db()
        self.assertEqual(lastfm_task.interval.every, 15)

    def test_edit_missing_task(self):
        response = self.client.post(
            reverse("edit_import_schedule"),
            {"task_name": "Nope", "frequency": "1h"},
        )
        self.assertRedirects(response, reverse("import_data"), fetch_redirect_response=False)
        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Import schedule not found", str(messages[0]))

    def test_edit_redirects_to_referer_not_fragment(self):
        """Forms rendered inside the htmx activity fragment must not redirect
        the user back to the bare fragment URL.
        """
        response = self.client.post(
            reverse("edit_import_schedule"),
            {
                "task_name": self.task.name,
                "frequency": "6h",
                "next": "/settings/import/activity",
            },
            HTTP_REFERER="/settings/activity",
        )
        self.assertEqual(response["Location"], "/settings/activity")

    def test_delete_redirects_to_referer_not_fragment(self):
        response = self.client.post(
            reverse("delete_import_schedule"),
            {
                "task_name": self.task.name,
                "next": "/settings/import/activity",
            },
            HTTP_REFERER="/settings/activity",
        )
        self.assertEqual(response["Location"], "/settings/activity")

    def test_edit_state_recognizes_current_cadence(self):
        """The card opens with the task's current cadence preselected."""
        from users import helpers

        self.assertEqual(helpers.schedule_edit_state(self.task), ("2h", ""))
        self.task.crontab = CrontabSchedule.objects.create(
            minute="30", hour="3", day_of_week="*",
            day_of_month="*", month_of_year="*",
        )
        self.assertEqual(helpers.schedule_edit_state(self.task), ("daily", "03:30"))
        self.task.crontab = None
        self.task.interval = IntervalSchedule.objects.create(
            every=45, period=IntervalSchedule.MINUTES,
        )
        self.assertEqual(helpers.schedule_edit_state(self.task), ("", ""))
