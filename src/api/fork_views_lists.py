# FORK: advanced list endpoints — smart rules, collaborators, reorder,
# recommendations, and activity — mirroring the fork's web list views.
# URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import Item, MediaTypes
from app.services import metadata_resolution
from lists import smart_rules
from lists.models import (
    CustomList,
    CustomListItem,
    ListActivity,
    ListActivityType,
    ListRecommendation,
)
from lists.tiers import clean_tiers, resolve_tiers
from lists.views_add_reorder import apply_full_order, apply_reorder_action
from lists.views_helpers import list_has_item_identity
from lists.views_recommendations import get_or_create_recommendation_item
from lists.views_tiers import apply_fill, apply_undo

from .contract_serializers import (
    DetailErrorSerializer,
    ListItemsOrderRequestSerializer,
    ListItemsRanksRequestSerializer,
    ListItemsReorderRequestSerializer,
)

logger = logging.getLogger(__name__)

MAX_BULK_LIST_ITEM_IDS = 500


_OBJ_READ = extend_schema(responses={200: OpenApiTypes.OBJECT})
_OBJ_WRITE = extend_schema(
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT, 204: None},
)
_OBJ_DELETE = extend_schema(responses={204: None})

def _get_editable_list(request, list_id):
    """Return (custom_list, error_response) enforcing edit permission."""
    custom_list = (
        CustomList.objects.select_related("owner")
        .prefetch_related("collaborators")
        .filter(id=list_id)
        .first()
    )
    if custom_list is None or not custom_list.user_can_view(request.user):
        return None, Response({"detail": "List not found."}, status=HTTP.NOT_FOUND)
    if not custom_list.user_can_edit(request.user):
        return None, Response(
            {"detail": "You do not have permission to edit this list."},
            status=HTTP.FORBIDDEN,
        )
    return custom_list, None


def _get_tier_list(request, list_id, *, write):
    """Return (custom_list, error_response) for the Tiers view of a list."""
    custom_list = CustomList.objects.select_related("owner").filter(id=list_id).first()
    if custom_list is None or not custom_list.user_can_view(request.user):
        return None, Response({"detail": "List not found."}, status=HTTP.NOT_FOUND)
    if write and not custom_list.user_can_edit(request.user):
        return None, Response(
            {"detail": "You do not have permission to edit this list."},
            status=HTTP.FORBIDDEN,
        )
    if write and custom_list.is_smart:
        return None, Response(
            {"detail": "Smart lists do not have editable tiers."},
            status=HTTP.BAD_REQUEST,
        )
    return custom_list, None


def _serialize_tiers(custom_list):
    placements = [
        {"item_id": item_id, "tier": tier}
        for item_id, tier in CustomListItem.objects.filter(custom_list=custom_list)
        .order_by("date_added", "id")
        .values_list("item_id", "tier")
    ]
    return {"tiers": resolve_tiers(custom_list), "placements": placements}


