"""Currency shown next to collection prices (#1100).

A collection price is stored as a bare number, so the currency is only a
display choice: changing it relabels the numbers and never converts them.
"""

from decimal import Decimal

from django.utils.formats import number_format
from django.utils.translation import get_language_from_request, trans_real

AUTO = "auto"
DEFAULT_CURRENCY = "USD"

# code: (symbol, symbol goes after the number, decimal places)
CURRENCIES = {
    "USD": ("$", False, 2),
    "EUR": ("€", False, 2),
    "GBP": ("£", False, 2),
    "CAD": ("CA$", False, 2),
    "AUD": ("A$", False, 2),
    "NZD": ("NZ$", False, 2),
    "JPY": ("¥", False, 0),
    "CNY": ("CN¥", False, 2),
    "KRW": ("₩", False, 0),
    "INR": ("₹", False, 2),
    "BRL": ("R$", False, 2),
    "MXN": ("MX$", False, 2),
    "CHF": ("CHF", False, 2),
    "SEK": ("kr", True, 2),
    "NOK": ("kr", True, 2),
    "DKK": ("kr", True, 2),
    "PLN": ("zł", True, 2),
    "CZK": ("Kč", True, 2),
    "ZAR": ("R", False, 2),
    "SGD": ("S$", False, 2),
    "HKD": ("HK$", False, 2),
}

_EURO_REGIONS = [
    "AT",
    "BE",
    "CY",
    "DE",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PT",
    "SI",
    "SK",
]
REGION_CURRENCY = {
    **dict.fromkeys(_EURO_REGIONS, "EUR"),
    "US": "USD",
    "GB": "GBP",
    "CA": "CAD",
    "AU": "AUD",
    "NZ": "NZD",
    "JP": "JPY",
    "CN": "CNY",
    "KR": "KRW",
    "IN": "INR",
    "BR": "BRL",
    "MX": "MXN",
    "CH": "CHF",
    "SE": "SEK",
    "NO": "NOK",
    "DK": "DKK",
    "PL": "PLN",
    "CZ": "CZK",
    "ZA": "ZAR",
    "SG": "SGD",
    "HK": "HKD",
}

# Used when the browser names a language but no country ("de", not "de-AT").
LANGUAGE_CURRENCY = {"de": "EUR", "fr": "EUR", "es": "EUR"}


def choices():
    """Return (code, label) pairs for the preference dropdown."""
    return [
        (code, code if symbol == code else f"{code} ({symbol})")
        for code, (symbol, _, _) in CURRENCIES.items()
    ]


def _region_subtag(tag):
    """Return the known region of a language tag, or None.

    The region is not always last: "de-CH-1996" has a variant after it and
    "en-GB-u-ca-gregory" an extension. A single-letter subtag starts an
    extension or private use section, so the search stops there.
    """
    for part in tag.replace("_", "-").upper().split("-")[1:]:
        if len(part) == 1:
            return None
        if part.isalpha() and part in REGION_CURRENCY:
            return part
    return None


def regional_currency(request):
    """Guess a currency from the browser's languages, then the UI language."""
    if request is None:
        return DEFAULT_CURRENCY
    header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    for tag, _quality in trans_real.parse_accept_lang_header(header):
        region = _region_subtag(tag)
        if region in REGION_CURRENCY:
            return REGION_CURRENCY[region]
    language = get_language_from_request(request).split("-")[0]
    return LANGUAGE_CURRENCY.get(language, DEFAULT_CURRENCY)


def resolve_currency(user, request=None):
    """Return the currency code to show: the user's choice, else the region's."""
    chosen = getattr(user, "currency", AUTO)
    if chosen in CURRENCIES:
        return chosen
    return regional_currency(request)


def format_price(amount, code):
    """Format a price with the currency symbol and the currency's decimals."""
    symbol, after, places = CURRENCIES[code]
    number = number_format(Decimal(amount), decimal_pos=places, use_l10n=False)
    return f"{number} {symbol}" if after else f"{symbol}{number}"
