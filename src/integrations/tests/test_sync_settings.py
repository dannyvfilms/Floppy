"""Direction settings must never approve more than a provider can honour.

The dangerous shape here is a user choosing "Both" on a connection whose
adapter cannot write, and the page then reporting two-way sync. These tests pin
that the approval is intersected with real capability and that the shortfall is
named rather than hidden.
"""

import logging

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources
from integrations.imports.helpers import encrypt
from integrations.models import (
    CAPABILITY_WATCHED_PUSH_PLAYED,
    CAPABILITY_WATCHED_READ,
    CAPABILITY_WATCHED_WRITE_UNPLAYED,
    EmbyAccount,
    JellyfinAccount,
    StateConflict,
    StateConflictReason,
    StateConflictStatus,
    SyncBindingStatus,
    SyncClientKind,
    SyncDirection,
)
from integrations.state import settings_view
from integrations.state.identity import activate_binding, get_or_create_binding


def setUpModule():
    """Silence log noise for this module only."""
    logging.disable(logging.DEBUG)


def tearDownModule():
    """Restore logging so other modules' assertLogs still see records."""
    logging.disable(logging.NOTSET)


class DirectionSettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw",
        )
        self.client.force_login(self.user)
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jf.example",
            api_key=encrypt("secret"),
            jellyfin_user_id="jf-user",
        )
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="jf-user",
        )

    def _post(self, direction):
        return self.client.post(
            reverse("sync_direction_settings"),
            {"binding_id": self.binding.pk, "direction": direction},
        )

    def test_both_grants_both_directions_on_a_capable_provider(self):
        self._post(settings_view.DIRECTION_BOTH)

        self.binding.refresh_from_db()
        self.assertEqual(
            sorted(self.binding.approved_directions),
            [SyncDirection.INBOUND.value, SyncDirection.OUTBOUND.value],
        )
        self.assertIn(CAPABILITY_WATCHED_PUSH_PLAYED, self.binding.approved_capabilities)

    def test_inbound_grants_no_outbound_capability(self):
        self._post(settings_view.DIRECTION_INBOUND)

        self.binding.refresh_from_db()
        self.assertEqual(
            self.binding.approved_directions,
            [SyncDirection.INBOUND.value],
        )
        self.assertNotIn(
            CAPABILITY_WATCHED_PUSH_PLAYED,
            self.binding.approved_capabilities,
        )

    def test_off_deactivates_without_discarding_nothing_else(self):
        self._post(settings_view.DIRECTION_BOTH)

        self._post(settings_view.DIRECTION_OFF)

        self.binding.refresh_from_db()
        self.assertEqual(self.binding.status, SyncBindingStatus.DISABLED.value)
        self.assertFalse(self.binding.is_operational())

    def test_switching_from_both_to_inbound_revokes_the_write(self):
        self._post(settings_view.DIRECTION_BOTH)
        self._post(settings_view.DIRECTION_INBOUND)

        self.binding.refresh_from_db()
        self.assertNotIn(
            CAPABILITY_WATCHED_PUSH_PLAYED,
            self.binding.approved_capabilities,
        )

    def test_another_users_binding_cannot_be_changed(self):
        other = get_user_model().objects.create_user(
            username="other",
            password="pw",
        )
        self.client.force_login(other)

        self._post(settings_view.DIRECTION_BOTH)

        self.binding.refresh_from_db()
        self.assertEqual(self.binding.status, SyncBindingStatus.PENDING.value)

    def test_the_pause_switch_keeps_approvals(self):
        self._post(settings_view.DIRECTION_BOTH)

        self.client.post(
            reverse("sync_kill_switch"),
            {"binding_id": self.binding.pk, "kill_switch": "on"},
        )

        self.binding.refresh_from_db()
        self.assertTrue(self.binding.kill_switch)
        self.assertFalse(self.binding.is_operational())
        self.assertIn(
            CAPABILITY_WATCHED_PUSH_PLAYED,
            self.binding.approved_capabilities,
            "pausing must not discard what the user approved",
        )