# /api/v1/lists/[list_id]/tiers/
class ListTiersView(drf_views.APIView):
    """Read or replace a list's tier definitions and item placements."""

    @_OBJ_READ
    def get(self, request, list_id):
        """Return the tiers and the tier each item sits in ("" is Unranked)."""
        custom_list, error = _get_tier_list(request, list_id, write=False)
        if error:
            return error
        return Response(_serialize_tiers(custom_list), status=HTTP.OK)

    @_OBJ_WRITE
    def put(self, request, list_id):
        """Replace the tiers; items in a removed tier become Unranked."""
        custom_list, error = _get_tier_list(request, list_id, write=True)
        if error:
            return error
        try:
            tiers = clean_tiers(request.data.get("tiers"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=HTTP.BAD_REQUEST)
        with transaction.atomic():
            custom_list.tiers = tiers
            custom_list.save(update_fields=["tiers"])
            CustomListItem.objects.filter(custom_list=custom_list).exclude(
                tier__in=[entry["id"] for entry in tiers],
            ).update(tier="")
        return Response(_serialize_tiers(custom_list), status=HTTP.OK)


# /api/v1/lists/[list_id]/tiers/move/
class ListTierMoveView(drf_views.APIView):
    """Put one item in a tier and keep the tier's order as dropped."""

    @_OBJ_WRITE
    def post(self, request, list_id):
        """Move `item_id` to `tier` ("" is Unranked); `item_ids` sets its order."""
        custom_list, error = _get_tier_list(request, list_id, write=True)
        if error:
            return error
        tier = str(request.data.get("tier") or "")
        if tier and tier not in {entry["id"] for entry in resolve_tiers(custom_list)}:
            return Response({"detail": "Unknown tier."}, status=HTTP.BAD_REQUEST)
        item_ids = request.data.get("item_ids") or []
        if not isinstance(item_ids, list):
            return Response(
                {"detail": "'item_ids' must be a list."},
                status=HTTP.BAD_REQUEST,
            )
        with transaction.atomic():
            moved = CustomListItem.objects.filter(
                custom_list=custom_list,
                item_id=request.data.get("item_id") or 0,
            ).update(tier=tier)
            if not moved:
                return Response(
                    {"detail": "Item is not in this list."},
                    status=HTTP.NOT_FOUND,
                )
            if item_ids and apply_full_order(custom_list, item_ids) != HTTP.NO_CONTENT:
                # Rejected order (duplicate or foreign ids): undo the tier move.
                transaction.set_rollback(True)
                return Response(
                    {"detail": "'item_ids' must list this list's items once each."},
                    status=HTTP.BAD_REQUEST,
                )
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/lists/[list_id]/tiers/fill/
class ListTierFillView(drf_views.APIView):
    """Place unranked items by the requester's rating."""

    @_OBJ_WRITE
    def post(self, request, list_id):
        """Fill the Unranked pool from ratings; return placements and order."""
        custom_list, error = _get_tier_list(request, list_id, write=True)
        if error:
            return error
        if not request.user.ratings_enabled:
            return Response(
                {"detail": "Ratings are turned off for this account."},
                status=HTTP.BAD_REQUEST,
            )
        placements, order = apply_fill(custom_list, request.user)
        return Response({"placements": placements, "order": order}, status=HTTP.OK)


# /api/v1/lists/[list_id]/tiers/fill/undo/
class ListTierFillUndoView(drf_views.APIView):
    """Put the items from a fill back in Unranked."""

    @_OBJ_WRITE
    def post(self, request, list_id):
        """Undo `placements` unless the items have since moved."""
        custom_list, error = _get_tier_list(request, list_id, write=True)
        if error:
            return error
        try:
            pairs = [
                (int(entry["item_id"]), str(entry["tier"]))
                for entry in request.data["placements"]
            ]
        except (KeyError, TypeError, ValueError):
            return Response({"detail": "Invalid placements."}, status=HTTP.BAD_REQUEST)
        return Response({"order": apply_undo(custom_list, pairs)}, status=HTTP.OK)


def _serialize_smart_rules(custom_list):
    payload = {
        "is_smart": custom_list.is_smart,
        "smart_media_types": custom_list.smart_media_types,
        "smart_excluded_media_types": custom_list.smart_excluded_media_types,
        "smart_filters": custom_list.smart_filters,
        "items_count": custom_list.items.count(),
    }
    if custom_list.is_smart:
        # The normalized rules the editor works with (same as the web page).
        payload["rules"] = smart_rules.normalize_list_rules(custom_list)
    return payload


class ListItemsBulkAddView(drf_views.APIView):
    """Add a bounded set of library items to an editable manual list."""

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {
            "item_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": MAX_BULK_LIST_ITEM_IDS},
        }, "required": ["item_ids"]}},
        responses={"200": {"type": "object", "properties": {
            "added": {"type": "integer"}, "skipped": {"type": "integer"},
        }}},
    )
    def post(self, request, list_id):
        """Add owned-catalog item ids, skipping missing or existing entries."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        if custom_list.is_smart:
            return Response({"detail": "Smart lists cannot be edited directly."}, status=HTTP.BAD_REQUEST)
        item_ids = request.data.get("item_ids")
        if not isinstance(item_ids, list) or not item_ids:
            return Response({"detail": "'item_ids' must be a non-empty array."}, status=HTTP.BAD_REQUEST)
        if len(item_ids) > MAX_BULK_LIST_ITEM_IDS or any(not str(value).isdigit() for value in item_ids):
            return Response({"detail": "'item_ids' must contain at most 500 item ids."}, status=HTTP.BAD_REQUEST)
        with transaction.atomic():
            CustomListItem.objects.lock_custom_lists([custom_list.id])
            items = Item.objects.in_bulk({int(value) for value in item_ids})
            existing = set(CustomListItem.objects.filter(custom_list=custom_list, item_id__in=items).values_list("item_id", flat=True))
            new_items = [item for item_id, item in items.items() if item_id not in existing]
            created = CustomListItem.objects.bulk_create([
                CustomListItem(custom_list=custom_list, item=item, added_by=request.user)
                for item in new_items
            ])
            ListActivity.objects.bulk_create([
                ListActivity(
                    custom_list=custom_list,
                    user=request.user,
                    activity_type=ListActivityType.ITEM_ADDED,
                    item=item,
                )
                for item in new_items
            ])
        return Response({"added": len(created), "skipped": len(item_ids) - len(created)}, status=HTTP.OK)


# /api/v1/lists/[list_id]/smart-rules/
class ListSmartRulesView(drf_views.APIView):
    """Read or replace a smart list's rules (mirrors smart_rules_update)."""

    def get(self, request, list_id):
        """Return the list's smart configuration."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        return Response(_serialize_smart_rules(custom_list), status=HTTP.OK)

    def put(self, request, list_id):
        """Replace the smart rules and re-sync membership."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        if not custom_list.is_smart:
            return Response(
                {"detail": "This list is not a smart list."},
                status=HTTP.BAD_REQUEST,
            )

        normalized = smart_rules.normalize_rule_payload(
            request.data,
            custom_list.owner,
        )
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
        return Response(
            {**_serialize_smart_rules(custom_list), "rules": normalized},
            status=HTTP.OK,
        )


