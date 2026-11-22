"""Discover's Anime Seasons page: the MyAnimeList seasonal anime grid."""

import logging
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from django.views.decorators.http import require_GET

from app.discover_views import _discover_media_options, discover_enabled_required
from app.models import Anime, Item, MediaTypes, Sources
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
ANIME_SEASON_SORTS = ("popularity", "score", "title")


def _season_options():
    return [
        {"value": "winter", "label": pgettext("anime season", "Winter")},
        {"value": "spring", "label": pgettext("anime season", "Spring")},
        {"value": "summer", "label": pgettext("anime season", "Summer")},
        {"value": "fall", "label": pgettext("anime season", "Fall")},
    ]


def _format_options():
    return [
        {"value": "all", "label": _("All formats")},
        {"value": "tv", "label": _("TV")},
        {"value": "movie", "label": _("Movies")},
        {"value": "ova", "label": _("OVA")},
        {"value": "ona", "label": _("ONA")},
        {"value": "special", "label": _("Specials")},
        {"value": "music", "label": _("Music")},
    ]


def _sort_options():
    return [
        {"value": "popularity", "label": _("Popularity")},
        {"value": "score", "label": _("Score")},
        {"value": "title", "label": _("Title")},
    ]


def anime_cour_for_date(value: date) -> tuple[int, str]:
    """Return the anime season (year and cour) that contains the given date."""
    return value.year, ANIME_SEASONS[(value.month - 1) // 3]


def adjacent_anime_cour(year: int, season: str, offset: int) -> tuple[int, str]:
    """Return the season ``offset`` cours before (negative) or after the given one."""
    index = ANIME_SEASONS.index(season) + offset
    return year + index // len(ANIME_SEASONS), ANIME_SEASONS[index % len(ANIME_SEASONS)]


def _max_year():
    return timezone.localdate().year + ANIME_SEASON_FUTURE_YEARS


def _coerce_params(request):
    """Read the query string, replacing any unknown value with its default."""
    current_year, current_season = anime_cour_for_date(timezone.localdate())
    season = (request.GET.get("season") or current_season).lower()
    if season not in ANIME_SEASONS:
        season = current_season
    try:
        year = int(request.GET.get("year", current_year))
    except (TypeError, ValueError):
        year = current_year
    if not ANIME_SEASON_MIN_YEAR <= year <= _max_year():
        year = current_year
    anime_format = (request.GET.get("format") or "all").lower()
    if anime_format not in ANIME_SEASON_FORMATS:
        anime_format = "all"
    sort = (request.GET.get("sort") or "popularity").lower()
    if sort not in ANIME_SEASON_SORTS:
        sort = "popularity"
    return year, season, anime_format, sort


def _sorted(anime, sort):
    """Order entries by the chosen sort; missing values go last, title breaks ties."""
    if sort == "title":
        return sorted(anime, key=lambda entry: entry["title"].casefold())
    if sort == "score":
        return sorted(
            anime,
            key=lambda entry: (
                entry["score"] is None,
                -(entry["score"] or 0),
                entry["title"].casefold(),
            ),
        )
    return sorted(
        anime,
        key=lambda entry: (
            entry["popularity_rank"] is None,
            entry["popularity_rank"] or 0,
            entry["title"].casefold(),
        ),
    )


def _cards(user, anime):
    """Pair each entry with its Item and the user's Anime row, in two queries."""
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
    cards = []
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
        cards.append({"item": item, "media": tracked.get(item.id), **entry})
    return cards


def _season_link(year, season):
    """Return (year, season) when it is inside the browsable range, else None."""
    if ANIME_SEASON_MIN_YEAR <= year <= _max_year():
        return {"year": year, "season": season}
    return None


@login_required
@require_GET
@discover_enabled_required
def anime_seasons_page(request):
    """Render a MAL seasonal anime grid without changing Discover recommendations."""
    year, season, anime_format, sort = _coerce_params(request)
    error = ""
    settings_url = ""
    anime = []
    if not credentials.is_configured(Sources.MAL.value, user=request.user):
        error = _(
            "Add a MyAnimeList client ID in the provider settings to browse "
            "seasonal anime.",
        )
        settings_url = reverse("provider_detail", kwargs={"slug": Sources.MAL.value})
    else:
        try:
            anime = mal.seasonal_anime(year, season)
        except services.ProviderAPIError as exc:
            logger.warning(
                "MAL seasonal anime failed year=%s season=%s status=%s",
                year,
                season,
                exc.status_code,
            )
            error = str(exc)
            if exc.status_code in {400, 401, 403}:
                settings_url = reverse(
                    "provider_detail",
                    kwargs={"slug": Sources.MAL.value},
                )

    if anime_format != "all":
        anime = [entry for entry in anime if entry["format"] == anime_format]

    season_options = _season_options()
    previous = adjacent_anime_cour(year, season, -1)
    following = adjacent_anime_cour(year, season, 1)
    return render(
        request,
        "app/anime_seasons.html",
        {
            "cards": _cards(request.user, _sorted(anime, sort)),
            "error": error,
            "settings_url": settings_url,
            "year": year,
            "season": season,
            "season_label": next(
                option["label"]
                for option in season_options
                if option["value"] == season
            ),
            "selected_format": anime_format,
            "selected_sort": sort,
            "filters_applied": anime_format != "all" or sort != "popularity",
            "discover_media_options": _discover_media_options(request.user),
            "season_options": season_options,
            "format_options": _format_options(),
            "sort_options": _sort_options(),
            "year_options": range(_max_year(), ANIME_SEASON_MIN_YEAR - 1, -1),
            "previous_link": _season_link(*previous),
            "next_link": _season_link(*following),
        },
    )
