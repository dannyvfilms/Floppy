import logging
import math
from collections import Counter, defaultdict

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.forms import CollectionEntryForm
from app.log_safety import exception_summary
from app.models import CollectionEntry, Game, Item, MediaTypes, Status
from app.providers import services
from app.services import metadata_resolution
from integrations.models import CollectionSourceState

logger = logging.getLogger(__name__)

COLLECTION_SORT_CHOICES = [
    ("collected_at", "Date Collected"),
    ("title", "Title"),
    ("release_date", "Release Date"),
]
COLLECTION_SORT_FIELDS = {
    "collected_at": "collected_at",
    "title": "item__title",
    "release_date": "item__release_datetime",
}
COLLECTION_RATING_CHOICES = {"all", "rated", "not_rated"}


def _scored_item_ids(user, item_ids_by_media_type):
    """Return the ids of items (grouped by media_type) that have a user score."""
    scored_ids = set()
    for item_media_type, item_ids in item_ids_by_media_type.items():
        try:
            model = apps.get_model("app", item_media_type)
        except LookupError:
            continue
        if item_media_type == MediaTypes.EPISODE.value:
            filter_kwargs = {"related_season__user": user}
        else:
            filter_kwargs = {"user": user}
        scored_ids.update(
            model.objects.filter(
                item_id__in=item_ids,
                score__isnull=False,
                **filter_kwargs,
            ).values_list("item_id", flat=True),
        )
    return scored_ids


@require_GET
def collection_list(request, media_type=None):
    """Display user's collection, filterable by type, format, and rating."""
    effective_media_type = media_type or request.GET.get("type", "")
    if effective_media_type == "all":
        effective_media_type = ""

    search_query = request.GET.get("q", "").strip()
    sort_by = request.GET.get("sort", "collected_at")
    if sort_by not in COLLECTION_SORT_FIELDS:
        sort_by = "collected_at"
    direction = request.GET.get("direction") or (
        "desc" if sort_by == "collected_at" else "asc"
    )
    if direction not in ("asc", "desc"):
        direction = "asc"
    layout = request.GET.get("layout", "grid")
    if layout not in ("grid", "table"):
        layout = "grid"
    format_filter = request.GET.get("format", "")
    if format_filter == "all":
        format_filter = ""
    resolution_filter = request.GET.get("resolution", "")
    if resolution_filter == "all":
        resolution_filter = ""
    hdr_filter = request.GET.get("hdr", "")
    if hdr_filter == "all":
        hdr_filter = ""
    rating_filter = request.GET.get("rating", "all")
    if rating_filter not in COLLECTION_RATING_CHOICES:
        rating_filter = "all"

    collection = helpers.get_user_collection(request.user, effective_media_type)
    if search_query:
        collection = collection.filter(item__title__icontains=search_query)
    if format_filter:
        collection = collection.filter(media_type=format_filter)
    if resolution_filter:
        collection = collection.filter(resolution=resolution_filter)
    if hdr_filter:
        collection = collection.filter(hdr=hdr_filter)

    if rating_filter != "all":
        item_ids_by_media_type = defaultdict(list)
        for item_id, item_media_type in collection.values_list(
            "item_id",
            "item__media_type",
        ).distinct():
            item_ids_by_media_type[item_media_type].append(item_id)
        scored_ids = _scored_item_ids(request.user, item_ids_by_media_type)
        if rating_filter == "rated":
            collection = collection.filter(item_id__in=scored_ids)
        else:
            collection = collection.exclude(item_id__in=scored_ids)

    order_field = COLLECTION_SORT_FIELDS[sort_by]
    if direction == "desc":
        order_field = f"-{order_field}"
    collection = collection.order_by(order_field, "-id")

    paginator = Paginator(collection, 20)
    page_number = int(request.GET.get("page", 1))

    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    base_collection = CollectionEntry.objects.filter(user=request.user)
    available_media_types = set(
        base_collection.order_by()
        .values_list("item__media_type", flat=True)
        .distinct(),
    )
    media_types = [
        value for value in MediaTypes.values if value in available_media_types
    ]
    available_formats = sorted(
        value
        for value in base_collection.exclude(media_type="")
        .order_by()
        .values_list("media_type", flat=True)
        .distinct()
        if value
    )
    available_resolutions = sorted(
        value
        for value in base_collection.exclude(resolution="")
        .order_by()
        .values_list("resolution", flat=True)
        .distinct()
        if value
    )
    available_hdr = sorted(
        value
        for value in base_collection.exclude(hdr="")
        .order_by()
        .values_list("hdr", flat=True)
        .distinct()
        if value
    )

    is_fragment = helpers.is_htmx_fragment(request)
    context = {
        "collection_entries": page_obj,
        "media_type": effective_media_type,
        "media_types": media_types,
        "available_formats": available_formats,
        "available_resolutions": available_resolutions,
        "available_hdr": available_hdr,
        "sort_choices": COLLECTION_SORT_CHOICES,
        "sort_by": sort_by,
        "direction": direction,
        "layout": layout,
        "format_filter": format_filter,
        "resolution_filter": resolution_filter,
        "hdr_filter": hdr_filter,
        "rating_filter": rating_filter,
        "search_query": search_query,
        "is_pagination": is_fragment and page_number > 1,
    }

    if is_fragment:
        return render(request, "app/components/collection_items.html", context)

    return render(request, "app/collection_list.html", context)


