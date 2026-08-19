from unittest.mock import patch

from django.test import TestCase

from app.models import (
    CREDITS_BACKFILL_VERSION,
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    MetadataBackfillField,
    Person,
    Sources,
)
from app.tasks_backfill_state import _record_backfill_success
from app.tasks_imdb import (
    backfill_imdb_game_person_profiles,
    refresh_imdb_game_credits_from_datasets,
)


class RefreshImdbGameCreditsTaskTests(TestCase):
    def test_backfills_images_even_when_no_new_credits_to_sync(self):
        """Regression: a game already synced in a prior run has no new tconsts to
        fetch, but its cast can still be missing images from before this backfill
        existed — that shouldn't skip the image backfill step entirely.
        """
        item = Item.objects.create(
            media_id="igdb-1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Dispatch",
            image="http://example.com/game.jpg",
            provider_external_ids={"imdb_id": "tt1111111"},
        )
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000001",
            name="Alice Actor",
            image="",
        )
        ItemPersonCredit.objects.create(
            item=item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Sam",
        )
        # Mark the game as already synced with the current strategy so
        # _resolved_game_items excludes it — the "no new credits" scenario.
        _record_backfill_success(
            item,
            MetadataBackfillField.CREDITS.value,
            strategy_version=CREDITS_BACKFILL_VERSION,
        )

        with (
            patch(
                "app.providers.imdb_datasets.download_videogame_title_index",
                return_value={},
            ),
            # Defensive: the excluded item means these should never be called,
            # but a live multi-hundred-MB dataset download must never be a
            # possible test outcome if the filtering contract changes again.
            patch(
                "app.providers.imdb_datasets.download_principals",
                return_value={},
            ) as mock_principals,
            patch(
                "app.providers.imdb_datasets.download_names",
                return_value={},
            ),
            patch(
                "app.providers.tmdb.search_person_profile",
                return_value={
                    "image": "https://image.tmdb.org/t/p/h632/alice.jpg",
                    "gender": "female",
                },
            ) as mock_search,
            patch(
                "app.services.imdb_game_credits.backfill_missing_game_studios",
                return_value=1,
            ) as mock_studios,
        ):
            result = refresh_imdb_game_credits_from_datasets()

        mock_principals.assert_not_called()
        mock_studios.assert_called_once_with()
        mock_search.assert_called_once_with("Alice Actor")
        person.refresh_from_db()
        self.assertEqual(person.image, "https://image.tmdb.org/t/p/h632/alice.jpg")
        self.assertEqual(result["studios_backfilled"], 1)
        self.assertEqual(result["profiles_backfilled"], 1)
        self.assertEqual(result["synced"], 0)


class BackfillImdbGamePersonProfilesTaskTests(TestCase):
    def test_task_returns_profile_backfill_count(self):
        Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000001",
            name="Alice Actor",
            image="",
        )

        with patch(
            "app.providers.tmdb.search_person_profile",
            return_value={
                "image": "https://image.tmdb.org/t/p/h632/alice.jpg",
                "gender": "female",
            },
        ):
            result = backfill_imdb_game_person_profiles()

        self.assertEqual(result, {"profiles_backfilled": 1})
