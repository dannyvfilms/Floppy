"""Conservative title matching shared by provider-backed integrations."""

import re
import unicodedata

_TRAILING_YEAR_RE = re.compile(r"\s*(?:\(\d{4}\)|\[\d{4}\])\s*$")
_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


def normalize_title(value):
    """Return a comparison form for a human-facing title.

    This deliberately does not do fuzzy matching.  Punctuation, accents,
    apostrophes, ampersands, and a year suffix are presentation details; words
    and their order remain significant.
    """
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    value = _TRAILING_YEAR_RE.sub("", value)
    return " ".join(_NON_WORD_RE.sub(" ", value).split())


def _result_id(result):
    """Return the provider id from either search-result shape."""
    if not isinstance(result, dict):
        return None
    value = result.get("media_id") or result.get("id")
    return str(value) if value not in (None, "") else None


def _result_titles(result):
    """Yield every provider title that can legitimately represent a result."""
    if not isinstance(result, dict):
        return
    for key in ("title", "original_title", "localized_title", "name", "original_name"):
        value = result.get(key)
        if value:
            yield value


def unique_title_match(results, title, *, year=None):
    """Return one exact normalized-title result, or ``None``.

    A year narrows the candidates but never replaces title agreement.  Multiple
    provider ids remain ambiguous even when their display titles are identical;
    callers must queue those rows for review instead of guessing.
    """
    normalized_title = normalize_title(title)
    if not normalized_title:
        return None

    expected_year = str(year) if year not in (None, "") else None
    candidates = []
    seen_ids = set()
    for result in results or []:
        result_id = _result_id(result)
        if not result_id or result_id in seen_ids:
            continue
        if expected_year is not None:
            result_year = result.get("year")
            if result_year in (None, ""):
                result_year = (
                    result.get("release_date")
                    or result.get("first_air_date")
                    or result.get("originally_available_at")
                )
                if result_year:
                    result_year = str(result_year).split("-", 1)[0]
            if result_year in (None, "") or str(result_year) != expected_year:
                continue
        if not any(
            normalize_title(candidate_title) == normalized_title
            for candidate_title in _result_titles(result)
        ):
            continue
        seen_ids.add(result_id)
        candidates.append(result)

    return candidates[0] if len(candidates) == 1 else None
