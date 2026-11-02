import logging
from http import HTTPStatus

from django.conf import settings
from django.db import transaction

from app.models import Item, MediaTypes, Sources
from app.providers import credentials, services
from integrations.imports import helpers
from lists.models import CustomList, CustomListItem

logger = logging.getLogger(__name__)

TRAKT_API_BASE_URL = "https://api.trakt.tv"
BULK_PAGE_SIZE = 1000


def import_trakt_lists(user, access_token, client_id=None):
    """Import and rebuild Trakt lists for a user."""
    trakt_lists = _get_trakt_lists(access_token, client_id=client_id)
    imported_count = 0
    skipped_lists = 0
    skipped_items = 0

    # Fetch everything from Trakt, and resolve each entry against TMDB, before
    # the rebuild transaction opens. The delete below takes SQLite's write
    # lock, and holding it across paginated HTTP calls and a TMDB lookup per
    # entry blocked every other writer, page views included, meanwhile.
    fetched_lists = []
    for trakt_list in trakt_lists:
        list_id = trakt_list.get("ids", {}).get("trakt")
        if not list_id:
            skipped_lists += 1
            continue
        list_items = _get_trakt_list_items(
            access_token,
            list_id,
            client_id=client_id,
        )
        list_resolved, list_skipped = _resolve_entries(list_items)
        skipped_items += list_skipped
        fetched_lists.append((trakt_list, list_id, list_resolved))

    try:
        logger.info("Fetching Watchlist for user %s", user.username)
        watchlist_items = _get_trakt_watchlist_items(
            access_token,
            client_id=client_id,
        )
        logger.info(
            "Fetched %s items from Watchlist for user %s",
            len(watchlist_items) if watchlist_items else 0,
            user.username,
        )
        watchlist_fetched = True
    except Exception as e:
        logger.warning(
            "Failed to import Watchlist for %s: %s",
            user.username,
            e,
            exc_info=True,
        )
        watchlist_items = []
        watchlist_fetched = False
        skipped_lists += 1
    # Outside the try: a TMDB failure while resolving entries aborts the
    # import before anything is deleted, rather than dropping the Watchlist.
    watchlist_resolved, watchlist_skipped = _resolve_entries(watchlist_items or [])
    skipped_items += watchlist_skipped

    previous_lists = CustomList.objects.filter(owner=user, source="trakt")
    if not watchlist_fetched:
        # Keep the Watchlist already imported when Trakt would not return it.
        previous_lists = previous_lists.exclude(source_id="watchlist")

    with transaction.atomic():
        helpers.retry_on_lock(previous_lists.delete)

        for trakt_list, list_id, list_resolved in fetched_lists:
            custom_list = _create_custom_list(user, trakt_list, list_id)
            imported_count += 1
            for item in list_resolved:
                CustomListItem.objects.get_or_create(
                    custom_list=custom_list,
                    item=item,
                    defaults={"added_by": user},
                )

        # Import Watchlist as a special list
        if watchlist_fetched:
            watchlist_list = CustomList.objects.create(
                name="Watchlist",
                description="",
                owner=user,
                visibility="private",
                allow_recommendations=False,
                source="trakt",
                source_id="watchlist",
            )
            imported_count += 1
            for item in watchlist_resolved:
                CustomListItem.objects.get_or_create(
                    custom_list=watchlist_list,
                    item=item,
                    defaults={"added_by": user},
                )
            logger.info(
                "Successfully imported Watchlist for user %s (%s items)",
                user.username,
                watchlist_list.items.count(),
            )

    logger.info(
        "Imported %s Trakt lists for %s (%s lists skipped, %s items skipped)",
        imported_count,
        user.username,
        skipped_lists,
        skipped_items,
    )


def import_trakt_lists_from_export(user, archive):
    """Rebuild Trakt lists from a Trakt export archive instead of the API.

    Mirrors ``import_trakt_lists``: existing ``source="trakt"`` lists are
    dropped and recreated, with the watchlist stored as a synthetic list.
    Only the data source differs — ``lists-lists.json`` for list metadata,
    ``lists-list-<id>-*.json`` for their items, ``lists-watchlist-*.json``
    for the watchlist.

    Returns ``(lists_created, warnings)``.
    """
    trakt_lists = archive.read_json("lists-lists", default=[]) or []
    items_by_list_id = archive.list_item_files()
    imported_count = 0
    skipped_items = 0
    warnings = []

    # Resolve entries against TMDB before the rebuild transaction takes the
    # write lock (see import_trakt_lists).
    resolved_lists = []
    for trakt_list in trakt_lists:
        list_id = trakt_list.get("ids", {}).get("trakt")
        if not list_id:
            continue
        entries = [
            entry
            for base_name in items_by_list_id.get(str(list_id), [])
            for entry in archive.read_json(base_name, default=[]) or []
        ]
        list_resolved, list_skipped = _resolve_entries(entries)
        skipped_items += list_skipped
        resolved_lists.append((trakt_list, list_id, list_resolved))
    watchlist_resolved, watchlist_skipped = _resolve_entries(
        archive.load("lists-watchlist")
    )
    skipped_items += watchlist_skipped

    with transaction.atomic():
        helpers.retry_on_lock(
            lambda: CustomList.objects.filter(owner=user, source="trakt").delete(),
        )

        for trakt_list, list_id, list_resolved in resolved_lists:
            custom_list = _create_custom_list(user, trakt_list, list_id)
            imported_count += 1
            for item in list_resolved:
                CustomListItem.objects.get_or_create(
                    custom_list=custom_list,
                    item=item,
                    defaults={"added_by": user},
                )

        watchlist_list = CustomList.objects.create(
            name="Watchlist",
            description="",
            owner=user,
            visibility="private",
            allow_recommendations=False,
            source="trakt",
            source_id="watchlist",
        )
        imported_count += 1
        for item in watchlist_resolved:
            CustomListItem.objects.get_or_create(
                custom_list=watchlist_list,
                item=item,
                defaults={"added_by": user},
            )

    if skipped_items:
        warnings.append(
            f"Skipped {skipped_items} list item(s) that could not be matched in TMDB.",
        )

    logger.info(
        "Imported %s Trakt lists from export for %s (%s items skipped)",
        imported_count,
        user.username,
        skipped_items,
    )
    return imported_count, warnings


