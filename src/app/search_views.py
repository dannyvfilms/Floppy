import logging

from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from app import helpers
from app.log_safety import exception_summary
from app.models import (
    AlbumTracker,
    ArtistTracker,
    BasicMedia,
    Item,
    MediaTypes,
    PodcastShowTracker,
    Sources,
)
from app.providers import services
from app.services import metadata_resolution
from app.templatetags.app_tags import media_url, music_album_url, music_artist_url
from users.models import VALID_SEARCH_TYPES, MediaStatusChoices

logger = logging.getLogger(__name__)

# Minimum characters before the search bar fires autocomplete suggestions.
MIN_SUGGESTION_QUERY_LENGTH = 2


def _mark_grouped_anime_route(media_items):
    """Annotate grouped-anime rows so templates route them through the Anime UI."""
    for media in media_items or []:
        media.route_media_type = MediaTypes.ANIME.value
        item = getattr(media, "item", None)
        if item is not None:
            item.route_media_type = MediaTypes.ANIME.value
    return media_items


def _norm(text):
    return str(text or "").strip().casefold()


def _title_fields(item_obj):
    if isinstance(item_obj, dict):
        return (
            item_obj.get("title"),
            item_obj.get("original_title"),
            item_obj.get("localized_title"),
        )
    return (
        getattr(item_obj, "title", None),
        getattr(item_obj, "original_title", None),
        getattr(item_obj, "localized_title", None),
    )


def _display_title_for_user(item_obj, user):
    if hasattr(item_obj, "get_display_title"):
        return item_obj.get_display_title(user=user)

    title, original_title, localized_title = _title_fields(item_obj)
    title = str(title or "").strip()
    original_title = str(original_title or "").strip() or None
    localized_title = str(localized_title or "").strip() or None

    if not localized_title and title:
        localized_title = title

    preference = getattr(user, "title_display_preference", "localized")
    if preference == "original":
        return original_title or localized_title or title
    return localized_title or original_title or title


def _matched_title(item_obj, search_query, user):
    normalized_query = _norm(search_query)
    if not normalized_query:
        return None

    display_title = _display_title_for_user(item_obj, user)
    display_norm = _norm(display_title)

    title, original_title, localized_title = _title_fields(item_obj)
    candidates = []
    for candidate in (title, localized_title, original_title):
        text = str(candidate or "").strip()
        if text and text not in candidates:
            candidates.append(text)

    # Prefer exact, then prefix, then contains.
    for predicate in (
        lambda value: _norm(value) == normalized_query,
        lambda value: _norm(value).startswith(normalized_query),
        lambda value: normalized_query in _norm(value),
    ):
        for candidate in candidates:
            if _norm(candidate) == display_norm:
                continue
            if predicate(candidate):
                return candidate
    return None


