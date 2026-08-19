import calendar
import contextlib
import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from uuid import uuid4

import requests
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError
from django.db.models import F, Max, Min, Q
from django.db.models.functions import ExtractDay, ExtractMonth, TruncDate
from django.db.utils import OperationalError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.timezone import datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app import (
    cache_utils,
    config,
    credits,  # noqa: A004  # app.credits module, not the site builtin
    custom_metadata,
    discover,
    fork_services_episode,
    helpers,
    history_cache,
    history_processor,
    live_playback,
    metadata_utils,
    statistics_cache,
)

# history_cache is imported above
from app import (
    statistics as stats,
)
from app.activity_builders import (
    DETAIL_EPISODES_PER_PAGE,
    _annotate_home_card_images,
    _build_detail_activity_state,
    _build_detail_activity_subtitle,
    _detail_episode_number_for_pagination,
    _detail_episode_page_label,
    _format_detail_activity_duration,
    _get_game_lengths_refresh_lock,
    _normalize_detail_episode_actions,
    _paginate_detail_episodes,
    _queue_game_lengths_refresh,
    _should_queue_game_lengths_refresh,
)
from app.collection_views import (
    _build_collection_episode_audit_entries,
    _build_collection_season_audit_entries,
    _collection_quality_labels_by_item_id,
    _collection_redirect,
    _collection_source_labels_by_item_id,
    _episode_collection_entries,
    _format_collection_progress,
    _format_collection_progress_value,
    _item_has_collection_source_state,
    _most_common_quality_label,
    collection_add,
    collection_list,
    collection_modal,
    collection_quick_add,
    collection_remove,
    collection_remove_season,
    collection_status_api,
    collection_update,
)
from app.columns import (
    resolve_column_config,
    resolve_columns,
    resolve_default_column_config,
    sanitize_column_prefs,
)
from app.db_retry import run_retryable_db_operation
from app.detail_builders import (
    _apply_cached_hltb_link,
    _build_detail_link_entry,
    _build_detail_link_sections,
    _build_game_length_card,
    _build_game_lengths_context,
    _build_trakt_popularity_context,
    _format_game_length_minutes,
    _format_game_length_seconds,
    _normalize_detail_link_brand_key,
)
from app.discover import tab_cache as discover_tab_cache
from app.discover_views import (
    DISCOVER_ALLOWED_MEDIA_TYPES,
    DISCOVER_FAST_LOCAL_PLANNING_MEDIA_TYPES,
    DISCOVER_HIDDEN_SECTION,
    _apply_discover_response_headers,
    _build_track_modal_discover_tab_context,
    _coerce_discover_debug,
    _coerce_discover_media_type,
    _discover_candidate_seed,
    _discover_hidden_entries,
    _discover_media_options,
    _discover_model_for_media_type,
    _discover_planning_instance,
    _discover_response_rows,
    _discover_rows_context,
    _get_or_create_discover_item,
    _invalidate_discover_after_action,
    _mark_discover_stale_without_refresh,
    _render_discover_row_fragment,
    _render_discover_rows_fragment,
    _resolve_discover_media_type_for_user,
    discover_action,
    discover_page,
    discover_rows,
    discover_toggle_hidden,
    refresh_discover,
)
from app.forms import (
    BulkEpisodeTrackForm,
    CollectionEntryForm,
    EpisodeForm,
    ManualItemForm,
    get_form_class,
)
from app.history_views import (
    _build_anniversary_history_days,
    _build_release_history_days,
    _cached_history_entry_matches_filters,
    _can_use_cached_month_history,
    _filter_cached_history_days,
    _filter_history_by_enabled_media_types,
    history,
    history_genres,
)
from app.log_safety import exception_summary, safe_url
from app.media_details_views import _get_tv_runtime_display_fallback, media_details
from app.media_list_views import (
    MEDIA_LIST_NO_STATUS,
    MEDIA_LIST_NO_STATUS_LABEL,
    MEDIA_RATING_CHOICES,
    RECENTLY_NOT_RATED_DAYS,
    RECENTLY_NOT_RATED_KEY,
    RECENTLY_NOT_RATED_LABEL,
    MediaListEntry,
    _collect_reading_activity_day_keys,
    _tracked_media_entries,
    media_list,
    update_table_columns,
)
from app.metadata_sync_views import (
    _build_flat_anime_episode_preview,
    _build_local_tv_with_seasons_metadata,
    _build_missing_season_metadata,
    _get_local_show_item,
    _resolve_current_display_metadata_payload,
    _save_provider_metadata_status,
    list_hardcover_editions,
    migrate_grouped_anime,
    remap_metadata_provider,
    search_remap_candidates,
    set_hardcover_edition,
    sync_metadata,
    update_item_image,
    update_manual_item_metadata,
    update_metadata_provider_preference,
)
from app.models import (
    TV,
    Album,
    Anime,
    Artist,
    BasicMedia,
    Book,
    CollectionEntry,
    Comic,
    CreditRoleType,
    DiscoverFeedback,
    DiscoverFeedbackType,
    Episode,
    Game,
    Item,
    ItemPersonCredit,
    ItemTag,
    Manga,
    MediaTypes,
    MetadataProviderPreference,
    Movie,
    Music,
    Person,
    PodcastShow,
    ProviderMetadataStatus,
    Season,
    Sources,
    Status,
    Studio,
    Tag,
    Track,
)
from app.music_album_views import (
    album_delete,
    album_save,
    album_track_modal,
    delete_all_album_plays_view,
    delete_all_artist_plays_view,
    song_save,
    sync_album_metadata_view,
)
from app.music_views import (
    _build_music_album_activity_subtitle,
    _build_music_artist_activity_subtitle,
    _build_music_detail_secondary_actions,
    _music_activity_date_range,
    _music_album_detail_url,
    _music_artist_detail_url,
    _music_bulk_redirect_url,
    _render_music_album_details,
    _render_music_artist_details,
    _render_music_tracker_modal,
    album_detail,
    artist_delete,
    artist_detail,
    artist_save,
    artist_track_modal,
    create_album_from_search,
    create_artist_from_search,
    music_album_details,
    music_artist_details,
    prefetch_artist_covers,
    prefetch_artist_relation_images,
    sync_artist_discography_view,
)
from app.people_views import person_detail, studio_detail
from app.podcast_views import (
    podcast_episodes_api,
    podcast_mark_all_played,
    podcast_save,
    podcast_show_delete,
    podcast_show_detail,
    podcast_show_save,
    podcast_show_track_modal,
)
from app.providers import (
    comicvine,
    hardcover,
    igdb,
    mangaupdates,
    manual,
    openlibrary,
    services,
    tmdb,
)
from app.save_views import (
    episode_bulk_save,
    episode_drop,
    episode_history_poll,
    episode_save,
    media_delete,
    media_save,
)
from app.score_views import (
    _collect_music_history_day_keys_for_album_ids,
    _collect_music_history_day_keys_for_artist,
    update_album_score,
    update_artist_score,
    update_episode_score,
    update_media_score,
    update_track_score,
)
from app.search_views import (
    _mark_grouped_anime_route,
    media_search,
    search_suggestions,
)
from app.season_details_views import season_details
from app.services import (
    anime_migration,
    bulk_episode_tracking,
    bulk_music_tracking,
    metadata_resolution,
)
from app.services import game_lengths as game_length_services
from app.services import music as sync_services
from app.services import trakt_popularity as trakt_popularity_service
from app.services.tracking_hydration import (
    ensure_item_metadata,
    ensure_item_metadata_from_discover_seed,
)
from app.signals import suppress_media_cache_change_signals
from app.statistics_views import (
    _STATISTICS_HOURS_DISPLAY_RE,
    STATISTICS_CARD_LAST_YEAR_LABELS,
    STATISTICS_COMPARE_LABELS,
    STATISTICS_COMPARE_LAST_YEAR,
    STATISTICS_COMPARE_NONE,
    STATISTICS_COMPARE_PREVIOUS_PERIOD,
    _adjust_month_delta,
    _build_hours_per_media_type_comparison,
    _dates_close,
    _format_statistics_percent_change,
    _format_statistics_range_label,
    _format_statistics_total_for_media_type,
    _get_predefined_range_date_strings,
    _get_statistics_card_comparison_suffix,
    _get_statistics_card_range_label,
    _get_statistics_card_tooltip_labels,
    _get_statistics_minutes_by_type,
    _identify_predefined_range,
    _normalize_statistics_compare_mode,
    _parse_statistics_total_display_to_minutes,
    _resolve_statistics_comparison_range,
    _resolve_statistics_range_inputs,
    _statistics_day_boundary,
    refresh_statistics,
    select_featured_person,
    statistics,
    statistics_talent_fragment,
    update_genre_sort,
    update_statistics_compare_mode,
    update_statistics_preferences,
    update_studio_sort,
    update_top_talent_sort,
)
from app.tag_views import (
    _build_detail_tag_sections,
    _detail_request_url,
    _parse_detail_tag_preview_genres,
    _render_tag_modal_response,
    _resolve_detail_tag_genres,
    _user_tags_for_item,
    tag_bulk_toggle,
    tag_create,
    tag_delete,
    tag_index,
    tag_item_toggle,
    tags_modal,
)
from app.templatetags import app_tags
from app.track_modal_views import (
    _bulk_episode_form_initial_data,
    _DummyPodcastWrapper,
    _episode_domain_template_payload,
    _render_podcast_show_track_modal,
    _render_standard_track_modal,
    _track_modal_date_suggestion,
    _track_modal_field_groups,
    _track_modal_release_date_shortcut,
    _track_modal_release_runtime_minutes,
    track_modal,
)
from app.tv_sort import _sort_tv_media_by_time_left
from app.view_constants import (
    DETAIL_SECONDARY_FRAGMENT,
    LOCAL_ONLY_MISSING_SEASON_BANNER,
)
from integrations import anime_mapping
from integrations.models import CollectionSourceState
from lists.models import CustomList
from users.home_screen import build_home_page_groups
from users.models import (
    HomeSortChoices,
    MediaSortChoices,
    MediaStatusChoices,
    TopTalentSortChoices,
)