def _collection_redirect(request):
    """Redirect to a safe next URL when present, otherwise collection list."""
    next_url = request.GET.get("next") or request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("collection_list")


_SEASON_OR_SHOW_MEDIA_TYPES = {
    MediaTypes.SEASON.value,
    MediaTypes.TV.value,
    MediaTypes.ANIME.value,
}

_COLLECTION_ENTRY_COPY_FIELDS = (
    "media_type",
    "resolution",
    "hdr",
    "is_3d",
    "audio_codec",
    "audio_channels",
    "bitrate",
)


def _episodes_for_season_or_show(item):
    """Return the episode Items covered by a season or show/anime Item."""
    episode_items = Item.objects.filter(
        media_id=item.media_id,
        source=item.source,
        media_type=MediaTypes.EPISODE.value,
    )
    if item.media_type == MediaTypes.SEASON.value:
        episode_items = episode_items.filter(season_number=item.season_number)
    else:
        episode_items = episode_items.exclude(season_number=0)
    return episode_items


def _expand_collection_entry_to_episodes(user, item, *, cleaned_data):
    """Create a CollectionEntry for every episode under a season/show Item.

    Episodes that already have at least one CollectionEntry for this user are
    left untouched. Returns (created_count, skipped_count).
    """
    episode_items = list(_episodes_for_season_or_show(item))
    if not episode_items:
        return 0, 0

    already_collected_ids = set(
        CollectionEntry.objects.filter(
            user=user,
            item_id__in=[episode_item.id for episode_item in episode_items],
        ).values_list("item_id", flat=True),
    )

    to_create = [
        episode_item
        for episode_item in episode_items
        if episode_item.id not in already_collected_ids
    ]
    if not to_create:
        return 0, len(episode_items)

    copy_fields = {
        field: cleaned_data[field]
        for field in _COLLECTION_ENTRY_COPY_FIELDS
        if field in cleaned_data
    }
    new_entries = CollectionEntry.objects.bulk_create(
        [
            CollectionEntry(user=user, item=episode_item, **copy_fields)
            for episode_item in to_create
        ],
    )

    collected_at = cleaned_data.get("collected_at")
    if collected_at:
        CollectionEntry.objects.filter(
            id__in=[entry.id for entry in new_entries],
        ).update(collected_at=collected_at)

    return len(new_entries), len(already_collected_ids)


def _collection_add_season_or_show_response(request, item, form):
    """Expand a season/show collection submission into per-episode entries."""
    created_count, skipped_count = _expand_collection_entry_to_episodes(
        request.user,
        item,
        cleaned_data=form.cleaned_data,
    )
    if created_count:
        message = f"Added {created_count} episode(s) to collection"
        if skipped_count:
            message += f" ({skipped_count} already collected)"
    else:
        message = "All episodes are already in your collection"
    messages.success(request, message)
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True, "message": message})
    return _collection_redirect(request)


