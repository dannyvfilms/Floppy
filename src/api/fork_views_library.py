# FORK: library page endpoints for the native app. The web media list builds
# its filter menu and bulk toolbar inside session-only views; these views call
# the same builders and bulk handlers so a Bearer-token client gets the same
# option lists and the same bulk semantics, with no second implementation.
import json
from collections import defaultdict
from dataclasses import replace
from http import HTTPStatus as HTTP  # noqa: N814
from urllib.parse import urlencode

from django.db.models import Count
from django.http import Http404, HttpRequest, QueryDict
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework import views as drf_views
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from app import bulk_action_views
from app.library_query import LibraryQueryExecutor
from app.library_query.adapters import from_media_list_filters
from app.media_list_filters import (
    MediaListFilterError,
    media_list_media_types,
    parse_media_list_filters,
)
from app.media_list_views import (
    AUTHOR_FILTER_MEDIA_TYPES,
    AUTHOR_MEDIA_TYPES,
    GAME_GROUP_BY_CHOICES,
    PROGRESS_MEDIA_TYPES,
    PROVIDER_MEDIA_TYPES,
    _normalize_filter_value,
    build_filter_data_from_item_values,
)
from app.models import BasicMedia, CollectionEntry, Item, ItemTag, MediaTypes, Tag
from app.services import bulk_show_plays
from lists import views_list_actions

from .helpers import check_valid_type
from .schema import MEDIA_LIST_FILTER_PARAMS, MEDIA_TYPE_COMPLETE_PARAM

TEXT_FILTER_TYPES = (
    MediaTypes.TV.value,
    MediaTypes.MOVIE.value,
    MediaTypes.ANIME.value,
    MediaTypes.PODCAST.value,
)
MAX_BULK_ITEMS = 5000


class LibraryFilterOptionsSerializer(serializers.Serializer):
    """Option lists the library filter menu offers for one media type."""

    media_type = serializers.CharField()
    genres = serializers.ListField(child=serializers.CharField())
    implied_genres = serializers.ListField(child=serializers.CharField())
    years = serializers.ListField(child=serializers.DictField())
    sources = serializers.ListField(child=serializers.DictField())
    languages = serializers.ListField(child=serializers.DictField())
    countries = serializers.ListField(child=serializers.DictField())
    platforms = serializers.ListField(child=serializers.DictField())
    formats = serializers.ListField(child=serializers.DictField())
    authors = serializers.ListField(child=serializers.DictField())
    providers = serializers.ListField(child=serializers.DictField())
    media_statuses = serializers.ListField(child=serializers.DictField())
    tags = serializers.ListField(child=serializers.DictField())
    show_languages = serializers.BooleanField()
    show_countries = serializers.BooleanField()
    show_platforms = serializers.BooleanField()
    show_formats = serializers.BooleanField()
    show_authors = serializers.BooleanField()
    author_is_channel = serializers.BooleanField()
    show_providers = serializers.BooleanField()
    show_progress = serializers.BooleanField()


class LibraryItemIdsSerializer(serializers.Serializer):
    """Item ids behind the current filters."""

    item_ids = serializers.ListField(child=serializers.IntegerField())


class BulkItemsSerializer(serializers.Serializer):
    """Base body of every library bulk action."""

    item_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=MAX_BULK_ITEMS,
    )


class BulkStatusRequestSerializer(BulkItemsSerializer):
    """Apply one status (or ``no_status``) to the selected items."""

    status = serializers.CharField()


class BulkListRequestSerializer(BulkItemsSerializer):
    """Add the selected items to one manual list."""

    list_id = serializers.IntegerField(min_value=1)


class BulkTagRequestSerializer(BulkItemsSerializer):
    """Add or remove one tag across the selected items."""

    tag_id = serializers.IntegerField(min_value=1)
    action = serializers.ChoiceField(choices=["add", "remove"], default="add")


