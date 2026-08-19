from datetime import UTC, datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from app.models import (
    CreditRoleType,
    Item,
    ItemPersonCredit,
    ItemStudioCredit,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Person,
    PersonGender,
    Sources,
    Studio,
)
from app.providers import services
from app.services import imdb_game_credits


def _make_game(media_id, title, year=2025, **extra):
    release = datetime(year, 1, 1, tzinfo=UTC) if year else None
    return Item.objects.create(
        media_id=media_id,
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
        title=title,
        image="http://example.com/game.jpg",
        release_datetime=release,
        **extra,
    )


class ResolveGameImdbIdsTests(TestCase):
    def test_exact_title_and_year_match_resolves(self):
        game = _make_game("igdb-1", "Dispatch", year=2025)

        with patch(
            "app.providers.imdb_datasets.download_videogame_title_index",
            return_value={"tt1111111": ("Dispatch", 2025)},
        ):
            updated = imdb_game_credits.resolve_game_imdb_ids()

        game.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(game.provider_external_ids.get("imdb_id"), "tt1111111")

    def test_year_outside_tolerance_does_not_match(self):
        _make_game("igdb-2", "Dispatch", year=2025)

        with patch(
            "app.providers.imdb_datasets.download_videogame_title_index",
            return_value={"tt1111111": ("Dispatch", 2019)},
        ):
            updated = imdb_game_credits.resolve_game_imdb_ids()

        self.assertEqual(updated, 0)

    def test_ambiguous_title_match_is_skipped(self):
        _make_game("igdb-3", "Common Name", year=2025)

        with patch(
            "app.providers.imdb_datasets.download_videogame_title_index",
            return_value={
                "tt1111111": ("Common Name", 2025),
                "tt2222222": ("Common Name", 2025),
            },
        ):
            updated = imdb_game_credits.resolve_game_imdb_ids()

        self.assertEqual(updated, 0)

    def test_already_resolved_items_are_excluded(self):
        _make_game(
            "igdb-4",
            "Dispatch",
            year=2025,
            provider_external_ids={"imdb_id": "tt0000000"},
        )

        with patch(
            "app.providers.imdb_datasets.download_videogame_title_index",
        ) as mock_download:
            updated = imdb_game_credits.resolve_game_imdb_ids()

        self.assertEqual(updated, 0)
        mock_download.assert_not_called()


class SyncGameCreditsFromImdbTests(TestCase):
    def setUp(self):
        self.item = _make_game(
            "igdb-5",
            "Dispatch",
            year=2025,
            provider_external_ids={"imdb_id": "tt1111111"},
        )

    def test_syncs_cast_and_crew_under_imdb_source(self):
        principals = {
            "tt1111111": [
                {
                    "nconst": "nm0000001",
                    "category": "actor",
                    "job": "",
                    "characters": '["Sam"]',
                    "ordering": 1,
                },
                {
                    "nconst": "nm0000002",
                    "category": "director",
                    "job": "Director",
                    "characters": "",
                    "ordering": 2,
                },
            ],
        }
        names = {"nm0000001": "Alice Actor", "nm0000002": "Bob Director"}

        synced = imdb_game_credits.sync_game_credits_from_imdb(principals, names)

        self.assertEqual(synced, 1)
        cast = ItemPersonCredit.objects.get(
            item=self.item, role_type=CreditRoleType.CAST.value
        )
        crew = ItemPersonCredit.objects.get(
            item=self.item, role_type=CreditRoleType.CREW.value
        )

        self.assertEqual(cast.person.source, Sources.IMDB.value)
        self.assertEqual(cast.person.source_person_id, "nm0000001")
        self.assertEqual(cast.role, "Sam")
        self.assertEqual(crew.person.source, Sources.IMDB.value)
        self.assertEqual(crew.department, "Directing")

        # The game item's own source is untouched — no IGDB-namespace collision.
        self.assertFalse(Person.objects.filter(source=Sources.IGDB.value).exists())

        state = MetadataBackfillState.objects.get(
            item=self.item, field=MetadataBackfillField.CREDITS.value
        )
        self.assertIsNotNone(state.last_success_at)

    def test_rerun_skips_already_synced_items(self):
        principals = {
            "tt1111111": [
                {
                    "nconst": "nm0000001",
                    "category": "actor",
                    "job": "",
                    "characters": "",
                    "ordering": 1,
                },
            ],
        }
        names = {"nm0000001": "Alice Actor"}

        first = imdb_game_credits.sync_game_credits_from_imdb(principals, names)
        second = imdb_game_credits.sync_game_credits_from_imdb(principals, names)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

    def test_missing_principals_records_failure_without_raising(self):
        synced = imdb_game_credits.sync_game_credits_from_imdb({}, {})

        self.assertEqual(synced, 0)
        state = MetadataBackfillState.objects.get(
            item=self.item, field=MetadataBackfillField.CREDITS.value
        )
        self.assertEqual(state.fail_count, 1)

    def test_rerun_can_fill_missing_crew_when_cast_already_exists(self):
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm-existing-cast",
            name="Existing Cast",
            image="",
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            role="Old Role",
        )
        principals = {
            "tt1111111": [
                {
                    "nconst": "nm-existing-cast",
                    "category": "actor",
                    "job": "",
                    "characters": '["Sam"]',
                    "ordering": 1,
                },
                {
                    "nconst": "nm0000002",
                    "category": "director",
                    "job": "Director",
                    "characters": "",
                    "ordering": 2,
                },
            ],
        }
        names = {"nm-existing-cast": "Existing Cast", "nm0000002": "Bob Director"}

        synced = imdb_game_credits.sync_game_credits_from_imdb(principals, names)

        self.assertEqual(synced, 1)
        self.assertTrue(
            ItemPersonCredit.objects.filter(
                item=self.item,
                role_type=CreditRoleType.CREW.value,
                department="Directing",
            ).exists(),
        )


