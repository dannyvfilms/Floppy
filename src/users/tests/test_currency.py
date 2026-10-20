from decimal import Decimal

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from users import currency


def _request(accept_language=""):
    request = RequestFactory().get("/")
    if accept_language:
        request.META["HTTP_ACCEPT_LANGUAGE"] = accept_language
    return request


class CurrencyResolutionTests(SimpleTestCase):
    """Auto picks a currency from the browser; an explicit choice always wins."""

    def test_browser_region_picks_currency(self):
        for header, expected in (
            ("en-US,en;q=0.9", "USD"),
            ("en-GB,en;q=0.9", "GBP"),
            ("de-CH", "CHF"),
            ("fr-FR,fr;q=0.8", "EUR"),
            ("ja-JP", "JPY"),
            ("en-CA", "CAD"),
        ):
            with self.subTest(header=header):
                self.assertEqual(currency.regional_currency(_request(header)), expected)

    def test_region_is_found_before_variants_scripts_and_extensions(self):
        for header, expected in (
            ("de-CH-1996", "CHF"),
            ("en-GB-oxendict", "GBP"),
            ("zh-Hans-CN", "CNY"),
            ("en-GB-u-ca-gregory", "GBP"),
            ("en-u-ca-gregory", "USD"),
            ("en-x-gb", "USD"),
        ):
            with self.subTest(header=header):
                self.assertEqual(currency.regional_currency(_request(header)), expected)

    def test_language_without_region_falls_back_to_language_default(self):
        self.assertEqual(currency.regional_currency(_request("de")), "EUR")
        self.assertEqual(currency.regional_currency(_request("en")), "USD")

    def test_unknown_region_or_missing_header_falls_back_to_usd(self):
        self.assertEqual(currency.regional_currency(_request("en-XX")), "USD")
        self.assertEqual(currency.regional_currency(_request()), "USD")
        self.assertEqual(currency.regional_currency(None), "USD")

    def test_second_language_region_is_used_when_first_has_none(self):
        self.assertEqual(currency.regional_currency(_request("en,en-GB;q=0.8")), "GBP")

    def test_explicit_choice_beats_browser_region(self):
        user = type("U", (), {"currency": "EUR"})()
        self.assertEqual(currency.resolve_currency(user, _request("en-US")), "EUR")

    def test_auto_and_unknown_stored_values_use_the_region(self):
        for stored in ("auto", "XYZ"):
            user = type("U", (), {"currency": stored})()
            with self.subTest(stored=stored):
                self.assertEqual(
                    currency.resolve_currency(user, _request("en-GB")), "GBP"
                )

    def test_every_region_currency_is_a_known_currency(self):
        self.assertTrue(
            set(currency.REGION_CURRENCY.values()) <= set(currency.CURRENCIES)
        )
        self.assertTrue(
            set(currency.LANGUAGE_CURRENCY.values()) <= set(currency.CURRENCIES)
        )


class CurrencyFormatTests(SimpleTestCase):
    def test_symbol_placement_and_decimals(self):
        self.assertEqual(currency.format_price(Decimal("9.5"), "USD"), "$9.50")
        self.assertEqual(currency.format_price(Decimal("9.5"), "GBP"), "£9.50")
        self.assertEqual(currency.format_price(Decimal(1200), "JPY"), "¥1200")
        self.assertEqual(currency.format_price(Decimal("99.9"), "SEK"), "99.90 kr")
        self.assertEqual(currency.format_price(Decimal(5), "CHF"), "CHF5.00")

    def test_float_and_zero_amounts_format(self):
        self.assertEqual(currency.format_price(0, "USD"), "$0.00")
        self.assertEqual(currency.format_price(4.5, "EUR"), "€4.50")


class UserPriceTagTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="priceuser", password="testpass123"
        )

    def _render(self, request=None):
        template = Template("{% load user_tags %}{% user_price 12.5 %}")
        return template.render(Context({"user": self.user, "request": request}))

    def test_auto_follows_browser_region(self):
        self.assertEqual(self._render(_request("en-GB")), "£12.50")
        self.assertEqual(self._render(_request("en-US")), "$12.50")

    def test_chosen_currency_wins(self):
        self.user.currency = "EUR"
        self.assertEqual(self._render(_request("en-US")), "€12.50")

    def test_renders_without_a_request(self):
        self.assertEqual(self._render(None), "$12.50")


class CurrencyPreferenceTests(TestCase):
    def setUp(self):
        self.credentials = {"username": "currencyuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_new_users_default_to_auto(self):
        self.assertEqual(self.user.currency, "auto")

    def test_preferences_page_offers_currency(self):
        response = self.client.get(reverse("preferences"))
        self.assertContains(response, 'name="currency"')
        self.assertContains(response, "EUR (€)")

    def test_post_persists_currency(self):
        self.client.post(reverse("preferences"), {"currency": "GBP"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.currency, "GBP")

    def test_post_can_return_to_auto(self):
        self.user.currency = "GBP"
        self.user.save()
        self.client.post(reverse("preferences"), {"currency": "auto"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.currency, "auto")

    def test_post_rejects_unknown_currency(self):
        self.client.post(reverse("preferences"), {"currency": "XYZ"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.currency, "auto")

    def test_unrelated_post_leaves_currency_alone(self):
        self.user.currency = "JPY"
        self.user.save()
        self.client.post(reverse("preferences"), {"date_format": "m_d_yyyy"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.currency, "JPY")
