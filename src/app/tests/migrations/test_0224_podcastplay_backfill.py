import datetime
import importlib

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Podcast, PodcastPlay, Sources, Status

migration_0224 = importlib.import_module("app.migrations.0224_podcastplay")

UTC = datetime.UTC


class PodcastPlayBackfillTests(TestCase):
    """History records that share an end date are one listen."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="bf", password="x")

    def _tracker(self, media_id, **fields):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title=media_id,
            image="https://example.com/i.jpg",
        )
        return Podcast.objects.create(item=item, user=self.user, **fields)

    def test_edits_of_one_listen_collapse_and_repeats_stay_separate(self):
        podcast = self._tracker(
            "ep-1",
            status=Status.COMPLETED.value,
            progress=30,
            end_date=datetime.datetime(2024, 1, 1, 10, tzinfo=UTC),
        )
        # The old edit path: every save added a history record.
        podcast.start_date = datetime.datetime(2024, 1, 1, 9, tzinfo=UTC)
        podcast.save()
        podcast.notes = "edited"
        podcast.save()
        podcast.end_date = datetime.datetime(2024, 2, 1, 10, tzinfo=UTC)
        podcast.save()
        PodcastPlay.objects.all().delete()

        migration_0224.backfill_plays(apps, None)

        plays = list(PodcastPlay.objects.order_by("end_date"))
        self.assertEqual([p.end_date.month for p in plays], [1, 2])
        self.assertEqual(plays[0].start_date.hour, 9)
        self.assertTrue(all(p.status == Status.COMPLETED.value for p in plays))

    def test_tracker_without_history_gets_a_play_from_its_own_row(self):
        done = self._tracker(
            "ep-2",
            status=Status.COMPLETED.value,
            end_date=datetime.datetime(2024, 3, 1, 10, tzinfo=UTC),
        )
        open_ = self._tracker("ep-3", status=Status.IN_PROGRESS.value, progress=4)
        planning = self._tracker("ep-4", status=Status.PLANNING.value)
        PodcastPlay.objects.all().delete()
        apps.get_model("app", "HistoricalPodcast").objects.all().delete()

        migration_0224.backfill_plays(apps, None)

        self.assertEqual(done.plays.get().status, Status.COMPLETED.value)
        self.assertEqual(open_.plays.get().status, Status.IN_PROGRESS.value)
        self.assertEqual(open_.plays.get().progress, 4)
        self.assertFalse(planning.plays.exists())

    def test_running_it_twice_adds_nothing(self):
        self._tracker(
            "ep-5",
            status=Status.COMPLETED.value,
            end_date=datetime.datetime(2024, 3, 1, 10, tzinfo=UTC),
        )
        PodcastPlay.objects.all().delete()

        migration_0224.backfill_plays(apps, None)
        migration_0224.backfill_plays(apps, None)

        self.assertEqual(PodcastPlay.objects.count(), 1)