@require_GET
def media_search(request):
    """Return the media search page."""
    requested_media_type = request.GET["media_type"]
    if request.user.is_authenticated:
        media_type = request.user.update_preference(
            "last_search_type",
            requested_media_type,
        )
    elif requested_media_type in VALID_SEARCH_TYPES:
        media_type = requested_media_type
    else:
        media_type = MediaTypes.TV.value
    query = request.GET["q"]
    page = int(request.GET.get("page", 1))
    layout = request.GET.get("layout", "grid")

    local_results = []
    local_results_total = 0
    local_results_limit = 24
    local_results_kind = "media"
    local_music_artists = []
    local_music_artists_total = 0
    local_music_albums = []
    local_music_albums_total = 0
    if request.user.is_authenticated and query and page == 1:
        try:
            if media_type == MediaTypes.PODCAST.value:
                show_trackers = (
                    PodcastShowTracker.objects.filter(user=request.user)
                    .exclude(show__title__isnull=True)
                    .exclude(show__title__exact="")
                    .filter(show__title__icontains=query)
                )
                local_results_total = show_trackers.count()
                show_trackers = show_trackers.order_by("show__title")[
                    :local_results_limit
                ]

                class PodcastShowAdapter:
                    """Adapter to make PodcastShowTracker compatible with media components."""

                    def __init__(self, tracker):
                        self.tracker = tracker
                        self.id = tracker.id
                        self.status = tracker.status
                        self.score = tracker.score
                        self.start_date = tracker.start_date
                        self.end_date = tracker.end_date
                        self.notes = tracker.notes
                        self.created_at = tracker.created_at
                        self.updated_at = tracker.updated_at

                        self.item, _ = Item.objects.get_or_create(
                            media_id=tracker.show.podcast_uuid,
                            source=Sources.POCKETCASTS.value,
                            media_type=MediaTypes.PODCAST.value,
                            defaults={
                                "title": tracker.show.title,
                                "image": tracker.show.image or settings.IMG_NONE,
                            },
                        )
                        show_image = tracker.show.image or settings.IMG_NONE
                        if (
                            self.item.title != tracker.show.title
                            or self.item.image != show_image
                        ):
                            self.item.title = tracker.show.title
                            self.item.image = show_image
                            self.item.save(update_fields=["title", "image"])

                adapted_media = [
                    PodcastShowAdapter(tracker) for tracker in show_trackers
                ]
                local_results = [
                    {
                        "item": media.item,
                        "media": media,
                        "matched_title": _matched_title(
                            media.item, query, request.user
                        ),
                    }
                    for media in adapted_media
                ]
            elif media_type == MediaTypes.MUSIC.value:
                artist_trackers = (
                    ArtistTracker.objects.filter(user=request.user)
                    .exclude(artist__name__isnull=True)
                    .exclude(artist__name__exact="")
                    .filter(artist__name__icontains=query)
                    .select_related("artist")
                )
                local_music_artists_total = artist_trackers.count()
                local_music_artists = list(
                    artist_trackers.order_by("artist__name")[:local_results_limit]
                )

                album_trackers = (
                    AlbumTracker.objects.filter(user=request.user)
                    .exclude(album__title__isnull=True)
                    .exclude(album__title__exact="")
                    .filter(
                        Q(album__title__icontains=query)
                        | Q(album__artist__name__icontains=query),
                    )
                    .select_related("album", "album__artist")
                    .prefetch_related("album__artist_credits__artist")
                )
                local_music_albums_total = album_trackers.count()
                local_music_albums = list(
                    album_trackers.order_by("album__title")[:local_results_limit]
                )

                local_results_total = (
                    local_music_artists_total + local_music_albums_total
                )
                local_results_kind = "music"
            else:
                local_queryset = BasicMedia.objects.get_media_list(
                    request.user,
                    media_type,
                    MediaStatusChoices.ALL,
                    "title",
                    search=query,
                    direction="asc",
                )
                local_media = list(local_queryset)
                if (
                    media_type == MediaTypes.TV.value
                    and getattr(
                        request.user,
                        "anime_library_mode",
                        MediaTypes.ANIME.value,
                    )
                    == MediaTypes.ANIME.value
                ):
                    local_media = [
                        media
                        for media in local_media
                        if getattr(
                            getattr(media, "item", None), "library_media_type", None
                        )
                        != MediaTypes.ANIME.value
                    ]
                elif media_type == MediaTypes.ANIME.value and getattr(
                    request.user,
                    "anime_library_mode",
                    MediaTypes.ANIME.value,
                ) in {MediaTypes.ANIME.value, "both"}:
                    grouped_local_media = list(
                        BasicMedia.objects.get_media_list(
                            request.user,
                            MediaTypes.TV.value,
                            MediaStatusChoices.ALL,
                            "title",
                            search=query,
                            direction="asc",
                        ),
                    )
                    grouped_local_media = [
                        media
                        for media in grouped_local_media
                        if getattr(
                            getattr(media, "item", None), "library_media_type", None
                        )
                        == MediaTypes.ANIME.value
                    ]
                    _mark_grouped_anime_route(grouped_local_media)
                    local_media.extend(grouped_local_media)
                    local_media.sort(
                        key=lambda media: getattr(
                            getattr(media, "item", None),
                            "title",
                            "",
                        ).lower(),
                    )

                local_results_total = len(local_media)
                local_media = local_media[:local_results_limit]
                BasicMedia.objects.annotate_max_progress(local_media, media_type)
                local_results = [
                    {
                        "item": media.item,
                        "media": media,
                        "matched_title": _matched_title(
                            media.item, query, request.user
                        ),
                    }
                    for media in local_media
                ]
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Local search failed: %s", exception_summary(exc))

    source_options = metadata_resolution.available_metadata_sources(media_type)
    default_source = metadata_resolution.metadata_default_source(
        request.user,
        media_type,
    )
    # only receives source when searching with secondary source
    source = request.GET.get("source", default_source)
    if source not in {option.value for option in source_options} and source_options:
        source = source_options[0].value

    search_page = 1 if media_type == MediaTypes.MUSIC.value else page
    data = services.search(
        media_type,
        query,
        search_page,
        source,
        language=metadata_resolution.metadata_language_default(request.user),
    )

    if media_type == MediaTypes.MUSIC.value:
        context = {
            "user": request.user,
            "data": data,
            "music_online_artists": data.get("artists", []),
            "music_online_releases": data.get("releases", []),
            "source": source,
            "source_options": source_options,
            "media_type": media_type,
            "layout": layout,
            "local_results": local_results,
            "local_results_total": local_results_total,
            "local_results_limit": local_results_limit,
            "local_results_kind": local_results_kind,
            "local_music_artists": local_music_artists,
            "local_music_artists_total": local_music_artists_total,
            "local_music_albums": local_music_albums,
            "local_music_albums_total": local_music_albums_total,
        }
        return render(request, "app/search.html", context)

    # Enrich search results with user tracking data
    if data.get("results"):
        data["results"] = helpers.enrich_items_with_user_data(
            request,
            data["results"],
            section_name="search",
        )
        for result in data["results"]:
            result["matched_title"] = _matched_title(
                result.get("item"), query, request.user
            )

    context = {
        "user": request.user,
        "data": data,
        "source": source,
        "source_options": source_options,
        "media_type": media_type,
        "layout": layout,
        "local_results": local_results,
        "local_results_total": local_results_total,
        "local_results_limit": local_results_limit,
        "local_results_kind": local_results_kind,
    }

    return render(request, "app/search.html", context)


