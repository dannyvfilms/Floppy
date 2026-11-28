# FORK: person and studio profile endpoints for the native app. They run the
# web profile views (`app.people_views`) and return their JSON contract, so the
# filter, sort and credit logic has one owner.
import json
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.http import HttpResponseBadRequest
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import people_views
from app.models import Person
from app.providers import services, tmdb
from lists.models import CustomList, CustomListPerson

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
    "adult_mode",
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
    except services.ProviderNotConfiguredError as exc:
        logger.warning("Profile provider failed: %s", exc)
        # Say which provider needs credentials so a client can link to its settings.
        return Response(
            {
                "detail": str(exc),
                "errors": {
                    "provider": exc.provider,
                    "provider_label": exc.provider_label,
                    "settings_path": reverse("provider_detail", kwargs={"slug": exc.provider}),
                },
            },
            status=HTTP.BAD_GATEWAY,
        )
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


# /api/v1/people/search/
class PersonSearchView(drf_views.APIView):
    """Search TMDB people for the people-discovery surface."""

    @extend_schema(
        operation_id="searchPeople",
        parameters=[
            OpenApiParameter(
                name="query",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Person name to search (minimum two characters).",
            ),
        ],
        responses={200: dict, 502: DetailErrorSerializer},
    )
    def get(self, request):
        """Return bounded, normalized TMDB person matches."""
        query = str(request.query_params.get("query") or "").strip()
        if len(query) < people_views.MIN_PERSON_SEARCH_LENGTH:
            return Response({"query": query, "people": []}, status=HTTP.OK)
        query = query[: people_views.MAX_PERSON_SEARCH_LENGTH]
        try:
            with services.interactive_request_scope():
                people = tmdb.search_people(query)
        except services.ProviderAPIError as exc:
            logger.warning("People search provider failed: %s", exc)
            return Response(
                {"detail": "TMDB is currently unavailable."},
                status=HTTP.BAD_GATEWAY,
            )
        return Response(
            {"query": query, "people": people_views.person_search_results(people)},
            status=HTTP.OK,
        )


class AdvancedDiscoverView(drf_views.APIView):
    """Search TMDB Discover and return the shared web/native presentation model."""

    @extend_schema(
        operation_id="advancedTmdbDiscover",
        parameters=[
            OpenApiParameter("type", OpenApiTypes.STR, description="movie or tv; defaults to movie."),
            OpenApiParameter("search", OpenApiTypes.STR, description="Set to 1 to run the discovery query."),
            OpenApiParameter("person", OpenApiTypes.STR, many=True, explode=True, description="Repeated TMDB person IDs."),
            OpenApiParameter("person_role", OpenApiTypes.STR, description="people, cast, or crew."),
            OpenApiParameter("person_logic", OpenApiTypes.STR, description="and or or for staged people IDs."),
            OpenApiParameter("certification_country", OpenApiTypes.STR),
            OpenApiParameter(
                "certification",
                OpenApiTypes.STR,
                many=True,
                explode=True,
                description="Repeated ratings are ORed within certification_country.",
            ),
            OpenApiParameter("include_adult", OpenApiTypes.BOOL),
            OpenApiParameter("include_video", OpenApiTypes.BOOL, description="Movie only."),
            OpenApiParameter("include_null_first_air_dates", OpenApiTypes.BOOL, description="TV only."),
            OpenApiParameter("sort", OpenApiTypes.STR, description="release_date, title, popularity, or votes."),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("format", OpenApiTypes.STR, description="Use json for the shared view contract."),
        ],
        responses={200: dict},
    )
    def get(self, request):
        """Return TMDB filters and optionally the provider discovery result."""
        http_request = getattr(request, "_request", request)
        http_request.user = request.user
        query = http_request.GET.copy()
        query["format"] = "json"
        http_request.GET = query
        try:
            response = people_views.advanced_discover(http_request)
        except services.ProviderAPIError as exc:
            logger.warning("Advanced discovery provider failed: %s", exc)
            return Response({"detail": "TMDB is currently unavailable."}, status=HTTP.BAD_GATEWAY)
        if response.status_code != HTTP.OK:
            return Response({"detail": "Advanced discovery is unavailable."}, status=response.status_code)
        return Response(json.loads(response.content), status=HTTP.OK)


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


def _saved_person(source, person_id):
    """Return the stored person row for a profile, or None."""
    return Person.objects.filter(source=source, source_person_id=str(person_id)).first()


# /api/v1/people/[source]/[person_id]/lists/
class PersonListsView(drf_views.APIView):
    """The lists a person is saved on, for the viewer."""

    @extend_schema(operation_id="getPersonLists", responses={200: dict, 404: DetailErrorSerializer})
    def get(self, request, source, person_id):
        """Return the viewer's lists that hold this person."""
        person = _saved_person(source, person_id)
        if person is None:
            return Response({"detail": "Person not found."}, status=HTTP.NOT_FOUND)
        list_ids = CustomListPerson.objects.filter(
            person=person,
            custom_list__in=CustomList.objects.get_user_lists(request.user),
        ).values_list("custom_list_id", flat=True)
        return Response({"results": [{"list_id": list_id} for list_id in list_ids]})


# /api/v1/people/[source]/[person_id]/lists/[list_id]/
class PersonListDetailView(drf_views.APIView):
    """Save a person on a list, or take them off it."""

    def _resolve(self, request, source, person_id, list_id):
        person = _saved_person(source, person_id)
        if person is None:
            return None, None, Response({"detail": "Person not found."}, status=HTTP.NOT_FOUND)
        custom_list = CustomList.objects.filter(id=list_id).first()
        if custom_list is None or not custom_list.user_can_view(request.user):
            return None, None, Response({"detail": "List not found."}, status=HTTP.NOT_FOUND)
        if not custom_list.user_can_edit(request.user) or custom_list.is_smart:
            return None, None, Response({"detail": HTTP.FORBIDDEN.phrase}, status=HTTP.FORBIDDEN)
        return person, custom_list, None

    @extend_schema(request=None, responses={204: None, 403: DetailErrorSerializer, 404: DetailErrorSerializer})
    def put(self, request, source, person_id, list_id):
        """Add the person to the list; saving twice is harmless."""
        person, custom_list, error = self._resolve(request, source, person_id, list_id)
        if error:
            return error
        CustomListPerson.objects.get_or_create(
            custom_list=custom_list,
            person=person,
            defaults={"added_by": request.user},
        )
        return Response(status=HTTP.NO_CONTENT)

    @extend_schema(responses={204: None, 403: DetailErrorSerializer, 404: DetailErrorSerializer})
    def delete(self, request, source, person_id, list_id):
        """Remove the person from the list."""
        person, custom_list, error = self._resolve(request, source, person_id, list_id)
        if error:
            return error
        CustomListPerson.objects.filter(custom_list=custom_list, person=person).delete()
        return Response(status=HTTP.NO_CONTENT)
