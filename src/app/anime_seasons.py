"""Anime Seasons: one MyAnimeList seasonal listing as a page model.

The web page (``anime_seasons_views``) and ``/api/v1/discover/anime-seasons/``
both build the page here, so the season, filters, states and copy match on
every platform. Nothing here writes: Discover recommendations and their caches
are not touched.
"""

import logging
from datetime import date

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from app.models import Anime, Item, MediaTypes, Sources, Status
from app.providers import credentials, mal, services

logger = logging.getLogger(__name__)

# MAL names its quarterly seasons ("cours") after the calendar season in which
# they start: winter is January to March, spring April to June, and so on.
ANIME_SEASONS = ("winter", "spring", "summer", "fall")
# MAL's seasonal archive starts in 1917; nothing earlier can return results.
ANIME_SEASON_MIN_YEAR = 1917
# Seasons are announced about a year ahead; allow a margin beyond that.
ANIME_SEASON_FUTURE_YEARS = 2
ANIME_SEASON_FORMATS = ("all", "tv", "movie", "ova", "ona", "special", "music")
# Each sort's natural first direction: most popular, highest score, A to Z.
ANIME_SEASON_SORTS = {"popularity": "desc", "score": "desc", "title": "asc"}
UNTRACKED = "untracked"
ANIME_SEASON_STATUSES = (UNTRACKED, *Status.values)


