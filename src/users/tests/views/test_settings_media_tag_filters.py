"""Media type filters and the settings navigation."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from app.providers import credentials
from users.media_tags import MEDIA_TAG_KEYS, MEDIA_TYPE_TAGS
from users.templatetags.user_tags import media_tag_choices, media_tag_list


class MediaTagHelperTests(SimpleTestCase):
    def test_every_provider_has_valid_media_tags(self):
        for spec in credentials.REGISTRY.values():
            with self.subTest(provider=spec.slug):
                self.assertTrue(spec.media_tags)
                self.assertLessEqual(set(spec.media_tags), MEDIA_TAG_KEYS)

    def test_every_media_type_maps_to_a_known_tag(self):
        self.assertLessEqual(set(MEDIA_TYPE_TAGS.values()), MEDIA_TAG_KEYS)

    def test_choices_keep_canonical_order_and_respect_the_limit(self):
        keys = [choice["key"] for choice in media_tag_choices("music screen")]
        self.assertEqual(keys, ["screen", "music"])
        self.assertEqual(len(media_tag_choices()), len(MEDIA_TAG_KEYS))

    def test_tag_list_drops_unknown_keys(self):
        self.assertEqual(
            str(media_tag_list(["games", "x'];alert(1)//"])),
            "['games']",
        )
        self.assertEqual(str(media_tag_list(None)), "[]")


class SettingsPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member",
            password="12345",
        )
        self.client.force_login(self.user)

    def test_connected_applications_is_a_top_level_nav_item(self):
        response = self.client.get(reverse("appearance"))
        html = response.content.decode()
        link = html[html.index(reverse("oauth_applications")) :]
        link = link[: link.index("</a>")]

        self.assertIn("px-2 py-2", link)
        self.assertNotIn("pl-10", link)

    def test_integrations_page_keeps_only_its_jump_chips(self):
        response = self.client.get(reverse("integrations"))

        self.assertContains(response, "Jump to integration:")
        self.assertNotContains(response, 'data-testid="media-tag-filter"')

    def test_metadata_page_filters_by_media_type(self):
        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(response, 'data-testid="media-tag-filter"')
        self.assertContains(response, "Games")
        self.assertContains(response, "matchesTag(")

    def test_import_data_page_uses_the_shared_filter(self):
        response = self.client.get(reverse("import_data"))

        self.assertContains(response, 'data-testid="media-tag-filter"')
        self.assertContains(response, "All Sources")
        self.assertContains(response, "Backups")


class ProviderTagCoverageTests(SimpleTestCase):
    def test_tmdb_is_listed_under_anime_because_anime_can_use_it(self):
        self.assertIn("anime_manga", credentials.REGISTRY["tmdb"].media_tags)
