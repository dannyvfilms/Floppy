# Tests for settings endpoints that the existing fork tests did not
# exercise yet (home-screen list picker, account POST, managed-user password,
# what's-new relay).
from http import HTTPStatus as HTTP  # noqa: N814
from unittest import mock
from unittest.mock import patch

from django.http import JsonResponse

from lists.models import CustomList

from .base import FloppyApiTestCase


class HomeScreenListsTests(FloppyApiTestCase):
    """GET /user/home-screen/lists/."""

    def setUp(self):
        super().setUp()
        # The base fixtures seed user1's "Shared Picks" list, so this test uses
        # names unique to itself.
        self.mine = CustomList.objects.create(
            name="Zephyr Queue",
            owner=self.user1,
        )
        self.theirs = CustomList.objects.create(
            name="Secluded Stash",
            owner=self.user2,
        )

    def test_requires_authentication(self):
        response = self.call_api(
            "get", "api_settings_user_home_screen_lists", headers=self.invalid_auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_lists_list_the_callers_own_lists(self):
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_lists",
            params={"q": "Zephyr"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = response.json()["results"]
        self.assertEqual([row["id"] for row in results], [self.mine.id])
        self.assertEqual(results[0]["name"], "Zephyr Queue")
        self.assertEqual(results[0]["label"], "Zephyr Queue (List)")

    def test_other_users_private_list_is_invisible(self):
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_lists",
            params={"q": "Secluded"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["results"], [])
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_lists",
            params={"q": "Secluded"},
            headers=self.auth_headers2,
        )
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [self.theirs.id]
        )

    def test_query_filters_by_name(self):
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_lists",
            params={"q": "zephyr"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [self.mine.id]
        )
        response = self.call_api(
            "get",
            "api_settings_user_home_screen_lists",
            params={"q": "no-such-list"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.json()["results"], [])


class UserAccountPostTests(FloppyApiTestCase):
    """POST /user/account/ — the native JSON contract of the web account view."""

    def test_requires_authentication(self):
        response = self.call_api(
            "post",
            "api_settings_user_account",
            payload={"username": "whatever"},
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_username_rename_succeeds(self):
        response = self.call_api(
            "post",
            "api_settings_user_account",
            payload={"username": "renamed-user-1"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        body = response.json()
        self.assertTrue(body["ok"])
        self.user1.refresh_from_db()
        self.assertEqual(self.user1.username, "renamed-user-1")
        # Only the caller's own account moves.
        self.user2.refresh_from_db()
        self.assertNotEqual(self.user2.username, "renamed-user-1")

    def test_blank_username_is_refused_without_500(self):
        response = self.call_api(
            "post",
            "api_settings_user_account",
            payload={"username": ""},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        body = response.json()
        self.assertFalse(body["ok"])
        self.user1.refresh_from_db()
        self.assertNotEqual(self.user1.username, "")

    def test_taken_username_is_refused_and_user2_untouched(self):
        response = self.call_api(
            "post",
            "api_settings_user_account",
            payload={"username": self.user2.username},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertFalse(response.json()["ok"])
        self.user2.refresh_from_db()
        self.user1.refresh_from_db()
        self.assertNotEqual(self.user1.username, self.user2.username)


class ManagedUserPasswordTests(FloppyApiTestCase):
    """POST /admin/users/<id>/password/ — superuser-only account writes."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.user1)

    def make_superuser(self):
        self.user1.is_superuser = True
        self.user1.save(update_fields=["is_superuser"])

    def create_member(self):
        created = self.call_api(
            "post",
            "api_settings_managed_users",
            payload={"username": "member-one", "password": ""},
            headers={},
        )
        self.assertEqual(created.status_code, HTTP.OK, created.content)
        return created.json()["user"]["id"]

    def test_requires_authentication(self):
        response = self.call_api(
            "post",
            "api_settings_managed_user_password",
            args=(self.user2.id,),
            payload={"password": "nope"},
            headers=self.invalid_auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_non_superuser_is_forbidden(self):
        response = self.call_api(
            "post",
            "api_settings_managed_user_password",
            args=(self.user2.id,),
            payload={"password": "nope"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)
        self.user2.refresh_from_db()
        self.assertFalse(self.user2.check_password("nope"))

    def test_superuser_sets_member_password(self):
        self.make_superuser()
        member_id = self.create_member()
        response = self.call_api(
            "post",
            "api_settings_managed_user_password",
            args=(member_id,),
            payload={"password": "a-real-new-password"},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.OK, response.content)
        from django.contrib.auth import get_user_model

        member = get_user_model().objects.get(pk=member_id)
        self.assertTrue(member.check_password("a-real-new-password"))

    def test_empty_password_is_refused(self):
        self.make_superuser()
        member_id = self.create_member()
        response = self.call_api(
            "post",
            "api_settings_managed_user_password",
            args=(member_id,),
            payload={"password": ""},
            headers={},
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
        self.assertIn("detail", response.json())


class WhatsNewTests(FloppyApiTestCase):
    """GET /settings/whats-new/ — relays the release-notes JSON."""

    def test_requires_authentication(self):
        response = self.call_api(
            "get", "api_settings_whats_new", headers=self.invalid_auth_headers
        )
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)

    def test_release_notes_are_relayed(self):
        payload = JsonResponse({"releases": [{"version": "1.2.0", "isNew": True}]})
        with mock.patch("users.views.whats_new", return_value=payload):
            response = self.call_api(
                "get", "api_settings_whats_new", headers=self.auth_headers
            )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(
            response.json(), {"releases": [{"version": "1.2.0", "isNew": True}]}
        )
