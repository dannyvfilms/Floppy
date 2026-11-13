from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    Game,
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
    Status,
)
from app.providers.services import ProviderNotConfiguredError
from app.tasks_game_groups import (
    _users_by_item,
    count_game_group_backfill_items,
    populate_game_group_data_for_items,
    reconcile_game_groups_backfill,
    reopen_unconfigured_game_groups,
)


class GameGroupBackfillTests(TestCase):
    def _game(self, media_id="123", **fields):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title=f"Game {media_id}",
            **fields,
        )

    @patch("app.tasks_game_groups.credentials.is_configured")
    def test_group_backfill_prefers_a_user_with_igdb_credentials(
        self,
        mock_configured,
    ):
        item = self._game()
        other = get_user_model().objects.create_user(username="other")
        owner = get_user_model().objects.create_user(username="owner")
        Game.objects.create(
            item=item,
            user=other,
            status=Status.IN_PROGRESS.value,
        )
        Game.objects.create(
            item=item,
            user=owner,
            status=Status.COMPLETED.value,
        )
        mock_configured.side_effect = lambda slug, user: user.username == "owner"

        self.assertEqual(_users_by_item([item])(item), owner)

    @patch("app.tasks_game_groups.services.get_media_metadata")
    def test_backfill_populates_franchise_and_collection(self, mock_metadata):
        item = self._game()
        mock_metadata.return_value = {
            "provider_franchise_id": "10",
            "provider_franchise_name": "Mario",
            "provider_collection_id": "20",
            "provider_collection_name": "Super Mario",
        }

        result = populate_game_group_data_for_items([item.id])

        item.refresh_from_db()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(item.provider_franchise_name, "Mario")
        self.assertEqual(item.provider_collection_name, "Super Mario")

    @patch("app.tasks_game_groups.services.get_media_metadata")
    def test_provider_without_groups_still_completes(self, mock_metadata):
        item = self._game()
        mock_metadata.return_value = {
            "provider_franchise_id": "",
            "provider_franchise_name": "",
            "provider_collection_id": "",
            "provider_collection_name": "",
        }

        result = populate_game_group_data_for_items([item.id])

        self.assertEqual(result["updated"], 1)
        self.assertEqual(count_game_group_backfill_items(), 0)

    @patch("app.tasks_game_groups.enqueue_game_group_backfill_items", return_value=1)
    def test_reconcile_selects_games_missing_group_data(self, mock_enqueue):
        self._game(
            media_id="1",
            provider_franchise_name="Mario",
            provider_collection_name="Super Mario",
        )
        missing = self._game(media_id="2")

        result = reconcile_game_groups_backfill()

        self.assertEqual(result["selected"], 1)
        self.assertEqual(mock_enqueue.call_args.args[0], [missing.id])


    @patch("app.tasks_game_groups.services.get_media_metadata")
    def test_unconfigured_provider_does_not_burn_attempts(self, mock_metadata):
        item = self._game()
        mock_metadata.side_effect = ProviderNotConfiguredError("igdb", "not set")

        populate_game_group_data_for_items([item.id])

        self.assertFalse(
            MetadataBackfillState.objects.filter(
                item=item, field=MetadataBackfillField.GAME_GROUPS
            ).exists()
        )

    @patch("app.tasks_game_groups.reconcile_game_groups_backfill.apply_async")
    @patch("app.tasks_game_groups.credentials.is_configured", return_value=True)
    def test_reopen_resets_given_up_unconfigured_failures(
        self, _configured, mock_reconcile
    ):
        stuck = self._game("1")
        other = self._game("2")
        for item, error in (
            (stuck, "exception: ProviderNotConfiguredError"),
            (other, "exception: timeout"),
        ):
            MetadataBackfillState.objects.create(
                item=item,
                field=MetadataBackfillField.GAME_GROUPS,
                fail_count=6,
                give_up=True,
                last_error=error,
            )

        self.assertEqual(reopen_unconfigured_game_groups(), 1)

        states = {
            s.item_id: s
            for s in MetadataBackfillState.objects.filter(
                field=MetadataBackfillField.GAME_GROUPS
            )
        }
        self.assertFalse(states[stuck.id].give_up)
        self.assertEqual(states[stuck.id].fail_count, 0)
        self.assertTrue(states[other.id].give_up)
        mock_reconcile.assert_called_once()
