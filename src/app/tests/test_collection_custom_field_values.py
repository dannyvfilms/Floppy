from django.contrib.auth import get_user_model
from django.test import TestCase

from app import helpers
from app.collection_views import _custom_field_values, _ids_ordered_by_custom_field
from app.models import CollectionEntry, Item, MediaTypes, Sources


class CustomFieldValueExtractionTest(TestCase):
    """One field's value is read by the database with its JSON type intact."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cf", password="x")
        self.values = [
            {"2": "Beta", "3": 1},
            {"2": 10},
            {"2": True},
            {"2": 2.5},
            {"2": ""},
            {"3": "other"},
            {},
            {"2": None},
            {"2": False},
        ]
        self.ids = []
        for n, values in enumerate(self.values):
            item = Item.objects.create(
                media_id=str(n),
                source=Sources.MANUAL.value,
                media_type=MediaTypes.BOOK.value,
                title=f"b{n}",
            )
            entry = CollectionEntry.objects.create(
                user=self.user,
                item=item,
                custom_field_values=values,
            )
            self.ids.append(entry.id)
        self.collection = helpers.get_user_collection(self.user, "")

    def test_values_keep_json_types_for_numeric_keys(self):
        got = dict(_custom_field_values(self.collection, 2))
        self.assertEqual(
            [got[pk] for pk in self.ids],
            ["Beta", 10, True, 2.5, "", None, None, None, False],
        )
        self.assertIs(got[self.ids[2]], True)
        self.assertIs(got[self.ids[8]], False)
        # An explicit JSON null decodes to None, the same as a missing key.
        self.assertIsNone(got[self.ids[7]])

    def test_sort_puts_numbers_then_checkboxes_then_text_blanks_last(self):
        class Field:
            id = 2

        ordered = _ids_ordered_by_custom_field(self.collection, Field, "asc")
        i = self.ids
        self.assertEqual(
            ordered,
            [i[3], i[1], i[8], i[2], i[0], i[7], i[6], i[5], i[4]],
        )