# /api/v1/lists/[list_id]/smart-rules/options/
class ListSmartRuleOptionsView(drf_views.APIView):
    """The choices the smart-rule editor offers for a list."""

    @_OBJ_READ
    def get(self, request, list_id):
        """Return genre, year, platform... options for the list's current rules."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        if not custom_list.is_smart:
            return Response(
                {"detail": "This list is not a smart list."},
                status=HTTP.BAD_REQUEST,
            )
        rules = smart_rules.normalize_list_rules(custom_list)
        options = smart_rules.build_rule_filter_data(
            owner=custom_list.owner,
            media_types=rules["media_types"],
            status=rules["status"],
            search=rules["search"],
            include_list_options=True,
        )
        available = smart_rules.get_available_media_types(custom_list.owner)
        return Response(
            {
                "options": options,
                "media_types": [
                    {"value": value, "label": MediaTypes(value).label}
                    for value in available
                ],
            },
            status=HTTP.OK,
        )


# /api/v1/lists/[list_id]/smart-sync/
class ListSmartSyncView(drf_views.APIView):
    """Re-sync a smart list's membership from its rules."""

    def post(self, request, list_id):
        """Run sync_smart_items and return the resulting count."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        if not custom_list.is_smart:
            return Response(
                {"detail": "This list is not a smart list."},
                status=HTTP.BAD_REQUEST,
            )
        custom_list.sync_smart_items()
        return Response(
            {"items_count": custom_list.items.count()},
            status=HTTP.OK,
        )


# /api/v1/lists/[list_id]/collaborators/
class ListCollaboratorsView(drf_views.APIView):
    """Read or replace a list's collaborators."""

    def get(self, request, list_id):
        """Return collaborator usernames."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        return Response(
            {
                "owner": custom_list.owner.username,
                "collaborators": [
                    user.username for user in custom_list.collaborators.all()
                ],
            },
            status=HTTP.OK,
        )

    def put(self, request, list_id):
        """Replace the collaborator set with the given usernames."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error

        usernames = request.data.get("usernames")
        if not isinstance(usernames, list):
            return Response(
                {"detail": "'usernames' must be a list."},
                status=HTTP.BAD_REQUEST,
            )

        users = list(
            get_user_model().objects.filter(username__in=usernames),
        )
        found = {user.username for user in users}
        missing = [name for name in usernames if name not in found]
        if missing:
            return Response(
                {"detail": "Unknown usernames.", "missing": missing},
                status=HTTP.NOT_FOUND,
            )
        users = [user for user in users if user != custom_list.owner]

        before = set(custom_list.collaborators.all())
        custom_list.collaborators.set(users)
        after = set(users)
        for _added in after - before:
            ListActivity.objects.create(
                custom_list=custom_list,
                user=request.user,
                activity_type=ListActivityType.COLLABORATOR_ADDED,
            )
        for _removed in before - after:
            ListActivity.objects.create(
                custom_list=custom_list,
                user=request.user,
                activity_type=ListActivityType.COLLABORATOR_REMOVED,
            )

        return Response(
            {"collaborators": [user.username for user in users]},
            status=HTTP.OK,
        )


