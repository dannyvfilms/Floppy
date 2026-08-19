# FORK: advanced list endpoints — smart rules, collaborators, reorder,
# recommendations, and activity — mirroring the fork's web list views.
# URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.auth import get_user_model
from rest_framework import views as drf_views
from rest_framework.response import Response

from lists import smart_rules
from lists.models import (
    CustomList,
    CustomListItem,
    ListActivity,
    ListActivityType,
    ListRecommendation,
)
from lists.views_add_reorder import apply_full_order, apply_reorder_action
from lists.views_recommendations import get_or_create_recommendation_item

logger = logging.getLogger(__name__)


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


def _serialize_smart_rules(custom_list):
    return {
        "is_smart": custom_list.is_smart,
        "smart_media_types": custom_list.smart_media_types,
        "smart_excluded_media_types": custom_list.smart_excluded_media_types,
        "smart_filters": custom_list.smart_filters,
        "items_count": custom_list.items.count(),
    }


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
        custom_list.smart_filters = {
            key: normalized.get(key, smart_rules.SMART_FILTER_DEFAULTS[key])
            for key in smart_rules.SMART_FILTER_KEYS
        }
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


# /api/v1/lists/[list_id]/items/reorder/
class ListItemsReorderView(drf_views.APIView):
    """Move a single item within the list's custom order."""

    def post(self, request, list_id):
        """Apply a first/back/next/last move (mirrors reorder_list_item)."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        status = apply_reorder_action(
            custom_list,
            request.data.get("item_id"),
            (request.data.get("action") or "").strip().lower(),
        )
        if status >= HTTP.BAD_REQUEST:
            return Response(
                {"detail": "Invalid item_id/action."},
                status=status,
            )
        return Response(status=status)


# /api/v1/lists/[list_id]/items/order/
class ListItemsOrderView(drf_views.APIView):
    """Replace the list's custom order with an ordered item-id list."""

    def put(self, request, list_id):
        """Apply the full order (mirrors reorder_list_items_all)."""
        custom_list, error = _get_editable_list(request, list_id)
        if error:
            return error
        item_ids = request.data.get("item_ids")
        if not isinstance(item_ids, list) or not item_ids:
            return Response(
                {"detail": "'item_ids' must be a non-empty list."},
                status=HTTP.BAD_REQUEST,
            )
        status = apply_full_order(custom_list, item_ids)
        if status >= HTTP.BAD_REQUEST:
            return Response({"detail": "Invalid item ids."}, status=status)
        return Response(status=status)


def _serialize_recommendation(recommendation):
    return {
        "id": recommendation.id,
        "item_id": recommendation.item_id,
        "title": recommendation.item.title,
        "media_type": recommendation.item.media_type,
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
            )
        except Exception as e:
            return Response(
                {"detail": "Could not resolve item.", "errors": str(e)},
                status=HTTP.BAD_GATEWAY,
            )

        if custom_list.items.filter(id=item.id).exists():
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
