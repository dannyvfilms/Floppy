"""Several Jellyfin servers on one Floppy user: each is routed on its own (#2111)."""

import importlib
import json
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import IntervalSchedule, PeriodicTask

from integrations.imports.helpers import decrypt, encrypt
from integrations.imports.jellyfin_playback_reporting import PlaybackReportingRow
from integrations.models import JellyfinAccount, SourcePage, SyncClientKind
from integrations.state.adapters.jellyfin import build_adapter
from integrations.tasks import JELLYFIN_PULL_TASK_NAME
from integrations.tasks._webhook import _queue_jellyfin_instant_push
from integrations.webhooks.jellyfin import (
    attribute_connection,
    release_connection_sources,
    source_instance_ids,
)

CLIENT = "integrations.views.JellyfinClient"
PULL = "integrations.views.tasks.pull_jellyfin_history.delay"


def _page(user, instance_id, media_id):
    return SourcePage.objects.create(
        user=user,
        source="jellyfin",
        source_instance_id=instance_id,
        provider="tmdb",
        media_type="movie",
        media_id=media_id,
        path=f"web/#/details?id={media_id}",
    )


def _account(user, n, **extra):
    fields = {
        "name": f"Server {n}",
        "base_url": f"https://jf{n}.local:8096",
        "api_key": encrypt(f"key-{n}"),
        "jellyfin_user_id": f"jf-user-{n}",
        "server_id": f"server-{n}",
        **extra,
    }
    return JellyfinAccount.objects.create(user=user, **fields)


