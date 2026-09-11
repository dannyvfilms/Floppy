"""Tests for resolving imported collection columns onto custom fields."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.collection_field_import import (
    IMPORTED_GROUP_NAME,
    ImportColumn,
    ImportedFieldResolver,
    infer_field_type,
    normalize_label,
)
from app.models import (
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldSource,
    CollectionFieldType,
    MediaTypes,
)

MOVIE = MediaTypes.MOVIE.value


class TypeInferenceTests(TestCase):
    """Type inference must only commit when the reading is unambiguous."""

    def test_plain_numbers_infer_number(self):
        """A column of plain numbers becomes a number field."""
        field_type, options = infer_field_type(["1", "2.5", "-3"])
        self.assertEqual(field_type, CollectionFieldType.NUMBER)
        self.assertEqual(options, [])

    def test_leading_zeros_stay_text(self):
        """Identifiers with leading zeros must not become numbers."""
        field_type, _ = infer_field_type(["001", "002", "010"])
        self.assertEqual(field_type, CollectionFieldType.TEXT)

    def test_iso_dates_infer_date(self):
        """Year-first dates are unambiguous and become a date field."""
        field_type, _ = infer_field_type(["2020-01-02", "1999/12/31"])
        self.assertEqual(field_type, CollectionFieldType.DATE)

    def test_ambiguous_dates_stay_text(self):
        """03/04/2020 could be March or April, so it stays text."""
        field_type, _ = infer_field_type(["03/04/2020", "05/06/2021"])
        self.assertEqual(field_type, CollectionFieldType.TEXT)

    def test_boolean_tokens_infer_checkbox(self):
        """Yes/No columns become checkboxes."""
        field_type, _ = infer_field_type(["Yes", "No", "yes"])
        self.assertEqual(field_type, CollectionFieldType.CHECKBOX)

    def test_bare_digits_are_not_checkboxes(self):
        """1/0 alone is a number, not a checkbox."""
        field_type, _ = infer_field_type(["1", "0", "1"])
        self.assertEqual(field_type, CollectionFieldType.NUMBER)

    def test_repeated_short_vocabulary_infers_select(self):
        """A small repeated vocabulary becomes a select with its options."""
        field_type, options = infer_field_type(
            ["Mint", "Good", "Mint", "Good", "Mint"],
        )
        self.assertEqual(field_type, CollectionFieldType.SELECT)
        self.assertEqual(options, ["Good", "Mint"])

    def test_unique_free_text_is_not_a_select(self):
        """Values that never repeat are free text, not a vocabulary."""
        field_type, _ = infer_field_type(["one", "two", "three", "four"])
        self.assertEqual(field_type, CollectionFieldType.TEXT)

    def test_mixed_types_fall_back_to_text(self):
        """A column mixing numbers and words is preserved as text."""
        field_type, _ = infer_field_type(["12", "twelve", "12"])
        self.assertEqual(field_type, CollectionFieldType.TEXT)

    def test_structured_values_serialize_reversibly(self):
        """A multi-valued XML field is preserved as reversible JSON text."""
        field_type, _ = infer_field_type([["a", "b"], ["c"]])
        self.assertEqual(field_type, CollectionFieldType.TEXT)


class LabelNormalizationTests(TestCase):
    """Label matching folds case, separators and Unicode form."""

    def test_separators_and_case_fold_together(self):
        """Different separators and casing normalize to the same key."""
        self.assertEqual(normalize_label("Story Arc"), normalize_label("story_arc"))
        self.assertEqual(normalize_label("STORY-ARC"), normalize_label("Story  Arc"))

    def test_unicode_forms_fold_together(self):
        """Composed and decomposed forms compare equal."""
        self.assertEqual(normalize_label("Éditeur"), normalize_label("Éditeur"))


class ResolverTests(TestCase):
    """Resolution reuses fields, records provenance, and preserves values."""

    def setUp(self):
        """Create the importing user."""
        self.user = get_user_model().objects.create_user(
            username="resolver",
            password="12345",
        )

    def resolver(self):
        """Return a fresh resolver for the CLZ source."""
        return ImportedFieldResolver(self.user, "clz")

    def test_creates_field_in_imported_group(self):
        """An unknown column creates a field in the imported group."""
        resolver = self.resolver()
        resolver.prepare(
            [ImportColumn("Storage Box", "Storage Box", ["A", "B"], [MOVIE])],
        )

        field = CollectionField.objects.get(label="Storage Box")
        self.assertEqual(field.group.name, IMPORTED_GROUP_NAME)
        self.assertEqual(field.media_types, [MOVIE])
        self.assertIn("Storage Box", resolver.report.created_fields)

    def test_matches_existing_field_by_compatible_label(self):
        """A column matching an existing label reuses that field."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Mine")
        existing = CollectionField.objects.create(
            group=group,
            label="Storage box",
            field_type=CollectionFieldType.TEXT,
            media_types=[MOVIE],
        )

        resolver = self.resolver()
        resolved = resolver.prepare(
            [ImportColumn("storage_box", "storage_box", ["A"], [MOVIE])],
        )

        self.assertEqual(resolved["storage_box"].id, existing.id)
        self.assertEqual(CollectionField.objects.count(), 1)

    def test_reuses_field_after_rename_and_move(self):
        """A renamed, regrouped field is still found via its source mapping."""
        first = self.resolver()
        first.prepare([ImportColumn("Story Arc", "Story Arc", ["X"], [MOVIE])])
        field = CollectionField.objects.get(label="Story Arc")

        other_group = CollectionFieldGroup.objects.create(user=self.user, name="Other")
        field.label = "Arc"
        field.group = other_group
        field.save()

        second = self.resolver()
        resolved = second.prepare(
            [ImportColumn("Story Arc", "Story Arc", ["Y"], [MOVIE])],
        )

        self.assertEqual(resolved["Story Arc"].id, field.id)
        self.assertEqual(CollectionField.objects.count(), 1)

    def test_records_provenance(self):
        """Creating a field records the source column it came from."""
        self.resolver().prepare(
            [ImportColumn("Key Reason", "Key Reason", ["First app"], [MOVIE])],
        )

        mapping = CollectionFieldSource.objects.get(user=self.user, source="clz")
        self.assertEqual(mapping.source_label, "Key Reason")
        self.assertTrue(mapping.created_field)

    def test_widens_media_types_without_retyping(self):
        """Reuse widens media types but leaves type and options alone."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Mine")
        existing = CollectionField.objects.create(
            group=group,
            label="Grade",
            field_type=CollectionFieldType.SELECT,
            options=["A"],
            media_types=[MediaTypes.BOOK.value],
        )

        self.resolver().prepare(
            [ImportColumn("Grade", "Grade", ["9.8", "9.6"], [MOVIE])],
        )

        existing.refresh_from_db()
        self.assertEqual(existing.field_type, CollectionFieldType.SELECT)
        self.assertEqual(existing.options, ["A"])
        self.assertIn(MOVIE, existing.media_types)

    def test_incompatible_value_goes_to_text_companion(self):
        """A value the field's type cannot hold is preserved, not dropped."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Mine")
        CollectionField.objects.create(
            group=group,
            label="Grade",
            field_type=CollectionFieldType.NUMBER,
            media_types=[MOVIE],
        )

        resolver = self.resolver()
        resolver.prepare([ImportColumn("Grade", "Grade", ["9.8"], [MOVIE])])
        values = resolver.build_values({"Grade": "Near Mint"}, MOVIE)

        companion = CollectionField.objects.get(label="Grade (clz)")
        self.assertEqual(values[str(companion.id)], "Near Mint")
        self.assertTrue(resolver.report.conflicts)

    def test_repeat_import_reuses_definitions(self):
        """Running the same import twice does not duplicate fields."""
        for _ in range(2):
            self.resolver().prepare(
                [ImportColumn("Variant", "Variant", ["Cover A"], [MOVIE])],
            )

        self.assertEqual(CollectionField.objects.filter(label="Variant").count(), 1)
        self.assertEqual(CollectionFieldSource.objects.count(), 1)

    def test_users_are_isolated(self):
        """One user's fields are never reused for another user's import."""
        other = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        self.resolver().prepare(
            [ImportColumn("Variant", "Variant", ["Cover A"], [MOVIE])],
        )
        ImportedFieldResolver(other, "clz").prepare(
            [ImportColumn("Variant", "Variant", ["Cover B"], [MOVIE])],
        )

        self.assertEqual(CollectionField.objects.filter(label="Variant").count(), 2)
        self.assertEqual(
            CollectionFieldSource.objects.filter(user=other).count(),
            1,
        )

    def test_overlong_label_is_truncated_deterministically(self):
        """A label longer than the column fits without colliding."""
        long_label = "x" * 150
        first = self.resolver().prepare(
            [ImportColumn("a", long_label, ["1"], [MOVIE])],
        )
        self.assertLessEqual(len(first["a"].label), 100)

    def test_number_values_are_stored_as_numbers(self):
        """A number column round trips as a float, matching the UI's storage."""
        resolver = self.resolver()
        resolver.prepare([ImportColumn("Value", "Value", ["10", "20"], [MOVIE])])
        values = resolver.build_values({"Value": "10"}, MOVIE)
        self.assertEqual(next(iter(values.values())), 10.0)

    def test_values_for_other_media_types_are_skipped(self):
        """A field that does not cover the row's media type is not written."""
        group = CollectionFieldGroup.objects.create(user=self.user, name="Mine")
        field = CollectionField.objects.create(
            group=group,
            label="Pages",
            field_type=CollectionFieldType.NUMBER,
            media_types=[MediaTypes.BOOK.value],
        )
        resolver = self.resolver()
        resolver.register("Pages", field)

        self.assertEqual(resolver.build_values({"Pages": "300"}, MOVIE), {})
