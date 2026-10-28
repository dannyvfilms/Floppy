from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import (
    TV,
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    Episode,
    Game,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
    Video,
)
from app.templatetags.app_tags import item_slot_id
from integrations.models import CollectionSourceState


class CollectionListViewTest(TestCase):
    """Test collection list view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.item = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

    def test_collection_list_authenticated(self):
        """Test authenticated user can view their collection."""
        self.client.login(**self.credentials)
        response = self.client.get(reverse("collection_list"))
        self.assertEqual(response.status_code, 200)

    def test_initial_layout_does_not_wait_for_alpine(self):
        """Cached posters need their grid width before any script initializes."""
        self.client.login(**self.credentials)
        for layout in ("grid", "table"):
            with self.subTest(layout=layout):
                response = self.client.get(
                    reverse("collection_list"), {"layout": layout}
                )
                expected = "media-grid" if layout == "grid" else ""
                self.assertRegex(
                    response.content.decode(),
                    rf'id="collection-view"[^>]*\sclass="{expected}"',
                )

    def test_collection_list_unauthenticated(self):
        """Test unauthenticated user is redirected to login."""
        response = self.client.get(reverse("collection_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_collection_list_filtered_by_location(self):
        """Filtering by location keeps only entries stored there, per user."""
        self.client.login(**self.credentials)
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        items = {}
        for key, location in (
            ("nas", "NAS"),
            ("home", "Home"),
            ("all", "all"),
            ("none", ""),
        ):
            items[key] = Item.objects.create(
                media_id=f"loc-{key}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Movie {key}",
                image="http://example.com/movie.jpg",
            )
            CollectionEntry.objects.create(
                user=self.user,
                item=items[key],
                purchase_location=location,
            )
        CollectionEntry.objects.create(
            user=other_user,
            item=items["nas"],
            purchase_location="Garage",
        )

        response = self.client.get(reverse("collection_list"), {"location": "NAS"})

        entries = list(response.context["collection_entries"])
        self.assertEqual([entry.item_id for entry in entries], [items["nas"].id])
        self.assertEqual(response.context["location_filter"], "NAS")
        self.assertEqual(
            response.context["available_locations"],
            ["Home", "NAS", "all"],
        )

        # A location literally called "all" filters like any other.
        response = self.client.get(reverse("collection_list"), {"location": "all"})
        entries = list(response.context["collection_entries"])
        self.assertEqual([entry.item_id for entry in entries], [items["all"].id])

        response = self.client.get(reverse("collection_list"))
        self.assertEqual(len(response.context["collection_entries"]), 4)

    def test_collection_list_filtered_by_media_type(self):
        """Test filtering by media_type parameter."""
        self.client.login(**self.credentials)

        # Create entries for different media types
        movie_item = Item.objects.create(
            media_id="movie1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="http://example.com/movie.jpg",
        )
        tv_item = Item.objects.create(
            media_id="tv1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="TV Show",
            image="http://example.com/tv.jpg",
        )

        CollectionEntry.objects.create(user=self.user, item=movie_item)
        CollectionEntry.objects.create(user=self.user, item=tv_item)

        # Filter by movie
        response = self.client.get(
            reverse(
                "collection_list_filtered",
                kwargs={"media_type": MediaTypes.MOVIE.value},
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["collection_entries"]), 1)
        self.assertEqual(
            response.context["collection_entries"][0].item.media_type,
            MediaTypes.MOVIE.value,
        )

    def test_collection_list_empty(self):
        """Test empty collection display."""
        self.client.login(**self.credentials)
        response = self.client.get(reverse("collection_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["collection_entries"]), 0)

    def test_collection_card_shows_tracked_rating_and_status(self):
        """A collected item the user tracks shows the same rating and status as the library."""
        movie = Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            score=8.5,
        )
        CollectionEntry.objects.create(user=self.user, item=self.item)
        self.client.login(**self.credentials)

        response = self.client.get(reverse("collection_list"))

        content = response.content.decode()
        self.assertIn(f'id="{item_slot_id("media-card-rating", movie.item)}"', content)
        self.assertIn(">8.5</span>", content)
        self.assertIn(f'id="{item_slot_id("media-status-chip", movie.item)}"', content)
        self.assertIn('class="media-status-chip ', content)

    def test_collection_card_for_untracked_item_has_no_rating_or_status(self):
        """An owned but untracked item shows no status chip and no rating."""
        CollectionEntry.objects.create(user=self.user, item=self.item)
        self.client.login(**self.credentials)

        response = self.client.get(reverse("collection_list"))

        content = response.content.decode()
        self.assertIn("Test Movie", content)
        self.assertNotIn("media-card-rate-button", content)
        self.assertNotIn('class="media-status-chip ', content)

    def test_collection_card_rating_ignores_other_users_tracking(self):
        """Another user's rating of the same item never appears on this user's card."""
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        Movie.objects.create(
            item=self.item,
            user=other_user,
            status=Status.COMPLETED.value,
            progress=1,
            score=3,
        )
        CollectionEntry.objects.create(user=self.user, item=self.item)
        self.client.login(**self.credentials)

        response = self.client.get(reverse("collection_list"))

        self.assertNotContains(response, "media-card-rate-button")
        self.assertNotContains(response, "text-yellow-300")

    def test_collection_card_lookup_does_not_grow_with_page_size(self):
        """Loading ratings for the page is a fixed number of queries, not one per card."""
        self.client.login(**self.credentials)

        def add_tracked_movies(start, count):
            for index in range(start, start + count):
                item = Item.objects.create(
                    media_id=f"query-{index}",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.MOVIE.value,
                    title=f"Query Movie {index}",
                )
                Movie.objects.create(
                    item=item,
                    user=self.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    score=7,
                )
                CollectionEntry.objects.create(user=self.user, item=item)

        def count_queries():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse("collection_list"))
            return len(queries)

        add_tracked_movies(0, 2)
        count_queries()  # the first visit also runs one-time setup queries
        small_page = count_queries()
        add_tracked_movies(2, 8)
        large_page = count_queries()

        self.assertEqual(small_page, large_page)

    def test_collection_episode_cards_do_not_query_per_episode(self):
        """Episode cards read their season; it is loaded with the page, not per card."""
        self.client.login(**self.credentials)
        show_item = Item.objects.create(
            media_id="ep-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Episode Show",
        )
        season_item = Item.objects.create(
            media_id="ep-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Episode Show",
        )
        tv = TV.objects.create(
            item=show_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

        def add_tracked_episodes(start, count):
            for number in range(start, start + count):
                item = Item.objects.create(
                    media_id="ep-show",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    season_number=1,
                    episode_number=number,
                    title=f"Episode {number}",
                )
                Episode.objects.create(item=item, related_season=season)
                CollectionEntry.objects.create(user=self.user, item=item)

        def count_queries():
            with CaptureQueriesContext(connection) as queries:
                self.client.get(reverse("collection_list"))
            return len(queries)

        add_tracked_episodes(1, 2)
        count_queries()  # the first visit also runs one-time setup queries
        small_page = count_queries()
        add_tracked_episodes(3, 4)
        large_page = count_queries()

        self.assertEqual(small_page, large_page)


class CollectionCompletenessTest(TestCase):
    """Test the collection page's partial/full collection filter and badge."""

    def setUp(self):
        """Set up a partially collected show and a fully collected show."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.partial_show = Item.objects.create(
            media_id="tv1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Partial Show",
            image="http://example.com/tv1.jpg",
        )
        self.partial_episode_collected = Item.objects.create(
            media_id=self.partial_show.media_id,
            source=self.partial_show.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Partial Show Episode 1",
            image="http://example.com/tv1-e1.jpg",
        )
        Item.objects.create(
            media_id=self.partial_show.media_id,
            source=self.partial_show.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=2,
            title="Partial Show Episode 2",
            image="http://example.com/tv1-e2.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=self.partial_episode_collected,
        )

        self.full_show = Item.objects.create(
            media_id="tv2",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Full Show",
            image="http://example.com/tv2.jpg",
        )
        full_show_episode = Item.objects.create(
            media_id=self.full_show.media_id,
            source=self.full_show.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Full Show Episode 1",
            image="http://example.com/tv2-e1.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=full_show_episode)

    def test_completeness_filter_partial_only_matches_partial_show(self):
        """Filtering by 'partial' returns only rows from the partial show."""
        self.client.login(**self.credentials)
        response = self.client.get(
            reverse("collection_list"),
            {"completeness": "partial"},
        )
        self.assertEqual(response.status_code, 200)
        entries = response.context["collection_entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].item_id, self.partial_episode_collected.id)

    def test_completeness_filter_full_only_matches_full_show(self):
        """Filtering by 'full' returns only rows from the fully collected show."""
        self.client.login(**self.credentials)
        response = self.client.get(
            reverse("collection_list"),
            {"completeness": "full"},
        )
        self.assertEqual(response.status_code, 200)
        entries = response.context["collection_entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].item.media_id, self.full_show.media_id)

    def test_completeness_filter_all_returns_everything(self):
        """The default 'all' filter is unaffected by completeness."""
        self.client.login(**self.credentials)
        response = self.client.get(reverse("collection_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["collection_entries"]), 2)

    def test_completeness_badge_attached_to_show_row(self):
        """The partial show's TV-level row is annotated with completeness stats."""
        CollectionEntry.objects.create(user=self.user, item=self.partial_show)

        self.client.login(**self.credentials)
        response = self.client.get(
            reverse("collection_list"),
            {"type": MediaTypes.TV.value},
        )
        self.assertEqual(response.status_code, 200)
        entries = response.context["collection_entries"]
        show_entry = next(e for e in entries if e.item_id == self.partial_show.id)
        self.assertEqual(
            show_entry.completeness,
            {"collected": 1, "total": 2, "is_partial": True},
        )

    def test_completeness_not_attached_to_episode_row(self):
        """Episode-grain rows don't carry a completeness badge."""
        self.client.login(**self.credentials)
        response = self.client.get(reverse("collection_list"))
        self.assertEqual(response.status_code, 200)
        entries = response.context["collection_entries"]
        episode_entry = next(
            e for e in entries if e.item_id == self.partial_episode_collected.id
        )
        self.assertFalse(hasattr(episode_entry, "completeness"))


