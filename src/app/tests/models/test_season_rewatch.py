from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    RewatchAlreadyCompleteError,
    Season,
    Sources,
    Status,
)

# Patch the provider lookup used by app.models.tv (imported there as `providers`).
METADATA_PATH = "app.providers.services.get_media_metadata"

SEASON_METADATA = {
    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
    "max_progress": 2,
    "image": "s.jpg",
    # Episode.save() asks for "tv_with_seasons" and reads this key.
    "season/1": {"episodes": [{"episode_number": 1}, {"episode_number": 2}]},
}


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class SeasonRewatch(TestCase):
    """Rewatching a season that has already been watched to the end."""

    def setUp(self):
        """Create a two-episode season with both episodes watched."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

        item_tv = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=item_tv,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_season = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        self.episode_items = []
        for episode_number in (1, 2):
            item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=episode_number,
            )
            self.episode_items.append(item)
            with patch(METADATA_PATH, return_value=SEASON_METADATA):
                Episode.objects.create(
                    item=item,
                    related_season=self.season,
                    end_date=datetime(2023, 6, episode_number, tzinfo=UTC),
                )

    def _set_status(self, status):
        """Set the season status without going through save() side effects."""
        Season.objects.filter(pk=self.season.pk).update(status=status)
        self.season.refresh_from_db()

    def _watch(self, episode_item, end_date):
        """Log a play of an episode."""
        return Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date=end_date,
        )

    def test_repeat_play_keeps_manual_in_progress(self, _mock_metadata):
        """A repeat play must not reset a manually reopened season to Completed."""
        self.season.start_rewatch()

        self._watch(self.episode_items[0], datetime(2026, 8, 18, tzinfo=UTC))

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_final_first_watch_still_completes(self, _mock_metadata):
        """Guard: finishing a season for the first time must still complete it."""
        self.season.episodes.filter(item=self.episode_items[1]).delete()
        self._set_status(Status.IN_PROGRESS.value)

        self._watch(self.episode_items[1], datetime(2023, 6, 2, tzinfo=UTC))

        self.assertEqual(
            Season.objects.get(pk=self.season.pk).status,
            Status.COMPLETED.value,
        )

    def test_historical_repeat_play_does_not_block_completion(self, _mock_metadata):
        """Issue #929: a fully-watched season must complete despite old repeat plays.

        Imported libraries (Trakt, SIMKL, etc.) can carry duplicate/repeat
        play history with no rewatch pass ever opened. That history alone
        must not be mistaken for a deliberate reopen.
        """
        self._watch(self.episode_items[0], datetime(2023, 6, 1, tzinfo=UTC))

        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(
            self.season.derived_status_from_episode_progress(max_progress=2),
            Status.COMPLETED.value,
        )

    def test_rewatch_resets_progress_to_the_start_of_the_season(
        self,
        _mock_metadata,
    ):
        """Starting a rewatch makes the season read as unwatched again."""
        self.season.start_rewatch()

        self.assertEqual(self.season.progress, 0)
        self.assertEqual(self.season.completed_episode_count, 0)
        self.assertEqual(self.season.next_episode_number(), 1)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_starting_an_already_open_rewatch_is_a_no_op(
        self,
        _mock_metadata,
    ):
        """A retried/duplicate start can't push an open pass's cutoff later.

        Without this guard, a retry after the user had already replayed
        an episode would overwrite rewatch_started_at with the later
        timestamp, stranding that play as pre-cutoff history and forcing
        them to replay it again.
        """
        original_start = datetime(2026, 8, 1, tzinfo=UTC)
        self.season.start_rewatch(started_at=original_start)
        self._watch(self.episode_items[0], datetime(2026, 8, 2, tzinfo=UTC))

        self.season.start_rewatch(started_at=timezone.now())

        self.season.refresh_from_db()
        self.assertEqual(self.season.rewatch_started_at, original_start)
        self.assertEqual(self.season.completed_episode_count, 1)

    def test_starting_a_rewatch_already_fully_replayed_is_rejected(
        self,
        _mock_metadata,
    ):
        """A pass backdated over plays that already cover it is refused.

        Opening it and having it immediately close itself again would be
        more confusing than just saying no — the user asked to rewatch
        something and nothing would visibly happen.
        """
        self._watch(self.episode_items[0], datetime(2026, 8, 2, tzinfo=UTC))
        self._watch(self.episode_items[1], datetime(2026, 8, 3, tzinfo=UTC))

        with self.assertRaises(RewatchAlreadyCompleteError):
            self.season.start_rewatch(started_at=datetime(2026, 8, 1, tzinfo=UTC))

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_starting_a_rewatch_partially_replayed_stays_in_progress(
        self,
        _mock_metadata,
    ):
        """A pass that doesn't yet cover every episode stays open."""
        self._watch(self.episode_items[0], datetime(2026, 8, 2, tzinfo=UTC))

        self.season.start_rewatch(started_at=datetime(2026, 8, 1, tzinfo=UTC))

        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_play_during_rewatch_advances_progress(self, _mock_metadata):
        """Only plays inside the pass count towards it."""
        self.season.start_rewatch()

        self._watch(self.episode_items[0], timezone.now())

        self.season.refresh_from_db()
        self.assertEqual(self.season.progress, 1)
        self.assertEqual(self.season.completed_episode_count, 1)
        self.assertEqual(self.season.next_episode_number(), 2)

    def test_play_without_end_date_counts_towards_the_pass(self, _mock_metadata):
        """A play logged with no date still belongs to the open pass."""
        self.season.start_rewatch()

        self._watch(self.episode_items[0], None)

        self.season.refresh_from_db()
        self.assertEqual(self.season.completed_episode_count, 1)

    def test_finishing_the_rewatch_completes_and_clears_the_pass(
        self,
        _mock_metadata,
    ):
        """The pass ends itself once every episode has been played again."""
        self.season.start_rewatch()

        for episode_item in self.episode_items:
            self._watch(episode_item, timezone.now())

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertIsNone(self.season.rewatch_started_at)

    def test_stopping_a_rewatch_restores_the_completed_status(self, _mock_metadata):
        """Abandoning a pass falls back to what the full history implies."""
        self.season.start_rewatch()

        self.season.stop_rewatch()

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_completing_a_season_mid_rewatch_logs_the_missing_plays(
        self,
        _mock_metadata,
    ):
        """Marking the season complete fills in the episodes the pass missed."""
        self.season.start_rewatch()
        self._watch(self.episode_items[0], timezone.now())

        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.assertEqual(
            self.season.episodes.filter(item=self.episode_items[1]).count(),
            2,
        )
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)

    def test_show_rewatch_starts_a_pass_on_every_season(self, _mock_metadata):
        """Rewatching a show opens a pass on each of its seasons."""
        self.tv.start_rewatch()

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
        self.assertTrue(self.tv.is_rewatching)

    def test_show_rewatch_leaves_an_already_open_season_untouched(
        self,
        _mock_metadata,
    ):
        """A retried show-level start can't push an open season's cutoff later.

        Season 2 is added fresh (never watched, never rewatched) so the
        retry still has somewhere to legitimately open a pass — proving
        season 1 is skipped specifically because it's already mid-pass,
        not because every season happened to be covered.
        """
        season_2_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=2,
        )
        season_2 = Season.objects.create(
            item=season_2_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

        original_start = datetime(2026, 8, 1, tzinfo=UTC)
        self.season.start_rewatch(started_at=original_start)
        self._watch(self.episode_items[0], datetime(2026, 8, 2, tzinfo=UTC))

        self.tv.start_rewatch(started_at=timezone.now())

        self.season.refresh_from_db()
        season_2.refresh_from_db()
        self.assertEqual(self.season.rewatch_started_at, original_start)
        self.assertIsNotNone(season_2.rewatch_started_at)

    def test_show_rewatch_already_open_on_every_season_is_rejected(
        self,
        _mock_metadata,
    ):
        """A retry once every season is already mid-pass is refused, not silent."""
        self.tv.start_rewatch(started_at=datetime(2026, 8, 1, tzinfo=UTC))

        with self.assertRaises(RewatchAlreadyCompleteError):
            self.tv.start_rewatch(started_at=timezone.now())

    def test_show_rewatch_already_fully_replayed_is_rejected(
        self,
        _mock_metadata,
    ):
        """A show whose only season would immediately re-close is refused too."""
        self._watch(self.episode_items[0], datetime(2026, 8, 2, tzinfo=UTC))
        self._watch(self.episode_items[1], datetime(2026, 8, 3, tzinfo=UTC))

        with self.assertRaises(RewatchAlreadyCompleteError):
            self.tv.start_rewatch(started_at=datetime(2026, 8, 1, tzinfo=UTC))

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_show_rewatch_skips_a_season_already_covered_but_opens_the_rest(
        self,
        _mock_metadata,
    ):
        """One already-covered season doesn't block reopening the others."""
        season_2_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=2,
        )
        # Created In Progress, then completed separately: creating it
        # Completed directly would fire the season's own "fill in the
        # episodes a completion implies" logic under the class-level
        # 2-episode metadata mock, before the 1-episode mock below is
        # active — auto-creating an episode 2 that doesn't exist here.
        season_2 = Season.objects.create(
            item=season_2_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        season_2_episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Show",
            season_number=2,
            episode_number=1,
        )
        one_episode_metadata = {
            "episodes": [{"episode_number": 1}],
            "max_progress": 1,
            "image": "s.jpg",
            "season/2": {"episodes": [{"episode_number": 1}]},
        }
        with patch(METADATA_PATH, return_value=one_episode_metadata):
            Episode.objects.create(
                item=season_2_episode_item,
                related_season=season_2,
                end_date=datetime(2023, 6, 1, tzinfo=UTC),
            )
        Season.objects.filter(pk=season_2.pk).update(status=Status.COMPLETED.value)
        season_2.refresh_from_db()

        # Season 1 gets a play on the pass date, so it's already covered from
        # there; season 2's only play predates it, so it genuinely reopens.
        self._watch(self.episode_items[0], datetime(2026, 8, 1, tzinfo=UTC))
        self._watch(self.episode_items[1], datetime(2026, 8, 1, tzinfo=UTC))

        def metadata_for_season(
            media_type,
            media_id,
            source,
            season_numbers=None,
            **_kwargs,
        ):
            if season_numbers and season_numbers[0] == 2:
                return one_episode_metadata
            return SEASON_METADATA

        with patch(METADATA_PATH, side_effect=metadata_for_season):
            skipped = self.tv.start_rewatch(started_at=datetime(2026, 8, 1, tzinfo=UTC))

        self.season.refresh_from_db()
        season_2.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertIsNotNone(season_2.rewatch_started_at)
        self.assertEqual(season_2.status, Status.IN_PROGRESS.value)
        # Reported back so a caller can tell the user season 1 was left
        # alone — succeeding silently here would hide that from them.
        self.assertEqual([s.item.season_number for s in skipped], [1])

    def test_show_is_not_rewatching_without_an_open_pass(self, _mock_metadata):
        """A show with no season in a pass is not being rewatched."""
        self.assertFalse(self.tv.is_rewatching)

    def test_show_stop_rewatch_closes_every_open_pass(self, _mock_metadata):
        """Ending a show rewatch closes the pass on each of its seasons."""
        self.tv.start_rewatch()

        self.tv.stop_rewatch()

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertFalse(self.tv.is_rewatching)

    def test_show_stop_rewatch_reconciles_the_shows_own_status(
        self,
        _mock_metadata,
    ):
        """Ending a show pass before finishing it must not strand the show.

        Each season correctly falls back to what its own history implies,
        but nothing previously re-derived the parent TV's status from that —
        a show stopped before its rewatch finished stayed In Progress
        forever, even once every season was Completed again. Each call below
        re-fetches the TV, the way the view does per request — reusing the
        setUp instance in place would hide the bug behind its own staleness
        (it predates the auto-completion that watching every episode in
        setUp triggers).
        """
        TV.objects.get(pk=self.tv.pk).start_rewatch()
        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.IN_PROGRESS.value,
        )

        ended = {**SEASON_METADATA, "details": {"status": "Ended"}}
        with patch(METADATA_PATH, return_value=ended):
            TV.objects.get(pk=self.tv.pk).stop_rewatch()

        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.COMPLETED.value,
        )

    def test_show_stop_rewatch_keeps_a_returning_series_in_progress(
        self,
        _mock_metadata,
    ):
        """Every season Completed again does not finish a show still airing (#1265)."""
        TV.objects.get(pk=self.tv.pk).start_rewatch()

        returning = {**SEASON_METADATA, "details": {"status": "Returning Series"}}
        with patch(METADATA_PATH, return_value=returning):
            TV.objects.get(pk=self.tv.pk).stop_rewatch()

        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.IN_PROGRESS.value,
        )

    def test_show_stop_rewatch_resolves_each_season_by_its_own_length(
        self,
        _mock_metadata,
    ):
        """A 3-episode season isn't judged complete by a 2-episode one's count.

        Built with bulk_create + a direct status update rather than the
        normal watch flow, so this only exercises stop_rewatch's own
        resolution — Episode.save() resolving a fully-replayed season on its
        own is covered separately, and would otherwise mask this bug too.
        """
        season_2_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=2,
        )
        season_2 = Season.objects.create(
            item=season_2_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        season_2_episode_items = [
            Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=2,
                episode_number=episode_number,
            )
            for episode_number in (1, 2, 3)
        ]
        three_episode_metadata = {
            "episodes": [{"episode_number": n} for n in (1, 2, 3)],
            "max_progress": 3,
            "image": "s.jpg",
            "season/2": {"episodes": [{"episode_number": n} for n in (1, 2, 3)]},
        }

        def metadata_for_season(
            media_type,
            media_id,
            source,
            season_numbers=None,
            **_kwargs,
        ):
            if season_numbers and season_numbers[0] == 2:
                return three_episode_metadata
            return SEASON_METADATA

        now = timezone.now()
        Season.objects.filter(pk__in=[self.season.pk, season_2.pk]).update(
            status=Status.IN_PROGRESS.value,
            rewatch_started_at=now,
        )
        # Season 1 (2 episodes): both replayed within the pass.
        Episode.objects.bulk_create(
            Episode(
                item=item,
                related_season=self.season,
                end_date=now,
                status=Status.COMPLETED.value,
            )
            for item in self.episode_items
        )
        # Season 2 (3 episodes): only 1 of 3 replayed within the pass.
        Episode.objects.bulk_create(
            [
                Episode(
                    item=season_2_episode_items[0],
                    related_season=season_2,
                    end_date=now,
                    status=Status.COMPLETED.value,
                ),
            ],
        )

        with patch(METADATA_PATH, side_effect=metadata_for_season):
            # A fresh instance, the way a real request loads one — no
            # in-memory `max_progress`, so this only passes if stop_rewatch
            # annotates it itself.
            TV.objects.get(pk=self.tv.pk).stop_rewatch()

        self.season.refresh_from_db()
        season_2.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertEqual(season_2.status, Status.IN_PROGRESS.value)

    def test_replaying_an_episode_keeps_its_rating(self, _mock_metadata):
        """A rating belongs to the episode, so a new play carries it too."""
        self.season.episodes.filter(item=self.episode_items[0]).update(score=8)
        self.season.start_rewatch()

        self._watch(self.episode_items[0], timezone.now())

        scores = list(
            self.season.episodes.filter(item=self.episode_items[0]).values_list(
                "score",
                flat=True,
            ),
        )
        self.assertEqual([str(score) for score in scores], ["8.0", "8.0"])

    def test_an_explicit_rating_on_a_play_wins(self, _mock_metadata):
        """Rating the new play directly still takes precedence."""
        self.season.episodes.filter(item=self.episode_items[0]).update(score=8)

        self.season.watch(1, timezone.now(), score=5)

        newest = (
            self.season.episodes.filter(item=self.episode_items[0])
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(str(newest.score), "5.0")

    def test_completing_mid_pass_fills_after_the_furthest_replay_only(
        self,
        _mock_metadata,
    ):
        """Skipped episodes below the furthest replay stay unlogged, as on a first watch."""
        third_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Show",
            season_number=1,
            episode_number=3,
        )
        three_episodes = {
            **SEASON_METADATA,
            "episodes": [{"episode_number": n} for n in (1, 2, 3)],
            "max_progress": 3,
            "season/1": {"episodes": [{"episode_number": n} for n in (1, 2, 3)]},
        }

        def play_counts():
            return [
                self.season.episodes.filter(item=item).count()
                for item in (*self.episode_items, third_item)
            ]

        with patch(METADATA_PATH, return_value=three_episodes):
            self._watch(third_item, datetime(2023, 6, 3, tzinfo=UTC))
            self.season.start_rewatch()
            # Replay episode 2 only, leaving episode 1 skipped in this pass.
            self._watch(self.episode_items[1], timezone.now())

            before = play_counts()
            self.season.status = Status.COMPLETED.value
            self.season.save()

        after = play_counts()
        added = [now - then for now, then in zip(after, before, strict=True)]
        # Only episode 3 — the one after the furthest replay — is filled in.
        self.assertEqual(added, [0, 0, 1])
