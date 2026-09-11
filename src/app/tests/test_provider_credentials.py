"""Coverage for the metadata provider credential registry and resolver."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import InstanceProviderCredential, UserProviderCredential
from app.providers import credentials
from integrations.imports.helpers import decrypt


class ProviderCredentialPrecedenceTests(TestCase):
    """The resolution chain: user, then env, then instance, then shared default."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="credential-user",
            password="12345",
        )

    def tearDown(self):
        cache.clear()

    @override_settings(HARDCOVER_API="")
    def test_unset_provider_resolves_to_nothing(self):
        self.assertEqual(credentials.get("hardcover", "api_key"), "")
        self.assertFalse(credentials.is_configured("hardcover"))
        self.assertIsNone(credentials.source_of("hardcover", "api_key"))

    @override_settings(HARDCOVER_API="")
    def test_instance_value_is_used_when_env_is_empty(self):
        credentials.set_instance("hardcover", {"api_key": "instance-token"})

        self.assertEqual(credentials.get("hardcover", "api_key"), "instance-token")
        self.assertTrue(credentials.is_configured("hardcover"))
        self.assertEqual(
            credentials.source_of("hardcover", "api_key"),
            credentials.SOURCE_DB,
        )

    @override_settings(HARDCOVER_API="env-token")
    def test_env_wins_over_a_stored_instance_value(self):
        credentials.set_instance("hardcover", {"api_key": "instance-token"})

        self.assertEqual(credentials.get("hardcover", "api_key"), "env-token")
        self.assertEqual(
            credentials.source_of("hardcover", "api_key"),
            credentials.SOURCE_ENV,
        )

    @override_settings(HARDCOVER_API="env-token")
    def test_personal_key_wins_over_env(self):
        credentials.set_user("hardcover", self.user, {"api_key": "personal-token"})

        self.assertEqual(
            credentials.get("hardcover", "api_key", user=self.user),
            "personal-token",
        )
        self.assertEqual(
            credentials.source_of("hardcover", "api_key", self.user),
            credentials.SOURCE_USER,
        )
        # Another member is unaffected.
        self.assertEqual(credentials.get("hardcover", "api_key"), "env-token")

    def test_shared_default_is_reported_as_a_default_not_as_env(self):
        """A bundled token must stay overridable from the UI."""
        from django.conf import settings

        self.assertEqual(
            credentials.source_of("tmdb", "api_key"),
            credentials.SOURCE_DEFAULT,
        )
        self.assertEqual(
            credentials.get("tmdb", "api_key"),
            settings.SHARED_DEFAULT_CREDENTIALS["TMDB_API"],
        )

    def test_shared_defaults_never_include_private_secret_fields(self):
        from django.conf import settings

        self.assertNotIn("IGDB_SECRET", settings.SHARED_DEFAULT_CREDENTIALS)
        self.assertNotIn("SIMKL_SECRET", settings.SHARED_DEFAULT_CREDENTIALS)

    @override_settings(HARDCOVER_API="")
    def test_instance_and_personal_values_are_encrypted_at_rest(self):
        credentials.set_instance("hardcover", {"api_key": "instance-token"})
        credentials.set_user("hardcover", self.user, {"api_key": "personal-token"})

        instance_value = InstanceProviderCredential.objects.get(
            provider="hardcover",
            field="api_key",
        ).value
        personal_value = UserProviderCredential.objects.get(
            provider="hardcover",
            field="api_key",
        ).value

        self.assertNotEqual(instance_value, "instance-token")
        self.assertNotEqual(personal_value, "personal-token")
        self.assertEqual(decrypt(instance_value), "instance-token")
        self.assertEqual(decrypt(personal_value), "personal-token")

    def test_instance_value_beats_the_shared_default(self):
        credentials.set_instance("tmdb", {"api_key": "my-own-tmdb-key"})

        self.assertEqual(credentials.get("tmdb", "api_key"), "my-own-tmdb-key")
        self.assertEqual(
            credentials.source_of("tmdb", "api_key"),
            credentials.SOURCE_DB,
        )

    @override_settings(TMDB_API="operator-supplied")
    def test_env_override_of_a_shared_default_reads_as_env(self):
        self.assertEqual(
            credentials.source_of("tmdb", "api_key"),
            credentials.SOURCE_ENV,
        )

    @override_settings(TVDB_API_KEY="", TVDB_PIN="")
    def test_optional_fields_do_not_block_is_configured(self):
        credentials.set_instance("tvdb", {"api_key": "tvdb-key", "pin": ""})

        self.assertTrue(credentials.is_configured("tvdb"))
        self.assertEqual(credentials.get("tvdb", "pin"), "")

    @override_settings(HARDCOVER_API="")
    def test_saving_a_blank_value_clears_the_stored_credential(self):
        credentials.set_instance("hardcover", {"api_key": "instance-token"})
        credentials.set_instance("hardcover", {"api_key": ""})

        self.assertEqual(credentials.get("hardcover", "api_key"), "")
        self.assertFalse(
            InstanceProviderCredential.objects.filter(provider="hardcover").exists(),
        )

    @override_settings(TVDB_API_KEY="", TVDB_PIN="")
    def test_clear_instance_removes_every_field(self):
        credentials.set_instance("tvdb", {"api_key": "k", "pin": "p"})
        credentials.clear_instance("tvdb")

        self.assertEqual(credentials.get("tvdb", "api_key"), "")

    @override_settings(HARDCOVER_API="")
    def test_an_undecryptable_value_reads_as_unset(self):
        """Rotating SECRET must degrade to 'not configured', never to a 500."""
        InstanceProviderCredential.objects.create(
            provider="hardcover",
            field="api_key",
            value="not-valid-ciphertext",
        )
        credentials.invalidate_cache()

        self.assertEqual(credentials.get("hardcover", "api_key"), "")
        self.assertFalse(credentials.is_configured("hardcover"))

    def test_unknown_provider_or_field_is_inert(self):
        self.assertEqual(credentials.get("nope", "api_key"), "")
        self.assertEqual(credentials.get("hardcover", "nope"), "")
        self.assertFalse(credentials.is_configured("nope"))

    def test_a_personal_key_works_for_a_shared_default_provider(self):
        """The 'Shared default' pill promises replaceability; keep that true."""
        credentials.set_user("tmdb", self.user, {"api_key": "my-tmdb-key"})

        self.assertTrue(
            UserProviderCredential.objects.filter(provider="tmdb").exists(),
        )
        self.assertEqual(
            credentials.get("tmdb", "api_key", user=self.user),
            "my-tmdb-key",
        )
        # Another member still gets the bundled key.
        self.assertNotEqual(credentials.get("tmdb", "api_key"), "my-tmdb-key")

    def test_an_unknown_provider_still_stores_nothing(self):
        with self.assertRaises(KeyError):
            credentials.set_user("nope", self.user, {"api_key": "x"})

    def test_trakt_personal_credentials_use_the_trakt_account_row(self):
        from integrations.models import TraktAccount

        credentials.set_user(
            "trakt",
            self.user,
            {"client_id": "personal-id", "client_secret": "personal-secret"},
        )

        self.assertTrue(TraktAccount.objects.filter(user=self.user).exists())
        self.assertEqual(
            credentials.get("trakt", "client_id", user=self.user),
            "personal-id",
        )
        self.assertFalse(
            UserProviderCredential.objects.filter(provider="trakt").exists(),
        )


class SharedDefaultMappingTests(TestCase):
    """The mapping must match the values the settings actually ship with."""

    def test_every_mapped_setting_exists_and_is_a_registry_field(self):
        from django.conf import settings

        mapped_settings = {
            field.setting
            for spec in credentials.REGISTRY.values()
            for field in spec.fields
        }
        for name in settings.SHARED_DEFAULT_CREDENTIALS:
            self.assertTrue(hasattr(settings, name), name)
            self.assertIn(name, mapped_settings, name)


class ProviderGatingTests(TestCase):
    """provider_is_enabled now answers from the registry."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(TVDB_API_KEY="")
    def test_tvdb_becomes_available_once_a_key_is_stored(self):
        from app.services import metadata_resolution

        self.assertFalse(metadata_resolution.provider_is_enabled("tvdb"))

        credentials.set_instance("tvdb", {"api_key": "stored"})

        self.assertTrue(metadata_resolution.provider_is_enabled("tvdb"))

    def test_providers_without_credentials_stay_enabled(self):
        from app.services import metadata_resolution

        self.assertTrue(metadata_resolution.provider_is_enabled("openlibrary"))
        self.assertTrue(metadata_resolution.provider_is_enabled("musicbrainz"))