def _safe_url(builder, target):
    """Return a detail URL for a suggestion, or None if it can't be built."""
    try:
        url = builder(target)
    except Exception:  # pragma: no cover - defensive against reverse failures
        return None
    return url or None


def get_saved_suggestions(user, media_type, query, limit=8):
    """Return compact autocomplete suggestions from the user's saved library.

    Saved items only, scoped to ``media_type``. Each suggestion is a dict of
    ``{title, subtitle, image, url}``. Mirrors the local-results queries used by
    :func:`media_search` but capped small and side-effect free for typeahead.
    """
    suggestions = []

    if media_type == MediaTypes.PODCAST.value:
        show_trackers = (
            PodcastShowTracker.objects.filter(user=user)
            .exclude(show__title__isnull=True)
            .exclude(show__title__exact="")
            .filter(show__title__icontains=query)
            .select_related("show")
            .order_by("show__title")[:limit]
        )
        for tracker in show_trackers:
            show = tracker.show
            url = _safe_url(
                media_url,
                {
                    "media_type": MediaTypes.PODCAST.value,
                    "source": Sources.POCKETCASTS.value,
                    "media_id": show.podcast_uuid,
                    "title": show.title,
                },
            )
            if url:
                suggestions.append(
                    {
                        "title": show.title,
                        "subtitle": None,
                        "image": show.image or None,
                        "url": url,
                    }
                )
        return suggestions

    if media_type == MediaTypes.MUSIC.value:
        artist_trackers = (
            ArtistTracker.objects.filter(user=user)
            .exclude(artist__name__isnull=True)
            .exclude(artist__name__exact="")
            .filter(artist__name__icontains=query)
            .select_related("artist")
            .order_by("artist__name")[:limit]
        )
        for tracker in artist_trackers:
            url = _safe_url(music_artist_url, tracker.artist)
            if url:
                suggestions.append(
                    {
                        "title": tracker.artist.name,
                        "subtitle": "Artist",
                        "image": getattr(tracker.artist, "image", None) or None,
                        "url": url,
                    }
                )

        album_trackers = (
            AlbumTracker.objects.filter(user=user)
            .exclude(album__title__isnull=True)
            .exclude(album__title__exact="")
            .filter(
                Q(album__title__icontains=query)
                | Q(album__artist__name__icontains=query),
            )
            .select_related("album", "album__artist")
            .order_by("album__title")[:limit]
        )
        for tracker in album_trackers:
            url = _safe_url(music_album_url, tracker.album)
            if url:
                album_artist = getattr(tracker.album, "artist", None)
                artist_name = getattr(album_artist, "name", None)
                suggestions.append(
                    {
                        "title": tracker.album.title,
                        "subtitle": artist_name or "Album",
                        "image": getattr(tracker.album, "image", None) or None,
                        "url": url,
                    }
                )
        return suggestions[:limit]

    local_queryset = BasicMedia.objects.get_media_list(
        user,
        media_type,
        MediaStatusChoices.ALL,
        "title",
        search=query,
        direction="asc",
    )
    local_media = list(local_queryset)

    anime_mode = getattr(user, "anime_library_mode", MediaTypes.ANIME.value)
    if media_type == MediaTypes.TV.value and anime_mode == MediaTypes.ANIME.value:
        local_media = [
            media
            for media in local_media
            if getattr(getattr(media, "item", None), "library_media_type", None)
            != MediaTypes.ANIME.value
        ]
    elif media_type == MediaTypes.ANIME.value and anime_mode in {
        MediaTypes.ANIME.value,
        "both",
    }:
        grouped = [
            media
            for media in BasicMedia.objects.get_media_list(
                user,
                MediaTypes.TV.value,
                MediaStatusChoices.ALL,
                "title",
                search=query,
                direction="asc",
            )
            if getattr(getattr(media, "item", None), "library_media_type", None)
            == MediaTypes.ANIME.value
        ]
        _mark_grouped_anime_route(grouped)
        local_media.extend(grouped)
        local_media.sort(
            key=lambda media: getattr(
                getattr(media, "item", None),
                "title",
                "",
            ).lower(),
        )

    for media in local_media[:limit]:
        item = getattr(media, "item", None)
        if item is None:
            continue
        url = _safe_url(media_url, item)
        if not url:
            continue
        suggestions.append(
            {
                "title": _display_title_for_user(item, user),
                "subtitle": _matched_title(item, query, user),
                "image": getattr(item, "image", None) or None,
                "url": url,
            }
        )
    return suggestions


@require_GET
def search_suggestions(request):
    """Return the autocomplete dropdown fragment for the global search bar."""
    query = request.GET.get("q", "").strip()
    media_type = request.GET.get("media_type", "")

    if (
        not request.user.is_authenticated
        or len(query) < MIN_SUGGESTION_QUERY_LENGTH
        or media_type not in {choice.value for choice in MediaTypes}
    ):
        return render(request, "app/components/search_suggestions.html")

    try:
        suggestions = get_saved_suggestions(request.user, media_type, query)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Suggestion search failed: %s", exception_summary(exc))
        suggestions = []

    return render(
        request,
        "app/components/search_suggestions.html",
        {
            "suggestions": suggestions,
            "query": query,
            "media_type": media_type,
        },
    )
