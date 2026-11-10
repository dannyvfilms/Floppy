# FORK: tests for the native-app additions to music, podcast, collection and
# tag endpoints (track listens, releases, manual episodes, custom fields).
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.models import (
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    Item,
    ItemTag,
    MediaTypes,
    Music,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Tag,
)

from .base import FloppyApiTestCase
from .test_fork_music import MusicApiTestCase


class TrackListenTests(MusicApiTestCase):
    """Track detail, listens and listen deletion."""

    def _listen(self, when):
        return self.call_api(
            "post",
            "api_music_song_play",
            payload={
                "album_id": self.album.id,
                "track_id": self.track1.id,
                "end_date": when,
            },
            headers=self.auth_headers,
        )

    def test_track_detail_exposes_artist_and_album_ids(self):
        """A track resolves to its artist and album."""
        response = self.call_api(
            "get",
            "api_music_track_detail",
            args=(self.track1.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        body = response.json()
        self.assertEqual(body["artist_id"], self.artist.id)
        self.assertEqual(body["album_id"], self.album.id)
        self.assertEqual(body["play_count"], 0)

    def test_listens_list_and_delete(self):
        """Each distinct listen is listed and can be deleted."""
        self._listen("2025-01-01T10:00:00Z")
        self._listen("2025-02-01T10:00:00Z")
        listed = self.call_api(
            "get",
            "api_music_track_plays",
            args=(self.track1.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(listed.status_code, HTTP.OK)
        results = listed.json()["results"]
        self.assertEqual(len(results), 2)
        newest = results[0]["history_id"]

        deleted = self.call_api(
            "delete",
            "api_music_track_play_detail",
            args=(self.track1.id, newest),
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        after = self.call_api(
            "get",
            "api_music_track_plays",
            args=(self.track1.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(len(after.json()["results"]), 1)

    def _detail_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.call_api(
                "get",
                "api_music_track_detail",
                args=(self.track1.id,),
                headers=self.auth_headers,
            )
        return response.json()["play_count"], len(ctx.captured_queries)

    def test_track_listens_cost_does_not_grow_with_listens(self):
        """Counting listens is one query, not one per history record."""
        self._listen("2025-01-01T10:00:00Z")
        self._listen("2025-02-01T10:00:00Z")
        count_two, queries_two = self._detail_queries()
        for month in range(3, 9):
            self._listen(f"2025-0{month}-01T10:00:00Z")
        count_eight, queries_eight = self._detail_queries()
        self.assertEqual((count_two, count_eight), (2, 8))
        self.assertEqual(queries_eight, queries_two)

    def test_listens_are_paged(self):
        """The plays list is bounded by limit/offset and reports the total."""
        for month in range(1, 4):
            self._listen(f"2025-0{month}-01T10:00:00Z")
        response = self.call_api(
            "get",
            "api_music_track_plays",
            args=(self.track1.id,),
            headers=self.auth_headers,
            params={"limit": 2},
        )
        body = response.json()
        self.assertEqual(len(body["results"]), 2)
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["pagination"]["total"], 3)
        self.assertTrue(body["results"][0]["played_at"].startswith("2025-03-01"))

    def test_delete_other_users_listen_is_not_found(self):
        """A listen of another account cannot be deleted."""
        self._listen("2025-01-01T10:00:00Z")
        music = Music.objects.get(user=self.user1, track=self.track1)
        history_id = music.history.first().history_id
        response = self.call_api(
            "delete",
            "api_music_track_play_detail",
            args=(self.track1.id, history_id),
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_unknown_track_is_not_found(self):
        """Missing tracks return 404."""
        response = self.call_api(
            "get",
            "api_music_track_plays",
            args=(999999,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_library_row_carries_music_identity(self):
        """The media row of a played song names its artist, album and track."""
        self._listen("2025-01-01T10:00:00Z")
        response = self.client.get(
            "/api/v1/media/music/",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        row = response.json()["results"][0]
        self.assertEqual(row["artist_id"], self.artist.id)
        self.assertEqual(row["album_id"], self.album.id)
        self.assertEqual(row["track_id"], self.track1.id)

    @patch("api.fork_views_music.musicbrainz.get_release_group_releases")
    def test_releases_list_and_select(self, mock_releases):
        """Releases load, an unknown one is rejected, a valid one is stored."""
        self.album.musicbrainz_release_group_id = "rg-1"
        self.album.save()
        mock_releases.return_value = [{"release_id": "rel-1", "title": "Deluxe"}]
        listed = self.call_api(
            "get",
            "api_music_album_releases",
            args=(self.album.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(listed.json()["results"][0]["release_id"], "rel-1")
        bad = self.call_api(
            "post",
            "api_music_album_releases",
            args=(self.album.id,),
            payload={"release_id": "nope"},
            headers=self.auth_headers,
        )
        self.assertEqual(bad.status_code, HTTP.BAD_REQUEST)
        with patch("api.fork_views_music.sync_album_release_tracks", return_value=2):
            ok = self.call_api(
                "post",
                "api_music_album_releases",
                args=(self.album.id,),
                payload={"release_id": "rel-1"},
                headers=self.auth_headers,
            )
        self.assertEqual(ok.json()["selected_release_id"], "rel-1")


class ManualPodcastEpisodeTests(FloppyApiTestCase):
    """Add, edit and delete episodes of a manual show."""

    def setUp(self):
        """Create a manual show the first user tracks."""
        super().setUp()
        self.show = PodcastShow.objects.create(
            podcast_uuid="manual-show-1",
            source=Sources.MANUAL.value,
            title="My Show",
        )
        PodcastShowTracker.objects.create(user=self.user1, show=self.show)

    def test_add_edit_delete(self):
        """The three writes mirror the web manager."""
        added = self.call_api(
            "post",
            "api_podcast_show_episode_manage",
            args=(self.show.id,),
            payload={"title": "Pilot", "episode_number": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(added.status_code, HTTP.CREATED)
        episode_id = added.json()["id"]
        edited = self.call_api(
            "patch",
            "api_podcast_episode_detail",
            args=(episode_id,),
            payload={"title": "Pilot (remastered)", "episode_number": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(edited.status_code, HTTP.OK)
        self.assertEqual(edited.json()["title"], "Pilot (remastered)")
        listed = self.call_api(
            "get",
            "api_podcast_show_episode_manage",
            args=(self.show.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(len(listed.json()["results"]), 1)
        deleted = self.call_api(
            "delete",
            "api_podcast_episode_detail",
            args=(episode_id,),
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(PodcastEpisode.objects.filter(id=episode_id).exists())

    def test_missing_title_is_rejected(self):
        """The form rejects an episode without a title."""
        response = self.call_api(
            "post",
            "api_podcast_show_episode_manage",
            args=(self.show.id,),
            payload={"episode_number": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("title", response.json()["errors"])

    def test_other_user_cannot_manage(self):
        """A user who does not track the show gets 404."""
        response = self.call_api(
            "post",
            "api_podcast_show_episode_manage",
            args=(self.show.id,),
            payload={"title": "Nope"},
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_score_requires_a_tracked_episode(self):
        """Scoring an episode the user never tracked is 404."""
        episode = PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="manual-x",
            title="Ep",
        )
        response = self.call_api(
            "patch",
            "api_podcast_episode_score",
            args=(episode.id,),
            payload={"score": 8},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class CollectionAndTagPayloadTests(FloppyApiTestCase):
    """Collection fields and tag type breakdown."""

    def test_collection_entry_carries_purchase_fields(self):
        """Location, price and custom values are part of the payload."""
        item = Item.objects.filter(media_type=MediaTypes.MOVIE.value).first()
        CollectionEntry.objects.create(
            user=self.user1,
            item=item,
            purchase_location="Shelf B",
            purchase_price="12.50",
            custom_field_values={"3": "x"},
        )
        response = self.call_api("get", "api_collection", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        row = response.json()["results"][0]
        self.assertEqual(row["purchase_location"], "Shelf B")
        self.assertEqual(row["purchase_price"], "12.50")
        self.assertEqual(row["custom_field_values"], {"3": "x"})
        self.assertIn("score", row)
        self.assertIn("completeness", row)
        colors = response.json()["media_type_colors"]
        self.assertEqual(colors[MediaTypes.MOVIE.value], "#6366f1")

    def test_custom_field_schema_round_trip(self):
        """PUT stores a group with a field; GET returns it."""
        saved = self.call_api(
            "put",
            "api_collection_fields",
            payload={
                "groups": [
                    {
                        "name": "Condition",
                        "fields": [
                            {
                                "label": "Grade",
                                "field_type": "text",
                                "media_types": [MediaTypes.MOVIE.value],
                            },
                        ],
                    },
                ],
            },
            headers=self.auth_headers,
        )
        self.assertEqual(saved.status_code, HTTP.OK, saved.content)
        listed = self.call_api("get", "api_collection_fields", headers=self.auth_headers)
        self.assertEqual(listed.json()["groups"][0]["fields"][0]["label"], "Grade")
        self.assertEqual([option["value"] for option in listed.json()["media_types"]], MediaTypes.values)
        self.assertTrue(listed.json()["field_types"])

    def test_default_token_cannot_delete_collection_field_schema(self):
        """Replacing a schema needs user:write; denied writes preserve all data."""
        from integrations.models import IntegrationToken

        group = CollectionFieldGroup.objects.create(user=self.user1, name="Condition")
        field = CollectionField.objects.create(group=group, label="Grade")
        entry = CollectionEntry.objects.create(
            user=self.user1, item=self.items_by_type["movie"][0],
            custom_field_values={str(field.id): "Mint"},
        )
        _token, raw = IntegrationToken.generate(user=self.user1, name="Tracking")
        response = self.call_api(
            "put", "api_collection_fields", payload={"groups": []},
            headers={"HTTP_AUTHORIZATION": f"Bearer {raw}"},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.assertTrue(CollectionFieldGroup.objects.filter(pk=group.pk).exists())
        self.assertTrue(CollectionField.objects.filter(pk=field.pk).exists())
        entry.refresh_from_db()
        self.assertEqual(entry.custom_field_values, {str(field.id): "Mint"})
        _token, raw = IntegrationToken.generate(user=self.user1, name="Settings", scopes=["user:write"])
        response = self.call_api(
            "put", "api_collection_fields", payload={"groups": []},
            headers={"HTTP_AUTHORIZATION": f"Bearer {raw}"},
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertFalse(CollectionField.objects.filter(pk=field.pk).exists())

    def test_patch_writes_custom_field_values(self):
        """PATCH stores custom values and keeps the ones it leaves out."""
        item = Item.objects.filter(media_type=MediaTypes.MOVIE.value).first()
        self.call_api(
            "put",
            "api_collection_fields",
            payload={
                "groups": [
                    {
                        "name": "Condition",
                        "fields": [
                            {
                                "label": "Grade",
                                "field_type": "text",
                                "media_types": [MediaTypes.MOVIE.value],
                            },
                            {
                                "label": "Signed",
                                "field_type": "checkbox",
                                "media_types": [MediaTypes.MOVIE.value],
                            },
                        ],
                    },
                ],
            },
            headers=self.auth_headers,
        )
        groups = self.call_api(
            "get",
            "api_collection_fields",
            headers=self.auth_headers,
        ).json()["groups"]
        grade, signed = (str(field["id"]) for field in groups[0]["fields"])
        entry = CollectionEntry.objects.create(user=self.user1, item=item)
        first = self.call_api(
            "patch",
            "api_collection_entry",
            args=(entry.id,),
            payload={"custom_field_values": {grade: "Mint", signed: True}},
            headers=self.auth_headers,
        )
        self.assertEqual(first.status_code, HTTP.OK, first.content)
        self.assertEqual(
            first.json()["custom_field_values"],
            {grade: "Mint", signed: True},
        )
        second = self.call_api(
            "patch",
            "api_collection_entry",
            args=(entry.id,),
            payload={"custom_field_values": {grade: "Good"}},
            headers=self.auth_headers,
        )
        self.assertEqual(
            second.json()["custom_field_values"],
            {grade: "Good", signed: True},
        )

    def test_patch_with_bad_custom_fields_saves_nothing(self):
        """A rejected custom_field_values leaves the form fields unsaved too."""
        item = Item.objects.filter(media_type=MediaTypes.MOVIE.value).first()
        entry = CollectionEntry.objects.create(user=self.user1, item=item)
        response = self.call_api(
            "patch",
            "api_collection_entry",
            args=(entry.id,),
            payload={"purchase_location": "Shop", "custom_field_values": []},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        entry.refresh_from_db()
        self.assertNotEqual(entry.purchase_location, "Shop")

    def test_custom_field_schema_rejects_bad_payload(self):
        """A payload without groups is 400."""
        response = self.call_api(
            "put",
            "api_collection_fields",
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_tags_include_type_breakdown(self):
        """Each tag reports how many items of each type use it."""
        item = Item.objects.filter(media_type=MediaTypes.MOVIE.value).first()
        tag = Tag.objects.create(user=self.user1, name="Cozy")
        ItemTag.objects.create(tag=tag, item=item)
        response = self.call_api("get", "api_tags", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        result = response.json()["results"][0]
        self.assertEqual(
            result["type_breakdown"],
            [{"media_type": "movie", "count": 1}],
        )