def anime_cour_for_date(value: date) -> tuple[int, str]:
    """Return the anime season (year and cour) that contains the given date."""
    return value.year, ANIME_SEASONS[(value.month - 1) // 3]


def adjacent_anime_cour(year: int, season: str, offset: int) -> tuple[int, str]:
    """Return the season ``offset`` cours before (negative) or after the given one."""
    index = ANIME_SEASONS.index(season) + offset
    return year + index // len(ANIME_SEASONS), ANIME_SEASONS[index % len(ANIME_SEASONS)]


def _max_year():
    return timezone.localdate().year + ANIME_SEASON_FUTURE_YEARS


def _season_names():
    return {
        "winter": pgettext("anime season", "Winter"),
        "spring": pgettext("anime season", "Spring"),
        "summer": pgettext("anime season", "Summer"),
        "fall": pgettext("anime season", "Fall"),
    }


def season_label(year, season):
    """Return a season's display name, such as "Fall 2026"."""
    return f"{_season_names()[season]} {year}"


def normalize_query(params):
    """Read a query mapping, replacing any unknown value with its default."""
    current_year, current_season = anime_cour_for_date(timezone.localdate())
    season = str(params.get("season") or current_season).lower()
    if season not in ANIME_SEASONS:
        season = current_season
    try:
        year = int(params.get("year", current_year))
    except (TypeError, ValueError):
        year = current_year
    if not ANIME_SEASON_MIN_YEAR <= year <= _max_year():
        year = current_year
    anime_format = str(params.get("format") or "all").lower()
    if anime_format not in ANIME_SEASON_FORMATS:
        anime_format = "all"
    sort = str(params.get("sort") or "popularity").lower()
    if sort not in ANIME_SEASON_SORTS:
        sort = "popularity"
    direction = str(params.get("direction") or "").lower()
    if direction not in {"asc", "desc"}:
        direction = ANIME_SEASON_SORTS[sort]
    statuses = [
        value
        for value in str(params.get("statuses") or "").split(",")
        if value in ANIME_SEASON_STATUSES
    ]
    return {
        "year": year,
        "season": season,
        "format": anime_format,
        "sort": sort,
        "direction": direction,
        "statuses": list(dict.fromkeys(statuses)),
    }


def _sorted(entries, sort, direction):
    """Order entries; missing values always go last and the title breaks ties."""
    reverse = direction == "desc"

    def title(entry):
        return entry["title"].casefold()

    if sort == "title":
        return sorted(entries, key=title, reverse=reverse)
    if sort == "score":
        field, sign = "score", 1
    else:
        # MAL ranks popularity from 1, so a lower rank is more popular.
        field, sign = "popularity_rank", -1
    present = sorted(
        (entry for entry in entries if entry[field] is not None),
        key=title,
    )
    present.sort(key=lambda entry: sign * entry[field], reverse=reverse)
    missing = sorted((entry for entry in entries if entry[field] is None), key=title)
    return present + missing


def _with_tracking(user, anime):
    """Attach each entry's Item and the user's Anime row, in two queries."""
    items = {
        item.media_id: item
        for item in Item.objects.filter(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            media_id__in=[entry["media_id"] for entry in anime],
        )
    }
    tracked = {
        media.item_id: media
        for media in Anime.objects.filter(
            user=user,
            item_id__in=[item.id for item in items.values()],
        )
    }
    entries = []
    for entry in anime:
        item = items.get(entry["media_id"])
        if item is None:
            # Unsaved: the card only needs it to build links and the track action.
            item = Item(
                media_id=entry["media_id"],
                source=entry["source"],
                media_type=entry["media_type"],
                title=entry["title"],
                original_title=entry["original_title"],
                localized_title=entry["localized_title"],
                image=entry["image"],
            )
        entries.append({**entry, "item": item, "media": tracked.get(item.id)})
    return entries


def _settings_url():
    return reverse("provider_detail", kwargs={"slug": Sources.MAL.value})


def load_anime_season(user, query):
    """Return the season's filtered and sorted entries, the listing size and any error.

    The error is a dict for the page's error state, or None.
    """
    year, season = query["year"], query["season"]
    if not credentials.is_configured(Sources.MAL.value, user=user):
        return (
            [],
            0,
            {
                "title": _("MyAnimeList is not set up"),
                "body": _(
                    "Add a MyAnimeList client ID in the provider settings to browse "
                    "seasonal anime.",
                ),
                "settingsUrl": _settings_url(),
            },
        )
    try:
        anime = mal.seasonal_anime(year, season)
    except services.ProviderAPIError as exc:
        logger.warning(
            "MAL seasonal anime failed year=%s season=%s status=%s",
            year,
            season,
            exc.status_code,
        )
        rejected = exc.status_code in {400, 401, 403}
        return (
            [],
            0,
            {
                "title": _("This season could not be loaded"),
                "body": str(exc),
                "settingsUrl": _settings_url() if rejected else "",
            },
        )

    total = len(anime)
    if query["format"] != "all":
        anime = [entry for entry in anime if entry["format"] == query["format"]]
    entries = _with_tracking(user, anime)
    if query["statuses"]:
        wanted = set(query["statuses"])
        entries = [
            entry
            for entry in entries
            if (entry["media"].status if entry["media"] else UNTRACKED) in wanted
        ]
    return _sorted(entries, query["sort"], query["direction"]), total, None


def _link(year, season):
    """Return a neighbouring season inside the browsable range, else None."""
    if ANIME_SEASON_MIN_YEAR <= year <= _max_year():
        return {"year": year, "season": season, "label": season_label(year, season)}
    return None


def _options(current_year, current_season):
    """Return the FilterBar options: Season, Year and Format, the statuses and sorts."""
    names = _season_names()

    def choices(pairs):
        return [{"value": value, "label": str(label)} for value, label in pairs]

    return {
        "sections": [
            {
                "key": "season",
                "label": pgettext("anime season", "Season"),
                "type": "single",
                # The current season is the default, so it reads as no filter.
                "clearValue": current_season,
                "idleLabel": str(names[current_season]),
                "options": choices(names.items()),
            },
            {
                # Not "year": the FilterBar files a "year" section under Release date.
                "key": "season_year",
                "label": _("Year"),
                "type": "single",
                "searchable": True,
                "clearValue": str(current_year),
                "idleLabel": str(current_year),
                "options": [
                    {"value": str(year), "label": str(year)}
                    for year in range(_max_year(), ANIME_SEASON_MIN_YEAR - 1, -1)
                ],
            },
            {
                "key": "format",
                "label": _("Format"),
                "type": "single",
                "clearValue": "all",
                "idleLabel": str(_("All formats")),
                "options": choices(
                    [
                        ("all", _("All formats")),
                        ("tv", _("TV")),
                        ("movie", _("Movies")),
                        ("ova", _("OVA")),
                        ("ona", _("ONA")),
                        ("special", _("Specials")),
                        ("music", _("Music")),
                    ],
                ),
            },
        ],
        "statuses": choices(
            # Status labels are gettext_noop markers, translated here.
            [
                (UNTRACKED, _("Not tracked")),
                *((value, _(label)) for value, label in Status.choices),
            ],
        ),
        "sorts": choices(
            [
                ("popularity", _("Popularity")),
                ("score", _("Score")),
                ("title", _("Title")),
            ],
        ),
    }


def anime_seasons_page_model(query, entries, total, error):
    """Return the shared page model for one season (without the cards)."""
    year, season = query["year"], query["season"]
    current_year, current_season = anime_cour_for_date(timezone.localdate())
    if error:
        state = "error"
    elif entries:
        state = "ready"
    else:
        state = "empty"
    return {
        "query": query,
        "season": {
            "year": year,
            "season": season,
            "label": season_label(year, season),
        },
        "previous": _link(*adjacent_anime_cour(year, season, -1)),
        "next": _link(*adjacent_anime_cour(year, season, 1)),
        "filters": {
            "fields": {
                "season": season,
                "season_year": str(year),
                "format": query["format"],
            },
            "statuses": query["statuses"],
            "sort": query["sort"],
            "direction": query["direction"],
        },
        "options": _options(current_year, current_season),
        "state": state,
        "count": len(entries),
        "empty": {
            "title": _("No anime found"),
            "body": _("No anime match these filters.")
            if total
            else _("MyAnimeList has no anime listed for this season yet."),
        },
        "error": error,
        "labels": {
            "title": _("Anime Seasons"),
            "subtitle": _("Seasonal anime from MyAnimeList."),
            "countLabel": _("anime"),
            "previous": _("Previous season"),
            "next": _("Next season"),
            "openSettings": _("Open MyAnimeList settings"),
            "retry": _("Try again"),
            "loading": _("Loading the season…"),
            "filters": _("Filters"),
            "status": _("Status"),
            "allStatuses": _("All statuses"),
            "sort": _("Sort"),
            "clear": _("Clear"),
            "clearAll": _("Clear all filters"),
            "clearStatus": _("Clear status filter"),
            "ascending": _("ascending"),
            "descending": _("descending"),
        },
    }


def anime_season_cards(user, request, entries):
    """Return each entry's shared media card model, keyed for the grid."""
    from app.card_surfaces import card_context
    from app.media_card_model import card_model

    page = {"user": user, "request": request}
    return [
        {
            "key": f"{entry['source']}-{entry['media_id']}",
            "card": card_model(
                card_context(
                    page,
                    "search",
                    {
                        "item": entry["item"],
                        "media": entry["media"],
                        "title": entry["title"],
                        "card_media_type": MediaTypes.ANIME.value,
                        "subtitle_override": entry["release_date"],
                    },
                ),
            ),
        }
        for entry in entries
    ]
