import datetime
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    CollectionEntry,
    Game,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Music,
    Sources,
    Status,
    Tag,
)
from lists import smart_rules
from lists.models import CustomList, CustomListItem


class CustomListModelTest(TestCase):
    """Test case for the CustomList model."""

    def setUp(self):
        """Set up test data for CustomList model."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.collaborator_credentials = {
            "username": "collaborator",
            "password": "12345",
        }
        self.collaborator = get_user_model().objects.create_user(
            **self.collaborator_credentials,
        )

        self.custom_list = CustomList.objects.create(
            name="Test List",
            description="Test Description",
            owner=self.user,
        )
        self.custom_list.collaborators.add(self.collaborator)

        self.item = Item.objects.create(
            title="Test Item",
            media_id="123",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
        )

        self.non_member_credentials = {
            "username": "non_member",
            "password": "12345",
        }
        self.non_member = get_user_model().objects.create_user(
            **self.non_member_credentials,
        )

    def test_custom_list_creation(self):
        """Test the creation of a CustomList instance."""
        self.assertEqual(self.custom_list.name, "Test List")
        self.assertEqual(self.custom_list.description, "Test Description")
        self.assertEqual(self.custom_list.owner, self.user)

    def test_custom_list_str_representation(self):
        """Test the string representation of a CustomList."""
        self.assertEqual(str(self.custom_list), "Test List")

    def test_public_reference_uses_slug_for_public_lists(self):
        """Public lists should prefer their custom slug in shared URLs."""
        self.custom_list.visibility = "public"
        self.custom_list.public_slug = "test-list"

        self.assertEqual(self.custom_list.public_reference, "test-list")

    def test_owner_permissions(self):
        """Test owner permissions on custom list."""
        self.assertTrue(self.custom_list.user_can_view(self.user))
        self.assertTrue(self.custom_list.user_can_edit(self.user))
        self.assertTrue(self.custom_list.user_can_delete(self.user))

    def test_collaborator_permissions(self):
        """Test collaborator permissions on custom list."""
        self.assertTrue(self.custom_list.user_can_view(self.collaborator))
        self.assertTrue(self.custom_list.user_can_edit(self.collaborator))
        self.assertFalse(self.custom_list.user_can_delete(self.collaborator))

    def test_non_member_permissions(self):
        """Test non-member permissions on custom list."""
        self.assertFalse(self.custom_list.user_can_view(self.non_member))
        self.assertFalse(self.custom_list.user_can_edit(self.non_member))
        self.assertFalse(self.custom_list.user_can_delete(self.non_member))

    def test_duplicate_item_constraint(self):
        """Test that an item cannot be added twice to the same list."""
        CustomListItem.objects.create(
            item=self.item,
            custom_list=self.custom_list,
        )

        with self.assertRaises(IntegrityError):
            CustomListItem.objects.create(
                item=self.item,
                custom_list=self.custom_list,
            )


class CustomListManagerTest(TestCase):
    """Test case for the CustomListManager."""

    def setUp(self):
        """Set up test data for CustomListManager tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.other_credentials = {"username": "other", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.other_user = get_user_model().objects.create_user(**self.other_credentials)
        self.list1 = CustomList.objects.create(name="List 1", owner=self.user)
        self.list2 = CustomList.objects.create(name="List 2", owner=self.other_user)
        self.list2.collaborators.add(self.user)

    def test_get_user_lists(self):
        """Test the get_user_lists method of CustomListManager."""
        user_lists = CustomList.objects.get_user_lists(self.user)
        self.assertEqual(user_lists.count(), 2)
        self.assertIn(self.list1, user_lists)
        self.assertIn(self.list2, user_lists)

    def test_get_by_reference_resolves_public_slug(self):
        """Slug references should resolve public lists."""
        self.list1.visibility = "public"
        self.list1.public_slug = "list-one"
        self.list1.save(update_fields=["visibility", "public_slug"])

        resolved = CustomList.objects.get_by_reference("list-one")

        self.assertEqual(resolved, self.list1)

    def test_smart_list_sync_items(self):
        """Smart list should sync matching items from saved filters."""
        item = Item.objects.create(
            title="Smart Movie",
            media_id="456",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie.jpg",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        smart_list = CustomList.objects.create(
            name="Smart",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"status": "all", "rating": "all", "collection": "all"},
        )

        smart_list.sync_smart_items()
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

    def test_collect_matching_item_ids_fast_paths_simple_status_rules(self):
        """Status-only smart rules should not build extra collection/rating scans."""
        completed_item = Item.objects.create(
            title="Completed Movie",
            media_id="4567",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/completed.jpg",
        )
        dropped_item = Item.objects.create(
            title="Dropped Movie",
            media_id="4568",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/dropped.jpg",
        )
        Movie.objects.create(
            item=completed_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        Movie.objects.create(
            item=dropped_item,
            user=self.user,
            status=Status.DROPPED.value,
        )

        normalized_rules = smart_rules.normalize_rule_payload(
            {
                "media_types": [MediaTypes.MOVIE.value],
                "status": Status.COMPLETED.value,
            },
            self.user,
        )

        with (
            patch(
                "lists.smart_rules._collection_filter_context",
                side_effect=AssertionError("collection context should not be built"),
            ),
            patch(
                "lists.smart_rules._filter_item_ids_by_rating",
                side_effect=AssertionError("rating filter scan should not run"),
            ),
            patch(
                "lists.smart_rules._matches_item_filters",
                side_effect=AssertionError("simple status rules should not scan items"),
            ),
        ):
            matched_ids = smart_rules.collect_matching_item_ids(
                self.user, normalized_rules
            )

        self.assertEqual(matched_ids, {completed_item.id})

    def test_smart_rules_support_multi_status_and_tag_modes(self):
        """Smart-list matching combines statuses with OR and tags by mode."""
        both_item = Item.objects.create(
            title="Action Comedy Movie",
            media_id="multi-1",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        action_item = Item.objects.create(
            title="Action Movie",
            media_id="multi-2",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        comedy_item = Item.objects.create(
            title="Comedy Movie",
            media_id="multi-3",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        plain_item = Item.objects.create(
            title="Plain Movie",
            media_id="multi-4",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
        )
        Movie.objects.create(
            item=both_item, user=self.user, status=Status.COMPLETED.value
        )
        Movie.objects.create(
            item=action_item, user=self.user, status=Status.DROPPED.value
        )
        Movie.objects.create(
            item=comedy_item, user=self.user, status=Status.PLANNING.value
        )
        Movie.objects.create(
            item=plain_item, user=self.user, status=Status.PAUSED.value
        )
        action_tag = Tag.objects.create(user=self.user, name="Action")
        comedy_tag = Tag.objects.create(user=self.user, name="Comedy")
        ItemTag.objects.create(item=both_item, tag=action_tag)
        ItemTag.objects.create(item=both_item, tag=comedy_tag)
        ItemTag.objects.create(item=action_item, tag=action_tag)
        ItemTag.objects.create(item=comedy_item, tag=comedy_tag)

        status_rules = smart_rules.normalize_rule_payload(
            {
                "media_types": [MediaTypes.MOVIE.value],
                "status": [Status.COMPLETED.value, Status.DROPPED.value],
            },
            self.user,
        )
        self.assertEqual(
            smart_rules.collect_matching_item_ids(self.user, status_rules),
            {both_item.id, action_item.id},
        )

        for mode, expected_ids in {
            "and": {both_item.id},
            "or": {both_item.id, action_item.id, comedy_item.id},
            "not": {plain_item.id},
        }.items():
            rules = smart_rules.normalize_rule_payload(
                {
                    "media_types": [MediaTypes.MOVIE.value],
                    "tag": ["Action", "Comedy"],
                    "tag_mode": mode,
                },
                self.user,
            )
            self.assertEqual(
                smart_rules.collect_matching_item_ids(self.user, rules),
                expected_ids,
            )
            self.assertEqual(
                {
                    item.id
                    for item in (both_item, action_item, comedy_item, plain_item)
                    if smart_rules.item_matches_rules(self.user, item, rules)
                },
                expected_ids,
            )

    def test_smart_list_collection_filter_uses_episode_collection_for_tv(self):
        """Collected TV rules should match when related episodes are collected."""
        tv_item = Item.objects.create(
            title="Collected Show",
            media_id="777",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/tv.jpg",
        )
        TV.objects.create(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)

        episode_item = Item.objects.create(
            title="Collected Show Episode",
            media_id="777",
            media_type=MediaTypes.EPISODE.value,
            source=Sources.TMDB.value,
            season_number=1,
            episode_number=1,
            image="https://example.com/episode.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=episode_item)

        smart_list = CustomList.objects.create(
            name="Collected Shows",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.TV.value],
            smart_filters={"collection": "collected"},
        )

        smart_list.sync_smart_items()
        self.assertTrue(smart_list.items.filter(id=tv_item.id).exists())

    def test_collect_matching_item_ids_excludes_collected_episode_items_for_tv(self):
        """Collection-only fallback shouldn't surface bare episode items for a TV row.

        Episodes carrying `library_media_type="tv"` (normal per-episode TV tracking)
        match the "tv" media type via `library_media_type`, but the Episode model has
        no `user` field, so returning their raw item ids crashes any downstream code
        that resolves them with `Episode.objects.filter(user=...)` (issue #397).
        """
        tv_item = Item.objects.create(
            title="Collected Show",
            media_id="778",
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/tv.jpg",
        )
        TV.objects.create(item=tv_item, user=self.user, status=Status.IN_PROGRESS.value)

        untracked_episode_item = Item.objects.create(
            title="Untracked Episode",
            media_id="779",
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            season_number=1,
            episode_number=1,
            image="https://example.com/episode.jpg",
        )
        CollectionEntry.objects.create(user=self.user, item=untracked_episode_item)

        normalized_rules = smart_rules.normalize_rule_payload(
            {"media_types": [MediaTypes.TV.value], "status": "all"},
            self.user,
        )
        matched_ids = smart_rules.collect_matching_item_ids(
            self.user,
            normalized_rules,
            include_collection_only_untracked=True,
        )

        self.assertIn(tv_item.id, matched_ids)
        self.assertNotIn(untracked_episode_item.id, matched_ids)

    def test_smart_list_language_filter(self):
        """Language filter should match item language metadata."""
        item = Item.objects.create(
            title="English Movie",
            media_id="900",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/english.jpg",
            languages=["en"],
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        smart_list = CustomList.objects.create(
            name="English Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"language": "en"},
        )
        smart_list.sync_smart_items()
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_implied_genre_filter_matches_item_implied_genres(self):
        """Implied genre rules should match only the implied_genres field."""
        item = Item.objects.create(
            title="Genre Album Track",
            media_id="music-1",
            media_type=MediaTypes.MUSIC.value,
            source=Sources.MUSICBRAINZ.value,
            image="https://example.com/music.jpg",
            genres=["Krautrock"],
            implied_genres=["Rock"],
        )
        Music.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        normalized_rules = smart_rules.normalize_rule_payload(
            {
                "media_types": [MediaTypes.MUSIC.value],
                "implied_genre": "Rock",
            },
            self.user,
        )

        matched_ids = smart_rules.collect_matching_item_ids(self.user, normalized_rules)

        self.assertEqual(matched_ids, {item.id})

    def test_build_rule_filter_data_keeps_direct_and_implied_genres_separate(self):
        item = Item.objects.create(
            title="Music Item",
            media_id="music-2",
            media_type=MediaTypes.MUSIC.value,
            source=Sources.MUSICBRAINZ.value,
            genres=["Art Rock"],
            implied_genres=["Rock"],
        )
        Music.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        filter_data = smart_rules.build_rule_filter_data(
            self.user,
            [MediaTypes.MUSIC.value],
            "all",
            "",
        )

        self.assertEqual(filter_data["genres"], ["Art Rock"])
        self.assertEqual(filter_data["implied_genres"], ["Rock"])

    def test_smart_list_platform_filter(self):
        """Platform filter should match game platform metadata."""
        item = Item.objects.create(
            title="Switch Game",
            media_id="1200",
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            image="https://example.com/game.jpg",
            platforms=["Switch"],
        )
        Game.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        smart_list = CustomList.objects.create(
            name="Switch Games",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.GAME.value],
            smart_filters={"platform": "Switch"},
        )
        smart_list.sync_smart_items()
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_provider_filter_matches_when_region_configured(self):
        """Provider filter should match items available on that service in the user's region."""
        item = Item.objects.create(
            title="Streaming Movie",
            media_id="1300",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie.jpg",
            watch_providers={
                "US": {
                    "flatrate": [
                        {"provider_id": 8, "provider_name": "Netflix"},
                    ],
                },
            },
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        self.user.watch_provider_region = "US"
        self.user.save(update_fields=["watch_provider_region"])

        smart_list = CustomList.objects.create(
            name="Netflix Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"provider": "Netflix"},
        )
        smart_list.sync_smart_items()
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_provider_filter_no_match_without_region_configured(self):
        """Provider filter should exclude items when the owner has no region set."""
        item = Item.objects.create(
            title="Unfiltered Movie",
            media_id="1301",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie2.jpg",
            watch_providers={
                "US": {
                    "flatrate": [
                        {"provider_id": 8, "provider_name": "Netflix"},
                    ],
                },
            },
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        smart_list = CustomList.objects.create(
            name="Netflix Movies No Region",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"provider": "Netflix"},
        )
        smart_list.sync_smart_items()
        self.assertFalse(smart_list.items.filter(id=item.id).exists())

    def test_build_rule_filter_data_includes_providers_when_region_configured(self):
        item = Item.objects.create(
            title="Provider Data Movie",
            media_id="1302",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/movie3.jpg",
            watch_providers={
                "US": {
                    "flatrate": [
                        {"provider_id": 384, "provider_name": "HBO Max"},
                    ],
                },
            },
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)
        self.user.watch_provider_region = "US"
        self.user.save(update_fields=["watch_provider_region"])

        filter_data = smart_rules.build_rule_filter_data(
            self.user,
            [MediaTypes.MOVIE.value],
            "all",
            "",
        )

        self.assertTrue(filter_data["show_providers"])
        self.assertIn(
            {"value": "HBO Max", "label": "HBO Max"}, filter_data["providers"]
        )

    def test_smart_list_not_rated_excludes_rated_replays_on_full_sync(self):
        """Full smart-list rebuilds should treat any scored replay as rated."""
        item = Item.objects.create(
            title="Replay Rated Movie",
            media_id="1400",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/replay-rated-movie.jpg",
        )
        first_watch = timezone.now() - timedelta(days=14)
        replay_watch = timezone.now() - timedelta(days=1)
        Movie.objects.bulk_create(
            [
                Movie(
                    item=item,
                    user=self.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    score=8,
                    start_date=first_watch,
                    end_date=first_watch,
                ),
                Movie(
                    item=item,
                    user=self.user,
                    status=Status.COMPLETED.value,
                    progress=1,
                    score=None,
                    start_date=replay_watch,
                    end_date=replay_watch,
                ),
            ],
        )

        smart_list = CustomList.objects.create(
            name="Unrated Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"rating": "not_rated"},
        )

        smart_list.sync_smart_items()

        self.assertFalse(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_not_rated_ignores_replay_on_incremental_sync(self):
        """Replay saves should not add an item once any previous play is rated."""
        item = Item.objects.create(
            title="Incremental Replay Rated Movie",
            media_id="1401",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/incremental-replay-rated-movie.jpg",
        )
        first_watch = timezone.now() - timedelta(days=10)
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            score=9,
            start_date=first_watch,
            end_date=first_watch,
        )

        smart_list = CustomList.objects.create(
            name="Incremental Unrated Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"rating": "not_rated"},
        )
        self.assertFalse(smart_list.items.filter(id=item.id).exists())

        replay_watch = timezone.now() - timedelta(hours=6)
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            score=None,
            start_date=replay_watch,
            end_date=replay_watch,
        )

        self.assertFalse(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_rating_range_filter(self):
        """Rating min/max should constrain matched tracked items."""
        low_item = Item.objects.create(
            title="Low Rated Movie",
            media_id="1500",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/low-rated.jpg",
        )
        high_item = Item.objects.create(
            title="High Rated Movie",
            media_id="1501",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/high-rated.jpg",
        )
        Movie.objects.create(
            item=low_item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=6.4,
        )
        Movie.objects.create(
            item=high_item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=8.2,
        )

        smart_list = CustomList.objects.create(
            name="Highly Rated Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={"rating_min": "7.0"},
        )

        smart_list.sync_smart_items()

        self.assertFalse(smart_list.items.filter(id=low_item.id).exists())
        self.assertTrue(smart_list.items.filter(id=high_item.id).exists())

    def test_smart_list_release_date_range_filter(self):
        """Release date min/max should match item release dates."""
        older_item = Item.objects.create(
            title="Nineties Movie",
            media_id="1600",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/nineties.jpg",
            release_datetime=timezone.make_aware(datetime.datetime(1999, 6, 1, 12, 0)),
        )
        newer_item = Item.objects.create(
            title="Two Thousands Movie",
            media_id="1601",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/twothousands.jpg",
            release_datetime=timezone.make_aware(datetime.datetime(2005, 6, 1, 12, 0)),
        )
        Movie.objects.create(
            item=older_item, user=self.user, status=Status.COMPLETED.value
        )
        Movie.objects.create(
            item=newer_item, user=self.user, status=Status.COMPLETED.value
        )

        smart_list = CustomList.objects.create(
            name="2000s Movies",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={
                "release_date_from": "2000-01-01",
                "release_date_to": "2009-12-31",
            },
        )

        smart_list.sync_smart_items()

        self.assertFalse(smart_list.items.filter(id=older_item.id).exists())
        self.assertTrue(smart_list.items.filter(id=newer_item.id).exists())

    def test_smart_list_date_added_range_filter(self):
        """Date-added min/max should filter against tracker row created_at."""
        older_item = Item.objects.create(
            title="Older Added Movie",
            media_id="1700",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/older-added.jpg",
        )
        newer_item = Item.objects.create(
            title="Newer Added Movie",
            media_id="1701",
            media_type=MediaTypes.MOVIE.value,
            source=Sources.TMDB.value,
            image="https://example.com/newer-added.jpg",
        )
        older_movie = Movie.objects.create(
            item=older_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        newer_movie = Movie.objects.create(
            item=newer_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        older_created_at = timezone.now() - timedelta(days=30)
        newer_created_at = timezone.now() - timedelta(days=2)
        Movie.objects.filter(pk=older_movie.pk).update(created_at=older_created_at)
        Movie.objects.filter(pk=newer_movie.pk).update(created_at=newer_created_at)

        smart_list = CustomList.objects.create(
            name="Recent Adds",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.MOVIE.value],
            smart_filters={
                "date_added_from": (
                    timezone.localdate() - timedelta(days=7)
                ).isoformat(),
                "date_added_to": timezone.localdate().isoformat(),
            },
        )

        smart_list.sync_smart_items()

        self.assertFalse(smart_list.items.filter(id=older_item.id).exists())
        self.assertTrue(smart_list.items.filter(id=newer_item.id).exists())

    def test_smart_list_updates_on_media_status_and_delete(self):
        """Media save/delete events should incrementally add/remove smart memberships."""
        smart_list = CustomList.objects.create(
            name="Planning Games",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.GAME.value],
            smart_filters={"status": Status.PLANNING.value},
        )
        item = Item.objects.create(
            title="Signal Game",
            media_id="1300",
            media_type=MediaTypes.GAME.value,
            source=Sources.IGDB.value,
            image="https://example.com/signal-game.jpg",
        )

        game = Game.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

        game.status = Status.COMPLETED.value
        game.save(update_fields=["status"])
        self.assertFalse(smart_list.items.filter(id=item.id).exists())

        game.status = Status.PLANNING.value
        game.save(update_fields=["status"])
        self.assertTrue(smart_list.items.filter(id=item.id).exists())

        game.delete()
        self.assertFalse(smart_list.items.filter(id=item.id).exists())

    def test_smart_list_updates_on_episode_collection_changes(self):
        """Episode collection ownership should incrementally update TV collection lists."""
        smart_list = CustomList.objects.create(
            name="Collected Shows",
            owner=self.user,
            is_smart=True,
            smart_media_types=[MediaTypes.TV.value],
            smart_filters={"collection": "collected"},
        )
        tv_item = Item.objects.create(
            title="Collection Show",
            media_id="1400",
            media_type=MediaTypes.TV.value,
            source=Sources.TMDB.value,
            image="https://example.com/collection-show.jpg",
        )
        TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            title="Collection Show Episode",
            media_id="1400",
            media_type=MediaTypes.EPISODE.value,
            source=Sources.TMDB.value,
            season_number=1,
            episode_number=1,
            image="https://example.com/collection-show-episode.jpg",
        )

        self.assertFalse(smart_list.items.filter(id=tv_item.id).exists())

        entry = CollectionEntry.objects.create(user=self.user, item=episode_item)
        self.assertTrue(smart_list.items.filter(id=tv_item.id).exists())

        entry.delete()
        self.assertFalse(smart_list.items.filter(id=tv_item.id).exists())


class CustomListItemDeleteRenumberTest(TestCase):
    """CustomListItem.delete() must safely renumber later list positions."""

    def setUp(self):
        """Create a user, a list, and enough items to force multi-row renumbering."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )
        self.custom_list = CustomList.objects.create(name="Big List", owner=self.user)
        self.items = []
        for index in range(50):
            item = Item.objects.create(
                title=f"Item {index}",
                media_id=str(1000 + index),
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
            )
            self.items.append(item)
            CustomListItem.objects.create(custom_list=self.custom_list, item=item)

    def test_deleting_from_the_middle_renumbers_without_error(self):
        """Deleting an early item must cleanly renumber ~49 trailing rows."""
        target = CustomListItem.objects.get(
            custom_list=self.custom_list,
            item=self.items[5],
        )

        target.delete()

        remaining = list(
            CustomListItem.objects.filter(custom_list=self.custom_list).order_by(
                "list_item_id",
            ),
        )
        self.assertEqual(len(remaining), 49)
        # Sequential with no gap left where the deleted row was.
        self.assertEqual(
            [entry.list_item_id for entry in remaining],
            list(range(len(remaining))),
        )
        self.assertFalse(any(entry.list_item_id is None for entry in remaining))

    def test_deleting_every_item_one_at_a_time_never_collides(self):
        """Repeated single deletes from the front must never raise IntegrityError."""
        for _ in range(len(self.items)):
            first = (
                CustomListItem.objects.filter(custom_list=self.custom_list)
                .order_by("list_item_id")
                .first()
            )
            try:
                first.delete()
            except IntegrityError as exc:  # pragma: no cover - the bug this guards
                self.fail(f"delete() raised IntegrityError: {exc}")

        self.assertEqual(
            CustomListItem.objects.filter(custom_list=self.custom_list).count(),
            0,
        )

    def test_delete_refreshes_a_stale_position_after_locking_the_list(self):
        """A delete must not close the gap using a pre-lock position snapshot."""
        stale_target = CustomListItem.objects.get(
            custom_list=self.custom_list,
            item=self.items[3],
        )
        CustomListItem.objects.get(
            custom_list=self.custom_list,
            item=self.items[0],
        ).delete()

        # The first delete renumbered this row in the database, while the
        # already-loaded instance still carries its original position.
        stale_target.delete()

        positions = list(
            CustomListItem.objects.filter(custom_list=self.custom_list)
            .order_by("list_item_id")
            .values_list("list_item_id", flat=True),
        )
        self.assertEqual(positions, list(range(len(positions))))

    def test_list_item_id_uniqueness_remains_enforced(self):
        """Every supported database must reject duplicate list positions."""
        first = CustomListItem.objects.get(
            custom_list=self.custom_list,
            item=self.items[0],
        )
        duplicate = CustomListItem(
            custom_list=self.custom_list,
            item=Item.objects.create(
                title="Duplicate position",
                media_id="duplicate-position",
                media_type=MediaTypes.MOVIE.value,
                source=Sources.TMDB.value,
            ),
            list_item_id=first.list_item_id,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate.save(force_insert=True)
