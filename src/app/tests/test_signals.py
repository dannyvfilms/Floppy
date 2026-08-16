from datetime import timedelta
from unittest.mock import patch

from celery import states
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_results.models import TaskResult

from app import signals, tasks
from app.models import (
    CREDITS_BACKFILL_VERSION,
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Person,
    PersonGender,
    Sources,
)
from integrations.tasks import scheduled_backup_export


class TaskResultOnPublishTests(TestCase):
    HEADERS = {
        "task": "Import from Trakt",
        "id": "00000000-0000-0000-0000-000000000341",
    }

    def test_creates_pending_task_result_when_apps_ready(self):
        signals.create_task_result_on_publish(headers=dict(self.HEADERS))

        self.assertTrue(
            TaskResult.objects.filter(task_id=self.HEADERS["id"]).exists(),
        )

    def test_skips_untracked_task(self):
        headers = {
            **self.HEADERS,
            "task": "app.tasks.example",
        }

        signals.create_task_result_on_publish(headers=headers)

        self.assertFalse(TaskResult.objects.filter(task_id=headers["id"]).exists())

    def test_skips_task_result_during_app_initialization(self):
        with patch.object(signals.apps, "ready", new=False):
            signals.create_task_result_on_publish(headers=dict(self.HEADERS))

        self.assertFalse(
            TaskResult.objects.filter(task_id=self.HEADERS["id"]).exists(),
        )


class TaskResultOnCompletionTests(TestCase):
    TASK_ID = "00000000-0000-0000-0000-000000000518"

    def _create_pending_result(self):
        return TaskResult.objects.create(
            task_id=self.TASK_ID,
            status="PENDING",
            task_name="Scheduled backup export",
            task_kwargs="{'user_id': 1,}",
        )

    def test_success_signal_marks_task_result_as_success(self):
        self._create_pending_result()
        sender = type(
            "Sender",
            (),
            {
                "name": "Scheduled backup export",
                "request": type("Request", (), {"id": self.TASK_ID})(),
            },
        )()

        signals.update_task_result_on_success(
            sender=sender,
            result="Backup saved to /floppy/backups/example.csv",
        )

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.status, "SUCCESS")
        self.assertEqual(
            task.result,
            '"Backup saved to /floppy/backups/example.csv"',
        )
        self.assertIsNotNone(task.date_done)

    def test_success_signal_preserves_task_name_and_kwargs(self):
        self._create_pending_result()
        sender = type(
            "Sender",
            (),
            {
                "name": "Scheduled backup export",
                "request": type("Request", (), {"id": self.TASK_ID})(),
            },
        )()

        signals.update_task_result_on_success(sender=sender, result="ok")

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.task_name, "Scheduled backup export")
        self.assertEqual(task.task_kwargs, "{'user_id': 1,}")

    def test_failure_signal_marks_task_result_as_failure(self):
        self._create_pending_result()

        signals.update_task_result_on_failure(
            sender=type("Sender", (), {"name": "Scheduled backup export"})(),
            task_id=self.TASK_ID,
            exception=ValueError("boom"),
            einfo="Traceback (most recent call last): ValueError: boom",
        )

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.status, "FAILURE")
        self.assertIn("boom", task.result)
        self.assertIn("boom", task.traceback)

    def test_success_signal_no_op_without_task_id(self):
        self._create_pending_result()
        sender = type(
            "Sender",
            (),
            {
                "name": "Scheduled backup export",
                "request": type("Request", (), {"id": None})(),
            },
        )()

        signals.update_task_result_on_success(sender=sender, result="ok")

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.status, "PENDING")

    def test_completion_signals_ignore_untracked_tasks(self):
        TaskResult.objects.create(
            task_id=self.TASK_ID,
            status=states.PENDING,
            task_name="app.tasks.example",
        )
        sender = type(
            "Sender",
            (),
            {
                "name": "app.tasks.example",
                "request": type("Request", (), {"id": self.TASK_ID})(),
            },
        )()

        signals.update_task_result_on_success(sender=sender, result="ignored")
        signals.update_task_result_on_failure(
            sender=sender,
            task_id=self.TASK_ID,
            exception=ValueError("ignored"),
        )

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.status, states.PENDING)

    def test_scheduled_backup_export_task_marks_result_success_end_to_end(self):
        """Regression test for issue #518: scheduled export history stuck on Pending.

        CELERY_TASK_ALWAYS_EAGER skips the broker, so before_task_publish (which
        normally creates the PENDING row in production) never fires here - the
        PENDING row is created manually to mirror what a real scheduled run does.
        """
        user = get_user_model().objects.create_user(
            username="export-signal-user",
            password="testpass123",
        )
        TaskResult.objects.create(
            task_id=self.TASK_ID,
            status="PENDING",
            task_name="Scheduled backup export",
        )

        with patch("integrations.exports.write_backup", return_value="backup.csv"):
            scheduled_backup_export.apply_async(
                kwargs={"user_id": user.id},
                task_id=self.TASK_ID,
            )

        task = TaskResult.objects.get(task_id=self.TASK_ID)
        self.assertEqual(task.status, "SUCCESS")
        self.assertIn("Backup saved to backup.csv", task.result)


