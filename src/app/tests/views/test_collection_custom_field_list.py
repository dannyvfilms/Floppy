"""Collection page: search, filter and sort by the user's custom fields (#809).

Custom field values live in ``CollectionEntry.custom_field_values``, keyed by
``str(field.id)``. A key such as ``"2"`` is compiled by Django as an array
index (``$[2]``) on SQLite, so a key lookup silently matches nothing. These
tests therefore pin the behaviour, not the query that produces it.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldType,
    Item,
    MediaTypes,
    Sources,
)


class CollectionCustomFieldListTest(TestCase):
    """Imported custom fields must be usable from the Collection page."""

    def setUp(self):
        """Create a user with a few fields and volumes carrying values."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.other = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        self.client.login(**self.credentials)

        group = CollectionFieldGroup.objects.create(user=self.user, name="Shelf")
        self.box = self._field(
            group,
            "Storage Box",
            CollectionFieldType.SELECT,
            options=["Box A", "Box B"],
        )
        self.grade = self._field(group, "Grade", CollectionFieldType.NUMBER)
        self.key = self._field(group, "Is Key Comic", CollectionFieldType.CHECKBOX)
        self.notes = self._field(group, "Notes", CollectionFieldType.TEXT)
        self.book_only = self._field(
            group,
            "ISBN Shelf",
            CollectionFieldType.SELECT,
            options=["Top"],
            media_types=[MediaTypes.BOOK.value],
        )

        self.vol = {}
        for number, box, grade, key, note in (
            (1, "Box A", 9.4, True, "Signed by Obata"),
            (2, "Box B", 10.5, False, ""),
            (3, "Box A", 8.0, False, "Water damage"),
            (4, None, None, None, None),
        ):
            values = {}
            if box is not None:
                values = {
                    str(self.box.id): box,
                    str(self.grade.id): grade,
                    str(self.key.id): key,
                    str(self.notes.id): note,
                }
            self.vol[number] = self._entry(self.user, f"Death Note #{number}", values)

        # The other user's data must never match, whatever the filter says.
        self._entry(
            self.other,
            "Death Note #9",
            {str(self.box.id): "Box A", str(self.notes.id): "Signed by Obata"},
        )

    def _field(self, group, label, field_type, options=None, media_types=None):
        return CollectionField.objects.create(
            group=group,
            label=label,
            field_type=field_type,
            options=options or [],
            media_types=media_types or [MediaTypes.MANGA.value],
        )

    def _entry(self, user, title, values):
        item = Item.objects.create(
            media_id=f"{user.username}-{title}",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MANGA.value,
            title=title,
            image="",
        )
        return CollectionEntry.objects.create(
            user=user,
            item=item,
            custom_field_values=values,
        )

    def titles(self, **params):
        """Return the titles the Collection page lists for *params*."""
        response = self.client.get(reverse("collection_list"), params)
        self.assertEqual(response.status_code, 200)
        return [entry.item.title for entry in response.context["collection_entries"]]

    # -- search ---------------------------------------------------------

    def test_search_matches_a_custom_field_value(self):
        """Searching a storage box finds the volumes in it, not just titles."""
        self.assertCountEqual(
            self.titles(q="box a"),
            ["Death Note #1", "Death Note #3"],
        )

    def test_search_matches_free_text_values(self):
        """Notes typed into a text field are searchable."""
        self.assertEqual(self.titles(q="obata"), ["Death Note #1"])

    def test_search_still_matches_titles(self):
        """Title search keeps working beside the value search."""
        self.assertEqual(self.titles(q="Note #2"), ["Death Note #2"])

    def test_search_does_not_match_field_ids(self):
        """A field's numeric id is plumbing, so searching it finds nothing."""
        self._entry(self.user, "Shelf Check", {str(self.book_only.id): "Top"})

        self.assertNotIn("Shelf Check", self.titles(q=str(self.book_only.id)))

    # -- filter ---------------------------------------------------------

    def test_filter_by_dropdown_field(self):
        """Choosing Box A keeps only the volumes stored there."""
        self.assertCountEqual(
            self.titles(field=self.box.id, field_value="Box A"),
            ["Death Note #1", "Death Note #3"],
        )

    def test_filter_by_checkbox_field(self):
        """A checkbox filters on yes and no."""
        self.assertEqual(
            self.titles(field=self.key.id, field_value="true"),
            ["Death Note #1"],
        )
        self.assertCountEqual(
            self.titles(field=self.key.id, field_value="false"),
            ["Death Note #2", "Death Note #3"],
        )

    def test_filter_ignores_another_users_field(self):
        """A field the user does not own filters nothing."""
        group = CollectionFieldGroup.objects.create(user=self.other, name="Theirs")
        theirs = self._field(group, "Theirs", CollectionFieldType.SELECT)

        self.assertEqual(len(self.titles(field=theirs.id, field_value="Box A")), 4)

    def test_filter_ignores_unknown_field(self):
        """A stale or garbled field id leaves the list unfiltered."""
        self.assertEqual(len(self.titles(field="nope", field_value="Box A")), 4)
        self.assertEqual(len(self.titles(field=999999, field_value="Box A")), 4)

    def test_filter_offers_only_dropdown_and_checkbox_fields(self):
        """Text and number fields are searched, so only the others get a filter (all types)."""
        response = self.client.get(reverse("collection_list"))

        filters = {
            item["label"]: item["choices"]
            for item in response.context["custom_field_filters"]
        }
        self.assertEqual(
            filters,
            {
                "Storage Box": [("Box A", "Box A"), ("Box B", "Box B")],
                "Is Key Comic": [("true", "Yes"), ("false", "No")],
                "ISBN Shelf": [("Top", "Top")],
            },
        )

    def test_filter_offers_only_fields_for_the_chosen_media_type(self):
        """A field that applies to books is not offered on the manga page."""
        response = self.client.get(reverse("collection_list"), {"type": "book"})
        labels = [item["label"] for item in response.context["custom_field_filters"]]
        self.assertEqual(labels, ["ISBN Shelf"])

        response = self.client.get(reverse("collection_list"), {"type": "manga"})
        labels = [item["label"] for item in response.context["custom_field_filters"]]
        self.assertEqual(labels, ["Storage Box", "Is Key Comic"])

    # -- sort -----------------------------------------------------------

    def test_sort_by_number_field_is_numeric(self):
        """10.5 sorts after 9.4, which a text sort would get wrong."""
        self.assertEqual(
            self.titles(sort=f"field_{self.grade.id}", direction="asc"),
            ["Death Note #3", "Death Note #1", "Death Note #2", "Death Note #4"],
        )

    def test_sort_descending_keeps_blanks_last(self):
        """Volumes with no value stay at the bottom in both directions."""
        self.assertEqual(
            self.titles(sort=f"field_{self.grade.id}", direction="desc"),
            ["Death Note #2", "Death Note #1", "Death Note #3", "Death Note #4"],
        )

    def test_explicit_null_values_sort_with_blanks(self):
        """A stored null counts as no value, not as the text "null"."""
        self._entry(
            self.user,
            "Death Note #5",
            {str(self.box.id): None, str(self.grade.id): None},
        )

        self.assertEqual(
            self.titles(sort=f"field_{self.grade.id}", direction="desc"),
            [
                "Death Note #2",
                "Death Note #1",
                "Death Note #3",
                "Death Note #5",
                "Death Note #4",
            ],
        )
        self.assertEqual(
            self.titles(sort=f"field_{self.box.id}", direction="desc"),
            [
                "Death Note #2",
                "Death Note #3",
                "Death Note #1",
                "Death Note #5",
                "Death Note #4",
            ],
        )

    def test_sort_by_dropdown_field_orders_by_text(self):
        """Dropdown values sort alphabetically, ties broken by newest first."""
        self.assertEqual(
            self.titles(sort=f"field_{self.box.id}", direction="asc"),
            ["Death Note #3", "Death Note #1", "Death Note #2", "Death Note #4"],
        )

    def test_sort_choices_list_the_users_fields(self):
        """The sort menu offers each field next to Title and Date Collected."""
        response = self.client.get(reverse("collection_list"))

        choices = dict(response.context["sort_choices"])
        self.assertEqual(choices[f"field_{self.grade.id}"], "Grade")
        self.assertIn("title", choices)

        response = self.client.get(reverse("collection_list"), {"type": "manga"})
        self.assertNotIn(
            f"field_{self.book_only.id}",
            dict(response.context["sort_choices"]),
        )

    def test_sort_by_another_users_field_falls_back_to_default(self):
        """An id the user does not own sorts by date collected."""
        group = CollectionFieldGroup.objects.create(user=self.other, name="Theirs")
        theirs = self._field(group, "Theirs", CollectionFieldType.NUMBER)

        response = self.client.get(
            reverse("collection_list"),
            {"sort": f"field_{theirs.id}"},
        )

        self.assertEqual(response.context["sort_by"], "collected_at")

    def test_custom_sort_pages_through_every_entry_once(self):
        """Paging a custom-field sort neither skips nor repeats volumes."""
        for number in range(5, 30):
            self._entry(
                self.user,
                f"Death Note #{number}",
                {str(self.grade.id): float(number)},
            )
        params = {"sort": f"field_{self.grade.id}", "direction": "asc"}

        first = self.titles(**params, page=1)
        second = self.titles(**params, page=2)

        self.assertEqual(len(first), 20)
        self.assertEqual(len(first) + len(second), 29)
        self.assertEqual(len(set(first + second)), 29)
        self.assertEqual(second[-1], "Death Note #4")

    def test_filter_and_sort_combine(self):
        """A filter and a sort apply together."""
        self.assertEqual(
            self.titles(
                field=self.box.id,
                field_value="Box A",
                sort=f"field_{self.grade.id}",
                direction="desc",
            ),
            ["Death Note #1", "Death Note #3"],
        )
