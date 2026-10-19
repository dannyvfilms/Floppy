import logging

from django.conf import settings
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render
from django.utils.translation import gettext
from django.views.decorators.http import require_GET

from app import helpers
from app.library_query import LibraryQueryExecutor
from app.library_query.adapters import from_media_list_filters
from app.log_safety import exception_summary
from app.media_list_filters import (
    MediaListEntry,
    MediaListFilters,
    media_list_entries_for_items,
)
from app.models import (
    AlbumTracker,
    ArtistTracker,
    BasicMedia,
    Item,
    ItemTag,
    MediaTypes,
    PodcastShowTracker,
)
from app.providers import services
from app.services import metadata_resolution
from app.templatetags.app_tags import (
    media_type_readable,
    media_type_readable_plural,
    media_url,
    music_album_url,
    music_artist_url,
)
from users.models import ALL_SEARCH_TYPE, VALID_SEARCH_TYPES, MediaStatusChoices

logger = logging.getLogger(__name__)

# Minimum characters before the search bar fires autocomplete suggestions.
MIN_SUGGESTION_QUERY_LENGTH = 2

# Per-type cap on the library-only "All" search page, which shows every
# enabled type at once (#1160).
LOCAL_GROUP_LIMIT = 12
ALL_SUGGESTIONS_PER_TYPE = 3


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


def _tagged_untracked_items(user, media_type, query, library_ids):
    """Return the user's tagged ``media_type`` items the library query does not cover.

    A tag can sit on an item with no tracker and no collection entry (#1160),
    so the library query misses it. ``library_ids`` is what that query matched
    (a subquery or a set of ids). Kept as one relational query so the caller's
    slice bounds the work.
    """
    tagged = Exists(ItemTag.objects.filter(tag__user=user, item_id=OuterRef("pk")))
    include_anime_in_anime, include_anime_in_tv = (
        metadata_resolution.anime_library_visibility(user)
    )
    grouped_anime = Q(
        media_type=MediaTypes.TV.value,
        library_media_type=MediaTypes.ANIME.value,
    )
    if media_type == MediaTypes.ANIME.value:
        type_filter = Q(media_type=MediaTypes.ANIME.value)
        if include_anime_in_anime:
            type_filter |= grouped_anime
    elif media_type == MediaTypes.TV.value:
        type_filter = Q(media_type=MediaTypes.TV.value)
        if not include_anime_in_tv:
            type_filter &= ~grouped_anime
    else:
        type_filter = Q(media_type=media_type)

    return (
        Item.objects.filter(
            type_filter,
            tagged,
            Q(title__icontains=query)
            | Q(original_title__icontains=query)
            | Q(localized_title__icontains=query),
        )
        .exclude(id__in=library_ids)
        .order_by("title", "id")
    )


def _merge_by_title(entries, extra_items, limit):
    """Merge ``MediaListEntry`` rows with media-less items by title, capped at ``limit``."""
    merged = list(entries)
    merged += [MediaListEntry(item=item, media=None) for item in extra_items[:limit]]
    merged.sort(key=lambda entry: (entry.item.title or "").lower())
    return merged[:limit]


class PodcastShowAdapter:
    """Adapter to make PodcastShowTracker compatible with media components."""

    def __init__(self, tracker):
        """Copy the tracker's fields and find or create the show's Item."""
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
            source=tracker.show.source,
            media_type=MediaTypes.PODCAST.value,
            defaults={
                "title": tracker.show.title,
                "image": tracker.show.image or settings.IMG_NONE,
            },
        )
        show_image = tracker.show.image or settings.IMG_NONE
        if self.item.title != tracker.show.title or self.item.image != show_image:
            self.item.title = tracker.show.title
            self.item.image = show_image
            self.item.save(update_fields=["title", "image"])


