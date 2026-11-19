"""Person pages send credits a page at a time (performance prompt 49-A).

The detail census (#2048) measured a person with 1,000 credits at 11 MB of
web HTML and 8.5 MB of API JSON, and a database write on every view. The page
now sends one page of each grid, the next page on request, and writes the
person row only when the provider's profile changed.
"""

import json
import re
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from app import credits
from app.models import Item, MediaTypes, Movie, Person, Sources, Status
from app.people_views import PERSON_CREDITS_PAGE_SIZE

PERSON_ID = "9090"
CREDITS = PERSON_CREDITS_PAGE_SIZE * 2 + 5  # three pages, the last one short
WATCHED = PERSON_CREDITS_PAGE_SIZE + 3  # two watched pages


def _payload(**overrides):
    payload = {
        "person_id": PERSON_ID,
        "source": Sources.TMDB.value,
        "name": "Long Career",
        "image": "http://example.com/long.jpg",
        "biography": "Many films.",
        "known_for_department": "Acting",
        "gender": "female",
        "birth_date": "1950-01-02",
        "death_date": None,
        "place_of_birth": "Paris",
        "filmography": [
            {
                "media_id": str(1000 + index),
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": f"Film {index:03d}",
                "image": "http://example.com/film.jpg",
                "year": 1960 + index % 60,
                "release_date": f"{1960 + index % 60}-01-{1 + index % 28:02d}",
                "credit_type": "cast",
                "role": "Lead",
                "department": "Acting",
            }
            for index in range(CREDITS)
        ],
    }
    payload.update(overrides)
    return payload


def _write_statements(queries):
    return [
        query["sql"]
        for query in queries.captured_queries
        if re.match(r"\s*(INSERT|UPDATE|DELETE)", query["sql"], re.IGNORECASE)
    ]


