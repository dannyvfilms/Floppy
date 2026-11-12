"""A play may use the stored episode count, but only to say "not finished yet".

`Episode.save` used to read the provider's season payload on every play just to
count its episodes. It now reads `Item.provider_episode_count` first. That
number is refreshed when a payload is fetched, so it can be older than the
payload cache ever was. These tests hold the rule that makes that safe: every
status a play produces is the status the payload alone would have produced.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.providers import services

METADATA_PATH = "app.providers.services.get_media_metadata"
STORED_COUNT_PATH = "app.models.tv.Episode._stored_season_episode_count"
START = datetime(2025, 3, 1, tzinfo=UTC)


class FakeProvider:
    """Stand in for `get_media_metadata` with a season size that can change."""

    def __init__(self, season_sizes, *, fail=False):
        """Hold the season sizes to report and whether every call fails."""
        self.season_sizes = dict(season_sizes)
        self.fail = fail
        self.season_reads = 0

    def _season(self, media_id, source, number):
        size = self.season_sizes[number]
        return {
            "media_id": media_id,
            "source": source,
            "media_type": MediaTypes.SEASON.value,
            "title": "Show",
            "season_title": f"Season {number}",
            "season_number": number,
            "image": "season.jpg",
            "max_progress": size,
            "details": {"episodes": size},
            "episodes": [
                {"episode_number": index, "air_date": "2020-01-01", "runtime": 30}
                for index in range(1, size + 1)
            ],
        }

    def __call__(self, media_type, media_id, source, season_numbers=None, *_, **__):
        if media_type == "tv_with_seasons":
            self.season_reads += 1
        if self.fail:
            raise services.ProviderAPIError(source, error=ValueError("down"))
        main = [number for number in self.season_sizes if number > 0]
        payload = {
            "media_id": media_id,
            "source": source,
            "media_type": MediaTypes.TV.value,
            "title": "Show",
            "image": "show.jpg",
            "max_progress": sum(self.season_sizes[number] for number in main),
            "details": {
                "status": "Returning Series",
                "seasons": len(main),
                "episodes": sum(self.season_sizes[number] for number in main),
            },
            "related": {
                "seasons": [
                    {"season_number": number, "image": "season.jpg"}
                    for number in sorted(self.season_sizes)
                ],
            },
        }
        for number in season_numbers or []:
            payload[f"season/{number}"] = self._season(media_id, source, number)
        if media_type == MediaTypes.SEASON.value:
            return payload[f"season/{season_numbers[0]}"]
        return payload


class StoredEpisodeCountTestCase(TestCase):
    """Build one tracked season and replay plays against a fake provider."""

    media_id = "4100"
    source = Sources.TMDB.value
    library_media_type = MediaTypes.TV.value

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="stored-count",
            password="x",
        )
        self.enterContext(patch.object(Item, "fetch_releases"))

    def _item(self, media_type, **extra):
        return Item.objects.create(
            media_id=self.media_id,
            source=self.source,
            media_type=media_type,
            library_media_type=self.library_media_type,
            title="Show",
            image="show.jpg",
            **extra,
        )

    def build(self, *, season_number=1, stored_count=None, season_status=None):
        tv, _ = TV.objects.get_or_create(
            item=Item.objects.filter(
                media_id=self.media_id,
                source=self.source,
                media_type=MediaTypes.TV.value,
            ).first()
            or self._item(MediaTypes.TV.value),
            user=self.user,
            defaults={"status": Status.PLANNING.value},
        )
        season_item = self._item(
            MediaTypes.SEASON.value,
            season_number=season_number,
            provider_episode_count=stored_count,
        )
        with patch(METADATA_PATH, FakeProvider({season_number: 1})):
            season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=season_status or Status.PLANNING.value,
            )
        return season

    def play(self, season, episode_number, *, when=None):
        item, _ = Item.objects.get_or_create(
            media_id=self.media_id,
            source=self.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=season.item.season_number,
            episode_number=episode_number,
            defaults={
                "title": "Show",
                "image": "episode.jpg",
                "library_media_type": self.library_media_type,
            },
        )
        return Episode.objects.create(
            item=item,
            related_season=Season.objects.select_related("item").get(pk=season.pk),
            end_date=when or START + timedelta(days=Episode.objects.count()),
        )

    def state(self, season):
        season = Season.objects.select_related("related_tv").get(pk=season.pk)
        return (
            season.status,
            season.related_tv.status,
            season.rewatch_started_at is None,
        )

    def run_sequence(self, season, plays, provider, *, grow=None):
        """Play `plays` in order; return the state after each one.

        `grow` maps a play index to new season sizes, applied before that play:
        the provider lists more episodes from then on.
        """
        states = []
        reads = []
        with patch(METADATA_PATH, provider):
            for index, episode_number in enumerate(plays):
                if grow and index in grow:
                    provider.season_sizes.update(grow[index])
                before = provider.season_reads
                self.play(season, episode_number)
                reads.append(provider.season_reads - before)
                states.append(self.state(season))
        return states, reads

    def assert_same_as_payload_only(
        self,
        *,
        sizes,
        plays,
        stored_count,
        season_number=1,
        grow=None,
        season_status=None,
        prepare=None,
    ):
        """Compare the stored-count path with the payload-only path it replaced.

        The shadow run disables the stored count, which is the base behaviour.
        Both runs start from identical rows in separate users' libraries.
        """
        runs = {}
        for label in ("payload_only", "stored"):
            self.user = get_user_model().objects.create_user(
                username=f"{label}-{get_user_model().objects.count()}",
                password="x",
            )
            Item.objects.filter(media_id=self.media_id).exclude(
                media_type=MediaTypes.EPISODE.value,
            ).delete()
            season = self.build(
                season_number=season_number,
                stored_count=stored_count,
                season_status=season_status,
            )
            if prepare:
                prepare(season)
            provider = FakeProvider(sizes)
            if label == "payload_only":
                with patch(STORED_COUNT_PATH, return_value=None):
                    runs[label] = self.run_sequence(season, plays, provider, grow=grow)
            else:
                runs[label] = self.run_sequence(season, plays, provider, grow=grow)

        self.assertEqual(runs["stored"][0], runs["payload_only"][0])
        return runs["stored"]


class StatusSequenceIdentityTests(StoredEpisodeCountTestCase):
    """Gate 2: per category, the stored count changes no status."""

    def test_normal_season(self):
        states, reads = self.assert_same_as_payload_only(
            sizes={1: 4},
            plays=[1, 2, 3, 4],
            stored_count=4,
        )

        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertEqual([state[0] for state in states[:3]], [Status.IN_PROGRESS.value] * 3)
        # Only the play that could finish the season asks the provider.
        self.assertEqual(reads, [0, 0, 0, 1])

    def test_specials_season(self):
        states, reads = self.assert_same_as_payload_only(
            sizes={0: 3, 1: 2},
            plays=[1, 2, 3],
            stored_count=3,
            season_number=0,
        )

        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertEqual(reads, [0, 0, 1])

    def test_airing_season_with_a_count_stored_before_new_episodes(self):
        """The trap: two episodes were listed when the count was stored."""
        states, reads = self.assert_same_as_payload_only(
            sizes={1: 2},
            plays=[1, 2, 3, 4],
            stored_count=2,
            grow={1: {1: 4}},
        )

        self.assertEqual(
            [state[0] for state in states],
            [Status.IN_PROGRESS.value] * 3 + [Status.COMPLETED.value],
        )
        # Play 2 reaches the stale count, so it asks, learns of four episodes
        # and stores that; play 3 is below four again.
        self.assertEqual(reads, [0, 1, 0, 1])

    def test_caught_up_weekly_viewer(self):
        """Each new episode completes the season again, as it does today."""
        states, _ = self.assert_same_as_payload_only(
            sizes={1: 1},
            plays=[1, 2, 3],
            stored_count=1,
            grow={1: {1: 2}, 2: {1: 3}},
        )

        self.assertEqual([state[0] for state in states], [Status.COMPLETED.value] * 3)

    def test_placeholder_season_stored_as_zero(self):
        states, reads = self.assert_same_as_payload_only(
            sizes={1: 3},
            plays=[1, 2, 3],
            stored_count=0,
        )

        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertEqual(reads, [1, 0, 1])

    def test_no_stored_count(self):
        _, reads = self.assert_same_as_payload_only(
            sizes={1: 3},
            plays=[1, 2, 3],
            stored_count=None,
        )

        # The first play has the payload in hand and stores its count.
        self.assertEqual(reads, [1, 0, 1])

    def test_out_of_order_and_repeat_plays(self):
        states, _ = self.assert_same_as_payload_only(
            sizes={1: 4},
            plays=[3, 1, 1, 4, 3, 2],
            stored_count=4,
        )

        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertNotIn(Status.COMPLETED.value, [state[0] for state in states[:-1]])

    def test_paused_season_resumes(self):
        self.assert_same_as_payload_only(
            sizes={1: 3},
            plays=[1, 2, 3],
            stored_count=3,
            season_status=Status.PAUSED.value,
        )

    def test_dropped_season_stays_dropped(self):
        states, _ = self.assert_same_as_payload_only(
            sizes={1: 2},
            plays=[1, 2],
            stored_count=2,
            season_status=Status.DROPPED.value,
        )

        self.assertEqual([state[0] for state in states], [Status.DROPPED.value] * 2)

    def test_rewatch_pass(self):
        def finish_then_rewatch(season):
            with patch(METADATA_PATH, FakeProvider({1: 3})):
                for number in (1, 2, 3):
                    self.play(season, number, when=START - timedelta(days=30 - number))
                Season.objects.get(pk=season.pk).start_rewatch(
                    started_at=START - timedelta(days=1),
                    max_progress=3,
                )

        states, reads = self.assert_same_as_payload_only(
            sizes={1: 3},
            plays=[1, 2, 3],
            stored_count=3,
            prepare=finish_then_rewatch,
        )

        # The pass stays open until its last episode, then closes.
        self.assertEqual([state[2] for state in states], [False, False, True])
        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertEqual(reads, [0, 0, 1])


class GroupedAnimeSequenceTests(StatusSequenceIdentityTests):
    """The same sequences for a TVDB show kept in the anime library."""

    media_id = "81797"
    source = Sources.TVDB.value
    library_media_type = MediaTypes.ANIME.value


class StoredCountBoundaryTests(StoredEpisodeCountTestCase):
    """What the stored count may and may not decide."""

    def test_custom_order_always_uses_the_order_payload(self):
        self.media_id = "order_7"
        season = self.build(stored_count=3)
        provider = FakeProvider({1: 3})

        _, reads = self.run_sequence(season, [1, 2, 3], provider)

        self.assertEqual(reads, [1, 1, 1])
        self.assertEqual(self.state(season)[0], Status.COMPLETED.value)
        season.item.refresh_from_db()
        self.assertEqual(season.item.provider_episode_count, 3)

    def test_custom_order_count_is_not_stored_from_a_play(self):
        self.media_id = "order_8"
        season = self.build(stored_count=None)

        self.run_sequence(season, [1], FakeProvider({1: 3}))

        season.item.refresh_from_db()
        self.assertIsNone(season.item.provider_episode_count)

    def test_rating_only_row_reads_nothing(self):
        season = self.build(stored_count=3)
        item = self._item(
            MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
        )
        provider = FakeProvider({1: 3})

        with patch(METADATA_PATH, provider):
            Episode.objects.create(
                item=item,
                related_season=season,
                rating_only=True,
                score=7,
            )

        self.assertEqual(provider.season_reads, 0)
        self.assertEqual(self.state(season)[0], Status.PLANNING.value)

    def test_play_saves_without_the_provider(self):
        """Below the stored count, a provider outage no longer matters."""
        season = self.build(stored_count=4)
        provider = FakeProvider({1: 4}, fail=True)

        states, reads = self.run_sequence(season, [1, 2, 3], provider)

        self.assertEqual(reads, [0, 0, 0])
        self.assertEqual(provider.season_reads, 0)
        self.assertEqual(
            states,
            [(Status.IN_PROGRESS.value, Status.IN_PROGRESS.value, True)] * 3,
        )
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 3)

    def test_finishing_play_does_not_complete_on_the_stored_count_alone(self):
        """With the provider down, the stored count must not finish a season."""
        season = self.build(stored_count=2)
        provider = FakeProvider({1: 2}, fail=True)

        with self.assertLogs("app.models.tv", level="WARNING") as logs:
            states, reads = self.run_sequence(season, [1, 2], provider)

        self.assertEqual(reads, [0, 1])
        self.assertEqual(states[-1][0], Status.IN_PROGRESS.value)
        self.assertIn("Skipping Episode status sync", logs.output[0])

    def test_local_count_fallback_still_applies(self):
        season = self.build(stored_count=None)
        Item.objects.filter(pk=season.item_id).update(local_season_episode_count=2)
        provider = FakeProvider({1: 2}, fail=True)

        with self.assertLogs("app.models.tv", level="INFO") as logs:
            states, _ = self.run_sequence(season, [1, 2], provider)

        self.assertEqual(states[-1][0], Status.COMPLETED.value)
        self.assertTrue(
            any("Using locally recorded episode count" in line for line in logs.output),
        )
        season.item.refresh_from_db()
        self.assertIsNone(season.item.provider_episode_count)

    def test_count_stored_too_high_leaves_the_season_open(self):
        """The accepted difference: the provider removed episodes since.

        The payload alone would complete the season on the fourth play. The
        stored count says six, so the season stays in progress (later than
        before, never earlier) until a payload fetch lowers the count.
        """
        season = self.build(stored_count=6)
        provider = FakeProvider({1: 4})

        states, reads = self.run_sequence(season, [1, 2, 3, 4], provider)

        self.assertEqual(reads, [0, 0, 0, 0])
        self.assertEqual(states[-1][0], Status.IN_PROGRESS.value)

    def test_stale_count_in_memory_cannot_complete_early(self):
        """A season item loaded before a fetch raised the count is still safe."""
        season = self.build(stored_count=2)
        stale = Season.objects.select_related("item").get(pk=season.pk)
        Item.objects.filter(pk=season.item_id).update(provider_episode_count=4)
        provider = FakeProvider({1: 4})
        items = [
            self._item(MediaTypes.EPISODE.value, season_number=1, episode_number=number)
            for number in (1, 2)
        ]

        with patch(METADATA_PATH, provider):
            for item in items:
                Episode.objects.create(item=item, related_season=stale, end_date=START)
                stale.item.provider_episode_count = 2

        self.assertEqual(self.state(season)[0], Status.IN_PROGRESS.value)


class PlayCostTests(StoredEpisodeCountTestCase):
    """The stored count removes work from a play; it adds none."""

    def _statements(self, *, stored_count, loaded):
        self.user = get_user_model().objects.create_user(
            username=f"cost-{get_user_model().objects.count()}",
            password="x",
        )
        Item.objects.filter(media_id=self.media_id).delete()
        season = self.build(stored_count=stored_count)
        provider = FakeProvider({1: 4})
        with patch(METADATA_PATH, provider):
            self.play(season, 1)
            item = self._item(
                MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=2,
            )
            related = Season.objects.get(pk=season.pk)
            if loaded:
                related = Season.objects.select_related("item").get(pk=season.pk)
            before = provider.season_reads
            with CaptureQueriesContext(connection) as queries:
                Episode.objects.create(item=item, related_season=related, end_date=START)
        return len(queries), provider.season_reads - before

    def test_loaded_season_item_adds_no_statement(self):
        with patch(STORED_COUNT_PATH, return_value=None):
            base_statements, base_reads = self._statements(stored_count=4, loaded=True)
        statements, reads = self._statements(stored_count=4, loaded=True)

        self.assertEqual((base_reads, reads), (1, 0))
        self.assertLessEqual(statements, base_statements)

    def test_unloaded_season_item_costs_one_narrow_read(self):
        with patch(STORED_COUNT_PATH, return_value=None):
            base_statements, _ = self._statements(stored_count=4, loaded=False)
        statements, reads = self._statements(stored_count=4, loaded=False)

        self.assertEqual(reads, 0)
        self.assertLessEqual(statements, base_statements + 1)
