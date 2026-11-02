"""REST endpoints for personal TV episode ordering."""

from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from app.episode_order_views import available_orders, owned_tv, selected_order
from app.models import EpisodeOrder
from app.services import episode_ordering


class EpisodeOrderView(APIView):
    """List provider orders and apply an explicit history reconciliation."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, tv_id):
        """Return currently available provider orders for one tracked show."""
        tv = owned_tv(request.user, tv_id)
        orders, errors = available_orders(tv, request.user)
        return Response({
            "active": tv.active_episode_order_id, "orders": orders, "errors": errors,
            "can_revert": episode_ordering.can_revert(tv),
        })

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def post(self, request, tv_id):
        """Preview or apply an order change using stable provider identities."""
        tv = owned_tv(request.user, tv_id)
        action = request.data.get("action", "preview")
        try:
            if action == "preview":
                order = selected_order(
                    tv, request.user, request.data.get("provider"), request.data.get("key"),
                )
                preview = episode_ordering.preview_change(tv, order)
                return Response({"order_id": order.pk, **preview})
            if action == "revert":
                change = episode_ordering.revert_change(tv)
                tv.refresh_from_db()
                return Response({
                    "change_id": change.pk, "active_order": tv.active_episode_order_id,
                })
            order = EpisodeOrder.objects.get(pk=request.data.get("order_id"), show=tv.item)
            journal = episode_ordering.apply_change(
                tv,
                order,
                token=request.data.get("token", ""),
                resolutions=request.data.get("resolutions") or [],
            )
            return Response({"change_id": journal.pk, "active_order": order.pk})
        except EpisodeOrder.DoesNotExist:
            return Response({"detail": "Episode order not found."}, status=status.HTTP_404_NOT_FOUND)
        except (ValueError, TypeError, KeyError) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