class PersonCreditPagesTests(TestCase):
    """One page per grid, the next page on request, filters before paging."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="pager", password="x")
        now = timezone.now()
        for index in range(WATCHED):
            item = Item.objects.create(
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                media_id=str(1000 + index),
                title=f"Film {index:03d}",
            )
            Movie.objects.create(
                user=cls.user, item=item, status=Status.COMPLETED.value, end_date=now
            )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)
        patcher = patch("app.providers.tmdb.person", return_value=_payload())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.url = reverse(
            "person_detail",
            kwargs={"source": "tmdb", "person_id": PERSON_ID, "name": "long-career"},
        )

    def _json(self, **params):
        response = self.client.get(self.url, {"format": "json", **params})
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_web_page_sends_one_page_per_grid_with_full_counts(self):
        response = self.client.get(self.url)
        html = response.content.decode()

        self.assertEqual(html.count("data-person-credit"), PERSON_CREDITS_PAGE_SIZE * 2)
        # Headings count every credit, not the page.
        self.assertIn(f"{CREDITS} titles", html)
        self.assertIn(f"{WATCHED} titles", html)
        # Each grid's last card asks for page 2 of its own list.
        self.assertIn('"section": "filmography", "credits_page": "2"', html)
        self.assertIn('"section": "watched", "watched_page": "2"', html)

    def test_more_request_returns_only_the_next_cards_of_one_grid(self):
        response = self.client.get(
            self.url,
            {"section": "filmography", "credits_page": "3"},
            headers={"hx-request": "true"},
        )
        html = response.content.decode()

        self.assertEqual(html.count("data-person-credit"), 5)
        self.assertNotIn("<section", html)
        # The last page has no "next page" sentinel.
        self.assertNotIn("hx-trigger", html)

    def test_api_pages_follow_the_chosen_sort(self):
        first = self._json(sort="title", direction="asc")
        second = self._json(
            sort="title", direction="asc", section="filmography", credits_page="2"
        )

        self.assertEqual(first["filmographyTotal"], CREDITS)
        self.assertEqual(first["watchedTotal"], WATCHED)
        self.assertEqual(first["filmographyNextPage"], 2)
        self.assertEqual(first["watchedNextPage"], 2)
        self.assertEqual(len(first["filmography"]), PERSON_CREDITS_PAGE_SIZE)
        self.assertEqual(len(first["watched"]), PERSON_CREDITS_PAGE_SIZE)

        # A "more" request fills only the grid it names.
        self.assertEqual(second["watched"], [])
        self.assertEqual(second["filmographyNextPage"], 3)
        titles = [entry["title"] for entry in first["filmography"]]
        titles += [entry["title"] for entry in second["filmography"]]
        self.assertEqual(titles, sorted(titles))
        self.assertEqual(len(set(titles)), PERSON_CREDITS_PAGE_SIZE * 2)

        last = self._json(section="watched", watched_page="2")
        self.assertEqual(len(last["watched"]), WATCHED - PERSON_CREDITS_PAGE_SIZE)
        self.assertIsNone(last["watchedNextPage"])

    def test_filters_apply_before_paging(self):
        data = self._json(year="1960")

        expected = sum(1 for index in range(CREDITS) if index % 60 == 0)
        self.assertEqual(data["filmographyTotal"], expected)
        self.assertIsNone(data["filmographyNextPage"])

    def test_shown_count_keeps_a_scrolled_grid_on_refresh(self):
        """The play-totals fill-in re-renders the grid at the size on screen."""
        data = self._json(credits_shown=str(PERSON_CREDITS_PAGE_SIZE + 1))

        self.assertEqual(len(data["filmography"]), PERSON_CREDITS_PAGE_SIZE * 2)
        self.assertEqual(data["filmographyNextPage"], 3)

    def test_full_page_load_ignores_page_parameters(self):
        """A card's "track" modal returns to the page URL it was loaded from.

        For a card from a later page that is the "more" URL; opened as a whole
        page it must show the person page from the top, not one page of cards.
        """
        response = self.client.get(
            self.url, {"section": "filmography", "credits_page": "3"}
        )
        html = response.content.decode()

        self.assertIn('id="person-hero"', html)
        self.assertEqual(html.count("data-person-credit"), PERSON_CREDITS_PAGE_SIZE * 2)

    def test_bad_page_numbers_fall_back_to_the_first_page(self):
        data = self._json(credits_page="nope", watched_page="-4")

        self.assertEqual(data["filmography"][0]["title"], self._json()["filmography"][0]["title"])
        self.assertEqual(data["filmographyNextPage"], 2)

    def test_repeat_view_writes_nothing(self):
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [sql for sql in _write_statements(queries) if "app_person" in sql], []
        )


class UpsertPersonProfileTests(TestCase):
    """The person row is written only when the provider's profile changed."""

    def test_unchanged_profile_is_not_written(self):
        person = credits.upsert_person_profile("tmdb", PERSON_ID, _payload())
        with CaptureQueriesContext(connection) as queries:
            again = credits.upsert_person_profile("tmdb", PERSON_ID, _payload())

        self.assertEqual(again.pk, person.pk)
        self.assertEqual(_write_statements(queries), [])

    def test_changed_fields_are_saved(self):
        credits.upsert_person_profile("tmdb", PERSON_ID, _payload())
        with CaptureQueriesContext(connection) as queries:
            credits.upsert_person_profile(
                "tmdb", PERSON_ID, _payload(biography="Updated.", death_date="2020-05-06")
            )

        person = Person.objects.get(source="tmdb", source_person_id=PERSON_ID)
        self.assertEqual(person.biography, "Updated.")
        self.assertEqual(person.death_date, date(2020, 5, 6))
        self.assertEqual(person.name, "Long Career")
        self.assertEqual(len(_write_statements(queries)), 1)

    def test_empty_provider_answer_keeps_the_stored_profile(self):
        credits.upsert_person_profile("tmdb", PERSON_ID, _payload())

        person = credits.upsert_person_profile("tmdb", PERSON_ID, {})

        self.assertEqual(person.name, "Long Career")
        self.assertEqual(
            Person.objects.get(source="tmdb", source_person_id=PERSON_ID).biography,
            "Many films.",
        )

    def test_empty_provider_answer_for_an_unknown_person_creates_nothing(self):
        self.assertIsNone(credits.upsert_person_profile("tmdb", "404404", {}))
        self.assertFalse(Person.objects.filter(source_person_id="404404").exists())