def _local_podcast_results(user, query, limit):
    """Return ``(results, total)`` for the user's tracked or tagged podcast shows."""
    show_trackers = (
        PodcastShowTracker.objects.filter(user=user)
        .exclude(show__title__isnull=True)
        .exclude(show__title__exact="")
        .filter(show__title__icontains=query)
    )
    # A show can be tagged without being tracked (#1160).
    tagged_only = (
        Item.objects.filter(
            Exists(ItemTag.objects.filter(tag__user=user, item_id=OuterRef("pk"))),
            media_type=MediaTypes.PODCAST.value,
            title__icontains=query,
        )
        .exclude(
            media_id__in=PodcastShowTracker.objects.filter(user=user).values(
                "show__podcast_uuid",
            ),
        )
        .order_by("title", "id")
    )
    total = show_trackers.count() + tagged_only.count()
    results = [
        {
            "item": media.item,
            "media": media,
            "matched_title": _matched_title(media.item, query, user),
        }
        for media in (
            PodcastShowAdapter(tracker)
            for tracker in show_trackers.order_by("show__title")[:limit]
        )
    ]
    results += [
        {
            "item": item,
            "media": None,
            "matched_title": _matched_title(item, query, user),
        }
        for item in tagged_only[:limit]
    ]
    results.sort(key=lambda result: (result["item"].title or "").lower())
    return results[:limit], total


def _local_music_results(user, query, limit):
    """Return the user's tracked artists and albums matching ``query``."""
    artist_trackers = (
        ArtistTracker.objects.filter(user=user)
        .exclude(artist__name__isnull=True)
        .exclude(artist__name__exact="")
        .filter(artist__name__icontains=query)
        .select_related("artist")
    )
    album_trackers = (
        AlbumTracker.objects.filter(user=user)
        .exclude(album__title__isnull=True)
        .exclude(album__title__exact="")
        .filter(
            Q(album__title__icontains=query) | Q(album__artist__name__icontains=query),
        )
        .select_related("album", "album__artist")
        .prefetch_related("album__artist_credits__artist")
    )
    return {
        "artists": list(artist_trackers.order_by("artist__name")[:limit]),
        "artists_total": artist_trackers.count(),
        "albums": list(album_trackers.order_by("album__title")[:limit]),
        "albums_total": album_trackers.count(),
    }


def _local_media_results(user, media_type, query, limit, *, annotate_progress=True):
    """Return ``(results, total)`` for tracked, collected or tagged ``media_type`` items.

    Only the first ``limit`` items are loaded; the total is counted in SQL.
    """
    # Every status plus "no status", so an imported rating with no status and
    # a collected-only item both count (the media list's "everything" view).
    filters = MediaListFilters(
        statuses=tuple(
            value
            for value in MediaStatusChoices.values
            if value != MediaStatusChoices.ALL
        ),
        include_no_status=True,
        search=query,
        sort="title",
        direction="asc",
    )
    executor = LibraryQueryExecutor(
        user,
        from_media_list_filters(filters, (media_type,)),
    )
    library_total = executor.count()
    entries = media_list_entries_for_items(
        user,
        executor.page(0, limit, total=library_total).items,
    )
    tagged_only = _tagged_untracked_items(user, media_type, query, executor.matches())
    total = library_total + tagged_only.count()
    merged = _merge_by_title(entries, tagged_only, limit)

    if media_type == MediaTypes.ANIME.value:
        for entry in merged:
            if entry.item.media_type == MediaTypes.TV.value:
                _mark_grouped_anime_route(
                    [entry.media] if entry.media is not None else [entry.item],
                )
    if annotate_progress:
        BasicMedia.objects.annotate_max_progress(
            [entry.media for entry in merged if entry.media is not None],
            media_type,
        )
    results = [
        {
            "item": entry.item,
            "media": entry.media,
            "matched_title": _matched_title(entry.item, query, user),
        }
        for entry in merged
    ]
    return results, total