class CollectionAddViewTest(TestCase):
    """Test collection add view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.item = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

    def test_collecting_a_video_lists_it_without_tracking_it(self):
        """A downloaded video can be collected; collecting never tracks it."""
        video_item = Item.objects.create(
            media_id="vid1",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="A Downloaded Video",
            image="http://example.com/video.jpg",
        )
        self.client.login(**self.credentials)

        self.client.post(
            reverse("collection_add"),
            {"item_id": video_item.id, "media_type": "Digital", "resolution": "1080p"},
        )

        self.assertTrue(
            CollectionEntry.objects.filter(user=self.user, item=video_item).exists(),
        )
        self.assertFalse(Video.objects.filter(user=self.user).exists())
        response = self.client.get(
            reverse("collection_list_filtered", args=[MediaTypes.VIDEO.value]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A Downloaded Video")

    def test_collection_add_valid_data(self):
        """Test POST with valid data creates CollectionEntry."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": self.item.id,
                "media_type": "bluray",
                "resolution": "1080p",
            },
        )

        # Should redirect or return success
        self.assertIn(response.status_code, [200, 302])
        self.assertTrue(
            CollectionEntry.objects.filter(user=self.user, item=self.item).exists()
        )

    def test_collection_add_existing_entry_creates_additional_copy(self):
        """Test POST with existing entry creates another collection copy."""
        self.client.login(**self.credentials)

        # Create existing entry
        entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            media_type="dvd",
        )

        # Try to add again with different data
        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": self.item.id,
                "media_type": "bluray",
                "resolution": "1080p",
            },
        )

        # Existing entry should remain unchanged
        entry.refresh_from_db()
        self.assertEqual(entry.media_type, "dvd")
        self.assertEqual(entry.resolution, "")

        # A second entry should be created for the new copy
        self.assertEqual(
            CollectionEntry.objects.filter(user=self.user, item=self.item).count(), 2
        )
        new_entry = (
            CollectionEntry.objects.filter(user=self.user, item=self.item)
            .exclude(id=entry.id)
            .first()
        )
        self.assertIsNotNone(new_entry)
        self.assertEqual(new_entry.media_type, "bluray")
        self.assertEqual(new_entry.resolution, "1080p")

    def test_collection_add_invalid_item_id(self):
        """Test validation errors for invalid item_id."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": 99999,  # Non-existent ID
            },
        )

        # Should handle error gracefully
        self.assertIn(response.status_code, [400, 302])

    def test_collection_add_json_response(self):
        """Test JSON response for AJAX requests."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": self.item.id,
                "media_type": "bluray",
            },
            HTTP_HX_REQUEST="true",
        )

        # Should return JSON
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["content-type"], "application/json")

    def test_collection_add_allows_long_game_platform_names(self):
        """Test game platform values longer than 20 chars are accepted."""
        self.client.login(**self.credentials)
        game_item = Item.objects.create(
            media_id="game-1234",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="Test Game",
            image="http://example.com/game.jpg",
        )
        long_platform = "Sega Mega Drive/Genesis"

        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": game_item.id,
                "media_type": "ROM",
                "resolution": long_platform,
                "hdr": "Standard",
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = CollectionEntry.objects.get(user=self.user, item=game_item)
        self.assertEqual(entry.resolution, long_platform)

    def test_collection_add_does_not_track_untracked_game(self):
        """Collecting a game never creates a tracker row, same as every other type."""
        self.client.login(**self.credentials)
        game_item = Item.objects.create(
            media_id="game-2000",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="Untracked Game",
            image="http://example.com/game2.jpg",
        )

        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": game_item.id,
                "media_type": "physical",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            CollectionEntry.objects.filter(user=self.user, item=game_item).exists()
        )
        self.assertFalse(Game.objects.filter(user=self.user, item=game_item).exists())

    def test_collection_add_does_not_change_existing_game_status(self):
        """Adding collection metadata must not overwrite an existing tracked game state."""
        self.client.login(**self.credentials)
        game_item = Item.objects.create(
            media_id="game-3000",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.GAME.value,
            title="Tracked Game",
            image="http://example.com/game3.jpg",
        )
        existing_game = Game.objects.create(
            user=self.user,
            item=game_item,
            status=Status.COMPLETED.value,
            progress=120,
        )

        response = self.client.post(
            reverse("collection_add"),
            {
                "item_id": game_item.id,
                "media_type": "rom",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Game.objects.filter(user=self.user, item=game_item).count(), 1)
        existing_game.refresh_from_db()
        self.assertEqual(existing_game.status, Status.COMPLETED.value)
        self.assertEqual(existing_game.progress, 120)

    def test_collection_add_redirects_to_next_on_form_error(self):
        """Test invalid submits redirect back to next URL when provided."""
        self.client.login(**self.credentials)
        next_url = "/search?q=clevatess&media_type=game"

        response = self.client.post(
            reverse("collection_add"),
            {
                "next": next_url,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_url)


class CollectionUpdateViewTest(TestCase):
    """Test collection update view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.item = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

        self.entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            media_type="dvd",
        )

    def test_collection_update_existing_entry(self):
        """Test POST updates existing CollectionEntry."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_update", kwargs={"entry_id": self.entry.id}),
            {
                "item": self.item.id,
                "media_type": "bluray",
                "resolution": "4k",
                "hdr": "HDR10",
            },
        )

        self.entry.refresh_from_db()
        self.assertEqual(self.entry.media_type, "bluray")
        self.assertEqual(self.entry.resolution, "4k")
        self.assertEqual(self.entry.hdr, "HDR10")

    def test_collection_update_nonexistent_entry(self):
        """Test 404 for non-existent entry_id."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_update", kwargs={"entry_id": 99999}),
            {
                "item": self.item.id,
                "media_type": "bluray",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_collection_update_other_user_entry(self):
        """Test user can only update their own entries."""
        self.client.login(**self.credentials)

        # Create another user and entry
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        other_entry = CollectionEntry.objects.create(
            user=other_user,
            item=self.item,
        )

        # Try to update other user's entry
        response = self.client.post(
            reverse("collection_update", kwargs={"entry_id": other_entry.id}),
            {
                "item": self.item.id,
                "media_type": "bluray",
            },
        )

        # Should return 404 (entry not found for this user)
        self.assertEqual(response.status_code, 404)


class CollectionRemoveViewTest(TestCase):
    """Test collection remove view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.item = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

        self.entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
        )

    def test_collection_remove_deletes_entry(self):
        """Test POST deletes CollectionEntry."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_remove", kwargs={"entry_id": self.entry.id}),
        )

        # Entry should be deleted
        self.assertFalse(CollectionEntry.objects.filter(id=self.entry.id).exists())

    def test_collection_remove_nonexistent_entry(self):
        """Test 404 for non-existent entry_id."""
        self.client.login(**self.credentials)
        response = self.client.post(
            reverse("collection_remove", kwargs={"entry_id": 99999}),
        )

        self.assertEqual(response.status_code, 404)

    def test_collection_remove_other_user_entry(self):
        """Test user can only delete their own entries."""
        self.client.login(**self.credentials)

        # Create another user and entry
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        other_entry = CollectionEntry.objects.create(
            user=other_user,
            item=self.item,
        )

        # Try to delete other user's entry
        response = self.client.post(
            reverse("collection_remove", kwargs={"entry_id": other_entry.id}),
        )

        # Should return 404 (entry not found for this user)
        self.assertEqual(response.status_code, 404)
        # Entry should still exist
        self.assertTrue(CollectionEntry.objects.filter(id=other_entry.id).exists())

    def test_collection_remove_redirects_to_next_when_provided(self):
        """Test remove submits redirect back to the provided next URL."""
        self.client.login(**self.credentials)
        next_url = "/details/tmdb/game/1234/test-game"

        response = self.client.post(
            reverse("collection_remove", kwargs={"entry_id": self.entry.id}),
            {"next": next_url},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_url)

    def test_collection_remove_season_deletes_only_sonarr_backed_episode_rows(self):
        """Season chip delete should remove collected Sonarr episode rows for that season."""
        self.client.login(**self.credentials)

        season_item = Item.objects.create(
            media_id="show-collection-remove",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Season 1",
            image="http://example.com/season.jpg",
        )
        season_one_episode = Item.objects.create(
            media_id="show-collection-remove",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Pilot",
            image="http://example.com/pilot.jpg",
        )
        season_two_episode = Item.objects.create(
            media_id="show-collection-remove",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Return",
            image="http://example.com/return.jpg",
        )
        season_one_entry = CollectionEntry.objects.create(
            user=self.user,
            item=season_one_episode,
        )
        season_two_entry = CollectionEntry.objects.create(
            user=self.user,
            item=season_two_episode,
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_one_episode,
            source="sonarr",
            quality_label="WebDL-1080p",
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_two_episode,
            source="sonarr",
            quality_label="WebDL-1080p",
        )

        response = self.client.post(
            reverse(
                "collection_remove_season",
                kwargs={"season_item_id": season_item.id},
            ),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            CollectionEntry.objects.filter(id=season_one_entry.id).exists(),
        )
        self.assertTrue(
            CollectionEntry.objects.filter(id=season_two_entry.id).exists(),
        )


class CollectionModalViewTest(TestCase):
    """Test collection modal view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.item = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )

    def test_collection_modal_new_entry(self):
        """Test modal for new entry (no existing collection)."""
        self.client.login(**self.credentials)
        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "1234",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["entry"])
        self.assertEqual(response.context["existing_entries"].count(), 0)

    def test_collection_modal_existing_entry(self):
        """Test modal for existing entry list."""
        self.client.login(**self.credentials)

        entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            media_type="bluray",
            resolution="1080p",
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "1234",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["entry"], entry)
        self.assertEqual(response.context["existing_entries"].count(), 1)
        self.assertFalse(response.context["form"].instance.pk)

    def test_collection_modal_existing_entries_multiple(self):
        """Test modal renders all existing entries for the same item."""
        self.client.login(**self.credentials)

        first_entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            media_type="physical",
            resolution="Super Nintendo Entertainment System",
            hdr="Deluxe",
        )
        second_entry = CollectionEntry.objects.create(
            user=self.user,
            item=self.item,
            media_type="rom",
            resolution="Sega Mega Drive/Genesis",
            hdr="Standard",
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "1234",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["existing_entries"].count(), 2)
        self.assertEqual(response.context["entry"], second_entry)
        self.assertContains(response, "Super Nintendo Entertainment System")
        self.assertContains(response, "Sega Mega Drive/Genesis")
        self.assertTrue(CollectionEntry.objects.filter(id=first_entry.id).exists())

    def test_collection_modal_show_displays_season_audit_entries_with_sources(self):
        """TV modal should summarize collected episodes by season."""
        self.client.login(**self.credentials)

        show_item = Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/show.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=show_item,
            media_type="digital",
            audio_codec="AAC",
            audio_channels="5.1",
            bitrate=1653,
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=show_item,
            source="sonarr",
        )
        Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Season 2",
            image="http://example.com/season2.jpg",
        )
        first_episode = Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=3,
            title="Third Episode",
            image="http://example.com/episode3.jpg",
        )
        second_episode = Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=4,
            title="Fourth Episode",
            image="http://example.com/episode4.jpg",
        )
        season_two_episode = Item.objects.create(
            media_id="tv-1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Season Two Premiere",
            image="http://example.com/season2-ep1.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=first_episode,
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=second_episode,
            media_type="digital",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=season_two_episode,
            media_type="bluray",
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=first_episode,
            source="sonarr",
            quality_label="WebDL-1080p",
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=second_episode,
            source="plex",
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_two_episode,
            source="sonarr",
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": "tv-1234",
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["item"], show_item)
        self.assertEqual(response.context["visible_existing_entries"], [])
        self.assertEqual(len(response.context["season_audit_entries"]), 2)
        self.assertEqual(
            response.context["season_audit_entries"][0]["title"],
            "Season 1",
        )
        self.assertEqual(
            response.context["season_audit_entries"][0]["display_title"],
            "Season 1: 2/2 • 100%",
        )
        self.assertEqual(
            response.context["season_audit_entries"][0]["progress_label"],
            "Collected Episodes: 2/2 • 100%",
        )
        self.assertEqual(
            response.context["season_audit_entries"][0]["source_labels"],
            ["Sonarr", "Plex"],
        )
        self.assertEqual(
            response.context["season_audit_entries"][0]["quality_label"],
            "WebDL-1080p",
        )
        self.assertEqual(
            response.context["season_audit_entries"][1]["title"],
            "Season 2",
        )
        self.assertEqual(
            response.context["season_audit_entries"][1]["progress_label"],
            "Collected Episodes: 1/1 • 100%",
        )
        self.assertContains(response, "Collected Seasons")
        self.assertContains(response, "Season 1: 2/2 • 100%")
        self.assertNotContains(response, "Collected Episodes: 2/2 • 100%")
        self.assertContains(response, "WebDL-1080p")
        self.assertContains(response, "Sonarr")
        self.assertContains(response, "Add Another Copy")
        self.assertContains(
            response,
            reverse(
                "collection_remove_season",
                kwargs={
                    "season_item_id": response.context["season_audit_entries"][0][
                        "season_item_id"
                    ],
                },
            ),
        )
        self.assertContains(response, 'aria-label="Remove collection entry"', count=2)
        self.assertNotContains(response, "Existing Entries")
        self.assertNotContains(response, "Delete")
        # Season 1 now counts both of its collected episodes, so the Plex-sourced
        # one contributes its label alongside Sonarr.
        self.assertContains(response, "Sources: Sonarr • Plex")
        self.assertNotContains(response, "S01E03 - Third Episode")

    def test_collection_modal_season_limits_episode_audit_entries_to_the_season(self):
        """Season modal should only show collected episode rows for that season."""
        self.client.login(**self.credentials)

        Item.objects.create(
            media_id="tv-5678",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Seasoned Show",
            image="http://example.com/show2.jpg",
        )
        Item.objects.create(
            media_id="tv-5678",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Season 1",
            image="http://example.com/season1.jpg",
        )
        Item.objects.create(
            media_id="tv-5678",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Season 2",
            image="http://example.com/season2.jpg",
        )
        season_one_episode = Item.objects.create(
            media_id="tv-5678",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Season One Episode",
            image="http://example.com/season1-ep1.jpg",
        )
        season_two_episode = Item.objects.create(
            media_id="tv-5678",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=1,
            title="Season Two Episode",
            image="http://example.com/season2-ep1.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=season_one_episode)
        CollectionEntry.objects.create(user=self.user, item=season_two_episode)
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_one_episode,
            source="sonarr",
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_two_episode,
            source="sonarr",
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "tv-5678",
                },
            ),
            {
                "season_number": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["episode_audit_entries"]), 1)
        self.assertEqual(
            response.context["episode_audit_entries"][0]["title"],
            "S01E01 - Season One Episode",
        )
        self.assertContains(response, "S01E01 - Season One Episode")
        self.assertNotContains(response, "S02E01 - Season Two Episode")

    def test_collection_modal_season_keeps_manual_entries_visible_with_sonarr_audit_rows(
        self,
    ):
        """Manual season copies should stay visible alongside Sonarr episode rows."""
        self.client.login(**self.credentials)

        Item.objects.create(
            media_id="tv-9012",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Hybrid Show",
            image="http://example.com/show3.jpg",
        )
        season_item = Item.objects.create(
            media_id="tv-9012",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Season 1",
            image="http://example.com/season1.jpg",
        )
        season_episode = Item.objects.create(
            media_id="tv-9012",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Pilot",
            image="http://example.com/pilot.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=season_item,
            media_type="digital",
        )
        CollectionEntry.objects.create(
            user=self.user,
            item=season_episode,
        )
        CollectionSourceState.objects.create(
            user=self.user,
            item=season_episode,
            source="sonarr",
            quality_label="WebDL-1080p",
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "tv-9012",
                },
            ),
            {
                "season_number": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["episode_audit_entries"]), 1)
        self.assertEqual(len(response.context["visible_existing_entries"]), 1)
        self.assertContains(response, "Existing Entries")
        self.assertContains(response, "Digital")
        self.assertContains(response, "S01E01 - Pilot")
        self.assertContains(response, "Source: Sonarr")
        self.assertContains(response, "WebDL-1080p")
        self.assertContains(
            response,
            reverse(
                "collection_remove",
                kwargs={
                    "entry_id": response.context["episode_audit_entries"][0]["entry"].id
                },
            ),
        )
        self.assertContains(response, 'aria-label="Remove collection entry"', count=2)
        self.assertNotContains(response, ">Collection Entry<", html=True)