# /api/v1/lists/[list_id]/viewers/
class ListViewersView(drf_views.APIView):
    """Read or replace the users a list is shared with (view only)."""

    @_OBJ_READ
    def get(self, request, list_id):
        """Return viewer usernames."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        return Response(
            {"viewers": [user.username for user in custom_list.viewers.all()]},
            status=HTTP.OK,
        )

    @_OBJ_WRITE
    def put(self, request, list_id):
        """Replace the viewer set with the given usernames."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        usernames = request.data.get("usernames")
        if not isinstance(usernames, list):
            return Response(
                {"detail": "'usernames' must be a list."},
                status=HTTP.BAD_REQUEST,
            )
        users = list(get_user_model().objects.filter(username__in=usernames))
        found = {user.username for user in users}
        missing = [name for name in usernames if name not in found]
        if missing:
            return Response(
                {"detail": "Unknown usernames.", "missing": missing},
                status=HTTP.NOT_FOUND,
            )
        users = [user for user in users if user != custom_list.owner]
        custom_list.viewers.set(users)
        return Response(
            {"viewers": [user.username for user in users]},
            status=HTTP.OK,
        )


_ORDER_ERRORS = {
    401: DetailErrorSerializer,
    403: DetailErrorSerializer,
    404: DetailErrorSerializer,
}


