from users.models import SavedView

from .base import FloppyApiTestCase


class LibrarySavedViewTests(FloppyApiTestCase):
    """The native library can manage only the caller's saved media views."""

    endpoint = "/api/v1/library/saved-views/"

    def test_list_create_apply_and_delete_saved_view(self):
        created = self.client.post(
            self.endpoint,
            {"media_type": "movie", "name": "Rated", "query": "rating=rated&sort=score"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(created.status_code, 201)
        saved_id = created.data["id"]
        self.assertEqual(created.data["query"], "rating=rated&sort=score")

        listed = self.client.get(
            self.endpoint,
            {"media_type": "movie"},
            **self.auth_headers,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["id"] for item in listed.data], [saved_id])

        applied = self.client.get(f"{self.endpoint}{saved_id}/", **self.auth_headers)
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.data["name"], "Rated")

        deleted = self.client.delete(f"{self.endpoint}{saved_id}/", **self.auth_headers)
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(SavedView.objects.filter(pk=saved_id).exists())

    def test_saved_views_are_private_and_validate_input(self):
        view = SavedView.objects.create(user=self.user2, media_type="movie", name="Private")
        hidden = self.client.get(f"{self.endpoint}{view.id}/", **self.auth_headers)
        self.assertEqual(hidden.status_code, 404)

        invalid = self.client.post(
            self.endpoint,
            {"media_type": "not-a-type", "name": "Bad"},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(invalid.status_code, 400)
