"""Occurrence history, rather than tracking mutations, drives inferred progress."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.translation import override

from app.models import TV, Episode, Item, RewatchCancellation, Season, Status
from app.providers import services
from app.services.episode_ordering import persist_order
from app.services.progress_breakdown import build_progress_breakdown
from app.services.rewatch_progress import cancel_run
from app.tests.test_progress_breakdown import _catalogue, _episode


class InferredRewatchTests(TestCase):
    """Keep inference deterministic across imports, edits, and cancellations."""

    def setUp(self):
        """Install an offline catalogue and a completed, privately owned show."""
        self.user = get_user_model().objects.create_user(username="rewatch")
        self.catalogue = {}
        self.metadata_reader = services.get_media_metadata
        provider = patch(
            "app.providers.services.get_media_metadata",
            side_effect=self.metadata,
        )
        provider.start()
        self.addCleanup(provider.stop)
        self.item = Item.objects.create(
            media_id="62565", source="tmdb", media_type="tv",
            title="Food Wars! Shokugeki no Soma",
        )
        self.tv = TV.objects.create(item=self.item, user=self.user, status=Status.PLANNING.value)
        self.seasons = {}
        self.items = {}
        self.start = datetime(2025, 7, 21, 19, 49, tzinfo=UTC)
        self.step = 0
        self.client.force_login(self.user)

    def metadata(self, *args, **kwargs):
        """Read the current test catalogue after each fixture change."""
        return _catalogue(**self.catalogue)(*args, **kwargs)

    def seed(self, layout=(5, 5, 5)):
        """Seed first-watch facts without invoking completion fan-out."""
        plays = []
        for number, count in enumerate(layout, 1):
            self.catalogue[f"s{number}"] = [_episode(ep) for ep in range(1, count + 1)]
            item = Item.objects.create(
                media_id=self.item.media_id, source="tmdb", media_type="season",
                title=self.item.title, season_number=number,
            )
            self.seasons[number] = Season.objects.create(
                item=item, related_tv=self.tv, user=self.user, status=Status.PLANNING.value,
            )
            for episode in range(1, count + 1):
                self.items[number, episode] = Item.objects.create(
                    media_id=self.item.media_id, source="tmdb", media_type="episode",
                    title=self.item.title, season_number=number, episode_number=episode,
                )
                plays.append(Episode(
                    item=self.items[number, episode], related_season=self.seasons[number],
                    end_date=datetime(2021, 1, 1, tzinfo=UTC),
                ))
        Episode.objects.bulk_create(plays)
        Season.objects.filter(related_tv=self.tv).update(status=Status.COMPLETED.value)
        TV.objects.filter(pk=self.tv.pk).update(status=Status.COMPLETED.value)
        self.tv.refresh_from_db()
        self.tv.max_progress = sum(layout)

    def play(self, season, episode, *, at=None, **extra):
        """Import a play; occurrence time is independent of row creation order."""
        row = Episode(
            item=self.items[season, episode], related_season=self.seasons[season],
            end_date=at or self.start + timedelta(minutes=self.step), **extra,
        )
        self.step += 1
        Episode.objects.bulk_create([row])
        return row

    def progress(self, season=None):
        """Resolve either surface against the same tracking history."""
        return build_progress_breakdown(**({"season": self.seasons[season]} if season else {"tv": self.tv}))

    def cancel(self, breakdown=None):
        """Use the real private, CSRF-protected application action."""
        breakdown = breakdown or self.progress()
        return self.client.post(reverse("cancel_progress_rewatch"), {
            "media_type": "tv", "instance_id": self.tv.pk, "run_key": breakdown.run_key,
        })

    def test_food_wars_history_and_card_agree_without_changing_status(self):
        self.seed((24, 13, 24, 12, 13))
        for episode in range(1, 14):
            self.play(5, episode, at=datetime(2022, 9, 1, tzinfo=UTC))
        for episode in range(1, 25):
            self.play(1, episode)
            if episode == 2:
                self.play(1, 2)
        self.play(2, 1)
        result = self.progress()
        self.assertEqual((result.watched, result.total, result.percent), (86, 86, 100))
        self.assertEqual((result.rewatch_watched, result.rewatch_percent), (25, 29))
        self.assertEqual(result.seasons[0].rewatch_percent, 100)
        self.assertEqual(result.seasons[1].rewatch_percent, 8)
        self.assertEqual(self.progress(1).rewatch_percent, 100)
        html = render_to_string("app/components/detail_progress_card_slot.html", {
            "current_instance": self.tv, "media": self.item, "media_type": "tv",
        })
        self.assertIn("rewatch: 29,", html)
        self.assertIn("percent: 100,", html)
        self.assertIn("Cancel rewatch", html)
        self.assertEqual(TV.objects.get(pk=self.tv.pk).status, Status.COMPLETED.value)
        self.assertFalse(Season.objects.filter(related_tv=self.tv, rewatch_started_at__isnull=False).exists())

    def test_prefix_fills_gaps_and_ignores_duplicates(self):
        self.seed()
        for episode in (1, 1, 2, 2, 5):
            self.play(1, episode)
        self.assertEqual(self.progress().rewatch_watched, 2)
        self.play(1, 3)
        self.play(1, 4)
        self.assertEqual(self.progress().rewatch_watched, 5)

    def test_isolated_and_scattered_repeats_do_not_establish_a_run(self):
        self.seed()
        for season, episode in ((1, 1), (2, 4), (3, 5), (1, 3)):
            self.play(season, episode)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_season_glow_is_offset_and_label_uses_season_denominator(self):
        self.seed((24, 13, 24, 12, 13))
        self.play(3, 1)
        self.play(3, 2)
        result = self.progress()
        self.assertEqual((result.rewatch_watched, result.rewatch_total, result.rewatch_percent), (2, 24, 8))
        self.assertAlmostEqual(result.rewatch_offset, 37 / 86 * 100, places=4)
        self.assertAlmostEqual(result.rewatch_width, 2 / 86 * 100, places=4)
        self.assertIn("Season 3 rewatch", result.rewatch_label)
        self.assertEqual(self.progress(3).rewatch_offset, 0)
        with override("de"):
            html = render_to_string("app/components/detail_progress_card_slot.html", {
                "current_instance": self.tv, "media": self.item, "media_type": "tv",
            })
        self.assertIn("offset: 43.0233, width: 2.3256,", html)

    def test_cancellation_suppresses_extensions_but_allows_a_separate_season(self):
        self.seed()
        for episode in range(1, 6):
            self.play(1, episode)
        self.play(2, 1)
        response = self.cancel()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RewatchCancellation.objects.get().evidence[0]["season"], 1)
        self.play(2, 2)
        self.assertIsNone(self.progress().rewatch_percent)
        self.play(3, 1)
        self.play(3, 2)
        self.assertEqual((self.progress().rewatch_season, self.progress().rewatch_watched), (3, 2))
        self.play(2, 3)
        self.assertEqual(self.progress().rewatch_season, 3)

    def test_natural_season_boundary_is_still_a_cancelled_continuation(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        self.cancel()
        for episode in (3, 4, 5):
            self.play(1, episode)
        self.play(2, 1)
        self.play(2, 2)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_fresh_restart_replaces_cancelled_run(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        self.cancel()
        self.play(1, 1)
        self.assertIsNone(self.progress().rewatch_percent)
        self.play(1, 2)
        self.assertEqual(self.progress().rewatch_watched, 2)

    def test_stale_cancellation_does_not_cancel_newer_run(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        old = self.progress()
        self.play(3, 1)
        self.play(3, 2)
        self.cancel(old)
        self.assertFalse(RewatchCancellation.objects.exists())
        self.assertEqual(self.progress().rewatch_season, 3)

    def test_old_unconfirmed_shuffle_cannot_supersede_a_newer_restart(self):
        self.seed()
        self.play(3, 1, at=datetime(2022, 1, 1, tzinfo=UTC))
        self.play(1, 1)
        self.play(1, 2)
        self.play(3, 2)
        result = self.progress()
        self.assertIsNone(result.rewatch_season)
        self.assertEqual(result.rewatch_watched, 2)

    def test_complete_latest_run_hides_instead_of_falling_back(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        for episode in range(1, 6):
            self.play(3, episode)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_occurrence_order_and_tied_import_batches(self):
        self.seed()
        self.play(1, 2, at=self.start)
        self.play(1, 1, at=self.start)
        self.assertEqual(self.progress().rewatch_watched, 2)
        Episode.objects.filter(end_date=self.start).update(end_date=None)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_deleted_or_edited_evidence_changes_progress(self):
        self.seed()
        self.play(1, 1)
        second = self.play(1, 2)
        self.assertEqual(self.progress().rewatch_watched, 2)
        Episode.objects.filter(pk=second.pk).update(status=Status.DROPPED.value)
        self.assertIsNone(self.progress().rewatch_percent)
        second.delete()
        self.assertIsNone(self.progress().rewatch_percent)

    def test_duplicate_backfill_does_not_resurrect_cancelled_run(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        cancel_run(self.tv, self.progress().rewatch_run)
        self.play(1, 1, at=self.start - timedelta(minutes=1))
        self.play(1, 3)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_catalogue_growth_does_not_resurrect_cancelled_evidence(self):
        self.seed((5, 5))
        self.play(1, 1)
        self.play(1, 2)
        self.cancel()
        self.catalogue["s3"] = [_episode(1), _episode(2)]
        self.assertIsNone(self.progress().rewatch_percent)

    def test_explicit_pass_wins_and_ending_it_suppresses_inference(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        Season.objects.filter(pk=self.seasons[1].pk).update(rewatch_started_at=self.start)
        self.assertTrue(self.progress().rewatch_run.explicit)
        response = self.client.post(reverse("media_rewatch"), {
            "media_type": "tv", "instance_id": self.tv.pk, "action": "stop",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_ending_explicit_pass_before_confirmation_suppresses_later_extension(self):
        self.seed()
        self.play(1, 1)
        Season.objects.filter(pk=self.seasons[1].pk).update(rewatch_started_at=self.start)
        self.client.post(reverse("media_rewatch"), {
            "media_type": "tv", "instance_id": self.tv.pk, "action": "stop",
        })
        self.play(1, 2)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_single_episode_scope_requires_explicit_controls(self):
        self.seed((1,))
        self.play(1, 1)
        self.play(1, 1)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_complete_show_hides_rewatch_and_incomplete_first_watch_cannot_restart(self):
        self.seed((3, 3))
        for season in (1, 2):
            for episode in (1, 2, 3):
                self.play(season, episode)
        self.assertIsNone(self.progress().rewatch_percent)
        Episode.objects.filter(item=self.items[1, 3]).delete()
        self.play(1, 1)
        self.play(1, 2)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_rating_only_and_archived_rows_are_not_replay_evidence(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2, rating_only=True)
        self.assertIsNone(self.progress().rewatch_percent)
        self.play(2, 1)
        self.play(2, 2)
        Season.objects.filter(pk=self.seasons[2].pk).update(order_archived=True)
        self.assertIsNone(self.progress().rewatch_percent)

    def test_cancellation_is_bound_to_tracking_order(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        self.cancel()
        RewatchCancellation.objects.update(order_key="order:another-catalogue")
        self.assertEqual(self.progress().rewatch_watched, 2)

    def test_selected_catalogue_controls_inference_and_cancellation_scope(self):
        self.seed((3,))
        self.play(1, 1)
        self.play(1, 2)
        self.cancel()
        order = persist_order(self.item, "tmdb", self.item.media_id, "aired", "Personal order", {
            "episodes": [
                {"provider_episode_id": f"ep-{number}", "season_number": 1,
                 "episode_number": number, "title": f"Episode {number}", "air_date": "2020-01-01"}
                for number in range(1, 5)
            ],
        })
        self.tv.active_episode_order = order
        with patch("app.providers.services.get_media_metadata", side_effect=self.metadata_reader):
            self.assertIsNone(self.progress().rewatch_percent)
            self.items[1, 4] = Item.objects.create(
                media_id=self.item.media_id, source="tmdb", media_type="episode",
                title="Episode 4", season_number=1, episode_number=4,
            )
            self.play(1, 4, at=datetime(2021, 1, 1, tzinfo=UTC))
            result = self.progress()
        self.assertEqual((result.total, result.rewatch_watched, result.rewatch_percent), (4, 2, 50))
        self.assertIn("order_", result.seasons[0].url)

    def test_cancellation_requires_owner_and_csrf_and_valid_input(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        url = reverse("cancel_progress_rewatch")
        other = get_user_model().objects.create_user(username="other-rewatch")
        self.client.force_login(other)
        self.assertEqual(self.cancel().status_code, 404)
        self.client.logout()
        self.assertEqual(self.cancel().status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(url, {
            "media_type": "tv", "instance_id": self.tv.pk, "run_key": self.progress().run_key,
        })
        # Floppy's CSRF failure handler refreshes authenticated sessions.
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RewatchCancellation.objects.exists())
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {"media_type": "tv", "instance_id": "bad"}).status_code, 400)

    def test_fragment_payload_matches_the_card(self):
        self.seed()
        self.play(1, 1)
        self.play(1, 2)
        response = self.client.get(reverse("tv_progress_breakdown", args=[self.tv.pk]))
        payload = json.loads(response["HX-Trigger-After-Swap"])["rewatch-progress-resolved"]
        self.assertEqual(payload["rewatch"], self.progress().rewatch_percent)
        self.assertEqual(payload["run_key"], self.progress().run_key)
