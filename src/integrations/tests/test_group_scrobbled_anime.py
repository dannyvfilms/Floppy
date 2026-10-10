from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.services.anime_migration import AnimeMigrationError
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor

MAPPING_ENTRIES = [{"tmdb_id": "12345", "season_number": 2, "episode_offset": 12}]
MAPPING_DATA = {"tmdb_show:12345:s2": {"mal:999": {"13-24": "1-12"}}}
PAYLOAD = {"media_type": "episode", "completed": True}


@patch(
    "app.providers.tmdb.tv_with_seasons",
    side_effect=lambda _id, seasons: {f"season/{season}": {"episodes": []} for season in seasons},
)
@patch("app.services.metadata_resolution.upsert_provider_links")
@patch(
    "integrations.webhooks.anime_mappings.find_entries_for_mal_id",
    return_value=MAPPING_ENTRIES,
)
@patch(
    "integrations.webhooks.anime_mappings.fetch_mapping_data",
    return_value=MAPPING_DATA,
)
@patch(
    "app.providers.mal.anime",
    return_value={"title": "Cour Two", "image": "", "max_progress": 12},
)
class GroupScrobbledAnimeTests(TestCase):
    """A scrobbled MAL episode converts a flat entry when the user opts in."""

    def setUp(self):
        """Create a user tracking a flat MAL entry at episode 3."""
        self.user = get_user_model().objects.create_user(username="grouper")
        self.item = Item.objects.create(
            media_id="999",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Cour Two",
        )
        self.anime = Anime.objects.create(
            item=self.item,
            user=self.user,
            progress=3,
            status=Status.IN_PROGRESS.value,
        )
        self.processor = GenericScrobbleProcessor()

    def _scrobble(self, episode_number=4):
        with patch.object(self.processor, "_handle_tv_episode") as handle_tv:
            result = self.processor._handle_anime(
                "999", episode_number, PAYLOAD, self.user
            )
        return result, handle_tv

    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_opted_in_converts_and_logs_the_mapped_episode(self, migrate, *_):
        """The flat entry is converted and the episode lands on the TMDB season."""
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        result, handle_tv = self._scrobble()

        self.assertTrue(result)
        migrate.assert_called_once_with(self.user, self.item, Sources.TMDB.value)
        handle_tv.assert_called_once_with(
            "12345",
            2,
            16,
            PAYLOAD,
            self.user,
            library_media_type=MediaTypes.ANIME.value,
        )
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 3)

    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_split_entry_logs_the_season_that_holds_the_episode(
        self, migrate, metadata, fetch, *_,
    ):
        """Regression: the first mapped season was used for every episode,
        so MAL episode 20 of an entry split 13 + 12 became S1E20, not S2E7.
        """
        metadata.return_value = {"title": "Split", "image": "", "max_progress": 25}
        fetch.return_value = {
            "tmdb_show:12345:s1": {"mal:999": {"1-13": "1-13"}},
            "tmdb_show:12345:s2": {"mal:999": {"1-12": "14-25"}},
        }
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        _, handle_tv = self._scrobble(episode_number=20)

        self.assertEqual(handle_tv.call_args.args[:3], ("12345", 2, 7))

    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_uncovered_episode_stays_flat(self, migrate, metadata, fetch, *_):
        """No season covers the episode, so nothing is converted."""
        metadata.return_value = {"title": "Split", "image": "", "max_progress": 25}
        fetch.return_value = {"tmdb_show:12345:s1": {"mal:999": {"1-13": "1-13"}}}
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        _, handle_tv = self._scrobble(episode_number=20)

        migrate.assert_not_called()
        handle_tv.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 20)

    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_opted_out_keeps_the_flat_entry(self, migrate, *_):
        """Without the setting only the flat progress moves."""
        result, handle_tv = self._scrobble()

        self.assertTrue(result)
        migrate.assert_not_called()
        handle_tv.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 4)

    @patch(
        "app.services.anime_migration.migrate_flat_anime_to_grouped",
        side_effect=AnimeMigrationError("season too short"),
    )
    def test_refused_conversion_falls_back_to_flat(self, _migrate, *_):
        """A refused conversion never loses the scrobble."""
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        result, handle_tv = self._scrobble()

        self.assertTrue(result)
        handle_tv.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 4)


    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_missing_tmdb_season_keeps_the_flat_entry(self, migrate, *mocks):
        """Regression: the entry was converted before the episode was known
        to be loggable, so a missing TMDB season lost the play for good.
        """
        tv_with_seasons = mocks[-1]
        tv_with_seasons.side_effect = None
        tv_with_seasons.return_value = {}
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        result, handle_tv = self._scrobble()

        self.assertTrue(result)
        migrate.assert_not_called()
        handle_tv.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 4)

    @patch("app.services.anime_migration.migrate_flat_anime_to_grouped")
    def test_tmdb_outage_during_conversion_falls_back_to_flat(self, migrate, *_):
        """Regression: TMDB failing in the conversion preflight aborted the
        scrobble, so the play was recorded nowhere.
        """
        from unittest.mock import MagicMock

        from app.providers.services import ProviderAPIError

        migrate.side_effect = ProviderAPIError(
            "tmdb", MagicMock(response=MagicMock(status_code=503)),
        )
        self.user.group_scrobbled_anime = True
        self.user.save(update_fields=["group_scrobbled_anime"])

        result, handle_tv = self._scrobble()

        self.assertTrue(result)
        handle_tv.assert_not_called()
        self.anime.refresh_from_db()
        self.assertEqual(self.anime.progress, 4)


class GroupScrobbledAnimeToggleTests(TestCase):
    """The Sync to Trackers page toggles the setting."""

    def test_toggle(self):
        """Posting enabled=true turns it on; omitting it turns it off."""
        user = get_user_model().objects.create_user(username="toggler")
        self.client.force_login(user)
        url = reverse("update_group_scrobbled_anime")

        self.client.post(url, {"enabled": "true"})
        user.refresh_from_db()
        self.assertTrue(user.group_scrobbled_anime)

        self.client.post(url, {})
        user.refresh_from_db()
        self.assertFalse(user.group_scrobbled_anime)
