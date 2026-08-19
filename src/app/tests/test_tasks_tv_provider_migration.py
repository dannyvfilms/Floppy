from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app.models import TV, Item, MediaTypes, Sources, Status
from app.services.tv_provider_migration import TvMigrationResult
from app.tasks_tv_provider_migration import migrate_tv_shows_to_preferred_provider_task


class MigrateTvShowsToPreferredProviderTaskTests(TestCase):
    """Tests for the nightly TVDB provider-migration batch task."""

    def setUp(self):
        """Create a TVDB-preferring user and a TMDB-preferring user."""
        cache.clear()
        self.tvdb_user = get_user_model().objects.create_user(
            username="tvdb-pref",
            password="pw12345",
        )
        self.tvdb_user.tv_metadata_source_default = Sources.TVDB.value
        self.tvdb_user.save()

        self.tmdb_user = get_user_model().objects.create_user(
            username="tmdb-pref",
            password="pw12345",
        )

    def _create_tmdb_show(self, user, media_id, *, anime=False):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value if anime else MediaTypes.TV.value,
            title=f"Show {media_id}",
            image="",
            provider_external_ids={"tvdb_id": f"tvdb-{media_id}"},
        )
        TV.objects.create(item=item, user=user, status=Status.IN_PROGRESS.value)
        return item

    def test_skips_entirely_when_tvdb_not_configured(self):
        """No candidates should be queried or migrated when TVDB is unconfigured."""
        with patch("app.providers.tvdb.enabled", return_value=False):
            result = migrate_tv_shows_to_preferred_provider_task()

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "tvdb_not_configured")

    @patch("app.services.tv_provider_migration.migrate_tv_item_to_tvdb")
    def test_only_considers_shows_tracked_by_a_tvdb_preferring_user(
        self,
        mock_migrate,
    ):
        """A show only tracked by a TMDB-preferring user should be left alone."""
        mock_migrate.return_value = TvMigrationResult(migrated=True)

        tvdb_pref_show = self._create_tmdb_show(self.tvdb_user, "111")
        self._create_tmdb_show(self.tmdb_user, "222")

        with patch("app.providers.tvdb.enabled", return_value=True):
            result = migrate_tv_shows_to_preferred_provider_task()

        self.assertEqual(result["migrated"], 1)
        mock_migrate.assert_called_once()
        (called_item,) = mock_migrate.call_args.args
        self.assertEqual(called_item.pk, tvdb_pref_show.pk)

    @patch("app.services.tv_provider_migration.migrate_tv_item_to_tvdb")
    def test_excludes_grouped_anime_items(self, mock_migrate):
        """Grouped-anime items use a separate TVDB pathway and must not be touched."""
        self._create_tmdb_show(self.tvdb_user, "333", anime=True)

        with patch("app.providers.tvdb.enabled", return_value=True):
            result = migrate_tv_shows_to_preferred_provider_task()

        mock_migrate.assert_not_called()
        self.assertEqual(result["migrated"], 0)

    def test_survives_a_per_item_crash(self):
        """A crash on one show must not stop the rest of the batch from running."""
        self._create_tmdb_show(self.tvdb_user, "444")

        with (
            patch("app.providers.tvdb.enabled", return_value=True),
            patch(
                "app.services.tv_provider_migration.migrate_tv_item_to_tvdb",
                side_effect=Exception("boom"),
            ),
        ):
            result = migrate_tv_shows_to_preferred_provider_task()

        self.assertEqual(result["errored"], 1)
        self.assertEqual(result["migrated"], 0)
