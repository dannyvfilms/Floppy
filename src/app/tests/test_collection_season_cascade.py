from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.helpers import get_season_collection_stats, get_tv_show_collection_stats
from app.models import CollectionEntry, Item, MediaTypes, Sources


class CollectionSeasonCascadeTest(TestCase):
    """Test marking a whole season/show as collected cascades to episodes (#396)."""

    def setUp(self):
        """Create a user, TV show, one season, and two episodes."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.tv_item = Item.objects.create(
            media_id="tv1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test TV",
            image="http://example.com/tv.jpg",
        )
        self.season_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Season 1",
            image="http://example.com/season1.jpg",
        )
        self.episode_one = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Episode 1",
            image="http://example.com/episode1.jpg",
        )
        self.episode_two = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Episode 2",
            image="http://example.com/episode2.jpg",
        )

    def _post_collection_add(self, item):
        return self.client.post(
            reverse("collection_add"),
            {"item_id": item.id},
            HTTP_HX_REQUEST="true",
        )

    def test_marking_season_collected_creates_one_entry_per_episode(self):
        """Submitting the season creates a CollectionEntry for every episode."""
        response = self._post_collection_add(self.season_item)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(
            CollectionEntry.objects.filter(
                user=self.user, item=self.season_item
            ).exists(),
        )
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__in=[self.episode_one, self.episode_two],
            ).count(),
            2,
        )

        stats = get_season_collection_stats(self.user, self.season_item)
        self.assertEqual(stats, {"collected_episodes": 2, "total_episodes": 2})

    def test_marking_season_collected_skips_already_collected_episodes(self):
        """Regression test for #396: existing episode entries aren't duplicated.

        Before the fix, marking the season collected after one episode was
        already collected created an ambiguous season-level entry that the
        stats functions silently ignored, leaving the count stuck at 1/2.
        """
        CollectionEntry.objects.create(user=self.user, item=self.episode_one)

        response = self._post_collection_add(self.season_item)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user, item=self.episode_one
            ).count(),
            1,
        )
        self.assertTrue(
            CollectionEntry.objects.filter(
                user=self.user, item=self.episode_two
            ).exists(),
        )

        stats = get_season_collection_stats(self.user, self.season_item)
        self.assertEqual(stats, {"collected_episodes": 2, "total_episodes": 2})

    def test_marking_show_collected_excludes_specials(self):
        """Marking the whole show collected creates entries for all episodes except season 0."""
        special_item = Item.objects.create(
            media_id=self.tv_item.media_id,
            source=self.tv_item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=0,
            episode_number=1,
            title="Special",
            image="http://example.com/special.jpg",
        )

        response = self._post_collection_add(self.tv_item)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user, item=self.tv_item).exists(),
        )
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__in=[self.episode_one, self.episode_two],
            ).count(),
            2,
        )
        self.assertFalse(
            CollectionEntry.objects.filter(user=self.user, item=special_item).exists(),
        )

        stats = get_tv_show_collection_stats(self.user, self.tv_item)
        self.assertEqual(stats["collected_episodes"], 2)
        self.assertEqual(stats["collected_seasons"], 1)

    def test_marking_movie_collected_still_creates_single_entry(self):
        """Non-TV media types are unaffected by the season/show expansion."""
        movie_item = Item.objects.create(
            media_id="movie1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )

        response = self._post_collection_add(movie_item)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user, item=movie_item).count(),
            1,
        )

    def test_collection_remove_season_deletes_manual_entries(self):
        """The season bulk-remove endpoint deletes manually-added episode entries."""
        CollectionEntry.objects.create(user=self.user, item=self.episode_one)
        CollectionEntry.objects.create(user=self.user, item=self.episode_two)

        response = self.client.post(
            reverse(
                "collection_remove_season",
                kwargs={"season_item_id": self.season_item.id},
            ),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__in=[self.episode_one, self.episode_two],
            ).count(),
            0,
        )

    def test_season_modal_shows_manual_episode_audit_entries(self):
        """The season modal lists manually-collected episodes with delete buttons."""
        entry = CollectionEntry.objects.create(user=self.user, item=self.episode_one)

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": self.tv_item.media_id,
                },
            ),
            {"season_number": "1"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manual")
        self.assertContains(
            response,
            reverse("collection_remove", kwargs={"entry_id": entry.id}),
        )

    def test_quick_add_season_expands_to_episodes(self):
        """The one-click quick-add endpoint also expands season items into episodes."""
        response = self.client.post(
            reverse(
                "collection_quick_add",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": self.tv_item.media_id,
                },
            ),
            {"season_number": "1"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(
            CollectionEntry.objects.filter(
                user=self.user,
                item__in=[self.episode_one, self.episode_two],
            ).count(),
            2,
        )