class TaskResultCleanupTests(TestCase):
    def _create_result(self, task_id, status, when):
        result = TaskResult.objects.create(
            task_id=task_id,
            status=status,
            task_name="app.tasks.example",
        )
        TaskResult.objects.filter(pk=result.pk).update(
            date_created=when,
            date_done=when,
        )
        return result

    def test_cleanup_removes_expired_and_abandoned_rows(self):
        now = timezone.now()
        old = now - timedelta(days=8)
        stale_pending = now - timedelta(hours=1)
        recent = now - timedelta(days=1)
        recent_pending = now - timedelta(minutes=10)

        expired_success = self._create_result("cleanup-success", states.SUCCESS, old)
        stale_pending_result = self._create_result(
            "cleanup-pending",
            states.PENDING,
            stale_pending,
        )
        stale_started = self._create_result("cleanup-started", states.STARTED, old)
        recent_success = self._create_result("keep-success", states.SUCCESS, recent)
        recent_pending_result = self._create_result(
            "keep-pending",
            states.PENDING,
            recent_pending,
        )

        deleted = tasks.cleanup_task_results.run(batch_size=10)

        self.assertEqual(deleted, 3)
        self.assertFalse(
            TaskResult.objects.filter(
                pk__in=[expired_success.pk, stale_pending_result.pk, stale_started.pk],
            ).exists(),
        )
        self.assertTrue(
            TaskResult.objects.filter(
                pk__in=[recent_success.pk, recent_pending_result.pk],
            ).exists(),
        )

    def test_cleanup_respects_batch_size(self):
        old = timezone.now() - timedelta(days=8)
        self._create_result("cleanup-batch-1", states.SUCCESS, old)
        self._create_result("cleanup-batch-2", states.SUCCESS, old)

        deleted = tasks.cleanup_task_results.run(batch_size=1)

        self.assertEqual(deleted, 1)
        self.assertEqual(TaskResult.objects.filter(status=states.SUCCESS).count(), 1)


