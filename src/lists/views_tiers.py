"""Endpoints behind the Tiers view: move an item, edit the tiers, export the board."""

import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from lists.models import CustomList, CustomListItem
from lists.tiers import (
    TIER_BOARD_LIMIT,
    clean_tiers,
    resolve_tiers,
    tier_index_for_score,
)
from lists.views_add_reorder import apply_full_order


def _editable_list(request, list_id):
    """Return the list, or None when the user may not change its tiers."""
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.is_smart or not custom_list.user_can_edit(request.user):
        return None
    return custom_list


@login_required
@require_POST
def move_tier_item(request, list_id):
    """Put one item in a tier and keep the tier's order as dropped.

    ``item_ids[]`` is the target tier's items in their new order; it sets the
    item's place among them with the same ordering the custom sort uses.
    """
    custom_list = _editable_list(request, list_id)
    if custom_list is None:
        return HttpResponse(status=403)

    tier = request.POST.get("tier", "")
    if tier and tier not in {entry["id"] for entry in resolve_tiers(custom_list)}:
        return HttpResponse(status=400)

    with transaction.atomic():
        moved = CustomListItem.objects.filter(
            custom_list=custom_list,
            item_id=request.POST.get("item_id") or 0,
        ).update(tier=tier)
        if not moved:
            return HttpResponse(status=404)
        item_ids = request.POST.getlist("item_ids[]")
        if item_ids:
            apply_full_order(custom_list, item_ids)
    return HttpResponse(status=204)


@login_required
@require_POST
def save_tiers(request, list_id):
    """Replace the list's tiers; items in a removed tier become Unranked."""
    custom_list = _editable_list(request, list_id)
    if custom_list is None:
        return HttpResponse(status=403)

    try:
        tiers = clean_tiers(json.loads(request.body or b"{}").get("tiers"))
    except (ValueError, AttributeError):
        return HttpResponse(status=400)

    with transaction.atomic():
        custom_list.tiers = tiers
        custom_list.save(update_fields=["tiers"])
        CustomListItem.objects.filter(custom_list=custom_list).exclude(
            tier__in=[entry["id"] for entry in tiers],
        ).update(tier="")
    return JsonResponse({"tiers": tiers})


def _tier_orders(custom_list, tier_ids):
    """Return each tier's item ids in list order, for tiers the client re-sorts."""
    orders = {tier_id: [] for tier_id in tier_ids}
    for item_id, tier in (
        CustomListItem.objects.filter(custom_list=custom_list, tier__in=tier_ids)
        .order_by("date_added", "id")
        .values_list("item_id", "tier")
    ):
        orders[tier].append(item_id)
    return orders


@login_required
@require_POST
def fill_from_ratings(request, list_id):
    """Place unranked items by the requester's rating; rated ones only.

    The 0-10 rating range is split evenly across the tiers. Items already in a
    tier are left alone, so this only ever fills the Unranked pool.
    """
    custom_list = _editable_list(request, list_id)
    if custom_list is None:
        return HttpResponse(status=403)
    if not request.user.ratings_enabled:
        return HttpResponse(status=400)

    from app.models import Item
    from lists.views_helpers import _attach_media_with_aggregation

    tier_ids = [entry["id"] for entry in resolve_tiers(custom_list)]
    unranked = list(
        CustomListItem.objects.filter(custom_list=custom_list)
        .exclude(tier__in=tier_ids)
        .order_by("date_added", "id")
        .values_list("item_id", flat=True)[:TIER_BOARD_LIMIT],
    )
    items = list(Item.objects.filter(id__in=unranked))
    _attach_media_with_aggregation(items, request.user)

    placements = []
    for item in items:
        score = getattr(item.media, "score", None)
        if score is not None:
            index = tier_index_for_score(score, len(tier_ids))
            placements.append({"item_id": item.id, "tier": tier_ids[index]})

    with transaction.atomic():
        for tier_id in tier_ids:
            ids = [p["item_id"] for p in placements if p["tier"] == tier_id]
            if ids:
                CustomListItem.objects.filter(
                    custom_list=custom_list,
                    item_id__in=ids,
                ).update(tier=tier_id)
    touched = sorted({p["tier"] for p in placements})
    return JsonResponse(
        {"placements": placements, "order": _tier_orders(custom_list, touched)},
    )


@login_required
@require_POST
def undo_fill(request, list_id):
    """Put the items from a fill back in Unranked, unless they have since moved."""
    custom_list = _editable_list(request, list_id)
    if custom_list is None:
        return HttpResponse(status=403)
    try:
        placements = json.loads(request.body or b"{}")["placements"]
        pairs = [(int(entry["item_id"]), str(entry["tier"])) for entry in placements]
    except (ValueError, KeyError, TypeError):
        return HttpResponse(status=400)

    with transaction.atomic():
        for item_id, tier in pairs:
            CustomListItem.objects.filter(
                custom_list=custom_list,
                item_id=item_id,
                tier=tier,
            ).update(tier="")
    return JsonResponse({"order": _tier_orders(custom_list, [""])})


@require_GET
def export_tiers(request, list_id):
    """Download the tier board as a PNG; anyone who can view the list can."""
    custom_list = get_object_or_404(CustomList, id=list_id)
    if custom_list.is_smart or not custom_list.user_can_view(request.user):
        raise Http404
    # Imported here so serving other requests does not load Pillow.
    from lists.tier_export import render_board

    response = HttpResponse(render_board(custom_list), content_type="image/png")
    filename = f"{slugify(custom_list.name) or 'list'}-tiers.png"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response
