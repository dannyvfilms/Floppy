"""Tests for the provider-id collection endpoints (fork-only)."""
from datetime import UTC, datetime
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

    def test_put_stores_media_info_and_collected_at(self):
        """A new entry keeps every sent field, including the collected date."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        response = self._put(
            item.media_id,
            {
                "media_type": "bluray",
                "resolution": "4k",
                "hdr": "Dolby Vision",
                "is_3d": True,
                "audio_codec": "TrueHD Atmos",
                "audio_channels": "7.1",
                "bitrate": 4608,
                "collected_at": "2014-05-01T12:30:00.000Z",
            },
        )

        self.assertEqual(response.status_code, HTTP.CREATED)
        entry = CollectionEntry.objects.get(user=self.user1, item=item)
        self.assertEqual(entry.media_type, "bluray")
        self.assertEqual(entry.resolution, "4k")
        self.assertEqual(entry.hdr, "Dolby Vision")
        self.assertTrue(entry.is_3d)
        self.assertEqual(entry.audio_codec, "TrueHD Atmos")
        self.assertEqual(entry.audio_channels, "7.1")
        self.assertEqual(entry.bitrate, 4608)
        self.assertEqual(entry.collected_at, datetime(2014, 5, 1, 12, 30, tzinfo=UTC))

    def test_put_repeat_updates_sent_fields_and_keeps_the_rest(self):
        """A repeat PUT changes only what it sends."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        self._put(
            item.media_id,
            {"resolution": "1080p", "hdr": "HDR10", "is_3d": True},
        )

        response = self._put(
            item.media_id,
            {"audio_codec": "DTS-HD MA", "is_3d": False},
        )

        self.assertEqual(response.status_code, HTTP.OK)
        entry = CollectionEntry.objects.get(user=self.user1, item=item)
        self.assertEqual(entry.resolution, "1080p")
        self.assertEqual(entry.hdr, "HDR10")
        self.assertFalse(entry.is_3d)
        self.assertEqual(entry.audio_codec, "DTS-HD MA")

    def test_put_invalid_field_rejected(self):
        """A wrongly typed or too long field is a 400 and creates nothing."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]

        for payload in (
            {"hdr": "x" * 31},
            {"is_3d": "yes"},
            {"bitrate": "320"},
            {"bitrate": -1},
            {"collected_at": "yesterday"},
            {"collected_at": "2014-13-01T00:00:00Z"},
        ):
            with self.subTest(payload=payload):
                response = self._put(item.media_id, payload)

                self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
                self.assertFalse(
                    CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
                )

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

    def test_put_leaves_a_copy_of_another_format(self):
        """A digital PUT adds its own copy instead of rewriting a Blu-ray."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        bluray = CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            media_type="Blu-ray",
            resolution="1080p",
        )

        response = self._put(
            item.media_id,
            {"media_type": "digital", "resolution": "4K"},
        )

        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertNotEqual(response.json()["id"], bluray.id)
        bluray.refresh_from_db()
        self.assertEqual(bluray.media_type, "Blu-ray")
        self.assertEqual(bluray.resolution, "1080p")

        again = self._put(item.media_id, {"media_type": "digital"})

        self.assertEqual(again.status_code, HTTP.OK)
        self.assertEqual(again.json()["id"], response.json()["id"])
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user1, item=item).count(),
            2,
        )

    def test_put_reuses_a_copy_of_the_same_format_or_none(self):
        """The format match ignores case and punctuation; no format matches too."""
        movies = self.items_by_type[MediaTypes.MOVIE.value]
        bluray = CollectionEntry.objects.create(
            user=self.user1,
            item=movies[0],
            media_type="Blu-ray",
        )
        unknown = CollectionEntry.objects.create(user=self.user1, item=movies[1])

        same = self._put(movies[0].media_id, {"media_type": "bluray"})
        blank = self._put(movies[1].media_id, {"media_type": "digital"})

        self.assertEqual(same.status_code, HTTP.OK)
        self.assertEqual(same.json()["id"], bluray.id)
        bluray.refresh_from_db()
        self.assertEqual(bluray.media_type, "Blu-ray")
        self.assertEqual(blank.status_code, HTTP.OK)
        self.assertEqual(blank.json()["id"], unknown.id)
        unknown.refresh_from_db()
        self.assertEqual(unknown.media_type, "digital")

    def test_put_prefers_the_same_format_over_a_copy_without_one(self):
        """A matching copy wins over a newer copy that has no format."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        bluray = CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            media_type="Blu-ray",
        )
        # collected_at is auto_now_add, so make the Blu-ray the older copy here.
        CollectionEntry.objects.filter(id=bluray.id).update(
            collected_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        CollectionEntry.objects.create(user=self.user1, item=item)

        response = self._put(item.media_id, {"media_type": "bluray"})

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["id"], bluray.id)

    def test_put_does_not_take_a_non_latin_format_for_none(self):
        """A format in another script is a format, not a blank one."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        disc = CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            media_type="ブルーレイ",
        )

        response = self._put(item.media_id, {"media_type": "digital"})

        self.assertEqual(response.status_code, HTTP.CREATED)
        disc.refresh_from_db()
        self.assertEqual(disc.media_type, "ブルーレイ")

    def test_put_without_a_format_reuses_any_copy(self):
        """Without a sent media_type the first copy is reused, as before."""
        item = self.items_by_type[MediaTypes.MOVIE.value][0]
        bluray = CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            media_type="Blu-ray",
        )

        response = self._put(item.media_id, {"resolution": "4K"})

        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["id"], bluray.id)
        bluray.refresh_from_db()
        self.assertEqual(bluray.media_type, "Blu-ray")
        self.assertEqual(bluray.resolution, "4K")

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

        winner, won = view._create_entry(self.user1, item, {"resolution": "1080p"})
        loser, lost = view._create_entry(self.user1, item, {"resolution": "720p"})

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

    @patch(METADATA_PATH)
    def test_anime_parameter_finds_an_episode_created_outside_the_anime_library(
        self, mock_metadata
    ):
        """A PUT creates a new episode in the default library; the same parameter finds it."""
        mock_metadata.return_value = {
            "media_id": "209867",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.EPISODE.value,
            "title": "Frieren: Beyond Journey's End",
            "image": "https://example.com/still.jpg",
        }
        args = (MediaTypes.TV.value, Sources.TMDB.value, "209867", 1, 6)
        params = {"library_media_type": MediaTypes.ANIME.value}

        created = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            params=params,
            payload={"media_type": "digital"},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        item = Item.objects.get(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=6,
        )
        self.assertNotEqual(item.library_media_type, MediaTypes.ANIME.value)

        repeated = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            params=params,
            payload={"media_type": "digital"},
            headers=self.auth_headers,
        )
        self.assertEqual(repeated.status_code, HTTP.OK)
        self.assertEqual(repeated.json()["id"], created.json()["id"])

        deleted = self.call_api(
            "delete",
            "api_media_episode_collection",
            args=args,
            params=params,
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
        )
        # The repeat PUT found the item without fetching its metadata again.
        mock_metadata.assert_called_once()

    @patch(METADATA_PATH)
    def test_anime_parameter_finds_the_copy_after_a_watch_in_the_anime_library(
        self, mock_metadata
    ):
        """A watch adds an anime library item; the API copy on the default one stays reachable."""
        mock_metadata.return_value = {
            "media_id": "209867",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.EPISODE.value,
            "title": "Frieren: Beyond Journey's End",
            "image": "https://example.com/still.jpg",
        }
        args = (MediaTypes.TV.value, Sources.TMDB.value, "209867", 1, 6)
        params = {"library_media_type": MediaTypes.ANIME.value}

        created = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            params=params,
            payload={"media_type": "digital"},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        watched = Item.objects.create(
            media_id="209867",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            episode_number=6,
            title="Frieren: Beyond Journey's End",
        )

        repeated = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            params=params,
            payload={"resolution": "1080p"},
            headers=self.auth_headers,
        )
        self.assertEqual(repeated.status_code, HTTP.OK)
        self.assertEqual(repeated.json()["id"], created.json()["id"])
        self.assertEqual(repeated.json()["resolution"], "1080p")

        deleted = self.call_api(
            "delete",
            "api_media_episode_collection",
            args=args,
            params=params,
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(CollectionEntry.objects.filter(user=self.user1).exists())
        self.assertTrue(Item.objects.filter(pk=watched.pk).exists())

    @patch(METADATA_PATH)
    def test_anime_library_episode_found_with_library_media_type(self, mock_metadata):
        """PUT and DELETE reach an episode in the anime library when told so."""
        item = Item.objects.create(
            media_id="1429",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            episode_number=1,
            title="Attack on Titan",
        )
        args = (MediaTypes.TV.value, Sources.TMDB.value, "1429", 1, 1)
        params = {"library_media_type": MediaTypes.ANIME.value}

        created = self.call_api(
            "put",
            "api_media_episode_collection",
            args=args,
            params=params,
            payload={"resolution": "1080p"},
            headers=self.auth_headers,
        )

        self.assertEqual(created.status_code, HTTP.CREATED)
        self.assertTrue(
            CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
        )
        mock_metadata.assert_not_called()

        deleted = self.call_api(
            "delete",
            "api_media_episode_collection",
            args=args,
            params=params,
            headers=self.auth_headers,
        )

        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user1, item=item).exists(),
        )

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
