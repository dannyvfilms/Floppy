"""Upgrade repair of existing stored metadata without manual per-item syncing."""

from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from app import history_cache
from app.models import (
    TV,
    BackfillReconcileState,
    Episode,
    Item,
    MetadataProviderPreference,
    Movie,
    Season,
    Sources,
    Status,
)
from app.tasks_metadata_language import (
    repair_metadata_language_batch,
    reset_metadata_language_repair,
)


@override_settings(TMDB_LANG="en-US")
class MetadataLanguageRepairTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="spanish",
            metadata_language="es-ES",
        )
        self.metadata = self.enterContext(
            patch("app.tasks_metadata_language.services.get_media_metadata"),
        )
        self.metadata.return_value = {
            "title": "El padrino",
            "original_title": "The Godfather",
            "localized_title": "El padrino",
            "synopsis": "La historia de una familia.",
        }
        self.enterContext(
            patch(
                "app.tasks_metadata_language.interactive_request_active",
                return_value=False,
            ),
        )

    def movie(self, **fields):
        defaults = {
            "media_id": str(Item.objects.count() + 1),
            "source": Sources.TMDB.value,
            "media_type": "movie",
            "title": "The Godfather",
            "synopsis": "An English overview.",
            "metadata_fetched_at": timezone.now(),
        }
        defaults.update(fields)
        item = Item.objects.create(**defaults)
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=self.user, status=Status.PLANNING.value),
            ]
        )
        return item

    def due(self):
        BackfillReconcileState.objects.update(next_run_after=None)

    @patch("app.history_cache.schedule_history_refresh")
    def test_unchanged_and_synopsis_only_repairs_preserve_history(self, refresh):
        item = self.movie(
            title="El padrino",
            localized_title="El padrino",
            original_title="The Godfather",
            synopsis=self.metadata.return_value["synopsis"],
        )
        keys = [
            history_cache._cache_key(self.user.pk, style)
            for style in ("sessions", "repeats")
        ]
        for synopsis in (item.synopsis, "Una sinopsis nueva."):
            with self.subTest(synopsis=synopsis):
                BackfillReconcileState.objects.all().delete()
                self.metadata.return_value["synopsis"] = synopsis
                for key in keys:
                    cache.set(key, {"days": [], "sentinel": "valid"})
                self.assertEqual(repair_metadata_language_batch(1)["success"], 1)
                item.refresh_from_db()
                self.assertEqual(item.synopsis, synopsis)
                for key in keys:
                    self.assertEqual(cache.get(key)["sentinel"], "valid")
        self.assertEqual(self.metadata.call_count, 2)
        refresh.assert_not_called()

    @patch("app.history_cache.schedule_history_refresh")
    def test_title_fields_invalidate_both_history_styles_for_all_owners(self, refresh):
        item = self.movie()
        other = get_user_model().objects.create_user(
            username="shared-spanish",
            metadata_language="es-ES",
        )
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=other, status=Status.PLANNING.value),
            ]
        )
        for field in ("title", "original_title", "localized_title"):
            with self.subTest(field=field):
                BackfillReconcileState.objects.all().delete()
                Item.objects.filter(pk=item.pk).update(
                    **{
                        name: value
                        for name, value in self.metadata.return_value.items()
                        if name != "synopsis"
                    },
                )
                Item.objects.filter(pk=item.pk).update(**{field: "Old value"})
                keys = [
                    history_cache._cache_key(owner.pk, style)
                    for owner in (self.user, other)
                    for style in ("sessions", "repeats")
                ]
                for key in keys:
                    cache.set(key, {"days": []})
                refresh.reset_mock()
                self.assertEqual(repair_metadata_language_batch(1)["success"], 1)
                for key in keys:
                    self.assertIsNone(cache.get(key))
                self.assertEqual(
                    [call.args[0] for call in refresh.call_args_list],
                    [self.user.pk, other.pk],
                )

    @patch("app.history_cache.schedule_history_refresh")
    def test_changed_prefix_invalidates_history_despite_later_failure(self, refresh):
        first = self.movie()
        self.movie()
        self.metadata.side_effect = [
            self.metadata.return_value,
            RuntimeError("offline"),
        ]
        key = history_cache._cache_key(self.user.pk, "repeats")
        cache.set(key, {"days": []})

        result = repair_metadata_language_batch(2)

        self.assertEqual(result, {"attempted": 2, "success": 1, "errors": 1})
        self.assertEqual(
            BackfillReconcileState.objects.get().last_cursor_item_id, first.pk
        )
        self.assertGreater(
            BackfillReconcileState.objects.get().next_run_after, timezone.now()
        )
        self.assertIsNone(cache.get(key))
        refresh.assert_called_once_with(self.user.pk)
        self.due()
        self.metadata.side_effect = None
        self.assertEqual(repair_metadata_language_batch(2)["success"], 1)

    @patch("app.history_cache.schedule_history_refresh")
    def test_changed_prefix_invalidates_history_on_reset_during_next_fetch(
        self, refresh
    ):
        first = self.movie()
        second = self.movie()
        key = history_cache._cache_key(self.user.pk, "sessions")
        cache.set(key, {"days": []})

        def reset_second_fetch(*args, **kwargs):
            if self.metadata.call_count == 2:
                reset_metadata_language_repair(self.user.pk)
            return self.metadata.return_value

        self.metadata.side_effect = reset_second_fetch
        repair_metadata_language_batch(2)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.title, "El padrino")
        self.assertEqual(second.title, "The Godfather")
        self.assertIsNone(cache.get(key))
        refresh.assert_called_once_with(self.user.pk)

    @patch("app.history_cache.schedule_history_refresh")
    def test_changed_prefix_invalidates_history_on_preference_change(self, refresh):
        first = self.movie()
        second = self.movie()

        def change_second_fetch(*args, **kwargs):
            if self.metadata.call_count == 2:
                get_user_model().objects.filter(pk=self.user.pk).update(
                    metadata_language="fr-FR",
                )
            return self.metadata.return_value

        self.metadata.side_effect = change_second_fetch
        repair_metadata_language_batch(2)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.title, "El padrino")
        self.assertEqual(second.title, "The Godfather")
        refresh.assert_called_once_with(self.user.pk)

    @patch("app.history_cache.schedule_history_refresh")
    def test_terminal_failure_after_changed_item_still_refreshes_history(self, refresh):
        first = self.movie()
        self.movie()
        response = requests.Response()
        response.status_code = 404
        self.metadata.side_effect = [
            self.metadata.return_value,
            requests.HTTPError(response=response),
        ]

        self.assertEqual(
            repair_metadata_language_batch(2),
            {"attempted": 2, "success": 1, "errors": 1},
        )

        first.refresh_from_db()
        self.assertEqual(first.title, "El padrino")
        refresh.assert_called_once_with(self.user.pk)

    @patch("app.history_cache.schedule_history_refresh")
    def test_episode_title_refreshes_each_related_season_owner(self, refresh):
        other = get_user_model().objects.create_user(
            username="episode-owner",
            metadata_language="es-ES",
        )
        episode_item, tv_item, season_item = Item.objects.bulk_create(
            [
                Item(
                    media_id="show",
                    source=Sources.TMDB.value,
                    media_type=kind,
                    title="Old title",
                    season_number=season,
                    episode_number=episode,
                )
                for kind, season, episode in (
                    ("episode", 1, 1),
                    ("tv", None, None),
                    ("season", 1, None),
                )
            ]
        )
        shows = TV.objects.bulk_create(
            [
                TV(item=tv_item, user=owner, status=Status.PLANNING.value)
                for owner in (self.user, other)
            ]
        )
        seasons = Season.objects.bulk_create(
            [
                Season(
                    item=season_item,
                    user=show.user,
                    related_tv=show,
                    status=Status.PLANNING.value,
                )
                for show in shows
            ]
        )
        Episode.objects.bulk_create(
            [Episode(item=episode_item, related_season=season) for season in seasons]
        )

        self.assertEqual(repair_metadata_language_batch(1)["success"], 1)

        self.assertEqual(
            [call.args[0] for call in refresh.call_args_list],
            [self.user.pk, other.pk],
        )
        self.assertEqual(self.metadata.call_args.kwargs["episode_number"], 1)

    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    def test_active_browsing_defers_without_losing_automatic_continuation(
        self, publish
    ):
        self.movie()
        with (
            patch(
                "app.tasks_metadata_language.interactive_request_active",
                return_value=True,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            repair_metadata_language_batch(1)
        self.metadata.assert_not_called()
        self.assertEqual(publish.call_args.kwargs["countdown"], 60)
        self.assertEqual(BackfillReconcileState.objects.get().last_cursor_item_id, 0)

    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    def test_successful_page_schedules_bounded_followup_then_stops(self, publish):
        self.movie()
        with self.captureOnCommitCallbacks(execute=True):
            repair_metadata_language_batch(1)
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(publish.call_args.kwargs["countdown"], 60)
        self.assertEqual(publish.call_args.kwargs["kwargs"]["batch_size"], 25)
        self.due()
        with self.captureOnCommitCallbacks(execute=True):
            repair_metadata_language_batch(1)
        self.assertEqual(publish.call_count, 1)

    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    def test_skipped_page_continues_without_waiting_for_periodic_task(self, publish):
        self.movie(manual_metadata={"synopsis": "My text"})
        with self.captureOnCommitCallbacks(execute=True):
            repair_metadata_language_batch(1)
        self.assertEqual(publish.call_args.kwargs["countdown"], 60)
        self.metadata.assert_not_called()

    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    def test_failed_fetch_continuation_respects_backoff(self, publish):
        self.movie()
        self.metadata.side_effect = RuntimeError("provider unavailable")
        with self.captureOnCommitCallbacks(execute=True):
            repair_metadata_language_batch(1)
        self.assertGreaterEqual(publish.call_args.kwargs["countdown"], 1800)

    @patch("app.tasks.backfill_item_metadata_task.apply_async")
    def test_reset_before_commit_drops_stale_continuation(self, publish):
        self.movie()
        with self.captureOnCommitCallbacks(execute=True):
            repair_metadata_language_batch(1)
            BackfillReconcileState.objects.all().delete()
        publish.assert_not_called()

    def test_existing_english_metadata_repairs_without_manual_sync(self):
        item = self.movie()

        self.assertEqual(
            repair_metadata_language_batch(1),
            {"attempted": 1, "success": 1, "errors": 0},
        )

        item.refresh_from_db()
        self.assertEqual(item.title, "El padrino")
        self.assertEqual(item.localized_title, "El padrino")
        self.assertEqual(item.original_title, "The Godfather")
        self.assertEqual(item.synopsis, "La historia de una familia.")
        self.assertEqual(self.metadata.call_args.kwargs["language"], "es-ES")
        self.assertEqual(Movie.objects.get(item=item).status, Status.PLANNING.value)

    def test_batches_resume_and_completion_survives_cache_clear(self):
        first = self.movie()
        second = self.movie()

        repair_metadata_language_batch(1)
        self.assertEqual(
            BackfillReconcileState.objects.get().last_cursor_item_id, first.pk
        )
        self.due()
        cache.clear()
        repair_metadata_language_batch(1)
        self.assertEqual(
            BackfillReconcileState.objects.get().last_cursor_item_id, second.pk
        )
        self.due()
        repair_metadata_language_batch(1)
        self.assertIsNotNone(BackfillReconcileState.objects.get().completed_at)
        cache.clear()
        repair_metadata_language_batch(1)
        self.assertEqual(self.metadata.call_count, 2)

    def test_failed_item_is_not_skipped_or_marked_complete(self):
        item = self.movie()
        self.metadata.side_effect = RuntimeError("provider down")

        result = repair_metadata_language_batch(1)

        self.assertEqual(result, {"attempted": 1, "success": 0, "errors": 1})
        state = BackfillReconcileState.objects.get()
        self.assertEqual(state.last_cursor_item_id, 0)
        self.assertIsNone(state.completed_at)
        self.assertGreater(state.next_run_after, timezone.now())
        self.assertEqual(repair_metadata_language_batch(1)["attempted"], 0)
        self.due()
        self.metadata.side_effect = None
        repair_metadata_language_batch(1)
        item.refresh_from_db()
        self.assertEqual(item.synopsis, "La historia de una familia.")

    def test_removed_provider_item_does_not_block_later_library_entries(self):
        removed = self.movie()
        valid = self.movie()
        response = requests.Response()
        response.status_code = 404
        self.metadata.side_effect = [
            requests.HTTPError(response=response),
            self.metadata.return_value,
        ]
        result = repair_metadata_language_batch(2)
        self.assertEqual(result, {"attempted": 2, "success": 1, "errors": 1})
        valid.refresh_from_db()
        removed.refresh_from_db()
        self.assertEqual(valid.synopsis, "La historia de una familia.")
        self.assertEqual(removed.synopsis, "An English overview.")
        self.assertEqual(
            BackfillReconcileState.objects.get().last_cursor_item_id, valid.pk
        )

    def test_blank_synopsis_preserves_existing_text(self):
        item = self.movie()
        self.metadata.return_value["synopsis"] = ""

        repair_metadata_language_batch(1)

        item.refresh_from_db()
        self.assertEqual(item.synopsis, "An English overview.")

    def test_manual_source_custom_metadata_and_manual_provider_are_skipped(self):
        self.movie(source=Sources.MANUAL.value)
        self.movie(manual_metadata={"synopsis": "My review"})
        manual_display = self.movie()
        MetadataProviderPreference.objects.create(
            item=manual_display,
            user=self.user,
            provider=Sources.MANUAL.value,
        )

        repair_metadata_language_batch(10)

        self.metadata.assert_not_called()

    def test_per_item_language_override_wins(self):
        item = self.movie()
        MetadataProviderPreference.objects.create(
            item=item,
            user=self.user,
            language="fr-FR",
        )

        repair_metadata_language_batch(1)

        self.assertEqual(self.metadata.call_args.kwargs["language"], "fr-FR")

    def test_conflicting_tracking_owners_are_not_rewritten(self):
        item = self.movie()
        other = get_user_model().objects.create_user(username="english")
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=other, status=Status.PLANNING.value),
            ]
        )

        repair_metadata_language_batch(1)

        self.metadata.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.title, "The Godfather")

    def test_agreeing_tracking_owners_can_be_repaired(self):
        item = self.movie()
        other = get_user_model().objects.create_user(
            username="also-spanish",
            metadata_language="es-ES",
        )
        Movie.objects.bulk_create(
            [
                Movie(item=item, user=other, status=Status.PLANNING.value),
            ]
        )

        self.assertEqual(repair_metadata_language_batch(1)["success"], 1)

    def test_reset_during_fetch_prevents_stale_write(self):
        item = self.movie()
        translated = self.metadata.return_value

        def reset_while_fetching(*args, **kwargs):
            reset_metadata_language_repair(self.user.pk)
            return translated

        self.metadata.side_effect = reset_while_fetching

        repair_metadata_language_batch(1)

        item.refresh_from_db()
        self.assertEqual(item.title, "The Godfather")
        state = BackfillReconcileState.objects.get()
        self.assertEqual(state.last_cursor_item_id, 0)
        self.assertIsNone(state.completed_at)

    def test_preference_change_during_fetch_prevents_stale_write(self):
        item = self.movie()
        translated = self.metadata.return_value

        def change_while_fetching(*args, **kwargs):
            get_user_model().objects.filter(pk=self.user.pk).update(
                metadata_language="fr-FR"
            )
            return translated

        self.metadata.side_effect = change_while_fetching

        repair_metadata_language_batch(1)

        item.refresh_from_db()
        self.assertEqual(item.title, "The Godfather")

    def test_reset_reopens_previously_completed_language(self):
        self.movie()
        repair_metadata_language_batch(1)
        self.due()
        repair_metadata_language_batch(1)
        reset_metadata_language_repair(self.user.pk)

        repair_metadata_language_batch(1)

        self.assertEqual(self.metadata.call_count, 2)

    def test_default_english_users_do_not_trigger_upgrade_sweep(self):
        self.user.metadata_language = ""
        self.user.save(update_fields=["metadata_language"])
        self.movie()

        repair_metadata_language_batch(1)

        self.metadata.assert_not_called()
        self.assertFalse(BackfillReconcileState.objects.exists())

    def test_item_override_repairs_even_with_default_english_user_language(self):
        self.user.metadata_language = ""
        self.user.save(update_fields=["metadata_language"])
        item = self.movie()
        MetadataProviderPreference.objects.create(
            item=item,
            user=self.user,
            language="es-ES",
        )

        repair_metadata_language_batch(1)

        self.assertEqual(self.metadata.call_args.kwargs["language"], "es-ES")

    def test_clearing_language_repairs_back_to_instance_default(self):
        item = self.movie()
        repair_metadata_language_batch(1)
        self.user.metadata_language = ""
        self.user.save(update_fields=["metadata_language"])
        reset_metadata_language_repair(self.user.pk)
        self.metadata.return_value = {
            "title": "The Godfather",
            "synopsis": "An English overview.",
        }

        repair_metadata_language_batch(1)

        item.refresh_from_db()
        self.assertEqual(self.metadata.call_args.kwargs["language"], "en-US")
        self.assertEqual(item.title, "The Godfather")

    @override_settings(TMDB_LANG="es-ES")
    def test_non_english_instance_default_repairs_blank_user_preference(self):
        self.user.metadata_language = ""
        self.user.save(update_fields=["metadata_language"])
        self.movie()

        repair_metadata_language_batch(1)

        self.assertEqual(self.metadata.call_args.kwargs["language"], "es-ES")
        self.assertEqual(
            BackfillReconcileState.objects.get().key,
            f"metadata_language:{self.user.pk}:es-ES",
        )

    def test_untracked_items_are_not_repaired(self):
        item = self.movie()
        Movie.objects.filter(item=item).delete()

        repair_metadata_language_batch(1)

        self.metadata.assert_not_called()

    @patch("app.reconcile_state.cache_safety.acquire_lock", return_value=False)
    def test_cache_lock_failure_skips_provider_work(self, _lock):
        self.movie()

        repair_metadata_language_batch(1)

        self.metadata.assert_not_called()
