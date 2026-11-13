import json

from django.test import TestCase
from django.urls import reverse

from users.models import User


class SidebarPinsTests(TestCase):
    """Sidebar pins belong to the account, not the browser."""

    def setUp(self):
        self.user = User.objects.create_user(username="pins", password="pw")
        self.client.login(username="pins", password="pw")
        self.url = reverse("sidebar_pins")

    def post(self, data):
        return self.client.post(self.url, json.dumps(data), content_type="application/json")

    def test_saves_and_renders_pins_for_every_browser(self):
        pins = {"nav": ["calendar"], "lists": [{"id": "7", "name": "Faves", "url": "/lists/7"}]}
        self.assertEqual(self.post(pins).status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.sidebar_pins, pins)

        other_browser = self.client_class()
        other_browser.login(username="pins", password="pw")
        html = other_browser.get(reverse("home")).content.decode()
        self.assertIn('id="sidebar-pins-data"', html)
        self.assertIn("Faves", html)

    def test_rejects_unsafe_and_unknown_entries(self):
        response = self.post({
            "nav": ["calendar", "bogus", "calendar"],
            "lists": [
                {"id": "1", "name": "x", "url": "javascript:alert(1)"},
                {"id": "2", "name": "x", "url": "//evil.example"},
                {"id": "3", "name": "ok", "url": "/lists/3"},
                "junk",
            ],
        })
        self.assertEqual(
            response.json(),
            {"nav": ["calendar"], "lists": [{"id": "3", "name": "ok", "url": "/lists/3"}]},
        )

    def test_bad_json_and_anonymous(self):
        self.assertEqual(
            self.client.post(self.url, "{", content_type="application/json").status_code, 400,
        )
        self.client.logout()
        self.assertEqual(self.post({}).status_code, 302)