class ConnectionViewTests(TestCase):
    """Add, edit and disconnect touch only the connection they name."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="multi-jf")
        self.client.force_login(self.user)
        self.first = _account(self.user, 1)

    def _connect(self, n, **extra):
        with (
            patch(f"{CLIENT}.healthcheck", return_value={"Id": f"server-{n}"}),
            patch(
                f"{CLIENT}.get_current_user",
                return_value={"Id": f"jf-user-{n}", "Name": f"user{n}"},
            ),
            patch(PULL) as pull,
        ):
            response = self.client.post(
                reverse("jellyfin_connect"),
                {
                    "base_url": f"https://jf{n}.local:8096",
                    "api_key": f"key-{n}",
                    "name": f"Server {n}",
                    **extra,
                },
            )
        return response, pull

    def test_add_creates_a_separate_connection_and_schedule(self):
        response, pull = self._connect(2)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.jellyfin_accounts.count(), 2)
        second = self.user.jellyfin_accounts.get(server_id="server-2")
        pull.assert_called_once_with(user_id=self.user.id, account_id=second.id)
        self.first.refresh_from_db()
        self.assertEqual(decrypt(self.first.api_key), "key-1")
        kwargs = [
            json.loads(task.kwargs)
            for task in PeriodicTask.objects.filter(task=JELLYFIN_PULL_TASK_NAME)
        ]
        self.assertEqual(
            [item["account_id"] for item in kwargs],
            [second.id],
        )
        # A later connection's Playback Reporting identities are scoped to it.
        self.assertEqual(second.identity_scope, "server-2")
        self.assertEqual(self.first.identity_scope, "")

    def test_duplicate_server_and_user_is_refused(self):
        response, _pull = self._connect(1)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.user.jellyfin_accounts.count(), 1)

    def test_same_server_with_another_jellyfin_user_is_allowed(self):
        with (
            patch(f"{CLIENT}.healthcheck", return_value={"Id": "server-1"}),
            patch(
                f"{CLIENT}.get_current_user",
                return_value={"Id": "someone-else", "Name": "else"},
            ),
            patch(PULL),
        ):
            self.client.post(
                reverse("jellyfin_connect"),
                {"base_url": "https://jf1.local:8096", "api_key": "k"},
            )

        self.assertEqual(self.user.jellyfin_accounts.count(), 2)

    def test_edit_keeps_the_saved_key_when_left_blank(self):
        second = _account(self.user, 2, push_watched_enabled=False)
        with (
            patch(f"{CLIENT}.healthcheck", return_value={"Id": "server-2"}),
            patch(
                f"{CLIENT}.get_current_user",
                return_value={"Id": "jf-user-2", "Name": "user2"},
            ),
            patch(PULL),
        ):
            self.client.post(
                reverse("jellyfin_connect"),
                {"instance_id": second.id, "name": "Renamed", "api_key": ""},
            )

        second.refresh_from_db()
        self.assertEqual(second.name, "Renamed")
        self.assertEqual(decrypt(second.api_key), "key-2")
        self.assertFalse(second.push_watched_enabled)
        self.first.refresh_from_db()
        self.assertEqual(self.first.name, "Server 1")

    def test_edit_cannot_reach_another_users_connection(self):
        other = get_user_model().objects.create_user(username="someone-else")
        theirs = _account(other, 9)

        response, _pull = self._connect(5, instance_id=theirs.id)

        self.assertEqual(response.status_code, 302)
        theirs.refresh_from_db()
        self.assertEqual(theirs.name, "Server 9")

    def test_switching_server_resets_only_that_connections_cursor(self):
        second = _account(
            self.user,
            2,
            playback_reporting_last_rowid=500,
            playback_reporting_available=True,
        )
        self.first.playback_reporting_last_rowid = 77
        self.first.save()
        with (
            patch(f"{CLIENT}.healthcheck", return_value={"Id": "server-3"}),
            patch(
                f"{CLIENT}.get_current_user",
                return_value={"Id": "jf-user-3", "Name": "user3"},
            ),
            patch(PULL),
        ):
            self.client.post(
                reverse("jellyfin_connect"),
                {
                    "account_id": second.id,
                    "base_url": "https://jf3.local:8096",
                    "api_key": "key-3",
                },
            )

        second.refresh_from_db()
        self.first.refresh_from_db()
        self.assertIsNone(second.playback_reporting_last_rowid)
        self.assertEqual(second.identity_scope, "server-3")
        self.assertEqual(self.first.playback_reporting_last_rowid, 77)

    def test_disconnect_one_leaves_the_other_and_its_schedules(self):
        second = _account(self.user, 2, scheduled_push_enabled=True)
        self.client.post(reverse("jellyfin_settings"), {"account_id": self.first.id, "pull_history_enabled": "on", "scheduled_push_enabled": "on"})
        self.client.post(reverse("jellyfin_settings"), {"account_id": second.id, "pull_history_enabled": "on", "scheduled_push_enabled": "on"})
        self.assertEqual(PeriodicTask.objects.filter(task__contains="Jellyfin").count(), 4)

        self.client.post(reverse("jellyfin_disconnect"), {"instance_id": second.id})

        self.assertEqual(list(self.user.jellyfin_accounts.all()), [self.first])
        remaining = PeriodicTask.objects.filter(task__contains="Jellyfin")
        self.assertEqual(remaining.count(), 2)
        for task in remaining:
            self.assertEqual(json.loads(task.kwargs)["account_id"], self.first.id)

    def test_actions_without_an_account_are_ambiguous_with_several(self):
        _account(self.user, 2)

        with patch(PULL) as pull:
            self.client.post(reverse("jellyfin_pull_now"))

        pull.assert_not_called()

    def test_pull_now_targets_the_named_connection(self):
        second = _account(self.user, 2)

        with patch(PULL) as pull:
            self.client.post(reverse("jellyfin_pull_now"), {"account_id": second.id})

        pull.assert_called_once_with(user_id=self.user.id, account_id=second.id)

    def test_connection_tab_lists_every_connection_without_keys(self):
        _account(self.user, 2)

        response = self.client.get(
            reverse("provider_detail", args=["jellyfin"]) + "?tab=connection",
        )

        card = response.context["account_connection"]
        self.assertEqual([row["name"] for row in card["instances"]], ["Server 1", "Server 2"])
        self.assertTrue(all(row["editable"] for row in card["instances"]))
        self.assertNotIn("key-1", str(card))


class TaskRoutingTests(TestCase):
    """Scheduled and queued work runs against the connection it names."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="multi-jf-tasks")
        self.first = _account(self.user, 1)
        self.second = _account(self.user, 2)

    @patch("integrations.tasks._media_imports.JellyfinPushSyncService")
    def test_push_runs_only_for_the_named_account(self, service):
        from integrations.tasks._media_imports import push_jellyfin_watched

        service.return_value.sync.return_value = ({}, "")
        push_jellyfin_watched(user_id=self.user.id, account_id=self.second.id)

        self.assertEqual(service.call_args.args[1], self.second)
        self.second.refresh_from_db()
        self.first.refresh_from_db()
        self.assertIsNotNone(self.second.last_sync_at)
        self.assertIsNone(self.first.last_sync_at)

    @patch("integrations.tasks._jellyfin_pull.JellyfinClient")
    def test_a_rejected_key_breaks_only_that_connection(self, client):
        from integrations.jellyfin_client import JellyfinAuthError
        from integrations.tasks._jellyfin_pull import pull_jellyfin_history

        client.return_value.healthcheck.side_effect = JellyfinAuthError("bad key")
        self.second.connection_broken = True
        self.second.save()

        result = pull_jellyfin_history(user_id=self.user.id, account_id=self.second.id)

        self.assertIn("rejected", result)
        self.first.refresh_from_db()
        self.assertFalse(self.first.connection_broken)

    def test_a_call_without_an_account_fans_out_per_connection(self):
        from integrations.tasks._jellyfin_pull import pull_jellyfin_history

        with patch.object(pull_jellyfin_history, "apply_async") as queue:
            pull_jellyfin_history(user_id=self.user.id)

        self.assertEqual(
            sorted(call.kwargs["kwargs"]["account_id"] for call in queue.call_args_list),
            sorted([self.first.id, self.second.id]),
        )

    def test_a_connection_belonging_to_another_user_is_not_run(self):
        from integrations.imports.helpers import MediaImportError
        from integrations.tasks._jellyfin_pull import pull_jellyfin_history

        other = get_user_model().objects.create_user(username="not-mine")

        with self.assertRaises(MediaImportError):
            pull_jellyfin_history(user_id=other.id, account_id=self.first.id)

    def test_scheduled_pull_for_a_deleted_connection_fails_loudly_not_silently(self):
        from integrations.imports.helpers import MediaImportError
        from integrations.tasks._jellyfin_pull import pull_jellyfin_history

        gone = self.second.id
        self.second.delete()

        with self.assertRaises(MediaImportError):
            pull_jellyfin_history(user_id=self.user.id, account_id=gone)

    def test_manual_import_goes_to_the_named_connection(self):
        from integrations.imports.jellyfin_playback_reporting import importer

        with patch(
            "integrations.imports.jellyfin_playback_reporting."
            "JellyfinPlaybackReportingImporter",
        ) as importer_class:
            importer_class.return_value.import_data.return_value = ({}, "")
            importer(b"", self.user, "new", account_id=self.second.id)
            self.assertEqual(importer_class.call_args.args[1], self.second)
            importer(b"", self.user, "new")
            # Two connections and no id: ambiguous, so none is chosen.
            self.assertIsNone(importer_class.call_args.args[1])


