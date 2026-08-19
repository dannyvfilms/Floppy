from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import Item, Movie, Status
from users.models import User


@override_settings(SEERR_GLOBAL_WEBHOOK_SECRET="topsecret")
class SeerrGlobalWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="john", password="pw")
        self.user.jellyseerr_enabled = True
        self.user.jellyseerr_allowed_usernames = "alice"
        self.user.jellyseerr_default_added_status = Status.PLANNING.value
        self.user.save()

    def _url(self):
        return reverse("seerr_global_webhook")

    def _payload(self, secret="topsecret", requester="alice", **overrides):  # noqa: S107  # test fixture value
        payload = {
            "media_type": "movie",
            "media_tmdbid": "123",
            "media_status": "PENDING",
            "requestedBy_username": requester,
            "secret": secret,
        }
        payload.update(overrides)
        return payload

    @override_settings(SEERR_GLOBAL_WEBHOOK_SECRET="")
    def test_disabled_when_secret_unset_returns_404(self):
        resp = self.client.post(
            self._url(),
            data=self._payload(),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_missing_payload_returns_400(self):
        resp = self.client.post(self._url(), data=b"", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_json_returns_400(self):
        resp = self.client.post(
            self._url(), data="{notjson", content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_wrong_secret_returns_401(self):
        resp = self.client.post(
            self._url(),
            data=self._payload(secret="wrong"),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_requester_returns_400(self):
        resp = self.client.post(
            self._url(),
            data=self._payload(requester=""),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @patch("app.providers.services.get_media_metadata")
    def test_matching_requester_adds_movie(self, mock_meta):
        mock_meta.return_value = {
            "title": "Example Movie",
            "image": "https://example.com/movie.jpg",
        }

        resp = self.client.post(
            self._url(),
            data=self._payload(),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(Movie.objects.count(), 1)
        movie = Movie.objects.first()
        self.assertEqual(movie.user_id, self.user.id)

    @patch("app.providers.services.get_media_metadata")
    def test_non_matching_requester_no_op(self, mock_meta):
        resp = self.client.post(
            self._url(),
            data=self._payload(requester="charlie"),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(Movie.objects.count(), 0)
        mock_meta.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    def test_blank_allowed_usernames_excluded_from_global_matching(self, mock_meta):
        self.user.jellyseerr_allowed_usernames = ""
        self.user.save(update_fields=["jellyseerr_allowed_usernames"])

        resp = self.client.post(
            self._url(),
            data=self._payload(),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(Movie.objects.count(), 0)
        mock_meta.assert_not_called()

    @patch("app.providers.services.get_media_metadata")
    def test_two_users_matching_same_requester_both_get_item(self, mock_meta):
        mock_meta.return_value = {
            "title": "Shared Movie",
            "image": "https://example.com/shared.jpg",
        }

        other = User.objects.create_user(username="jane", password="pw")
        other.jellyseerr_enabled = True
        other.jellyseerr_allowed_usernames = "alice"
        other.save()

        resp = self.client.post(
            self._url(),
            data=self._payload(),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(Item.objects.count(), 1)
        self.assertEqual(Movie.objects.count(), 2)
        user_ids = set(Movie.objects.values_list("user_id", flat=True))
        self.assertEqual(user_ids, {self.user.id, other.id})
