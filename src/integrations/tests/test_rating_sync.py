"""Rating sync contracts: explicit writers, durable delivery and personal auth."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from app.log_safety import redact_secrets
from app.models import TV, Episode, Item, Movie, Season, Status
from app.services.episode_scores import rate_episode
from integrations.imports.helpers import decrypt, encrypt
from integrations.models import (
    CAPABILITY_RATING_PUSH,
    CAPABILITY_WATCHED_PUSH_PLAYED,
    OutboundStateDelivery,
    RatingSyncEdit,
    TMDbAccount,
)
from integrations.state import outbound
from integrations.state.adapters.base import RemoteRating, TransientAdapterError
from integrations.state.adapters.tmdb import TMDbRatingAdapter
from integrations.state.identity import activate_binding, get_or_create_binding
from integrations.state.ratings import rating_edit
from integrations.tasks._ratings import _latest_rating, export_tmdb_ratings
from integrations.tmdb_api import TMDbAuthError, TMDbClient


class RatingSyncTestCase(TestCase):
    """Local fixtures without provider or broker traffic."""

    def setUp(self):
        """Connect one account and approve only outbound ratings."""
        self.user = get_user_model().objects.create_user(username="rating-owner")
        self.client.force_login(self.user)
        release_patch = patch("app.models.Item.fetch_releases")
        release_patch.start()
        self.addCleanup(release_patch.stop)
        metadata_patch = patch(
            "app.providers.services.get_media_metadata",
            return_value={
                "max_progress": None,
                "related": {"seasons": [], "recommendations": []},
                "episodes": [
                    {
                        "episode_number": 2,
                        "season_number": 1,
                        "title": "Episode",
                        "runtime": 45,
                    }
                ],
            },
        )
        metadata_patch.start()
        self.addCleanup(metadata_patch.stop)
        self.item = Item.objects.create(
            media_id="550", source="tmdb", media_type="movie", title="Movie"
        )
        self.movie = Movie.objects.create(
            user=self.user, item=self.item, status=Status.PLANNING.value
        )
        self.account = TMDbAccount.objects.create(
            user=self.user,
            account_id="42",
            username="tmdb-user",
            session_id=encrypt("private-session"),
        )
        self.binding, _ = get_or_create_binding(
            self.user,
            "tmdb",
            instance_key="themoviedb.org",
            profile_key="42",
        )
        activate_binding(
            self.binding, capabilities=[CAPABILITY_RATING_PUSH], directions=["outbound"]
        )
        self.url = reverse("update_media_score", args=["movie", self.movie.pk])

    def edit(self, score):
        """Use the real UI rating writer."""
        return self.client.post(
            self.url, {"score": "null" if score is None else str(score)}
        )

    def episode_fixture(self):
        """Create an unwatched episode identity without metadata calls."""
        tv_item = Item.objects.create(
            media_id="100", source="tmdb", media_type="tv", title="Show"
        )
        tv = TV.objects.create(
            item=tv_item, user=self.user, status=Status.PLANNING.value
        )
        season_item = Item.objects.create(
            media_id="100",
            source="tmdb",
            media_type="season",
            title="Show",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.PLANNING.value,
        )
        item = Item.objects.create(
            media_id="100",
            source="tmdb",
            media_type="episode",
            title="Episode",
            season_number=1,
            episode_number=2,
        )
        return season, item


class DirectRatingTests(RatingSyncTestCase):
    """Only explicit, successful edits publish; copied/imported scores do not."""

    def test_ui_edit_and_clear_create_atomic_intents(self):
        self.assertEqual(self.edit("7.2").status_code, 200)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.score, Decimal("7.2"))
        self.assertEqual(OutboundStateDelivery.objects.get().rating, Decimal("7.2"))
        self.edit(None)
        first, last = OutboundStateDelivery.objects.order_by("pk")
        self.assertEqual(first.status, "superseded")
        self.assertIsNone(last.rating)
        self.assertIsNone(RatingSyncEdit.objects.get().score)

    def test_empty_score_post_is_an_explicit_clear(self):
        self.edit(7)
        self.client.post(self.url, {})
        self.assertIsNone(OutboundStateDelivery.objects.latest("pk").rating)

    def test_rating_only_connection_does_not_enable_watched_change_log(self):
        from app.models import WatchStateSequence

        self.assertFalse(WatchStateSequence.objects.get(user=self.user).emit_changes)

    def test_duplicate_edit_and_unrelated_save_do_not_publish(self):
        self.edit(7)
        self.edit(7)
        self.movie.refresh_from_db()
        self.movie.notes = "notes"
        self.movie.save()
        self.assertEqual(OutboundStateDelivery.objects.count(), 1)

    def test_import_and_provider_writes_stay_local(self):
        self.movie.score = 6
        self.movie.save()
        Movie.objects.filter(pk=self.movie.pk).update(score=8)
        self.assertFalse(OutboundStateDelivery.objects.exists())
        self.assertFalse(RatingSyncEdit.objects.exists())

    def test_disabled_connection_moves_nothing(self):
        self.binding.status = "disabled"
        self.binding.save()
        self.edit(8)
        self.assertFalse(OutboundStateDelivery.objects.exists())
        self.assertEqual(RatingSyncEdit.objects.get().score, 8)

    def test_user_isolation(self):
        other = get_user_model().objects.create_user(username="other-owner")
        self.client.force_login(other)
        self.assertEqual(self.edit(7).status_code, 404)
        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_invalid_input_moves_nothing(self):
        self.assertEqual(self.edit("garbage").status_code, 400)
        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_outer_rollback_discards_edit_and_intent(self):
        with transaction.atomic():
            self.edit(8)
            transaction.set_rollback(True)
        self.movie.refresh_from_db()
        self.assertIsNone(self.movie.score)
        self.assertFalse(RatingSyncEdit.objects.exists())
        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_success_schedules_only_after_commit(self):
        with patch("integrations.tasks.deliver_watched_state.delay") as kick:
            with self.captureOnCommitCallbacks(execute=True):
                self.edit(8)
                kick.assert_not_called()
            kick.assert_called_once()

    def test_api_patch_uses_same_path(self):
        response = self.client.patch(
            reverse("api_media_detail", args=["movie", "tmdb", "550"]),
            data='{"score": 6.3}',
            content_type="application/json",
            HTTP_X_API_KEY=self.user.token,
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(OutboundStateDelivery.objects.get().rating, Decimal("6.3"))

    def test_repeated_api_decimal_score_is_not_a_fresh_rating(self):
        url = reverse("api_media_detail", args=["movie", "tmdb", "550"])
        for _ in range(2):
            response = self.client.patch(
                url,
                data='{"score": 7.2}',
                content_type="application/json",
                HTTP_X_API_KEY=self.user.token,
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(OutboundStateDelivery.objects.count(), 1)

    def test_episode_clear_survives_deleted_rating_only_row(self):
        season, item = self.episode_fixture()
        url = reverse("update_episode_score", args=[season.pk, 2])
        self.assertEqual(self.client.post(url, {"score": 8}).status_code, 200)
        self.assertTrue(Episode.ratings.get(item=item).rating_only)
        self.assertEqual(self.client.post(url, {"score": "null"}).status_code, 200)
        self.assertFalse(Episode.ratings.filter(item=item).exists())
        self.assertEqual(_latest_rating(self.user, item), (True, None))
        self.assertIsNone(
            OutboundStateDelivery.objects.filter(item=item).latest("pk").rating
        )

    def test_bulk_episode_score_change_is_one_delivery(self):
        season, item = self.episode_fixture()
        Episode.all_objects.bulk_create(
            [
                Episode(item=item, related_season=season, score=6),
                Episode(item=item, related_season=season, score=6),
            ]
        )
        url = reverse("update_episode_score", args=[season.pk, 2])
        self.assertEqual(self.client.post(url, {"score": 9}).status_code, 200)
        self.assertEqual(OutboundStateDelivery.objects.filter(item=item).count(), 1)
        self.assertEqual(
            set(Episode.ratings.filter(item=item).values_list("score", flat=True)),
            {Decimal(9)},
        )

    def test_new_replay_inheriting_score_does_not_publish(self):
        season, item = self.episode_fixture()
        original = Episode.ratings.create(
            item=item, related_season=season, score=7, rating_only=True
        )
        Episode.ratings.filter(pk=original.pk).update(
            scored_at=timezone.now() - timedelta(days=1)
        )

        @rating_edit
        def replay(request):
            Episode.objects.create(item=item, related_season=season)
            return HttpResponse()

        request = RequestFactory().post("/replay", {"score": "null"})
        request.user = self.user
        replay(request)
        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_episode_service_outside_scope_does_not_publish(self):
        season, _item = self.episode_fixture()
        rate_episode(season, 2, Decimal(8))
        self.assertFalse(OutboundStateDelivery.objects.exists())


class DeliveryTests(RatingSyncTestCase):
    """Ratings share durability and retry rules with watched-state delivery."""

    def test_rating_and_watched_deliveries_do_not_supersede_each_other(self):
        watched = OutboundStateDelivery.objects.create(
            binding=self.binding,
            user=self.user,
            item=self.item,
            target_revision=1,
        )
        self.edit(8)
        watched.refresh_from_db()
        self.assertEqual(watched.operation, "watched")
        self.assertEqual(watched.status, "pending")
        self.assertIsNotNone(outbound.claim(watched.pk))
        self.assertIsNotNone(
            outbound.claim(OutboundStateDelivery.objects.get(operation="rating").pk)
        )

    def test_only_one_rating_revision_may_be_in_flight(self):
        self.edit(7)
        first = OutboundStateDelivery.objects.get()
        self.assertIsNotNone(outbound.claim(first.pk))
        self.edit(8)
        newest = OutboundStateDelivery.objects.latest("pk")
        self.assertIsNone(outbound.claim(newest.pk))

    def test_retry_compares_normalized_score_before_writing(self):
        self.edit("7.2")
        delivery = OutboundStateDelivery.objects.get()
        delivery.attempts = 1
        delivery.save()
        with patch.object(
            TMDbClient, "request", return_value={"rated": {"value": 7.0}}
        ) as api:
            result = outbound.run_delivery(delivery.pk)
        self.assertEqual(result.status, "delivered")
        self.assertEqual(api.call_count, 1)

    def test_clear_retry_distinguishes_unrated_from_unknown(self):
        self.edit(7)
        self.edit(None)
        delivery = OutboundStateDelivery.objects.latest("pk")
        delivery.attempts = 1
        delivery.save()
        with patch.object(TMDbClient, "request", return_value={"rated": False}) as api:
            self.assertEqual(outbound.run_delivery(delivery.pk).status, "delivered")
        self.assertEqual(api.call_count, 1)

    def test_unknown_readback_does_not_acknowledge_a_clear(self):
        self.edit(7)
        self.edit(None)
        delivery = OutboundStateDelivery.objects.latest("pk")
        delivery.attempts = 1
        delivery.save()
        with patch.object(
            TMDbClient, "request", side_effect=[{}, {"success": True}]
        ) as api:
            self.assertEqual(outbound.run_delivery(delivery.pk).status, "delivered")
        self.assertEqual(api.call_args.args[0], "DELETE")

    def test_failed_old_inflight_revision_never_retries_over_new_edit(self):
        self.edit(7)
        delivery = OutboundStateDelivery.objects.get()
        adapter = TMDbRatingAdapter(self.account)

        def fail_after_edit(*args, **kwargs):
            self.edit(9)
            message = "Timed out"
            raise TransientAdapterError(message)

        with (
            patch.object(outbound, "get_adapter", return_value=adapter),
            patch.object(adapter, "write_rating", side_effect=fail_after_edit),
        ):
            self.assertEqual(outbound.run_delivery(delivery.pk).status, "superseded")
        self.assertEqual(OutboundStateDelivery.objects.latest("pk").rating, 9)

    def test_transient_failure_retries_and_auth_failure_is_terminal(self):
        self.edit(8)
        delivery = OutboundStateDelivery.objects.get()
        with patch.object(
            TMDbClient, "request", side_effect=TransientAdapterError("timeout")
        ):
            result = outbound.run_delivery(delivery.pk)
        self.assertEqual(result.status, "pending")
        self.assertIsNotNone(result.next_attempt_at)
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        result.next_attempt_at = None
        result.save()
        with patch.object(TMDbClient, "request", side_effect=TMDbAuthError("rejected")):
            self.assertEqual(outbound.run_delivery(delivery.pk).status, "failed")
        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)

    def test_lost_broker_kick_is_recovered_by_sweeper(self):
        from integrations.tasks._state_sync import sweep_watched_state_deliveries

        self.edit(8)
        with patch.object(TMDbClient, "request", return_value={"success": True}):
            self.assertEqual(sweep_watched_state_deliveries(), 1)
        self.assertEqual(OutboundStateDelivery.objects.get().status, "delivered")

    def test_disconnect_skips_queued_deliveries(self):
        self.edit(8)
        with patch.object(TMDbClient, "request", return_value={"success": True}):
            self.client.post(reverse("tmdb_disconnect"))
        self.assertFalse(TMDbAccount.objects.exists())
        self.assertIsNone(outbound.run_delivery(OutboundStateDelivery.objects.get().pk))
        self.assertEqual(OutboundStateDelivery.objects.get().status, "skipped")

    def test_permission_is_rechecked_at_delivery_time(self):
        self.edit(8)
        self.binding.approved_capabilities = [CAPABILITY_WATCHED_PUSH_PLAYED]
        self.binding.save()
        with patch.object(TMDbClient, "request") as api:
            self.assertEqual(
                outbound.run_delivery(OutboundStateDelivery.objects.get().pk).status,
                "skipped",
            )
        api.assert_not_called()

    def test_unresolved_identity_records_a_visible_skip(self):
        self.item.source = "manual"
        self.item.save()
        self.edit(8)
        with patch.object(TMDbClient, "request") as api:
            result = outbound.run_delivery(OutboundStateDelivery.objects.get().pk)
        self.assertEqual(result.status, "skipped")
        self.assertIn("unambiguously", result.last_error_message)
        api.assert_not_called()


class TMDbAdapterTests(RatingSyncTestCase):
    """Provider-specific conversion, identity and health behavior."""

    def test_scale_conversion_does_not_confuse_zero_and_clear(self):
        adapter = TMDbRatingAdapter(self.account)
        for value, expected in [
            (None, None),
            (0, "0.5"),
            ("0.2", "0.5"),
            ("7.2", "7"),
            ("7.3", "7.5"),
            (10, "10"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(
                    adapter.normalize_rating(value),
                    Decimal(expected) if expected else None,
                )

    def test_transport_sets_rounded_rating_and_deletes_clears(self):
        self.edit("7.3")
        with patch.object(TMDbClient, "request", return_value={"success": True}) as api:
            outbound.run_delivery(OutboundStateDelivery.objects.latest("pk").pk)
        api.assert_called_once_with("POST", "movie/550/rating", json={"value": 7.5})
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.score, Decimal("7.3"))
        self.edit(None)
        with patch.object(TMDbClient, "request", return_value={"success": True}) as api:
            outbound.run_delivery(OutboundStateDelivery.objects.latest("pk").pk)
        api.assert_called_once_with("DELETE", "movie/550/rating")

    def test_identity_and_unsupported_season(self):
        adapter = TMDbRatingAdapter(self.account)
        season, item = self.episode_fixture()
        self.assertEqual(adapter.resolve_external_id(self.item), "movie/550")
        self.assertEqual(adapter.resolve_external_id(season.related_tv.item), "tv/100")
        self.assertEqual(adapter.resolve_external_id(item), "tv/100/season/1/episode/2")
        self.assertIsNone(adapter.resolve_external_id(season.item))
        item.episode_order_id = 1
        self.assertIsNone(adapter.resolve_external_id(item))

    def test_invalid_encryption_is_unusable_without_a_crash(self):
        self.account.session_id = "old-key-ciphertext"
        self.account.save()
        self.edit(8)
        with patch.object(TMDbClient, "request") as api:
            result = outbound.run_delivery(OutboundStateDelivery.objects.get().pk)
        self.assertEqual(result.status, "failed")
        self.assertIn("decrypt", result.last_error_message)
        api.assert_not_called()

    def test_inflight_success_after_disconnect_does_not_recreate_account(self):
        adapter = TMDbRatingAdapter(self.account)

        def finish_after_disconnect(*args, **kwargs):
            TMDbAccount.objects.filter(pk=self.account.pk).delete()
            return {"success": True}

        with patch.object(TMDbClient, "request", side_effect=finish_after_disconnect):
            adapter.write_rating("movie/550", score=Decimal(8))
        self.assertFalse(TMDbAccount.objects.exists())

    def test_old_session_rejection_does_not_mark_reconnected_account_broken(self):
        adapter = TMDbRatingAdapter(self.account)
        TMDbAccount.objects.filter(pk=self.account.pk).update(
            session_id=encrypt("new-session")
        )
        with patch.object(
            TMDbClient, "request", side_effect=TMDbAuthError("old session rejected")
        ):
            with self.assertRaises(TMDbAuthError):
                adapter.write_rating("movie/550", score=Decimal(8))
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)
        self.assertEqual(decrypt(self.account.session_id), "new-session")

    def test_http_failures_are_classified_without_secret_text(self):
        client = TMDbClient(self.user, "private-session")
        for status, error_class in [
            (401, TMDbAuthError),
            (403, TMDbAuthError),
            (429, TransientAdapterError),
            (503, TransientAdapterError),
        ]:
            with (
                self.subTest(status=status),
                patch(
                    "integrations.tmdb_api.requests.request",
                    return_value=Mock(status_code=status),
                ),
            ):
                with self.assertRaises(error_class) as caught:
                    client.request("GET", "account")
                self.assertNotIn("private-session", str(caught.exception))
        with patch(
            "integrations.tmdb_api.requests.request",
            side_effect=requests.Timeout("secret-url"),
        ):
            with self.assertRaises(TransientAdapterError):
                client.request("GET", "account")

    def test_session_id_is_redacted(self):
        for text in [
            "session_id=private-session",
            '{"session_id": "private-session"}',
            "?api_key=x&session_id=private-session",
        ]:
            self.assertNotIn("private-session", redact_secrets(text))

    def test_sweeper_reprobes_rejected_credentials(self):
        from integrations.tasks._state_sync import sweep_watched_state_deliveries

        self.account.connection_broken = True
        self.account.last_failed_at = timezone.now() - timedelta(hours=2)
        self.account.save()
        with patch.object(TMDbClient, "request", return_value={"id": 42}) as api:
            sweep_watched_state_deliveries()
        api.assert_called_once_with("GET", "account")
        self.account.refresh_from_db()
        self.assertFalse(self.account.connection_broken)


class ExportTests(RatingSyncTestCase):
    """Export is explicit, bounded, and uses the latest edit across repeats."""

    def test_imported_rating_is_sent_only_by_export(self):
        self.movie.score = 8
        self.movie.save()
        self.assertFalse(OutboundStateDelivery.objects.exists())
        self.assertEqual(export_tmdb_ratings(self.user.pk), 1)
        self.assertEqual(OutboundStateDelivery.objects.get().rating, 8)

    def test_latest_edit_wins_over_newer_tracking_entry(self):
        old = timezone.now() - timedelta(days=5)
        Movie.objects.create(
            user=self.user,
            item=self.item,
            score=9,
            scored_at=old,
            status=Status.PLANNING.value,
        )
        self.edit(7)
        self.assertEqual(export_tmdb_ratings(self.user.pk), 1)
        self.assertEqual(OutboundStateDelivery.objects.latest("pk").rating, 7)

    def test_latest_clear_wins_over_old_rated_entry(self):
        Movie.objects.create(
            user=self.user,
            item=self.item,
            score=9,
            scored_at=timezone.now() - timedelta(days=1),
            status=Status.PLANNING.value,
        )
        self.edit(7)
        self.edit(None)
        export_tmdb_ratings(self.user.pk)
        self.assertIsNone(OutboundStateDelivery.objects.latest("pk").rating)

    def test_newer_imported_edit_wins_over_older_explicit_edit(self):
        self.edit(7)
        self.movie.refresh_from_db()
        self.movie.score = 9
        self.movie.save()
        self.assertEqual(_latest_rating(self.user, self.item), (True, Decimal(9)))

    def test_export_stops_when_sync_is_disabled(self):
        self.edit(7)
        self.client.post(reverse("tmdb_settings"), {})
        self.assertEqual(export_tmdb_ratings(self.user.pk), 0)

    def test_batches_do_not_skip_items(self):
        self.movie.score = 8
        self.movie.save()
        second = Item.objects.create(
            media_id="551", source="tmdb", media_type="movie", title="Second"
        )
        Movie.objects.create(
            user=self.user, item=second, score=7, status=Status.PLANNING.value
        )
        with patch("integrations.tasks._ratings.EXPORT_BATCH_SIZE", 1):
            self.assertEqual(export_tmdb_ratings(self.user.pk), 2)


class ConnectionTests(RatingSyncTestCase):
    """TMDb browser approval is user/session bound, single-use and opt-in."""

    def authorization(self, **overrides):
        """Store a pending authorization just as the start view does."""
        session = self.client.session
        session["tmdb_auth"] = {
            "request_token": "approved-token",
            "user_id": self.user.pk,
            "expires_at": (timezone.now() + timedelta(minutes=30)).timestamp(),
            **overrides,
        }
        session.save()

    def callback(self, **overrides):
        """Return to the real callback route."""
        return self.client.get(
            reverse("tmdb_callback"),
            {
                "request_token": "approved-token",
                "approved": "true",
                **overrides,
            },
        )

    def test_start_uses_browser_approval(self):
        with patch.object(
            TMDbClient,
            "request",
            return_value={
                "request_token": "request-123",
                "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
            },
        ):
            response = self.client.post(reverse("tmdb_connect"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(
                "https://www.themoviedb.org/authenticate/request-123?"
            )
        )
        self.assertEqual(self.client.session["tmdb_auth"]["user_id"], self.user.pk)

    def test_start_accepts_tmdb_utc_expiry_format(self):
        expiry = (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S UTC")
        with patch.object(
            TMDbClient,
            "request",
            return_value={"request_token": "utc-token", "expires_at": expiry},
        ):
            response = self.client.post(reverse("tmdb_connect"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["tmdb_auth"]["request_token"], "utc-token")

    def test_invalid_or_expired_provider_expiry_does_not_start_authorization(self):
        for expiry in [
            None,
            1,
            "2026-99-99 00:00:00 UTC",
            "invalid",
            "2000-01-01 00:00:00 UTC",
        ]:
            with (
                self.subTest(expiry=expiry),
                patch.object(
                    TMDbClient,
                    "request",
                    return_value={"request_token": "bad-token", "expires_at": expiry},
                ),
            ):
                response = self.client.post(reverse("tmdb_connect"))
            self.assertEqual(response.url, reverse("integrations"))
            self.assertNotIn("tmdb_auth", self.client.session)

    def test_callback_encrypts_session_and_does_not_enable_sync(self):
        self.authorization()
        with patch.object(
            TMDbClient,
            "request",
            side_effect=[
                {"session_id": "new-private-session"},
                {"id": 43, "username": "new-user"},
            ],
        ):
            self.assertEqual(self.callback().status_code, 302)
        self.account.refresh_from_db()
        self.assertNotEqual(self.account.session_id, "new-private-session")
        self.assertEqual(decrypt(self.account.session_id), "new-private-session")
        self.assertEqual(self.account.account_id, "43")
        self.assertFalse(self.user.sync_bindings.filter(status="active").exists())
        self.assertNotIn("tmdb_auth", self.client.session)

    def test_mismatched_expired_denied_and_other_user_tokens_do_not_exchange(self):
        scenarios = [
            ({}, {"request_token": "other"}),
            ({}, {"request_token": "☃"}),
            ({"expires_at": 0}, {}),
            ({"user_id": self.user.pk + 1}, {}),
            ({}, {"approved": "false"}),
        ]
        for stored, callback in scenarios:
            with self.subTest(stored=stored, callback=callback):
                self.authorization(**stored)
                with patch.object(TMDbClient, "request") as api:
                    self.callback(**callback)
                api.assert_not_called()

    def test_callback_cannot_be_replayed(self):
        self.authorization()
        with patch.object(
            TMDbClient,
            "request",
            side_effect=[{"session_id": "new-session"}, {"id": 42}],
        ):
            self.callback()
        with patch.object(TMDbClient, "request") as api:
            self.callback()
        api.assert_not_called()

    def test_enable_does_not_export_existing_ratings(self):
        self.client.post(reverse("tmdb_settings"), {"enabled": "on"})
        self.assertFalse(OutboundStateDelivery.objects.exists())

    def test_export_requires_an_active_binding(self):
        self.client.post(reverse("tmdb_settings"), {})
        with patch("integrations.tasks.export_tmdb_ratings.delay") as export:
            self.client.post(reverse("tmdb_export_ratings"))
        export.assert_not_called()

    def test_settings_show_connection_and_delivery_results(self):
        self.edit(8)
        response = self.client.get(reverse("integrations"))
        self.assertContains(response, "TMDb ratings")
        self.assertContains(response, "tmdb-user")
        self.assertNotContains(response, "private-session")