def _collection_quick_add_season_or_show_response(request, item):
    """Expand a season/show quick-add into per-episode entries."""
    created_count, skipped_count = _expand_collection_entry_to_episodes(
        request.user,
        item,
        cleaned_data={},
    )
    if created_count:
        message = f"Added {created_count} episode(s) to collection"
        if skipped_count:
            message += f" ({skipped_count} already collected)"
        messages.success(request, message)
    else:
        message = "All episodes are already in your collection"
    if request.headers.get("HX-Request"):
        return JsonResponse(
            {"success": True, "created": bool(created_count), "message": message}
        )
    return _collection_redirect(request)


@require_POST
def collection_add(request):
    """Add a new owned copy to collection (with optional metadata)."""
    item_id = request.POST.get("item_id")
    if not item_id:
        if request.headers.get("HX-Request"):
            return HttpResponseBadRequest("Item ID is required")
        messages.error(request, "Item ID is required")
        return _collection_redirect(request)

    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        if request.headers.get("HX-Request"):
            return HttpResponseBadRequest("Item not found")
        messages.error(request, "Item not found")
        return _collection_redirect(request)

    post_data = request.POST.copy()
    post_data["item"] = item.id

    form = CollectionEntryForm(
        post_data,
        user=request.user,
        collection_media_type=item.media_type,
    )

    if form.is_valid():
        if item.media_type in _SEASON_OR_SHOW_MEDIA_TYPES:
            return _collection_add_season_or_show_response(request, item, form)

        entry = form.save(commit=False)
        entry.user = request.user
        entry.item = item
        entry.save()

        if item.media_type == MediaTypes.GAME.value:
            game_exists = Game.objects.filter(user=request.user, item=item).exists()
            if not game_exists:
                Game.objects.create(
                    user=request.user,
                    item=item,
                    status=Status.PLANNING.value,
                    progress=0,
                )

        collected_at = form.cleaned_data.get("collected_at")
        if collected_at:
            CollectionEntry.objects.filter(id=entry.id).update(
                collected_at=collected_at
            )
            entry.collected_at = collected_at
        messages.success(request, f"Added {item.title} to collection")
        if request.headers.get("HX-Request"):
            return JsonResponse(
                {"success": True, "message": f"Added {item.title} to collection"}
            )
    else:
        helpers.form_error_messages(form, request)
        if request.headers.get("HX-Request"):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    return _collection_redirect(request)


@require_POST
def collection_quick_add(request, source, media_type, media_id):
    """Add a bare collection entry in one click, without the details modal.

    Idempotent: if the user already has any entry for the item, nothing is
    created (extra copies with metadata go through the modal).
    """
    season_number = _parse_optional_int(request.POST.get("season_number"))
    episode_number = _parse_optional_int(request.POST.get("episode_number"))
    error_response = _validate_collection_numbers(
        request,
        media_type,
        season_number,
        episode_number,
    )
    if error_response:
        return error_response

    item, _ = _resolve_collection_item(
        source,
        media_type,
        media_id,
        season_number,
        episode_number,
    )

    if item.media_type in _SEASON_OR_SHOW_MEDIA_TYPES:
        return _collection_quick_add_season_or_show_response(request, item)

    entry = CollectionEntry.objects.filter(user=request.user, item=item).first()
    created = False
    if entry is None:
        entry = CollectionEntry.objects.create(user=request.user, item=item)
        created = True
        messages.success(request, f"Added {item.title} to collection")

    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True, "created": created, "entry_id": entry.id})
    return _collection_redirect(request)