class BulkPlaysRequestSerializer(BulkItemsSerializer):
    """Start a preview or a run of Add Plays to History for selected shows."""

    scope = serializers.CharField(required=False)
    season_from = serializers.IntegerField(required=False, allow_null=True)
    season_to = serializers.IntegerField(required=False, allow_null=True)
    existing = serializers.CharField(required=False)
    date_mode = serializers.CharField(required=False)
    start = serializers.CharField(required=False, allow_blank=True)
    end = serializers.CharField(required=False, allow_blank=True)
    date = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.CharField(required=False, allow_blank=True)
    end_date = serializers.CharField(required=False, allow_blank=True)
    dry_run = serializers.BooleanField(required=False, default=False)


class BulkResultSerializer(serializers.Serializer):
    """Outcome of a bulk action, mirroring the web toolbar's JSON."""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False)
    updated = serializers.IntegerField(required=False)
    created = serializers.IntegerField(required=False)
    added = serializers.IntegerField(required=False)
    already_present = serializers.IntegerField(required=False)
    skipped = serializers.IntegerField(required=False)
    operation_id = serializers.CharField(required=False)


class BulkPlaysStatusSerializer(serializers.Serializer):
    """Progress of a bulk plays preview or run."""

    success = serializers.BooleanField()
    state = serializers.CharField(required=False)
    dry_run = serializers.BooleanField(required=False)
    total = serializers.IntegerField(required=False)
    done = serializers.IntegerField(required=False)


def _media_type_error(media_type):
    if not check_valid_type(media_type, complete=True):
        return Response({"detail": "Unsupported media type."}, status=HTTP.BAD_REQUEST)
    return None


def _item_choice(values):
    return [{"value": value, "label": value} for value in values]


