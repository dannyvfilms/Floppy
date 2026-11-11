# FORK: calendar endpoints the native app needs beyond /api/v1/calendar/:
# the user's ICS subscription links (with the option lists the links panel
# renders) and the viewer's tracking status per event. URL wiring lives in
# fork_urls.py.
from collections import defaultdict
from http import HTTPStatus as HTTP  # noqa: N814

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import Item, MediaTypes, Status
from app.templatetags.app_tags import (
    media_status_readable,
    media_type_readable_plural,
)
from events.history_feed import DEFAULT_MEDIA_TYPES, HISTORY_MEDIA_TYPES
from events.models import INACTIVE_TRACKING_STATUSES, Event, ReleaseTypes

from .helpers import resolve_calendar_date_range

_NO_STATUS_TYPES = {MediaTypes.TV.value, MediaTypes.EPISODE.value}


def _event_status_values():
    return [
        status.value
        for status in Status
        if status.value not in INACTIVE_TRACKING_STATUSES
    ]


def _release_media_types():
    return [
        media_type.value
        for media_type in MediaTypes
        if media_type != MediaTypes.EPISODE
    ]


def _filter_media_types(user):
    enabled = set(user.get_enabled_media_types())
    if MediaTypes.TV.value in enabled:
        enabled.add(MediaTypes.SEASON.value)
    return sorted(enabled, key=lambda media_type: MediaTypes(media_type).label)


# /api/v1/calendar/links/
class CalendarLinksView(drf_views.APIView):
    """The user's calendar subscription URLs and the links panel options.

    The URLs embed the permanent account token, so these require a session,
    including for first-party full-access tokens.
    """

    @extend_schema(operation_id="getCalendarLinks", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return release and history ICS URLs plus filter vocabularies."""
        user = request.user
        statuses = _event_status_values()
        release_type_choices = ReleaseTypes.choices
        media_types = _release_media_types()
        enabled = set(user.get_enabled_media_types())
        filter_media_types = _filter_media_types(user)
        return Response(
            {
                "release_base_url": request.build_absolute_uri(
                    reverse("download_calendar", kwargs={"token": user.token}),
                ),
                "history_base_url": request.build_absolute_uri(
                    reverse("download_history_calendar", kwargs={"token": user.token}),
                ),
                "release_media_types": [
                    {
                        "value": media_type,
                        "label": media_type_readable_plural(media_type),
                    }
                    for media_type in media_types
                ],
                "history_media_types": [
                    {
                        "value": media_type,
                        "label": media_type_readable_plural(media_type),
                    }
                    for media_type in HISTORY_MEDIA_TYPES
                ],
                "statuses": [
                    {"value": status, "label": media_status_readable(status)}
                    for status in statuses
                ],
                "release_types": [
                    {"value": value, "label": str(label)}
                    for value, label in release_type_choices
                ],
                "initial_release_media_types": [
                    media_type for media_type in media_types if media_type in enabled
                ],
                "initial_history_media_types": list(DEFAULT_MEDIA_TYPES),
                "initial_statuses": statuses,
                "initial_release_types": [value for value, _ in release_type_choices],
                "filter_media_types": [
                    {
                        "value": media_type,
                        "label": media_type_readable_plural(media_type),
                    }
                    for media_type in filter_media_types
                ],
                "filter_statuses_by_type": {
                    media_type: statuses
                    for media_type in filter_media_types
                    if media_type not in _NO_STATUS_TYPES
                },
                "user_id": user.id,
                "week_start_day": user.week_start_day,
                "region_unset": user.watch_provider_region == "UNSET",
            },
            status=HTTP.OK,
        )


# /api/v1/calendar/statuses/
class CalendarStatusesView(drf_views.APIView):
    """The viewer's tracking status for each event in a date range.

    Events do not carry the viewer's status; the web calendar derives it from
    the viewer's own tracked rows, and so does this.
    """

    @extend_schema(
        operation_id="getCalendarStatuses",
        parameters=[
            OpenApiParameter("start_date", str),
            OpenApiParameter("end_date", str),
            OpenApiParameter("month", int),
            OpenApiParameter("year", int),
        ],
    responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        """Return {event_id: status} for events the viewer tracks."""
        try:
            first_day, last_day = resolve_calendar_date_range(
                request.GET.get("start_date"),
                request.GET.get("end_date"),
                request.GET.get("month"),
                request.GET.get("year"),
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid date format."},
                status=HTTP.BAD_REQUEST,
            )
        events = list(
            Event.objects.get_user_events(request.user, first_day, last_day)
            .select_related("item"),
        )
        item_ids_by_type = defaultdict(set)
        for event in events:
            item_ids_by_type[event.item.media_type].add(event.item_id)
        status_by_item_id = {}
        for media_type, item_ids in item_ids_by_type.items():
            if media_type == MediaTypes.EPISODE.value:
                continue
            status_by_item_id.update(
                Item.objects.filter(
                    id__in=item_ids,
                    **{f"{media_type}__user": request.user},
                ).values_list("id", f"{media_type}__status"),
            )
        return Response(
            {
                "statuses": {
                    str(event.id): status_by_item_id[event.item_id]
                    for event in events
                    if status_by_item_id.get(event.item_id)
                },
            },
            status=HTTP.OK,
        )
