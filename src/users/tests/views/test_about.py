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
        # AsyncAPI (W3) is not shipped yet, so About must not advertise it.
        # The rule is unchanged: link only artifacts that actually exist.
        self.assertNotContains(response, "AsyncAPI")