class LibraryFilterOptionsView(drf_views.APIView):
    """Option lists for the library filter menu of one media type."""

    @extend_schema(
        parameters=[MEDIA_TYPE_COMPLETE_PARAM, *MEDIA_LIST_FILTER_PARAMS],
        operation_id="listLibraryFilterOptions",
        responses={200: LibraryFilterOptionsSerializer},
    )
    def get(self, request, media_type):
        """Return what the menu lists for the filters that are already set.

        Like the web menu, the options are read before the per-item filters
        narrow the list (rating, dates, collection, progress, author, format,
        provider), so choosing one filter does not hide the others.
        """
        error = _media_type_error(media_type)
        if error:
            return error
        try:
            filters = replace(parse_media_list_filters(request), media_type=media_type)
        except MediaListFilterError as exc:
            return Response(
                {"detail": f"Invalid {exc.parameter}: {exc}"},
                status=HTTP.BAD_REQUEST,
            )
        user = request.user
        region = filters.provider_region or None
        menu_filters = replace(
            filters,
            rating="all",
            rating_min="",
            rating_max="",
            release_date_from="",
            release_date_to="",
            date_added_from="",
            date_added_to="",
            collection="all",
            progress="all",
            author="",
            format="",
            provider="",
            platforms=() if media_type == MediaTypes.GAME.value else filters.platforms,
            tags=(),
        )
        engine = LibraryQueryExecutor(
            user,
            from_media_list_filters(
                menu_filters, media_list_media_types(menu_filters, media_type),
            ),
        )
        items = Item.objects.filter(pk__in=engine.filtered.values("pk")).order_by()
        rows = list(BasicMedia.objects.item_values_for_menu(items, region))
        item_ids = {row["id"] for row in rows}

        platforms_by_item = defaultdict(set)
        formats_by_item = defaultdict(set)
        if item_ids and media_type == MediaTypes.GAME.value:
            for item_id, resolution in CollectionEntry.objects.filter(
                user=user, item_id__in=item_ids,
            ).values_list("item_id", "resolution"):
                value = str(resolution or "").strip()
                if value:
                    platforms_by_item[item_id].add(value)
        if item_ids and media_type in AUTHOR_MEDIA_TYPES:
            for item_id, collected_format in (
                CollectionEntry.objects.filter(user=user, item_id__in=item_ids)
                .exclude(media_type="")
                .values_list("item_id", "media_type")
            ):
                value = _normalize_filter_value(collected_format)
                if value:
                    formats_by_item[item_id].add(value)

        has_providers = media_type in PROVIDER_MEDIA_TYPES
        data = build_filter_data_from_item_values(
            rows,
            collection_formats_by_item_id=formats_by_item,
            collection_platforms_by_item_id=platforms_by_item,
            region=region,
            pinned_providers=user.pinned_watch_providers,
            include_providers=False,
        )
        counts = dict(
            ItemTag.objects.filter(
                tag__user=user, item_id__in=engine.filtered.values("pk"),
            )
            .values("tag_id")
            .annotate(item_count=Count("item_id", distinct=True))
            .values_list("tag_id", "item_count"),
        )
        tags = [
            {"id": tag_id, "name": name, "count": counts.get(tag_id, 0)}
            for tag_id, name in Tag.objects.filter(user=user).values_list("id", "name")
        ]
        tags.sort(key=lambda tag: (-tag["count"], tag["name"].casefold()))
        providers = _item_choice(sorted(set(data["pinned_providers"]), key=str.lower))
        if has_providers:
            seen = {entry["value"] for entry in providers}
            providers += [entry for entry in data["providers"] if entry["value"] not in seen]
        payload = {
            "media_type": media_type,
            "genres": data["genres"],
            "implied_genres": data["implied_genres"],
            "years": data["years"],
            "sources": data["sources"],
            "languages": data["languages"],
            "countries": data["countries"],
            "platforms": data["platforms"],
            "formats": data["formats"],
            "authors": data["authors"],
            "providers": providers if has_providers else [],
            "media_statuses": data["media_statuses"],
            "tags": tags,
            "show_languages": media_type in TEXT_FILTER_TYPES,
            "show_countries": media_type in TEXT_FILTER_TYPES,
            "show_platforms": media_type == MediaTypes.GAME.value,
            "show_formats": media_type in AUTHOR_MEDIA_TYPES,
            "show_authors": media_type in AUTHOR_FILTER_MEDIA_TYPES,
            "author_is_channel": media_type == MediaTypes.VIDEO.value,
            "show_providers": has_providers
            and bool(
                (region and region != "UNSET") or user.pinned_watch_providers,
            ),
            "show_progress": media_type in PROGRESS_MEDIA_TYPES,
        }
        return Response(payload, status=HTTP.OK)


class LibraryItemIdsView(drf_views.APIView):
    """Every item id behind the current filters (the toolbar's Select all)."""

    @extend_schema(
        parameters=[MEDIA_TYPE_COMPLETE_PARAM, *MEDIA_LIST_FILTER_PARAMS],
        operation_id="listLibraryItemIds",
        responses={200: LibraryItemIdsSerializer},
    )
    def get(self, request, media_type):
        """Return the ids of all items that match the filters."""
        error = _media_type_error(media_type)
        if error:
            return error
        try:
            filters = replace(parse_media_list_filters(request), media_type=media_type)
        except MediaListFilterError as exc:
            return Response(
                {"detail": f"Invalid {exc.parameter}: {exc}"},
                status=HTTP.BAD_REQUEST,
            )
        engine = LibraryQueryExecutor(
            request.user,
            from_media_list_filters(filters, media_list_media_types(filters, media_type)),
        )
        return Response({"item_ids": sorted(engine.ids())}, status=HTTP.OK)


def _call_web_view(view, request, data, *args):
    """Run a session bulk handler with a form body and return (status, json).

    The handler is the web toolbar's own, so limits, validation and messages
    are identical. It only needs ``user`` and ``POST``.
    """
    django_request = HttpRequest()
    django_request.method = "POST"
    django_request.user = request.user
    django_request.POST = QueryDict(urlencode(data, doseq=True))
    try:
        response = view(django_request, *args)
    except Http404:
        return HTTP.NOT_FOUND, {"success": False, "error": "Not found."}
    if not response.content:
        return response.status_code, {"success": True}
    try:
        return response.status_code, json.loads(response.content)
    except ValueError:
        return response.status_code, {
            "success": False,
            "error": response.content.decode(errors="replace")[:200],
        }


