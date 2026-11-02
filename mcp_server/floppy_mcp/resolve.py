"""Candidate matching for resolve_game.

Pure functions: no I/O, so the matching rules are unit-testable without HTTP.
Matching is deliberately literal. A candidate is only called a match on a
field when the provider data says so; missing data is reported as unknown
(None), never as a mismatch and never as a numerical confidence.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Short names people use -> the provider's platform name, normalized.
_PLATFORM_ALIASES = {
    "n64": "nintendo 64",
    "gc": "nintendo gamecube",
    "gcn": "nintendo gamecube",
    "gamecube": "nintendo gamecube",
    "ds": "nintendo ds",
    "nds": "nintendo ds",
    "3ds": "nintendo 3ds",
    "switch": "nintendo switch",
    "nes": "nintendo entertainment system nes",
    "snes": "super nintendo entertainment system snes",
    "gb": "game boy",
    "gbc": "game boy color",
    "gba": "game boy advance",
    "ps1": "playstation",
    "psx": "playstation",
    "ps": "playstation",
    "ps2": "playstation 2",
    "ps3": "playstation 3",
    "ps4": "playstation 4",
    "ps5": "playstation 5",
    "pc": "pc microsoft windows",
    "windows": "pc microsoft windows",
}
# Words in a title that hint at a re-release. Reported as evidence only: the
# catalog does not say whether a row is a port, remaster or remake.
_EDITION_MARKERS = (
    "remaster",
    "remastered",
    "remake",
    "collection",
    "compilation",
    "trilogy",
    "definitive",
    "anniversary",
    "ambassador",
    "deluxe",
    "edition",
    "hd",
)


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"^the ", "", text)


def _norm_platform(name: Any) -> str:
    norm = _norm(name)
    return _PLATFORM_ALIASES.get(norm, norm)


def _title_match(candidate_title: str, wanted: list[str]) -> str | None:
    """'exact' (equal after normalising), 'partial' (token-contained) or None."""
    title = _norm(candidate_title)
    partial = False
    for name in wanted:
        if name == title:
            return "exact"
        if f" {name} " in f" {title} " or f" {title} " in f" {name} ":
            partial = True
    return "partial" if partial else None


def _platform_match(candidate: dict[str, Any], platform: str | None) -> bool | None:
    if not platform:
        return None
    have = [_norm_platform(p) for p in candidate.get("platforms") or []]
    if not have:
        return None
    return _norm_platform(platform) in have


def _year_match(
    candidate: dict[str, Any],
    year: int | None,
    year_to: int | None,
) -> bool | None:
    if year is None:
        return None
    cand_year = candidate.get("year")
    if not isinstance(cand_year, int):
        return None
    return year <= cand_year <= (year_to if year_to is not None else year)


def _candidate(
    raw: dict[str, Any],
    wanted: list[str],
    platform: str | None,
    year: int | None,
    year_to: int | None,
) -> dict[str, Any] | None:
    title_match = _title_match(raw.get("title", ""), wanted)
    if title_match is None:
        return None
    title = _norm(raw.get("title", ""))
    return {
        "source": raw.get("source"),
        "media_id": raw.get("media_id"),
        "title": raw.get("title"),
        "year": raw.get("year"),
        "platforms": raw.get("platforms") or [],
        "evidence": {
            "title": title_match,
            "platform": _platform_match(raw, platform),
            "year": _year_match(raw, year, year_to),
            "edition_words": [
                word for word in _EDITION_MARKERS if f" {word} " in f" {title} "
            ],
        },
        "original": raw,
    }


def _rank(candidate: dict[str, Any], given: tuple[bool, bool]) -> tuple[int, int, int]:
    """(contradicted, title only partial, a given constraint unproven)."""
    ev = candidate["evidence"]
    return (
        ev["platform"] is False or ev["year"] is False,
        ev["title"] != "exact",
        (given[0] and ev["platform"] is None) or (given[1] and ev["year"] is None),
    )


def resolve_candidates(
    results: list[dict[str, Any]],
    title: str,
    aliases: list[str] | None = None,
    platform: str | None = None,
    year: int | None = None,
    year_to: int | None = None,
) -> dict[str, Any]:
    """Classify provider results against a title and optional constraints.

    status:
      exact      one candidate fits every given constraint, each backed by data
      likely     one fits, but a constraint is unknown or the title only partly
                 matches: check it before relying on it
      ambiguous  several fit: the caller (or user) must choose
      no_match   nothing fits; ``candidates`` holds the near misses
    """
    wanted = [n for n in (_norm(t) for t in [title, *(aliases or [])]) if n]
    seen: set[tuple[Any, Any]] = set()
    candidates = []
    for raw in results:
        key = (raw.get("source"), raw.get("media_id"))
        if key in seen:
            continue
        seen.add(key)
        cand = _candidate(raw, wanted, platform, year, year_to)
        if cand:
            candidates.append(cand)
    given = (bool(platform), year is not None)
    candidates.sort(key=lambda c: _rank(c, given))

    fitting = [c for c in candidates if _rank(c, given)[:2] == (0, 0)]
    partial = [c for c in candidates if _rank(c, given)[:2] == (0, 1)]
    if len(fitting) > 1:
        status = "ambiguous"
    elif len(fitting) == 1:
        status = "likely" if _rank(fitting[0], given)[2] else "exact"
    elif partial:
        status = "likely" if len(partial) == 1 else "ambiguous"
    else:
        status = "no_match"

    selected = None
    if status in {"exact", "likely"}:
        pick = (fitting or partial)[0]
        selected = {"source": pick["source"], "media_id": pick["media_id"]}
    return {
        "status": status,
        "selected": selected if status == "exact" else None,
        "likely": selected if status == "likely" else None,
        "candidates": candidates,
    }
