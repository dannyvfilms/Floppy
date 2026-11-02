"""Status changes record what made them, and the user can see it (#1133)."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from app.history_processor import status_change_log
from app.models import TV, Item, MediaTypes, Season, Sources, Status
from integrations.webhooks.stremio import StremioWebhookProcessor

SHOW_ID = "1396"


def _show_metadata(media_id, season_numbers, *_args, **_kwargs):
    metadata = {"media_id": media_id, "title": "Breaking Bad", "image": ""}
    for number in season_numbers:
        metadata[f"season/{number}"] = {
            "image": "",
            "episodes": [{"episode_number": 1}, {"episode_number": 2}],
        }
    return metadata


class StatusChangeReasonTests(TestCase):
    """Automatic and manual status changes carry a readable reason."""

    def setUp(self):
        """Create a user tracking a dropped show."""
        self.credentials = {"username": "u", "password": "p"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.tv_item = Item.objects.create(
            media_id=SHOW_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.DROPPED.value,
        )
        season_item = Item.objects.create(
            media_id=SHOW_ID,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Breaking Bad",
        )
        Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.DROPPED.value,
        )
        self.metadata = patch(
            "app.providers.services.get_media_metadata",
            return_value={"episodes": [], "max_progress": 2, "related": {"seasons": []}},
        )
        self.metadata.start()
        self.addCleanup(self.metadata.stop)
        fetch_releases = patch("app.models.Item.fetch_releases")
        fetch_releases.start()
        self.addCleanup(fetch_releases.stop)

    def _verified_play(self):
        payload = {
            "id": "tt0903747:1:1",
            "type": "series",
            "_floppy_verified_completion": True,
        }
        with patch("app.providers.tmdb.tv_with_seasons", side_effect=_show_metadata):
            StremioWebhookProcessor()._handle_tv_episode(
                SHOW_ID, 1, 1, payload, self.user,
            )

    def test_webhook_reopen_is_labelled_with_its_source(self):
        """The log names the scrobble that reopened a dropped show."""
        self._verified_play()

        latest = status_change_log(self.tv)[0]
        self.assertEqual(latest["old"], Status.DROPPED.value)
        self.assertEqual(latest["new"], Status.IN_PROGRESS.value)
        self.assertEqual(latest["reason"], "Stremio playback")

    def test_user_edit_is_labelled_as_the_user(self):
        """A status set through the track form is recorded as the user's."""
        self.client.login(**self.credentials)
        self.client.post(
            reverse("media_save"),
            {
                "media_id": SHOW_ID,
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.TV.value,
                "instance_id": str(self.tv.id),
                "status": Status.PAUSED.value,
            },
        )

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.PAUSED.value)
        self.assertEqual(status_change_log(self.tv)[0]["reason"], "you")

    def test_edit_tracking_modal_has_status_history_tab(self):
        """The Edit Tracking modal has a Status history tab naming each change's cause."""
        self._verified_play()
        self.client.login(**self.credentials)

        response = self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": SHOW_ID,
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["status_history_tab_available"])
        self.assertContains(response, "activeTab = 'status-history'")
        self.assertContains(response, "by Stremio playback")

    def test_diagnose_command_reports_changes_and_schedules(self):
        """The diagnostic command names the reason and never prints tokens."""
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        self._verified_play()
        crontab = CrontabSchedule.objects.create(hour=0, minute=0)
        PeriodicTask.objects.create(
            name="Import from Trakt for u at 00:00 daily",
            task="Import from Trakt",
            crontab=crontab,
            kwargs=(
                f'{{"user_id": {self.user.id}, "mode": "overwrite",'
                ' "token": "secret-token"}'
            ),
        )

        out = StringIO()
        call_command("diagnose_status_reverts", "--user", "u", stdout=out)
        report = out.getvalue()

        self.assertIn("Breaking Bad: Dropped -> In progress  [Stremio playback]", report)
        self.assertIn("mode=overwrite", report)
        self.assertIn("rebuilds shows from the source", report)
        self.assertNotIn("secret-token", report)
