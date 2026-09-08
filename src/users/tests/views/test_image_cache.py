from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app import image_cache
from app.models import ApplicationSettings


class ImageCacheSettingsTests(TestCase):
    """Verify the Advanced page ownership and persistence rules."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="image-cache-user",
            password="test-pass-123",
        )
        self.admin = get_user_model().objects.create_superuser(
            username="image-cache-admin",
            password="test-pass-123",
            email="admin@example.com",
        )
        image_cache.set_enabled(False)

    def tearDown(self):
        cache.delete(image_cache.SETTING_CACHE_KEY)

    def test_normal_user_can_view_but_cannot_mutate_or_clear(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("advanced"))
        self.assertFalse(response.context["image_caching_enabled"])
        self.assertContains(response, "Only a superuser can change")

        self.assertEqual(
            self.client.post(
                reverse("update_image_cache"),
                {"image_caching_enabled": "1"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.post(reverse("clear_image_cache")).status_code, 403)
        self.assertFalse(ApplicationSettings.objects.get(pk=1).image_caching_enabled)

    def test_superuser_toggle_persists_and_clear_is_superuser_only(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("update_image_cache"),
            {"image_caching_enabled": "1"},
        )
        self.assertRedirects(response, reverse("advanced"))
        self.assertTrue(ApplicationSettings.objects.get(pk=1).image_caching_enabled)
        response = self.client.get(reverse("advanced"))
        self.assertContains(response, "Clear Image Cache")
        soup = BeautifulSoup(response.content, "html.parser")
        clear_form = soup.find("form", action=reverse("clear_image_cache"))
        self.assertIsNotNone(clear_form)
        self.assertEqual(clear_form["method"], "post")
        self.assertEqual(
            clear_form["onsubmit"],
            "return window.confirm(gettext('Clear all cached external images? "
            "They will be downloaded again if caching remains enabled.'));",
        )

