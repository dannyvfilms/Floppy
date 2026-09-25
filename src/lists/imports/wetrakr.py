import logging

from django.db import transaction

from integrations.imports import helpers
from lists.imports.trakt import _build_item_from_entry
from lists.models import CustomList, CustomListItem

logger = logging.getLogger(__name__)


def import_wetrakr_lists(user, wetrakr_lists):
    """Rebuild a user's WeTrakr lists from ``[(name, description, entries)]``.

    Entries are Trakt-shaped (see ``integrations.imports.wetrakr``), so items
    resolve through the Trakt list importer. Lists from an earlier WeTrakr
    import are replaced, the same way Trakt lists are.

    Returns ``(lists_created, items_skipped)``.
    """
    skipped_items = 0

    with transaction.atomic():
        helpers.retry_on_lock(
            lambda: CustomList.objects.filter(owner=user, source="wetrakr").delete(),
        )

        for name, description, entries in wetrakr_lists:
            custom_list = CustomList.objects.create(
                name=name,
                description=description,
                owner=user,
                visibility="private",
                allow_recommendations=False,
                source="wetrakr",
                source_id=name[:100],
            )
            for entry in entries:
                item = _build_item_from_entry(entry)
                if not item:
                    skipped_items += 1
                    continue
                CustomListItem.objects.get_or_create(
                    custom_list=custom_list,
                    item=item,
                    defaults={"added_by": user},
                )

    logger.info(
        "Imported %s WeTrakr lists for %s (%s items not found in TMDB)",
        len(wetrakr_lists),
        user.username,
        skipped_items,
    )
    return len(wetrakr_lists), skipped_items