logger = logging.getLogger(__name__)


def home(request):
    """Home page with media items in progress."""
    try:
        items_limit = 14
        try:
            load_row_id = int(request.GET.get("load_row", ""))
        except (TypeError, ValueError):
            load_row_id = None
        try:
            load_row_offset = max(int(request.GET.get("offset", "0")), 0)
        except (TypeError, ValueError):
            load_row_offset = 0

        # First paint renders only the first group; the rest hydrates via
        # home_rest_fragment. Row-append (load_row) requests need the full
        # row set, so they skip the deferral.
        defer_remaining_groups = load_row_id is None
        home_groups = build_home_page_groups(
            request.user,
            items_limit,
            load_row_id=load_row_id,
            load_row_offset=load_row_offset,
            append_only=bool(request.headers.get("HX-Request") and load_row_id),
            first_group_only=defer_remaining_groups,
        )

        if request.headers.get("HX-Request") and load_row_id:
            target_row = next(
                (
                    row
                    for group in home_groups
                    for row in group["rows"]
                    if row["row_id"] == load_row_id
                ),
                None,
            )
            if target_row is None:
                return HttpResponse("")
            response = render(
                request,
                "app/components/home_grid.html",
                {
                    "media_list": target_row,
                    "user": request.user,
                    "MediaTypes": MediaTypes,
                    "IMG_NONE": settings.IMG_NONE,
                },
            )
            # The client's data-total-count is frozen at the initial page
            # render (home_grid.html carries no total/loaded data), so
            # report the freshly computed values on every load-more
            # response to keep it in sync.
            response["X-Home-Row-Total"] = str(target_row["total"])
            response["X-Home-Row-Loaded"] = str(target_row["loaded_count"])
            return response

        context = {
            "user": request.user,
            "home_groups": home_groups,
            "items_limit": items_limit,
            "active_playback_card": live_playback.build_home_playback_card(
                request.user
            ),
            "MediaTypes": MediaTypes,
            "IMG_NONE": settings.IMG_NONE,
            "defer_remaining_groups": defer_remaining_groups and bool(home_groups),
            "artwork_poll_row_ids": [
                row["row_id"]
                for group in home_groups
                for row in group["rows"]
                if row.get("poll_for_covers")
            ],
        }
        return render(request, "app/home.html", context)
    except OperationalError:
        logger.exception("Database error in home view")
        # Return empty state on database error
        context = {
            "user": request.user,
            "home_groups": [],
            "items_limit": 14,
            "database_error": True,
            "active_playback_card": None,
            "MediaTypes": MediaTypes,
            "IMG_NONE": settings.IMG_NONE,
            "defer_remaining_groups": False,
            "artwork_poll_row_ids": [],
        }
        return render(request, "app/home.html", context)


@require_GET
def home_rest_fragment(request):
    """Deferred home content: every group after the first.

    The shell renders the first group synchronously; this fragment supplies
    the rest (served from the per-row cache when warm) plus an out-of-band
    update of the artwork poller covering all groups.
    """
    home_groups = build_home_page_groups(request.user, items_limit=14)
    return render(
        request,
        "app/components/home_rest_fragment.html",
        {
            "user": request.user,
            "home_groups": home_groups[1:],
            "artwork_poll_row_ids": [
                row["row_id"]
                for group in home_groups
                for row in group["rows"]
                if row.get("poll_for_covers")
            ],
            "MediaTypes": MediaTypes,
            "IMG_NONE": settings.IMG_NONE,
        },
    )


def _queue_missing_cover_prefetch(user):
    """Queue album-cover prefetch tasks for any artists/albums missing art."""
    from django.db.models import Q

    from app.models import AlbumTracker, ArtistTracker
    from app.tasks import prefetch_album_covers_batch

    artist_ids: set[int] = set()
    artist_ids.update(
        ArtistTracker.objects.filter(user=user)
        .filter(Q(artist__image="") | Q(artist__image=settings.IMG_NONE))
        .values_list("artist_id", flat=True)
        .distinct()
    )
    artist_ids.update(
        AlbumTracker.objects.filter(user=user)
        .filter(Q(album__image="") | Q(album__image=settings.IMG_NONE))
        .exclude(album__artist__isnull=True)
        .values_list("album__artist_id", flat=True)
        .distinct()
    )
    for artist_id in artist_ids:
        cache_key = f"music:cover-prefetch:{artist_id}"
        if cache.add(cache_key, True, 60 * 10):
            try:
                prefetch_album_covers_batch.delay([artist_id], limit_per_artist=5)
            except Exception:  # pragma: no cover - defensive
                cache.delete(cache_key)


def _artwork_cover_fingerprint(user):
    """Cheap fingerprint of the user's missing-cover state.

    The artwork poller only exists to pick up cover-art writes (Artist,
    Album, PodcastShow images), which don't fire user-scoped row-cache
    invalidation. Three indexed counts are enough to detect "a cover
    arrived since the last poll" without rebuilding any rows.
    """
    from app.models import AlbumTracker, ArtistTracker, PodcastShowTracker

    missing_artist = (
        ArtistTracker.objects.filter(user=user)
        .filter(Q(artist__image="") | Q(artist__image=settings.IMG_NONE))
        .count()
    )
    missing_album = (
        AlbumTracker.objects.filter(user=user)
        .filter(Q(album__image="") | Q(album__image=settings.IMG_NONE))
        .count()
    )
    missing_show = (
        PodcastShowTracker.objects.filter(user=user)
        .filter(Q(show__image="") | Q(show__image=settings.IMG_NONE))
        .count()
    )
    return (missing_artist, missing_album, missing_show)