@require_POST
def collection_update(request, entry_id):
    """Update collection entry metadata."""
    try:
        entry = CollectionEntry.objects.get(id=entry_id, user=request.user)
    except CollectionEntry.DoesNotExist:
        from django.http import Http404

        msg = "Collection entry not found"
        raise Http404(msg) from None

    form = CollectionEntryForm(
        request.POST,
        instance=entry,
        user=request.user,
        collection_media_type=entry.item.media_type,
    )
    if form.is_valid():
        entry = form.save()
        collected_at = form.cleaned_data.get("collected_at")
        if collected_at:
            CollectionEntry.objects.filter(id=entry.id).update(
                collected_at=collected_at
            )
            entry.collected_at = collected_at
        messages.success(request, f"Updated collection entry for {entry.item.title}")
        if request.headers.get("HX-Request"):
            return JsonResponse(
                {"success": True, "message": "Updated collection entry"}
            )
    else:
        helpers.form_error_messages(form, request)
        if request.headers.get("HX-Request"):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    return _collection_redirect(request)


@require_POST
def collection_remove(request, entry_id):
    """Remove item from collection."""
    try:
        entry = CollectionEntry.objects.get(id=entry_id, user=request.user)
    except CollectionEntry.DoesNotExist:
        from django.http import Http404

        msg = "Collection entry not found"
        raise Http404(msg) from None

    item_title = entry.item.title
    entry.delete()
    messages.success(request, f"Removed {item_title} from collection")

    if request.headers.get("HX-Request"):
        return JsonResponse(
            {"success": True, "message": f"Removed {item_title} from collection"}
        )
    return _collection_redirect(request)


@require_POST
def collection_remove_season(request, season_item_id):
    """Remove all collected episode rows for a season summary chip."""
    season_item = get_object_or_404(
        Item,
        id=season_item_id,
        media_type=MediaTypes.SEASON.value,
    )
    season_title = (
        "Specials"
        if season_item.season_number == 0
        else f"Season {season_item.season_number}"
    )
    deleted_count, _deleted_objects = CollectionEntry.objects.filter(
        user=request.user,
        item__media_id=season_item.media_id,
        item__source=season_item.source,
        item__media_type=MediaTypes.EPISODE.value,
        item__season_number=season_item.season_number,
    ).delete()

    if deleted_count:
        messages.success(request, f"Removed {season_title} from collection")
    else:
        messages.error(request, f"No collected episodes found for {season_title}")

    if request.headers.get("HX-Request"):
        message = (
            f"Removed {season_title} from collection"
            if deleted_count
            else f"No collected episodes found for {season_title}"
        )
        return JsonResponse(
            {
                "success": bool(deleted_count),
                "message": message,
            },
            status=200 if deleted_count else 404,
        )
    return _collection_redirect(request)


def _collection_source_labels_by_item_id(user, item_ids):
    """Return source labels grouped by item id for collection auditing."""
    if not item_ids:
        return {}

    source_labels = dict(CollectionSourceState.SOURCE_CHOICES)
    source_labels_by_item_id = defaultdict(list)
    for state in CollectionSourceState.objects.filter(
        user=user,
        item_id__in=item_ids,
    ).order_by("source"):
        label = source_labels.get(state.source, state.source.title())
        if label not in source_labels_by_item_id[state.item_id]:
            source_labels_by_item_id[state.item_id].append(label)
    return source_labels_by_item_id


def _collection_quality_labels_by_item_id(user, item_ids, *, source=None):
    """Return reported quality labels grouped by item id."""
    if not item_ids:
        return {}

    source_states = CollectionSourceState.objects.filter(
        user=user,
        item_id__in=item_ids,
    ).exclude(quality_label="")
    if source:
        source_states = source_states.filter(source=source)

    quality_labels_by_item_id = {}
    for state in source_states.order_by(
        "source",
        "-last_source_updated_at",
        "-last_synced_at",
        "-id",
    ):
        quality_labels_by_item_id.setdefault(state.item_id, state.quality_label)
    return quality_labels_by_item_id


def _most_common_quality_label(labels):
    """Return the most common non-empty quality label."""
    normalized_labels = [
        str(label).strip() for label in labels if str(label or "").strip()
    ]
    if not normalized_labels:
        return ""
    return Counter(normalized_labels).most_common(1)[0][0]


