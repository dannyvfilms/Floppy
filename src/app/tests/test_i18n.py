"""Language selection and presentation must not change stored media identities."""

from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.template import engines
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from app.forms import MovieForm
from app.middleware import UserLanguageMiddleware
from app.models import MediaTypes, Status
from app.templatetags.app_tags import (
    long_unit,
    media_status_readable,
    media_type_readable,
    media_type_readable_plural,
    progress_unit_label,
)


class GermanPresentationTests(SimpleTestCase):
    """Exercise real catalogs and template compilation rather than copied strings."""

    def test_labels_are_localized_without_changing_status_values(self):
        with translation.override("de"):
            self.assertEqual(media_type_readable(MediaTypes.MOVIE), "Film")
            self.assertEqual(media_type_readable_plural(MediaTypes.BOOK), "Bücher")
            self.assertEqual(media_status_readable(Status.PLANNING), "Geplant")
            choices = dict(MovieForm().fields["status"].choices)
            self.assertEqual(choices["Planning"], "Geplant")
            self.assertEqual(Status.PLANNING.value, "Planning")
            self.assertEqual(MediaTypes.MOVIE.label, "Movie")

    def test_progress_units_have_german_plurals_and_stable_raw_values(self):
        with translation.override("de"):
            for media_type, singular, plural, raw in (
                (MediaTypes.SEASON, "Folge", "Folgen", "Episode"),
                (MediaTypes.BOOK, "Seite", "Seiten", "Page"),
                (MediaTypes.MANGA, "Kapitel", "Kapitel", "Chapter"),
                (MediaTypes.MUSIC, "Wiedergabe", "Wiedergaben", "Play"),
            ):
                with self.subTest(media_type=media_type):
                    self.assertEqual(progress_unit_label(media_type, 1), singular)
                    self.assertEqual(progress_unit_label(media_type, 2), plural)
                    self.assertEqual(long_unit(media_type), raw)

    def test_all_application_templates_compile(self):
        engine = engines["django"].engine
        for path in (settings.BASE_DIR / "templates").rglob("*.html"):
            with self.subTest(template=str(path)):
                engine.from_string(path.read_text())

    def test_language_does_not_leak_to_next_request(self):
        factory = RequestFactory()
        middleware = UserLanguageMiddleware(
            lambda request: HttpResponse(translation.gettext("Home"))
        )
        german_request = factory.get("/", HTTP_ACCEPT_LANGUAGE="en")
        german_request.user = SimpleNamespace(is_authenticated=True, ui_language="de")
        self.assertEqual(middleware(german_request).content, b"Startseite")
        english_request = factory.get("/", HTTP_ACCEPT_LANGUAGE="en")
        english_request.user = SimpleNamespace(is_authenticated=False)
        self.assertEqual(middleware(english_request).content, b"Home")


class GermanPreferencesTests(TestCase):
    """Check language changes across settings, HTML, and JavaScript requests."""

    def test_saved_language_controls_html_and_javascript(self):
        user = get_user_model().objects.create_user(username="language-test")
        self.client.force_login(user)
        response = self.client.post(reverse("preferences"), {"ui_language": "de"})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.ui_language, "de")
        response = self.client.get(reverse("preferences"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, '<html lang="de"')
        self.assertContains(response, "Einstellungen")
        self.assertContains(response, reverse("javascript-catalog"))
        catalog = self.client.get(reverse("javascript-catalog"))
        self.assertContains(catalog, "Heute")
        self.assertIn("no-store", catalog.headers["Cache-Control"])

    def test_anonymous_catalog_uses_browser_language(self):
        response = self.client.get(
            reverse("javascript-catalog"), HTTP_ACCEPT_LANGUAGE="de-DE,de;q=0.9"
        )
        self.assertContains(response, "Heute")
        english = self.client.get(
            reverse("javascript-catalog"), HTTP_ACCEPT_LANGUAGE="en"
        )
        self.assertNotContains(english, "Heute")


class FrenchPresentationTests(SimpleTestCase):
    """French catalogs localize labels and use its own plural rule."""

    def test_labels_are_localized_without_changing_status_values(self):
        with translation.override("fr"):
            self.assertEqual(media_type_readable(MediaTypes.MOVIE), "Film")
            self.assertEqual(media_status_readable(Status.PLANNING), "Prévu")
            choices = dict(MovieForm().fields["status"].choices)
            self.assertEqual(choices["Planning"], "Prévu")
            self.assertEqual(Status.PLANNING.value, "Planning")

    def test_progress_units_treat_zero_as_singular(self):
        # French uses plural=(n > 1), unlike German and English.
        with translation.override("fr"):
            self.assertEqual(progress_unit_label(MediaTypes.SEASON, 0), "Épisode")
            self.assertEqual(progress_unit_label(MediaTypes.SEASON, 1), "Épisode")
            self.assertEqual(progress_unit_label(MediaTypes.SEASON, 2), "Épisodes")


class FrenchPreferencesTests(TestCase):
    """Check a saved French preference across HTML and JavaScript requests."""

    def test_saved_language_controls_html_and_javascript(self):
        user = get_user_model().objects.create_user(username="french-language-test")
        self.client.force_login(user)
        response = self.client.post(reverse("preferences"), {"ui_language": "fr"})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.ui_language, "fr")
        response = self.client.get(reverse("preferences"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(response, '<html lang="fr"')
        self.assertContains(response, "Paramètres")
        catalog = self.client.get(reverse("javascript-catalog"))
        self.assertContains(catalog, "Aujourd'hui")
