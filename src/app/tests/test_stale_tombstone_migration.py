"""The data migration that clears tombstones left on still-tracked media (#1133)."""

from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import TV, DeletedMedia, Item, MediaTypes, Movie, Sources, Status

migration = import_module("app.migrations.0202_clear_stale_deleted_media")


class ClearStaleTombstonesTests(TestCase):
    """Only tombstones for media the user tracks right now are removed."""

    def setUp(self):
        """Create a user with one tracked show and one tracked movie."""
        self.user = get_user_model().objects.create_user(username="u", password="p")
        self.other = get_user_model().objects.create_user(username="o", password="p")
        self.show = self._item(MediaTypes.TV.value, "1396")
        self.movie = self._item(MediaTypes.MOVIE.value, "603")
        TV.objects.create(item=self.show, user=self.user, status=Status.IN_PROGRESS.value)
        Movie.objects.create(item=self.movie, user=self.user, status=Status.COMPLETED.value)

    @staticmethod
    def _item(media_type, media_id):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            title=f"{media_type} {media_id}",
        )

    @staticmethod
    def _tombstone(user, media_type, media_id):
        return DeletedMedia.objects.create(
            user=user,
            media_type=media_type,
            source=Sources.TMDB.value,
            media_id=media_id,
        )

    def test_removes_tombstones_for_tracked_media_only(self):
        """A genuinely deleted item and another user's tombstone are kept."""
        stale_show = self._tombstone(self.user, MediaTypes.TV.value, "1396")
        stale_movie = self._tombstone(self.user, MediaTypes.MOVIE.value, "603")
        deleted = self._tombstone(self.user, MediaTypes.TV.value, "555")
        # The other user does not track the show, so their tombstone is real.
        other_users = self._tombstone(self.other, MediaTypes.TV.value, "1396")

        migration.clear_stale_tombstones(apps, None)

        remaining = set(DeletedMedia.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, {deleted.pk, other_users.pk})
        self.assertNotIn(stale_show.pk, remaining)
        self.assertNotIn(stale_movie.pk, remaining)

    def test_media_type_must_match(self):
        """A movie tombstone does not survive or clear on a show with the same id."""
        movie_with_show_id = self._tombstone(self.user, MediaTypes.MOVIE.value, "1396")

        migration.clear_stale_tombstones(apps, None)

        self.assertTrue(DeletedMedia.objects.filter(pk=movie_with_show_id.pk).exists())
