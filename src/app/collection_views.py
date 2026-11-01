import json
import logging
import math
from collections import Counter, defaultdict

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.db import connection
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.expressions import RawSQL
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.collection_fields import (
    CollectionFieldNotFoundError,
    CollectionFieldValidationError,
    save_collection_field_schema,
    serialize_collection_field_schema,
)
from app.forms import CollectionEntryForm
from app.log_safety import exception_summary
from app.media_list_filters import media_list_entries_for_items
from app.models import (
    CollectionEntry,
    CollectionField,
    CollectionFieldGroup,
    CollectionFieldType,
    Item,
    MediaTypes,
)
from app.providers import services
from app.services import metadata_resolution
from app.templatetags import app_tags
from integrations.models import CollectionSourceState
from users.home_screen import get_home_configurable_media_types

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
COLLECTION_ROW_BATCH = 20
# Query keys that describe one row's slice, not the filters the row inherits.
_ROW_ONLY_PARAMS = (
    "group",
    "type",
    "page",
    "offset",
    "seed",
    "row_type",
    "org.htmx.cache-buster",
)
COLLECTION_RATING_CHOICES = {"all", "rated", "not_rated"}
COLLECTION_COMPLETENESS_CHOICES = {"all", "partial", "full"}
_TV_FAMILY_MEDIA_TYPES = {
    MediaTypes.TV.value,
    MediaTypes.ANIME.value,
    MediaTypes.SEASON.value,
    MediaTypes.EPISODE.value,
}


def _custom_fields_for_list(user, media_type):
    """Return the user's custom fields that apply to *media_type* (all when blank)."""
    fields = CollectionField.objects.filter(group__user=user).order_by(
        "group__position",
        "group_id",
        "position",
        "id",
    )
    return [
        field for field in fields if not media_type or media_type in field.media_types
    ]


def _custom_field_filters(fields):
    """Return the filter menu entries: dropdown and checkbox fields only.

    Text, number and date fields have no short list of values to pick from, so
    they are reached through search and sort instead.
    """
    filters = []
    for field in fields:
        if field.field_type == CollectionFieldType.SELECT and field.options:
            choices = [(option, option) for option in field.options]
        elif field.field_type == CollectionFieldType.CHECKBOX:
            choices = [("true", gettext("Yes")), ("false", gettext("No"))]
        else:
            continue
        filters.append({"id": field.id, "label": field.label, "choices": choices})
    return filters


# Values are read in Python rather than with a JSON key lookup: keys are
# str(field.id), and Django compiles a numeric key as an array index
# ($[2]) on SQLite, so a database lookup silently matches nothing.
def _custom_value_entry_ids(collection, query):
    """Return ids of entries with a custom field value containing *query*."""
    needle = query.casefold()
    return [
        entry_id
        for entry_id, values in collection.values_list("id", "custom_field_values")
        if any(
            not isinstance(value, bool) and needle in str(value).casefold()
            for value in (values or {}).values()
        )
    ]


def _custom_field_values(collection, field_id):
    """Return (entry id, stored value) for one custom field, in id order.

    The database extracts the single value, so the rest of each entry's JSON
    never leaves it. The key is quoted into the path for the reason above.
    """
    column = f'"{collection.model._meta.db_table}"."custom_field_values"'
    if connection.vendor == "sqlite":
        path = '$."' + str(field_id) + '"'
        rows = collection.order_by("id").values_list(
            "id",
            RawSQL(f"json_extract({column}, %s)", [path]),  # noqa: S611 - column is model metadata, key is bound
            RawSQL(f"json_type({column}, %s)", [path]),  # noqa: S611 - column is model metadata, key is bound
        )
        return [
            (pk, {"true": True, "false": False}.get(kind, value))
            for pk, value, kind in rows
        ]
    rows = collection.order_by("id").values_list(
        "id",
        RawSQL(f"{column} -> %s::text", [str(field_id)]),  # noqa: S611 - column is model metadata, key is bound
    )
    return [(pk, value) for pk, value in rows]