@require_GET
@login_required
def home_rows_artwork_refresh(request):
    """Coalesced HTMX polling endpoint for music/podcast row artwork.

    One request refreshes every polled row: rebuilds them in a single
    build_home_page_groups pass (bypassing and rewriting the row cache,
    since cover updates don't fire user-scoped invalidation signals),
    returns each row as an out-of-band swap, and re-renders the poller —
    which self-terminates once no row still needs covers.

    Rebuilding the rows materializes the user's whole music/podcast
    library (multi-second on large libraries), so when the missing-cover
    fingerprint is unchanged since the last poll the rebuild is skipped
    and only the poller is re-armed.
    """
    raw_ids = request.GET.get("ids", "")
    row_ids = {int(part) for part in raw_ids.split(",") if part.strip().isdigit()}
    if not row_ids:
        return render(
            request,
            "app/components/home_artwork_poller.html",
            {"poll_row_ids": []},
        )

    cover_state = _artwork_cover_fingerprint(request.user)
    cover_state_key = f"home_artwork_cover_state_{request.user.id}"
    if cache.get(cover_state_key) == cover_state:
        # No cover changed since the last poll: keep polling (and keep
        # retrying prefetch, it has its own cooldown) without paying the
        # row rebuild.
        _queue_missing_cover_prefetch(request.user)
        return render(
            request,
            "app/components/home_artwork_poller.html",
            {"poll_row_ids": sorted(row_ids)},
        )

    home_groups = build_home_page_groups(
        request.user,
        items_limit=14,
        only_row_ids=row_ids,
        refresh_row_cache=True,
    )
    rows = [r for group in home_groups for r in group["rows"] if r["row_id"] in row_ids]

    if any(row.get("poll_for_covers") for row in rows):
        _queue_missing_cover_prefetch(request.user)

    row_fragments = [
        render_to_string(
            "app/components/_scrollable_row.html",
            {
                "row": row,
                "user": request.user,
                "MediaTypes": MediaTypes,
                "IMG_NONE": settings.IMG_NONE,
                "force_artwork_anchor": True,
                "oob_swap": True,
            },
            request=request,
        )
        for row in rows
    ]
    poller = render_to_string(
        "app/components/home_artwork_poller.html",
        {
            "poll_row_ids": sorted(
                row["row_id"] for row in rows if row.get("poll_for_covers")
            ),
        },
        request=request,
    )
    cache.set(cover_state_key, cover_state, 60 * 60)
    return HttpResponse(poller + "".join(row_fragments))


@require_GET
@login_required
def home_row_artwork_refresh(request, row_id: int):
    """Legacy single-row artwork refresh (superseded by the coalesced poll).

    Re-renders one row, refreshing its cache; still used as a fallback URL.
    """
    home_groups = build_home_page_groups(
        request.user,
        items_limit=14,
        only_row_id=row_id,
        refresh_row_cache=True,
    )
    row = next(
        (r for group in home_groups for r in group["rows"] if r["row_id"] == row_id),
        None,
    )
    if row is None:
        return HttpResponse("")

    if row.get("poll_for_covers"):
        _queue_missing_cover_prefetch(request.user)

    return render(
        request,
        "app/components/_scrollable_row.html",
        {
            "row": row,
            "user": request.user,
            "MediaTypes": MediaTypes,
            "IMG_NONE": settings.IMG_NONE,
            "force_artwork_anchor": True,
        },
    )


def trakt_series_graph_fragment(request, source, media_id):
    """HTMX polling fragment for the Trakt episode ratings series graph.

    Returns the inner grid content (or skeleton) and drops hx-trigger once
    all episode Items have trakt_rating, so polling stops automatically.
    """
    from app.detail_builders import _build_series_graph_data
    from app.models import Item, MediaTypes

    graph_data = _build_series_graph_data(
        source,
        str(media_id),
        use_trakt=True,
        include_unrated=True,
    )

    poll_for_graph = Item.objects.filter(
        media_id=str(media_id),
        source=source,
        media_type=MediaTypes.EPISODE.value,
        season_number__gt=0,
        trakt_rating__isnull=True,
    ).exists()

    return render(
        request,
        "app/components/trakt_series_graph_fragment.html",
        {
            "graph_data": graph_data,
            "poll_for_graph": poll_for_graph,
            "source": source,
            "media_id": media_id,
        },
    )


def active_playback_fragment(request):
    """HTMX fragment: return the active playback card or empty response."""
    card = live_playback.build_home_playback_card(request.user)
    if not card:
        return HttpResponse("")
    return render(
        request,
        "app/components/active_playback_card.html",
        {
            "active_playback_card": card,
        },
    )


@require_POST
def progress_edit(request, media_type, instance_id):
    """Increase or decrease the progress of a media item from home page."""
    operation = request.POST["operation"]

    media = BasicMedia.objects.get_media_prefetch(
        request.user,
        media_type,
        instance_id,
    )

    if operation == "increase":
        try:
            media.increase_progress(
                watch_operation_id=request.POST.get("watch_operation_id")
                if media_type in {MediaTypes.TV.value, MediaTypes.SEASON.value}
                else None,
            )
        except ValidationError:
            return HttpResponseBadRequest("Invalid watch operation")
        except fork_services_episode.EpisodeWatchConflictError as error:
            return HttpResponse(str(error), status=409)
    elif operation == "decrease":
        media.decrease_progress()

    if media_type in {MediaTypes.TV.value, MediaTypes.SEASON.value}:
        # clear prefetch cache to get the updated episodes
        media = BasicMedia.objects.get_media_prefetch(
            request.user,
            media_type,
            instance_id,
        )

    context = {
        "media": media,
    }
    return render(
        request,
        "app/components/progress_changer.html",
        context,
    )


@login_not_required
@never_cache
@require_GET
def episode_details(
    request,
    source,
    media_id,
    title,
    season_number,
    episode_number,
    parent_media_type=None,
):
    """Return the details page for a single episode."""
    is_anonymous = not request.user.is_authenticated
    public_view = is_anonymous

    tv_with_seasons_metadata = services.get_media_metadata(
        "tv_with_seasons",
        media_id,
        source,
        [season_number],
    )
    season_key = f"season/{season_number}"
    season_metadata = tv_with_seasons_metadata.get(season_key) or {}

    if public_view:
        current_season_instance = None
        episodes_in_db = []
    else:
        user_seasons = BasicMedia.objects.filter_media_prefetch(
            request.user,
            media_id,
            MediaTypes.SEASON.value,
            source,
            season_number=season_number,
        )
        current_season_instance = user_seasons[0] if user_seasons else None
        episodes_in_db = (
            current_season_instance.episodes.all() if current_season_instance else []
        )

    processed_episodes = []
    if season_metadata.get("episodes"):
        if source == Sources.MANUAL.value:
            from app.providers import manual

            processed_episodes = manual.process_episodes(
                season_metadata, episodes_in_db
            )
        else:
            processed_episodes = tmdb.process_episodes(season_metadata, episodes_in_db)

    processed_episodes = _normalize_detail_episode_actions(processed_episodes)
    episode_data = next(
        (ep for ep in processed_episodes if ep["episode_number"] == episode_number),
        None,
    )

    episode_metadata = {}
    if source == Sources.TMDB.value:
        with contextlib.suppress(Exception):
            episode_metadata = tmdb.episode(media_id, season_number, episode_number)

    episode_item = Item.objects.filter(
        media_id=media_id,
        source=source,
        media_type=MediaTypes.EPISODE.value,
        season_number=season_number,
        episode_number=episode_number,
    ).first()

    if episode_data is not None and episode_item is not None:
        episode_data["item"] = episode_item

    season_url = reverse(
        "anime_season_details"
        if parent_media_type == MediaTypes.ANIME.value
        else "season_details",
        kwargs={
            "source": source,
            "media_id": media_id,
            "title": title,
            "season_number": season_number,
        },
    )

    # Surface the note from the most recent watch that has one, the same way
    # the movie/season pages do (issue #377).
    notes_entry = next(
        (
            watch
            for watch in (episode_data or {}).get("history", [])
            if watch.notes and watch.notes.strip()
        ),
        None,
    )

    context = {
        "user": request.user,
        "episode": episode_data,
        "notes_entry": notes_entry,
        "episode_notes_modal_target_id": (
            f"episode-notes-modal-{source}-{media_id}-{season_number}-{episode_number}"
        ),
        "episode_notes_modal_url": reverse(
            "track_modal",
            kwargs={
                "source": source,
                "media_type": MediaTypes.EPISODE.value,
                "media_id": media_id,
                "season_number": season_number,
            },
        ),
        "episodes": processed_episodes,
        "episode_metadata": episode_metadata,
        "season_metadata": season_metadata,
        "current_instance": current_season_instance,
        "public_view": public_view,
        "parent_media_type": parent_media_type or MediaTypes.TV.value,
        "season_url": season_url,
        "media_id": media_id,
        "source": source,
        "season_number": season_number,
        "episode_number": episode_number,
        "show_title": tv_with_seasons_metadata.get("title") or title,
        "season_title": season_metadata.get("season_title")
        or f"Season {season_number}",
        "episode_title": episode_metadata.get("episode_title")
        or (episode_data or {}).get("title")
        or f"Episode {episode_number}",
        "detail_return_url": request.build_absolute_uri(),
    }
    return render(request, "app/episode_details.html", context)


