# FORK: person and studio profile endpoints for the native app. They run the
# web profile views (`app.people_views`) and return their JSON contract, so the
# filter, sort and credit logic has one owner.
import json
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.http import HttpResponseBadRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import people_views
from app.providers import services

from .contract_serializers import DetailErrorSerializer

logger = logging.getLogger(__name__)

PERSON_FILTER_PARAMS = (
    "department",
    "year",
    "genre",
    "implied_genre",
    "source",
    "rating",
    "collection",
    "sort",
    "direction",
)


def _profile_response(request, view, *args):
    """Run a web profile view as JSON and relay its contract."""
    http_request = getattr(request, "_request", request)
    http_request.user = request.user
    query = http_request.GET.copy()
    query["format"] = "json"
    http_request.GET = query
    try:
        response = view(http_request, *args, "profile")
    except services.ProviderAPIError as exc:
        logger.warning("Profile provider failed: %s", exc)
        return Response(
            {"detail": f"{exc.provider_label} is currently unavailable."},
            status=HTTP.BAD_GATEWAY,
        )
    if isinstance(response, HttpResponseBadRequest):
        return Response({"detail": response.content.decode()}, status=HTTP.BAD_REQUEST)
    if response.status_code != HTTP.OK:
        return Response({"detail": "Profile not available."}, status=response.status_code)
    return Response(json.loads(response.content), status=HTTP.OK)


# /api/v1/people/[source]/[person_id]/
class PersonView(drf_views.APIView):
    """A person or author profile with the filmography toolbar state."""

    @extend_schema(
        operation_id="getPerson",
        parameters=[
            OpenApiParameter(name=name, type=str, location=OpenApiParameter.QUERY)
            for name in PERSON_FILTER_PARAMS
        ],
        responses={200: dict, 400: DetailErrorSerializer, 502: DetailErrorSerializer},
    )
    def get(self, request, source, person_id):
        """Return hero, counts, watched and filmography credits, and filters."""
        return _profile_response(request, people_views.person_detail, source, person_id)


# /api/v1/studios/[source]/[studio_id]/
class StudioView(drf_views.APIView):
    """A studio profile with its credited titles."""

    @extend_schema(
        operation_id="getStudio",
        responses={200: dict, 404: DetailErrorSerializer},
    )
    def get(self, request, source, studio_id):
        """Return hero, counts and credited titles for a studio."""
        return _profile_response(request, people_views.studio_detail, source, studio_id)
