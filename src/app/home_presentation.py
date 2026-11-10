"""Plain presentation data for the shared Home shelves.

The server keeps owning Home configuration, bounded row windows, up-next
semantics and card content. This module only reshapes those values for the
universal React composition; no HTML or transport reaches presentation.
"""

from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.translation import gettext as _

from app.card_surfaces import card_context
from app.media_card_model import progress_changer_model


def _request_csrf(request):
    if request is None:
        return ""
    try:
        return str(get_token(request))
    except (AttributeError, TypeError):
        return ""


def _base_context(user, request):
    return {
        "user": user,
        "request": request,
        "csrf_token": _request_csrf(request),
    }


def _entry_model(entry, row, user, request):
    item = entry.item
    if item is None:
        return None
    media = entry.media
    surface = "up_next" if entry.next_episode else "home"
    media_type = getattr(item, "media_type", None)
    values = {
        "video_landscape": bool(row.get("video_landscape")),
        "media": media,
        "item": item,
        "title": media or item,
        "card_media_type": media_type,
        "media_type_chip_type": getattr(item, "library_media_type", None)
        or media_type,
        "show_media_type_chip": bool(row.get("show_media_type_chip")),
        "show_played_chip": bool(row.get("show_played_chip")),
        "subtitle_override": entry.subtitle_override,
        "use_podcast_show": bool(entry.use_podcast_show),
        "podcast_show": entry.podcast_show,
        "image_override": getattr(media, "card_image_override", None)
        or getattr(item, "image", None),
        "image_source": getattr(media, "card_image_source", None) or "primary",
        "home_row_id": row.get("row_id"),
        "return_url": reverse("home"),
    }
    ctx = card_context(_base_context(user, request), surface, values)
    card = (ctx.get("react_props") or {}).get("model")
    if card is None:
        return None
    progress = None
    if getattr(entry, "show_progress_controls", False) and media is not None:
        progress = progress_changer_model(media, _request_csrf(request))
    return {
        "id": card.get("cardKey") or f"{media_type}-{getattr(item, 'id', '')}",
        "card": card,
        "progress": progress,
    }


def row_presentation(row, user, request=None):
    """Return one built Home row as the shared rail's model."""
    items = []
    for entry in row.get("items") or []:
        model = _entry_model(entry, row, user, request)
        if model is not None:
            items.append(model)
    return {
        "rowId": row.get("row_id"),
        "rowType": row.get("row_type"),
        "title": row.get("title"),
        "titleMain": row.get("title_main"),
        "titleDetail": row.get("title_detail"),
        "url": row.get("url"),
        "summary": row.get("summary"),
        "summaryInline": row.get("summary_inline"),
        "direction": row.get("direction"),
        "items": items,
        "total": row.get("total"),
        "seed": row.get("seed", 0),
        "loadedCount": row.get("loaded_count"),
        "showPlayedChip": bool(row.get("show_played_chip")),
        "showMediaTypeChip": bool(row.get("show_media_type_chip")),
        "mixedMedia": bool(row.get("mixed_media")),
        "videoLandscape": bool(row.get("video_landscape")),
        "pollForCovers": bool(row.get("poll_for_covers")),
        "oppositeArtwork": row.get("opposite_artwork") or [],
    }


def groups_presentation(groups, user, request=None):
    """Return built groups with presentation-ready rows."""
    return [
        {
            "mediaType": group.get("media_type"),
            "label": group.get("label"),
            "rows": [
                row_presentation(row, user, request) for row in group.get("rows", [])
            ],
        }
        for group in groups
    ]


def deferred_groups_presentation(deferred_groups):
    """Return deferred group headers and their row ids."""
    return [
        {
            "mediaType": group.get("media_type"),
            "label": group.get("label"),
            "rowIds": [str(row_id) for row_id in group.get("row_ids", [])],
        }
        for group in deferred_groups
    ]


def home_labels():
    """Return the shared Home composition's user-facing labels."""
    return {
        "altTitle": str(_("Show alternative title")),
        "nextEpisode": str(_("Jump to next episode")),
        "nextEpisodeCompact": str(_("Next")),
        "noStatus": str(_("No Status")),
        "scrollLeft": str(_("Scroll left")),
        "scrollRight": str(_("Scroll right")),
        "loadingMore": str(_("Loading more")),
        "loadingRow": str(_("Loading row")),
        "artworkRefreshing": str(_("Refreshing artwork...")),
        "unableToLoad": str(_("Unable to load this row.")),
        "retry": str(_("Try again")),
        "rowEmpty": str(_("Nothing here yet.")),
        "toggleSort": str(_("Toggle sort direction for")),
        "emptyTitle": str(_("Nothing is configured for Home yet")),
        "emptyHint": str(
            _("Add or enable rows from the Home Screen settings page to populate this view."),
        ),
        "openSettings": str(_("Open Home Screen Settings")),
    }


def home_screen_payload(user, request=None, items_limit=14, deferred=True):
    """Build the shared Home composition payload, optionally deferring rows."""
    from users.home_screen import (
        build_home_page_groups,
        build_home_page_manifest,
        warm_first_group_split,
    )

    deferred_source = []
    groups = None
    if deferred:
        manifest = build_home_page_manifest(user)
        inline_index, defer_from = warm_first_group_split(
            user,
            manifest,
            items_limit,
        )
        deferred_source = [
            {
                "media_type": group["media_type"],
                "label": group["label"],
                "row_ids": [row.id for row in group["rows"]],
            }
            for group in manifest[defer_from:]
        ]
        groups = [manifest[inline_index]] if inline_index is not None else []

    home_groups = (
        build_home_page_groups(user, items_limit, groups=groups)
        if groups != []
        else []
    )
    return {
        "groups": groups_presentation(home_groups, user, request),
        "deferredGroups": deferred_groups_presentation(deferred_source),
        "showMediaTypeHeaders": bool(
            getattr(user, "home_show_media_type_headers", False),
        ),
        "readOnly": not getattr(user, "is_authenticated", False),
        "itemsLimit": items_limit,
        "settingsUrl": reverse("home_screen"),
        "csrfToken": _request_csrf(request),
        "labels": home_labels(),
    }
