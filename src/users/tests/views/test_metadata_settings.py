"""Coverage for the Settings > Metadata page."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import InstanceProviderCredential
from app.providers import credentials


@patch("app.providers.credentials._probe", return_value=None)
class MetadataSettingsPageTests(TestCase):
    """Credential probes are stubbed: these tests must not reach a provider."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="member",
            password="12345",
        )
        self.admin = get_user_model().objects.create_superuser(
            username="admin",
            password="12345",
        )

    def tearDown(self):
        cache.clear()

    def test_page_lists_every_registered_provider(self, _probe):
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))

        self.assertEqual(response.status_code, 200)
        for spec in credentials.REGISTRY.values():
            self.assertContains(response, spec.label)

    @override_settings(HARDCOVER_API="env-token")
    def test_an_env_backed_field_renders_locked(self, _probe):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(response, "HARDCOVER_API")
        self.assertContains(response, "Environment")
        self.assertNotContains(response, "env-token")

    @override_settings(HARDCOVER_API="")
    def test_superuser_can_save_and_clear_an_instance_credential(self, _probe):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("save_provider_credential", args=["hardcover"]),
            {"api_key": "stored-token"},
        )
        self.assertEqual(credentials.get("hardcover", "api_key"), "stored-token")

        self.client.post(reverse("clear_provider_credential", args=["hardcover"]))
        self.assertEqual(credentials.get("hardcover", "api_key"), "")

    @override_settings(HARDCOVER_API="")
    def test_saved_instance_credential_is_masked_in_the_settings_page(self, _probe):
        credentials.set_instance("hardcover", {"api_key": "stored-token"})
        self.client.force_login(self.admin)

        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(response, "••••••••oken")
        self.assertNotContains(response, "stored-token")

    @override_settings(HARDCOVER_API="")
    def test_personal_credential_is_not_rendered_in_the_settings_page(self, _probe):
        credentials.set_user("hardcover", self.user, {"api_key": "personal-token"})
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))

        self.assertNotContains(response, 'value="personal-token"')

    @override_settings(HARDCOVER_API="")
    def test_a_normal_user_cannot_write_instance_credentials(self, _probe):
        self.client.force_login(self.user)

        save = self.client.post(
            reverse("save_provider_credential", args=["hardcover"]),
            {"api_key": "stored-token"},
        )
        clear = self.client.post(
            reverse("clear_provider_credential", args=["hardcover"]),
        )

        self.assertEqual(save.status_code, 403)
        self.assertEqual(clear.status_code, 403)
        self.assertFalse(InstanceProviderCredential.objects.exists())

    @override_settings(HARDCOVER_API="env-token")
    def test_an_env_locked_field_cannot_be_overwritten_by_a_post(self, _probe):
        self.client.force_login(self.admin)

        self.client.post(
            reverse("save_provider_credential", args=["hardcover"]),
            {"api_key": "sneaky-token"},
        )

        self.assertFalse(InstanceProviderCredential.objects.exists())

    def test_a_normal_user_can_save_a_personal_key(self, _probe):
        self.client.force_login(self.user)

        self.client.post(
            reverse("save_personal_credential", args=["hardcover"]),
            {"api_key": "my-token"},
        )

        self.assertEqual(
            credentials.get("hardcover", "api_key", user=self.user),
            "my-token",
        )

    def test_an_unknown_provider_slug_is_a_404(self, _probe):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("save_personal_credential", args=["nosuchprovider"]),
            {"api_key": "my-token"},
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(HARDCOVER_API="")
    def test_a_failing_validator_blocks_the_save(self, _probe):
        spec = credentials.REGISTRY["hardcover"]
        patched = {**credentials.REGISTRY}
        patched["hardcover"] = type(spec)(
            **{
                **{f: getattr(spec, f) for f in spec.__slots__},
                "validator": lambda values: "that key was rejected",
            },
        )
        self.client.force_login(self.admin)

        with self.settings():
            original = dict(credentials.REGISTRY)
            credentials.REGISTRY.update(patched)
            try:
                response = self.client.post(
                    reverse("save_provider_credential", args=["hardcover"]),
                    {"api_key": "bad-token"},
                    follow=True,
                )
            finally:
                credentials.REGISTRY.clear()
                credentials.REGISTRY.update(original)

        self.assertContains(response, "that key was rejected")
        self.assertFalse(InstanceProviderCredential.objects.exists())

    def test_a_non_superuser_is_told_how_to_promote_their_account(self, _probe):
        """A silent read-only form is what made this page look broken."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(response, "You are not a superuser")
        self.assertContains(response, "promote_superuser member")

    def test_every_provider_offers_a_personal_key(self, _probe):
        """A 'Shared default' pill reads as an invitation, so it must hold everywhere."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))
        providers = [
            provider
            for group in response.context["credential_groups"]
            for provider in group["providers"]
        ]

        self.assertEqual(len(providers), len(credentials.REGISTRY))
        self.assertTrue(all(provider["user_scope"] for provider in providers))

    def test_groups_split_metadata_from_account_credentials(self, _probe):
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))
        sections = {
            group["key"]: {p["slug"] for p in group["providers"]}
            for group in response.context["credential_groups"]
        }

        self.assertIn("tmdb", sections["metadata"])
        self.assertIn("comicvine", sections["metadata"])
        self.assertIn("steam", sections["accounts"])
        self.assertIn("trakt", sections["accounts"])

    def test_a_superuser_sees_no_promotion_banner(self, _probe):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("metadata_settings"))

        self.assertNotContains(response, "You are not a superuser")
        self.assertNotContains(response, "promote_superuser")

    @patch("users.metadata_views.preflight.in_container", return_value=False)
    def test_a_source_install_is_told_to_run_manage_py(self, _in_container, _probe):
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(response, "python src/manage.py promote_superuser member")
        self.assertNotContains(response, "docker exec")

    @patch.dict("os.environ", {"HOST_CONTAINERNAME": "yamtrack"})
    @patch("users.metadata_views.preflight.in_container", return_value=True)
    def test_a_container_install_is_told_to_use_docker_exec(self, _in_container, _probe):
        """Podman counts too: preflight.in_container checks both markers."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("metadata_settings"))

        self.assertContains(
            response,
            "docker exec -it yamtrack python manage.py promote_superuser member",
        )
        self.assertNotContains(response, "python src/manage.py")

    def test_the_page_leaks_no_template_source(self, _probe):
        """Django's {# #} is single-line only; a multi-line one renders verbatim."""
        self.client.force_login(self.admin)

        page = self.client.get(reverse("metadata_settings")).content.decode()

        self.assertNotIn("{#", page)
        self.assertNotIn("{%", page)