class BackfillMissingPersonProfilesTests(TestCase):
    def test_fills_image_and_gender_for_blank_imdb_people_via_tmdb_search(self):
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000010",
            name="Alice Actor",
            image="",
        )
        with patch(
            "app.providers.tmdb.search_person_profile",
            return_value={
                "image": "https://image.tmdb.org/t/p/h632/alice.jpg",
                "gender": "female",
            },
        ) as mock_search:
            updated = imdb_game_credits.backfill_missing_person_profiles()

        mock_search.assert_called_once_with("Alice Actor")
        person.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(person.image, "https://image.tmdb.org/t/p/h632/alice.jpg")
        self.assertEqual(person.gender, PersonGender.FEMALE.value)

    def test_only_fills_gender_when_image_already_present(self):
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000015",
            name="Has Image No Gender",
            image="https://example.com/existing.jpg",
            gender=PersonGender.UNKNOWN.value,
        )
        with patch(
            "app.providers.tmdb.search_person_profile",
            return_value={
                "image": "https://image.tmdb.org/t/p/h632/other.jpg",
                "gender": "male",
            },
        ):
            updated = imdb_game_credits.backfill_missing_person_profiles()

        person.refresh_from_db()
        self.assertEqual(updated, 1)
        # Existing image is not clobbered by a fresh (unverified) name match.
        self.assertEqual(person.image, "https://example.com/existing.jpg")
        self.assertEqual(person.gender, PersonGender.MALE.value)

    def test_leaves_person_alone_when_tmdb_finds_nothing(self):
        person = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000011",
            name="Nobody Findable",
            image="",
        )
        with patch("app.providers.tmdb.search_person_profile", return_value=None):
            updated = imdb_game_credits.backfill_missing_person_profiles()

        person.refresh_from_db()
        self.assertEqual(updated, 0)
        self.assertEqual(person.image, "")
        self.assertEqual(person.gender, PersonGender.UNKNOWN.value)

    def test_skips_people_with_image_and_known_gender(self):
        Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000012",
            name="Already Has Image",
            image="https://example.com/existing.jpg",
            gender=PersonGender.MALE.value,
        )
        with patch("app.providers.tmdb.search_person_profile") as mock_search:
            updated = imdb_game_credits.backfill_missing_person_profiles()

        mock_search.assert_not_called()
        self.assertEqual(updated, 0)

    def test_ignores_non_imdb_people(self):
        Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="10",
            name="Tmdb Native Person",
            image="",
        )
        with patch("app.providers.tmdb.search_person_profile") as mock_search:
            updated = imdb_game_credits.backfill_missing_person_profiles()

        mock_search.assert_not_called()
        self.assertEqual(updated, 0)

    def test_continues_when_one_tmdb_lookup_fails(self):
        failed = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000013",
            name="Rate Limited Person",
            image="",
        )
        succeeded = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000014",
            name="Working Person",
            image="",
        )

        def _search(name):
            if name == "Rate Limited Person":
                raise services.ProviderAPIError(
                    Sources.TMDB.value, Exception("rate limited")
                )
            return {
                "image": "https://image.tmdb.org/t/p/h632/working.jpg",
                "gender": "male",
            }

        with patch("app.providers.tmdb.search_person_profile", side_effect=_search):
            updated = imdb_game_credits.backfill_missing_person_profiles()

        failed.refresh_from_db()
        succeeded.refresh_from_db()
        self.assertEqual(updated, 1)
        self.assertEqual(failed.image, "")
        self.assertEqual(succeeded.image, "https://image.tmdb.org/t/p/h632/working.jpg")
        self.assertEqual(succeeded.gender, PersonGender.MALE.value)


class BackfillMissingGameStudiosTests(TestCase):
    def test_backfills_igdb_studios_for_imdb_resolved_games(self):
        item = _make_game(
            "igdb-6",
            "Dispatch",
            year=2025,
            provider_external_ids={"imdb_id": "tt1111111"},
        )

        with patch(
            "app.providers.services.get_media_metadata",
            return_value={
                "studios_full": [
                    {
                        "studio_id": "44",
                        "name": "AdHoc Studio",
                        "logo": "https://images.igdb.com/logo.png",
                        "sort_order": 0,
                    },
                ],
            },
        ):
            updated = imdb_game_credits.backfill_missing_game_studios()

        self.assertEqual(updated, 1)
        studio = Studio.objects.get(source=Sources.IGDB.value, source_studio_id="44")
        self.assertTrue(
            ItemStudioCredit.objects.filter(item=item, studio=studio).exists()
        )

    def test_skips_games_that_already_have_studios(self):
        item = _make_game(
            "igdb-7",
            "Dispatch",
            year=2025,
            provider_external_ids={"imdb_id": "tt1111111"},
        )
        studio = Studio.objects.create(
            source=Sources.IGDB.value,
            source_studio_id="55",
            name="Existing Studio",
        )
        ItemStudioCredit.objects.create(item=item, studio=studio)

        with patch("app.providers.services.get_media_metadata") as mock_metadata:
            updated = imdb_game_credits.backfill_missing_game_studios()

        mock_metadata.assert_not_called()
        self.assertEqual(updated, 0)
