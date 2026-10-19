from unittest import mock

import requests
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from users import release_notes

RELEASE_BODY = """<img width="1672" alt="Recap" src="https://example.com/a.png" />

## Changes since last release:

* **Your lists can have tiers now** — Sort lists into a Tiers view, and [export](https://example.com) the board.

* **Videos fit into the tracker** — Track videos as their own media type.

## What's Changed
* Merge the three parallel users 0140 migrations by @dannyvfilms in https://example.com/pull/1421
* Port MangaBaka fixes by @dannyvfilms in https://example.com/pull/1420
"""


def _release(tag, body=RELEASE_BODY, **extra):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/dannyvfilms/Floppy/releases/tag/{tag}",
        "published_at": "2026-10-09T02:43:59Z",
        "body": body,
        "draft": False,
        "prerelease": False,
        **extra,
    }


class ReleaseTagTests(SimpleTestCase):
    def test_a_build_between_releases_reads_as_its_release(self):
        self.assertEqual(release_notes.release_tag("v26.10.8-12-gabc1234"), "v26.10.8")
        self.assertEqual(release_notes.release_tag("v26.10.8-dirty"), "v26.10.8")
        self.assertEqual(release_notes.release_tag("v26.10.8"), "v26.10.8")

    def test_a_bare_commit_or_dev_has_no_release(self):
        self.assertEqual(release_notes.release_tag("abc1234"), "")
        self.assertEqual(release_notes.release_tag("dev"), "")
        self.assertEqual(release_notes.release_tag(None), "")

    def test_tags_sort_numerically_not_alphabetically(self):
        tags = ["v26.9.24", "v26.10.8", "v26.10.1"]
        ordered = sorted(tags, key=release_notes.tag_sort_key)
        self.assertEqual(ordered, ["v26.9.24", "v26.10.1", "v26.10.8"])


class ParseHighlightsTests(SimpleTestCase):
    def test_reads_only_the_changes_section(self):
        highlights = release_notes.parse_highlights(RELEASE_BODY)

        self.assertEqual(
            highlights,
            [
                {
                    "title": "Your lists can have tiers now",
                    "text": "Sort lists into a Tiers view, and export the board.",
                },
                {
                    "title": "Videos fit into the tracker",
                    "text": "Track videos as their own media type.",
                },
            ],
        )

    def test_a_body_without_the_section_has_no_highlights(self):
        self.assertEqual(release_notes.parse_highlights("Just some text"), [])
        self.assertEqual(release_notes.parse_highlights(None), [])

    def test_a_bullet_without_a_bold_lead_keeps_its_text(self):
        body = "## Changes\n* Plain bullet with no lead\n"
        self.assertEqual(
            release_notes.parse_highlights(body),
            [{"title": "", "text": "Plain bullet with no lead"}],
        )


class GetReleasesTests(SimpleTestCase):
    def setUp(self):
        cache.delete(release_notes.CACHE_KEY)
        self.addCleanup(cache.delete, release_notes.CACHE_KEY)

    def _response(self, payload):
        response = mock.Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_releases_are_newest_first_and_skip_drafts(self):
        payload = [
            _release("v26.9.24"),
            _release("v26.10.8"),
            _release("v26.10.9", draft=True),
        ]
        with mock.patch.object(
            release_notes.requests,
            "get",
            return_value=self._response(payload),
        ) as get:
            releases = release_notes.get_releases()
            again = release_notes.get_releases()

        self.assertEqual([r["tag"] for r in releases], ["v26.10.8", "v26.9.24"])
        self.assertEqual(again, releases)
        self.assertEqual(get.call_count, 1, "the second call must come from cache")

    def test_unreachable_github_returns_none_and_is_not_retried_at_once(self):
        with mock.patch.object(
            release_notes.requests,
            "get",
            side_effect=requests.ConnectionError("offline"),
        ) as get:
            self.assertIsNone(release_notes.get_releases())
            self.assertIsNone(release_notes.get_releases())

        self.assertEqual(get.call_count, 1)

    def test_an_unexpected_payload_returns_none(self):
        with mock.patch.object(
            release_notes.requests,
            "get",
            return_value=self._response([{"unexpected": True}]),
        ):
            self.assertIsNone(release_notes.get_releases())


@override_settings(VERSION="v26.10.1-4-gabc1234")
class WhatsNewViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reader",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def _releases(self):
        return [
            {
                "tag": "v26.10.8",
                "url": "https://github.com/dannyvfilms/Floppy/releases/tag/v26.10.8",
                "published": "2026-10-09",
                "highlights": [{"title": "Tiers", "text": "Sort lists."}],
            },
            {
                "tag": "v26.10.1",
                "url": "https://github.com/dannyvfilms/Floppy/releases/tag/v26.10.1",
                "published": "2026-10-02",
                "highlights": [],
            },
        ]

    def test_installed_and_newer_releases_are_labelled(self):
        with mock.patch.object(release_notes, "get_releases", return_value=self._releases()):
            response = self.client.get(reverse("whats_new"))

        self.assertEqual(response.status_code, 200)
        text = BeautifulSoup(response.content, "html.parser").get_text(" ", strip=True)
        self.assertIn("v26.10.8", text)
        self.assertIn("Newer than yours", text)
        self.assertIn("Installed", text)
        self.assertIn("Tiers", text)
        self.assertIn("See the release page for what changed.", text)

    def test_unreachable_github_links_to_the_releases_page(self):
        with mock.patch.object(release_notes, "get_releases", return_value=None):
            response = self.client.get(reverse("whats_new"))

        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content, "html.parser")
        self.assertIn("could not be loaded", soup.get_text(" ", strip=True))
        self.assertEqual(soup.find("a")["href"], release_notes.RELEASES_PAGE_URL)

    def test_about_loads_the_notes_in_the_background(self):
        response = self.client.get(reverse("about"))

        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.find(id="whats-new")
        self.assertIsNotNone(section)
        self.assertEqual(
            section.find(attrs={"hx-get": True})["hx-get"],
            reverse("whats_new"),
        )

    def test_anonymous_visitors_cannot_read_the_fragment(self):
        self.client.logout()
        response = self.client.get(reverse("whats_new"))
        self.assertEqual(response.status_code, 302)


@override_settings(VERSION="v26.10.8-3-gabc1234")
class UpdateBannerTests(TestCase):
    def _page_has_banner(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("about"))
        return b"floppy_seen_release" in response.content

    def test_admins_get_the_banner_with_the_release_tag(self):
        admin = get_user_model().objects.create_superuser(
            username="boss",
            password="testpass123",
        )
        self.assertTrue(self._page_has_banner(admin))
        self.assertContains(self.client.get(reverse("about")), "v26.10.8")

    def test_regular_users_do_not_get_the_banner(self):
        user = get_user_model().objects.create_user(
            username="regular",
            password="testpass123",
        )
        self.assertFalse(self._page_has_banner(user))

    @override_settings(VERSION="abc1234")
    def test_a_build_with_no_release_has_no_banner(self):
        admin = get_user_model().objects.create_superuser(
            username="boss2",
            password="testpass123",
        )
        self.assertFalse(self._page_has_banner(admin))
