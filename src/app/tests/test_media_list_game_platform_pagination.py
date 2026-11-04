"""Regression coverage for game-platform filtering in the library-query engine."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.library_query import (
    FilterValues,
    LibraryQuery,
    LibraryQueryExecutor,
    SortSpec,
)
from app.library_query.adapters import filter_values_from_rules
from app.library_query.spec import STATUS_MATCH_LATEST
from app.models import Game, Item, MediaTypes, Sources, Status


class GamePlatformSqlPaginationTests(TestCase):
    """Keep game platform filtering correct across SQL-backed pages."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="game-platform-pagination",
            password="12345",
        )
        cls.user.game_enabled = True
        cls.user.save(update_fields=["game_enabled"])

        items = [
            Item(
                media_id=f"game-platform-{index}",
                source=Sources.IGDB.value,
                media_type=MediaTypes.GAME.value,
                title=f"Game {index:02d}",
                platforms=["PC"] if index % 2 == 0 else ["PlayStation 5"],
            )
            for index in range(40)
        ]
        Item.objects.bulk_create(items)

        created_items = list(
            Item.objects.filter(
                media_id__startswith="game-platform-",
                media_type=MediaTypes.GAME.value,
            ).order_by("id")
        )

        Game.objects.bulk_create(
            [
                Game(
                    item=item,
                    user=cls.user,
                    status=Status.COMPLETED.value,
                )
                for item in created_items
            ]
        )

    def _page(self, filters, offset, limit=10):
        query = LibraryQuery(
            media_types=(MediaTypes.GAME.value,),
            filters=filters,
            sort=SortSpec(key="title", direction="asc"),
        )
        return LibraryQueryExecutor(self.user, query).page(offset, limit)

    def test_platform_filter_tiles_sql_pages_without_gaps(self):
        """A JSON-backed game platform filter remains correct across pages."""
        filters = FilterValues(platforms=("PC",))

        first = self._page(filters, 0)
        second = self._page(filters, 10)

        self.assertTrue(first.used_sql)
        self.assertTrue(second.used_sql)
        self.assertEqual(first.total, 20)
        self.assertEqual(second.total, 20)

        items = [*first.items, *second.items]
        self.assertEqual(len(items), 20)
        self.assertEqual(len({item.pk for item in items}), 20)
        self.assertTrue(all("PC" in item.platforms for item in items))
        self.assertEqual(
            [item.title for item in items],
            [f"Game {index:02d}" for index in range(0, 40, 2)],
        )

    def test_smart_rule_platform_forms_use_same_engine(self):
        """Legacy singular and current plural platform rules resolve identically."""
        for rules in (
            {"platform": "PC"},
            {"platforms": ("PC",)},
        ):
            with self.subTest(rules=rules):
                filters = filter_values_from_rules(
                    rules,
                    default_status_match=STATUS_MATCH_LATEST,
                )
                page = self._page(filters, 0, limit=50)

                self.assertTrue(page.used_sql)
                self.assertEqual(page.total, 20)
                self.assertTrue(
                    all("PC" in item.platforms for item in page.items),
                )
