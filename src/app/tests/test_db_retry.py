from django.test import TestCase

from app.db_retry import _describe_conflicting_row, update_or_create_race_safe
from app.models import Item, ItemProviderLink, MediaTypes, Sources


class UpdateOrCreateRaceSafeTests(TestCase):
    """Tests for update_or_create_race_safe's conflict handling."""

    def setUp(self):
        """Create two distinct tracked items to link providers against."""
        self.item_a = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show A",
            season_number=1,
        )
        self.item_b = Item.objects.create(
            media_id="2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show B",
            season_number=1,
        )

    def test_happy_path_creates_row(self):
        """A non-conflicting call creates the row normally."""
        link, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "111"},
        )
        self.assertTrue(created)
        self.assertEqual(link.provider_media_id, "111")

    def test_updates_existing_row_on_matching_lookup(self):
        """A second call with the same lookup updates in place."""
        update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "111"},
        )
        link, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "222"},
        )
        self.assertFalse(created)
        self.assertEqual(link.provider_media_id, "222")

    def test_returns_none_false_on_persistent_conflict(self):
        """A conflicting provider_media_id must not raise.

        Already claimed by a different item's link under the same
        (provider, provider_media_type, season_number), it should be
        skipped and reported as (None, False).
        """
        ItemProviderLink.objects.create(
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            provider_media_id="303821",
        )

        result, created = update_or_create_race_safe(
            ItemProviderLink.objects,
            item=self.item_b,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"provider_media_id": "303821"},
        )

        self.assertIsNone(result)
        self.assertFalse(created)

    def test_logs_conflicting_row_diagnostic(self):
        """The persistent-conflict warning should be diagnosable.

        It should include the raw DB error and identify the pre-existing
        conflicting row.
        """
        ItemProviderLink.objects.create(
            item=self.item_a,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=1,
            provider_media_id="303821",
        )

        with self.assertLogs("app.db_retry", level="WARNING") as logs:
            update_or_create_race_safe(
                ItemProviderLink.objects,
                item=self.item_b,
                provider=Sources.TVDB.value,
                provider_media_type=MediaTypes.SEASON.value,
                season_number=1,
                defaults={"provider_media_id": "303821"},
            )

        message = "\n".join(logs.output)
        self.assertIn("Persistent IntegrityError", message)
        self.assertIn("UNIQUE constraint failed", message)
        self.assertIn("303821", message)


class DescribeConflictingRowTests(TestCase):
    """Tests for the _describe_conflicting_row diagnostic helper."""

    def test_returns_unknown_when_defaults_not_probeable(self):
        """Non-scalar-only lookup/defaults yield an explicit unknown result."""
        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {},
            {"metadata": {"foo": "bar"}},
        )
        self.assertEqual(
            result,
            "unknown (no probeable scalar fields in lookup/defaults)",
        )

    def test_never_raises_on_bad_input(self):
        """An invalid field name in lookup/defaults must not propagate."""
        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {},
            {"not_a_real_field": object()},
        )
        self.assertIsInstance(result, str)

    def test_lookup_fields_narrow_the_probe(self):
        """The probe must use lookup fields, not just defaults.

        A `defaults`-only probe would match a row sharing provider_media_id
        regardless of season_number, producing a false-positive "conflicting
        row" (issue #326 follow-up: the original diagnostic listed an
        unrelated season-2 row alongside the real season-3 conflict).
        """
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show A",
            season_number=2,
        )
        ItemProviderLink.objects.create(
            item=item,
            provider=Sources.TVDB.value,
            provider_media_type=MediaTypes.SEASON.value,
            season_number=2,
            provider_media_id="303821",
        )

        result = _describe_conflicting_row(
            ItemProviderLink.objects,
            {
                "provider": Sources.TVDB.value,
                "provider_media_type": MediaTypes.SEASON.value,
                "season_number": 3,
            },
            {"provider_media_id": "303821"},
        )

        self.assertEqual(
            result,
            "unknown (no existing row matches the attempted lookup/defaults)",
        )
