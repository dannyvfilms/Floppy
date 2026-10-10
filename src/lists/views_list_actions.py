"""List management action views.

Covers CRUD, column preferences, the modal, item toggle and release-year fetch.

None of these views render the list detail page — they mutate state or return
small fragments. The read-heavy detail views live in views_list_detail.py and
views_smart_list.py; the browse views live in views_list_browse.py.
"""

import contextlib
import json
import logging
import os
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.cache import cache
from django.db import OperationalError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_GET, require_POST

from app import helpers
from app.columns import sanitize_column_prefs
from app.db_retry import is_contention_error, is_lock_error
from app.discover import tab_cache as discover_tab_cache
from app.library_query.adapters import (
    SMART_RULES_CURRENT_SEMANTICS,
    SMART_RULES_SEMANTICS_KEY,
)
from app.models import Item, MediaTypes, Status
from app.providers import services
from app.redis_diagnosis import queue_failure_message
from app.services import metadata_resolution
from app.templatetags.app_tags import media_type_readable_plural
from integrations.upload_staging import (
    enqueue_staged_task,
    stage_uploaded_file,
    staging_failure_message,
)
from lists import smart_rules
from lists import tasks as list_tasks
from lists.forms import CustomListForm
from lists.models import (
    CustomList,
    CustomListItem,
    ListActivity,
    ListActivityType,
)
from lists.views_helpers import (
    _build_list_url_template,
    _list_item_title_fields_from_metadata,
    _maybe_backfill_episode_title,
)
from users.models import ListDetailSortChoices, MediaSortChoices

logger = logging.getLogger(__name__)


@require_POST
def update_list_table_columns(request, list_id):
    """Persist list-table column prefs without overwriting regular media-list prefs."""
    if not request.user.is_authenticated:
        return HttpResponseBadRequest("Authentication required")

    custom_list = get_object_or_404(
        CustomList.objects.select_related("owner").prefetch_related("collaborators"),
        id=list_id,
    )
    if not custom_list.user_can_view(request.user):
        msg = "List not found"
        raise Http404(msg)

    media_type = request.POST.get("media_type_key", "all")
    if media_type != "all" and media_type not in MediaTypes.values:
        media_type = "all"

    raw_order = request.POST.get("order", "[]")
    raw_hidden = request.POST.get("hidden", "[]")

    try:
        parsed_order = json.loads(raw_order)
    except json.JSONDecodeError:
        parsed_order = []
    try:
        parsed_hidden = json.loads(raw_hidden)
    except json.JSONDecodeError:
        parsed_hidden = []

    order = (
        [value for value in parsed_order if isinstance(value, str)]
        if isinstance(parsed_order, list)
        else []
    )
    hidden = (
        [value for value in parsed_hidden if isinstance(value, str)]
        if isinstance(parsed_hidden, list)
        else []
    )

    valid_sorts = {choice[0] for choice in ListDetailSortChoices.choices}
    current_sort = request.POST.get("sort", ListDetailSortChoices.DATE_ADDED)
    if current_sort not in valid_sorts:
        current_sort = ListDetailSortChoices.DATE_ADDED

    clean_order, clean_hidden = sanitize_column_prefs(
        media_type=media_type,
        current_sort=current_sort,
        user=request.user,
        table_type="list",
        order=order,
        hidden=hidden,
    )

    request.user.update_column_prefs(
        media_type=media_type,
        table_type="list",
        order=clean_order,
        hidden=clean_hidden,
    )

    response = HttpResponse(status=204)
    response["HX-Trigger"] = json.dumps({"refreshTableColumns": True})
    return response


@require_POST
def create(request):
    """Create a new custom list."""
    form = CustomListForm(request.POST, user=request.user)
    if form.is_valid():
        custom_list = form.save(commit=False)
        custom_list.owner = request.user
        custom_list.save()
        form.save_m2m()
        logger.info("%s list created successfully.", custom_list)
        ListActivity.objects.create(
            custom_list=custom_list,
            user=request.user,
            activity_type=ListActivityType.LIST_CREATED,
        )
        if custom_list.is_smart and request.POST.get("smart_create_flow"):
            return redirect(
                f"{reverse('list_detail', args=[custom_list.public_reference])}?edit_smart_rules=1",
            )
    else:
        logger.error(form.errors.as_json())
        helpers.form_error_messages(form, request)
    return helpers.redirect_back(request)


