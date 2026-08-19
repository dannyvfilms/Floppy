"""IMDB public non-commercial datasets provider.

Downloads title.basics.tsv.gz, title.principals.tsv.gz, and name.basics.tsv.gz
from https://datasets.imdbws.com/ (updated daily, free for non-commercial use)
and returns parsed data used to resolve a video game's IMDB title and pull its
cast/crew. Each function streams the gzip response and discards rows that
don't match the requested filter to keep memory low.
"""

import csv
import gzip
import logging
import urllib.request

logger = logging.getLogger(__name__)

TITLE_BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
PRINCIPALS_URL = "https://datasets.imdbws.com/title.principals.tsv.gz"
NAME_BASICS_URL = "https://datasets.imdbws.com/name.basics.tsv.gz"

_DOWNLOAD_TIMEOUT = 120
_VIDEO_GAME_TITLE_TYPE = "videoGame"


def download_videogame_title_index() -> dict[str, tuple[str, int | None]]:
    """Download and parse title.basics.tsv.gz, filtered to video game titles.

    Returns {tconst: (primaryTitle, startYear)}. startYear is None when IMDB
    doesn't have a release year on file for that title.
    """
    logger.info(
        "imdb_datasets: downloading title index from %s",
        TITLE_BASICS_URL,
    )
    index: dict[str, tuple[str, int | None]] = {}

    with (
        urllib.request.urlopen(TITLE_BASICS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("titleType") != _VIDEO_GAME_TITLE_TYPE:
                continue
            tconst = row.get("tconst", "").strip()
            title = row.get("primaryTitle", "").strip()
            if not tconst or not title:
                continue
            year_raw = (row.get("startYear") or "").strip()
            year = int(year_raw) if year_raw and year_raw != "\\N" else None
            index[tconst] = (title, year)

    logger.info("imdb_datasets: loaded %d video game titles", len(index))
    return index


def download_principals(tconsts: set[str]) -> dict[str, list[dict]]:
    """Download and parse title.principals.tsv.gz, filtered to tconsts.

    Returns {tconst: [{"nconst", "category", "job", "characters", "ordering"}]}.
    """
    if not tconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading principals for %d titles from %s",
        len(tconsts),
        PRINCIPALS_URL,
    )
    result: dict[str, list[dict]] = {}

    with (
        urllib.request.urlopen(PRINCIPALS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row.get("tconst", "").strip()
            if tconst not in tconsts:
                continue
            nconst = row.get("nconst", "").strip()
            if not nconst:
                continue
            ordering_raw = (row.get("ordering") or "").strip()
            try:
                ordering = int(ordering_raw) if ordering_raw else None
            except (ValueError, TypeError):
                ordering = None
            result.setdefault(tconst, []).append(
                {
                    "nconst": nconst,
                    "category": (row.get("category") or "").strip(),
                    "job": _clean_optional(row.get("job")),
                    "characters": _clean_optional(row.get("characters")),
                    "ordering": ordering,
                },
            )

    logger.info("imdb_datasets: principals loaded for %d titles", len(result))
    return result


def download_names(nconsts: set[str]) -> dict[str, str]:
    """Download and parse name.basics.tsv.gz, filtered to nconsts.

    Returns {nconst: primaryName}.
    """
    if not nconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading names for %d people from %s",
        len(nconsts),
        NAME_BASICS_URL,
    )
    names: dict[str, str] = {}

    with (
        urllib.request.urlopen(NAME_BASICS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            nconst = row.get("nconst", "").strip()
            if nconst not in nconsts:
                continue
            name = (row.get("primaryName") or "").strip()
            if name:
                names[nconst] = name

    logger.info("imdb_datasets: loaded %d names", len(names))
    return names


def _clean_optional(value: str | None) -> str:
    r"""IMDB datasets use the literal string "\\N" for nulls; normalize to ""."""
    value = (value or "").strip()
    return "" if value == "\\N" else value