@never_cache
@require_GET
def anime_next_episode(request, media_id, title):
    """Redirect a flat MAL anime to its next unwatched mapped episode page.

    Home cards can't resolve the MAL→provider mapping per card at render time,
    so this resolves it once at click time and falls back to the anime detail
    page when no mapping (or no next episode) exists.
    """
    detail_url = reverse(
        "media_details",
        kwargs={
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "media_id": media_id,
            "title": title,
        },
    )
    if not request.user.is_authenticated:
        return redirect(detail_url)

    anime = Anime.objects.filter(
        user=request.user,
        item__media_id=media_id,
        item__source=Sources.MAL.value,
        item__media_type=MediaTypes.ANIME.value,
    ).first()
    progress = int(anime.progress or 0) if anime else 0

    detail_item = Item.objects.filter(
        media_id=media_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
    ).first()

    try:
        base_metadata = services.get_media_metadata(
            MediaTypes.ANIME.value,
            media_id,
            Sources.MAL.value,
        )
    except Exception:
        return redirect(detail_url)

    try:
        preview_episodes = (
            _build_flat_anime_episode_preview(
                request,
                detail_item=detail_item,
                media_id=media_id,
                base_metadata=base_metadata,
            )
            or []
        )
    except Exception:
        logger.warning(
            "Failed to resolve next-episode mapping for MAL anime %s",
            media_id,
            exc_info=True,
        )
        preview_episodes = []

    next_ep = next(
        (
            ep
            for ep in preview_episodes
            if ep.get("display_episode_number") == progress + 1
        ),
        None,
    )
    if not next_ep:
        return redirect(detail_url)

    return redirect(
        reverse(
            "anime_episode_details",
            kwargs={
                "source": next_ep["source"],
                "media_id": next_ep["media_id"],
                "title": title,
                "season_number": next_ep["season_number"],
                "episode_number": next_ep["episode_number"],
            },
        ),
    )


@require_POST
def music_bulk_save(request):
    """Dispatch a bulk music play range as a background task and return immediately."""
    context_kind = (request.POST.get("context_kind") or "").strip()
    context_id = request.POST.get("context_id")
    discover_tab_cache.mark_active_from_request(
        request,
        fallback_media_type=MediaTypes.MUSIC.value,
    )

    if context_kind not in {"artist", "album"}:
        return HttpResponseBadRequest("Invalid music bulk tracking context.")

    start_date_str = (request.POST.get("start_date") or "").strip()
    end_date_str = (request.POST.get("end_date") or "").strip()

    if not start_date_str or not end_date_str:
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=422)
            response["HX-Trigger"] = json.dumps(
                {
                    "showToast": {
                        "message": "Start and end dates are required.",
                        "type": "error",
                    },
                }
            )
            return response
        messages.error(request, "Start and end dates are required.")
        return redirect(request.POST.get("return_url") or "/")

    try:
        first_season_number = int(request.POST["first_season_number"])
        first_episode_number = int(request.POST["first_episode_number"])
        last_season_number = int(request.POST["last_season_number"])
        last_episode_number = int(request.POST["last_episode_number"])
    except (KeyError, ValueError):
        if request.headers.get("HX-Request"):
            response = HttpResponse(status=422)
            response["HX-Trigger"] = json.dumps(
                {
                    "showToast": {
                        "message": "Invalid track range.",
                        "type": "error",
                    },
                }
            )
            return response
        messages.error(request, "Invalid track range.")
        return redirect(request.POST.get("return_url") or "/")

    track_count = max(int(request.POST.get("episode_count") or 0), 0)
    write_mode = request.POST.get("write_mode", "add")
    distribution_mode = request.POST.get("distribution_mode", "even")

    from app.tasks import bulk_music_plays_task

    task = bulk_music_plays_task.apply_async(
        kwargs={
            "user_id": request.user.id,
            "context_kind": context_kind,
            "context_id": int(context_id),
            "first_season_number": first_season_number,
            "first_episode_number": first_episode_number,
            "last_season_number": last_season_number,
            "last_episode_number": last_episode_number,
            "write_mode": write_mode,
            "distribution_mode": distribution_mode,
            "start_date_str": start_date_str,
            "end_date_str": end_date_str,
        },
        priority=settings.CELERY_TASK_PRIORITY_INTERACTIVE,
    )
    logger.info(
        "bulk_music_plays_task_dispatched task_id=%s user_id=%d context_kind=%s context_id=%s",
        task.id,
        request.user.id,
        context_kind,
        context_id,
    )

    if request.headers.get("HX-Request"):
        plural = "s" if track_count != 1 else ""
        response = HttpResponse(status=204)
        response["HX-Trigger"] = json.dumps(
            {
                "closeModal": {},
                "showToast": {
                    "message": f"Adding plays to {track_count} track{plural}.",
                    "type": "info",
                },
            }
        )
        return response

    messages.info(request, f"Adding plays to {track_count} tracks.")
    return redirect(request.POST.get("return_url") or "/")


@require_http_methods(["GET", "POST"])
def create_entry(request):
    """Return the form for manually adding media items."""
    if request.method == "GET":
        media_types = MediaTypes.values
        return render(request, "app/create_entry.html", {"media_types": media_types})

    # Process the form submission
    form = ManualItemForm(request.POST, user=request.user)
    if not form.is_valid():
        # Handle form validation errors
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
        return redirect("create_entry")

    # Try to save the item
    try:
        item = form.save()
    except IntegrityError:
        # Handle duplicate item
        media_name = form.cleaned_data["title"]
        if form.cleaned_data.get("season_number"):
            media_name += f" - Season {form.cleaned_data['season_number']}"
        if form.cleaned_data.get("episode_number"):
            media_name += f" - Episode {form.cleaned_data['episode_number']}"

        logger.exception("%s already exists in the database.", media_name)
        messages.error(request, f"{media_name} already exists in the database.")
        return redirect("create_entry")

    # Prepare and validate the media form
    updated_request = request.POST.copy()
    updated_request.update({"source": item.source, "media_id": item.media_id})
    media_form = get_form_class(item.media_type)(updated_request, user=request.user)

    if not media_form.is_valid():
        # Handle media form validation errors
        logger.error(media_form.errors.as_json())
        helpers.form_error_messages(media_form, request)

        # Delete the item since the media creation failed
        item.delete()
        logger.info("%s was deleted due to media form validation failure", item)
        return redirect("create_entry")

    # Save the media instance
    media_form.instance.user = request.user
    media_form.instance.item = item

    # Handle relationships based on media type
    if item.media_type == MediaTypes.SEASON.value:
        media_form.instance.related_tv = form.cleaned_data["parent_tv"]
    elif item.media_type == MediaTypes.EPISODE.value:
        media_form.instance.related_season = form.cleaned_data["parent_season"]

    media_form.save()

    # Success message
    msg = f"{item} added successfully."
    messages.success(request, msg)
    logger.info(msg)

    return redirect("create_entry")