def _bulk_response(status_code, body):
    if status_code >= HTTP.BAD_REQUEST:
        return Response(
            {"detail": body.get("error") or "The bulk action failed."},
            status=status_code,
        )
    return Response(body, status=HTTP.OK)


def _ids_field(validated):
    return ",".join(str(value) for value in validated["item_ids"])


class _BulkView(drf_views.APIView):
    request_serializer = BulkItemsSerializer

    def validated(self, request):
        serializer = self.request_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class LibraryBulkStatusView(_BulkView):
    """Update the status of the selected items."""

    request_serializer = BulkStatusRequestSerializer

    @extend_schema(
        operation_id="bulkLibraryStatus",
        request=BulkStatusRequestSerializer,
        responses={200: BulkResultSerializer},
    )
    def post(self, request):
        """Set a status (or ``no_status``) on every selected item."""
        data = self.validated(request)
        form = {"item_ids": _ids_field(data), "status": data["status"]}
        return _bulk_response(
            *_call_web_view(bulk_action_views.bulk_status_update, request, form),
        )


class LibraryBulkCollectionView(_BulkView):
    """Quick-add the selected items to the collection."""

    @extend_schema(
        operation_id="bulkLibraryCollection",
        request=BulkItemsSerializer,
        responses={200: BulkResultSerializer},
    )
    def post(self, request):
        """Add every selected item to the collection."""
        data = self.validated(request)
        form = {"item_ids": _ids_field(data)}
        return _bulk_response(
            *_call_web_view(bulk_action_views.bulk_collection_quick_add, request, form),
        )


class LibraryBulkListView(_BulkView):
    """Add the selected items to one manual list."""

    request_serializer = BulkListRequestSerializer

    @extend_schema(
        operation_id="bulkLibraryList",
        request=BulkListRequestSerializer,
        responses={200: BulkResultSerializer},
    )
    def post(self, request):
        """Add every selected item to the list."""
        data = self.validated(request)
        # The list id is in the body, so CanWriteBoundList cannot see it.
        token = request.auth
        if hasattr(token, "may_write_list") and not token.may_write_list(
            data["list_id"],
        ):
            msg = "This token may not write that list."
            raise PermissionDenied(msg)
        form = {"item_ids": _ids_field(data), "custom_list_id": data["list_id"]}
        return _bulk_response(
            *_call_web_view(views_list_actions.bulk_list_add, request, form),
        )


class LibraryBulkTagView(_BulkView):
    """Add or remove one tag across the selected items."""

    request_serializer = BulkTagRequestSerializer

    @extend_schema(
        operation_id="bulkLibraryTag",
        request=BulkTagRequestSerializer,
        responses={200: BulkResultSerializer},
    )
    def post(self, request):
        """Apply the tag to, or remove it from, every selected item."""
        from app.tag_views import tag_bulk_toggle

        data = self.validated(request)
        tag = Tag.objects.filter(user=request.user, id=data["tag_id"]).first()
        if tag is None:
            return Response({"detail": "Tag not found."}, status=HTTP.NOT_FOUND)
        form = {
            "item_ids": _ids_field(data),
            "tag_name": tag.name,
            "action": data["action"],
        }
        status_code, body = _call_web_view(tag_bulk_toggle, request, form)
        if status_code >= HTTP.BAD_REQUEST:
            return _bulk_response(status_code, {"error": body.get("error")})
        verb = "Applied" if data["action"] == "add" else "Removed"
        return Response(
            {
                "success": True,
                "message": f"{verb} {tag.name} on {len(data['item_ids'])} item(s).",
            },
            status=HTTP.OK,
        )


