"""Table tests for the shared value helpers.

Each row is a case from the CQ-20 audit of the copies these helpers replaced;
every replaced copy gave the same answer on every row.
"""

from decimal import Decimal

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from app.helpers import (
    coerce_int,
    coerce_list,
    minutes_to_hm,
    seconds_to_clock,
    wants_json,
)
from integrations.oauth_models import no_store


class CoerceIntTests(SimpleTestCase):
    def test_table(self):
        rows = (
            (None, None),
            ("", None),
            ("   ", None),
            ("abc", None),
            ("7", 7),
            (" 7 ", 7),
            ("-3", -3),
            ("7.5", None),
            (7, 7),
            (3.9, 3),
            (-3.9, -3),
            (True, 1),
            (Decimal("4.7"), 4),
            (float("nan"), None),
            ([], None),
            ({}, None),
        )
        for value, expected in rows:
            with self.subTest(value=value):
                self.assertEqual(coerce_int(value), expected)

    def test_default_is_returned_for_values_that_do_not_convert(self):
        self.assertEqual(coerce_int(None, 0), 0)
        self.assertEqual(coerce_int("", 5), 5)
        self.assertEqual(coerce_int("x", 5), 5)
        self.assertEqual(coerce_int("8", 5), 8)

    def test_infinite_float_raises(self):
        with self.assertRaises(OverflowError):
            coerce_int(float("inf"))


class CoerceListTests(SimpleTestCase):
    def test_table(self):
        rows = (
            (None, []),
            ("", []),
            ("a", ["a"]),
            (" ", [" "]),
            (0, [0]),
            (False, [False]),
            ({}, [{}]),
            ((1, 2), [(1, 2)]),
            ({"id": 1}, [{"id": 1}]),
        )
        for value, expected in rows:
            with self.subTest(value=value):
                self.assertEqual(coerce_list(value), expected)

    def test_list_comes_back_as_the_same_object(self):
        value = [1, 2]
        self.assertIs(coerce_list(value), value)


class MinutesToHmTests(SimpleTestCase):
    def test_table(self):
        rows = (
            (0, "0m"),
            (40, "40m"),
            (59, "59m"),
            (60, "1h 0m"),
            (69, "1h 9m"),
            (125, "2h 5m"),
            (90.5, "1h 30m"),
            (1500, "25h 0m"),
        )
        for value, expected in rows:
            with self.subTest(value=value):
                self.assertEqual(minutes_to_hm(value), expected)


class SecondsToClockTests(SimpleTestCase):
    def test_table(self):
        rows = (
            (0, "0:00"),
            (5, "0:05"),
            (245, "4:05"),
            (3599, "59:59"),
            (3600, "1:00:00"),
            (3723, "1:02:03"),
            (245.9, "4:05"),
            (90000, "25:00:00"),
        )
        for value, expected in rows:
            with self.subTest(value=value):
                self.assertEqual(seconds_to_clock(value), expected)


class WantsJsonTests(SimpleTestCase):
    def test_table(self):
        factory = RequestFactory()
        rows = (
            ({}, "", False),
            ({"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}, "", True),
            ({"HTTP_ACCEPT": "application/json"}, "", True),
            ({"HTTP_ACCEPT": "text/html, application/json;q=0.9"}, "", True),
            ({"HTTP_ACCEPT": "text/html"}, "", False),
            ({}, "?format=json", False),
        )
        for headers, query, expected in rows:
            with self.subTest(headers=headers, query=query):
                request = factory.get(f"/{query}", **headers)
                self.assertIs(wants_json(request), expected)


class NoStoreTests(SimpleTestCase):
    def test_sets_both_headers_and_returns_the_response(self):
        response = HttpResponse()
        response["Cache-Control"] = "max-age=60"

        self.assertIs(no_store(response), response)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Pragma"], "no-cache")