@require_GET
def search_parent_tv(request):
    """Return the search results for parent TV shows."""
    query = request.GET.get("q", "").strip()

    if len(query) <= 1:
        return render(request, "app/components/search_parent_tv.html")

    logger.debug(
        "%s - Searching for TV shows with query: %s",
        request.user.username,
        query,
    )

    parent_tvs = TV.objects.filter(
        user=request.user,
        item__source=Sources.MANUAL.value,
        item__media_type=MediaTypes.TV.value,
        item__title__icontains=query,
    )[:5]

    return render(
        request,
        "app/components/search_parent_tv.html",
        {"results": parent_tvs, "query": query},
    )


@require_GET
def search_parent_season(request):
    """Return the search results for parent seasons."""
    query = request.GET.get("q", "").strip()

    if len(query) <= 1:
        return render(request, "app/components/search_parent_tv.html")

    logger.debug(
        "%s - Searching for seasons with query: %s",
        request.user.username,
        query,
    )

    parent_seasons = Season.objects.filter(
        user=request.user,
        item__source=Sources.MANUAL.value,
        item__media_type=MediaTypes.SEASON.value,
        item__title__icontains=query,
    )[:5]

    return render(
        request,
        "app/components/search_parent_season.html",
        {"results": parent_seasons, "query": query},
    )


