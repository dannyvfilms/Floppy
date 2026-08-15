"""Shared game-title normalisation for store-to-IGDB name matching.

Game stores decorate titles in ways IGDB doesn't -- trademark symbols,
platform suffixes, edition names, publisher brand prefixes. These helpers
strip that decoration so a name search can recover the base title. The
platform-specific store suffix pattern (Xbox's "(Windows)", PlayStation's
"PS4 & PS5", ...) is supplied by each importer; everything else is common.
"""

import re

DASHES = "-" + chr(0x2013) + chr(0x2014)  # hyphen, en dash, em dash
TRADEMARK_RE = re.compile(r"[®™©]")
# Curly apostrophes and superscript digits never appear in IGDB names.
CHAR_NORMALIZATIONS = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u00b2": " 2", "\u00b3": " 3"},
)
BRACKETED_TITLE_RE = re.compile(r"^\[(.+)\]$")

# Edition suffixes and publisher brand prefixes rename the same game; IGDB
# indexes the plain title.
EDITION_SUFFIX_RE = re.compile(
    r"\s*(?:[" + DASHES + r":]\s*)?(?:"
    r"(?:definitive|standard|ultimate|deluxe|complete|enhanced|gold|special|"
    r"digital|campaign|game\s+of\s+the\s+year|goty)\s+edition"
    r"|base\s+game"
    r"|complete"
    r")\s*$",
    re.IGNORECASE,
)
BRAND_PREFIX_RE = re.compile(r"^(?:ea\s+sports|ea|disney)\s+", re.IGNORECASE)


def search_names(name, store_suffix_re):
    """Yield search candidates, most faithful first.

    The title as the store reports it, then simplified, then with
    edition/brand decorations stripped. Numeral variants ("Alan Wake 2" vs
    "Alan Wake II") are covered by the IGDB search matching alternative names.
    """
    simplified = simplify_title(name, store_suffix_re)
    seen = []
    for candidate in (name, simplified, strip_decorations(simplified)):
        cleaned = candidate.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
            yield cleaned


def simplify_title(name, store_suffix_re):
    """Strip trademark symbols and store decorations from a title."""
    simplified = TRADEMARK_RE.sub("", name).translate(CHAR_NORMALIZATIONS)
    # Applied repeatedly: "Ghost Recon Breakpoint - Xbox Series X|S (Windows)".
    while True:
        stripped = store_suffix_re.sub("", simplified).strip(" " + DASHES + ":")
        if stripped == simplified or not stripped:
            break
        simplified = stripped
    bracketed = BRACKETED_TITLE_RE.match(simplified)
    if bracketed:
        simplified = bracketed.group(1)
    return " ".join(simplified.split())


def strip_decorations(name):
    """Strip edition suffixes and publisher brand prefixes from a title."""
    stripped = EDITION_SUFFIX_RE.sub("", name).strip(" " + DASHES + ":")
    stripped = BRAND_PREFIX_RE.sub("", stripped).strip()
    return stripped or name