def _custom_value_matches(raw, wanted):
    """Return whether a stored value equals the wanted filter value."""
    return raw not in (None, "") and str(raw).casefold() == wanted.casefold()


def _custom_sort_key(raw):
    """Order numbers numerically, checkboxes next, then text alphabetically."""
    if isinstance(raw, bool):
        return (1, int(raw), "")
    if isinstance(raw, int | float):
        return (0, raw, "")
    return (2, 0, str(raw).casefold())


def _ids_ordered_by_custom_field(collection, field, direction):
    """Return entry ids sorted by a custom field, entries with no value last.

    Ties keep newest first, like the other sorts.
    """
    present, blank = [], []
    for entry_id, raw in reversed(_custom_field_values(collection, field.id)):
        if raw in (None, ""):
            blank.append(entry_id)
        else:
            present.append((entry_id, _custom_sort_key(raw)))
    present.sort(key=lambda row: row[1], reverse=direction == "desc")
    return [entry_id for entry_id, _ in present] + blank


def _scored_item_query(user, item_media_types):
    """Return a ``Q`` on ``item_id`` matching items that have a user score."""
    scored = Q(pk__in=[])
    for item_media_type in item_media_types:
        try:
            model = apps.get_model("app", item_media_type)
        except LookupError:
            continue
        if item_media_type == MediaTypes.EPISODE.value:
            filter_kwargs = {"related_season__user": user}
        else:
            filter_kwargs = {"user": user}
        scored |= Q(
            item_id__in=model.objects.filter(
                score__isnull=False,
                **filter_kwargs,
            ).values("item_id"),
        )
    return scored


def _shows_for_keys(show_keys):
    """Resolve (media_id, source) keys to their TV/anime show Items."""
    if not show_keys:
        return []
    media_ids = {media_id for media_id, _source in show_keys}
    sources = {source for _media_id, source in show_keys}
    return [
        item
        for item in Item.objects.filter(
            media_type__in=[MediaTypes.TV.value, MediaTypes.ANIME.value],
            media_id__in=media_ids,
            source__in=sources,
        )
        if (item.media_id, item.source) in show_keys
    ]


def _completeness_matching_keys(user, show_keys, completeness_filter):
    """Return the show keys whose collection is ``partial`` or ``full``.

    Same rules as ``helpers.get_collection_completeness_map`` (a granular
    season/episode collection wins over a show-level entry), but reads one row
    per season instead of one Item per episode.
    """
    if not show_keys:
        return set()
    media_ids = {media_id for media_id, _source in show_keys}
    sources = {source for _media_id, source in show_keys}
    owned = CollectionEntry.objects.filter(user=user, item_id=OuterRef("pk"))

    episodes = defaultdict(list)  # key -> [(season_number, total, collected)]
    for media_id, source, season_number, total, collected in (
        Item.objects.filter(
            media_id__in=media_ids,
            source__in=sources,
            media_type=MediaTypes.EPISODE.value,
        )
        .exclude(season_number=0)
        .order_by()
        .values("media_id", "source", "season_number")
        .annotate(total=Count("pk"), collected=Count("pk", filter=Exists(owned)))
        .values_list("media_id", "source", "season_number", "total", "collected")
    ):
        if (media_id, source) in show_keys:
            episodes[(media_id, source)].append((season_number, total, collected))

    collected_seasons = defaultdict(set)
    for media_id, source, season_number in (
        Item.objects.filter(
            media_id__in=media_ids,
            source__in=sources,
            media_type=MediaTypes.SEASON.value,
        )
        .exclude(season_number=0)
        .filter(Exists(owned))
        .values_list("media_id", "source", "season_number")
    ):
        if (media_id, source) in show_keys:
            collected_seasons[(media_id, source)].add(season_number)

    shows = (
        Item.objects.filter(
            media_type__in=[MediaTypes.TV.value, MediaTypes.ANIME.value],
            media_id__in=media_ids,
            source__in=sources,
        )
        .annotate(is_owned=Exists(owned))
        .values_list("media_id", "source", "is_owned")
    )

    matching = set()
    for media_id, source, show_owned in shows:
        key = (media_id, source)
        if key not in show_keys:
            continue
        groups = episodes.get(key, [])
        total = sum(group_total for _n, group_total, _c in groups)
        seasons = collected_seasons.get(key, set())
        granular = bool(seasons) or any(group[2] for group in groups)
        if not granular:
            collected = total if show_owned else 0
        else:
            collected = sum(
                group_total
                if season_number in seasons and season_number is not None
                else group_collected
                for season_number, group_total, group_collected in groups
            )
        if not total:
            continue
        if (completeness_filter == "partial" and 0 < collected < total) or (
            completeness_filter == "full" and collected == total
        ):
            matching.add(key)
    return matching


