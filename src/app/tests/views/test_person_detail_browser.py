"""Touch verification for person-credit cards on the filmography page."""

import os
import re
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from app.models import MediaTypes, Person, Sources
from app.tests.live_server import SerialStaticLiveServerTestCase


@tag("slow", "playwright")
class PersonDetailCreditCardBrowserTests(SerialStaticLiveServerTestCase):
    """A touch tap reveals a hidden role before the title link navigates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.async_override = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.async_override.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.async_override.stop()
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="person-credit-touch",
            theme="system",
            clickable_media_cards=False,
        )
        self.client.force_login(self.user)
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            color_scheme="dark",
            service_workers="block",
        )
        self.addCleanup(self.context.close)
        self.context.add_cookies([{
            "name": "sessionid",
            "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.context.route("**/*", self.serve_local_only)
        self.page = self.context.new_page()
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    def serve_local_only(self, route):
        """Keep the test deterministic and avoid external images/provider calls."""
        if urlsplit(route.request.url).netloc != urlsplit(self.live_server_url).netloc:
            route.abort()
        else:
            route.continue_()

    @patch("app.providers.tmdb.person")
    def test_touch_reveals_credit_role_before_following_title_link(self, mock_person):
        mock_person.return_value = {
            "person_id": "123",
            "source": Sources.TMDB.value,
            "name": "Jane Star",
            "birth_date": "1930-01-01",
            "death_date": "2010-05-01",
            "filmography": [{
                "media_id": "900",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Posthumous Release",
                "image": "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
                "year": 2015,
                "release_date": "2015-07-01",
                "credit_type": "cast",
                "role": "Rae of Light",
            }],
        }
        url = reverse(
            "person_detail",
            kwargs={"source": Sources.TMDB.value, "person_id": "123", "name": "jane-star"},
        )
        self.page.goto(f"{self.live_server_url}{url}")
        card = self.page.locator('[data-media-card-root][data-react-mounted="true"]').first
        expect(card).to_be_visible()
        title_link = card.locator("a.media-card-title")
        destination = title_link.get_attribute("href")
        self.assertTrue(destination)

        card.locator("img.media-card-poster").click()
        self.assertEqual(self.page.url, f"{self.live_server_url}{url}")
        expect(card.locator(".media-card-year").filter(has_text="Rae of Light")).to_be_visible()
        age_line = card.get_by_text("85 yo at release\nDied 2010", exact=True)
        expect(age_line).to_be_visible()
        age_layout = age_line.evaluate("""element => {
          const style = getComputedStyle(element);
          return {
            lineClamp: style.webkitLineClamp,
            height: element.getBoundingClientRect().height,
            lineHeight: parseFloat(style.lineHeight),
          };
        }""")
        self.assertEqual(age_layout["lineClamp"], "2")
        self.assertGreaterEqual(age_layout["height"], age_layout["lineHeight"] * 2)
        self.assertEqual(age_line.evaluate("element => getComputedStyle(element).whiteSpace"), "pre-line")
        expect(card).to_have_class(re.compile("media-card-revealed"))

        screenshot = Path(os.environ["TMPDIR"]) / "person-credit-touch-revealed.png"
        self.page.screenshot(path=screenshot, full_page=True)
        with self.page.expect_navigation():
            title_link.click(force=True)
        self.assertIn(destination, self.page.url)
        self.assertEqual(self.page_errors, [])

    @patch("app.providers.tmdb.person", return_value={"name": "Jane Star", "filmography": []})
    @patch(
        "app.providers.tmdb.person_dates",
        return_value={"birth_date": "1965-02-01", "death_date": "1993-03-31"},
    )
    def test_cast_person_card_shows_release_age_and_death_then_reveals_role(
        self, _mock_person_dates, _mock_person
    ):
        """Visible cards fetch and persist dates, then touch reveals the role."""
        Person.objects.create(
            source=Sources.TMDB.value,
            source_person_id="123",
            name="Jane Star",
        )
        person_url = f"{self.live_server_url}{reverse('person_detail', kwargs={'source': Sources.TMDB.value, 'person_id': '123', 'name': 'jane-star'})}"
        age_url = (
            f"{reverse('person_credit_facts', kwargs={'source': Sources.TMDB.value, 'person_id': '123'})}"
            "?event_date=1994-05-11&media_type=movie"
        )
        props = {
            "kind": "cast",
            "title": "Cast",
            "items": [{
                "id": "tmdb:123",
                "cardId": "people-card-tmdb-123",
                "name": "Jane Star",
                "subtitle": "Rae of Light",
                "cardLines": [{"text": "Rae of Light", "dormant": False}],
                "imageUrl": "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
                "href": person_url,
                "ageUrl": age_url,
                "agePending": True,
            }],
            "titleOptions": {"overflow": "ellipsis", "lines": 1, "hover": "bleed", "hover_lines": 3},
            "labels": {},
        }
        self.page.goto(f"{self.live_server_url}{reverse('cards')}")
        cards_url = self.page.url
        self.page.evaluate(
            """props => {
              const wrapper = document.createElement('div');
              const script = document.createElement('script');
              script.id = 'person-cast-props';
              script.type = 'application/json';
              script.textContent = JSON.stringify(props);
              const host = document.createElement('div');
              host.dataset.peopleCastRoot = '';
              host.dataset.propsId = script.id;
              wrapper.append(script, host);
              document.body.append(wrapper);
            }""",
            props,
        )
        host = self.page.locator('[data-people-cast-root][data-react-mounted="true"]')
        expect(host).to_have_count(1)
        card = host.locator("#people-card-tmdb-123").locator(".media-card")
        expect(card).to_be_visible()
        card.scroll_into_view_if_needed()
        age_line = card.get_by_text("29 yo at release\nDied 1993", exact=True)
        expect(age_line).to_be_visible()
        persisted_person = Person.objects.get(
            source=Sources.TMDB.value,
            source_person_id="123",
        )
        self.assertEqual(persisted_person.death_date.isoformat(), "1993-03-31")
        self.assertIsNotNone(persisted_person.profile_dates_checked_at)
        role_text = card.get_by_text("Rae of Light", exact=True)
        self.assertEqual(
            role_text.evaluate("element => getComputedStyle(element).opacity"),
            "0",
        )
        self.assertNotIn("media-card-revealed", card.get_attribute("class") or "")

        card.locator("img.media-card-poster").click()
        self.assertEqual(self.page.url, cards_url)
        expect(card).to_have_class(re.compile("media-card-revealed"))
        expect(role_text).to_have_css("opacity", "1")
        screenshot = Path(os.environ["TMPDIR"]) / "person-credit-cast-rail.png"
        host.screenshot(path=screenshot)
        person_link = card.get_by_role("link", name="Jane Star", exact=True)
        expect(person_link).to_be_visible()
        with self.page.expect_navigation():
            card.locator(".media-card-overlay a[href]").click()
        self.assertIn("/person/tmdb/123/jane-star", self.page.url)
        self.assertEqual(self.page_errors, [])
