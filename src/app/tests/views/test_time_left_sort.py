from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django.test import TestCase
from django.utils import timezone
from django.utils.crypto import get_random_string

from app.models import (
    TV,
    BasicMedia,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.views import _sort_tv_media_by_time_left


class TVTimeLeftSortTests(TestCase):
    """Regression tests for TV time-left sorting."""

    def setUp(self):
        """Create a user for sort tests."""
        password = get_random_string(16)
        self.user = get_user_model().objects.create_user(
            username="test",
            password=password,
        )
        self.now = timezone.now()

    def _create_tv(self, title, media_id, season_configs):
        tv_item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title=title,
            image="http://example.com/show.jpg",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        for config in season_configs:
            season_number = config["season_number"]
            released_episodes = config["released_episodes"]
            watched_episodes = config.get("watched_episodes", 0)
            runtime_minutes = config.get("runtime_minutes", 30)
            watched_instances = []

            season_item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title=f"{title} Season {season_number}",
                image="http://example.com/season.jpg",
                season_number=season_number,
            )
            season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=config["status"],
            )

            for episode_number in range(1, released_episodes + 1):
                episode_item = Item.objects.create(
                    media_id=media_id,
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    title=f"{title} S{season_number:02d}E{episode_number:02d}",
                    image="http://example.com/episode.jpg",
                    season_number=season_number,
                    episode_number=episode_number,
                    runtime_minutes=runtime_minutes,
                    release_datetime=self.now - timedelta(days=episode_number),
                )
                if episode_number <= watched_episodes:
                    watched_instances.append(
                        Episode(
                            item=episode_item,
                            related_season=season,
                            end_date=self.now,
                        ),
                    )
            if watched_instances:
                Episode.objects.bulk_create(watched_instances)

        return tv

    def test_time_left_sort_excludes_dropped_season_remaining_episodes_only(self):
        """Ignore dropped-season backlog in time-left sorting for active shows."""
        excluded = self._create_tv(
            "Excluded Seasons Show",
            "tv-excluded",
            [
                {
                    "season_number": 1,
                    "status": Status.DROPPED.value,
                    "released_episodes": 10,
                    "watched_episodes": 5,
                },
                {
                    "season_number": 2,
                    "status": Status.IN_PROGRESS.value,
                    "released_episodes": 10,
                    "watched_episodes": 1,
                },
            ],
        )
        self._create_tv(
            "Comparison Show",
            "tv-comparison",
            [
                {
                    "season_number": 1,
                    "status": Status.IN_PROGRESS.value,
                    "released_episodes": 11,
                    "watched_episodes": 0,
                },
            ],
        )

        media_list = list(
            TV.objects.filter(user=self.user)
            .select_related("item")
            .prefetch_related(
                Prefetch("seasons", queryset=Season.objects.select_related("item")),
                Prefetch(
                    "seasons__episodes",
                    queryset=Episode.objects.select_related("item"),
                ),
            ),
        )
        BasicMedia.objects.annotate_max_progress(media_list, MediaTypes.TV.value)

        sorted_media = _sort_tv_media_by_time_left(media_list, direction="asc")

        self.assertEqual(
            [media.item.title for media in sorted_media[:2]],
            ["Excluded Seasons Show", "Comparison Show"],
        )

        sorted_excluded = next(
            media for media in sorted_media if media.item.title == excluded.item.title
        )
        self.assertEqual(sorted_excluded.episodes_left_display, 9)
        self.assertEqual(sorted_excluded.time_left_display, "4h 30m")

        # Dropped seasons are excluded from episodes_left/time_left as well,
        # matching the display math.
        self.assertEqual(sorted_excluded.episodes_left, 9)
        self.assertEqual(sorted_excluded.time_left, 270)

    def test_time_left_sort_does_not_crash_with_untracked_entry(self):
        """Untracked MediaListEntry (media=None) must not crash the TV time-left sort.

        Regression for GitHub #215: after connecting Sonarr, items appear in
        the TV list as untracked MediaListEntry objects. Their .progress is None
        (via __getattr__ fallback), which caused TypeError in max() at line 286.
        """
        from app.media_list_views import MediaListEntry

        tv = self._create_tv(
            "Tracked Show",
            "tv-tracked",
            [
                {
                    "season_number": 1,
                    "status": Status.IN_PROGRESS.value,
                    "released_episodes": 5,
                    "watched_episodes": 2,
                }
            ],
        )

        untracked_item = Item.objects.create(
            media_id="tv-sonarr-only",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Sonarr Only Show",
            image="http://example.com/show.jpg",
        )

        tracked_entry = MediaListEntry.from_media(tv)
        untracked_entry = MediaListEntry(item=untracked_item, media=None)

        BasicMedia.objects.annotate_max_progress([tv], MediaTypes.TV.value)

        result = _sort_tv_media_by_time_left(
            [tracked_entry, untracked_entry], direction="asc"
        )

        titles = [m.item.title for m in result]
        self.assertIn("Tracked Show", titles)
        self.assertIn("Sonarr Only Show", titles)
        self.assertEqual(result[-1].item.title, "Sonarr Only Show")

    def test_media_list_entry_pickle_round_trip(self):
        """MediaListEntry must survive a pickle round-trip (simulates cache.set/cache.get).

        Regression for GitHub #215: __getattr__ accessing self.media during unpickling
        caused recursive __getattr__ calls before __dict__ was populated, resulting in
        TypeError: 'NoneType' object is not callable inside pickle.loads().
        """
        import pickle

        from app.media_list_views import MediaListEntry

        tv = self._create_tv(
            "Test Show",
            "pickle-test-tv",
            [
                {
                    "season_number": 1,
                    "status": Status.IN_PROGRESS.value,
                    "released_episodes": 5,
                    "watched_episodes": 2,
                }
            ],
        )

        entry = MediaListEntry.from_media(tv)
        pickled = pickle.dumps(entry)
        restored = pickle.loads(pickled)  # Must not raise TypeError

        self.assertEqual(restored.item.title, "Test Show")
        self.assertEqual(restored.status, tv.status)