class LibraryBulkPlaysView(_BulkView):
    """Start a preview or run of Add Plays to History for selected shows."""

    request_serializer = BulkPlaysRequestSerializer

    @extend_schema(
        operation_id="bulkLibraryPlays",
        request=BulkPlaysRequestSerializer,
        responses={200: BulkResultSerializer},
    )
    def post(self, request):
        """Queue the job and return its operation id."""
        data = self.validated(request)
        form = {"item_ids": _ids_field(data)}
        for key in ("scope", "season_from", "season_to", "existing", "date_mode",
                    "start", "end", "date", "start_date", "end_date"):
            if data.get(key) not in (None, ""):
                form[key] = data[key]
        if data.get("dry_run"):
            form["dry_run"] = "1"
        return _bulk_response(
            *_call_web_view(bulk_action_views.bulk_show_plays_start, request, form),
        )


class LibraryBulkPlaysStatusView(drf_views.APIView):
    """Progress and results of a bulk plays preview or run."""

    @extend_schema(
        operation_id="bulkLibraryPlaysStatus",
        parameters=[OpenApiParameter("operation_id", str, OpenApiParameter.PATH)],
        responses={200: BulkPlaysStatusSerializer},
    )
    def get(self, request, operation_id):
        """Return the cached state of an operation the user started."""
        from django.core.cache import cache

        state = cache.get(bulk_show_plays.status_key(request.user.id, operation_id))
        if state is None:
            return Response({"detail": "This job has expired."}, status=HTTP.NOT_FOUND)
        return Response({"success": True, **state}, status=HTTP.OK)



# What the web media list stores per media type on the user
# (``<type>_layout`` ...) so the next visit opens the way it was left.
_LIBRARY_PREFERENCE_FIELDS = ("layout", "sort", "direction")
_MULTI_QUERY_KEYS = frozenset({"status", "tag", "platform", "exclude"})


def _library_type_error(media_type):
    if media_type not in MediaTypes.values:
        return Response({"detail": "Unsupported media type."}, status=HTTP.BAD_REQUEST)
    return None


def _saved_view_payload(saved):
    return {"id": saved.id, "name": saved.name, "mediaType": saved.media_type, "query": saved.query}


def _library_column_config(user, media_type, sort):
    from app.columns import resolve_column_config, resolve_default_column_config

    return {
        "columns": resolve_column_config(media_type, sort, user, "media"),
        "defaultColumns": resolve_default_column_config(media_type, sort, "media"),
    }


