"""Named, scoped API token lifecycle in the integrations settings page."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from integrations.models import (
    DEFAULT_INTEGRATION_SCOPES,
    IntegrationEventReceipt,
    IntegrationToken,
)


class IntegrationTokenLifecycleTests(TestCase):
    """Create, display once, list, revoke, and delete."""

    def setUp(self):
        """Log a user in."""
        self.user = get_user_model().objects.create_user(
            username="tokenuser",
            password="testpass123",
        )
        self.other = get_user_model().objects.create_user(
            username="otheruser",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def create(self, **overrides):
        """POST the create form with sensible defaults."""
        payload = {
            "name": "Nuvio living room",
            "scopes": ["progress:read", "progress:write"],
        }
        payload.update(overrides)
        return self.client.post(
            reverse("create_integration_token"),
            payload,
            follow=True,
        )

    def test_create_mints_a_token_with_the_selected_scopes(self):
        """The token is created with exactly the scopes that were ticked."""
        self.create()

        token = IntegrationToken.objects.get(user=self.user)
        self.assertEqual(token.name, "Nuvio living room")
        self.assertEqual(token.scopes, ["progress:read", "progress:write"])
        self.assertIsNone(token.expires_at)

    def test_secret_is_shown_once_and_not_again(self):
        """The raw secret appears on the redirect and never on a later load."""
        response = self.create()
        secret = response.context["new_integration_token"]["secret"]
        self.assertTrue(secret.startswith("flp_"))
        self.assertContains(response, secret)

        again = self.client.get(reverse("integrations"))
        self.assertIsNone(again.context["new_integration_token"])
        self.assertNotContains(again, secret)

    def test_secret_is_never_stored(self):
        """Only the digest is persisted."""
        response = self.create()
        secret = response.context["new_integration_token"]["secret"]

        token = IntegrationToken.objects.get(user=self.user)
        stored = [str(value) for value in token.__dict__.values()]
        self.assertNotIn(secret, stored)

    def test_expiry_is_applied_in_days(self):
        """A chosen expiry lands in the future by that many days."""
        self.create(expires_in_days="30")

        token = IntegrationToken.objects.get(user=self.user)
        self.assertIsNotNone(token.expires_at)
        expected = timezone.now() + timedelta(days=30)
        self.assertLess(abs((token.expires_at - expected).total_seconds()), 60)

    def test_unknown_scopes_are_dropped(self):
        """A forged scope name cannot be stored on the token."""
        self.create(scopes=["progress:read", "not:a:scope"])

        token = IntegrationToken.objects.get(user=self.user)
        self.assertEqual(token.scopes, ["progress:read"])

    def test_a_token_needs_a_name(self):
        """An unnamed token is refused, not silently created."""
        response = self.create(name="   ")

        self.assertFalse(IntegrationToken.objects.exists())
        self.assertContains(response, "Give the token a name")

    def test_a_token_needs_at_least_one_scope(self):
        """A token with no permissions would be useless and is refused."""
        response = self.create(scopes=[])

        self.assertFalse(IntegrationToken.objects.exists())
        self.assertContains(response, "Select at least one permission")

    def test_negative_expiry_is_refused(self):
        """An expiry in the past would create a dead token."""
        response = self.create(expires_in_days="-5")

        self.assertFalse(IntegrationToken.objects.exists())
        self.assertContains(response, "at least one day")

    def test_listing_shows_prefix_but_not_the_secret(self):
        """The list identifies a token by prefix only."""
        self.create()
        token = IntegrationToken.objects.get(user=self.user)

        response = self.client.get(reverse("integrations"))
        self.assertContains(response, token.token_prefix)
        self.assertContains(response, "Nuvio living room")

    def test_revoke_marks_the_token_revoked(self):
        """Revoking moves the token from the active list to revoked tokens."""
        self.create()
        token = IntegrationToken.objects.get(user=self.user)

        response = self.client.post(
            reverse("revoke_integration_token", args=[token.id]),
            follow=True,
        )

        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertContains(response, "Revoked tokens")
        self.assertContains(response, token.token_prefix)
        self.assertContains(
            response,
            reverse("delete_integration_token", args=[token.id]),
        )

    def test_cannot_revoke_another_users_token(self):
        """Token ids are not a cross-user handle."""
        token, _ = IntegrationToken.generate(user=self.other, name="theirs")

        response = self.client.post(
            reverse("revoke_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 404)
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)

    def test_another_users_tokens_are_not_listed(self):
        """The page shows only the logged-in user's tokens."""
        IntegrationToken.generate(user=self.other, name="theirs")

        response = self.client.get(reverse("integrations"))

        self.assertNotContains(response, "theirs")

    def test_oauth_access_tokens_are_not_listed_as_app_tokens(self):
        """OAuth credentials use Connected Applications, not the manual token panel."""
        IntegrationToken.generate(
            user=self.user,
            name="Living room OAuth",
            client_identifier="flp_oauth_test-client",
        )

        response = self.client.get(reverse("integrations"))

        self.assertNotContains(response, "Living room OAuth")

    def test_create_requires_post(self):
        """A GET must not mint a credential."""
        response = self.client.get(reverse("create_integration_token"))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(IntegrationToken.objects.exists())

    def test_scope_choices_are_offered_with_the_tracking_preset(self):
        """The form offers the vocabulary and pre-selects the tracking preset."""
        response = self.client.get(reverse("integrations"))

        values = [
            choice["value"] for choice in response.context["integration_scope_choices"]
        ]
        self.assertIn("scrobble:write", values)
        self.assertIn("lists:write", values)
        for scope in DEFAULT_INTEGRATION_SCOPES:
            self.assertIn(scope, response.context["integration_tracking_preset_json"])

    def test_expired_token_is_listed_as_expired(self):
        """An expired token stays visible so the user can see why an app broke."""
        token, _ = IntegrationToken.generate(
            user=self.user,
            name="Old tablet",
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertTrue(token.is_expired())

        response = self.client.get(reverse("integrations"))

        self.assertContains(response, "Old tablet")
        self.assertContains(response, "Expired")

    def test_a_live_token_is_not_marked_expired(self):
        """A token with a future expiry is not flagged."""
        token, _ = IntegrationToken.generate(
            user=self.user,
            name="Living room",
            expires_at=timezone.now() + timedelta(days=30),
        )

        self.assertFalse(token.is_expired())
        self.assertTrue(token.is_valid())

    def test_revoked_tokens_move_to_the_revoked_section(self):
        """A revoked token remains manageable but is no longer offered for use."""
        token, _ = IntegrationToken.generate(user=self.user, name="Retired")
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

        response = self.client.get(reverse("integrations"))

        self.assertContains(response, "Revoked tokens")
        self.assertContains(response, "Retired")
        self.assertContains(
            response,
            reverse("delete_integration_token", args=[token.id]),
        )

    def test_revoking_an_already_revoked_token_is_a_404(self):
        """A stale revoke button does not resurrect or double-revoke."""
        token, _ = IntegrationToken.generate(user=self.user, name="Retired")
        revoked_at = timezone.now()
        token.revoked_at = revoked_at
        token.save(update_fields=["revoked_at"])

        response = self.client.post(
            reverse("revoke_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 404)
        token.refresh_from_db()
        self.assertEqual(token.revoked_at, revoked_at)

    def test_delete_removes_a_revoked_token_and_preserves_event_receipts(self):
        """Permanent cleanup keeps idempotency history while dropping the credential."""
        token, _ = IntegrationToken.generate(user=self.user, name="Retired")
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        receipt = IntegrationEventReceipt.objects.create(
            token=token,
            user=self.user,
            client_event_id="event-1",
            payload_digest="a" * 64,
            response_body={"ok": True},
        )

        response = self.client.post(
            reverse("delete_integration_token", args=[token.id]),
        )

        self.assertRedirects(response, reverse("integrations"))
        self.assertFalse(IntegrationToken.objects.filter(pk=token.id).exists())
        receipt.refresh_from_db()
        self.assertIsNone(receipt.token_id)

    def test_cannot_delete_an_active_token(self):
        """Deletion cannot bypass the revoke-first security boundary."""
        token, _ = IntegrationToken.generate(user=self.user, name="Still active")

        response = self.client.post(
            reverse("delete_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(IntegrationToken.objects.filter(pk=token.id).exists())

    def test_cannot_delete_another_users_revoked_token(self):
        """A revoked token id is still not a cross-user delete handle."""
        token, _ = IntegrationToken.generate(user=self.other, name="theirs")
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

        response = self.client.post(
            reverse("delete_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(IntegrationToken.objects.filter(pk=token.id).exists())

    def test_cannot_delete_an_oauth_access_token_from_app_tokens(self):
        """OAuth access-token cleanup belongs to the Connected Applications flow."""
        token, _ = IntegrationToken.generate(
            user=self.user,
            name="OAuth access",
            client_identifier="flp_oauth_test-client",
        )
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

        response = self.client.post(
            reverse("delete_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(IntegrationToken.objects.filter(pk=token.id).exists())

    def test_delete_requires_post(self):
        """A GET must never permanently remove a credential record."""
        token, _ = IntegrationToken.generate(user=self.user, name="Retired")
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

        response = self.client.get(
            reverse("delete_integration_token", args=[token.id]),
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(IntegrationToken.objects.filter(pk=token.id).exists())