class TVTimeLeftCachedOrderTests(TestCase):
    """The time_left sort order cache must be consulted before list building."""

    def setUp(self):
        password = get_random_string(16)
        self.credentials = {"username": "tlcache", "password": password}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        for idx in range(1, 4):
            tv_item = Item.objects.create(
                media_id=f"tl-{idx}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Cached Sort Show {idx}",
                image="http://example.com/show.jpg",
            )
            tv = TV.objects.create(
                item=tv_item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
            )
            season_item = Item.objects.create(
                media_id=f"tl-{idx}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title=f"Cached Sort Show {idx}",
                image="http://example.com/season.jpg",
                season_number=1,
            )
            season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            episode_item = Item.objects.create(
                media_id=f"tl-{idx}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Cached Sort Show {idx}",
                image="http://example.com/e1.jpg",
                season_number=1,
                episode_number=1,
                runtime_minutes=30,
            )
            Episode.objects.create(
                item=episode_item,
                related_season=season,
                end_date=timezone.now(),
            )

    def _list_url(self, page=None):
        from django.urls import reverse

        url = reverse("medialist", args=["tv"]) + "?sort=time_left&direction=asc"
        if page:
            url += f"&page={page}"
        return url

    def test_warm_cache_skips_resort_and_keeps_order(self):
        """Page requests with a warm order cache never re-run the sort."""
        from unittest.mock import patch

        first = self.client.get(self._list_url())
        self.assertEqual(first.status_code, 200)
        first_titles = [
            entry.item.title for entry in first.context["media_list"].object_list
        ]

        with patch(
            "app.media_list_views._sort_tv_media_by_time_left",
        ) as mock_sort:
            second = self.client.get(self._list_url())
        self.assertEqual(second.status_code, 200)
        mock_sort.assert_not_called()

        second_titles = [
            entry.item.title for entry in second.context["media_list"].object_list
        ]
        self.assertEqual(first_titles, second_titles)

    def test_episode_save_invalidates_cached_order(self):
        """Episode changes clear the order cache so the next request re-sorts."""
        from unittest.mock import patch

        self.client.get(self._list_url())  # warm the cache

        season = Season.objects.filter(user=self.user).first()
        episode_item = Item.objects.filter(
            media_type=MediaTypes.EPISODE.value,
            media_id=season.item.media_id,
        ).first()
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=timezone.now(),
        )

        with patch(
            "app.media_list_views._sort_tv_media_by_time_left",
            side_effect=lambda media_list, direction: media_list,
        ) as mock_sort:
            response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, 200)
        mock_sort.assert_called_once()