# /api/v1/lists/[list_id]/items/reorder/
class ListItemsReorderView(drf_views.APIView):
    """Move a single item within the list's custom order."""

    @extend_schema(
        request=ListItemsReorderRequestSerializer,
        responses={204: None, 400: DetailErrorSerializer, **_ORDER_ERRORS},
        description=(
            "Move one item of a list to the first or last position, or swap it "
            "with its neighbour. The `id` of each entry in "
            "GET /api/v1/lists/{list_id}/items/ is the `item_id` to send; that "
            "endpoint returns items in this order unless `sort` is given. "
            "Requires edit access to the list. Returns 204 with no body, also "
            "when the item is already in place or the list has fewer than two "
            "items; 400 for a missing or invalid `item_id` or `action`; 404 "
            "when the list is not found or the item is not in it. Reordering "
            "rewrites the date added of every item in the list, since that is "
            "where the custom order is stored."
        ),
    )
    def post(self, request, list_id):
        """Apply a first/back/next/last move (mirrors reorder_list_item)."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        serializer = ListItemsReorderRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid item_id/action.", "errors": serializer.errors},
                status=HTTP.BAD_REQUEST,
            )
        status = apply_reorder_action(
            custom_list,
            serializer.validated_data["item_id"],
            serializer.validated_data["action"],
        )
        if status == HTTP.NOT_FOUND:
            return Response(
                {"detail": "Item is not in this list."},
                status=status,
            )
        return Response(status=status)


# /api/v1/lists/[list_id]/items/order/
class ListItemsOrderView(drf_views.APIView):
    """Replace the list's custom order with an ordered item-id list."""

    @extend_schema(
        request=ListItemsOrderRequestSerializer,
        responses={204: None, 400: DetailErrorSerializer, **_ORDER_ERRORS},
        description=(
            "Set the order of a list's items. `item_ids` are Floppy's numeric "
            "Item ids, the `id` field of each entry in "
            "GET /api/v1/lists/{list_id}/items/, which returns items in this "
            "order unless `sort` is given. Send every item of the list, or "
            "only a subset: the listed items take the positions they already "
            "occupy, in the order given, and the others stay where they are. "
            "Items cannot be placed at a numeric rank; only relative order is "
            "stored. Each id must appear once and belong to this list. "
            "Requires edit access to the list. Returns 204 with no body. "
            "Returns 400 when `item_ids` is missing, empty or not a list of "
            "integers, or contains a duplicate or an id that is not in this "
            "list (including ids from other lists); nothing is changed then. "
            "Returns 404 when the list is not found. Reordering rewrites the "
            "date added of every item in the list, since that is where the "
            "custom order is stored."
        ),
    )
    def put(self, request, list_id):
        """Apply the full order (mirrors reorder_list_items_all)."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        serializer = ListItemsOrderRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid item_ids.", "errors": serializer.errors},
                status=HTTP.BAD_REQUEST,
            )
        status = apply_full_order(custom_list, serializer.validated_data["item_ids"])
        if status >= HTTP.BAD_REQUEST:
            return Response(
                {"detail": "item_ids must list each item of this list at most once."},
                status=status,
            )
        return Response(status=status)


def _arrange_by_rank(custom_list):
    """Put the list's ranked items in rank order, in the slots they hold.

    Unranked items do not move; ranked items that share a rank keep their
    current relative order.
    """
    ranked = list(
        CustomListItem.objects.filter(custom_list=custom_list, rank__isnull=False)
        .order_by("rank", "date_added", "id")
        .values_list("item_id", flat=True),
    )
    if ranked:
        apply_full_order(custom_list, ranked)


# /api/v1/lists/[list_id]/items/ranks/
class ListItemsRanksView(drf_views.APIView):
    """Set or clear the ranks of some items in a list."""

    @extend_schema(
        request=ListItemsRanksRequestSerializer,
        responses={204: None, 400: DetailErrorSerializer, **_ORDER_ERRORS},
        description=(
            "Record where items stand in an outside ranking, such as #81 of "
            "100. The list keeps one order, its custom order: after the ranks "
            "are saved, every ranked item of the list sits in rank order in "
            "the positions the ranked items already hold, and unranked items "
            "do not move, so #1-80 can be added in a later call. The rank "
            "stays on the item as a number, and a drag in the custom order "
            "moves the item without changing it. `GET "
            "/api/v1/lists/{list_id}/items/` returns each entry's `rank`, "
            "null when unset. Items with the same rank keep their relative "
            "order. Requires edit access to the list. Returns 204 with no "
            "body. Returns 400 when `ranks` is missing, empty or malformed, "
            "an `item_id` repeats, or an `item_id` is not in this list; "
            "nothing is changed then. Returns 404 when the list is not found. "
            "Like PUT .../items/order/, it rewrites the date added of every "
            "item in the list, since that is where the custom order is stored."
        ),
    )
    def put(self, request, list_id):
        """Apply the ranks to the listed items, all or none."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        serializer = ListItemsRanksRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"detail": "Invalid ranks.", "errors": serializer.errors},
                status=HTTP.BAD_REQUEST,
            )
        entries = serializer.validated_data["ranks"]
        ranks = {entry["item_id"]: entry["rank"] for entry in entries}
        if len(ranks) != len(entries):
            return Response(
                {"detail": "Each item_id may appear once."},
                status=HTTP.BAD_REQUEST,
            )
        with transaction.atomic():
            CustomListItem.objects.lock_custom_lists([custom_list.id])
            rows = list(
                CustomListItem.objects.filter(
                    custom_list=custom_list,
                    item_id__in=ranks,
                ),
            )
            if len(rows) != len(ranks):
                return Response(
                    {"detail": "Every item_id must be an item of this list."},
                    status=HTTP.BAD_REQUEST,
                )
            for row in rows:
                row.rank = ranks[row.item_id]
            CustomListItem.objects.bulk_update(rows, ["rank"])
            _arrange_by_rank(custom_list)
        return Response(status=HTTP.NO_CONTENT)


def _serialize_recommendation(recommendation):
    return {
        "id": recommendation.id,
        "item_id": recommendation.item_id,
        "title": recommendation.item.title,
        "media_type": recommendation.item.media_type,
        "source": recommendation.item.source,
        "media_id": recommendation.item.media_id,
        "season_number": recommendation.item.season_number,
        "episode_number": recommendation.item.episode_number,
        "image": recommendation.item.image,
        "recommended_by": recommendation.recommender_display_name,
        "note": recommendation.note,
        "date_recommended": recommendation.date_recommended,
    }