def _build_share_view_name(media_type, normalized_rules):
    """Build a short, human-readable name for a Share View smart list."""
    parts = [media_type_readable_plural(media_type)]

    statuses = normalized_rules.get("status") or []
    if statuses:
        parts.append(", ".join(Status(value).label for value in statuses))

    sort_value = normalized_rules.get("sort")
    if sort_value:
        with contextlib.suppress(ValueError):
            parts.append(f"sorted by {MediaSortChoices(sort_value).label}")

    return " — ".join(parts)


@login_required
@require_POST
def share_view(request):
    """Create (or reuse) a public smart list snapshotting the current view."""
    media_type = request.POST.get("media_type", "")
    if media_type not in MediaTypes.values:
        return HttpResponseBadRequest("Invalid media type")

    normalized = smart_rules.normalize_rule_payload(request.POST, request.user)
    smart_media_types = [media_type]
    smart_filters = {
        key: normalized.get(key, smart_rules.SMART_FILTER_DEFAULTS[key])
        for key in smart_rules.SMART_FILTER_KEYS
    }
    # A snapshot of a media-list view evaluates the way that view does.
    smart_filters[SMART_RULES_SEMANTICS_KEY] = str(SMART_RULES_CURRENT_SEMANTICS)

    existing = CustomList.objects.filter(
        owner=request.user,
        is_smart=True,
        visibility="public",
        smart_media_types=smart_media_types,
        smart_filters=smart_filters,
    ).first()

    if existing:
        custom_list = existing
    else:
        custom_list = CustomList.objects.create(
            name=_build_share_view_name(media_type, normalized),
            owner=request.user,
            visibility="public",
            is_smart=True,
            smart_media_types=smart_media_types,
            smart_filters=smart_filters,
        )
        ListActivity.objects.create(
            custom_list=custom_list,
            user=request.user,
            activity_type=ListActivityType.LIST_CREATED,
        )
        list_tasks.sync_smart_list_task.delay(custom_list.id)

    return JsonResponse({"url": custom_list.get_absolute_url()})


@login_required
@require_POST
def smart_rules_update(request, list_id):
    """Persist smart list rules and sync list membership."""
    custom_list = get_object_or_404(CustomList, id=list_id)
    if not custom_list.user_can_edit(request.user):
        return HttpResponse(status=403)
    if not custom_list.is_smart:
        return JsonResponse({"error": "This list is not a smart list."}, status=400)

    payload = request.POST
    content_type = request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    normalized = smart_rules.normalize_rule_payload(payload, custom_list.owner)
    custom_list.smart_media_types = normalized["media_types"]
    custom_list.smart_excluded_media_types = []
    custom_list.smart_filters = smart_rules.saved_filters(normalized, custom_list)
    custom_list.save(
        update_fields=[
            "smart_media_types",
            "smart_excluded_media_types",
            "smart_filters",
        ],
    )
    custom_list.sync_smart_items()

    return JsonResponse(
        {
            "items_count": custom_list.items.count(),
            "rules": normalized,
        },
    )


