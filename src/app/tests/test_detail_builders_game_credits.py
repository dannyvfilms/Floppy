from django.test import TestCase

from app.detail_builders import _build_detail_link_sections, _build_detail_person_rows
from app.models import (
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    Person,
    Sources,
)


class GameCastRowFromCreditsTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            media_id="igdb-1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Dispatch",
            image="http://example.com/game.jpg",
            provider_external_ids={"imdb_id": "tt1111111"},
        )
        self.actor = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000001",
            name="Alice Actor",
            image="http://example.com/alice.jpg",
        )
        self.director = Person.objects.create(
            source=Sources.IMDB.value,
            source_person_id="nm0000002",
            name="Bob Director",
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=self.actor,
            role_type=CreditRoleType.CAST.value,
            role="Sam",
            sort_order=1,
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=self.director,
            role_type=CreditRoleType.CREW.value,
            role="Director",
            department="Directing",
            sort_order=2,
        )

    def test_cast_and_crew_rows_populate_from_item_person_credit(self):
        rows = _build_detail_person_rows({"media_id": "igdb-1"}, item=self.item)

        cast_items = rows["cast_row"]["items"]
        crew_items = rows["crew_row"]["items"]
        self.assertEqual(len(cast_items), 1)
        self.assertEqual(cast_items[0]["name"], "Alice Actor")
        self.assertEqual(cast_items[0]["role"], "Sam")
        self.assertEqual(len(crew_items), 1)
        self.assertEqual(crew_items[0]["name"], "Bob Director")

    def test_cast_entries_omit_person_id_to_avoid_broken_profile_links(self):
        rows = _build_detail_person_rows({"media_id": "igdb-1"}, item=self.item)

        for entry in rows["cast_row"]["items"] + rows["crew_row"]["items"]:
            self.assertNotIn("person_id", entry)

    def test_non_game_items_are_unaffected(self):
        movie_item = Item.objects.create(
            media_id="tmdb-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
            image="http://example.com/movie.jpg",
        )
        rows = _build_detail_person_rows({"media_id": "tmdb-1"}, item=movie_item)
        self.assertEqual(rows["cast_row"]["items"], [])
        self.assertEqual(rows["crew_row"]["items"], [])

    def test_existing_media_metadata_cast_takes_priority_over_credits(self):
        media_metadata = {
            "media_id": "igdb-1",
            "cast": [{"person_id": "1", "name": "From Metadata"}],
        }
        rows = _build_detail_person_rows(media_metadata, item=self.item)
        self.assertEqual(rows["cast_row"]["items"][0]["name"], "From Metadata")


class GameImdbLinkChipTests(TestCase):
    def test_imdb_chip_appears_when_resolved(self):
        item = Item.objects.create(
            media_id="igdb-2",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Dispatch",
            image="http://example.com/game.jpg",
            provider_external_ids={"imdb_id": "tt34996965"},
        )
        sections = _build_detail_link_sections(
            {"media_id": "igdb-2"},
            MediaTypes.GAME.value,
            Sources.IGDB.value,
            Sources.IGDB.value,
            item=item,
        )
        external_section = next(s for s in sections if s["title"] == "External links")
        imdb_entry = next(
            e for e in external_section["entries"] if e["label"] == "IMDb"
        )
        self.assertEqual(imdb_entry["url"], "https://www.imdb.com/title/tt34996965/")

    def test_no_imdb_chip_when_unresolved(self):
        item = Item.objects.create(
            media_id="igdb-3",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Some Unmatched Game",
            image="http://example.com/game.jpg",
        )
        sections = _build_detail_link_sections(
            {"media_id": "igdb-3"},
            MediaTypes.GAME.value,
            Sources.IGDB.value,
            Sources.IGDB.value,
            item=item,
        )
        for section in sections:
            for entry in section["entries"]:
                self.assertNotEqual(entry["label"], "IMDb")