class LibraryPreferencesView(drf_views.APIView):
    """The viewer's saved layout, sort, status and table columns for one library.

    The same user fields the web media list reads and writes (``<type>_layout``,
    ``_sort``, ``_direction``, ``_status``, ``table_column_prefs``), plus the
    saved views the sidebar lists for the type.
    """

    @extend_schema(operation_id="retrieveLibraryPreferences", responses={200: OpenApiTypes.OBJECT})
    def get(self, request, media_type):
        """Return the stored preferences, column config and saved views."""
        from app.media_list_entry_grouping import (
            preference_field,
            show_separate_entries,
        )
        from users.models import SavedView

        error = _library_type_error(media_type)
        if error:
            return error
        user = request.user
        sort = str(getattr(user, f"{media_type}_sort", "") or "")
        status = str(getattr(user, f"{media_type}_status", "") or "")
        payload = {
            "mediaType": media_type,
            "layout": str(getattr(user, f"{media_type}_layout", "") or "grid"),
            "sort": sort,
            "direction": str(getattr(user, f"{media_type}_direction", "") or ""),
            "statuses": [value for value in status.split(",") if value and value != "All"],
            "canSeparateEntries": bool(preference_field(media_type)),
            "separateEntries": show_separate_entries(user, media_type),
            "savedViews": [
                _saved_view_payload(saved)
                for saved in SavedView.objects.filter(user=user, media_type=media_type)
            ],
            "groupBy": (
                [{"value": value, "label": label} for value, label in GAME_GROUP_BY_CHOICES]
                if media_type == MediaTypes.GAME.value else []
            ),
        }
        payload.update(_library_column_config(user, media_type, sort or "score"))
        return Response(payload)

    @extend_schema(operation_id="updateLibraryPreferences", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request, media_type):
        """Store layout, sort, direction and/or the table columns ({order, hidden})."""
        from app.columns import sanitize_column_prefs
        from app.media_list_entry_grouping import preference_field

        error = _library_type_error(media_type)
        if error:
            return error
        user = request.user
        if not all(hasattr(user, f"{media_type}_{name}") for name in _LIBRARY_PREFERENCE_FIELDS):
            return Response({"detail": "Unsupported media type for preferences."}, status=HTTP.BAD_REQUEST)
        if "separateEntries" in request.data:
            field_name = preference_field(media_type)
            if not field_name or not isinstance(request.data["separateEntries"], bool):
                return Response({"detail": "A supported media type and boolean separateEntries are required."}, status=HTTP.BAD_REQUEST)
            user.update_preference(field_name, request.data["separateEntries"])
        for name in _LIBRARY_PREFERENCE_FIELDS:
            if name in request.data:
                user.update_preference(f"{media_type}_{name}", str(request.data[name]))
        statuses = request.data.get("statuses")
        if isinstance(statuses, list):
            user.update_preference(
                f"{media_type}_status", ",".join(str(value) for value in statuses) or "All",
            )
        columns = request.data.get("columns")
        if isinstance(columns, dict):
            order = [v for v in columns.get("order") or [] if isinstance(v, str)]
            hidden = [v for v in columns.get("hidden") or [] if isinstance(v, str)]
            clean_order, clean_hidden = sanitize_column_prefs(
                media_type,
                str(getattr(user, f"{media_type}_sort", "") or "score"),
                user, "media", order, hidden,
            )
            user.update_column_prefs(
                media_type=media_type, table_type="media", order=clean_order, hidden=clean_hidden,
            )
        return Response(
            _library_column_config(user, media_type, str(getattr(user, f"{media_type}_sort", "") or "score")),
        )


