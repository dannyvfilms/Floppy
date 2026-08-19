from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import MediaTypes
from integrations.models import PlexAccount
from integrations.onboarding import (
    ONBOARDING_SOURCES,
    get_source,
    sources_for_media_type,
)


class OnboardingRegistryTests(TestCase):
    """The service capability map used by the setup wizard."""

    def test_every_media_type_maps_to_at_least_one_or_zero_gracefully(self):
        """Every declared source's media types are valid MediaTypes values."""
        valid_values = set(MediaTypes.values)
        for source in ONBOARDING_SOURCES:
            for media_type in source.media_types:
                self.assertIn(media_type, valid_values)

    def test_sources_for_media_type_matches_declared_sources(self):
        """Filtering by media type returns exactly the sources that declare it."""
        movie_sources = {s.slug for s in sources_for_media_type(MediaTypes.MOVIE.value)}
        self.assertIn("plex", movie_sources)
        self.assertIn("radarr", movie_sources)
        self.assertNotIn("sonarr", movie_sources)

    def test_unknown_slug_returns_none(self):
        """An unrecognized slug is a lookup miss, not an exception."""
        self.assertIsNone(get_source("not-a-real-source"))

    def test_is_connected_reflects_persistent_account(self):
        """A source with a persistent account reports connected once one exists."""
        user = get_user_model().objects.create_user(
            username="onboarding-user", password="testpass123"
        )
        plex = get_source("plex")

        self.assertFalse(plex.is_connected(user))

        PlexAccount.objects.create(user=user, plex_token="token", plex_username="u")

        user.refresh_from_db()
        self.assertTrue(plex.is_connected(user))

    def test_sources_without_persistent_account_are_never_connected(self):
        """One-off import sources (OAuth token flows, uploads) never report connected."""
        user = get_user_model().objects.create_user(
            username="onboarding-user-2", password="testpass123"
        )
        trakt = get_source("trakt")

        self.assertFalse(trakt.is_connected(user))

    def test_only_plex_declares_a_realtime_integration(self):
        """Most sources are import-only; the integration step should stay invisible for them."""
        with_integration = {s.slug for s in ONBOARDING_SOURCES if s.has_integration()}
        self.assertEqual(with_integration, {"plex"})

    def test_integration_configured_reflects_webhook_activity(self):
        """Plex's integration counts as configured once its webhook has ever fired."""
        user = get_user_model().objects.create_user(
            username="onboarding-user-3", password="testpass123"
        )
        plex = get_source("plex")

        self.assertFalse(plex.is_integration_configured(user))

        user.plex_webhook_last_received_at = timezone.now()
        user.save(update_fields=["plex_webhook_last_received_at"])

        self.assertTrue(plex.is_integration_configured(user))
