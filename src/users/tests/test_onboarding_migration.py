from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase

migration_0118 = import_module(
    "users.migrations.0118_user_onboarding_selected_sources_and_more",
)


class OnboardingBackfillMigrationTests(TestCase):
    """The onboarding fields migration must not force existing users through setup."""

    def test_backfills_existing_users_as_completed(self):
        """Users that exist when the migration runs land on completed, not not_started."""
        user = get_user_model().objects.create_user(
            username="preexisting", password="testpass123"
        )
        self.assertEqual(user.onboarding_status, "not_started")

        migration_0118.backfill_existing_users_as_onboarded(apps, None)

        user.refresh_from_db()
        self.assertEqual(user.onboarding_status, "completed")
        self.assertEqual(user.onboarding_step, "done")

    def test_users_created_after_migration_keep_the_default(self):
        """A user created after the (one-time) backfill still gets the fresh-signup default."""
        get_user_model().objects.create_user(
            username="already_here", password="testpass123"
        )
        migration_0118.backfill_existing_users_as_onboarded(apps, None)

        new_user = get_user_model().objects.create_user(
            username="brand_new", password="testpass123"
        )

        self.assertEqual(new_user.onboarding_status, "not_started")
        self.assertEqual(new_user.onboarding_step, "media_types")
