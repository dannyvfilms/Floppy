"""MDBList list import and recurring sync.

Fetches the user's own MDBList lists (plus any public lists imported by
URL/ID) and mirrors them as CustomLists. Unlike the Trakt import, syncs are
stable upserts keyed on (owner, source, source_id) so list PKs, slugs and
visibility survive recurring refreshes.
"""

import logging
import re
from http import HTTPStatus

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import services
from integrations.imports import helpers

# Shared MDBList client helpers live with the full-account importer; keep the
# old private names so existing call sites and test patch targets still work.
from integrations.imports.mdblist import (
    PAGE_SIZE,
    validate_api_key,  # noqa: F401  (re-exported for views_mdblist)
)
from integrations.imports.mdblist import (
    normalize_items_response as _normalize_items_response,
)
from integrations.imports.mdblist import request as _request
from integrations.imports.mdblist import resolve_tmdb_id as _resolve_tmdb_id
from lists.models import CustomList, CustomListItem

logger = logging.getLogger(__name__)

LIST_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?mdblist\.com/lists/([^/\s]+)/([^/\s?#]+)",
)

MEDIATYPE_MAP = {
    "movie": MediaTypes.MOVIE.value,
    "show": MediaTypes.TV.value,
}


def get_list_info(api_key, list_id):
    """Fetch metadata for a single MDBList list."""
    response = _request(api_key, f"/lists/{list_id}")
    return _first_list_payload(response)


def resolve_list_reference(api_key, reference):
    """Resolve a list ID, URL, or username/slug into list info."""
    reference = reference.strip()
    if not reference:
        msg = "Provide an MDBList list URL or ID."
        raise helpers.MediaImportError(msg)

    if reference.isdigit():
        response = _request(api_key, f"/lists/{reference}")
    else:
        match = LIST_URL_PATTERN.search(reference)
        if match:
            username, slug = match.groups()
        elif reference.count("/") == 1:
            username, slug = reference.split("/")
        else:
            msg = (
                "Could not parse the MDBList list reference. Use a list ID, "
                "an mdblist.com/lists/... URL, or username/list-slug."
            )
            raise helpers.MediaImportError(msg)
        response = _request(api_key, f"/lists/{username}/{slug}")

    list_info = _first_list_payload(response)
    if not list_info:
        msg = "MDBList list not found. It may be private or deleted."
        raise helpers.MediaImportError(msg)
    return list_info


def _first_list_payload(response):
    """Normalize a list-info response (array or single object) to one dict."""
    if isinstance(response, list):
        return response[0] if response else None
    if isinstance(response, dict) and response.get("error"):
        return None
    return response or None


def _get_list_items(api_key, list_id):
    """Fetch all items of a list, paginated."""
    offset = 0
    all_entries = []
    while True:
        response = _request(
            api_key,
            f"/lists/{list_id}/items",
            params={"limit": PAGE_SIZE, "offset": offset, "unified": "true"},
        )
        entries = _normalize_items_response(response)
        all_entries.extend(entries)
        if len(entries) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_entries


def _build_item_from_entry(entry):
    """Create or fetch an Item from an MDBList list entry."""
    media_type = MEDIATYPE_MAP.get(entry.get("mediatype"))
    if not media_type:
        return None

    tmdb_id = _resolve_tmdb_id(entry, media_type)
    if not tmdb_id:
        return None
    title = entry.get("title") or str(tmdb_id)

    metadata = _get_metadata(media_type, str(tmdb_id), title)
    if not metadata:
        return None

    defaults = {
        **Item.title_fields_from_metadata(metadata, fallback_title=title),
        "image": metadata.get("image") or settings.IMG_NONE,
    }

    item, _ = Item.objects.get_or_create(
        media_id=str(tmdb_id),
        source=Sources.TMDB.value,
        media_type=media_type,
        season_number=None,
        episode_number=None,
        defaults=defaults,
    )
    return item


def _get_metadata(media_type, tmdb_id, title):
    """Fetch TMDB metadata for an MDBList entry."""
    try:
        return services.get_media_metadata(
            media_type,
            tmdb_id,
            Sources.TMDB.value,
        )
    except services.ProviderAPIError as error:
        if error.status_code == HTTPStatus.NOT_FOUND:
            logger.warning(
                "MDBList item %s missing in TMDB (%s)",
                title,
                tmdb_id,
            )
            return None
        raise


def _sync_list(user, api_key, list_info):
    """Upsert a CustomList from MDBList list info and reconcile its items.

    Returns the number of entries skipped (unresolvable items).
    """
    list_id = str(list_info["id"])
    entries = _get_list_items(api_key, list_id)

    desired_item_ids = set()
    skipped_items = 0
    for entry in entries:
        item = _build_item_from_entry(entry)
        if not item:
            skipped_items += 1
            continue
        desired_item_ids.add(item.id)

    def _apply():
        with transaction.atomic():
            custom_list, _ = CustomList.objects.update_or_create(
                owner=user,
                source="mdblist",
                source_id=list_id,
                defaults={
                    "name": list_info.get("name") or "MDBList",
                    "description": list_info.get("description") or "",
                },
            )
            custom_list.customlistitem_set.exclude(
                item_id__in=desired_item_ids,
            ).delete()
            existing_item_ids = set(
                custom_list.customlistitem_set.values_list("item_id", flat=True),
            )
            CustomListItem.objects.bulk_create(
                CustomListItem(
                    custom_list=custom_list,
                    item_id=item_id,
                    added_by=user,
                )
                for item_id in desired_item_ids - existing_item_ids
            )

    helpers.retry_on_lock(_apply)
    logger.info(
        "Synced MDBList list %s (%s) for %s: %s items, %s skipped",
        list_id,
        list_info.get("name"),
        user.username,
        len(desired_item_ids),
        skipped_items,
    )
    return skipped_items


def import_mdblist_lists(user):
    """Sync all of a user's MDBList lists (own + previously imported)."""
    account = getattr(user, "mdblist_account", None)
    if not account:
        logger.info("No MDBList account for user %s, skipping sync", user.username)
        return

    try:
        api_key = helpers.decrypt_or_raise(account.api_key)
        own_lists = _request(api_key, "/lists/user")
        if not isinstance(own_lists, list):
            own_lists = []

        synced_ids = set()
        skipped_lists = 0
        skipped_items = 0
        for list_info in own_lists:
            list_id = list_info.get("id")
            if not list_id:
                skipped_lists += 1
                continue
            skipped_items += _sync_list(user, api_key, list_info)
            synced_ids.add(str(list_id))

        # Lists imported by URL/ID that aren't in the user's own lists
        extra_ids = (
            CustomList.objects.filter(owner=user, source="mdblist")
            .exclude(source_id__in=synced_ids)
            .values_list("source_id", flat=True)
        )
        for list_id in extra_ids:
            list_info = get_list_info(api_key, list_id)
            if not list_info:
                logger.warning(
                    "MDBList list %s for %s is gone upstream, keeping local copy",
                    list_id,
                    user.username,
                )
                skipped_lists += 1
                continue
            skipped_items += _sync_list(user, api_key, list_info)
    except helpers.MediaImportError as error:
        account.connection_broken = True
        account.last_error_message = str(error)
        account.save(update_fields=["connection_broken", "last_error_message"])
        raise

    account.connection_broken = False
    account.last_error_message = ""
    account.last_sync_at = timezone.now()
    account.save(
        update_fields=["connection_broken", "last_error_message", "last_sync_at"],
    )
    logger.info(
        "Synced %s MDBList lists for %s (%s lists skipped, %s items skipped)",
        len(synced_ids) + len(extra_ids) - skipped_lists,
        user.username,
        skipped_lists,
        skipped_items,
    )


def import_mdblist_list_by_reference(user, reference):
    """Import a single MDBList list by URL or ID."""
    account = getattr(user, "mdblist_account", None)
    if not account:
        msg = "Connect your MDBList account before importing lists."
        raise helpers.MediaImportError(msg)

    try:
        api_key = helpers.decrypt_or_raise(account.api_key)
    except helpers.MediaImportError as error:
        account.connection_broken = True
        account.last_error_message = str(error)
        account.save(update_fields=["connection_broken", "last_error_message"])
        raise

    list_info = resolve_list_reference(api_key, reference)
    _sync_list(user, api_key, list_info)
    return list_info
