from contextlib import ExitStack
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_migration import AnimeMigrationError

META = {"max_progress": 13, "episodes": []}


class AnimeCompletionAutoMigrateTests(TestCase):
    """Completing a flat MAL anime should migrate it to episode tracking."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="a", password="x")
        self.item = Item.objects.create(
            media_id="10087",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Fate/Zero",
        )

    def _make(self, status=Status.PLANNING.value):
        with patch("app.providers.services.get_media_metadata", return_value=META):
            return Anime.objects.create(item=self.item, user=self.user, status=status)

    def _env(self, stack, *, series_id="275798", migrate_side_effect=None):
        """Enter the shared patches and return the migrate mock."""
        stack.enter_context(
            patch("app.providers.services.get_media_metadata", return_value=META),
        )
        stack.enter_context(
            patch(
                "app.services.metadata_resolution.provider_is_enabled",
                return_value=True,
            ),
        )
        stack.enter_context(
            patch(
                "app.services.metadata_resolution.metadata_default_source",
                return_value=Sources.TVDB.value,
            ),
        )
        stack.enter_context(
            patch(
                "integrations.anime_mapping.resolve_provider_series_id",
                return_value=series_id,
            ),
        )
        return stack.enter_context(
            patch(
                "app.services.anime_migration.migrate_flat_anime_to_grouped",
                side_effect=migrate_side_effect,
            ),
        )

    def test_completing_flat_mal_anime_triggers_migration(self):
        anime = self._make()
        with ExitStack() as stack:
            migrate = self._env(stack)
            anime.status = Status.COMPLETED.value
            anime.save()
        migrate.assert_called_once()
        args, _ = migrate.call_args
        self.assertEqual(args[0], self.user)
        self.assertEqual(args[1], self.item)
        self.assertEqual(args[2], Sources.TVDB.value)

    def test_no_migration_without_provider_mapping(self):
        anime = self._make()
        with ExitStack() as stack:
            migrate = self._env(stack, series_id=None)
            anime.status = Status.COMPLETED.value
            anime.save()
        migrate.assert_not_called()

    def test_no_migration_when_not_completed(self):
        anime = self._make()
        with ExitStack() as stack:
            migrate = self._env(stack)
            anime.status = Status.PAUSED.value
            anime.save()
        migrate.assert_not_called()

    def test_migration_error_is_non_fatal(self):
        anime = self._make()
        with ExitStack() as stack:
            self._env(
                stack, migrate_side_effect=AnimeMigrationError("no mapping season")
            )
            anime.status = Status.COMPLETED.value
            anime.save()  # must not raise
        anime.refresh_from_db()
        self.assertEqual(anime.status, Status.COMPLETED.value)

    def test_end_to_end_creates_episode_records(self):
        # Drive the real migration (only the provider/network calls are stubbed)
        # to prove completion produces actual Episode watch records.
        from app.models import Episode
        from app.services.tracking_hydration import HydratedItemResult

        anime = self._make()

        tv_item = Item.objects.create(
            media_id="275798",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Fate/Zero",
        )
        season_meta = {
            "title": "Fate/Zero Season 1",
            "image": "s.jpg",
            "episodes": [{"episode_number": n} for n in range(1, 14)],
        }

        def meta_side_effect(media_type, *args, **kwargs):
            # anime_migration and process_status share one get_media_metadata.
            if media_type == "tv_with_seasons":
                return {"season/1": season_meta}
            return META  # flat anime max_progress lookup

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.providers.services.get_media_metadata",
                    side_effect=meta_side_effect,
                ),
            )
            stack.enter_context(
                patch(
                    "app.services.metadata_resolution.provider_is_enabled",
                    return_value=True,
                ),
            )
            stack.enter_context(
                patch(
                    "app.services.metadata_resolution.metadata_default_source",
                    return_value=Sources.TVDB.value,
                ),
            )
            stack.enter_context(
                patch(
                    "integrations.anime_mapping.resolve_provider_series_id",
                    return_value="275798",
                ),
            )
            stack.enter_context(
                patch(
                    "integrations.anime_mapping.find_entries_for_mal_id",
                    return_value=[
                        {"tvdb_id": "275798", "tvdb_season": 1, "tvdb_epoffset": 0}
                    ],
                ),
            )
            stack.enter_context(
                patch(
                    "app.services.anime_migration.ensure_item_metadata",
                    return_value=HydratedItemResult(
                        item=tv_item, metadata={"title": "Fate/Zero"}, created=False
                    ),
                ),
            )
            stack.enter_context(
                patch("app.services.anime_migration.upsert_provider_links"),
            )

            anime.status = Status.COMPLETED.value
            anime.save()

        # 13 watched episodes created under the TVDB series...
        self.assertEqual(
            Episode.objects.filter(
                related_season__related_tv__user=self.user,
                item__media_id="275798",
                item__source=Sources.TVDB.value,
            ).count(),
            13,
        )
        # ...and the flat MAL entry is now marked migrated.
        anime.refresh_from_db()
        self.assertEqual(anime.migrated_to_item_id, tv_item.id)

    def test_already_migrated_not_remigrated(self):
        other = Item.objects.create(
            media_id="275798",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Fate/Zero",
        )
        anime = self._make()
        anime.migrated_to_item = other
        with patch("app.providers.services.get_media_metadata", return_value=META):
            anime.save()

        with ExitStack() as stack:
            migrate = self._env(stack)
            anime.status = Status.COMPLETED.value
            anime.save()
        migrate.assert_not_called()
