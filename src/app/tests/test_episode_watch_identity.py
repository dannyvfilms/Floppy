import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from api.serializers import EpisodeSerializer
from app import fork_services_episode
from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.signals import suppress_media_change_side_effects
from integrations.exports import get_track_fields


def _episode_metadata(media_type, *_args, **_kwargs):
    episodes = [
        {"episode_number": 1, "name": "One", "still_path": None},
        {"episode_number": 2, "name": "Two", "still_path": None},
    ]
    if media_type == "tv_with_seasons":
        return {"season/1": {"episodes": episodes}}
    return {
        "season_number": 1,
        "episodes": episodes,
        "_tvdb_episode_image_map": {},
    }


class EpisodeWatchIdentityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.other_user = get_user_model().objects.create_user(username="other")
        self.tv = self._create_tv(self.user, "show")
        self.season = self._create_season(self.user, self.tv, "show")
        self.other_tv = self._create_tv(self.other_user, "show")
        self.other_season = self._create_season(
            self.other_user,
            self.other_tv,
            "show",
        )
        self.metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_episode_metadata,
        )
        self.metadata_patcher.start()
        self.addCleanup(self.metadata_patcher.stop)

    @staticmethod
    def _create_tv(user, media_id):
        item, _created = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            defaults={"title": "Show"},
        )
        return TV.objects.create(item=item, user=user, status=Status.IN_PROGRESS.value)

    @staticmethod
    def _create_season(user, tv, media_id):
        item, _created = Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            defaults={"title": "Show"},
        )
        return Season.objects.create(
            item=item,
            user=user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )

    def test_legacy_no_token_repeat_behavior_is_unchanged(self):
        first = self.season.watch(1, datetime.datetime.now(datetime.UTC))
        second = self.season.watch(1, datetime.datetime.now(datetime.UTC))

        self.assertTrue(first.created)
        self.assertTrue(second.created)
        self.assertEqual(
            Episode.objects.filter(related_season=self.season).count(),
            2,
        )
        self.assertFalse(
            Episode.objects.filter(
                related_season=self.season,
                watch_operation_id__isnull=False,
            ).exists(),
        )

    def test_same_token_retry_returns_winner_without_second_side_effect(self):
        token = uuid4()
        with (
            patch("app.models.tv.cache_utils.clear_time_left_cache_for_user") as clear_time,
            patch("app.models.tv.cache_utils.clear_media_list_cache_for_user") as clear_list,
        ):
            first = self.season.watch(
                1,
                datetime.datetime.now(datetime.UTC),
                watch_operation_id=token,
            )
            first_effects = (clear_time.call_count, clear_list.call_count)
            retry = self.season.watch(
                1,
                datetime.datetime.now(datetime.UTC),
                watch_operation_id=token,
            )

        self.assertTrue(first.created)
        self.assertFalse(retry.created)
        self.assertEqual(first.episode.pk, retry.episode.pk)
        self.assertEqual(Episode.objects.filter(watch_operation_id=token).count(), 1)
        self.assertEqual(
            (clear_time.call_count, clear_list.call_count),
            first_effects,
        )

    def test_new_token_allows_intentional_rewatch(self):
        first = self.season.watch(
            1,
            datetime.datetime.now(datetime.UTC),
            watch_operation_id=uuid4(),
        )
        second = self.season.watch(
            1,
            datetime.datetime.now(datetime.UTC),
            watch_operation_id=uuid4(),
        )

        self.assertNotEqual(first.episode.pk, second.episode.pk)
        self.assertEqual(
            Episode.objects.filter(related_season=self.season).count(),
            2,
        )

    def test_token_conflicts_are_generic_across_user_and_episode(self):
        token = uuid4()
        self.season.watch(
            1,
            datetime.datetime.now(datetime.UTC),
            watch_operation_id=token,
        )

        for season, episode_number in ((self.other_season, 1), (self.season, 2)):
            with self.subTest(season=season.pk, episode_number=episode_number):
                with self.assertRaises(
                    fork_services_episode.EpisodeWatchConflictError,
                ) as raised:
                    season.watch(
                        episode_number,
                        datetime.datetime.now(datetime.UTC),
                        watch_operation_id=token,
                    )
                self.assertEqual(
                    raised.exception.code,
                    "EPISODE-WATCH-CONFLICT-001",
                )
                self.assertEqual(str(raised.exception), raised.exception.code)
                self.assertNotIn(str(token), str(raised.exception))
                self.assertNotIn(self.user.username, str(raised.exception))

    def test_malformed_token_is_rejected_without_echo(self):
        malformed = "not-a-private-token"
        with self.assertRaises(ValidationError) as raised:
            self.season.watch(
                1,
                datetime.datetime.now(datetime.UTC),
                watch_operation_id=malformed,
            )

        self.assertEqual(raised.exception.code, "invalid")
        self.assertNotIn(malformed, str(raised.exception))

    def test_field_is_private_nullable_and_excluded_from_history(self):
        result = self.season.watch(1, datetime.datetime.now(datetime.UTC))

        field = Episode._meta.get_field("watch_operation_id")
        self.assertTrue(field.null)
        self.assertTrue(field.unique)
        self.assertFalse(field.editable)
        self.assertIsNone(result.episode.watch_operation_id)
        self.assertNotIn(
            "watch_operation_id",
            {field.name for field in Episode.history.model._meta.fields},
        )
        self.assertNotIn(
            "watch_operation_id",
            EpisodeSerializer(result.episode).data,
        )
        self.assertNotIn("watch_operation_id", get_track_fields())


class EpisodeWatchIdentityConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="concurrent")
        tv_item = Item.objects.create(
            media_id="concurrent-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="concurrent-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        with patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=_episode_metadata,
        ):
            self.season.get_episode_item(1)

    @skipUnless(connection.vendor == "sqlite", "SQLite concurrency coverage")
    def test_concurrent_same_token_create_returns_one_winner_on_sqlite(self):
        token = uuid4()
        barrier = Barrier(2)

        def watch():
            close_old_connections()
            try:
                season = Season.objects.select_related("user", "item").get(
                    pk=self.season.pk,
                )
                barrier.wait()
                with suppress_media_change_side_effects():
                    return season.watch(
                        1,
                        datetime.datetime.now(datetime.UTC),
                        watch_operation_id=token,
                    )
            finally:
                close_old_connections()

        with (
            patch(
                "app.models.providers.services.get_media_metadata",
                side_effect=_episode_metadata,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _index: watch(), range(2)))

        self.assertEqual(Episode.objects.filter(watch_operation_id=token).count(), 1)
        self.assertEqual({result.episode.pk for result in results}, {results[0].episode.pk})
        self.assertEqual(sum(result.created for result in results), 1)