# Custom fields that number a copy within its item. A manga series is one item
# whose copies are told apart only by volume, so a card needs to say which.
_COPY_NUMBER_LABELS = {"volume": "Vol. %s", "issue": "#%s", "issue nr": "#%s"}


def _copy_labels(user, entries):
    """Return ``{entry id: "Vol. 3"}`` for entries whose copy carries a number."""
    numbering = {
        str(field.id): _COPY_NUMBER_LABELS[field.label.strip().casefold()]
        for field in CollectionField.objects.filter(group__user=user)
        if field.label.strip().casefold() in _COPY_NUMBER_LABELS
    }
    labels = {}
    for entry in entries:
        for field_id, pattern in numbering.items():
            value = (entry.custom_field_values or {}).get(field_id)
            if value in (None, ""):
                continue
            number = f"{value:g}" if isinstance(value, float) else str(value)
            labels[entry.id] = pattern % number
            break
    return labels


def _decorate_collection_entries(user, entries):
    """Attach the user's media (rating, status) and TV completeness to entries."""
    media_by_item_id = {
        library_entry.item.pk: library_entry.media
        for library_entry in media_list_entries_for_items(
            user,
            list({entry.item_id: entry.item for entry in entries}.values()),
        )
    }
    from app.media_list_filters import attach_card_collection_platforms

    attach_card_collection_platforms(user, [entry.item for entry in entries])
    copy_labels = _copy_labels(user, entries)
    for entry in entries:
        entry.media = media_by_item_id.get(entry.item_id)
        entry.copy_label = copy_labels.get(entry.id, "")
    badge_entries = [
        entry
        for entry in entries
        if entry.item.media_type in _SEASON_OR_SHOW_MEDIA_TYPES
    ]
    if badge_entries:
        badge_show_keys = {
            (entry.item.media_id, entry.item.source) for entry in badge_entries
        }
        badge_completeness_map = helpers.get_collection_completeness_map(
            user,
            _shows_for_keys(badge_show_keys),
        )
        for entry in badge_entries:
            entry.completeness = badge_completeness_map.get(entry.item_id)


def _ordered_collection_slice(collection, sort_by, direction, custom_field, offset):
    """Return one batch of entries in the selected sort order."""
    end = offset + COLLECTION_ROW_BATCH
    if custom_field:
        ids = _ids_ordered_by_custom_field(collection, custom_field, direction)
        ids = ids[offset:end]
        entries_by_id = collection.in_bulk(ids)
        return [entries_by_id[pk] for pk in ids]
    order_field = COLLECTION_SORT_FIELDS[sort_by]
    if direction == "desc":
        order_field = f"-{order_field}"
    return list(collection.order_by(order_field, "-id")[offset:end])


