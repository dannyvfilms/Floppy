from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from events.models import Event

METADATA_PATH = "app.providers.services.get_media_metadata"


class TVCompletionIdentityTests(TestCase):
    """Whole-show completion must preserve compatible imported identities."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="completion-user",
            password="x",
        )

    def _tv(self, library_media_type):
        item = Item.objects.create(
            media_id="show-812",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=library_media_type,
            title="Show",
        )
        return TV.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

    def _complete_tv(self, tv):
        tv_metadata = {
            "max_progress": 1,
            "related": {"seasons": [{"season_number": 1}]},
        }
        season_metadata = {
            "season/1": {
                "image": "season.jpg",
                "episodes": [{"episode_number": 1}],
            },
        }
        with (
            patch(METADATA_PATH, side_effect=[tv_metadata, season_metadata]),
            patch.object(Item, "fetch_releases"),
        ):
            tv.status = Status.COMPLETED.value
            tv.save()

    def _season_item(self, library_media_type):
        return Item.objects.create(
            media_id="show-812",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=library_media_type,
            season_number=1,
            title="Show Season 1",
        )

    def test_reuses_imported_tv_bucket_season_and_history(self):
        tv = self._tv(MediaTypes.TV.value)
        season_item = self._season_item(MediaTypes.TV.value)
        start_date = datetime(2025, 4, 1, tzinfo=UTC)
        end_date = datetime(2025, 4, 2, tzinfo=UTC)
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
            score=8.5,
            notes="Imported note",
        )
        episode_item = Item.objects.create(
            media_id="show-812",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.TV.value,
            season_number=1,
            episode_number=1,
            title="Episode 1",
        )
        Episode.objects.bulk_create(
            [
                Episode(
                    item=episode_item,
                    related_season=season,
                    end_date=end_date,
                ),
            ],
        )
        episode = Episode.objects.get(related_season=season, item=episode_item)
        season_start_date = season.start_date
        season_end_date = season.end_date
        item_count = Item.objects.count()
        season_history_count = season.history.count()

        self._complete_tv(tv)

        season.refresh_from_db()
        episode.refresh_from_db()
        self.assertEqual(season.item_id, season_item.id)
        self.assertEqual(season.status, Status.COMPLETED.value)
        self.assertEqual(season.score, 8.5)
        self.assertEqual(season.notes, "Imported note")
        self.assertEqual(season.start_date, season_start_date)
        self.assertEqual(season.end_date, season_end_date)
        self.assertEqual(episode.end_date, end_date)
        self.assertGreaterEqual(season.history.count(), season_history_count)
        self.assertEqual(Item.objects.count(), item_count)
        self.assertEqual(Season.objects.filter(related_tv=tv).count(), 1)
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 1)

    def test_normal_tv_does_not_reuse_anime_season(self):
        tv = self._tv(MediaTypes.TV.value)
        anime_tv = self._tv(MediaTypes.ANIME.value)
        anime_season = Season.objects.create(
            item=self._season_item(MediaTypes.ANIME.value),
            user=self.user,
            related_tv=anime_tv,
            status=Status.PLANNING.value,
        )

        self._complete_tv(tv)

        normal_season = Season.objects.get(related_tv=tv)
        self.assertEqual(normal_season.item.library_media_type, MediaTypes.SEASON.value)
        self.assertEqual(anime_season.item.library_media_type, MediaTypes.ANIME.value)
        self.assertEqual(Season.objects.filter(related_tv=anime_tv).count(), 1)

    def test_anime_does_not_reuse_normal_tv_season(self):
        tv = self._tv(MediaTypes.ANIME.value)
        normal_tv = self._tv(MediaTypes.TV.value)
        normal_season = Season.objects.create(
            item=self._season_item(MediaTypes.TV.value),
            user=self.user,
            related_tv=normal_tv,
            status=Status.PLANNING.value,
        )

        self._complete_tv(tv)

        anime_season = Season.objects.get(related_tv=tv)
        self.assertEqual(anime_season.item.library_media_type, MediaTypes.ANIME.value)
        self.assertEqual(normal_season.item.library_media_type, MediaTypes.TV.value)
        self.assertEqual(Season.objects.filter(related_tv=normal_tv).count(), 1)

    def test_missing_target_item_converges_when_creation_is_interleaved(self):
        tv = self._tv(MediaTypes.TV.value)
        original_title_fields = Item.title_fields_from_metadata
        inserted = False

        def insert_conflicting_item(metadata, fallback_title=""):
            nonlocal inserted
            if not inserted:
                inserted = True
                Item.objects.create(
                    media_id="show-812",
                    source=Sources.TVDB.value,
                    media_type=MediaTypes.SEASON.value,
                    library_media_type=MediaTypes.SEASON.value,
                    season_number=1,
                    title="Raced season",
                )
            return original_title_fields(metadata, fallback_title=fallback_title)

        with (
            patch(
                METADATA_PATH,
                side_effect=[
                    {
                        "max_progress": 1,
                        "related": {"seasons": [{"season_number": 1}]},
                    },
                    {
                        "season/1": {
                            "episodes": [{"episode_number": 1}],
                        },
                    },
                ],
            ),
            patch.object(Item, "fetch_releases"),
            patch.object(
                Item,
                "title_fields_from_metadata",
                side_effect=insert_conflicting_item,
            ),
        ):
            tv.status = Status.COMPLETED.value
            tv.save()

        self.assertEqual(
            Item.objects.filter(
                media_id="show-812",
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ).count(),
            1,
        )
        self.assertEqual(Season.objects.filter(related_tv=tv).count(), 1)


class SeasonCompletionEvidenceTests(TestCase):
    """Season completion must use distinct episode evidence."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="evidence-user",
            password="x",
        )
        tv_item = Item.objects.create(
            media_id="evidence-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Evidence Show",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        season_item = Item.objects.create(
            media_id="evidence-show",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
            title="Evidence Show Season 1",
            local_season_episode_count=10,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

    def _record_episodes(self, episode_numbers, status=Status.COMPLETED.value):
        items = {
            number: Item.objects.create(
                media_id="evidence-show",
                source=Sources.TVDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=number,
                title=f"Episode {number}",
            )
            for number in set(episode_numbers)
        }
        Episode.objects.bulk_create(
            [
                Episode(
                    item=items[number],
                    related_season=self.season,
                    status=status,
                    dropped=status == Status.DROPPED.value,
                    end_date=timezone.now(),
                )
                for number in episode_numbers
            ],
        )

    def _add_release_events(self):
        now = timezone.now()
        Event.objects.bulk_create(
            [
                Event(
                    item=self.season.item,
                    content_number=number,
                    datetime=now - timedelta(days=number),
                )
                for number in range(1, 11)
            ],
        )

    def _sync_status(self):
        self.season.refresh_from_db()
        self.season._sync_status_after_episode_change()
        self.season.refresh_from_db()
        return self.season.status

    def test_late_episode_with_release_events_stays_in_progress(self):
        self._add_release_events()
        self._record_episodes([10])
        Season.objects.filter(pk=self.season.pk).update(status=Status.COMPLETED.value)

        self.assertEqual(self._sync_status(), Status.IN_PROGRESS.value)

    def test_late_episode_with_local_count_stays_in_progress(self):
        self._record_episodes([10])
        Season.objects.filter(pk=self.season.pk).update(status=Status.COMPLETED.value)

        self.assertEqual(self._sync_status(), Status.IN_PROGRESS.value)

    def test_all_distinct_local_episodes_complete_the_season(self):
        self._record_episodes(range(1, 11))

        self.assertEqual(self._sync_status(), Status.COMPLETED.value)

    def test_repeated_plays_do_not_inflate_completion_count(self):
        self._record_episodes([1, 2, 3, 4, 5, 6, 7, 8, 10, 10])

        self.assertEqual(self.season.completed_episode_count, 9)
        self.assertEqual(self._sync_status(), Status.IN_PROGRESS.value)

    def test_dropped_episode_does_not_count_as_completed(self):
        self._record_episodes(range(1, 10))
        self._record_episodes([10], status=Status.DROPPED.value)

        self.assertEqual(self.season.completed_episode_count, 9)
        self.assertEqual(self._sync_status(), Status.IN_PROGRESS.value)

    def test_manual_in_progress_rewatch_stays_in_progress(self):
        self._record_episodes(range(1, 11))
        Season.objects.filter(pk=self.season.pk).update(status=Status.IN_PROGRESS.value)

        self.assertEqual(self._sync_status(), Status.IN_PROGRESS.value)
