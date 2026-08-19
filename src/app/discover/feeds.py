"""RSS feed for external-metadata Discover rows (Radarr/Sonarr RSS List compatible)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_not_required
from django.contrib.syndication.views import Feed
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed
from django.views.decorators.http import require_GET

from app.discover.filters import exclude_owned_items, get_owned_keys_by_media_type
from app.discover.registry import get_rows
from app.discover.service import get_live_row
from app.models import MediaTypes, Sources
from app.templatetags.app_tags import media_url
from users.models import User

EXTERNAL_ROW_SOURCES = {"trakt", "provider"}

# Radarr's RSS List parser only accepts <category>movie</category>; Sonarr's only
# accepts <category>show</category>. Media types with no arr consumer are omitted.
ARR_CATEGORY_BY_MEDIA_TYPE = {
    MediaTypes.MOVIE.value: "movie",
    MediaTypes.TV.value: "show",
    MediaTypes.ANIME.value: "show",
}


def get_external_row_definitions(media_type: str):
    """Return Discover row definitions sourced from external metadata providers."""
    return [row for row in get_rows(media_type) if row.source in EXTERNAL_ROW_SOURCES]


def get_feed_row(user, media_type, row_key, *, skip_planning=True, skip_collected=True):
    """Return the filtered row for feed/preview rendering, or None if unknown."""
    row = get_live_row(user, media_type, row_key, skip_planning=skip_planning)
    if row is None:
        return None
    if skip_collected:
        owned_keys = get_owned_keys_by_media_type(user, media_type)
        row.items = exclude_owned_items(row.items, owned_keys)
    return row


def _parse_bool_param(request, name: str, *, default: bool = True) -> bool:
    raw = request.GET.get(name)
    if raw is None:
        return default
    return raw not in {"0", "false", "False"}


class DiscoverRssFeed(Rss201rev2Feed):
    """RSS feed generator emitting the arr-compatible <category> element."""

    def add_item_elements(self, handler, item):
        """Add standard RSS elements plus the Radarr/Sonarr category."""
        super().add_item_elements(handler, item)
        category = item.get("arr_category")
        if category:
            handler.addQuickElement("category", category)


class DiscoverRowFeed(Feed):
    """RSS feed for a single Discover row's external-metadata items."""

    feed_type = DiscoverRssFeed

    def get_object(self, request, token, media_type, row_key):
        """Resolve the user by token and validate the requested row."""
        try:
            user = User.objects.get(token=token)
        except ObjectDoesNotExist as error:
            msg = "Feed not found"
            raise Http404(msg) from error

        available_rows = get_external_row_definitions(media_type)
        row_definition = next(
            (row for row in available_rows if row.key == row_key),
            None,
        )
        if row_definition is None:
            msg = "Feed not found"
            raise Http404(msg)

        self.request = request
        row = get_feed_row(
            user,
            media_type,
            row_key,
            skip_planning=_parse_bool_param(request, "skip_planning"),
            skip_collected=_parse_bool_param(request, "skip_collected"),
        )
        return {"row_definition": row_definition, "row": row}

    def title(self, obj):
        """Return the feed title."""
        return f"{obj['row_definition'].title} - Floppy"

    def link(self, obj):
        """Return the Discover page URL."""
        return self.request.build_absolute_uri(reverse("discover"))

    def description(self, obj):
        """Return the feed description."""
        return obj["row_definition"].why

    def items(self, obj):
        """Return the row's candidate items."""
        row = obj["row"]
        return row.items if row else []

    def item_title(self, item):
        """Return the item title."""
        return item.title

    def item_description(self, item):
        """Return the item description."""
        return item.source_reason or item.title

    def item_link(self, item):
        """Return the item's Floppy detail URL."""
        return self.request.build_absolute_uri(media_url(item))

    def item_guid(self, item):
        """Return the arr-compatible guid, preferring the TMDB scheme."""
        if item.source == Sources.TMDB.value:
            return f"tmdb://{item.media_id}"
        # Scheme stays "yamtrack": guids are opaque dedupe keys already held
        # by subscribers, and changing them re-marks every item unread.
        return f"yamtrack://{item.media_type}/{item.source}/{item.media_id}"

    def item_guid_is_permalink(self, item):
        """Guids are identifiers, not permalinks."""
        return False

    def item_extra_kwargs(self, item):
        """Expose the arr category for DiscoverRssFeed to render."""
        return {"arr_category": ARR_CATEGORY_BY_MEDIA_TYPE.get(item.media_type, "")}


@login_not_required
@require_GET
def discover_row_feed(request, token, media_type, row_key):
    """Serve a Discover row as an RSS feed (Radarr/Sonarr "RSS List" compatible)."""
    feed = DiscoverRowFeed()
    return feed(request, token, media_type, row_key)


@require_GET
def discover_row_feed_preview(request):
    """Render an HTMX preview of the filtered Discover row for the RSS settings page."""
    media_type = request.GET.get("media_type", "")
    row_key = request.GET.get("row_key", "")

    row = None
    if any(row.key == row_key for row in get_external_row_definitions(media_type)):
        row = get_feed_row(
            request.user,
            media_type,
            row_key,
            skip_planning=_parse_bool_param(request, "skip_planning"),
            skip_collected=_parse_bool_param(request, "skip_collected"),
        )

    return render(
        request,
        "app/components/discover_row_preview.html",
        {
            "row": row,
            "selected_media_type": media_type,
        },
    )
