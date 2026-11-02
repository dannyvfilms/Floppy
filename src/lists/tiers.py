"""Tier definitions for a list's Tiers view.

A list stores its tiers as ``[{"id", "name", "color"}]`` on ``CustomList.tiers``.
An empty value means the default S to F tiers, so a list needs no setup before
its first edit. Each list item names its tier by id; a blank or unknown id means
Unranked.
"""

import re
from decimal import Decimal

MAX_TIERS = 12
# A tier board shows every item on one page; past this it says so.
TIER_BOARD_LIMIT = 300
MAX_SCORE = 10  # Floppy stores ratings on a 0-10 scale
MAX_NAME_LENGTH = 16
TIER_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_TIERS = (
    {"id": "s", "name": "S", "color": "#ff7f7f"},
    {"id": "a", "name": "A", "color": "#ffbf7f"},
    {"id": "b", "name": "B", "color": "#ffdf7f"},
    {"id": "c", "name": "C", "color": "#bfff7f"},
    {"id": "d", "name": "D", "color": "#7fbfff"},
    {"id": "f", "name": "F", "color": "#c4a7ff"},
)


def resolve_tiers(custom_list):
    """Return the list's tiers in order, falling back to the defaults."""
    return list(custom_list.tiers or DEFAULT_TIERS)


def clean_tiers(raw):
    """Return validated tiers from submitted data, or raise ``ValueError``."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_TIERS:
        msg = f"Provide between 1 and {MAX_TIERS} tiers."
        raise ValueError(msg)
    cleaned = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            msg = "Each tier must be an object."
            raise ValueError(msg)  # noqa: TRY004
        tier_id = str(entry.get("id") or "")
        name = str(entry.get("name") or "").strip()[:MAX_NAME_LENGTH]
        color = str(entry.get("color") or "")
        if not TIER_ID_PATTERN.match(tier_id) or tier_id in seen:
            msg = "Each tier needs a unique id."
            raise ValueError(msg)
        if not name or not COLOR_PATTERN.match(color):
            msg = "Each tier needs a name and a #rrggbb colour."
            raise ValueError(msg)
        seen.add(tier_id)
        cleaned.append({"id": tier_id, "name": name, "color": color.lower()})
    return cleaned


def ink_for(color):
    """Return black or white text, whichever reads better on ``color``."""
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    return "#1f2937" if 0.299 * red + 0.587 * green + 0.114 * blue > 153 else "#ffffff"  # noqa: PLR2004


def tier_index_for_score(score, tier_count):
    """Return which tier (0 is the top) a 0-10 score falls in.

    The 0-10 rating range is split evenly across the tiers, best scores first,
    so a score of 10 is in the first tier and 0 in the last. A score on the
    line between two tiers goes in the lower one.
    """
    steps = (MAX_SCORE - Decimal(str(score))) * tier_count // MAX_SCORE
    return max(0, min(int(steps), tier_count - 1))