class ItemSignalTests(TestCase):
    def test_item_save_does_not_delete_current_genre_state_on_unrelated_update(self):
        item = Item.objects.create(
            media_id="3001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Signal Show",
            image="https://example.com/signal-show.jpg",
            genres=["Drama", "Anime"],
        )
        MetadataBackfillState.objects.create(
            item=item,
            field=MetadataBackfillField.GENRES,
            strategy_version=tasks.GENRE_BACKFILL_VERSION,
            last_success_at=timezone.now(),
        )

        signals.schedule_runtime_backfill_on_item_save(
            sender=Item,
            instance=item,
            created=False,
            update_fields={"title"},
        )

        self.assertTrue(
            MetadataBackfillState.objects.filter(
                item=item,
                field=MetadataBackfillField.GENRES,
                strategy_version=tasks.GENRE_BACKFILL_VERSION,
            ).exists(),
        )

    @override_settings(TESTING=False)
    @patch("app.tasks.enqueue_runtime_backfill_items", return_value=0)
    @patch("app.tasks.enqueue_credits_backfill_items", return_value=0)
    @patch("app.tasks.enqueue_genre_backfill_items", return_value=1)
    def test_item_save_requeues_tmdb_tv_genre_backfill_on_identity_change(
        self,
        mock_enqueue_genre_backfill_items,
        _mock_enqueue_credits_backfill_items,
        _mock_enqueue_runtime_backfill_items,
    ):
        item = Item.objects.create(
            media_id="3002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Signal Identity Change",
            image="https://example.com/signal-identity-change.jpg",
            genres=["Drama"],
        )
        MetadataBackfillState.objects.create(
            item=item,
            field=MetadataBackfillField.GENRES,
            strategy_version=tasks.GENRE_BACKFILL_VERSION,
            last_success_at=timezone.now(),
        )
        mock_enqueue_genre_backfill_items.reset_mock()

        signals.schedule_runtime_backfill_on_item_save(
            sender=Item,
            instance=item,
            created=False,
            update_fields={"media_id"},
        )

        self.assertFalse(
            MetadataBackfillState.objects.filter(
                item=item,
                field=MetadataBackfillField.GENRES,
            ).exists(),
        )
        mock_enqueue_genre_backfill_items.assert_called_once_with([item.id])


class CreditsBackfillSignalTests(TestCase):
    @patch("app.tasks.enqueue_credits_backfill_items")
    def test_schedule_credits_backfill_if_needed_keeps_current_tmdb_season_state(
        self,
        mock_enqueue,
    ):
        season_item = Item.objects.create(
            media_id="4001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Signal Season",
            image="https://example.com/signal-season.jpg",
            season_number=1,
        )
        person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="4001",
            name="Signal Person",
            gender=PersonGender.UNKNOWN.value,
        )
        ItemPersonCredit.objects.create(
            item=season_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )
        MetadataBackfillState.objects.create(
            item=season_item,
            field=MetadataBackfillField.CREDITS,
            strategy_version=CREDITS_BACKFILL_VERSION,
            last_success_at=timezone.now(),
        )

        signals._schedule_credits_backfill_if_needed(season_item.id)

        self.assertTrue(
            MetadataBackfillState.objects.filter(
                item=season_item,
                field=MetadataBackfillField.CREDITS,
                strategy_version=CREDITS_BACKFILL_VERSION,
            ).exists(),
        )
        mock_enqueue.assert_not_called()

    @patch("app.tasks.enqueue_credits_backfill_items")
    def test_schedule_credits_backfill_if_needed_requeues_stale_tmdb_season_state(
        self,
        mock_enqueue,
    ):
        season_item = Item.objects.create(
            media_id="4002",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Stale Signal Season",
            image="https://example.com/stale-signal-season.jpg",
            season_number=1,
        )
        person = Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="4002",
            name="Stale Signal Person",
            gender=PersonGender.UNKNOWN.value,
        )
        ItemPersonCredit.objects.create(
            item=season_item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Lead",
        )
        MetadataBackfillState.objects.create(
            item=season_item,
            field=MetadataBackfillField.CREDITS,
            strategy_version=max(CREDITS_BACKFILL_VERSION - 1, 1),
            last_success_at=timezone.now(),
        )

        signals._schedule_credits_backfill_if_needed(season_item.id)

        self.assertTrue(
            MetadataBackfillState.objects.filter(
                item=season_item,
                field=MetadataBackfillField.CREDITS,
                strategy_version=max(CREDITS_BACKFILL_VERSION - 1, 1),
            ).exists(),
        )
        mock_enqueue.assert_called_once_with([season_item.id], countdown=3)