def _format_collection_progress(label, collected_count, total_count):
    """Render a consistent progress label for modal audit rows."""
    progress = f"{label}: {collected_count}/{total_count}"
    if total_count > 0:
        progress += f" • {math.floor((collected_count / total_count) * 100)}%"
    return progress


def _format_collection_progress_value(collected_count, total_count):
    """Render a progress value without the leading label."""
    progress = f"{collected_count}/{total_count}"
    if total_count > 0:
        progress += f" • {math.floor((collected_count / total_count) * 100)}%"
    return progress


def _episode_collection_entries(user, item, *, season_number=None):
    """Return episode collection rows (manual or integration-synced) for a show."""
    episode_entries = CollectionEntry.objects.filter(
        user=user,
        item__media_id=item.media_id,
        item__source=item.source,
        item__media_type=MediaTypes.EPISODE.value,
    )
    if season_number is not None:
        episode_entries = episode_entries.filter(item__season_number=season_number)

    return list(
        episode_entries.select_related("item").order_by(
            "item__season_number",
            "item__episode_number",
            "-collected_at",
            "-id",
        ),
    )


def _item_has_collection_source_state(user, item, *, source=None):
    """Return True when the current item still has sync-owned source state."""
    source_states = CollectionSourceState.objects.filter(
        user=user,
        item=item,
    )
    if source:
        source_states = source_states.filter(source=source)
    return source_states.exists()


def _build_collection_season_audit_entries(user, item):
    """Return season-level collected-episode summaries for TV/anime show modal auditing."""
    supported_media_types = {
        MediaTypes.TV.value,
        MediaTypes.ANIME.value,
    }
    if item.media_type not in supported_media_types:
        return []

    season_items = list(
        Item.objects.filter(
            media_id=item.media_id,
            source=item.source,
            media_type=MediaTypes.SEASON.value,
        )
        .exclude(season_number=0)
        .order_by("season_number", "id"),
    )
    if not season_items:
        return []

    episode_items = list(
        Item.objects.filter(
            media_id=item.media_id,
            source=item.source,
            media_type=MediaTypes.EPISODE.value,
        )
        .exclude(season_number=0)
        .order_by("season_number", "episode_number", "id"),
    )
    episode_entries = _episode_collection_entries(user, item)
    if not episode_entries:
        return []

    season_item_ids = [season_item.id for season_item in season_items]
    episode_item_ids = [entry.item_id for entry in episode_entries]
    source_labels_by_item_id = _collection_source_labels_by_item_id(
        user,
        season_item_ids + episode_item_ids,
    )
    quality_labels_by_item_id = _collection_quality_labels_by_item_id(
        user,
        episode_item_ids,
        source="sonarr",
    )

    episode_item_ids_by_season_number = defaultdict(set)
    for episode_item in episode_items:
        if episode_item.season_number is None:
            continue
        episode_item_ids_by_season_number[episode_item.season_number].add(
            episode_item.id
        )

    collected_episode_ids_by_season_number = defaultdict(set)
    for episode_entry in episode_entries:
        season_number = episode_entry.item.season_number
        if season_number is None:
            continue
        collected_episode_ids_by_season_number[season_number].add(episode_entry.item_id)

    season_audit_entries = []
    for season_item in season_items:
        season_number = season_item.season_number
        if season_number is None:
            continue

        total_episodes = len(
            episode_item_ids_by_season_number.get(season_number, set())
        )
        collected_episode_ids = collected_episode_ids_by_season_number.get(
            season_number, set()
        )
        collected_count = min(total_episodes, len(collected_episode_ids))
        if collected_count == 0:
            continue

        source_labels = []
        for episode_item_id in sorted(collected_episode_ids):
            for label in source_labels_by_item_id.get(episode_item_id, []):
                if label not in source_labels:
                    source_labels.append(label)
        if not source_labels:
            source_labels = ["Manual"]

        collection_entry = helpers.get_season_collection_metadata(
            user, season_item
        ) or {
            "resolution": "",
            "hdr": "",
            "audio_codec": "",
            "audio_channels": "",
            "bitrate": None,
            "media_type": "",
            "is_3d": False,
            "collected_at": None,
        }
        season_title = "Specials" if season_number == 0 else f"Season {season_number}"
        progress_value = _format_collection_progress_value(
            collected_count,
            total_episodes,
        )
        quality_label = _most_common_quality_label(
            [
                quality_labels_by_item_id.get(episode_item_id, "")
                for episode_item_id in sorted(collected_episode_ids)
            ],
        )
        season_audit_entries.append(
            {
                "collection_entry": collection_entry,
                "season_item_id": season_item.id,
                "title": season_title,
                "display_title": f"{season_title}: {progress_value}",
                "progress_label": _format_collection_progress(
                    "Collected Episodes",
                    collected_count,
                    total_episodes,
                ),
                "source_labels": source_labels,
                "quality_label": quality_label,
            },
        )

    return season_audit_entries


