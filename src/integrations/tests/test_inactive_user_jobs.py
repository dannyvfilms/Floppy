"""A user deactivated after a task was queued must not receive new provider
work or tracking-state mutations from that task.

The unambiguous cases are guarded: provider imports (`import_media`, the
single choke point every importer task funnels through) and the Jellyfin
watched-state push. Webhook processors were already gated (see
`test_webhook_async`). Cache-warming jobs (statistics sync, history refresh)
stay enabled on purpose: they read the database and write only caches, which
survives reactivation, and the shared/global maintenance jobs must never be
disabled by one user's state.
"""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from integrations.models import ImportRun
from integrations.tasks._media_imports import import_media, push_jellyfin_watched


class InactiveUserImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="inactive-import")

    def test_import_skips_deactivated_user_without_creating_a_run(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        importer = Mock(name="importer")

        result = import_media(importer, None, self.user.id, "auto")

        self.assertIn("deactivated", result)
        importer.assert_not_called()
        self.assertFalse(
            ImportRun.objects.filter(user=self.user).exists(),
            "a skipped import must not be recorded as an import run",
        )

    def test_import_runs_for_an_active_user(self):
        importer = Mock(
            name="importer",
            return_value=({"created": 0, "updated": 0, "skipped": 0}, []),
        )

        with (
            patch("app.mixins.disable_fetch_releases"),
            patch("integrations.tasks._media_imports.import_progress.tracking"),
        ):
            import_media(importer, None, self.user.id, "auto")

        importer.assert_called_once()


class InactiveUserJellyfinPushTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="inactive-push")

    def test_push_skips_deactivated_user_without_touching_the_server(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with (
            patch(
                "integrations.tasks._media_imports.JellyfinPushSyncService"
            ) as service,
            patch(
                "integrations.tasks._media_imports._jellyfin_health.reprobe_if_broken"
            ) as reprobe,
        ):
            result = push_jellyfin_watched.apply(args=[self.user.id], throw=True).get()

        self.assertIn("deactivated", result)
        service.assert_not_called()
        reprobe.assert_not_called()
