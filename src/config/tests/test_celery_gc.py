"""Initial forks must share the same frozen image as replacement children."""

from unittest.mock import Mock, call, patch

from celery.signals import worker_before_create_process, worker_ready
from django.test import SimpleTestCase

from config import celery


class CeleryGCImageTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch.object(celery, "_parent_image_frozen", False))
        self.collect = self.enterContext(patch.object(celery.gc, "collect"))
        self.freeze = self.enterContext(patch.object(celery.gc, "freeze"))
        self.enterContext(patch("config.run_state.enable_fault_log"))

    def test_first_fork_freezes_before_ready_and_replacements_do_not_refreeze(self):
        events = Mock()
        events.attach_mock(self.collect, "collect")
        events.attach_mock(self.freeze, "freeze")

        worker_before_create_process.send(sender=self)
        self.assertTrue(celery._parent_image_frozen)
        self.assertEqual(events.mock_calls, [call.collect(), call.freeze()])

        worker_ready.send(sender=self)
        for _ in range(3):
            worker_before_create_process.send(sender=self)

        # Repeated freezing would retain transient parent state permanently.
        self.collect.assert_called_once_with()
        self.freeze.assert_called_once_with()

    def test_ready_freezes_when_pool_does_not_send_before_create(self):
        worker_ready.send(sender=self)
        worker_ready.send(sender=self)

        self.assertTrue(celery._parent_image_frozen)
        self.collect.assert_called_once_with()
        self.freeze.assert_called_once_with()

    def test_failed_freeze_can_retry_at_ready(self):
        self.freeze.side_effect = [RuntimeError("freeze failed"), None]
        with self.assertRaisesRegex(RuntimeError, "freeze failed"):
            celery._freeze_parent_image()
        self.assertFalse(celery._parent_image_frozen)

        worker_ready.send(sender=self)

        self.assertTrue(celery._parent_image_frozen)
        self.assertEqual(self.freeze.call_count, 2)

    def test_failed_collection_does_not_mark_image_frozen(self):
        self.collect.side_effect = RuntimeError("collection failed")

        with self.assertRaisesRegex(RuntimeError, "collection failed"):
            celery._freeze_parent_image()

        self.assertFalse(celery._parent_image_frozen)
        self.freeze.assert_not_called()

    def test_child_still_collects_and_freezes_with_inherited_parent_guard(self):
        celery._parent_image_frozen = True

        celery._freeze_child_image()

        self.collect.assert_called_once_with()
        self.freeze.assert_called_once_with()