class CollectionEditUiTest(TestCase):
    """Collected copies can be edited from the Collection tab (issue #1207)."""

    def setUp(self):
        """Set up a movie with two copies and a show with episodes."""
        self.client = Client()
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.movie = Item.objects.create(
            media_id="1234",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/image.jpg",
        )
        group = CollectionFieldGroup.objects.create(user=self.user, name="Condition")
        self.field = CollectionField.objects.create(
            group=group, label="Grade", media_types=["movie"]
        )

    def _movie_modal(self):
        return self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.MOVIE.value,
                    "media_id": "1234",
                },
            ),
        )

    def _show_with_episodes(self):
        for season_number in (1, 2):
            Item.objects.create(
                media_id="tv-1",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=season_number,
                title=f"Season {season_number}",
                image="http://example.com/s.jpg",
            )
        Item.objects.create(
            media_id="tv-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/show.jpg",
        )
        episodes = {}
        for season_number, episode_number in ((1, 1), (1, 2), (2, 1)):
            item = Item.objects.create(
                media_id="tv-1",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=season_number,
                episode_number=episode_number,
                title=f"Episode {season_number}-{episode_number}",
                image="http://example.com/e.jpg",
            )
            episodes[(season_number, episode_number)] = CollectionEntry.objects.create(
                user=self.user, item=item, media_type="digital", resolution="720p"
            )
        return episodes

    def test_modal_offers_an_edit_form_for_each_copy_prefilled(self):
        """Each existing copy gets its own pre-filled form posting to update."""
        digital = CollectionEntry.objects.create(
            user=self.user, item=self.movie, media_type="digital", resolution="1080p"
        )
        bluray = CollectionEntry.objects.create(
            user=self.user,
            item=self.movie,
            media_type="bluray",
            custom_field_values={str(self.field.id): "Mint"},
        )

        response = self._movie_modal()

        self.assertContains(response, 'aria-label="Edit collection entry"', count=2)
        for entry in (digital, bluray):
            update_url = reverse("collection_update", args=[entry.id])
            self.assertContains(response, f'action="{update_url}')
            self.assertContains(response, f'id="collection-edit-form-{entry.id}"')
            self.assertEqual(
                response.context["visible_existing_entries"][0].edit_form.instance.pk
                in (digital.id, bluray.id),
                True,
            )
        html = response.content.decode()
        self.assertIn('value="1080p"', html)
        self.assertIn('value="Mint"', html)
        # Edit widgets must not reuse the add form's ids.
        self.assertEqual(html.count('id="id_resolution"'), 1)
        self.assertIn(f'id="id_edit_{digital.id}_resolution"', html)

    def test_modal_without_copies_has_no_edit_form(self):
        """Nothing to edit until a copy exists."""
        response = self._movie_modal()
        self.assertNotContains(response, "Edit collection entry")
        self.assertNotContains(response, "Edit Copy")

    def test_editing_one_copy_leaves_the_other_alone(self):
        """Saving the edit form changes only that copy, custom fields included."""
        first = CollectionEntry.objects.create(
            user=self.user,
            item=self.movie,
            media_type="digital",
            custom_field_values={str(self.field.id): "Mint"},
        )
        second = CollectionEntry.objects.create(
            user=self.user, item=self.movie, media_type="digital"
        )

        response = self.client.post(
            reverse("collection_update", args=[second.id]),
            {
                "item": self.movie.id,
                "media_type": "bluray",
                "resolution": "4k",
                f"custom_field_{self.field.id}": "Good",
            },
        )

        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.media_type, "bluray")
        self.assertEqual(second.resolution, "4k")
        self.assertEqual(second.custom_field_values[str(self.field.id)], "Good")
        self.assertEqual(first.media_type, "digital")
        self.assertEqual(first.custom_field_values[str(self.field.id)], "Mint")

    def test_edit_can_clear_a_value(self):
        """Emptying a field in the edit form clears it (the Digital to unknown case)."""
        entry = CollectionEntry.objects.create(
            user=self.user, item=self.movie, media_type="digital", resolution="1080p"
        )
        self.client.post(
            reverse("collection_update", args=[entry.id]),
            {"item": self.movie.id, "media_type": "", "resolution": "1080p"},
        )
        entry.refresh_from_db()
        self.assertEqual(entry.media_type, "")
        self.assertEqual(entry.resolution, "1080p")

    def test_show_modal_season_rows_edit_all_their_episodes(self):
        """Season summary rows edit every collected episode of that season only."""
        episodes = self._show_with_episodes()
        season_one = Item.objects.get(
            media_id="tv-1", media_type=MediaTypes.SEASON.value, season_number=1
        )

        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": "tv-1",
                },
            ),
        )
        self.assertContains(response, 'aria-label="Edit collection entry"', count=2)
        self.assertContains(
            response,
            reverse("collection_update_season", args=[season_one.id]),
        )

        before = {key: entry.updated_at for key, entry in episodes.items()}
        response = self.client.post(
            reverse("collection_update_season", args=[season_one.id]),
            {"media_type": "bluray", "resolution": "1080p"},
        )

        self.assertEqual(response.status_code, 302)
        for key in ((1, 1), (1, 2)):
            episodes[key].refresh_from_db()
            self.assertEqual(episodes[key].media_type, "bluray")
            self.assertEqual(episodes[key].resolution, "1080p")
        episodes[(2, 1)].refresh_from_db()
        self.assertEqual(episodes[(2, 1)].media_type, "digital")
        for key in ((1, 1), (1, 2)):
            self.assertGreater(episodes[key].updated_at, before[key])
        self.assertEqual(episodes[(2, 1)].updated_at, before[(2, 1)])

    def test_season_edit_form_keeps_the_stored_format_selected(self):
        """A stored value missing from the format choices still shows as selected."""
        self._show_with_episodes()
        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": "tv-1",
                },
            ),
        )
        row = response.context["season_audit_entries"][0]
        self.assertEqual(row["edit_form"]["media_type"].value(), "digital")
        self.assertIn(
            "digital",
            [
                value
                for value, _label in row["edit_form"]
                .fields["media_type"]
                .widget.choices
            ],
        )
        self.assertContains(response, "Edit all episodes in this season")

    def test_season_update_skips_other_users_and_missing_seasons(self):
        """Only the requester's episodes change, and an empty season reports 404."""
        episodes = self._show_with_episodes()
        other = get_user_model().objects.create_user(username="o", password="12345")
        theirs = CollectionEntry.objects.create(
            user=other,
            item=episodes[(1, 1)].item,
            media_type="digital",
        )
        season_one = Item.objects.get(
            media_id="tv-1", media_type=MediaTypes.SEASON.value, season_number=1
        )
        self.client.post(
            reverse("collection_update_season", args=[season_one.id]),
            {"media_type": "bluray"},
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.media_type, "digital")

        CollectionEntry.objects.filter(user=self.user).delete()
        response = self.client.post(
            reverse("collection_update_season", args=[season_one.id]),
            {"media_type": "dvd"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)

    def test_season_update_requires_post_and_a_season_item(self):
        """GET is refused and a non-season item id is a 404."""
        episodes = self._show_with_episodes()
        season_one = Item.objects.get(
            media_id="tv-1", media_type=MediaTypes.SEASON.value, season_number=1
        )
        self.assertEqual(
            self.client.get(
                reverse("collection_update_season", args=[season_one.id])
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(
                reverse("collection_update_season", args=[episodes[(1, 1)].item_id]),
                {"media_type": "dvd"},
            ).status_code,
            404,
        )

    def test_season_modal_episode_rows_are_editable(self):
        """Episode rows in a season modal edit that one episode."""
        episodes = self._show_with_episodes()
        response = self.client.get(
            reverse(
                "collection_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "tv-1",
                },
            ),
            {"season_number": 1},
        )
        self.assertContains(response, 'aria-label="Edit collection entry"', count=2)
        self.assertContains(
            response,
            reverse("collection_update", args=[episodes[(1, 1)].id]),
        )
        self.assertNotContains(response, 'form="collection-edit-form-')