class LibraryGameGroupsView(drf_views.APIView):
    """Paged Games collection/franchise cards followed by ungrouped games."""

    @extend_schema(operation_id="listLibraryGameGroups", parameters=MEDIA_LIST_FILTER_PARAMS, responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Aggregate group summaries in SQL; hydrate only the requested page."""
        from copy import copy
        from types import SimpleNamespace

        from django.db.models import (
            Avg,
            Case,
            CharField,
            F,
            Max,
            Min,
            Sum,
            Value,
            When,
            Window,
        )
        from django.db.models.functions import Concat, Lower, RowNumber

        from app.card_surfaces import card_context
        from app.library_query import sorts
        from app.media_card_model import card_model
        from app.media_list_filters import get_media_list_entries

        from .helpers import parse_limit_offset
        from .serializers import MediaSerializer, UntrackedMediaSerializer

        limit, offset, error = parse_limit_offset(request)
        if error:
            return error
        try:
            filters = parse_media_list_filters(request)
        except MediaListFilterError as cause:
            return Response({"detail": f"Invalid {cause.parameter}: {cause}"}, status=HTTP.BAD_REQUEST)
        if filters.group_by not in {"series", "franchise"}:
            return Response({"detail": "Choose series or franchise grouping."}, status=HTTP.BAD_REQUEST)
        filters = replace(filters, media_type="game", group="", separate_entries=False)
        query = from_media_list_filters(filters, ("game",))
        engine = LibraryQueryExecutor(request.user, query)
        ctx = engine.contexts[0]
        stem = "provider_collection" if filters.group_by == "series" else "provider_franchise"
        key = Case(
            When(**{f"{stem}_id__gt": ""}, then=Concat(Value("id:"), F(f"{stem}_id"))),
            When(**{f"{stem}_name__gt": ""}, then=Concat(Value("name:"), Lower(f"{stem}_name"))),
            default=Value(""), output_field=CharField(),
        )
        candidates = engine.filtered
        if engine._needs_scan:
            candidates = candidates.filter(pk__in=engine.ids())
        groups = candidates.order_by().annotate(group_key=key).exclude(group_key="").values("group_key").annotate(
            name=Min(f"{stem}_name"), representative=Min("pk"), game_count=Count("pk"),
            score=Avg(sorts.sort_def("score").sql(ctx, 0)),
            progress=Sum(sorts.sort_def("progress").sql(ctx, 0)),
            first_release=Min("release_datetime"), last_release=Max("release_datetime"),
            first_added=Min(sorts.sort_def("date_added").sql(ctx, 0)),
            first_started=Min(sorts.sort_def("start_date").sql(ctx, 0)),
            last_ended=Max(sorts.sort_def("last_watched").sql(ctx, 0)),
        )
        sort_field = {"score": "score", "critic_rating": "score", "progress": "progress", "time_watched": "progress",
                      "date_added": "first_added", "start_date": "first_started", "end_date": "last_ended", "release_date": "last_release"}.get(filters.sort, "name")
        value = Lower("name") if sort_field == "name" else F(sort_field)
        order = value.desc(nulls_last=True) if filters.direction == "desc" else value.asc(nulls_last=True)
        # The web reverses present-value name ties, but keeps missing values A-Z.
        present_name = Case(
            When(**{f"{sort_field}__isnull": True}, then=Value("")),
            default=Lower("name"), output_field=CharField(),
        )
        ties = present_name.desc() if filters.direction == "desc" else Lower("name").asc()
        groups = groups.order_by(order, ties, Lower("name"), "group_key")
        group_total = groups.count()
        window = list(groups[offset:offset + limit]) if offset < group_total else []
        selected_keys = [row["group_key"] for row in window]
        if selected_keys:
            if engine.uses_sql:
                ordered = engine._ordered(candidates).annotate(group_key=key)
                representatives = dict(ordered.annotate(
                    _group_position=Window(RowNumber(), partition_by=[key], order_by=ordered.query.order_by),
                ).filter(_group_position=1, group_key__in=selected_keys).values_list("group_key", "pk"))
            else:
                keys_by_id = dict(candidates.annotate(group_key=key).filter(group_key__in=selected_keys).values_list("pk", "group_key"))
                representatives = {}
                for item_id in engine.ranked_ids():
                    if item_id in keys_by_id:
                        representatives.setdefault(keys_by_id[item_id], item_id)
            for row in window:
                row["representative"] = representatives.get(row["group_key"], row["representative"])
        items = Item.objects.in_bulk(row["representative"] for row in window)
        group_metadata = {group_key: {"genres": [], "platforms": []} for group_key in selected_keys}
        for group_key, genres, platforms in candidates.annotate(group_key=key).filter(group_key__in=selected_keys).values_list("group_key", "genres", "platforms").iterator(chunk_size=256):
            for name, values in (("genres", genres), ("platforms", platforms)):
                for value in values or []:
                    if value not in group_metadata[group_key][name]:
                        group_metadata[group_key][name].append(value)
        results = []
        for row in window:
            item = copy(items[row["representative"]])
            item.title, item.original_title, item.localized_title = row["name"] or row["group_key"], "", ""
            years = [str(value.year) for value in (row["first_release"], row["last_release"]) if value]
            item.display_release_year = "-".join(dict.fromkeys(years)) or None
            item.release_datetime = None
            item.synopsis = ""
            item.genres = group_metadata[row["group_key"]]["genres"]
            item.platforms = group_metadata[row["group_key"]]["platforms"]
            media = SimpleNamespace(
                item=item, card_tile_url="group", aggregated_score=row["score"], score=row["score"],
                progress=row["progress"] or 0, aggregated_progress=row["progress"] or 0,
                max_progress=None, repeats=0, play_count=0, status="", aggregated_status="",
                aggregated_created_at=row["first_added"], aggregated_start_date=row["first_started"],
                aggregated_end_date=row["last_ended"], last_played_at=row["last_ended"],
            )
            context = card_context({"user": request.user, "request": request}, "group", {
                "item": item, "media": media, "card_media_type": "game", "current_sort": filters.sort,
            })
            results.append({"group": {**row, "image": item.image, "card": card_model(context)}})
        ungrouped_filters = replace(filters, group="__ungrouped__")
        remaining = limit - len(results)
        entries, ungrouped_total = get_media_list_entries(
            request.user, "game", ungrouped_filters, limit=max(0, remaining), offset=max(0, offset - group_total),
        )
        results.extend(
            MediaSerializer(entry.media, context={"request": request}).data if entry.media is not None
            else UntrackedMediaSerializer(entry.item, context={"request": request}).data
            for entry in entries
        )
        return Response({"pagination": {"total": group_total + ungrouped_total, "limit": limit, "offset": offset}, "results": results})


def _web_query_pairs(query):
    """Spread the API's comma-joined values back into the web's repeated parameters."""
    pairs = []
    for key, value in (query or {}).items():
        if key in {"limit", "offset", "media_type", "name", "csrfmiddlewaretoken"} or value in (None, ""):
            continue
        if key in _MULTI_QUERY_KEYS:
            pairs.extend((key, part) for part in str(value).split(",") if part)
        else:
            pairs.append((key, str(value)))
    return pairs


class LibrarySavedViewsView(drf_views.APIView):
    """Named media-list views (the sidebar's saved views)."""

    @extend_schema(operation_id="createLibrarySavedView", request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        """Save {mediaType, name, query} like the web "Save View" action."""
        from users.models import SavedView
        from users.views import _saved_view_query

        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        media_type = str(request.data.get("mediaType") or "")
        if media_type not in request.user.get_sidebar_media_types():
            return Response({"detail": "Invalid media type."}, status=HTTP.BAD_REQUEST)
        name = str(request.data.get("name") or "").strip()[:100]
        if not name:
            return Response({"detail": "Give the view a name."}, status=HTTP.BAD_REQUEST)
        last = SavedView.objects.filter(user=request.user, media_type=media_type).order_by("-position").first()
        saved = SavedView.objects.create(
            user=request.user,
            media_type=media_type,
            name=name,
            query=_saved_view_query(QueryDict(urlencode(_web_query_pairs(request.data.get("query"))))),
            position=last.position + 1 if last else 0,
        )
        return Response(_saved_view_payload(saved), status=HTTP.CREATED)


class LibrarySavedViewDetailView(drf_views.APIView):
    """Delete one saved view."""

    @extend_schema(operation_id="deleteLibrarySavedView", responses={204: None})
    def delete(self, request, view_id):
        """Remove the caller's saved view (a no-op for demo accounts, like the web)."""
        from users.models import SavedView

        saved = SavedView.objects.filter(id=view_id, user=request.user).first()
        if saved is None:
            return Response({"detail": "Saved view not found."}, status=HTTP.NOT_FOUND)
        if not request.user.is_demo:
            saved.delete()
        return Response(status=HTTP.NO_CONTENT)


class LibraryShareView(drf_views.APIView):
    """Public smart list snapshotting the current view (the web "Share View")."""

    @extend_schema(operation_id="shareLibraryView", request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Create or reuse the public list for {mediaType, query}; returns its URL."""
        media_type = str(request.data.get("mediaType") or "")
        if media_type not in MediaTypes.values:
            return Response({"detail": "Invalid media type."}, status=HTTP.BAD_REQUEST)
        pairs = [*_web_query_pairs(request.data.get("query")), ("media_type", media_type)]
        status_code, body = _call_web_view(
            views_list_actions.share_view, request, {key: [v for k, v in pairs if k == key] for key, _ in pairs},
        )
        if status_code >= HTTP.BAD_REQUEST or not body.get("url"):
            return Response({"detail": "The view could not be shared."}, status=HTTP.BAD_REQUEST)
        return Response({"url": body["url"]})
