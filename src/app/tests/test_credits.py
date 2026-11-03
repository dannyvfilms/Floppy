from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app import credits
from app.models import (
    CreditRoleType,
    Item,
    ItemPersonCredit,
    ItemStudioCredit,
    MediaTypes,
    Movie,
    Person,
    Sources,
    Studio,
)


class AuthorCreditSyncTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            media_id="book-1",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Book One",
            image="http://example.com/book-one.jpg",
        )

    def test_sync_item_author_credits_creates_people_and_credits(self):
        credits.sync_item_author_credits(
            self.item,
            [
                {
                    "person_id": "OL1A",
                    "name": "Author One",
                    "image": "http://example.com/author1.jpg",
                    "role": "Author",
                    "sort_order": 0,
                },
                {
                    "person_id": "OL2A",
                    "name": "Author Two",
                    "image": "http://example.com/author2.jpg",
                    "role": "Co-Author",
                    "sort_order": 1,
                },
            ],
        )

        self.assertEqual(
            Person.objects.filter(source=Sources.OPENLIBRARY.value).count(),
            2,
        )
        author_credits = ItemPersonCredit.objects.filter(
            item=self.item,
            role_type=CreditRoleType.AUTHOR.value,
        ).order_by("sort_order")
        self.assertEqual(author_credits.count(), 2)
        self.assertEqual(
            list(author_credits.values_list("person__source_person_id", flat=True)),
            ["OL1A", "OL2A"],
        )

    def test_sync_item_author_credits_replaces_only_author_role_rows(self):
        cast_person = Person.objects.create(
            source=Sources.OPENLIBRARY.value,
            source_person_id="CAST1",
            name="Narrator",
        )
        old_author = Person.objects.create(
            source=Sources.OPENLIBRARY.value,
            source_person_id="OLD1",
            name="Old Author",
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=cast_person,
            role_type=CreditRoleType.CAST.value,
            role="Narrator",
        )
        ItemPersonCredit.objects.create(
            item=self.item,
            person=old_author,
            role_type=CreditRoleType.AUTHOR.value,
            role="Author",
        )

        credits.sync_item_author_credits(
            self.item,
            [
                {
                    "person_id": "OLNEW",
                    "name": "New Author",
                    "image": "http://example.com/new-author.jpg",
                    "role": "Author",
                    "sort_order": 0,
                },
            ],
        )

        self.assertEqual(
            ItemPersonCredit.objects.filter(
                item=self.item,
                role_type=CreditRoleType.CAST.value,
            ).count(),
            1,
        )
        author_credits = ItemPersonCredit.objects.filter(
            item=self.item,
            role_type=CreditRoleType.AUTHOR.value,
        )
        self.assertEqual(author_credits.count(), 1)
        self.assertEqual(author_credits.first().person.source_person_id, "OLNEW")


class CreditSyncSourceTests(TestCase):
    def test_sync_item_credits_from_metadata_uses_item_source(self):
        item = Item.objects.create(
            media_id="book-2",
            source=Sources.HARDCOVER.value,
            media_type=MediaTypes.BOOK.value,
            title="Book Two",
            image="http://example.com/book-two.jpg",
        )

        credits.sync_item_credits_from_metadata(
            item,
            {
                "cast": [
                    {
                        "person_id": "100",
                        "name": "Reader Person",
                        "role": "Reader",
                    },
                ],
                "crew": [],
                "studios_full": [
                    {
                        "studio_id": "200",
                        "name": "Publisher House",
                    },
                ],
            },
        )

        person = Person.objects.get(source_person_id="100")
        studio = Studio.objects.get(source_studio_id="200")
        self.assertEqual(person.source, Sources.HARDCOVER.value)
        self.assertEqual(studio.source, Sources.HARDCOVER.value)
        self.assertTrue(
            ItemPersonCredit.objects.filter(
                item=item,
                person=person,
                role_type=CreditRoleType.CAST.value,
            ).exists(),
        )
        self.assertTrue(
            ItemStudioCredit.objects.filter(item=item, studio=studio).exists(),
        )

    def test_sync_item_credits_from_metadata_honors_explicit_person_source(self):
        item = Item.objects.create(
            media_id="game-1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Some Game",
            image="http://example.com/game.jpg",
        )

        credits.sync_item_credits_from_metadata(
            item,
            {
                "cast": [
                    {"person_id": "nm001", "name": "Actor", "role": "Sam"},
                ],
                "crew": [],
            },
            person_source=Sources.IMDB.value,
        )

        person = Person.objects.get(source_person_id="nm001")
        self.assertEqual(person.source, Sources.IMDB.value)
        self.assertNotEqual(person.source, item.source)

    def test_upsert_person_profile_supports_non_tmdb_sources(self):
        person = credits.upsert_person_profile(
            Sources.OPENLIBRARY.value,
            "OL11A",
            {
                "name": "Open Author",
                "image": "http://example.com/author.jpg",
                "known_for_department": "Author",
                "biography": "Author bio",
                "gender": "unknown",
                "birth_date": "1965-01-02",
                "death_date": None,
                "place_of_birth": "London",
            },
        )

        self.assertIsNotNone(person)
        person = Person.objects.get(
            source=Sources.OPENLIBRARY.value, source_person_id="OL11A"
        )
        self.assertEqual(person.source, Sources.OPENLIBRARY.value)
        self.assertEqual(person.source_person_id, "OL11A")
        self.assertEqual(person.name, "Open Author")
        self.assertEqual(person.biography, "Author bio")


