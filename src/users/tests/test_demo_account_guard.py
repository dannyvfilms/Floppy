"""The public demo login must not be able to lock other visitors out."""

import json

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import get_resolver, reverse

from app.middleware import DemoAccountGuardMiddleware


class DemoAccountGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.demo = get_user_model().objects.create_user(
            username="demo", password="demodemo", is_demo=True
        )

    def test_every_blocked_route_exists(self):
        """A renamed route would silently drop out of the guard."""
        names = {key for key in get_resolver().reverse_dict if isinstance(key, str)}
        self.assertEqual(DemoAccountGuardMiddleware.BLOCKED_ROUTES - names, set())

    def test_demo_cannot_attach_an_authenticator(self):
        self.client.force_login(self.demo)
        secret = self.demo.get_or_create_authenticator_secret()

        response = self.client.post(
            reverse("account"),
            {
                "action": "enable_authenticator",
                "current_password": "demodemo",
                "authenticator_code": pyotp.TOTP(secret).now(),
                "code": pyotp.TOTP(secret).now(),
            },
        )

        self.assertRedirects(response, reverse("account"))
        self.demo.refresh_from_db()
        self.assertFalse(self.demo.authenticator_enabled)
        self.assertFalse(self.demo.recovery_codes.exists())

    def test_htmx_refusal_is_a_toast_not_a_redirect(self):
        self.client.force_login(self.demo)

        response = self.client.post(reverse("regenerate_token"), HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 403)
        toast = json.loads(response["HX-Trigger"])["showToast"]
        self.assertEqual(toast["message"], DemoAccountGuardMiddleware.MESSAGE)

    def test_demo_password_cannot_be_reset_with_an_authenticator(self):
        secret = pyotp.random_base32()
        self.demo.authenticator_secret = secret
        self.demo.authenticator_enabled = True
        self.demo.save()

        self.client.post(
            reverse("password_recover"),
            {
                "username": "demo",
                "authenticator_code": pyotp.TOTP(secret).now(),
                "new_password1": "taken-over-123",
                "new_password2": "taken-over-123",
            },
        )

        self.demo.refresh_from_db()
        self.assertTrue(self.demo.check_password("demodemo"))

    def test_demo_cannot_rotate_the_api_token(self):
        token = self.demo.token

        response = self.client.post(
            reverse("api_user_token_regenerate"), HTTP_X_API_KEY=token
        )

        self.assertEqual(response.status_code, 403)
        self.demo.refresh_from_db()
        self.assertEqual(self.demo.token, token)

    def test_regular_users_are_not_affected(self):
        user = get_user_model().objects.create_user(
            username="real", password="pw-12345"
        )
        self.client.force_login(user)
        token = user.token

        self.client.post(reverse("regenerate_token"))

        user.refresh_from_db()
        self.assertNotEqual(user.token, token)
