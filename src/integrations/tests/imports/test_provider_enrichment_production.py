"""Reading and listening importers enrich from providers outside tests.

Each importer turns provider enrichment off when ``settings.TESTING`` is set,
and the importer tests switch it back on by hand. These tests check the switch
itself: built with the flag off, every importer enriches. What enrichment does
is covered by the importer tests that set ``enable_provider_enrichment``.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from integrations.imports import helpers
from integrations.imports.audiobookshelf import AudiobookshelfImporter
from integrations.imports.kavita import KavitaImporter
from integrations.imports.koreader import KoreaderClient, KoreaderImporter
from integrations.imports.storyteller import StorytellerImporter
from integrations.models import (
    AudiobookshelfAccount,
    KavitaAccount,
    KoreaderAccount,
    StorytellerAccount,
)


class ProviderEnrichmentSwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="enrich-user")
        AudiobookshelfAccount.objects.create(
            user=cls.user,
            base_url="https://abs.example.com",
            api_token=helpers.encrypt("token"),
        )
        KoreaderAccount.objects.create(
            user=cls.user,
            server_url="https://kosync.example.com",
            username="reader",
            auth_key=helpers.encrypt(KoreaderClient.password_to_auth_key("secret")),
        )
        StorytellerAccount.objects.create(
            user=cls.user,
            server_url="https://storyteller.example.com",
            auth_token=helpers.encrypt("token"),
        )
        KavitaAccount.objects.create(
            user=cls.user,
            base_url="https://kavita.example.com/",
            api_key=helpers.encrypt("kavita-key"),
        )

    def _importers(self):
        return {
            "audiobookshelf": AudiobookshelfImporter(self.user),
            "koreader": KoreaderImporter(self.user),
            "storyteller": StorytellerImporter(self.user),
            # Kavita and Komga share ReadingServerImporter's switch.
            "reading_server": KavitaImporter(self.user),
        }

    @override_settings(TESTING=False)
    def test_production_importers_enrich(self):
        for name, importer in self._importers().items():
            with self.subTest(importer=name):
                self.assertIs(importer.enable_provider_enrichment, True)

    def test_test_mode_importers_do_not_enrich(self):
        for name, importer in self._importers().items():
            with self.subTest(importer=name):
                self.assertIs(importer.enable_provider_enrichment, False)