def _collection_media_type_rows(
    request,
    collection,
    sort_by,
    direction,
    custom_field,
):
    """Build one scrollable row per media type, in the user's Home order."""
    totals = dict(
        collection.order_by()
        .values_list("item__media_type")
        .annotate(total=Count("id")),
    )
    # Collection lists every owned type, disabled ones included, so keep the
    # user's saved order for those as well as the enabled ones.
    saved_order = list(request.user.home_screen_media_type_order or [])
    home_order = saved_order + [
        t
        for t in get_home_configurable_media_types(request.user)
        if t not in saved_order
    ]
    ordered_types = [t for t in home_order if t in totals] + [
        t for t in MediaTypes.values if t in totals and t not in home_order
    ]
    inherited = [
        (key, value)
        for key, values in request.GET.lists()
        if key not in _ROW_ONLY_PARAMS
        for value in values
    ]
    entries_by_type = {
        row_type: _ordered_collection_slice(
            collection.filter(item__media_type=row_type),
            sort_by,
            direction,
            custom_field,
            0,
        )
        for row_type in ordered_types
    }
    # Decorate every row in one pass: copy labels and TV completeness are
    # per-user, not per-type, so a pass per row repeats the same queries.
    _decorate_collection_entries(
        request.user,
        [entry for entries in entries_by_type.values() for entry in entries],
    )
    rows = []
    for row_type, entries in entries_by_type.items():
        load_more_query = urlencode(
            [*inherited, ("group", "type"), ("row_type", row_type)],
        )
        rows.append(
            {
                "row_id": f"collection-{row_type}",
                "title_main": app_tags.media_type_readable_plural(row_type),
                "icon_svg": str(
                    app_tags.icon(row_type, False, "w-5 h-5"),
                ),
                "summary": gettext("%(count)s collected") % {"count": totals[row_type]},
                "view_all_text": gettext("View all"),
                "view_all_url": reverse("collection_list_filtered", args=[row_type])
                + (f"?{urlencode(inherited)}" if inherited else ""),
                "view_all_internal": True,
                "load_more_url": f"{reverse('collection_list')}?{load_more_query}",
                "items": entries,
                "total": totals[row_type],
                "loaded_count": len(entries),
                "card_width_class": "w-44",
                "grid_class": "",
            },
        )
    return rows


