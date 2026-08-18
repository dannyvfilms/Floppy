from django.test import TestCase

from app import credits
from app.models import Item, MediaTypes, Sources, Studio


class ProviderStorageResilienceTests(TestCase):
    """Provider metadata must not fail because an opaque URL exceeds 200 chars."""

    def test_studio_logo_storage_is_not_capped_at_urlfield_default(self):
        field = Studio._meta.get_field("logo")

        self.assertIsNone(field.max_length)

    def test_credit_sync_preserves_long_studio_logo(self):
        item = Item.objects.create(
            media_id="125988",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Silo",
        )
        long_logo = "https://image.tmdb.org/t/p/original/" + ("signed-segment-" * 24)
        self.assertGreater(len(long_logo), 200)

        credits.sync_item_credits_from_metadata(
            item,
            {
                "cast": [],
                "crew": [],
                "studios_full": [
                    {
                        "studio_id": "1632",
                        "name": "Long URL Studio",
                        "logo": long_logo,
                    },
                ],
            },
        )

        studio = Studio.objects.get(
            source=Sources.TMDB.value,
            source_studio_id="1632",
        )
        self.assertEqual(studio.logo, long_logo)
        self.assertTrue(item.studio_credits.filter(studio=studio).exists())