@require_POST
def edit(request):
    """Edit an existing custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_edit(request.user):
        form = CustomListForm(request.POST, instance=custom_list, user=request.user)
        if form.is_valid():
            form.save()
            logger.info("%s list edited successfully.", custom_list)
            ListActivity.objects.create(
                custom_list=custom_list,
                user=request.user,
                activity_type=ListActivityType.LIST_EDITED,
            )
        else:
            logger.error(form.errors.as_json())
            helpers.form_error_messages(form, request)
    else:
        messages.error(
            request, gettext("You do not have permission to edit this list.")
        )
    return helpers.redirect_back(request)


@require_GET
def edit_form(request, list_id):
    """Render the edit-list modal fragment for a single list, on demand.

    Building this select2-backed form for every list on the /lists page
    eagerly was expensive (a Redis round-trip per widget render), so it's
    fetched lazily when the user opens the edit modal instead.
    """
    custom_list = get_object_or_404(CustomList, id=list_id)
    if not custom_list.user_can_edit(request.user):
        return HttpResponse(status=403)

    available_tags = CustomListForm._normalize_tags(
        tag
        for other_list in CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
        ).only("tags")
        for tag in (other_list.tags or [])
    )
    form = CustomListForm(
        instance=custom_list,
        auto_id=f"id_{custom_list.id}_%s",
        user=request.user,
        available_tags=available_tags,
    )
    return render(
        request,
        "lists/components/list_form.html",
        {
            "form": form,
            "custom_list": custom_list,
            "list_url_template": _build_list_url_template(request),
            # request.path is this fragment's URL, not the page hosting the modal.
            "next_url": reverse("lists"),
        },
    )


@require_POST
def delete(request):
    """Delete a custom list."""
    list_id = request.POST.get("list_id")
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.user_can_delete(request.user):
        custom_list.delete()
        logger.info("%s list deleted successfully.", custom_list)
        return redirect("lists")

    messages.error(request, gettext("You do not have permission to delete this list."))
    return helpers.redirect_back(request)


@require_POST
def import_list_csv(request):
    """Import a single custom list from an uploaded CSV file."""
    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        messages.error(request, gettext("Select a CSV file to import."))
        return redirect("lists")

    try:
        staged_file = str(stage_uploaded_file(csv_file))
    except OSError as error:
        logger.exception("Could not stage custom list CSV upload")
        messages.error(request, staging_failure_message(error))
        return redirect("lists")

    try:
        enqueue_staged_task(
            list_tasks.import_list_csv_task,
            request.user.id,
            staged_file,
            "new",
            staged_paths=(staged_file,),
        )
    except Exception as error:
        logger.exception("Could not queue custom list CSV import")
        messages.error(
            request,
            queue_failure_message(
                error,
                "The list import could not be queued.",
                "Try again.",
                settings.CELERY_BROKER_URL,
            ),
        )
        return redirect("lists")

    messages.info(request, gettext("List import started in the background."))
    return redirect("lists")


@require_GET
def lists_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the modal showing all custom lists and allowing to add to them."""
    tracking_media_type = metadata_resolution.get_tracking_media_type(
        media_type,
        source=source,
    )
    lookup = {
        "media_id": media_id,
        "source": source,
        "media_type": tracking_media_type,
        "season_number": season_number,
        "episode_number": episode_number,
    }
    if metadata_resolution.is_grouped_anime_route(media_type, source=source):
        lookup["library_media_type"] = MediaTypes.ANIME.value

    try:
        item = Item.objects.get(**lookup)
        _maybe_backfill_episode_title(item, force=True)
    except Item.MultipleObjectsReturned:
        item = Item.objects.filter(**lookup).first()
    except Item.DoesNotExist:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number],
            episode_number,
        )
        item = Item.objects.create(
            media_id=media_id,
            source=source,
            media_type=tracking_media_type,
            season_number=season_number,
            episode_number=episode_number,
            library_media_type=metadata.get("library_media_type") or media_type,
            image=metadata["image"],
            **_list_item_title_fields_from_metadata(tracking_media_type, metadata),
        )

    custom_lists = CustomList.objects.get_user_lists_with_item(request.user, item)
    if hasattr(custom_lists, "filter"):
        custom_lists = custom_lists.filter(is_smart=False)
    else:
        custom_lists = [
            custom_list
            for custom_list in custom_lists
            if not getattr(custom_list, "is_smart", False)
        ]
    custom_lists = list(custom_lists)
    on_list_count = sum(
        1 for custom_list in custom_lists if getattr(custom_list, "has_item", False)
    )

    selected_tag = (request.GET.get("tag") or "").strip()

    unique_tags = sorted(
        {
            tag.strip()
            for custom_list in custom_lists
            for tag in (custom_list.tags or [])
            if isinstance(tag, str) and tag.strip()
        },
        key=str.lower,
    )

    if selected_tag:
        selected_tag_folded = selected_tag.casefold()
        custom_lists = [
            custom_list
            for custom_list in custom_lists
            if any(
                isinstance(tag, str) and tag.strip().casefold() == selected_tag_folded
                for tag in (custom_list.tags or [])
            )
        ]

    return render(
        request,
        "lists/components/fill_lists.html",
        {
            "item": item,
            "custom_lists": custom_lists,
            "list_tags": unique_tags,
            "selected_list_tag": selected_tag,
            "on_list_count": on_list_count,
        },
    )