class CreditSyncQueryBudgetTests(TestCase):
    """A credits sync costs a fixed handful of queries however long the cast is.

    A film with a thousand credits used to issue about 6,000 queries on its
    first sync and 3,000 on every resync (production log, 9,902 in one
    request): an ``update_or_create`` per person, plus two reads per deleted
    credit from its Discover signal.
    """

    PEOPLE = 300
    # Independent of PEOPLE: the read of existing people/studios, the writes
    # (chunked), the credit delete and re-create. Well under one per person.
    MAX_QUERIES = 40

    def setUp(self):
        self.item = Item.objects.create(
            media_id="movie-big",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Big Cast",
            image="http://example.com/big.jpg",
        )
        self.metadata = {
            "cast": [
                {"person_id": i, "name": f"Actor {i}", "role": "Role", "order": i}
                for i in range(1, self.PEOPLE + 1)
            ],
            "crew": [
                {
                    "person_id": 10_000 + i,
                    "name": f"Crew {i}",
                    "job": "Editor",
                    "department": "Editing",
                }
                for i in range(self.PEOPLE)
            ],
            "studios_full": [
                {"studio_id": i, "name": f"Studio {i}"} for i in range(1, 51)
            ],
        }

    def _sync_queries(self):
        with CaptureQueriesContext(connection) as context:
            credits.sync_item_credits_from_metadata(self.item, self.metadata)
        return len(context.captured_queries)

    def test_first_sync_query_count_does_not_grow_with_cast(self):
        self.assertLessEqual(self._sync_queries(), self.MAX_QUERIES)
        self.assertEqual(
            ItemPersonCredit.objects.filter(item=self.item).count(),
            self.PEOPLE * 2,
        )
        self.assertEqual(ItemStudioCredit.objects.filter(item=self.item).count(), 50)

    def test_resync_query_count_does_not_grow_with_cast(self):
        credits.sync_item_credits_from_metadata(self.item, self.metadata)
        self.assertLessEqual(self._sync_queries(), self.MAX_QUERIES)
        self.assertEqual(
            ItemPersonCredit.objects.filter(item=self.item).count(),
            self.PEOPLE * 2,
        )

    def test_resync_updates_changed_people_and_keeps_profile_fields(self):
        credits.sync_item_credits_from_metadata(self.item, self.metadata)
        Person.objects.filter(source_person_id="4").update(biography="Kept bio")
        self.metadata["cast"][3]["name"] = "Renamed Actor"

        credits.sync_item_credits_from_metadata(self.item, self.metadata)

        person = Person.objects.get(source=Sources.TMDB.value, source_person_id="4")
        self.assertEqual(person.name, "Renamed Actor")
        self.assertEqual(person.biography, "Kept bio")
        self.assertEqual(
            Person.objects.filter(source=Sources.TMDB.value).count(),
            self.PEOPLE * 2,
        )

    def test_person_credited_as_cast_and_crew_is_one_row_with_both_credits(self):
        self.metadata = {
            "cast": [{"person_id": 7, "name": "Multi", "role": "Lead"}],
            "crew": [
                {"person_id": 7, "name": "Multi", "job": "Director", "department": "Directing"},
            ],
        }

        credits.sync_item_credits_from_metadata(self.item, self.metadata)

        self.assertEqual(Person.objects.filter(source_person_id="7").count(), 1)
        self.assertEqual(
            sorted(
                ItemPersonCredit.objects.filter(item=self.item).values_list(
                    "role_type",
                    flat=True,
                ),
            ),
            [CreditRoleType.CAST.value, CreditRoleType.CREW.value],
        )

    @patch("app.signals.discover_tab_cache.invalidate_for_media_change")
    def test_replacing_credits_invalidates_discover_once_per_tracking_user(
        self,
        mock_invalidate,
    ):
        user = get_user_model().objects.create_user(username="watcher", password="x")
        Movie.objects.create(user=user, item=self.item)
        credits.sync_item_credits_from_metadata(self.item, self.metadata)
        mock_invalidate.reset_mock()

        credits.sync_item_credits_from_metadata(self.item, self.metadata)

        mock_invalidate.assert_called_once_with(user.id, MediaTypes.MOVIE.value)


class MissingCreditsBackfillQueryTests(TestCase):
    """The backfill reads only item ids, so it must not sort or join people (#1791).

    ``ItemPersonCredit`` orders by ``sort_order, person__name`` by default; on a
    library with hundreds of thousands of credits that made person pages time out.
    """

    def test_id_reads_are_unordered_and_skip_the_person_join(self):
        item = Item.objects.create(
            media_id="movie-1791",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Backfill",
            image="http://example.com/b.jpg",
        )
        person = Person.objects.create(
            source=Sources.TMDB.value, source_person_id="1", name="Actor"
        )
        ItemPersonCredit.objects.create(
            item=item,
            person=person,
            role_type=CreditRoleType.CAST.value,
            sort_order=0,
        )

        with CaptureQueriesContext(connection) as queries:
            credits.missing_credits_backfill_item_ids([item.id])

        credit_sql = [
            q["sql"].upper()
            for q in queries
            if "APP_ITEMPERSONCREDIT" in q["sql"].upper()
            or "APP_ITEMSTUDIOCREDIT" in q["sql"].upper()
        ]
        self.assertTrue(credit_sql)
        for sql in credit_sql:
            self.assertNotIn("ORDER BY", sql)
            self.assertNotIn("APP_PERSON", sql)
