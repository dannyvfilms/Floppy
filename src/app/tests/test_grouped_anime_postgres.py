from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, tag

from app.models import Item, ItemProviderLink, MediaTypes, Sources
from app.services.grouped_anime import GroupedAnimeMatch, promote_grouped_anime


@tag("postgres")
@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row-lock semantics")
class GroupedAnimePostgresConcurrencyTests(TransactionTestCase):
    """Exercise promotion under two concurrent PostgreSQL transactions."""

    reset_sequences = True

    def setUp(self):
        self.item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Concurrent Anime",
            image="https://example.com/show.jpg",
        )
        self.match = GroupedAnimeMatch(
            decision="move",
            reason="exact_external_id_and_animation_genre",
            tmdb_id="9001",
            mal_ids=("12345",),
            mapping_revision="test",
            mapping_digest="digest",
            mapping_group_key="group",
        )

    def _promote(self):
        close_old_connections()
        try:
            return promote_grouped_anime(self.item, self.match)
        finally:
            close_old_connections()

    def test_two_workers_are_idempotent_and_preserve_one_link(self):
        """Concurrent callers both succeed without duplicate provider links."""
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: self._promote(), range(2)))

        self.assertEqual(results, [True, True])
        self.assertEqual(
            Item.objects.get(pk=self.item.pk).library_media_type,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            ItemProviderLink.objects.filter(item_id=self.item.pk).count(),
            2,
        )
