"""Regression coverage for the focused security follow-up."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from app.helpers import safe_return_url
from app.models import Album, Artist, Item, Status, Track


class SafeReturnUrlTests(SimpleTestCase):
    def test_destinations_preserve_host_and_https(self):
        request = RequestFactory().get("/", secure=True)
        for destination in [
            "https://outside.example/",
            "//outside.example/",
            "/\\outside.example/",
            "javascript:alert(1)",
            "http://testserver/path",
        ]:
            with self.subTest(destination=destination):
                self.assertEqual(safe_return_url(request, destination), "/")
        for destination in ["/media?sort=title#top", "https://testserver/media"]:
            self.assertEqual(safe_return_url(request, destination), destination)


class ReturnUrlViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="return-test", password="test-only",  # pragma: allowlist secret
        )
        self.client.force_login(self.user)

    def test_bulk_validation_errors_do_not_redirect_outside(self):
        for route, fields in [
            (
                "episode_bulk_save",
                {"source": "tmdb", "media_type": "tv", "media_id": "123"},
            ),
            ("music_bulk_save", {"context_kind": "album", "context_id": "1"}),
        ]:
            for destination in ["https://outside.example/", "//outside.example/"]:
                with self.subTest(route=route, destination=destination):
                    response = self.client.post(
                        reverse(route), {**fields, "return_url": destination}
                    )
                    self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_settings_toggle_rejects_external_next_and_referer(self):
        for fields, headers in [
            ({"next": "//outside.example/"}, {}),
            ({}, {"HTTP_REFERER": "https://outside.example/"}),
        ]:
            response = self.client.post(
                reverse("toggle_obfuscate_episodes"), fields, **headers
            )
            self.assertRedirects(
                response, reverse("home"), fetch_redirect_response=False
            )
        response = self.client.post(
            reverse("toggle_obfuscate_episodes"), {"next": "/?sort=title"}
        )
        self.assertRedirects(response, "/?sort=title", fetch_redirect_response=False)

    @patch(
        "app.metadata_sync_views.tmdb.metadata_languages",
        return_value=[("", "Default")],
    )
    def test_metadata_language_rejects_network_path_return(self, _languages):
        item = Item.objects.create(
            source="tmdb", media_type="movie", media_id="123", title="Test"
        )
        route = reverse(
            "update_metadata_language_preference",
            kwargs={"source": "tmdb", "media_type": "movie", "media_id": item.media_id},
        )
        response = self.client.post(
            route, {"language": "", "return_url": "//outside.example/"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.url.startswith("//"))
        self.assertNotIn("outside.example", response.url)

    def test_music_tracking_rejects_external_next(self):
        artist = Artist.objects.create(name="Return Artist")
        album = Album.objects.create(title="Return Album", artist=artist)
        track = Track.objects.create(
            album=album,
            title="Track",
            track_number=1,
            musicbrainz_recording_id="recording-1",
        )
        for route, fields in [
            ("album_save", {"album_id": album.pk, "status": Status.IN_PROGRESS.value}),
            (
                "artist_save",
                {"artist_id": artist.pk, "status": Status.IN_PROGRESS.value},
            ),
            ("album_delete", {"album_id": album.pk}),
            ("artist_delete", {"artist_id": artist.pk}),
            (
                "song_save",
                {
                    "album_id": album.pk,
                    "track_id": track.pk,
                    "recording_id": "recording-1",
                    "end_date": "2023-06-01T00:00",
                },
            ),
        ]:
            for destination in ["//outside.example/", "/?sort=title"]:
                with self.subTest(route=route, destination=destination):
                    response = self.client.post(
                        reverse(route), fields, QUERY_STRING="next=" + destination
                    )
                    self.assertEqual(response.status_code, 302)
                    if destination.startswith("//"):
                        self.assertNotIn("outside.example", response.url)
                    else:
                        self.assertEqual(response.url, destination)

    def test_podcast_show_redirects_stay_on_this_host(self):
        from app.models import PodcastShow

        show = PodcastShow.objects.create(podcast_uuid="next-show", title="Show")
        for destination in ["//outside.example/", "/?sort=title"]:
            with self.subTest(destination=destination):
                response = self.client.post(
                    reverse("podcast_show_delete"),
                    {"show_id": show.pk},
                    QUERY_STRING="next=" + destination,
                    HTTP_HX_REQUEST="true",
                )
                target = response["HX-Redirect"]
                if destination.startswith("//"):
                    self.assertNotIn("outside.example", target)
                else:
                    self.assertEqual(target, destination)

    def test_plex_preferences_reject_external_next(self):
        for route in ["update_plex_usernames", "update_plex_webhook_libraries"]:
            response = self.client.post(reverse(route), {"next": "//outside.example/"})
            self.assertRedirects(
                response, reverse("integrations"), fetch_redirect_response=False
            )