class PlaybackReportingIdentityTests(TestCase):
    """Equal rowids on two servers must not look like the same play."""

    def setUp(self):
        self.row = PlaybackReportingRow(
            date_created=__import__("datetime").datetime(2024, 1, 1),
            user_id="u",
            item_id="i",
            item_type="Movie",
            item_name="Name",
            playback_method="DirectPlay",
            client_name="Web",
            device_name="Dev",
            play_duration=60,
            line_number=1,
        )

    def test_unscoped_identity_is_unchanged_for_the_first_connection(self):
        self.assertEqual(
            self.row.source_identity(rowid=5),
            self.row.source_identity(rowid=5, scope=""),
        )

    def test_scoped_identities_differ_between_servers(self):
        self.assertNotEqual(
            self.row.source_identity(rowid=5, scope="server-2"),
            self.row.source_identity(rowid=5, scope="server-3"),
        )
        self.assertNotEqual(
            self.row.source_identity(rowid=5, scope="server-2"),
            self.row.source_identity(rowid=5),
        )


class WebhookAttributionTests(TestCase):
    """An inbound event is attributed by its server id, never guessed."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="multi-jf-hooks")

    def test_one_connection_takes_every_event(self):
        only = _account(self.user, 1)

        self.assertEqual(attribute_connection(self.user, {}), (only, False))
        self.assertEqual(
            attribute_connection(self.user, {"ServerId": "server-1"}),
            (only, False),
        )

    def test_server_id_picks_the_matching_connection(self):
        _account(self.user, 1)
        second = _account(self.user, 2)

        self.assertEqual(
            attribute_connection(self.user, {"ServerId": "server-2"}),
            (second, False),
        )

    def test_an_unmatched_or_missing_server_is_ambiguous_with_several(self):
        _account(self.user, 1)
        _account(self.user, 2)

        self.assertEqual(attribute_connection(self.user, {}), (None, True))
        self.assertEqual(
            attribute_connection(self.user, {"ServerId": "elsewhere"}),
            (None, True),
        )

    def test_no_connection_is_not_ambiguous(self):
        self.assertEqual(attribute_connection(self.user, {}), (None, False))

    def test_oldest_connection_keeps_the_unscoped_keys(self):
        first = _account(self.user, 1)
        second = _account(self.user, 2)

        self.assertEqual(source_instance_ids(self.user, first), (None, 0))
        self.assertEqual(
            source_instance_ids(self.user, second),
            (second.id, second.id),
        )

    def test_profiles_on_one_server_are_told_apart_by_user_id(self):
        first = _account(self.user, 1, server_id="shared")
        second = _account(self.user, 2, server_id="shared")

        self.assertEqual(
            attribute_connection(
                self.user,
                {"ServerId": "shared", "UserId": "JF-USER-2"},
            ),
            (second, False),
        )
        self.assertEqual(
            attribute_connection(
                self.user,
                {"ServerId": "shared", "UserId": "jf-user-1"},
            ),
            (first, False),
        )

    def test_profiles_on_one_server_without_a_user_are_ambiguous(self):
        _account(self.user, 1, server_id="shared")
        _account(self.user, 2, server_id="shared")

        self.assertEqual(
            attribute_connection(self.user, {"ServerId": "shared"}),
            (None, True),
        )
        self.assertEqual(
            attribute_connection(
                self.user,
                {"ServerId": "shared", "UserId": "someone-else"},
            ),
            (None, True),
        )

    @patch("integrations.tasks._media_imports.push_jellyfin_watched.apply_async")
    def test_instant_push_for_a_shared_server_follows_the_profile(self, push):
        _account(self.user, 1, server_id="shared", instant_push_enabled=False)
        second = _account(self.user, 2, server_id="shared", instant_push_enabled=True)

        _queue_jellyfin_instant_push(
            self.user,
            {"Event": "Stop", "ServerId": "shared", "UserId": "jf-user-2"},
        )
        push.assert_called_once()
        self.assertEqual(push.call_args.kwargs["kwargs"]["account_id"], second.id)

        push.reset_mock()
        _queue_jellyfin_instant_push(
            self.user,
            {"Event": "Stop", "ServerId": "shared"},
        )
        push.assert_not_called()

    def test_disconnecting_the_oldest_hands_its_keys_to_the_next(self):
        first = _account(self.user, 1)
        second = _account(self.user, 2)
        _page(self.user, 0, "movie-first")
        _page(self.user, second.id, "movie-second")

        release_connection_sources(self.user, first)
        first.delete()

        self.assertEqual(source_instance_ids(self.user, second), (None, 0))
        pages = {
            (page.source_instance_id, page.media_id)
            for page in SourcePage.objects.filter(user=self.user)
        }
        self.assertEqual(pages, {(0, "movie-second")})

    def test_disconnecting_a_later_connection_removes_only_its_records(self):
        first = _account(self.user, 1)
        second = _account(self.user, 2)
        _page(self.user, 0, "movie-first")
        _page(self.user, second.id, "movie-second")

        release_connection_sources(self.user, second)
        second.delete()

        self.assertEqual(source_instance_ids(self.user, first), (None, 0))
        pages = {
            (page.source_instance_id, page.media_id)
            for page in SourcePage.objects.filter(user=self.user)
        }
        self.assertEqual(pages, {(0, "movie-first")})

    def test_a_lone_connection_keeps_its_records_when_removed(self):
        only = _account(self.user, 1)
        _page(self.user, 0, "movie-only")

        release_connection_sources(self.user, only)

        self.assertTrue(SourcePage.objects.filter(user=self.user).exists())

    @patch("integrations.tasks._media_imports.push_jellyfin_watched.apply_async")
    def test_instant_push_goes_only_to_the_matching_server(self, push):
        _account(self.user, 1, instant_push_enabled=True)
        second = _account(self.user, 2, instant_push_enabled=True)

        _queue_jellyfin_instant_push(
            self.user,
            {"Event": "Stop", "ServerId": "server-2"},
        )

        push.assert_called_once()
        self.assertEqual(
            push.call_args.kwargs["kwargs"],
            {"user_id": self.user.id, "account_id": second.id},
        )

    @patch("integrations.tasks._media_imports.push_jellyfin_watched.apply_async")
    def test_each_server_debounces_on_its_own(self, push):
        _account(self.user, 1, instant_push_enabled=True)
        _account(self.user, 2, instant_push_enabled=True)

        for server in ("server-1", "server-1", "server-2", "server-2"):
            _queue_jellyfin_instant_push(
                self.user,
                {"Event": "Stop", "ServerId": server},
            )

        self.assertEqual(push.call_count, 2)

    @patch("integrations.tasks._media_imports.push_jellyfin_watched.apply_async")
    def test_an_ambiguous_event_pushes_nowhere(self, push):
        _account(self.user, 1, instant_push_enabled=True)
        _account(self.user, 2, instant_push_enabled=True)

        _queue_jellyfin_instant_push(self.user, {"Event": "Stop"})

        push.assert_not_called()


class AdapterAndLinkTests(TestCase):
    """Bindings and detail links resolve to the right server."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="multi-jf-state")

    def _binding(self, server_id, profile):
        from integrations.state.identity import get_or_create_binding

        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key=server_id,
            profile_key=profile,
        )
        return binding

    def test_binding_resolves_its_own_server(self):
        _account(self.user, 1)
        second = _account(self.user, 2)

        adapter = build_adapter(self._binding("server-2", "jf-user-2"))

        self.assertEqual(adapter.account, second)

    def test_binding_with_no_match_among_several_has_no_adapter(self):
        _account(self.user, 1)
        _account(self.user, 2)

        self.assertIsNone(build_adapter(self._binding("server-9", "jf-user-9")))

    def test_a_single_legacy_connection_still_resolves(self):
        only = _account(self.user, 1)
        only.server_id = ""
        only.save()

        adapter = build_adapter(self._binding("anything", "jf-user-1"))

        self.assertEqual(adapter.account, only)

    def test_source_pages_are_kept_per_server(self):
        from integrations.source_sync import set_source_page

        for instance_id, path in ((0, "web/#/details?id=a"), (7, "web/#/details?id=b")):
            set_source_page(
                user=self.user,
                source="jellyfin",
                provider="tmdb",
                media_type="movie",
                media_id="1",
                path=path,
                source_instance_id=instance_id,
            )

        self.assertEqual(
            SourcePage.objects.filter(user=self.user, source="jellyfin").count(),
            2,
        )


