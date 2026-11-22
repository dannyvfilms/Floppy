"""A list entry saved under a release id the album no longer holds still resolves."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from app.models import Album, Artist, Item, MediaTypes, Sources
from app.services import music

OLD_RELEASE = "de0e1482-d8a6-4afe-9cd1-dc9e1a53941e"
NEW_RELEASE = "11111111-1111-4111-8111-111111111111"
GROUP = "22222222-2222-4222-8222-222222222222"


class StaleReleaseIdTests(TestCase):
    """The album's release id changed after the list entry was saved."""

    def setUp(self):
        cache.clear()
        artist = Artist.objects.create(name="Angine de Poitrine")
        self.album = Album.objects.create(
            title="Vol.1",
            artist=artist,
            musicbrainz_release_id=NEW_RELEASE,
            musicbrainz_release_group_id=GROUP,
        )
        self.item = Item.objects.create(
            media_id=OLD_RELEASE,
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            title="Vol.1",
            image="none.svg",
        )

    @patch("app.providers.musicbrainz.get_release")
    def test_album_found_through_release_group(self, get_release):
        get_release.return_value = {"release_group_id": GROUP}
        self.assertEqual(music.album_for_media_id(OLD_RELEASE), self.album)

    @patch("app.providers.musicbrainz.get_release")
    def test_lookup_failure_is_remembered(self, get_release):
        get_release.side_effect = RuntimeError("offline")
        self.assertIsNone(music.album_for_media_id(OLD_RELEASE))
        self.assertIsNone(music.album_for_media_id(OLD_RELEASE))
        self.assertEqual(get_release.call_count, 1)

    @patch("app.providers.musicbrainz.get_release")
    def test_list_item_is_repointed_at_the_album(self, get_release):
        get_release.return_value = {"release_group_id": GROUP}
        self.assertEqual(music.repair_stale_album_list_items(None, [self.item]), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.media_id, NEW_RELEASE)

    @patch("app.providers.musicbrainz.get_release")
    def test_matching_item_is_not_looked_up(self, get_release):
        self.item.media_id = NEW_RELEASE
        self.item.save()
        self.assertEqual(music.repair_stale_album_list_items(None, [self.item]), 0)
        get_release.assert_not_called()