def _list_item_toggle_error_response(*, busy=False):
    """Return an empty HTMX response that only triggers an error toast.

    htmx doesn't swap the response body for 4xx/5xx status codes by
    default, so the button stays exactly as it was — accurate, since
    nothing committed — while HX-Trigger still fires the toast regardless
    of swap/status.
    """
    if busy:
        status = 503
        message = "The database is busy right now, so nothing changed. Please try again."
    else:
        status = 500
        message = (
            "Couldn't update this list — please try again. If it "
            "keeps happening, file a bug report from "
            "Settings > Advanced."
        )
    response = HttpResponse(status=status)
    response["HX-Trigger"] = json.dumps(
        {"showToast": {"message": message, "type": "error"}},
    )
    return response


# SQLite reports a stale read snapshot as "database is locked" at once, without
# waiting out busy_timeout, so a couple of quick retries clear it. A lock that
# already waited the full timeout is a long writer, and retrying only doubles
# the wait.
LIST_TOGGLE_ATTEMPTS = 3
LIST_TOGGLE_QUICK_FAILURE_SECONDS = 1.0


def _toggle_list_membership(custom_list, item, user):
    """Add or remove ``item`` and record the activity in one transaction."""
    with transaction.atomic():
        CustomListItem.objects.lock_custom_lists([custom_list.id])
        custom_list_item = CustomListItem.objects.filter(
            custom_list=custom_list,
            item=item,
        ).first()
        if custom_list_item is not None:
            # Instance-level delete renumbers the per-list sequence.
            custom_list_item.delete()
            has_item = False
            activity_type = ListActivityType.ITEM_REMOVED
        else:
            CustomListItem.objects.create(
                custom_list=custom_list,
                item=item,
                added_by=user,
            )
            has_item = True
            activity_type = ListActivityType.ITEM_ADDED

        ListActivity.objects.create(
            custom_list=custom_list,
            user=user,
            activity_type=activity_type,
            item=item,
        )
    return has_item


@require_POST
def list_item_toggle(request):
    """Add or remove an item from a custom list."""
    item_id = request.POST["item_id"]
    custom_list_id = request.POST["custom_list_id"]

    item = get_object_or_404(Item, id=item_id)
    discover_tab_cache.mark_active_from_request(
        request,
        fallback_media_type=item.media_type,
    )
    custom_list = get_object_or_404(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            id=custom_list_id,
        ).distinct(),  # To prevent duplicates, when user is owner and collaborator
    )

    if custom_list.is_smart:
        return HttpResponse(status=403)

    started = time.monotonic()
    attempt = 0
    try:
        while True:
            attempt += 1
            attempt_started = time.monotonic()
            try:
                has_item = _toggle_list_membership(custom_list, item, request.user)
                break
            except OperationalError as error:
                quick = (
                    time.monotonic() - attempt_started
                    < LIST_TOGGLE_QUICK_FAILURE_SECONDS
                )
                if not (is_lock_error(error) and quick) or (
                    attempt >= LIST_TOGGLE_ATTEMPTS
                ):
                    raise
                time.sleep(0.1 * attempt)
        logger.info(
            "%s %s %s.",
            item,
            "added to" if has_item else "removed from",
            custom_list,
        )
    except Exception as error:
        # Keep the last committed button state and surface every failed toggle.
        # The structured context contains database IDs only. SQLite cannot say
        # which connection held a lock, so a contention failure records how long
        # this request waited and how many attempts it made instead.
        contention = is_contention_error(error)
        logger.exception(
            "Failed to toggle list membership (item_id=%s, custom_list_id=%s, "
            "user_id=%s, contention=%s, attempts=%s, elapsed_ms=%s, pid=%s)",
            item.id,
            custom_list.id,
            request.user.id,
            contention,
            attempt,
            int((time.monotonic() - started) * 1000),
            os.getpid(),
        )
        return _list_item_toggle_error_response(busy=contention)

    return render(
        request,
        "lists/components/list_item_button.html",
        {"custom_list": custom_list, "item": item, "has_item": has_item},
    )