@require_GET
def history_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the history page for a media item."""
    instance_id = request.GET.get("instance_id")
    if instance_id:
        try:
            media = BasicMedia.objects.get_media(
                request.user,
                media_type,
                instance_id,
            )
            user_medias = [media]
        except (ObjectDoesNotExist, ValueError, TypeError):
            user_medias = BasicMedia.objects.filter_media(
                request.user,
                media_id,
                media_type,
                source,
                season_number=season_number,
                episode_number=episode_number,
            )
    else:
        user_medias = BasicMedia.objects.filter_media(
            request.user,
            media_id,
            media_type,
            source,
            season_number=season_number,
            episode_number=episode_number,
        )

    try:
        total_medias = user_medias.count()
    except TypeError:
        total_medias = len(user_medias)
    timeline_entries = []
    for index, media in enumerate(user_medias, start=1):
        # Filter history to only include records with end_date (completed plays)
        # This prevents showing invalid history records from in-progress episodes
        history = (
            media.history.filter(end_date__isnull=False)
            if hasattr(media.history, "filter")
            else [h for h in media.history.all() if h.end_date]
        )
        if history:
            media_entry_number = total_medias - index + 1
            timeline_entries.extend(
                history_processor.process_history_entries(
                    history,
                    media_type,
                    media_entry_number,
                    request.user,
                ),
            )
    return render(
        request,
        "app/components/fill_history.html",
        {
            "user": request.user,
            "media_type": media_type,
            "timeline": timeline_entries,
            "total_medias": total_medias,
            "return_url": request.GET.get("return_url", ""),
        },
    )


@require_http_methods(["DELETE"])
def delete_history_record(request, media_type, history_id):
    """Delete a specific history record."""
    try:
        historical_model = apps.get_model(
            app_label="app",
            model_name=f"historical{media_type.lower()}",
        )

        # Try to get the history record, checking both with and without history_user
        # This handles cases where history_user might be null (e.g., from old imports)
        try:
            history_record = historical_model.objects.get(
                history_id=history_id,
                history_user=request.user,
            )
        except historical_model.DoesNotExist:
            # If not found with history_user, check if history_user is null
            # and verify the record belongs to the user via the actual model instance
            history_record = historical_model.objects.get(
                history_id=history_id,
                history_user__isnull=True,
            )
            try:
                BasicMedia.objects.get_media(
                    request.user,
                    media_type.lower(),
                    history_record.id,
                )
            except ObjectDoesNotExist:
                msg = f"History record {history_id} not found for user {request.user}"
                raise historical_model.DoesNotExist(msg) from None

        # Capture all needed data BEFORE deletion to ensure we have it for cache invalidation
        # and verification, even if the object becomes invalid after deletion
        media_instance_id = history_record.id
        start_date = getattr(history_record, "start_date", None)
        end_date = getattr(history_record, "end_date", None)
        created_at = getattr(history_record, "created_at", None)
        media_type_lower = media_type.lower()

        # These media types store each play as a separate model instance.
        # Deleting only the historical record leaves the live row behind.
        instance_delete_types = {
            MediaTypes.MOVIE.value,
            MediaTypes.EPISODE.value,
            MediaTypes.GAME.value,
            MediaTypes.BOARDGAME.value,
        }
        delete_instance = media_type_lower in instance_delete_types

        logger.info(
            "Attempting to delete history record %s (media_type=%s, media_instance_id=%s, user=%s)",
            str(history_id),
            media_type_lower,
            media_instance_id,
            str(request.user),
        )

        # Get music_id or podcast_id from query params if provided (for updating count)
        music_id = request.GET.get("music_id")
        podcast_id = request.GET.get("podcast_id")

        # Perform the deletion
        if delete_instance:
            try:
                media_instance = BasicMedia.objects.get_media(
                    request.user,
                    media_type_lower,
                    media_instance_id,
                )
            except (ObjectDoesNotExist, ValueError, TypeError):
                logger.exception(
                    "Media instance %s not found for history record %s (media_type=%s, user=%s)",
                    str(media_instance_id),
                    str(history_id),
                    media_type_lower,
                    str(request.user),
                )
                return HttpResponse("Record not found", status=404)

            related_season = (
                getattr(media_instance, "related_season", None)
                if media_type_lower == MediaTypes.EPISODE.value
                else None
            )

            try:
                media_instance.delete()
            except Exception as e:
                logger.exception(
                    "Failed to delete media instance %s for history record %s: %s",
                    str(media_instance_id),
                    str(history_id),
                    str(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
                )
                return HttpResponse("Failed to delete record", status=500)

            # Keep season/TV status in sync when deleting episode plays
            if related_season:
                related_season._sync_status_after_episode_change()
                cache_utils.clear_time_left_cache_for_user(related_season.user_id)
                cache_utils.clear_media_list_cache_for_user(related_season.user_id)

            # Verify deletion succeeded by checking if the instance still exists
            try:
                model = apps.get_model(app_label="app", model_name=media_type_lower)
                verification_query = model.objects.filter(id=media_instance_id)
                if media_type_lower == MediaTypes.EPISODE.value:
                    verification_query = verification_query.filter(
                        related_season__user=request.user,
                    )
                else:
                    verification_query = verification_query.filter(user=request.user)

                if verification_query.exists():
                    logger.error(
                        "Deletion verification failed: media instance %s still exists after delete() call",
                        str(media_instance_id),
                    )
                    return HttpResponse("Deletion failed", status=500)
            except Exception as e:
                logger.warning(
                    "Could not verify deletion of media instance %s: %s",
                    str(media_instance_id),
                    str(e),
                )
                # Continue anyway as the delete() call may have succeeded
        else:
            try:
                history_record.delete()
            except Exception as e:
                logger.exception(
                    "Failed to delete history record %s: %s",
                    str(history_id),
                    str(e),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
                )
                return HttpResponse("Failed to delete record", status=500)

            # Verify deletion succeeded by checking if the record still exists
            try:
                verification_query = historical_model.objects.filter(
                    history_id=history_id
                )
                if verification_query.exists():
                    logger.error(
                        "Deletion verification failed: history record %s still exists after delete() call",
                        str(history_id),
                    )
                    return HttpResponse("Deletion failed", status=500)
            except Exception as e:
                logger.warning(
                    "Could not verify deletion of history record %s: %s",
                    str(history_id),
                    str(e),
                )
                # Continue anyway as the delete() call may have succeeded

        logger.info(
            "Successfully deleted %s %s (media_type=%s, media_instance_id=%s)",
            "media instance" if delete_instance else "history record",
            str(history_id),
            media_type_lower,
            media_instance_id,
        )

        # Invalidate caches since history changed.
        # Use the captured data instead of accessing the deleted object.
        logging_styles = ("sessions", "repeats")
        if media_type_lower in ("game", "boardgame"):
            start_dt = start_date or end_date
            end_dt = end_date or start_date
            history_day_keys = history_cache.history_day_keys_for_range(
                start_dt, end_dt
            )
        else:
            activity_dt = end_date or start_date or created_at
            history_day_key = history_cache.history_day_key(activity_dt)
            history_day_keys = [history_day_key] if history_day_key else []

        # Evict the affected payload immediately; the targeted refresh remains
        # asynchronous, and a cache miss is rebuilt inline by the history reader.
        history_cache.invalidate_history_days(
            request.user.id,
            day_keys=history_day_keys,
            logging_styles=logging_styles,
            reason="history_delete",
            force=True,
        )
        statistics_cache.invalidate_statistics_days(
            request.user.id,
            day_values=history_day_keys,
            reason="history_delete",
        )
        statistics_cache.schedule_all_ranges_refresh(request.user.id)

        # If music_id or podcast_id is provided, return updated count for out-of-band swap
        if music_id and media_type.lower() == "music":
            from app.models import Music
            from users.templatetags.user_tags import user_date_format

            try:
                music = Music.objects.get(id=music_id, user=request.user)
                # Get remaining history records (filtered by user or null)
                remaining_history = list(
                    music.history.filter(
                        history_user=request.user,
                    ).order_by("-end_date")
                ) or list(
                    music.history.filter(
                        history_user__isnull=True,
                    ).order_by("-end_date")
                )

                remaining_count = len(remaining_history)

                if remaining_count > 0:
                    # Get the last entry for date display
                    last_entry = remaining_history[0]

                    # Format the date using the same filter as the template
                    last_date_formatted = (
                        user_date_format(last_entry.end_date, request.user)
                        if last_entry.end_date
                        else "No date provided"
                    )

                    if remaining_count == 1:
                        history_text = f"Last listened: {last_date_formatted}"
                    else:
                        history_text = f"Last listened: {last_date_formatted} • Listened {remaining_count} times"

                    # Return response with out-of-band swaps for both album page and modal
                    response = HttpResponse()
                    # Update the count on the album detail page
                    response.write(
                        f'<p id="track-history-{music_id}" hx-swap-oob="true" class="text-xs text-gray-400 mt-2 px-4">{history_text}</p>'
                    )
                    # Update the count in the modal
                    modal_text = (
                        "Listened once"
                        if remaining_count == 1
                        else f"Listened {remaining_count} times"
                    )
                    response.write(
                        f'<p id="modal-listen-count-{music_id}" hx-swap-oob="true" class="text-sm text-gray-400 mt-1">{modal_text}</p>'
                    )
                    return response
                # No history left, hide the album page element and update modal
                response = HttpResponse()
                response.write(
                    f'<p id="track-history-{music_id}" hx-swap-oob="true" class="text-xs text-gray-400 mt-2 px-4" style="display: none;"></p>'
                )
                response.write(
                    f'<p id="modal-listen-count-{music_id}" hx-swap-oob="true" class="text-sm text-gray-400 mt-1">Not listened yet</p>'
                )
            except Music.DoesNotExist:
                pass
            else:
                return response

        # If podcast_id is provided, return updated count for out-of-band swap
        if podcast_id and media_type.lower() == "podcast":
            from app.models import Podcast
            from users.templatetags.user_tags import user_date_format

            try:
                podcast = Podcast.objects.get(id=podcast_id, user=request.user)
                # Get remaining history records (filtered by user or null)
                remaining_history = list(
                    podcast.history.filter(
                        history_user=request.user,
                    ).order_by("-end_date")
                ) or list(
                    podcast.history.filter(
                        history_user__isnull=True,
                    ).order_by("-end_date")
                )

                remaining_count = len(remaining_history)

                if remaining_count > 0:
                    # Get the last entry for date display
                    last_entry = remaining_history[0]

                    # Format the date using the same filter as the template
                    last_date_formatted = (
                        user_date_format(last_entry.end_date, request.user)
                        if last_entry.end_date
                        else "No date provided"
                    )

                    if remaining_count == 1:
                        history_text = f"Last played: {last_date_formatted}"
                    else:
                        history_text = f"Last played: {last_date_formatted} • Played {remaining_count} times"

                    # Return response with out-of-band swaps for both show page and modal
                    response = HttpResponse()
                    # Update the count in the modal
                    modal_text = (
                        "Played once"
                        if remaining_count == 1
                        else f"Played {remaining_count} times"
                    )
                    response.write(
                        f'<p id="modal-listen-count-{podcast_id}" hx-swap-oob="true" class="text-sm text-gray-400 mt-1">{modal_text}</p>'
                    )
                    response["HX-Trigger"] = "history-refresh-start"
                    return response
                # No history left, update modal
                response = HttpResponse()
                response.write(
                    f'<p id="modal-listen-count-{podcast_id}" hx-swap-oob="true" class="text-sm text-gray-400 mt-1">Not played yet</p>'
                )
                response["HX-Trigger"] = "history-refresh-start"
            except Podcast.DoesNotExist:
                pass
            else:
                return response

        # Return empty 200 response - the element will be removed by HTMX
        response = HttpResponse()
        response["HX-Trigger"] = "history-refresh-start"

    except historical_model.DoesNotExist:
        logger.exception(
            "History record %s not found for user %s",
            str(history_id),
            str(request.user),
        )
        return HttpResponse("Record not found", status=404)
    else:
        return response


@require_GET
def cache_status(request):
    """Return cache status metadata for history, statistics, or discover cache.

    Query params:
        cache_type: 'history', 'statistics', or 'discover'
        range_name: Required for statistics, ignored for history
        logging_style: Optional for history, defaults to 'repeats'

    Returns JSON with:
        exists: bool - Whether cache exists
        built_at: str - ISO format timestamp when cache was built (or None)
        is_stale: bool - Whether cache is considered stale
        is_refreshing: bool - Whether a refresh is currently in progress
        recently_built: bool - Whether cache was built in the last 30 seconds
    """
    cache_type = request.GET.get("cache_type")
    if cache_type not in ("history", "statistics", "discover"):
        return JsonResponse(
            {
                "error": "Invalid cache_type. Must be 'history', 'statistics', or 'discover'"
            },
            status=400,
        )

    if cache_type == "history":
        logging_style = request.GET.get("logging_style")
        if logging_style not in ("sessions", "repeats"):
            logging_style = "repeats"
        cache_entry = cache.get(
            history_cache._cache_key(request.user.id, logging_style)
        )
        refresh_lock_key = history_cache._refresh_lock_key(
            request.user.id, logging_style
        )
        refresh_lock = history_cache._clean_refresh_lock(refresh_lock_key)
        lock_has_day_keys = isinstance(refresh_lock, dict) and bool(
            refresh_lock.get("day_keys")
        )

        # Also check dedupe_key if lock has day_keys (for page_days refreshes)
        dedupe_key = None
        if lock_has_day_keys and isinstance(refresh_lock, dict):
            dedupe_key = refresh_lock.get("dedupe_key")
            if dedupe_key and dedupe_key != refresh_lock_key:
                # Check if dedupe lock is stale
                dedupe_lock = history_cache._clean_refresh_lock(dedupe_key)
                if dedupe_lock is None:
                    # Dedupe lock is stale/missing, clear main lock too
                    cache.delete(refresh_lock_key)
                    refresh_lock = None
                    lock_has_day_keys = False

        # Debug logging to help diagnose lock issues
        logger.debug(
            "Cache status check for user %s, logging_style %s: lock_key=%s, lock_exists=%s",
            request.user.id,
            logging_style,
            refresh_lock_key,
            refresh_lock is not None,
        )

        if cache_entry:
            built_at = cache_entry.get("built_at")
            is_stale = False
            recently_built = False
            if built_at:
                age = timezone.now() - built_at
                is_stale = age > history_cache.HISTORY_STALE_AFTER
                # Consider cache "recently built" if it was built in the last 60 seconds
                # This helps catch refreshes that completed just before or during page load
                recently_built = age < timedelta(seconds=60)
                # If the cache was just rebuilt but the lock is still set, clear it
                # to avoid a stuck "refreshing" state on the frontend.
                if refresh_lock and recently_built and not lock_has_day_keys:
                    cache.delete(refresh_lock_key)
                    refresh_lock = None
                # If cache is fresh (not stale), ignore lingering locks for index rebuilds.
                # Page-day refresh locks should remain until the task completes.
                if not is_stale and refresh_lock and not lock_has_day_keys:
                    cache.delete(refresh_lock_key)
                    refresh_lock = None

            return JsonResponse(
                {
                    "exists": True,
                    "built_at": built_at.isoformat() if built_at else None,
                    "is_stale": is_stale,
                    "is_refreshing": refresh_lock is not None,
                    "recently_built": recently_built,
                }
            )
        return JsonResponse(
            {
                "exists": False,
                "built_at": None,
                "is_stale": False,
                "is_refreshing": refresh_lock is not None,
                "recently_built": False,
            }
        )

    if cache_type == "statistics":
        range_name = request.GET.get("range_name")
        if not range_name:
            return JsonResponse(
                {"error": "range_name is required for statistics cache"}, status=400
            )

        if range_name not in statistics_cache.PREDEFINED_RANGES:
            return JsonResponse(
                {
                    "exists": False,
                    "built_at": None,
                    "is_stale": False,
                    "is_refreshing": False,
                    "recently_built": False,
                    "any_range_refreshing": False,
                }
            )

        cache_key = statistics_cache._cache_key(request.user.id, range_name)
        refresh_lock_key = statistics_cache._refresh_lock_key(
            request.user.id, range_name
        )
        cache_entry = cache.get(cache_key)
        refresh_lock = cache.get(refresh_lock_key)
        if refresh_lock and statistics_cache._lock_is_stale(refresh_lock):
            cache.delete(refresh_lock_key)
            refresh_lock = None

        any_range_refreshing = statistics_cache._any_range_refreshing(request.user.id)
        metadata_lock, metadata_built_at, metadata_recently_built = (
            statistics_cache._metadata_refresh_status(request.user.id)
        )
        metadata_refreshing = metadata_lock is not None

        refresh_scheduled = False
        if cache_entry:
            built_at = cache_entry.get("built_at")
            history_version = cache_entry.get("history_version")
            current_version = statistics_cache._get_history_version(request.user.id)
            is_stale = False
            recently_built = False
            age = None
            if built_at:
                age = timezone.now() - built_at
                # Consider cache "recently built" if it was built in the last 60 seconds
                # This helps catch refreshes that completed just before or during page load
                recently_built = age < timedelta(seconds=60)
            if history_version:
                is_stale = history_version != current_version
            elif age:
                is_stale = age > statistics_cache.STATISTICS_STALE_AFTER

            if not is_stale and refresh_lock:
                cache.delete(refresh_lock_key)
                refresh_lock = None
            elif is_stale and refresh_lock is None:
                refresh_scheduled = statistics_cache.schedule_statistics_refresh(
                    request.user.id,
                    range_name,
                    allow_inline=False,
                )
                refresh_lock = (
                    cache.get(refresh_lock_key) if refresh_scheduled else refresh_lock
                )

            is_refreshing = (
                refresh_lock is not None or refresh_scheduled or metadata_refreshing
            )
            return JsonResponse(
                {
                    "exists": True,
                    "built_at": built_at.isoformat() if built_at else None,
                    "is_stale": is_stale,
                    "is_refreshing": is_refreshing,
                    "recently_built": recently_built,
                    "any_range_refreshing": any_range_refreshing,
                    "refresh_scheduled": refresh_scheduled,
                    "metadata_refreshing": metadata_refreshing,
                    "metadata_built_at": metadata_built_at.isoformat()
                    if metadata_built_at
                    else None,
                    "metadata_recently_built": metadata_recently_built,
                }
            )
        refresh_scheduled = False
        if refresh_lock is None:
            # True cold miss (no cache entry, no active lock). This is the normal
            # state right after a bulk import, but it's also what a lost refresh
            # looks like (task never dequeued, worker restarted mid-task, etc.).
            # Re-schedule defensively; schedule_statistics_refresh() is debounced
            # via its own lock/dedupe keys, so polling this repeatedly is safe.
            refresh_scheduled = statistics_cache.schedule_statistics_refresh(
                request.user.id,
                range_name,
                allow_inline=False,
            )
            refresh_lock = (
                cache.get(refresh_lock_key) if refresh_scheduled else refresh_lock
            )

        is_refreshing = refresh_lock is not None or metadata_refreshing
        return JsonResponse(
            {
                "exists": False,
                "built_at": None,
                "is_stale": False,
                "is_refreshing": is_refreshing,
                "recently_built": False,
                "any_range_refreshing": any_range_refreshing,
                "refresh_scheduled": refresh_scheduled,
                "metadata_refreshing": metadata_refreshing,
                "metadata_built_at": metadata_built_at.isoformat()
                if metadata_built_at
                else None,
                "metadata_recently_built": metadata_recently_built,
            }
        )

    media_type = _resolve_discover_media_type_for_user(
        request.user,
        request.GET.get("media_type"),
    )
    show_more = request.GET.get("show_more") in {"1", "true", "True"}
    return JsonResponse(
        discover_tab_cache.get_tab_status(
            request.user.id,
            media_type,
            show_more=show_more,
        ),
    )


@require_GET
def date_range_script(request):
    """Serve the statistics date-range picker script."""
    script_path = Path(settings.STATICFILES_DIRS[0]) / "js" / "date-range.js"
    with script_path.open(encoding="utf-8") as script_file:
        return HttpResponse(
            script_file.read(),
            content_type="application/javascript",
        )


@login_not_required
@require_GET
def service_worker(request):
    """Serve the service worker file from static files."""
    sw_path = Path(settings.STATICFILES_DIRS[0]) / "js" / "serviceworker.js"
    with sw_path.open(encoding="utf-8") as sw_file:
        response = HttpResponse(sw_file.read(), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


__all__ = [
    "DETAIL_EPISODES_PER_PAGE",
    "DETAIL_SECONDARY_FRAGMENT",
    "DISCOVER_ALLOWED_MEDIA_TYPES",
    "DISCOVER_FAST_LOCAL_PLANNING_MEDIA_TYPES",
    "DISCOVER_HIDDEN_SECTION",
    "LOCAL_ONLY_MISSING_SEASON_BANNER",
    "MEDIA_LIST_NO_STATUS",
    "MEDIA_LIST_NO_STATUS_LABEL",
    "MEDIA_RATING_CHOICES",
    "RECENTLY_NOT_RATED_DAYS",
    "RECENTLY_NOT_RATED_KEY",
    "RECENTLY_NOT_RATED_LABEL",
    "ROUND_DOWN",
    "STATISTICS_CARD_LAST_YEAR_LABELS",
    "STATISTICS_COMPARE_LABELS",
    "STATISTICS_COMPARE_LAST_YEAR",
    "STATISTICS_COMPARE_NONE",
    "STATISTICS_COMPARE_PREVIOUS_PERIOD",
    "UTC",
    "_STATISTICS_HOURS_DISPLAY_RE",
    "Album",
    "Artist",
    "Book",
    "BulkEpisodeTrackForm",
    "CollectionEntry",
    "CollectionEntryForm",
    "CollectionSourceState",
    "Comic",
    "Counter",
    "CreditRoleType",
    "CustomList",
    "Decimal",
    "DiscoverFeedback",
    "DiscoverFeedbackType",
    "EmptyPage",
    "Episode",
    "EpisodeForm",
    "ExtractDay",
    "ExtractMonth",
    "F",
    "Game",
    "HomeSortChoices",
    "InvalidOperation",
    "ItemPersonCredit",
    "ItemTag",
    "Manga",
    "Max",
    "MediaListEntry",
    "MediaSortChoices",
    "MediaStatusChoices",
    "MetadataProviderPreference",
    "Min",
    "Movie",
    "Music",
    "Paginator",
    "Person",
    "PodcastShow",
    "ProviderMetadataStatus",
    "Status",
    "Studio",
    "Tag",
    "TopTalentSortChoices",
    "Track",
    "TruncDate",
    "_DummyPodcastWrapper",
    "_adjust_month_delta",
    "_annotate_home_card_images",
    "_apply_cached_hltb_link",
    "_apply_discover_response_headers",
    "_build_anniversary_history_days",
    "_build_collection_episode_audit_entries",
    "_build_collection_season_audit_entries",
    "_build_detail_activity_state",
    "_build_detail_activity_subtitle",
    "_build_detail_link_entry",
    "_build_detail_link_sections",
    "_build_detail_tag_sections",
    "_build_game_length_card",
    "_build_game_lengths_context",
    "_build_hours_per_media_type_comparison",
    "_build_local_tv_with_seasons_metadata",
    "_build_missing_season_metadata",
    "_build_music_album_activity_subtitle",
    "_build_music_artist_activity_subtitle",
    "_build_music_detail_secondary_actions",
    "_build_release_history_days",
    "_build_track_modal_discover_tab_context",
    "_build_trakt_popularity_context",
    "_bulk_episode_form_initial_data",
    "_cached_history_entry_matches_filters",
    "_can_use_cached_month_history",
    "_coerce_discover_debug",
    "_coerce_discover_media_type",
    "_collect_music_history_day_keys_for_album_ids",
    "_collect_music_history_day_keys_for_artist",
    "_collect_reading_activity_day_keys",
    "_collection_quality_labels_by_item_id",
    "_collection_redirect",
    "_collection_source_labels_by_item_id",
    "_dates_close",
    "_detail_episode_number_for_pagination",
    "_detail_episode_page_label",
    "_detail_request_url",
    "_discover_candidate_seed",
    "_discover_hidden_entries",
    "_discover_media_options",
    "_discover_model_for_media_type",
    "_discover_planning_instance",
    "_discover_response_rows",
    "_discover_rows_context",
    "_episode_collection_entries",
    "_episode_domain_template_payload",
    "_filter_cached_history_days",
    "_filter_history_by_enabled_media_types",
    "_format_collection_progress",
    "_format_collection_progress_value",
    "_format_detail_activity_duration",
    "_format_game_length_minutes",
    "_format_game_length_seconds",
    "_format_statistics_percent_change",
    "_format_statistics_range_label",
    "_format_statistics_total_for_media_type",
    "_get_game_lengths_refresh_lock",
    "_get_local_show_item",
    "_get_or_create_discover_item",
    "_get_predefined_range_date_strings",
    "_get_statistics_card_comparison_suffix",
    "_get_statistics_card_range_label",
    "_get_statistics_card_tooltip_labels",
    "_get_statistics_minutes_by_type",
    "_get_tv_runtime_display_fallback",
    "_identify_predefined_range",
    "_invalidate_discover_after_action",
    "_item_has_collection_source_state",
    "_mark_discover_stale_without_refresh",
    "_mark_grouped_anime_route",
    "_most_common_quality_label",
    "_music_activity_date_range",
    "_music_album_detail_url",
    "_music_artist_detail_url",
    "_music_bulk_redirect_url",
    "_normalize_detail_link_brand_key",
    "_normalize_statistics_compare_mode",
    "_paginate_detail_episodes",
    "_parse_detail_tag_preview_genres",
    "_parse_statistics_total_display_to_minutes",
    "_queue_game_lengths_refresh",
    "_render_discover_row_fragment",
    "_render_discover_rows_fragment",
    "_render_music_album_details",
    "_render_music_artist_details",
    "_render_music_tracker_modal",
    "_render_podcast_show_track_modal",
    "_render_standard_track_modal",
    "_render_tag_modal_response",
    "_resolve_current_display_metadata_payload",
    "_resolve_detail_tag_genres",
    "_resolve_statistics_comparison_range",
    "_resolve_statistics_range_inputs",
    "_save_provider_metadata_status",
    "_should_queue_game_lengths_refresh",
    "_sort_tv_media_by_time_left",
    "_statistics_day_boundary",
    "_track_modal_date_suggestion",
    "_track_modal_field_groups",
    "_track_modal_release_date_shortcut",
    "_track_modal_release_runtime_minutes",
    "_tracked_media_entries",
    "_user_tags_for_item",
    "album_delete",
    "album_detail",
    "album_save",
    "album_track_modal",
    "anime_mapping",
    "anime_migration",
    "app_tags",
    "artist_delete",
    "artist_detail",
    "artist_save",
    "artist_track_modal",
    "bulk_episode_tracking",
    "bulk_music_tracking",
    "calendar",
    "collection_add",
    "collection_list",
    "collection_modal",
    "collection_quick_add",
    "collection_remove",
    "collection_remove_season",
    "collection_status_api",
    "collection_update",
    "comicvine",
    "config",
    "create_album_from_search",
    "create_artist_from_search",
    "credits",
    "custom_metadata",
    "dataclass",
    "date",
    "datetime",
    "defaultdict",
    "delete_all_album_plays_view",
    "delete_all_artist_plays_view",
    "discover",
    "discover_action",
    "discover_page",
    "discover_rows",
    "discover_toggle_hidden",
    "ensure_item_metadata",
    "ensure_item_metadata_from_discover_seed",
    "episode_bulk_save",
    "episode_drop",
    "episode_history_poll",
    "episode_save",
    "exception_summary",
    "formats",
    "game_length_services",
    "get_object_or_404",
    "hardcover",
    "history",
    "history_genres",
    "igdb",
    "list_hardcover_editions",
    "login_not_required",
    "mangaupdates",
    "manual",
    "math",
    "media_delete",
    "media_details",
    "media_list",
    "media_save",
    "media_search",
    "metadata_resolution",
    "metadata_utils",
    "migrate_grouped_anime",
    "music_album_details",
    "music_artist_details",
    "openlibrary",
    "parse_date",
    "person_detail",
    "podcast_episodes_api",
    "podcast_mark_all_played",
    "podcast_save",
    "podcast_show_delete",
    "podcast_show_detail",
    "podcast_show_save",
    "podcast_show_track_modal",
    "prefetch_artist_covers",
    "prefetch_artist_relation_images",
    "quote",
    "re",
    "refresh_discover",
    "refresh_statistics",
    "relativedelta",
    "remap_metadata_provider",
    "requests",
    "resolve_column_config",
    "resolve_columns",
    "resolve_default_column_config",
    "run_retryable_db_operation",
    "safe_url",
    "sanitize_column_prefs",
    "search_remap_candidates",
    "search_suggestions",
    "season_details",
    "select_featured_person",
    "set_hardcover_edition",
    "slugify",
    "song_save",
    "static",
    "statistics",
    "statistics_talent_fragment",
    "stats",
    "studio_detail",
    "suppress_media_cache_change_signals",
    "sync_album_metadata_view",
    "sync_artist_discography_view",
    "sync_metadata",
    "sync_services",
    "tag_bulk_toggle",
    "tag_create",
    "tag_delete",
    "tag_index",
    "tag_item_toggle",
    "tags_modal",
    "time",
    "track_modal",
    "trakt_popularity_service",
    "update_album_score",
    "update_artist_score",
    "update_episode_score",
    "update_genre_sort",
    "update_item_image",
    "update_manual_item_metadata",
    "update_media_score",
    "update_metadata_provider_preference",
    "update_statistics_compare_mode",
    "update_statistics_preferences",
    "update_studio_sort",
    "update_table_columns",
    "update_top_talent_sort",
    "update_track_score",
    "url_has_allowed_host_and_scheme",
    "urlencode",
    "urlparse",
    "uuid4",
]
