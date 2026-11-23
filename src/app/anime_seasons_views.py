"""Discover's Anime Seasons page: the MyAnimeList seasonal anime grid."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from app.anime_seasons import (
    anime_seasons_page_model,
    load_anime_season,
    normalize_query,
)
from app.discover_views import discover_enabled_required


@login_required
@require_GET
@discover_enabled_required
def anime_seasons_page(request):
    """Render one season; the shared page owns the heading, filters and states.

    The cards stay server-rendered media cards (Track popup, status chip and
    hover actions included) in a page slot, as the library grid does.
    """
    query = normalize_query(request.GET)
    entries, total, error = load_anime_season(request.user, query)
    return render(
        request,
        "app/anime_seasons.html",
        {
            "entries": entries,
            "page_props": anime_seasons_page_model(query, entries, total, error),
        },
    )
