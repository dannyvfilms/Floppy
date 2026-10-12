"""Tests for the provider-id collection endpoints (fork-only)."""
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import Mock, patch

from api.fork_views import MediaCollectionView
from app.models import (
    CollectionEntry,
    CollectionEntrySource,
    Item,
    MediaTypes,
    Sources,
)
from app.providers import services

from .base import FloppyApiTestCase

METADATA_PATH = "api.fork_helpers.services.get_media_metadata"


def _provider_error(status_code):
    response = Mock(status_code=status_code, headers={})
    return services.ProviderAPIError(Sources.TMDB.value, Mock(response=response))


class MediaCollectionTests(FloppyApiTestCase):
    """PUT/DELETE media/{media_type}/{source}/{media_id}/collection."""

    def _put(self, media_id, payload=None):
        return self.call_api(
            "put",
            "api_media_collection",
            args=(MediaTypes.MOVIE.value, Sources.TMDB.value, media_id),
            payload=payload or {},
            headers=self.auth_headers,
        )

    def test_put_is_idempotent_and_updates_resolution(self):
        """A repeat PUT reuses the entry and applies a quality upgrade."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        created = self._put(item.media_id, {"resolution": "720p"})
        self.assertEqual(created.status_code, HTTP.CREATED)
        self.assertEqual(created.json()["resolution"], "720p")

        repeated = self._put(item.media_id, {"resolution": "1080p"})
        self.assertEqual(repeated.status_code, HTTP.OK)
        self.assertEqual(repeated.json()["id"], created.json()["id"])

        entry = CollectionEntry.objects.get(user=self.user1, item=item)
        self.assertEqual(entry.resolution, "1080p")

    @patch(METADATA_PATH)
    def test_put_creates_unknown_item_from_provider(self, mock_metadata):
        """An id Floppy has never seen is created from provider metadata."""
        mock_metadata.return_value = {
            "media_id": "987654",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "title": "Fresh Movie",
            "image": "https://example.com/fresh.jpg",
            "details": {"release_date": "1999-03-31"},
            "provider_external_ids": {"imdb_id": "tt0133093"},
        }

        response = self._put("987654")

        self.assertEqual(response.status_code, HTTP.CREATED)
        item = Item.objects.get(
            media_id="987654",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
        )
        self.assertEqual(item.title, "Fresh Movie")
        self.assertEqual(item.release_datetime.year, 1999)
        self.assertEqual(
            response.json()["item"]["ids"],
            {"tmdb": "987654", "imdb": "tt0133093"},
        )
        self.assertTrue(
            CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
        )

    @patch(METADATA_PATH)
    def test_put_unknown_provider_id_not_found(self, mock_metadata):
        """A provider 404 creates nothing."""
        mock_metadata.side_effect = _provider_error(HTTP.NOT_FOUND)

        response = self._put("987654")

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertFalse(Item.objects.filter(media_id="987654").exists())

    @patch(METADATA_PATH)
    def test_put_provider_outage_is_bad_gateway(self, mock_metadata):
        """A provider failure is not reported as a missing title."""
        mock_metadata.side_effect = _provider_error(HTTP.SERVICE_UNAVAILABLE)

        response = self._put("987654")

        self.assertEqual(response.status_code, HTTP.BAD_GATEWAY)
        self.assertFalse(Item.objects.filter(media_id="987654").exists())

    @patch(METADATA_PATH)
    def test_put_fetches_metadata_in_the_users_language(self, mock_metadata):
        """A new title is created in the caller's preferred metadata language."""
        self.user1.metadata_language = "de-DE"
        self.user1.save(update_fields=["metadata_language"])
        mock_metadata.return_value = {
            "media_id": "987654",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "title": "Frischer Film",
            "image": "https://example.com/fresh.jpg",
        }

        response = self._put("987654")

        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertEqual(mock_metadata.call_args.kwargs["language"], "de-DE")

    @patch(METADATA_PATH)
    def test_list_add_does_not_create_grouped_anime(self, mock_metadata):
        """TMDB anime is stored as TV in the anime bucket, so it is not created."""
        list_id = self.lists_by_name["favorites"].id

        response = self.call_api(
            "put",
            "api_media_list_detail",
            args=(MediaTypes.ANIME.value, Sources.TMDB.value, "987654", list_id),
            payload={},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        mock_metadata.assert_not_called()
        self.assertFalse(Item.objects.filter(media_id="987654").exists())

    def test_put_show_rejected_on_item_route(self):
        """Shows are collected per episode."""
        response = self.call_api(
            "put",
            "api_media_collection",
            args=(MediaTypes.TV.value, Sources.TMDB.value, "1396"),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def _delete(self, item, params=None):
        return self.call_api(
            "delete",
            "api_media_collection",
            args=(MediaTypes.MOVIE.value, item.source, item.media_id),
            headers=self.auth_headers,
            params=params,
        )

    def test_put_links_new_entry_to_the_api(self):
        """An entry created here carries the provenance link DELETE relies on."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self._put(item.media_id)

        self.assertEqual(response.status_code, HTTP.CREATED)
        entry = CollectionEntry.objects.get(user=self.user1, item=item)
        self.assertTrue(
            CollectionEntrySource.objects.filter(entry=entry, source="api").exists(),
        )

    def test_put_reuses_a_copy_added_elsewhere(self):
        """A copy from the web form is reused and stays unlinked."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        manual = CollectionEntry.objects.create(user=self.user1, item=item)

        response = self._put(item.media_id, {"resolution": "4k"})

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["id"], manual.id)
        self.assertFalse(CollectionEntrySource.objects.filter(entry=manual).exists())

    def test_delete_removes_only_the_copy_the_api_created(self):
        """DELETE leaves copies added elsewhere; a repeat DELETE is a 404."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        self._put(item.media_id)
        manual = CollectionEntry.objects.create(user=self.user1, item=item)

        response = self._delete(item)
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertEqual(
            list(CollectionEntry.objects.filter(user=self.user1, item=item)),
            [manual],
        )

        again = self._delete(item)
        self.assertEqual(again.status_code, HTTP.NOT_FOUND)
        self.assertIn("all=true", again.json()["detail"])
        self.assertTrue(CollectionEntry.objects.filter(id=manual.id).exists())

    def test_delete_all_removes_every_copy(self):
        """all=true also removes copies added elsewhere."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        self._put(item.media_id)
        CollectionEntry.objects.create(user=self.user1, item=item)

        response = self._delete(item, {"all": "true"})

        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
        )

    def test_delete_without_any_copy_is_not_found(self):
        """DELETE with nothing collected says so."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self._delete(item)

        self.assertEqual(response.status_code, HTTP.NOT_FOUND)
        self.assertNotIn("all=true", response.json()["detail"])

    def test_losing_a_simultaneous_create_reuses_the_winning_entry(self):
        """The unique link settles two first calls: one entry, no duplicate."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        view = MediaCollectionView()

        winner, won = view._create_entry(self.user1, item, "1080p")
        loser, lost = view._create_entry(self.user1, item, "720p")

        self.assertTrue(won)
        self.assertFalse(lost)
        self.assertEqual(loser.id, winner.id)
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user1, item=item).count(),
            1,
        )

    def test_put_non_object_body_rejected(self):
        """A JSON list body is a 400, not a server error."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self._put(item.media_id, [1])

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class MediaEpisodeCollectionTests(FloppyApiTestCase):
    """PUT/DELETE media/tv/{source}/{media_id}/{season}/episodes/{episode}/collection."""

    @patch(METADATA_PATH)
    def test_put_creates_episode_item(self, mock_metadata):
        """An unknown episode is created under the show's provider id."""
        mock_metadata.return_value = {
            "media_id": "1396",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.EPISODE.value,
            "title": "Breaking Bad",
            "image": "https://example.com/still.jpg",
        }
        args = (MediaTypes.TV.value, Sources.TMDB.value, "1396", 2, 5)

        response = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            payload={"resolution": "1080p"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, HTTP.CREATED)
        item = Item.objects.get(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=5,
        )
        entry = CollectionEntry.objects.get(user=self.user1, item=item)
        self.assertEqual(entry.resolution, "1080p")

        deleted = self.call_api(
            "delete",
            "api_media_episode_collection",
            args=args,
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)

    def test_non_tv_media_type_rejected(self):
        """The episode route only accepts tv."""
        response = self.call_api(
            "put",
            "api_media_episode_collection",
            args=(MediaTypes.MOVIE.value, Sources.TMDB.value, "1", 1, 1),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