def _build_collection_episode_audit_entries(user, item):
    """Return episode-level collected rows for season modal auditing."""
    if item.media_type != MediaTypes.SEASON.value:
        return []

    episode_entries = _episode_collection_entries(
        user,
        item,
        season_number=item.season_number,
    )
    if not episode_entries:
        return []

    item_ids = {entry.item_id for entry in episode_entries}
    source_labels_by_item_id = _collection_source_labels_by_item_id(user, item_ids)
    quality_labels_by_item_id = _collection_quality_labels_by_item_id(
        user,
        item_ids,
        source="sonarr",
    )

    audit_entries = []
    for entry in episode_entries:
        episode_item = entry.item
        season_number = episode_item.season_number or 0
        episode_number = episode_item.episode_number or 0
        title = episode_item.title or f"Episode {episode_item.episode_number or 0}"
        audit_entries.append(
            {
                "entry": entry,
                "title": f"S{season_number:02d}E{episode_number:02d} - {title}",
                "source_labels": source_labels_by_item_id.get(entry.item_id)
                or ["Manual"],
                "quality_label": quality_labels_by_item_id.get(entry.item_id, ""),
            },
        )

    return audit_entries


def _parse_optional_int(value):
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_collection_numbers(request, media_type, season_number, episode_number):
    """Return an error response when required season/episode numbers are missing."""
    if media_type == MediaTypes.SEASON.value and season_number is None:
        message = "Season number is required"
    elif media_type == MediaTypes.EPISODE.value and (
        season_number is None or episode_number is None
    ):
        message = "Season and episode numbers are required"
    else:
        return None
    if request.headers.get("HX-Request"):
        return HttpResponseBadRequest(message)
    messages.error(request, message)
    return redirect("home")


def _resolve_collection_item(
    source,
    media_type,
    media_id,
    season_number,
    episode_number,
    metadata=None,
):
    """Get or create the Item a collection entry attaches to.

    Returns ``(item, metadata)`` where *metadata* is the provider metadata
    fetched when the item was missing (or for games), else ``None``.
    """
    tracking_media_type = metadata_resolution.get_tracking_media_type(
        media_type,
        source=source,
    )

    lookup = {
        "media_id": media_id,
        "source": source,
        "media_type": tracking_media_type,
    }
    if metadata_resolution.is_grouped_anime_route(media_type, source=source):
        lookup["library_media_type"] = MediaTypes.ANIME.value

    if media_type == MediaTypes.SEASON.value:
        lookup["season_number"] = season_number
    elif media_type == MediaTypes.EPISODE.value:
        lookup["season_number"] = season_number
        lookup["episode_number"] = episode_number

    item = Item.objects.filter(**lookup).first()
    needs_metadata = item is None or media_type == MediaTypes.GAME.value

    if needs_metadata and metadata is None:
        try:
            metadata = services.get_media_metadata(
                media_type,
                media_id,
                source,
                [season_number] if season_number is not None else None,
                episode_number=episode_number,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Collection modal metadata lookup failed: %s",
                exception_summary(exc),
            )

    if not item:
        item_defaults = {
            **Item.title_fields_from_metadata(metadata or {}),
            "library_media_type": (
                (metadata or {}).get("library_media_type") or media_type
            ),
            "image": settings.IMG_NONE,
        }
        try:
            if not item_defaults.get("title"):
                item_defaults["title"] = (
                    (metadata or {}).get("season_title")
                    or (metadata or {}).get("name")
                    or ""
                )
            item_defaults["image"] = (metadata or {}).get("image") or settings.IMG_NONE

            if media_type == MediaTypes.BOOK.value:
                item_defaults["number_of_pages"] = (metadata or {}).get(
                    "max_progress"
                ) or (metadata or {}).get("details", {}).get("number_of_pages")

            if (metadata or {}).get("details", {}).get("runtime"):
                from app.statistics import parse_runtime_to_minutes

                runtime_minutes = parse_runtime_to_minutes(
                    (metadata or {})["details"]["runtime"]
                )
                if runtime_minutes:
                    item_defaults["runtime_minutes"] = runtime_minutes
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Collection modal metadata lookup failed while building defaults: %s",
                exception_summary(exc),
            )

        item, _ = Item.objects.get_or_create(
            **lookup,
            defaults=item_defaults,
        )

    return item, metadata


