"""Superuser user-management settings page and JSON actions."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UsersManagementTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="owner",
            email="owner@example.com",
            password="owner-pass-123",
        )
        self.member = User.objects.create_user(
            username="member",
            email="member@example.com",
            password="member-pass-123",
        )

    def _url(self, name, *args):
        return reverse(name, args=args or None)

    def _post(self, name, payload, *args):
        return self.client.post(
            self._url(name, *args),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_test_accounts_are_excluded_from_the_page(self):
        User.objects.create_test_user(username="fixture-only")
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("manage_users"))
        props = response.context["users_management"]

        self.assertNotContains(response, "fixture-only")
        self.assertNotIn(
            "fixture-only",
            [row["username"] for row in props["users"]],
        )
        self.assertContains(response, "member")

    def test_test_accounts_cannot_be_changed_through_the_page_actions(self):
        fixture = User.objects.create_test_user(username="fixture-only")
        self.client.force_login(self.superuser)

        for name, payload in [
            ("update_managed_user", {"isActive": False}),
            ("delete_managed_user", {}),
            ("set_managed_user_password", {"password": "fresh-secret-456"}),
        ]:
            with self.subTest(action=name):
                response = self.client.post(
                    reverse(name, args=[fixture.pk]),
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 404)
        fixture.refresh_from_db()
        self.assertTrue(fixture.is_active)

    def test_page_requires_login(self):
        response = self.client.get(reverse("manage_users"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("account_login"), response["Location"])

    def test_non_superuser_cannot_view_page(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("manage_users"))

        self.assertEqual(response.status_code, 403)

    def test_superuser_sees_every_account(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("manage_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "owner")
        self.assertContains(response, "member")

    def test_page_props_mark_self_and_deletion_rules(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("manage_users"))
        props = response.context["users_management"]
        rows = {row["username"]: row for row in props["users"]}

        self.assertTrue(rows["owner"]["isSelf"])
        self.assertFalse(rows["owner"]["canDelete"])
        self.assertFalse(rows["member"]["isSelf"])
        self.assertTrue(rows["member"]["canDelete"])

    def test_non_superuser_cannot_change_users(self):
        self.client.force_login(self.member)
        attempts = [
            ("create_managed_user", {"username": "new"}, None),
            ("update_managed_user", {"isActive": False}, self.member.pk),
            ("delete_managed_user", {}, self.superuser.pk),
            ("set_managed_user_password", {"password": "new-password-123"}, self.superuser.pk),
        ]

        for name, payload, user_id in attempts:
            with self.subTest(action=name):
                url = reverse(name) if user_id is None else reverse(name, args=[user_id])
                response = self.client.post(
                    url,
                    data=json.dumps(payload),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 403)

    def test_superuser_creates_account(self):
        self.client.force_login(self.superuser)

        response = self._post("create_managed_user", {
            "username": "friend",
            "email": "friend@example.com",
            "password": "friend-pass-123",
        })

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["username"], "friend")
        created = User.objects.get(username="friend")
        self.assertTrue(created.check_password("friend-pass-123"))
        self.assertTrue(created.is_active)

    def test_create_without_password_is_login_disabled(self):
        self.client.force_login(self.superuser)

        response = self._post("create_managed_user", {"username": "invited"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.get(username="invited").has_usable_password())

    def test_create_rejects_duplicate_username(self):
        self.client.force_login(self.superuser)

        response = self._post("create_managed_user", {"username": "member"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["error"])

    def test_create_rejects_invalid_username_and_email(self):
        self.client.force_login(self.superuser)

        invalid_username = self._post(
            "create_managed_user", {"username": "bad name"},
        )
        invalid_email = self._post(
            "create_managed_user", {"username": "valid", "email": "not-an-email"},
        )

        self.assertEqual(invalid_username.status_code, 400)
        self.assertEqual(invalid_email.status_code, 400)

    def test_update_promotes_superuser_and_forces_staff(self):
        self.client.force_login(self.superuser)

        response = self._post(
            "update_managed_user", {"isSuperuser": True}, self.member.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_superuser)
        self.assertTrue(self.member.is_staff)
        self.assertTrue(response.json()["user"]["isSuperuser"])

    def test_demoting_superuser_clears_staff(self):
        peer = User.objects.create_superuser(
            username="peer-owner",
            email="peer@example.com",
            password="peer-pass-123",
        )
        self.client.force_login(self.superuser)

        response = self._post(
            "update_managed_user", {"isSuperuser": False}, peer.pk,
        )

        self.assertEqual(response.status_code, 200)
        peer.refresh_from_db()
        self.assertFalse(peer.is_superuser)
        self.assertFalse(peer.is_staff)

    def test_update_deactivates_member(self):
        self.client.force_login(self.superuser)

        response = self._post(
            "update_managed_user", {"isActive": False}, self.member.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    def test_cannot_deactivate_or_demote_self(self):
        self.client.force_login(self.superuser)

        for payload in [{"isActive": False}, {"isSuperuser": False}]:
            with self.subTest(payload=payload):
                response = self._post(
                    "update_managed_user", payload, self.superuser.pk,
                )
                self.assertEqual(response.status_code, 400)

    def test_deactivating_peer_superuser_is_allowed(self):
        other = User.objects.create_superuser(
            username="second-owner",
            email="second@example.com",
            password="second-pass-123",
        )
        self.client.force_login(other)

        response = self._post(
            "update_managed_user", {"isActive": False}, self.superuser.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.superuser.refresh_from_db()
        self.assertFalse(self.superuser.is_active)
        self.assertTrue(other.is_active)

    def test_superuser_sets_member_password(self):
        self.client.force_login(self.superuser)

        response = self._post(
            "set_managed_user_password",
            {"password": "fresh-secret-456"},
            self.member.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("fresh-secret-456"))

    def test_password_rejects_blank_and_weak_values(self):
        self.client.force_login(self.superuser)

        blank = self._post("set_managed_user_password", {}, self.member.pk)
        weak = self._post(
            "set_managed_user_password", {"password": "123"}, self.member.pk,
        )

        self.assertEqual(blank.status_code, 400)
        self.assertEqual(weak.status_code, 400)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("member-pass-123"))

    def test_superuser_deletes_member(self):
        self.client.force_login(self.superuser)

        response = self._post("delete_managed_user", {}, self.member.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], self.member.pk)
        self.assertFalse(User.objects.filter(pk=self.member.pk).exists())

    def test_cannot_delete_self(self):
        self.client.force_login(self.superuser)

        response = self._post("delete_managed_user", {}, self.superuser.pk)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())

    def test_settings_navigation_shows_users_only_to_superusers(self):
        self.client.force_login(self.member)
        member_page = self.client.get(reverse("account"))
        self.assertNotContains(member_page, reverse("manage_users"))

        self.client.force_login(self.superuser)
        owner_page = self.client.get(reverse("account"))
        self.assertContains(owner_page, reverse("manage_users"))

    def test_superuser_deletes_peer_superuser(self):
        peer = User.objects.create_superuser(
            username="second",
            email="second@example.com",
            password="second-pass-123",
        )
        self.client.force_login(self.superuser)

        response = self._post("delete_managed_user", {}, peer.pk)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=peer.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())

    def test_malformed_json_is_rejected(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("create_managed_user"),
            data="{",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
