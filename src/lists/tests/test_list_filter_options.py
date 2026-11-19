"""The filter menu's options come from SQL, not from every item (BENCH-12 E)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import Item, MediaTypes, Sources
from app.tests.catalogue_fixtures import build_list
from lists.models import CustomList, CustomListItem
from lists.smart_rules import build_filter_data_for_items

PROVIDERS = {
    "US": {
        "flatrate": [
            {"provider_id": 8, "provider_name": "Netflix"},
            {"provider_id": 9, "provider_name": "Prime Video"},
        ],
        "free": [{"provider_id": 73, "provider_name": "Tubi"}],
        "buy": [{"provider_id": 2, "provider_name": "Apple TV"}],
    },
    "GB": {"flatrate": [{"provider_id": 39, "provider_name": "Now"}]},
}


def _item(media_id, **fields):
    return Item.objects.create(
        media_id=str(media_id),
        source=fields.pop("source", Sources.TMDB.value),
        media_type=fields.pop("media_type", MediaTypes.MOVIE.value),
        title=f"Title {media_id}",
        image="https://example.com/x.jpg",
        **fields,
    )


class FilterOptionValuesTests(TestCase):
    """Every option the Python loop produced is still produced, and nothing else."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="o", password="x")
        cls.owner.watch_provider_region = "US"
        cls.owner.save()
        cls.items = [
            _item(
                1,
                genres=["Drama", " Comedy ", ""],
                implied_genres=["Noir"],
                languages=["en", "fr"],
                country=" US ",
                release_datetime=datetime(1999, 12, 31, 23, 30, tzinfo=UTC),
                watch_providers=PROVIDERS,
                authors=[{"name": "Ann Author"}, {"person": "Bo Person"}, " Cy "],
            ),
            _item(
                2,
                genres=["Drama", "Action"],
                languages="ja",
                format="ebook",
                platforms=["PC", " "],
                media_type=MediaTypes.BOOK.value,
                source=Sources.OPENLIBRARY.value,
                authors="Solo Writer",
            ),
            _item(3, genres=[], languages="", watch_providers={"GB": {}}),
        ]

    def _options(self, item_ids):
        return build_filter_data_for_items(
            self.owner,
            item_ids,
            [MediaTypes.MOVIE.value, MediaTypes.BOOK.value],
            precomputed_tags=[],
            include_list_options=False,
        )

    def test_values(self):
        data = self._options({item.id for item in self.items})
        self.assertEqual(data["genres"], ["Action", "Comedy", "Drama"])
        self.assertEqual(data["implied_genres"], ["Noir"])
        self.assertEqual(
            data["years"],
            [
                {"value": "1999", "label": "1999"},
                {"value": "unknown", "label": "Unknown"},
            ],
        )
        self.assertEqual(
            [entry["value"] for entry in data["sources"]],
            sorted([Sources.TMDB.value, Sources.OPENLIBRARY.value]),
        )
        self.assertEqual(
            [entry["value"] for entry in data["languages"]], ["en", "fr", "ja"]
        )
        self.assertEqual([entry["value"] for entry in data["countries"]], ["US"])
        self.assertEqual([entry["value"] for entry in data["origins"]], ["US"])
        self.assertEqual([entry["value"] for entry in data["platforms"]], ["PC"])
        self.assertEqual(data["formats"], [{"value": "ebook", "label": "eBook"}])
        self.assertEqual(
            [entry["value"] for entry in data["authors"]],
            ["Ann Author", "Bo Person", "Cy", "Solo Writer"],
        )
        # Streaming and free in the viewer's region; not "buy", not other regions.
        self.assertEqual(
            [entry["value"] for entry in data["providers"]],
            ["Netflix", "Prime Video", "Tubi"],
        )

    def test_queryset_and_id_set_agree(self):
        custom_list = CustomList.objects.create(name="L", owner=self.owner)
        for item in self.items:
            CustomListItem.objects.create(
                custom_list=custom_list, item=item, added_by=self.owner
            )
        self.assertEqual(
            self._options(custom_list.items.values_list("id", flat=True)),
            self._options({item.id for item in self.items}),
        )

    def test_no_region_reads_no_providers(self):
        owner = SimpleNamespace(watch_provider_region="UNSET")
        data = build_filter_data_for_items(
            owner,
            {item.id for item in self.items},
            [MediaTypes.MOVIE.value],
            precomputed_tags=[],
            include_list_options=False,
        )
        self.assertEqual(data["providers"], [])
        self.assertFalse(data["show_providers"])

    def test_empty(self):
        data = self._options(set())
        self.assertEqual(data["genres"], [])
        self.assertEqual(data["years"], [])


class LongListFilterOptionsTests(TestCase):
    """A 600-item list builds its menu with the same SQL as a 10-item list."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="o", password="x")
        cls.owner.watch_provider_region = "US"
        cls.owner.save()
        cls.short = build_list(cls.owner, None, items=10, prefix="short")
        cls.long = build_list(cls.owner, None, items=600, prefix="long")

    def _queries(self, custom_list):
        with CaptureQueriesContext(connection) as queries:
            build_filter_data_for_items(
                self.owner,
                custom_list.items.values_list("id", flat=True),
                [MediaTypes.MOVIE.value],
                precomputed_tags=[],
                include_list_options=False,
            )
        return [query["sql"] for query in queries.captured_queries]

    def test_query_count_and_size_stay_flat(self):
        short_sql = self._queries(self.short)
        long_sql = self._queries(self.long)
        self.assertEqual(len(short_sql), len(long_sql))
        # The list stays a subquery; no statement carries the item ids.
        self.assertLess(max(map(len, long_sql)), max(map(len, short_sql)) + 50)
        # The provider JSON is only walked in SQL, never selected per title.
        for sql in long_sql:
            self.assertNotIn('"app_item"."watch_providers"', sql)
