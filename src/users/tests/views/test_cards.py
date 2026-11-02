"""Media Cards settings keep shared behavior and per-type drafts separate."""

import json

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class MediaCardsSettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="card-settings", password="test")
        self.client.force_login(self.user)
        self.url = reverse("cards_type", kwargs={"media_type": "tv"})
        self.profile = {
            "version": 1,
            "types": {"tv": {
                "lines": [{"fields": ["release_year", "genres"], "display": "dormant"}],
                "options": {"title": {"overflow": "wrap", "lines": 2, "hover": "stay"}},
            }},
        }

    def test_shared_mobile_action_control_lives_on_media_cards(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        control = soup.select_one('select[name="clickable_media_cards"]')
        self.assertIsNotNone(control)
        self.assertEqual({o["value"] for o in control.select("option")}, {"on", "off"})
        self.assertNotIn('name="clickable_media_cards"', self.client.get(reverse("sidebar")).content.decode())
        self.assertContains(response, "Title overflow")
        self.assertContains(response, "Add to this line")
        self.assertContains(response, "Always show")
        self.assertNotContains(response, 'class="cards-seg"')

    def test_save_updates_mobile_behavior_and_preserves_per_type_options(self):
        response = self.client.post(self.url, {
            "card_metadata": json.dumps(self.profile), "clickable_media_cards": "on",
        })
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertTrue(self.user.clickable_media_cards)
        profile = self.user.card_metadata["types"]["tv"]
        self.assertEqual(profile["lines"], self.profile["types"]["tv"]["lines"])
        self.assertEqual(profile["options"]["title"]["lines"], 2)
        self.assertEqual(profile["options"]["title"]["hover"], "stay")
        self.client.post(self.url, {"card_metadata": json.dumps(self.profile), "clickable_media_cards": "off"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.clickable_media_cards)

    def test_older_card_form_does_not_reset_mobile_behavior(self):
        self.user.clickable_media_cards = True
        self.user.save(update_fields=["clickable_media_cards"])
        self.client.post(self.url, {"card_metadata": json.dumps(self.profile)})
        self.user.refresh_from_db()
        self.assertTrue(self.user.clickable_media_cards)

    def test_saving_sidebar_does_not_reset_mobile_behavior(self):
        self.user.clickable_media_cards = True
        self.user.save(update_fields=["clickable_media_cards"])
        self.client.post(reverse("sidebar"), {"media_types_checkboxes": ["tv"], "show_discover": "on"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.clickable_media_cards)

    def test_preview_applies_touch_behavior_without_saving_it(self):
        response = self.client.post(reverse("cards_preview"), {
            "type": "tv", "draft": self.profile, "clickable_media_cards": True,
        }, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "media-card-hide-overlay")
        self.assertContains(response, "width: 100%; max-width: 16rem")
        self.user.refresh_from_db()
        self.assertFalse(self.user.clickable_media_cards)
        self.assertEqual(self.user.card_metadata, {})

    def test_preview_get_still_works(self):
        self.assertEqual(self.client.get(reverse("cards_preview")).status_code, 200)

    def test_demo_account_cannot_save_card_behavior(self):
        self.user.is_demo = True
        self.user.save(update_fields=["is_demo"])
        self.client.post(self.url, {"card_metadata": json.dumps(self.profile), "clickable_media_cards": "on"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.clickable_media_cards)
        self.assertEqual(self.user.card_metadata, {})