def _local_library_groups(user, query, limit):
    """Return one result group per enabled media type the user has a match in.

    Library-only (no provider calls), so a global search stays cheap (#1160).
    """
    groups = []
    for media_type in user.get_enabled_media_types():
        if media_type == MediaTypes.SEASON.value:
            continue
        group = {
            "media_type": media_type,
            "label": media_type_readable_plural(media_type),
            "kind": "media",
        }
        if media_type == MediaTypes.MUSIC.value:
            group.update(_local_music_results(user, query, limit))
            group["kind"] = "music"
            group["total"] = group["artists_total"] + group["albums_total"]
        elif media_type == MediaTypes.PODCAST.value:
            group["results"], group["total"] = _local_podcast_results(
                user,
                query,
                limit,
            )
        else:
            group["results"], group["total"] = _local_media_results(
                user,
                media_type,
                query,
                limit,
            )
        if group["total"]:
            groups.append(group)
    return groups


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
    page = helpers.get_page_number(request)
    layout = request.GET.get("layout", "grid")

    if media_type == ALL_SEARCH_TYPE:
        local_groups = []
        if request.user.is_authenticated and query:
            try:
                local_groups = _local_library_groups(
                    request.user,
                    query,
                    LOCAL_GROUP_LIMIT,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Local search failed: %s", exception_summary(exc))
        return render(
            request,
            "app/search.html",
            {
                "user": request.user,
                "media_type": media_type,
                "layout": layout,
                "local_groups": local_groups,
                "local_group_limit": LOCAL_GROUP_LIMIT,
            },
        )

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
                local_results, local_results_total = _local_podcast_results(
                    request.user,
                    query,
                    local_results_limit,
                )
            elif media_type == MediaTypes.MUSIC.value:
                music = _local_music_results(request.user, query, local_results_limit)
                local_music_artists = music["artists"]
                local_music_artists_total = music["artists_total"]
                local_music_albums = music["albums"]
                local_music_albums_total = music["albums_total"]
                local_results_total = (
                    local_music_artists_total + local_music_albums_total
                )
                local_results_kind = "music"
            else:
                local_results, local_results_total = _local_media_results(
                    request.user,
                    media_type,
                    query,
                    local_results_limit,
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Local search failed: %s", exception_summary(exc))

    source_options = metadata_resolution.available_metadata_sources(
        media_type,
        request.user,
    )
    default_source = metadata_resolution.metadata_default_source(
        request.user,
        media_type,
    )
    # only receives source when searching with secondary source
    source = request.GET.get("source", default_source)
    if source not in {option.value for option in source_options} and source_options:
        source = source_options[0].value

    search_page = 1 if media_type == MediaTypes.MUSIC.value else page
    try:
        if media_type == MediaTypes.VIDEO.value:
            # No provider to search: videos arrive from clients, so only the
            # local library results above apply.
            data = {"page": 1, "total_results": 0, "total_pages": 0, "results": []}
        else:
            with services.interactive_request_scope():
                data = services.search(
                    media_type,
                    query,
                    search_page,
                    source,
                    user=request.user,
                    language=metadata_resolution.metadata_language_default(request.user),
                )
    except services.ProviderAPIError as exc:
        logger.warning(
            "Search failed for media_type=%s query=%s: %s",
            media_type,
            query,
            exception_summary(exc),
        )
        messages.error(
            request,
            gettext("%(value_1)s is currently unavailable. Please try again shortly.")
            % {"value_1": exc.provider_label},
        )
        data = {"page": 1, "total_results": 0, "total_pages": 0, "results": []}

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


def _all_saved_suggestions(user, query, limit):
    """Return suggestions across every enabled type, each labelled with its type."""
    suggestions = []
    for media_type in user.get_enabled_media_types():
        if media_type == MediaTypes.SEASON.value:
            continue
        label = media_type_readable(media_type)
        for suggestion in get_saved_suggestions(
            user,
            media_type,
            query,
            limit=ALL_SUGGESTIONS_PER_TYPE,
        ):
            subtitle = suggestion["subtitle"]
            suggestion["subtitle"] = f"{label} · {subtitle}" if subtitle else label
            suggestions.append(suggestion)
        if len(suggestions) >= limit:
            break
    return suggestions[:limit]


def get_saved_suggestions(user, media_type, query, limit=8):
    """Return compact autocomplete suggestions from the user's saved library.

    Saved items only, scoped to ``media_type``. Each suggestion is a dict of
    ``{title, subtitle, image, url}``. Mirrors the local-results queries used by
    :func:`media_search` but capped small and side-effect free for typeahead.
    """
    if media_type == ALL_SEARCH_TYPE:
        return _all_saved_suggestions(user, query, limit)

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
                    "source": show.source,
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

    results, _total = _local_media_results(
        user,
        media_type,
        query,
        limit,
        annotate_progress=False,
    )
    local_items = [result["item"] for result in results]

    for item in local_items:
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
        or media_type not in {*MediaTypes.values, ALL_SEARCH_TYPE}
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