@require_GET
def collection_list(request, media_type=None):
    """Display user's collection, filterable by type, format, and rating."""
    effective_media_type = media_type or request.GET.get("type", "")
    if effective_media_type == "all":
        effective_media_type = ""

    search_query = request.GET.get("q", "").strip()
    custom_fields = _custom_fields_for_list(request.user, effective_media_type)
    custom_fields_by_id = {str(field.id): field for field in custom_fields}
    sort_by = request.GET.get("sort", "collected_at")
    custom_sort_field = None
    if sort_by.startswith("field_") and sort_by[6:] in custom_fields_by_id:
        custom_sort_field = custom_fields_by_id[sort_by[6:]]
    elif sort_by not in COLLECTION_SORT_FIELDS:
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
    # Free text, so no value ("all" included) can double as "any location".
    location_filter = request.GET.get("location", "")
    rating_filter = request.GET.get("rating", "all")
    if rating_filter not in COLLECTION_RATING_CHOICES:
        rating_filter = "all"
    completeness_filter = request.GET.get("completeness", "all")
    if completeness_filter not in COLLECTION_COMPLETENESS_CHOICES:
        completeness_filter = "all"
    custom_filter_field = request.GET.get("field", "")
    custom_filter_value = request.GET.get("field_value", "")
    if custom_filter_field not in custom_fields_by_id or not custom_filter_value:
        custom_filter_field = custom_filter_value = ""

    collection = helpers.get_user_collection(request.user, effective_media_type)
    if search_query:
        collection = collection.filter(
            Q(item__title__icontains=search_query)
            | Q(id__in=_custom_value_entry_ids(collection, search_query)),
        )
    if custom_filter_field:
        collection = collection.filter(
            id__in=[
                entry_id
                for entry_id, raw in _custom_field_values(
                    collection,
                    custom_filter_field,
                )
                if _custom_value_matches(raw, custom_filter_value)
            ],
        )
    if format_filter:
        collection = collection.filter(media_type=format_filter)
    if resolution_filter:
        collection = collection.filter(resolution=resolution_filter)
    if hdr_filter:
        collection = collection.filter(hdr=hdr_filter)
    if location_filter:
        collection = collection.filter(purchase_location=location_filter)

    if rating_filter != "all":
        scored = _scored_item_query(
            request.user,
            collection.order_by().values_list("item__media_type", flat=True).distinct(),
        )
        if rating_filter == "rated":
            collection = collection.filter(scored)
        else:
            collection = collection.exclude(scored)

    if completeness_filter != "all":
        show_keys = set(
            collection.filter(item__media_type__in=_TV_FAMILY_MEDIA_TYPES)
            .values_list("item__media_id", "item__source")
            .distinct(),
        )
        matching_keys = _completeness_matching_keys(
            request.user,
            show_keys,
            completeness_filter,
        )

        if matching_keys:
            key_query = Q()
            for match_media_id, match_source in matching_keys:
                key_query |= Q(
                    item__media_id=match_media_id,
                    item__source=match_source,
                )
            collection = collection.filter(
                item__media_type__in=_TV_FAMILY_MEDIA_TYPES,
            ).filter(key_query)
        else:
            collection = collection.none()

    # Rows are a grid-only layout and only make sense across several types.
    group_by_type = (
        request.GET.get("group") == "type"
        and not effective_media_type
        and layout == "grid"
    )
    row_type = request.GET.get("row_type", "")
    if group_by_type and row_type in MediaTypes.values:
        try:
            offset = max(0, int(request.GET.get("offset", 0)))
        except ValueError:
            offset = 0
        entries = _ordered_collection_slice(
            collection.filter(item__media_type=row_type),
            sort_by,
            direction,
            custom_sort_field,
            offset,
        )
        _decorate_collection_entries(request.user, entries)
        return render(
            request,
            "app/components/collection_row_grid.html",
            {"media_list": {"items": entries}},
        )

    page_number = helpers.get_page_number(request)
    collection_rows = []
    page_obj = []
    if group_by_type:
        collection_rows = _collection_media_type_rows(
            request,
            collection,
            sort_by,
            direction,
            custom_sort_field,
        )
    else:
        if custom_sort_field:
            paginator = Paginator(
                _ids_ordered_by_custom_field(collection, custom_sort_field, direction),
                20,
            )
        else:
            order_field = COLLECTION_SORT_FIELDS[sort_by]
            if direction == "desc":
                order_field = f"-{order_field}"
            paginator = Paginator(collection.order_by(order_field, "-id"), 20)
        try:
            page_obj = paginator.page(page_number)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)
        if custom_sort_field:
            # The page holds ids; load only those entries, in the sorted order.
            entries_by_id = collection.in_bulk(page_obj.object_list)
            page_obj.object_list = [entries_by_id[pk] for pk in page_obj.object_list]

        # The card shows the user's rating and status the same way the library does.
        _decorate_collection_entries(request.user, list(page_obj.object_list))

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
    available_locations = sorted(
        value
        for value in base_collection.exclude(purchase_location="")
        .order_by()
        .values_list("purchase_location", flat=True)
        .distinct()
        if value
    )

    is_fragment = helpers.is_htmx_fragment(request)
    context = {
        "collection_entries": page_obj,
        "collection_rows": collection_rows,
        "group_by_type": group_by_type,
        "media_type": effective_media_type,
        "media_types": media_types,
        "available_formats": available_formats,
        "available_resolutions": available_resolutions,
        "available_hdr": available_hdr,
        "available_locations": available_locations,
        "sort_choices": [
            *COLLECTION_SORT_CHOICES,
            *((f"field_{field.id}", field.label) for field in custom_fields),
        ],
        "custom_field_filters": _custom_field_filters(custom_fields),
        "custom_filter_field": custom_filter_field,
        "custom_filter_value": custom_filter_value,
        "sort_by": sort_by,
        "direction": direction,
        "layout": layout,
        "format_filter": format_filter,
        "resolution_filter": resolution_filter,
        "hdr_filter": hdr_filter,
        "location_filter": location_filter,
        "rating_filter": rating_filter,
        "completeness_filter": completeness_filter,
        "has_tv_family_collection": bool(
            _TV_FAMILY_MEDIA_TYPES & available_media_types,
        ),
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
    left untouched. Returns (created_entries, skipped_count).
    """
    episode_items = list(_episodes_for_season_or_show(item))
    if not episode_items:
        return [], 0

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
        return [], len(episode_items)

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

    return new_entries, len(already_collected_ids)


def _collection_add_season_or_show_response(request, item, form, post_data):
    """Expand a season/show collection submission into per-episode entries."""
    created_entries, skipped_count = _expand_collection_entry_to_episodes(
        request.user,
        item,
        cleaned_data=form.cleaned_data,
    )
    if created_entries:
        values = _custom_field_values_from_post(
            request.user,
            post_data,
            scope_media_type=item.media_type,
        )
        if values:
            CollectionEntry.objects.filter(
                id__in=[entry.id for entry in created_entries],
            ).update(custom_field_values=values)
        message = gettext("Added %(value_1)s episode(s) to collection") % {
            "value_1": len(created_entries)
        }
        if skipped_count:
            message += f" ({skipped_count} already collected)"
    else:
        message = gettext("All episodes are already in your collection")
    messages.success(request, message)
    if request.headers.get("HX-Request"):
        return JsonResponse({"success": True, "message": message})
    return _collection_redirect(request)


def _collection_quick_add_season_or_show_response(request, item):
    """Expand a season/show quick-add into per-episode entries."""
    created_entries, skipped_count = _expand_collection_entry_to_episodes(
        request.user,
        item,
        cleaned_data={},
    )
    if created_entries:
        message = gettext("Added %(value_1)s episode(s) to collection") % {
            "value_1": len(created_entries)
        }
        if skipped_count:
            message += f" ({skipped_count} already collected)"
        messages.success(request, message)
    else:
        message = gettext("All episodes are already in your collection")
    if request.headers.get("HX-Request"):
        return JsonResponse(
            {"success": True, "created": bool(created_entries), "message": message}
        )
    return _collection_redirect(request)


@require_POST
def collection_add(request):
    """Add a new owned copy to collection (with optional metadata)."""
    item_id = request.POST.get("item_id")
    if not item_id:
        if request.headers.get("HX-Request"):
            return HttpResponseBadRequest("Item ID is required")
        messages.error(request, gettext("Item ID is required"))
        return _collection_redirect(request)

    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        if request.headers.get("HX-Request"):
            return HttpResponseBadRequest("Item not found")
        messages.error(request, gettext("Item not found"))
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
            return _collection_add_season_or_show_response(
                request, item, form, post_data
            )

        entry = form.save(commit=False)
        entry.user = request.user
        entry.item = item
        entry.save()

        collected_at = form.cleaned_data.get("collected_at")
        if collected_at:
            CollectionEntry.objects.filter(id=entry.id).update(
                collected_at=collected_at
            )
            entry.collected_at = collected_at
        _apply_custom_field_values(entry, request.user, post_data)
        messages.success(
            request,
            gettext("Added %(value_1)s to collection") % {"value_1": item.title},
        )
        if request.headers.get("HX-Request"):
            return JsonResponse(
                {
                    "success": True,
                    "message": gettext("Added %(value_1)s to collection")
                    % {"value_1": item.title},
                }
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
        messages.success(
            request,
            gettext("Added %(value_1)s to collection") % {"value_1": item.title},
        )

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
        _apply_custom_field_values(entry, request.user, request.POST)
        messages.success(
            request,
            gettext("Updated collection entry for %(value_1)s")
            % {"value_1": entry.item.title},
        )
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
    messages.success(
        request,
        gettext("Removed %(value_1)s from collection") % {"value_1": item_title},
    )

    if request.headers.get("HX-Request"):
        return JsonResponse(
            {
                "success": True,
                "message": gettext("Removed %(value_1)s from collection")
                % {"value_1": item_title},
            }
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
        messages.success(
            request,
            gettext("Removed %(value_1)s from collection") % {"value_1": season_title},
        )
    else:
        messages.error(
            request,
            gettext("No collected episodes found for %(value_1)s")
            % {"value_1": season_title},
        )

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


@require_POST
def collection_update_season(request, season_item_id):
    """Apply edited format details to every collected episode of a season."""
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
    post_data = request.POST.copy()
    post_data["item"] = season_item.id
    form = CollectionEntryForm(
        post_data,
        user=request.user,
        collection_media_type=season_item.media_type,
    )
    if not form.is_valid():
        helpers.form_error_messages(form, request)
        if request.headers.get("HX-Request"):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
        return _collection_redirect(request)

    copy_fields = {
        field: form.cleaned_data[field]
        for field in _COLLECTION_ENTRY_COPY_FIELDS
        if field in form.cleaned_data
    }
    updated_count = CollectionEntry.objects.filter(
        user=request.user,
        item__media_id=season_item.media_id,
        item__source=season_item.source,
        item__media_type=MediaTypes.EPISODE.value,
        item__season_number=season_item.season_number,
    ).update(**copy_fields, updated_at=timezone.now())

    if updated_count:
        message = gettext("Updated %(value_1)s in collection") % {
            "value_1": season_title
        }
        messages.success(request, message)
    else:
        message = gettext("No collected episodes found for %(value_1)s") % {
            "value_1": season_title
        }
        messages.error(request, message)
    if request.headers.get("HX-Request"):
        return JsonResponse(
            {"success": bool(updated_count), "message": message},
            status=200 if updated_count else 404,
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
        message = gettext("Season number is required")
    elif media_type == MediaTypes.EPISODE.value and (
        season_number is None or episode_number is None
    ):
        message = gettext("Season and episode numbers are required")
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


def _custom_fields_fragment_context(request, item, *, manage_fields_open=False):
    """Build context for the custom-fields fragment, scoped to one item."""
    existing_entry = helpers.get_item_collection_entries(request.user, item).first()
    return {
        "item": item,
        "custom_field_groups": _visible_custom_field_groups(
            request.user, item.media_type
        ),
        "entry_custom_field_values": existing_entry.custom_field_values
        if existing_entry
        else {},
        "manage_fields_open": manage_fields_open,
        "custom_field_schema_json": json.dumps(
            serialize_collection_field_schema(request.user)
        ),
        "field_type_choices_json": json.dumps(
            [
                {"value": value, "label": label}
                for value, label in CollectionFieldType.choices
            ]
        ),
        "media_type_choices_json": json.dumps(
            [{"value": value, "label": label} for value, label in MediaTypes.choices]
        ),
        "collection_fields_save_url": reverse("collection_fields_save"),
    }


def _visible_custom_field_groups(user, media_type):
    """Return the user's field groups with only fields matching media_type."""
    groups = CollectionFieldGroup.objects.filter(user=user).prefetch_related("fields")
    visible_groups = []
    for group in groups:
        visible_fields = [
            field for field in group.fields.all() if media_type in field.media_types
        ]
        if visible_fields:
            group.visible_fields = visible_fields
            visible_groups.append(group)
    return visible_groups


def _custom_field_input_name(field_id):
    """Return the POST field name used for a custom field's value."""
    return f"custom_field_{field_id}"


def _custom_field_values_from_post(
    user, post_data, *, scope_media_type, base_values=None
):
    """Return the custom_field_values dict implied by a submitted form.

    Only considers fields scoped to scope_media_type, so submitting a form
    for one media type never clobbers values stored for a field the form
    never rendered (e.g. a book-only checkbox while adding a movie).
    """
    fields = CollectionField.objects.filter(group__user=user)
    values = dict(base_values or {})
    for field in fields:
        if scope_media_type not in field.media_types:
            continue
        input_name = _custom_field_input_name(field.id)
        if field.field_type == CollectionFieldType.CHECKBOX:
            values[str(field.id)] = input_name in post_data
            continue
        if input_name not in post_data:
            continue
        raw_value = post_data.get(input_name, "").strip()
        if not raw_value:
            values.pop(str(field.id), None)
            continue
        if field.field_type == CollectionFieldType.NUMBER:
            try:
                raw_value = float(raw_value)
            except ValueError:
                continue
        elif field.field_type == CollectionFieldType.SELECT and (
            raw_value not in field.options
        ):
            continue
        values[str(field.id)] = raw_value
    return values


def _apply_custom_field_values(entry, user, post_data, *, scope_media_type=None):
    """Read submitted custom_field_* values and store them on the entry."""
    entry.custom_field_values = _custom_field_values_from_post(
        user,
        post_data,
        scope_media_type=scope_media_type or entry.item.media_type,
        base_values=entry.custom_field_values,
    )
    entry.save(update_fields=["custom_field_values"])


def _edit_form_for(
    user, media_type, *, form_key, instance=None, initial=None, choices_override=None
):
    """Return an inline edit form whose widget ids cannot clash with the add form."""
    return CollectionEntryForm(
        instance=instance,
        initial=initial,
        user=user,
        collection_media_type=media_type,
        collection_choices_override={"resolution": choices_override}
        if choices_override
        else None,
        auto_id=f"id_edit_{form_key}_%s",
    )


def _attach_entry_edit_forms(user, entries, platform_choices=None):
    """Give each real CollectionEntry what its inline edit form needs."""
    for entry in entries:
        entry.edit_form = _edit_form_for(
            user,
            entry.item.media_type,
            form_key=entry.id,
            instance=entry,
            choices_override=platform_choices,
        )
        entry.edit_form_id = f"collection-edit-form-{entry.id}"
        entry.edit_id_prefix = f"edit_{entry.id}_"
        entry.edit_update_url = reverse("collection_update", args=[entry.id])


def _attach_season_edit_forms(user, season_audit_entries):
    """Give each season summary row a form that edits all its episode entries."""
    for row in season_audit_entries:
        form = _edit_form_for(
            user,
            MediaTypes.SEASON.value,
            form_key=f"season_{row['season_item_id']}",
            initial={
                field: row["collection_entry"].get(field)
                for field in _COLLECTION_ENTRY_COPY_FIELDS
            },
        )
        row["edit_form"] = form
        row["edit_title"] = gettext("Edit all episodes in this season")
        row["edit_collection_fields"] = [
            field
            for field in form.collection_fields
            if field in _COLLECTION_ENTRY_COPY_FIELDS
        ]
        row["edit_form_id"] = f"collection-edit-form-season-{row['season_item_id']}"
        row["edit_update_url"] = reverse(
            "collection_update_season", args=[row["season_item_id"]]
        )


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
    _attach_entry_edit_forms(request.user, visible_existing_entries, platform_choices)
    _attach_entry_edit_forms(
        request.user, [row["entry"] for row in episode_audit_entries]
    )
    _attach_season_edit_forms(request.user, season_audit_entries)
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
        **_custom_fields_fragment_context(request, item),
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
@require_POST
def collection_fields_save(request):
    """Reconcile the user's whole custom-field schema from one JSON payload."""
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    try:
        groups = save_collection_field_schema(request.user, payload)
    except CollectionFieldValidationError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except CollectionFieldNotFoundError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=404)

    html = None
    item = Item.objects.filter(id=payload.get("item_id")).first()
    if item is not None:
        html = render_to_string(
            "app/components/collection_custom_fields.html",
            _custom_fields_fragment_context(request, item, manage_fields_open=False),
            request=request,
        )
    return JsonResponse({"success": True, "groups": groups, "html": html})


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