@login_required
@require_POST
def bulk_list_add(request):
    """Add several items to one editable manual list."""
    from app.bulk_actions import posted_item_ids

    item_ids = posted_item_ids(request.POST)
    if not item_ids:
        return JsonResponse(
            {"success": False, "error": "At least one item is required."},
            status=400,
        )

    custom_list = get_object_or_404(
        CustomList.objects.filter(
            Q(owner=request.user) | Q(collaborators=request.user),
            id=request.POST.get("custom_list_id"),
        ).distinct(),
    )
    if custom_list.is_smart:
        return JsonResponse(
            {"success": False, "error": "Smart lists cannot be edited directly."},
            status=403,
        )

    items_by_id = Item.objects.in_bulk(item_ids)
    skipped = len(item_ids) - len(items_by_id)
    added_items = []
    with transaction.atomic():
        CustomListItem.objects.lock_custom_lists([custom_list.id])
        existing_ids = set(
            CustomListItem.objects.filter(
                custom_list=custom_list,
                item_id__in=items_by_id,
            ).values_list("item_id", flat=True),
        )
        added_items = [
            item
            for item_id, item in items_by_id.items()
            if item_id not in existing_ids
        ]
        CustomListItem.objects.bulk_create(
            [
                CustomListItem(
                    custom_list=custom_list,
                    item=item,
                    added_by=request.user,
                )
                for item in added_items
            ],
        )
        ListActivity.objects.bulk_create(
            [
                ListActivity(
                    custom_list=custom_list,
                    user=request.user,
                    activity_type=ListActivityType.ITEM_ADDED,
                    item=item,
                )
                for item in added_items
            ],
        )

    already_present = len(items_by_id) - len(added_items)
    return JsonResponse(
        {
            "success": True,
            "added": len(added_items),
            "already_present": already_present,
            "skipped": skipped,
            "message": (
                f"Added {len(added_items)} item(s) to {custom_list.name}."
                + (f" {already_present} already present." if already_present else "")
                + (f" {skipped} skipped." if skipped else "")
            ),
        },
    )


# An item the provider has no release date for is asked about on every page
# that shows it, one provider call each. Remember the miss for a day; a
# provider error is remembered briefly so an outage is not retried per view.
RELEASE_YEAR_MISS_SECONDS = 60 * 60 * 24
RELEASE_YEAR_ERROR_SECONDS = 60 * 10


@require_GET
@login_not_required
def fetch_release_year(request):
    """Fetch release year for a single item asynchronously."""
    item_id = request.GET.get("item_id")
    if not item_id:
        return JsonResponse({"error": "item_id required"}, status=400)

    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found"}, status=404)

    if item.release_datetime:
        return JsonResponse({"year": item.release_datetime.year})

    if item.media_type == MediaTypes.SEASON.value and item.season_number:
        episode_release = (
            Item.objects.filter(
                media_id=item.media_id,
                source=item.source,
                media_type=MediaTypes.EPISODE.value,
                season_number=item.season_number,
                release_datetime__isnull=False,
            )
            .order_by("release_datetime")
            .values_list("release_datetime", flat=True)
            .first()
        )
        if episode_release:
            item.release_datetime = episode_release
            item.save(update_fields=["release_datetime"])
            return JsonResponse({"year": episode_release.year})

    miss_key = f"release_year_miss_{item.id}"
    if cache.get(miss_key):
        return JsonResponse({"year": None})

    try:
        season_numbers = None
        episode_number = None
        if item.media_type == MediaTypes.SEASON.value and item.season_number:
            season_numbers = [item.season_number]
        elif (
            item.media_type == MediaTypes.EPISODE.value
            and item.season_number is not None
            and item.episode_number is not None
        ):
            season_numbers = [item.season_number]
            episode_number = item.episode_number

        with services.interactive_request_scope():
            metadata = services.get_media_metadata(
                item.media_type,
                item.media_id,
                item.source,
                season_numbers=season_numbers,
                episode_number=episode_number,
            )
        if metadata:
            release_datetime = helpers.extract_release_datetime(metadata)
            if release_datetime:
                item.release_datetime = release_datetime
                item.save(update_fields=["release_datetime"])
                return JsonResponse({"year": release_datetime.year})
    except Exception as exc:
        logger.warning(
            "Failed to fetch release year for item %s: %s",
            item_id,
            exc,
        )
        cache.set(miss_key, True, RELEASE_YEAR_ERROR_SECONDS)
        return JsonResponse({"year": None})

    cache.set(miss_key, True, RELEASE_YEAR_MISS_SECONDS)
    return JsonResponse({"year": None})