class ReadOnlyProviderTests(TestCase):
    """Choosing 'Both' on a read-only provider must not claim it writes."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw",
        )
        self.client.force_login(self.user)
        EmbyAccount.objects.create(
            user=self.user,
            base_url="https://emby.example",
            api_key=encrypt("secret"),
            emby_user_id="emby-user",
        )
        self.binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.EMBY.value,
            instance_key="s",
            profile_key="emby-user",
        )

    def test_both_grants_only_what_the_adapter_supports(self):
        self.client.post(
            reverse("sync_direction_settings"),
            {"binding_id": self.binding.pk, "direction": settings_view.DIRECTION_BOTH},
        )

        self.binding.refresh_from_db()
        self.assertEqual(
            self.binding.approved_capabilities,
            [CAPABILITY_WATCHED_READ],
        )
        self.assertEqual(
            self.binding.approved_directions,
            [SyncDirection.INBOUND.value],
            "an outbound direction must not be recorded without a write",
        )

    def test_the_shortfall_is_reported_to_the_user(self):
        response = self.client.post(
            reverse("sync_direction_settings"),
            {"binding_id": self.binding.pk, "direction": settings_view.DIRECTION_BOTH},
            follow=True,
        )

        messages = [str(message) for message in response.context["messages"]]
        self.assertTrue(
            any("unavailable" in message for message in messages),
            f"expected a capability-limitation message, got {messages}",
        )


class ViewModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")

    def test_an_approved_but_unsupported_capability_reads_as_unavailable(self):
        """The difference between 'off' and 'unavailable' is the user's choice.

        Only one of the two is something they decided, and conflating them is
        how a page ends up claiming a direction works.
        """
        EmbyAccount.objects.create(
            user=self.user,
            base_url="https://emby.example",
            api_key=encrypt("secret"),
            emby_user_id="u",
        )
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.EMBY.value,
            instance_key="s",
            profile_key="u",
        )
        # Approve a capability the adapter does not have, as a migration or an
        # older release could have left behind.
        activate_binding(
            binding,
            capabilities=[CAPABILITY_WATCHED_READ, CAPABILITY_WATCHED_WRITE_UNPLAYED],
            directions=[SyncDirection.INBOUND.value],
        )

        rows = settings_view.binding_rows(self.user)
        by_code = {row["code"]: row for row in rows[0]["capability_rows"]}

        self.assertTrue(by_code[CAPABILITY_WATCHED_WRITE_UNPLAYED]["unavailable"])
        self.assertFalse(by_code[CAPABILITY_WATCHED_READ]["unavailable"])

    def test_direction_is_derived_from_the_approved_directions(self):
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        self.assertEqual(
            settings_view.current_direction(binding),
            settings_view.DIRECTION_OFF,
        )

        binding.approved_directions = [
            SyncDirection.INBOUND.value,
            SyncDirection.OUTBOUND.value,
        ]
        self.assertEqual(
            settings_view.current_direction(binding),
            settings_view.DIRECTION_BOTH,
        )


class ConflictResolutionViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="pw",
        )
        self.client.force_login(self.user)
        self.item, _ = Item.objects.get_or_create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            defaults={"title": "The Matrix"},
        )
        binding, _ = get_or_create_binding(
            self.user,
            SyncClientKind.JELLYFIN.value,
            instance_key="s",
            profile_key="u",
        )
        self.conflict = StateConflict.objects.create(
            user=self.user,
            item=self.item,
            binding=binding,
            reason=StateConflictReason.DIVERGENT_WATCHED.value,
            local_snapshot={"watched": True},
            remote_snapshot={"watched": False},
        )

    def test_resolving_closes_the_conflict(self):
        self.client.post(
            reverse("sync_resolve_conflict"),
            {"conflict_id": self.conflict.pk, "watched": "false"},
        )

        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, StateConflictStatus.RESOLVED.value)

    def test_another_users_conflict_is_untouched(self):
        other = get_user_model().objects.create_user(
            username="other",
            password="pw",
        )
        self.client.force_login(other)

        self.client.post(
            reverse("sync_resolve_conflict"),
            {"conflict_id": self.conflict.pk, "watched": "false"},
        )

        self.conflict.refresh_from_db()
        self.assertEqual(self.conflict.status, StateConflictStatus.OPEN.value)
