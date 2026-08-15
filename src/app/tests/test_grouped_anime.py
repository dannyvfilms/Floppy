from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    TV,
    CollectionEntry,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    Season,
    Sources,
)
from app.services import grouped_anime


class GroupedAnimeClassifierTests(TestCase):
    """Verify exact classification and in-place grouped promotion."""

    def setUp(self):
        self.mapping = {
            "anime-show": {
                "mal_id": "12345",
                "tmdb_show_id": "9001",
                "tvdb_id": "7001",
                "imdb_id": "tt9001001",
            },
        }

    def test_classifier_requires_exact_id_and_animation(self):
        """Animation alone or a title match must not move a show."""
        animation = {
            "media_id": "9001",
            "genres": ["Animation"],
            "provider_external_ids": {"tvdb_id": "7001"},
        }
        result = grouped_anime.classify_tv_metadata(
            animation,
            mapping_data=self.mapping,
        )
        self.assertTrue(result.is_grouped_anime)
        self.assertEqual(result.mal_ids, ("12345",))

        not_animation = {**animation, "genres": ["Drama"]}
        self.assertFalse(
            grouped_anime.classify_tv_metadata(
                not_animation,
                mapping_data=self.mapping,
            ).is_grouped_anime,
        )

        title_only = {
            "media_id": "9999",
            "title": "Anime Show",
            "genres": ["Animation"],
        }
        self.assertFalse(
            grouped_anime.classify_tv_metadata(
                title_only,
                mapping_data=self.mapping,
            ).is_grouped_anime,
        )

    def test_promotion_preserves_tree_ids_and_history_shape(self):
        """Promotion changes buckets without creating replacement rows."""
        user = get_user_model().objects.create_user(
            username="grouped-anime",
            password="password",
        )
        tv_item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Anime Show",
            image="https://example.com/show.jpg",
        )
        tv = TV.objects.create(item=tv_item, user=user)
        second_user = get_user_model().objects.create_user(
            username="grouped-anime-tv-mode",
            password="password",
            anime_library_mode="tv",
        )
        second_tv = TV.objects.create(
            item=tv_item,
            user=second_user,
            status="Paused",
            score=9,
            notes="preserve this state",
        )
        collection = CollectionEntry.objects.create(
            item=tv_item,
            user=second_user,
            media_type="digital",
            resolution="1080p",
        )
        season_item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Anime Show Season 1",
            image="https://example.com/season.jpg",
        )
        season = Season.objects.create(item=season_item, user=user, related_tv=tv)
        episode_item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
            title="Episode 1",
            image="https://example.com/episode.jpg",
        )
        episode = Episode.objects.create(item=episode_item, related_season=season)
        second_season = Season.objects.create(
            item=season_item,
            user=second_user,
            related_tv=second_tv,
        )
        watch_date = timezone.now()
        second_episode = Episode.objects.create(
            item=episode_item,
            related_season=second_season,
            start_date=watch_date,
            end_date=watch_date,
        )
        TV.objects.filter(pk=second_tv.pk).update(status="Paused")
        second_tv.refresh_from_db()
        second_history_count = second_tv.history.count()
        ids = (
            tv_item.pk,
            season_item.pk,
            episode_item.pk,
            episode.pk,
            second_season.pk,
            second_episode.pk,
        )

        match = grouped_anime.classify_tv_metadata(
            {
                "media_id": "9001",
                "genres": ["Animation"],
                "provider_external_ids": {
                    "tvdb_id": "7001",
                    "imdb_id": "tt9001001",
                },
            },
            mapping_data=self.mapping,
        )
        self.assertTrue(grouped_anime.promote_grouped_anime(tv_item, match))

        self.assertEqual(
            (
                tv_item.pk,
                season_item.pk,
                episode_item.pk,
                episode.pk,
                second_season.pk,
                second_episode.pk,
            ),
            ids,
        )
        self.assertTrue(
            Item.objects.filter(
                pk__in=[tv_item.pk, season_item.pk, episode_item.pk],
                library_media_type=MediaTypes.ANIME.value,
            ).count()
            == 3,
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=tv_item,
                provider=Sources.TVDB.value,
                provider_media_id="7001",
                provider_media_type=MediaTypes.TV.value,
            ).exists(),
        )
        self.assertTrue(
            ItemProviderLink.objects.filter(
                item=tv_item,
                provider=Sources.MAL.value,
                provider_media_id="12345",
                provider_media_type=MediaTypes.TV.value,
            ).exists(),
        )

        # A retry sees the same locked tree and must not create replacement
        # rows or duplicate provider links.
        self.assertTrue(grouped_anime.promote_grouped_anime(tv_item, match))
        self.assertEqual(
            ItemProviderLink.objects.filter(item=tv_item).count(),
            3,
        )
        second_tv.refresh_from_db()
        second_user.refresh_from_db()
        self.assertEqual(second_tv.status, "Paused")
        self.assertEqual(str(second_tv.score), "9.0")
        self.assertEqual(second_tv.notes, "preserve this state")
        self.assertIsNotNone(second_tv.start_date)
        self.assertIsNotNone(second_tv.end_date)
        self.assertEqual(second_tv.history.count(), second_history_count)
        self.assertEqual(second_user.anime_library_mode, "tv")
        self.assertEqual(
            CollectionEntry.objects.get(pk=collection.pk).resolution,
            "1080p",
        )
        client = Client()
        client.force_login(second_user)
        response = client.get(reverse("medialist", args=[MediaTypes.TV.value]))
        titles = [
            media.item.title for media in response.context["media_list"].object_list
        ]
        self.assertIn("Anime Show", titles)

    def test_conflicting_exact_provider_groups_fail_closed(self):
        """IDs belonging to separate identity groups must never be merged."""
        mapping = {
            "first": {"mal_id": "1", "tmdb_show_id": "9001"},
            "second": {
                "mal_id": "2",
                "tvdb_id": "7002",
                "imdb_id": "tt7002",
            },
        }
        for external_ids in (
            {"tvdb_id": "7002"},
            {"imdb_id": "tt7002"},
        ):
            with self.subTest(external_ids=external_ids):
                result = grouped_anime.classify_tv_metadata(
                    {
                        "media_id": "9001",
                        "genres": ["Animation"],
                        "provider_external_ids": external_ids,
                    },
                    mapping_data=mapping,
                )

                self.assertFalse(result.is_grouped_anime)
                self.assertEqual(result.reason, "conflicting_exact_external_ids")
                self.assertEqual(len(result.candidate_group_keys), 2)

    def test_multiple_mal_seasons_require_one_identity_group(self):
        """Multiple MAL seasons are safe only when provider IDs connect them."""
        mapping = {
            "season-1": {"mal_id": "1", "tvdb_id": "7001"},
            "season-2": {"mal_id": "2", "tvdb_id": "7001"},
        }
        result = grouped_anime.classify_tv_metadata(
            {
                "media_id": "9001",
                "genres": ["Animation"],
                "provider_external_ids": {"tvdb_id": "7001"},
            },
            mapping_data=mapping,
        )

        self.assertTrue(result.is_grouped_anime)
        self.assertEqual(result.mal_ids, ("1", "2"))
        self.assertIn("multiple_mal_seasons", result.reason)
        self.assertIsNotNone(result.mapping_group_key)