def _get_trakt_lists(access_token, client_id=None):
    """Fetch Trakt lists for the authenticated user."""
    return _make_paginated_trakt_request(
        access_token,
        f"{TRAKT_API_BASE_URL}/users/me/lists",
        client_id=client_id,
        item_type="lists",
    )


def _get_trakt_list_items(access_token, list_id, client_id=None):
    """Fetch items for a Trakt list."""
    url = f"{TRAKT_API_BASE_URL}/users/me/lists/{list_id}/items"
    return _make_paginated_trakt_request(
        access_token,
        url,
        client_id=client_id,
        item_type="list items",
    )


def _get_trakt_watchlist_items(access_token, client_id=None):
    """Fetch items from the Trakt watchlist."""
    url = f"{TRAKT_API_BASE_URL}/users/me/watchlist"
    return _make_paginated_trakt_request(
        access_token,
        url,
        client_id=client_id,
        item_type="watchlist items",
    )


def _make_paginated_trakt_request(access_token, url, client_id=None, item_type="items"):
    """Fetch all pages from a Trakt endpoint."""
    page = 1
    all_entries = []

    while True:
        page_url = _build_paginated_url(url, page)
        page_entries = _make_trakt_request(access_token, page_url, client_id=client_id)
        if not page_entries:
            break

        all_entries.extend(page_entries)
        logger.info(
            "Fetched Trakt %s page %s (%s items)",
            item_type,
            page,
            len(page_entries),
        )
        page += 1

    return all_entries


def _build_paginated_url(url, page):
    """Append Trakt pagination parameters to a URL."""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}page={page}&limit={BULK_PAGE_SIZE}"


def _make_trakt_request(access_token, url, client_id=None):
    """Make an authenticated Trakt API request."""
    if not client_id:
        client_id = credentials.get("trakt", "client_id")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Floppy/{settings.VERSION}",
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Authorization": f"Bearer {access_token}",
    }
    try:
        return services.api_request("TRAKT", "GET", url, headers=headers)
    except services.ProviderAPIError as error:
        if error.status_code == HTTPStatus.UNAUTHORIZED:
            msg = "Trakt authorization expired. Please connect again."
            raise helpers.MediaImportError(msg) from error
        raise


def _create_custom_list(user, trakt_list, list_id):
    """Create a CustomList from a Trakt list payload."""
    privacy = trakt_list.get("privacy", "private")
    visibility = "public" if privacy == "public" else "private"
    return CustomList.objects.create(
        name=trakt_list.get("name", "Trakt List"),
        description=trakt_list.get("description") or "",
        owner=user,
        visibility=visibility,
        allow_recommendations=False,
        source="trakt",
        source_id=str(list_id),
    )


def _resolve_entries(entries):
    """Return the Items for Trakt entries and how many could not be matched."""
    items = []
    skipped = 0
    for entry in entries or []:
        item = _build_item_from_entry(entry)
        if item is None:
            skipped += 1
        else:
            items.append(item)
    return items, skipped


def _build_item_from_entry(entry):
    """Create or fetch an Item from a Trakt list entry."""
    entry_type = entry.get("type")
    season_number = None
    episode_number = None

    if entry_type == "movie":
        payload = entry.get("movie", {})
        media_type = MediaTypes.MOVIE.value
    elif entry_type == "show":
        payload = entry.get("show", {})
        media_type = MediaTypes.TV.value
    elif entry_type == "season":
        payload = entry.get("show", {})
        media_type = MediaTypes.SEASON.value
        season_number = entry.get("season", {}).get("number")
        if season_number is None:
            return None
    elif entry_type == "episode":
        payload = entry.get("show", {})
        media_type = MediaTypes.EPISODE.value
        season_number = entry.get("episode", {}).get("season")
        episode_number = entry.get("episode", {}).get("number")
        if season_number is None or episode_number is None:
            return None
    else:
        return None

    tmdb_id = payload.get("ids", {}).get("tmdb")
    title = payload.get("title") or str(tmdb_id or "")

    if not tmdb_id:
        return None

    metadata = _get_metadata(
        media_type,
        str(tmdb_id),
        title,
        season_number=season_number,
        episode_number=episode_number,
    )
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
        season_number=season_number,
        episode_number=episode_number,
        defaults=defaults,
    )
    return item


def _get_metadata(media_type, tmdb_id, title, season_number=None, episode_number=None):
    """Fetch TMDB metadata for a Trakt entry."""
    metadata_kwargs = {}
    if season_number is not None:
        metadata_kwargs["season_numbers"] = [season_number]
    if episode_number is not None:
        metadata_kwargs["episode_number"] = episode_number

    try:
        return services.get_media_metadata(
            media_type,
            tmdb_id,
            Sources.TMDB.value,
            **metadata_kwargs,
        )
    except services.ProviderAPIError as error:
        if error.status_code == HTTPStatus.NOT_FOUND:
            logger.warning(
                "Trakt list item %s missing in TMDB (%s)",
                title,
                tmdb_id,
            )
            return None
        raise