class ConnectionCardPageTests(TestCase):
    """The Sync and Import tabs draw one set of shared cards per connection."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="multi-jf-cards",
            password="pw",
        )
        self.client.force_login(self.user)
        self.first = _account(self.user, 1)
        self.second = _account(self.user, 2)

    def _page(self, tab):
        response = self.client.get(
            reverse("provider_detail", args=["jellyfin"]),
            {"tab": tab},
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_sync_tab_has_a_card_set_per_connection(self):
        html = self._page("sync")

        for account in (self.first, self.second):
            self.assertIn(f'id="form-jellyfin_sync_{account.id}"', html)
            self.assertIn(f'id="form-jellyfin_push_{account.id}"', html)
            self.assertIn(
                f'<input type="hidden" name="account_id" value="{account.id}">',
                html,
            )
        self.assertIn("Server 2", html)
        self.assertNotIn("jellyfin-history-", html)

    def test_import_tab_has_history_and_upload_cards_per_connection(self):
        html = self._page("import")

        for account in (self.first, self.second):
            self.assertIn(f'id="form-jellyfin_history_{account.id}"', html)
            self.assertIn(f'id="form-jellyfin_pull_{account.id}"', html)
            self.assertIn(f'id="file-import-jellyfin-pr-import-{account.id}"', html)
        self.assertEqual(html.count('name="playback_reporting_file"'), 2)

    def test_connection_tab_does_not_draw_the_per_connection_cards(self):
        html = self._page("connection")

        self.assertNotIn("form-jellyfin_sync_", html)
        self.assertNotIn("jellyfin-pr-import-", html)


class ProviderStateTests(TestCase):
    """The Providers overview reads every connection, not just one."""

    def _state(self, user):
        from users.provider_catalog import catalog, provider_state

        entry = next(row for row in catalog() if row["slug"] == "jellyfin")
        return provider_state(entry, user)

    def test_saved_connections_count_as_a_saved_account(self):
        user = get_user_model().objects.create_user(username="state-jf")
        self.assertFalse(self._state(user)["account_saved"])

        _account(user, 1)

        state = self._state(user)
        self.assertTrue(state["account_saved"])
        self.assertFalse(state["attention"])

    def test_one_broken_connection_needs_attention(self):
        user = get_user_model().objects.create_user(username="state-jf-broken")
        _account(user, 1)
        _account(user, 2, connection_broken=True)

        self.assertTrue(self._state(user)["attention"])


class MigrationTests(TestCase):
    """The data step points each existing schedule at its account."""

    def test_existing_user_schedules_gain_the_account_id(self):
        migration = importlib.import_module(
            "integrations.migrations.0066_jellyfin_multiple_connections",
        )
        user = get_user_model().objects.create_user(username="migrating")
        account = _account(user, 1)
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=240,
            period=IntervalSchedule.MINUTES,
        )
        task = PeriodicTask.objects.create(
            name="legacy pull",
            task=JELLYFIN_PULL_TASK_NAME,
            interval=interval,
            kwargs=json.dumps({"user_id": user.id}),
        )

        migration.scope_schedules_to_account(django_apps, None)

        task.refresh_from_db()
        self.assertEqual(
            json.loads(task.kwargs),
            {"user_id": user.id, "account_id": account.id},
        )
