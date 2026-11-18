"""An item's library bucket is never empty (prompt 63).

The bucket is part of an item's identity. An empty one let the same title be
stored twice: once empty (written by ``bulk_create``, which skips ``save()``)
and once with its media type. The database now refuses an empty bucket and
bulk writes fill it the way ``save()`` does.
"""

import ast
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from app.models import Item, MediaTypes, Sources

SRC = Path(settings.BASE_DIR)
ITEM_CONSTRUCTORS = {"Item", "item_model"}
RULE = (
    "Every Item built in a function that bulk-creates items must name its "
    "library_media_type (usually the media type): bulk_create skips save(), "
    "and an item's library bucket is never empty. See "
    "docs/agents/media_type_integration.md, 'The library bucket is never empty'."
)


class ItemBucketNeverEmptyTests(TestCase):
    def _music(self, **extra):
        return Item(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Song",
            **extra,
        )

    def test_bulk_create_fills_the_bucket(self):
        """The probe's bulk-created music item was stored with ''."""
        Item.objects.bulk_create([self._music()])

        self.assertEqual(Item.objects.get().library_media_type, MediaTypes.MUSIC.value)

    def test_a_second_copy_of_a_bulk_created_item_is_refused(self):
        """Probe ``bucket:bulk_create``: the normal create used to be accepted."""
        Item.objects.bulk_create([self._music()])

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._music().save()
        self.assertEqual(Item.objects.count(), 1)
        item, created = Item.objects.get_or_create(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
        )
        self.assertFalse(created)

    def test_bulk_update_fills_the_bucket_it_writes(self):
        item = Item.objects.create(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Song",
        )
        item.library_media_type = ""
        Item.objects.bulk_update([item], ["library_media_type"])

        item.refresh_from_db()
        self.assertEqual(item.library_media_type, MediaTypes.MUSIC.value)

    def test_database_refuses_an_empty_bucket(self):
        item = Item.objects.create(
            media_id="m1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MUSIC.value,
            title="Song",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Item.objects.filter(pk=item.pk).update(library_media_type="")

    def test_grouped_anime_bucket_is_still_allowed(self):
        Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Show",
        )
        Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.assertEqual(Item.objects.count(), 2)


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _constructor_name(call):
    return _name(call.func)


def _bulk_creates_items(function):
    for node in ast.walk(function):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "bulk_create"
        ):
            continue
        manager = node.func.value
        owner = manager.value if isinstance(manager, ast.Attribute) else manager
        if _name(owner) in ITEM_CONSTRUCTORS:
            return True
    return False


def unbucketed_bulk_items(source, path="<string>"):
    """Return ``path:line`` of each Item built without a bucket next to a bulk_create."""
    tree = ast.parse(source)
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _bulk_creates_items(function):
            continue
        for node in ast.walk(function):
            if not (
                isinstance(node, ast.Call)
                and _constructor_name(node) in ITEM_CONSTRUCTORS
            ):
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            # pk-only rows (bulk_update) and **spec rows are not new identities.
            if "media_type" not in keywords or None in keywords:
                continue
            if "library_media_type" not in keywords:
                found.append(f"{path}:{node.lineno}")
    return sorted(set(found))


class BulkCreatedItemsNameTheirBucketTests(SimpleTestCase):
    """Production code names the bucket; the queryset fill is the safety net.

    Tests bulk-create thousands of fixture items and rely on the fill in
    ``ItemQuerySet.bulk_create``, so they are not scanned.
    """

    def test_every_bulk_created_item_names_its_bucket(self):
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            parts = path.relative_to(SRC).parts
            if "tests" in parts or "migrations" in parts or parts[0].startswith("."):
                continue
            offenders += unbucketed_bulk_items(
                path.read_text(encoding="utf-8"),
                str(path.relative_to(SRC)),
            )
        self.assertEqual(offenders, [], RULE)

    def test_the_scan_finds_a_missing_bucket(self):
        source = (
            "def f(ids):\n"
            "    Item.objects.bulk_create(\n"
            "        [Item(media_id=i, source='manual', media_type='music') for i in ids]\n"
            "    )\n"
        )
        self.assertEqual(unbucketed_bulk_items(source), ["<string>:3"])
        fixed = source.replace(
            "media_type='music'", "media_type='music', library_media_type='music'"
        )
        self.assertEqual(unbucketed_bulk_items(fixed), [])