def build_collection_modal_context(
    request,
    source,
    media_type,
    media_id,
    *,
    season_number=None,
    episode_number=None,
    metadata=None,
):
    """Build reusable collection form context for modals and modal tabs."""
    item, metadata = _resolve_collection_item(
        source,
        media_type,
        media_id,
        season_number,
        episode_number,
        metadata,
    )

    platform_choices = None
    if media_type == MediaTypes.GAME.value:
        platforms = (metadata or {}).get("details", {}).get("platforms") or []
        if platforms:
            platform_choices = platforms

    existing_entries = helpers.get_item_collection_entries(request.user, item)
    existing_entry = existing_entries.first()
    season_audit_entries = _build_collection_season_audit_entries(request.user, item)
    episode_audit_entries = _build_collection_episode_audit_entries(request.user, item)
    visible_existing_entries = list(existing_entries)
    if season_audit_entries:
        # At show level an entry on the show Item cannot say which season it
        # covers, so the per-season audit rows replace it. A season-level entry
        # is unambiguous: keep it visible so it can still be seen and removed.
        visible_existing_entries = []
    form = CollectionEntryForm(
        user=request.user,
        collection_media_type=item.media_type,
        collection_choices_override={"resolution": platform_choices}
        if platform_choices
        else None,
    )
    form.fields["item"].initial = item.id

    return_url = (
        request.GET.get("return_url")
        or request.GET.get("next")
        or request.POST.get("return_url", "")
    )
    collection_fields = getattr(form, "collection_fields", [])

    return {
        "item": item,
        "entry": existing_entry,
        "existing_entries": existing_entries,
        "visible_existing_entries": visible_existing_entries,
        "season_audit_entries": season_audit_entries,
        "episode_audit_entries": episode_audit_entries,
        "form": form,
        "return_url": return_url,
        "collection_fields": collection_fields,
    }


@never_cache
@require_GET
def collection_modal(request, source, media_type, media_id):
    """Return modal HTML for adding and managing collection entries."""
    season_number = _parse_optional_int(request.GET.get("season_number"))
    episode_number = _parse_optional_int(request.GET.get("episode_number"))
    error_response = _validate_collection_numbers(
        request,
        media_type,
        season_number,
        episode_number,
    )
    if error_response:
        return error_response

    response = render(
        request,
        "app/components/collection_modal.html",
        build_collection_modal_context(
            request,
            source,
            media_type,
            media_id,
            season_number=season_number,
            episode_number=episode_number,
        ),
    )
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    response["Vary"] = "Cookie, HX-Request"
    return response


@login_required
@require_GET
@never_cache
def collection_status_api(request, item_id):
    """Return whether a collection entry exists for an item."""
    from app.helpers import is_item_collected

    try:
        item = Item.objects.get(id=item_id)
        collection_entry = is_item_collected(request.user, item)

        return JsonResponse(
            {
                "has_collection_data": collection_entry is not None,
                "item_id": item_id,
            },
        )
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found"}, status=404)
