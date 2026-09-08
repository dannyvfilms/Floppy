from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AboutViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_about_links_to_shipped_api_references(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/about.html")
        soup = BeautifulSoup(response.content, "html.parser")
        expected_links = {
            "API Reference": reverse("swagger-ui"),
            "Verified API Schema": reverse("openapi-contract"),
            "Domain Context (JSON-LD)": reverse("jsonld-context"),
            "Full Diagnostic API Schema": reverse("schema"),
            "Asynchronous Channels (AsyncAPI)": reverse("asyncapi-contract"),
        }
        api_links = [
            (link.get_text(" ", strip=True), link.get("href"))
            for link in soup.find_all("a")
            if link.get_text(" ", strip=True) in expected_links
        ]

        self.assertEqual(api_links, list(expected_links.items()))
        for label in expected_links:
            with self.subTest(label=label):
                link = next(
                    link
                    for link in soup.find_all("a")
                    if link.get_text(" ", strip=True) == label
                )
                icon = link.find("svg")
                self.assertEqual(icon.get("aria-hidden"), "true")
                self.assertEqual(icon.get("focusable"), "false")

    def test_about_documents_installing_floppy_as_a_pwa(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.find("section", attrs={"aria-labelledby": "about-install-heading"})

        self.assertIsNotNone(section, "About page is missing the install section")
        self.assertEqual(section.find(id="about-install-heading").get_text(strip=True), "Install Floppy")

        text = section.get_text(" ", strip=True)
        self.assertIn("Floppy is an installable PWA.", text)
        self.assertIn("Add it to your Home Screen", text)

        # Both platform walkthroughs must render server-side so they survive
        # a browser with no JavaScript and no beforeinstallprompt support.
        headings = [heading.get_text(strip=True) for heading in section.find_all("h4")]
        self.assertEqual(headings, ["iOS and iPadOS", "Android"])
        self.assertIn("Add to Home Screen", text)
        self.assertIn("Add to Home screen", text)
        self.assertIn("Safari", text)
        self.assertIn("Chrome", text)
        self.assertIn("HTTPS", text)

        wiki_link = section.find(
            "a",
            href=(
                "https://github.com/dannyvfilms/Floppy/wiki/"
                "2.-User-Guide#installing-floppy-on-your-phone"
            ),
        )
        self.assertIsNotNone(wiki_link, "Install section must link the wiki guide")
        self.assertEqual(wiki_link.get("rel"), ["noopener", "noreferrer"])

    def test_install_button_is_hidden_until_an_install_event_arrives(self):
        response = self.client.get(reverse("about"))
        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.find("section", attrs={"aria-labelledby": "about-install-heading"})

        button = section.find("button")

        self.assertIsNotNone(button, "Install section must offer an install button")
        self.assertEqual(button.get_text(" ", strip=True), "Install Floppy")
        # Hidden in the served HTML: only an actionable beforeinstallprompt
        # event reveals it, so a browser without one never shows a dead button.
        wrapper = button.parent
        self.assertEqual(wrapper.get("x-show"), "canInstall")
        self.assertIn("display: none", wrapper.get("style"))
        self.assertIn("install()", button.get("@click"))

    def test_rendered_pages_leak_no_template_comment_markup(self):
        """Multi-line {# #} is not a comment and renders as visible text."""
        response = self.client.get(reverse("about"))
        body = response.content.decode()

        self.assertNotIn("{#", body)
        self.assertNotIn("#}", body)