# /api/v1/lists/[list_id]/recommendations/
class ListRecommendationsView(drf_views.APIView):
    """List pending recommendations or submit a new one."""

    def get(self, request, list_id):
        """Return pending recommendations (owner/collaborators only)."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        recommendations = custom_list.recommendations.select_related(
            "item",
            "recommended_by",
        ).order_by("-date_recommended")
        return Response(
            {"results": [_serialize_recommendation(rec) for rec in recommendations]},
            status=HTTP.OK,
        )

    def post(self, request, list_id):
        """Submit a recommendation (mirrors submit_recommendation, auth only)."""
        custom_list = (
            CustomList.objects.select_related("owner").filter(id=list_id).first()
        )
        if custom_list is None or not custom_list.user_can_view(request.user):
            return Response({"detail": "List not found."}, status=HTTP.NOT_FOUND)
        if not custom_list.can_recommend():
            return Response(
                {"detail": "Recommendations are not enabled for this list."},
                status=HTTP.BAD_REQUEST,
            )

        media_id = request.data.get("media_id")
        media_type = request.data.get("media_type")
        source = request.data.get("source")
        if not (media_id and media_type and source):
            return Response(
                {"detail": "media_id, media_type, and source are required."},
                status=HTTP.BAD_REQUEST,
            )
        season_number = request.data.get("season_number")
        episode_number = request.data.get("episode_number")
        try:
            season_number = int(season_number) if season_number else None
            episode_number = int(episode_number) if episode_number else None
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid season/episode number."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            item = get_or_create_recommendation_item(
                media_id,
                media_type,
                source,
                season_number,
                episode_number,
                user=request.user,
                language=metadata_resolution.metadata_language_default(
                    request.user
                ),
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve item.", "errors": str(e)},
                status=HTTP.BAD_GATEWAY,
            )

        if list_has_item_identity(custom_list, item):
            return Response(
                {"detail": f'"{item.title}" is already in this list.'},
                status=HTTP.CONFLICT,
            )
        if ListRecommendation.objects.filter(
            custom_list=custom_list,
            item=item,
        ).exists():
            return Response(
                {"detail": f'"{item.title}" has already been recommended.'},
                status=HTTP.CONFLICT,
            )

        recommendation = ListRecommendation.objects.create(
            custom_list=custom_list,
            item=item,
            recommended_by=request.user,
            note=(request.data.get("note") or "").strip()[:1000],
        )
        return Response(
            _serialize_recommendation(recommendation),
            status=HTTP.CREATED,
        )


# /api/v1/lists/[list_id]/recommendations/[recommendation_id]/approve|deny/
class ListRecommendationDecisionView(drf_views.APIView):
    """Approve or deny a recommendation (mirrors the web decision views)."""

    def post(self, request, list_id, recommendation_id, decision):
        """Apply the decision; approval adds the item to the list."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        recommendation = ListRecommendation.objects.filter(
            id=recommendation_id,
            custom_list=custom_list,
        ).first()
        if recommendation is None:
            return Response(
                {"detail": "Recommendation not found."},
                status=HTTP.NOT_FOUND,
            )

        item = recommendation.item
        recommender_name = recommendation.recommender_display_name

        if decision == "approve":
            added = False
            if not custom_list.items.filter(id=item.id).exists():
                CustomListItem.objects.create(
                    custom_list=custom_list,
                    item=item,
                    added_by=request.user,
                )
                ListActivity.objects.create(
                    custom_list=custom_list,
                    user=request.user,
                    activity_type=ListActivityType.RECOMMENDATION_APPROVED,
                    item=item,
                    details=f"Recommended by {recommender_name}",
                )
                added = True
            recommendation.delete()
            return Response(
                {"approved": True, "added": added},
                status=HTTP.OK,
            )

        recommendation.delete()
        ListActivity.objects.create(
            custom_list=custom_list,
            user=request.user,
            activity_type=ListActivityType.RECOMMENDATION_DENIED,
            item=item,
            details=f"Recommended by {recommender_name}",
        )
        return Response({"approved": False}, status=HTTP.OK)


# /api/v1/lists/[list_id]/activity/
class ListActivityView(drf_views.APIView):
    """Activity log for a list (owner/collaborators only)."""

    def get(self, request, list_id):
        """Return the 100 most recent activity entries."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        activities = custom_list.activities.select_related("user", "item").order_by(
            "-timestamp",
        )[:100]
        return Response(
            {
                "results": [
                    {
                        "id": activity.id,
                        "activity_type": activity.activity_type,
                        "user": activity.user.username if activity.user else None,
                        "item_id": activity.item_id,
                        "item_title": activity.item.title if activity.item else None,
                        "details": activity.details,
                        "timestamp": activity.timestamp,
                    }
                    for activity in activities
                ],
            },
            status=HTTP.OK,
        )
