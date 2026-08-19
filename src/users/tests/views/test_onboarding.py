from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import MediaTypes
from integrations.models import PlexAccount


class OnboardingWizardTests(TestCase):
    """Tests for the first-run setup wizard views."""

    def setUp(self):
        """Create a fresh (not-yet-onboarded) user for the tests."""
        self.credentials = {"username": "newuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_new_user_defaults_to_not_started(self):
        """A freshly created user starts the wizard fresh."""
        self.assertEqual(self.user.onboarding_status, "not_started")
        self.assertEqual(self.user.onboarding_step, "media_types")

    def test_media_types_get_renders(self):
        """The media-types step renders the shared media type picker."""
        response = self.client.get(reverse("onboarding_media_types"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/onboarding/media_types.html")
        self.assertTemplateUsed(response, "users/components/media_type_picker.html")
        self.assertNotIn(MediaTypes.SEASON.value, response.context["media_types"])

    def test_media_types_post_ignores_season_entirely(self):
        """TV Seasons isn't offered, so this step must never touch season_enabled."""
        self.user.season_enabled = True
        self.user.save(update_fields=["season_enabled"])

        self.client.post(
            reverse("onboarding_media_types"),
            {"media_types_checkboxes": [MediaTypes.MOVIE.value]},
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.season_enabled)

    def test_media_types_post_advances_to_services(self):
        """Choosing media types moves to the services step and marks in_progress."""
        response = self.client.post(
            reverse("onboarding_media_types"),
            {"media_types_checkboxes": [MediaTypes.MOVIE.value, MediaTypes.TV.value]},
        )

        self.assertRedirects(response, reverse("onboarding_services", args=[0]))
        self.user.refresh_from_db()
        self.assertTrue(self.user.movie_enabled)
        self.assertTrue(self.user.tv_enabled)
        self.assertEqual(self.user.onboarding_status, "in_progress")
        self.assertEqual(self.user.onboarding_step, "services")

    def test_media_types_post_requires_at_least_one(self):
        """Submitting with nothing selected doesn't silently disable everything."""
        response = self.client.post(reverse("onboarding_media_types"), {})

        self.assertRedirects(response, reverse("onboarding_media_types"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_status, "not_started")

    def test_media_types_skip_completes_onboarding(self):
        """'I'll choose later' exits the wizard immediately."""
        response = self.client.post(
            reverse("onboarding_media_types"), {"action": "skip"}
        )

        self.assertRedirects(response, reverse("home"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_status, "completed")

    def test_services_step_remembers_shared_source_across_media_types(self):
        """Picking Plex for Movies keeps it selected when Plex also covers TV/Music."""
        self.user.movie_enabled = True
        self.user.tv_enabled = True
        for media_type in MediaTypes.values:
            if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
                setattr(self.user, f"{media_type}_enabled", False)
        self.user.save()

        first_response = self.client.post(
            reverse("onboarding_services", args=[0]), {"sources": ["plex"]}
        )
        self.user.refresh_from_db()
        self.assertIn("plex", self.user.onboarding_selected_sources)

        second_get = self.client.get(reverse("onboarding_services", args=[1]))
        self.assertIn(b"checked", second_get.content)

        second_response = self.client.post(
            reverse("onboarding_services", args=[1]), {"sources": ["plex"]}
        )
        self.assertRedirects(
            second_response, reverse("onboarding_services_summary")
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_selected_sources, ["plex"])
        self.assertIsNotNone(first_response)  # keeps the first response referenced

    def test_services_summary_later_completes_onboarding(self):
        """Bailing out from the summary step still marks onboarding complete."""
        self.user.onboarding_selected_sources = ["plex"]
        self.user.onboarding_step = "services_summary"
        self.user.save(
            update_fields=["onboarding_selected_sources", "onboarding_step"]
        )

        response = self.client.post(
            reverse("onboarding_services_summary"), {"action": "later"}
        )

        self.assertRedirects(response, reverse("home"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_status, "completed")

    def test_service_setup_skip_advances_queue(self):
        """Skipping a source removes it from the remaining queue without losing others."""
        self.user.onboarding_selected_sources = ["plex", "radarr"]
        self.user.save(update_fields=["onboarding_selected_sources"])

        response = self.client.post(
            reverse("onboarding_skip_service", kwargs={"slug": "plex"})
        )
        self.assertRedirects(response, reverse("onboarding_service_setup"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_skipped_sources, ["plex"])

        setup_response = self.client.get(reverse("onboarding_service_setup"))
        self.assertContains(setup_response, "radarr")

    def test_service_setup_empty_queue_advances_to_integration_setup(self):
        """An empty remaining queue moves straight to the (usually auto-skipped) integration step."""
        self.user.onboarding_selected_sources = []
        self.user.save(update_fields=["onboarding_selected_sources"])

        response = self.client.get(reverse("onboarding_service_setup"))
        self.assertRedirects(
            response,
            reverse("onboarding_integration_setup"),
            fetch_redirect_response=False,
        )

    def test_import_status_post_finishes_onboarding(self):
        """Finishing imports, the last step, completes onboarding."""
        response = self.client.post(reverse("onboarding_import_status"))

        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_status, "completed")

    def test_integration_setup_auto_advances_to_import_status(self):
        """No connected source has a pending integration -> the step is invisible."""
        self.user.onboarding_step = "integration_setup"
        self.user.save(update_fields=["onboarding_step"])

        response = self.client.get(reverse("onboarding_integration_setup"))

        self.assertRedirects(response, reverse("onboarding_import_status"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_step, "import_status")

    def test_integration_setup_shown_for_connected_plex_without_webhook(self):
        """A connected Plex account with no webhook activity yet gets the extra step."""
        PlexAccount.objects.create(
            user=self.user, plex_token="token", plex_username="u"
        )
        self.user.onboarding_selected_sources = ["plex"]
        self.user.onboarding_step = "integration_setup"
        self.user.save(update_fields=["onboarding_selected_sources", "onboarding_step"])

        response = self.client.get(reverse("onboarding_integration_setup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Setup Instructions")
        self.assertContains(response, "webhook/plex/")

    def test_skip_integration_advances_to_import_status(self):
        """Skipping the only pending integration moves on to the import status step."""
        PlexAccount.objects.create(
            user=self.user, plex_token="token", plex_username="u"
        )
        self.user.onboarding_selected_sources = ["plex"]
        self.user.onboarding_step = "integration_setup"
        self.user.save(update_fields=["onboarding_selected_sources", "onboarding_step"])

        skip_response = self.client.post(
            reverse("onboarding_skip_integration", kwargs={"slug": "plex"})
        )
        self.assertRedirects(
            skip_response,
            reverse("onboarding_integration_setup"),
            fetch_redirect_response=False,
        )

        follow_up = self.client.get(reverse("onboarding_integration_setup"))
        self.assertRedirects(follow_up, reverse("onboarding_import_status"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_step, "import_status")

    def test_integrations_open_query_param_deep_links_a_section(self):
        """The wizard's integration step opens the right section on Settings > Integrations."""
        response = self.client.get(
            reverse("integrations") + "?open=plex&onboarding=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "activeIntegration = deepLinkTag")
        self.assertContains(response, "Continue Guided Setup")

    def test_resume_redirects_to_saved_step(self):
        """Resuming sends the user back to wherever they left off."""
        self.user.onboarding_status = "in_progress"
        self.user.onboarding_step = "service_setup"
        # A non-empty, not-yet-connected queue so this step doesn't
        # immediately advance past itself.
        self.user.onboarding_selected_sources = ["plex"]
        self.user.save(
            update_fields=[
                "onboarding_status",
                "onboarding_step",
                "onboarding_selected_sources",
            ]
        )

        response = self.client.get(reverse("onboarding_resume"))
        self.assertRedirects(response, reverse("onboarding_service_setup"))

    def test_resume_from_stale_import_status_step_lands_on_integration_setup(self):
        """A step persisted before Scrobbling moved earlier doesn't skip it."""
        self.user.onboarding_status = "in_progress"
        self.user.onboarding_step = "import_status"
        self.user.save(update_fields=["onboarding_status", "onboarding_step"])

        response = self.client.get(reverse("onboarding_resume"))
        self.assertRedirects(
            response,
            reverse("onboarding_integration_setup"),
            fetch_redirect_response=False,
        )

    def test_restart_reopens_completed_onboarding(self):
        """'Run guided setup' from Settings works even after completion."""
        self.user.onboarding_status = "completed"
        self.user.onboarding_step = "done"
        self.user.save(update_fields=["onboarding_status", "onboarding_step"])

        response = self.client.get(reverse("onboarding_restart"))
        self.assertRedirects(response, reverse("onboarding_media_types"))

        self.user.refresh_from_db()
        self.assertEqual(self.user.onboarding_status, "in_progress")

    def test_demo_user_is_blocked(self):
        """Demo accounts never enter the wizard."""
        self.user.is_demo = True
        self.user.save(update_fields=["is_demo"])

        response = self.client.get(reverse("onboarding_media_types"))
        self.assertRedirects(response, reverse("home"))

    def test_import_data_open_query_param_deep_links_a_modal(self):
        """The wizard's connect step opens the right modal on the existing import page."""
        response = self.client.get(
            reverse("import_data") + "?open=plex&onboarding=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "openModal(deepLinkSlug)")
        self.assertContains(response, "Continue Guided Setup")


class SignupOnboardingRedirectTests(TestCase):
    """Local signup should land in the setup wizard, not Home."""

    def test_local_signup_redirects_to_onboarding(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "brandnew",
                "password1": "a-very-strong-pass123",
                "password2": "a-very-strong-pass123",
            },
        )

        self.assertRedirects(response, reverse("onboarding_media_types"))
