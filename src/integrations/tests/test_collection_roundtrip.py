"""Native export/import round trips for custom collection fields.

A backup must carry the field definitions, their values, purchase metadata,
multiple copies and source identity — and land all of it on a *different*
user, whose field ids are their own.
"""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    CollectionEntry,
    CollectionEntrySource,
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldSource,
    CollectionFieldType,
    Item,
    MediaTypes,
    Sources,
)
from integrations import exports
from integrations.imports import yamtrack


def export_csv(user):
    """Return the user's full CSV backup as text."""
    return "".join(exports.generate_rows(user))


def import_csv(user, text, mode="new"):
    """Import a CSV backup for *user* and return the importer's result."""
    stream = BytesIO(text.encode("utf-8"))
    stream.name = "backup.csv"
    return yamtrack.importer(stream, user, mode)


class CollectionRoundTripTests(TestCase):
    """Custom fields, values and copies survive an export/import cycle."""

    def setUp(self):
        """Build a source user with a populated collection."""
        self.source_user = get_user_model().objects.create_user(
            username="source",
            password="12345",
        )
        self.destination_user = get_user_model().objects.create_user(
            username="destination",
            password="12345",
        )

        self.item = Item.objects.get_or_create(
            media_id="10494",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "Perfect Blue", "image": "poster.jpg"},
        )[0]

        group = CollectionFieldGroup.objects.create(
            user=self.source_user,
            name="Condition",
        )
        self.grade = CollectionField.objects.create(
            group=group,
            label="Grade",
            field_type=CollectionFieldType.SELECT,
            options=["Mint", "Good"],
            media_types=[MediaTypes.MOVIE.value],
        )
        self.slabbed = CollectionField.objects.create(
            group=group,
            label="Slabbed",
            field_type=CollectionFieldType.CHECKBOX,
            media_types=[MediaTypes.MOVIE.value],
        )
        CollectionFieldSource.objects.create(
            user=self.source_user,
            source="clz",
            source_key="grade",
            source_label="Grade",
            field=self.grade,
            created_field=True,
        )

        self.first = CollectionEntry.objects.create(
            user=self.source_user,
            item=self.item,
            media_type="bluray",
            purchase_price=Decimal("24.99"),
            purchase_location="Local Shop",
            custom_field_values={
                str(self.grade.id): "Mint",
                str(self.slabbed.id): True,
            },
        )
        self.second = CollectionEntry.objects.create(
            user=self.source_user,
            item=self.item,
            media_type="dvd",
            custom_field_values={str(self.grade.id): "Good"},
        )
        CollectionEntrySource.objects.create(
            user=self.source_user,
            source="clz",
            source_record_id="4412",
            occurrence=0,
            entry=self.first,
        )

    def round_trip(self):
        """Export the source user and import it as the destination user."""
        import_csv(self.destination_user, export_csv(self.source_user))

    def test_field_definitions_are_recreated_for_the_new_user(self):
        """Labels, types and options arrive under the destination user's ids."""
        self.round_trip()

        grade = CollectionField.objects.get(
            group__user=self.destination_user,
            label="Grade",
        )
        self.assertNotEqual(grade.id, self.grade.id)
        self.assertEqual(grade.field_type, CollectionFieldType.SELECT)
        self.assertEqual(grade.options, ["Mint", "Good"])
        self.assertEqual(grade.group.name, "Condition")

    def test_values_are_remapped_onto_destination_field_ids(self):
        """Stored values follow the fields to their new ids."""
        self.round_trip()

        grade = CollectionField.objects.get(
            group__user=self.destination_user,
            label="Grade",
        )
        slabbed = CollectionField.objects.get(
            group__user=self.destination_user,
            label="Slabbed",
        )
        values = [
            entry.custom_field_values
            for entry in CollectionEntry.objects.filter(user=self.destination_user)
        ]
        self.assertIn(
            {str(grade.id): "Mint", str(slabbed.id): True},
            values,
        )

    def test_multiple_copies_and_purchase_metadata_survive(self):
        """Both copies arrive, with their purchase metadata intact."""
        self.round_trip()

        entries = CollectionEntry.objects.filter(user=self.destination_user)
        self.assertEqual(entries.count(), 2)
        priced = entries.get(purchase_price=Decimal("24.99"))
        self.assertEqual(priced.purchase_location, "Local Shop")
        self.assertEqual(priced.media_type, "bluray")

    def test_source_identity_survives(self):
        """A source-linked copy stays linked after the round trip."""
        self.round_trip()

        link = CollectionEntrySource.objects.get(user=self.destination_user)
        self.assertEqual(link.source, "clz")
        self.assertEqual(link.source_record_id, "4412")

    def test_field_provenance_survives(self):
        """The source-to-field mapping is rebuilt for the destination user."""
        self.round_trip()

        mapping = CollectionFieldSource.objects.get(user=self.destination_user)
        self.assertEqual(mapping.source, "clz")
        self.assertEqual(mapping.source_key, "grade")
        self.assertEqual(mapping.field.label, "Grade")

    def test_existing_destination_field_is_reused_not_duplicated(self):
        """A compatible field the destination already has is reused."""
        group = CollectionFieldGroup.objects.create(
            user=self.destination_user,
            name="Mine",
        )
        existing = CollectionField.objects.create(
            group=group,
            label="grade",
            field_type=CollectionFieldType.TEXT,
            media_types=[MediaTypes.BOOK.value],
        )

        self.round_trip()

        matches = CollectionField.objects.filter(
            group__user=self.destination_user,
            label__iexact="grade",
        )
        self.assertEqual(matches.count(), 1)
        existing.refresh_from_db()
        # The destination's own type wins; only its media types widen.
        self.assertEqual(existing.field_type, CollectionFieldType.TEXT)
        self.assertIn(MediaTypes.MOVIE.value, existing.media_types)

    def test_round_trip_into_the_same_user_is_stable(self):
        """Re-importing a user's own backup does not duplicate definitions."""
        import_csv(self.source_user, export_csv(self.source_user))

        self.assertEqual(
            CollectionField.objects.filter(group__user=self.source_user).count(),
            2,
        )

    def test_export_without_custom_fields_still_imports(self):
        """A backup from before this feature has no schema row and still loads."""
        CollectionField.objects.filter(group__user=self.source_user).delete()
        CollectionEntry.objects.filter(user=self.source_user).update(
            custom_field_values={},
        )

        import_csv(self.destination_user, export_csv(self.source_user))

        self.assertEqual(
            CollectionEntry.objects.filter(user=self.destination_user).count(),
            2,
        )
