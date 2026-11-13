"""Bulk item resolution and watch-state projection for imports."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Movie, Sources, Status, WatchState
from app.services.watch_state import project_watch_state, project_watch_states_bulk
from integrations.imports import helpers


class BulkResolveItemsTests(TestCase):
    def _spec(self, media_id, title="New"):
        return {
            "media_id": media_id,
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.MOVIE.value,
            "library_media_type": "",
            "season_number": None,
            "episode_number": None,
            "title": title,
            "image": "https://example.com/i.jpg",
        }

    def test_creates_missing_and_keeps_existing(self):
        existing = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Original",
            image="https://example.com/o.jpg",
        )
        found = helpers.bulk_resolve_items([self._spec("1", "CSV"), self._spec("2")])

        self.assertEqual(len(found), 2)
        keys = {key[0]: item for key, item in found.items()}
        self.assertEqual(keys["1"].pk, existing.pk)
        existing.refresh_from_db()
        self.assertEqual(existing.title, "Original")
        self.assertEqual(keys["2"].library_media_type, MediaTypes.MOVIE.value)
        self.assertEqual(Item.objects.count(), 2)

        helpers.bulk_resolve_items([self._spec("2")])
        self.assertEqual(Item.objects.count(), 2)


class BulkProjectionTests(TestCase):
    def test_matches_per_item_projection(self):
        user = get_user_model().objects.create_user(username="u", password="x")
        items = []
        for media_id, status in (("1", Status.COMPLETED.value), ("2", Status.PLANNING.value)):
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=media_id,
                image="x",
            )
            Movie.objects.bulk_create(
                [Movie(item=item, user=user, status=status, progress=1)],
            )
            items.append(item)

        project_watch_states_bulk(user, items)
        bulk = {
            s.item_id: (s.watched, s.play_count, s.state_digest)
            for s in WatchState.objects.filter(user=user)
        }
        WatchState.objects.all().delete()
        for item in items:
            project_watch_state(user, item)
        single = {
            s.item_id: (s.watched, s.play_count, s.state_digest)
            for s in WatchState.objects.filter(user=user)
        }
        self.assertEqual(bulk, single)
        self.assertEqual(len(bulk), 2)
