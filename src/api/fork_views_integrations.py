# FORK: import/export endpoints mirroring the web import-data page's
# one-off import dispatches, CSV export, and import activity.
# OAuth-based connects (Trakt/Plex/SIMKL/AniList-private) stay web-only.
# URL wiring lives in fork_urls.py.
import logging
from functools import partial
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from django.http import HttpResponse, QueryDict, StreamingHttpResponse
from django.template.defaultfilters import timesince
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from app.log_safety import redact_secrets
from app.redis_diagnosis import queue_failure_message
from integrations import exports, tasks
from integrations.imports import helpers as import_helpers
from integrations.upload_staging import (
    enqueue_staged_task,
    stage_uploaded_file,
    staging_failure_message,
)
from users.models import ImportModeChoices

logger = logging.getLogger(__name__)

# Username-driven imports: service -> (task export, identifier label).
# Resolve the task only when this endpoint is used so URL loading does not
# import every provider implementation into each Gunicorn worker.
_USERNAME_IMPORTS = {
    "mal": ("import_mal", "MyAnimeList username"),
    "anilist": ("import_anilist", "AniList username"),
    "kitsu": ("import_kitsu", "Kitsu user ID"),
    "steam": ("import_steam", "Steam ID"),
}

# Token-driven imports: service -> (task export, credential label). These have
# no public username to read, so the credential is the only way in, and it is
# encrypted before it reaches the broker.
_TOKEN_IMPORTS = {
    "mangabaka": ("import_mangabaka", "MangaBaka API token"),
}

# File-driven imports: service -> (task export, file label).
_FILE_IMPORTS = {
    # Service key stays "yamtrack": it is a public API parameter value.
    "yamtrack": ("import_yamtrack", "Floppy backup or Yamtrack CSV"),
    "trakt-collection": ("import_trakt_collection_csv", "Trakt collection CSV"),
    "trakt-export": ("import_trakt_export", "Trakt data export zip"),
    "hltb": ("import_hltb", "HowLongToBeat CSV"),
    "playnite": ("import_playnite", "Playnite CSV"),
    "grouvee": ("import_grouvee", "Grouvee export (JSON or zip)"),
    "imdb": ("import_imdb", "IMDB CSV"),
    "goodreads": ("import_goodreads", "Goodreads CSV"),
    "hardcover": ("import_hardcover", "Hardcover CSV"),
    "storygraph": ("import_storygraph", "StoryGraph CSV"),
    "youtube-takeout": (
        "import_youtube_takeout",
        "YouTube Takeout watch history (JSON or zip)",
    ),
}


def _resolve_mode(request):
    """Validate the import mode (defaults to the user's preference)."""
    mode = request.data.get("mode") or request.user.import_mode
    if mode not in ImportModeChoices.values:
        return None
    return mode


def _queue_failure_response(error):
    """Return 503 naming an unreachable Redis broker rather than a bare 500."""
    detail = queue_failure_message(
        error,
        "The import could not be queued.",
        "",
        settings.CELERY_BROKER_URL,
    )
    return Response({"detail": detail}, status=HTTP.SERVICE_UNAVAILABLE)


# /api/v1/imports/[service]/
class ImportDispatchView(drf_views.APIView):
    """Queue a one-off import for a service (mirrors the web import forms).

    Username services (mal, anilist, kitsu, steam) take {"username", "mode"}.
    Token services (mangabaka) take {"token", "mode"} and never a username.
    File services (yamtrack, trakt-collection, trakt-export, hltb, grouvee,
    imdb, goodreads, hardcover, storygraph, youtube-takeout) take a multipart upload in the
    "file" field plus an optional "mode". Returns 202 with a task_id pollable at
    /api/v1/tasks/{task_id}. Recurring schedules stay web-only.
    """

    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, service):
        """Dispatch the import task for the service."""
        mode = _resolve_mode(request)
        if mode is None:
            return Response(
                {
                    "detail": "Invalid mode.",
                    "choices": list(ImportModeChoices.values),
                },
                status=HTTP.BAD_REQUEST,
            )

        if service == "trakt-export" and mode not in import_helpers.TRAKT_EXPORT_MODES:
            return Response(
                {
                    "detail": import_helpers.TRAKT_EXPORT_UNSUPPORTED_MODE_MESSAGE,
                    "choices": list(import_helpers.TRAKT_EXPORT_MODES),
                },
                status=HTTP.BAD_REQUEST,
            )

        if service in _USERNAME_IMPORTS:
            task_export, label = _USERNAME_IMPORTS[service]
            task_fn = getattr(tasks, task_export)
            username = (str(request.data.get("username") or "")).strip()
            if not username:
                return Response(
                    {"detail": f"{label} is required in 'username'."},
                    status=HTTP.BAD_REQUEST,
                )
            try:
                task = task_fn.delay(
                    username=username,
                    user_id=request.user.id,
                    mode=mode,
                )
            except Exception as error:
                logger.exception("Could not queue %s import", label)
                return _queue_failure_response(error)
            return Response({"task_id": task.id}, status=HTTP.ACCEPTED)

        if service in _TOKEN_IMPORTS:
            task_export, label = _TOKEN_IMPORTS[service]
            task_fn = getattr(tasks, task_export)
            token = (str(request.data.get("token") or "")).strip()
            if not token:
                return Response(
                    {"detail": f"{label} is required in 'token'."},
                    status=HTTP.BAD_REQUEST,
                )
            task = task_fn.delay(
                token=import_helpers.encrypt(token),
                user_id=request.user.id,
                mode=mode,
            )
            return Response({"task_id": task.id}, status=HTTP.ACCEPTED)

        if service in _FILE_IMPORTS:
            task_export, label = _FILE_IMPORTS[service]
            task_fn = getattr(tasks, task_export)
            file = request.FILES.get("file")
            if not file:
                return Response(
                    {"detail": f"{label} upload is required in 'file'."},
                    status=HTTP.BAD_REQUEST,
                )
            try:
                staged_file = str(stage_uploaded_file(file))
            except OSError as error:
                logger.exception("Could not stage %s upload", label)
                return Response(
                    {"detail": staging_failure_message(error)},
                    status=HTTP.INSUFFICIENT_STORAGE,
                )
            try:
                task = enqueue_staged_task(
                    task_fn,
                    user_id=request.user.id,
                    file=staged_file,
                    mode=mode,
                    staged_paths=(staged_file,),
                )
            except Exception as error:
                logger.exception("Could not queue %s upload", label)
                return _queue_failure_response(error)
            return Response({"task_id": task.id}, status=HTTP.ACCEPTED)

        return Response(
            {
                "detail": "Unknown import service.",
                "services": sorted(
                    [*_USERNAME_IMPORTS, *_TOKEN_IMPORTS, *_FILE_IMPORTS],
                ),
            },
            status=HTTP.NOT_FOUND,
        )


# /api/v1/imports/activity/
class ImportActivityView(drf_views.APIView):
    """Recent import task history (mirrors the web import activity panel)."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the user's recent import task results and schedules."""
        from integrations.oauth_scope_info import has_full_account_access
        from users import provider_ui
        from users import views as user_views

        try:
            page = max(1, min(int(request.query_params.get("page", 1)), provider_ui.MAX_ACTIVITY_PAGES))
        except (ValueError, TypeError):
            page = 1
        data = request.user.get_import_tasks(result_limit=provider_ui.ACTIVITY_PAGE_SIZE + 1, result_offset=(page - 1) * provider_ui.ACTIVITY_PAGE_SIZE)
        results = [
            {
                "source": entry.get("source"),
                "status": entry.get("status"),
                "date": entry.get("date"),
                "summary": entry.get("summary"),
                "errors": entry.get("errors"),
            }
            for entry in data.get("results", [])[:provider_ui.ACTIVITY_PAGE_SIZE]
        ]
        schedules = [
            {
                "source": entry.get("source"),
                "username": entry.get("username"),
                "last_run": entry.get("last_run"),
                "next_run": entry.get("next_run"),
                "schedule": entry.get("schedule"),
                "mode": entry.get("mode"),
            }
            for entry in data.get("schedules", [])
        ]
        payload = {"results": results, "schedules": schedules,
                   "presentation": provider_ui.anilist_activity(request.user, page, all_sources=True, activity=data)}
        # Tracker state has the same full-account boundary as provider pages;
        # imports:read tokens retain their established import-only response.
        if not hasattr(request.auth, "has_scope") or has_full_account_access(request.auth):
            context = user_views.mal_export_context(request._request)
            account = context.get("mal_account")
            report = context["mal_sync_initial"]
            if report:
                report = {**report, **{key: [
                    {**row, "reason": redact_secrets(str(row.get("reason") or ""))} for row in report.get(key, [])
                ] for key in ("results", "mapping_issues")}}
            services = []
            for service in context["outbound_services"]:
                state = context["tmdb_rating_sync" if service["slug"] == "tmdb" else "wetrakr_sync"]
                services.append({
                    "slug": service["slug"], "state": service["state"], "counts": state["counts"],
                    "last_flushed_at": getattr(state.get("binding"), "last_flushed_at", None),
                    "last_sent_label": str(timesince(state["binding"].last_flushed_at)) + " ago"
                        if state.get("binding") and state["binding"].last_flushed_at else "",
                    "recent": [{"id": row.pk, "title": str(row.item),
                                "operation": row.get_operation_display(), "status": row.get_status_display(),
                                "error": redact_secrets(row.last_error_message)} for row in state["recent"]],
                })
            payload["tracker_activity"] = {
                "mal": {"connected": bool(account and account.is_connected),
                        "sync_enabled": bool(account and account.sync_enabled),
                        "report": report,
                        "ignored": context["mal_ignored_mappings"], "manual": context["mal_manual_mappings"]},
                "services": services,
                "actions": {name: reverse(name) for name in (
                    "mal_mapping_ignore", "mal_episode_mapping_save", "mal_episode_mapping_revert",
                    "mal_full_sync_retry_failed", "mal_full_sync_preview", "mal_mapping_search", "mal_mapping_episodes",
                )},
            }
        return Response(payload, status=HTTP.OK)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Delegate only existing activity actions, with their ownership checks."""
        from api.fork_views_providers import _call, _demo_blocked

        body = request.data if isinstance(request.data, dict) else {}
        path = str(body.get("path") or "")
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            return Response({"detail": "Choose a valid activity action."}, status=HTTP.BAD_REQUEST)
        try:
            match = resolve(path)
        except Resolver404:
            return Response({"detail": "Choose a valid activity action."}, status=HTTP.BAD_REQUEST)
        if match.url_name not in {
            "delete_import_schedule", "cancel_pending_import", "cancel_import_run", "rollback_import_run",
            "bulk_delete_by_import_source", "mal_mapping_ignore", "mal_episode_mapping_save",
            "mal_episode_mapping_revert", "mal_full_sync_retry_failed",
            "mal_mapping_search", "mal_mapping_episodes", "mal_full_sync_preview",
        }:
            return Response({"detail": "Choose a valid activity action."}, status=HTTP.BAD_REQUEST)
        denied = _demo_blocked(request, match.url_name)
        if denied:
            return denied
        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        read = match.url_name in {"mal_mapping_search", "mal_mapping_episodes"} or (
            match.url_name == "mal_full_sync_preview" and values.get("token")
        )
        if read:
            query = QueryDict(mutable=True)
            query.update(values)
            request._request.GET = query
        return _call(request, partial(match.func, **match.kwargs), *match.args, post=None if read else values,
                     method="GET" if read else "POST")


# /api/v1/export/csv/
class ExportCsvView(drf_views.APIView):
    """Stream the user's library as CSV (mirrors the web export)."""

    def get(self, request):
        """Stream the CSV backup.

        Query params: media_types (repeatable) to restrict types,
        include_lists=0 to skip custom lists, include_collection=0 to skip
        collection entries, only=collection for a collection-only export.
        """
        selected_media_types = request.GET.getlist("media_types")
        include_lists = request.GET.get("include_lists", "1") not in ("0", "false")
        include_collection = request.GET.get("include_collection", "1") not in (
            "0",
            "false",
        )
        media_types = selected_media_types or None

        if request.GET.get("only") == "collection":
            media_types = []
            include_lists = False
            include_collection = True

        now = timezone.localtime()
        response = StreamingHttpResponse(
            streaming_content=exports.generate_rows(
                request.user,
                media_types=media_types,
                include_lists=include_lists,
                include_collection=include_collection,
            ),
            content_type="text/csv",
            headers={
                "Content-Disposition": (f'attachment; filename="floppy_{now}.csv"'),
            },
        )
        logger.info("User %s started CSV export via API", request.user.username)
        return response


# /api/v1/export/template/
class ExportTemplateView(drf_views.APIView):
    """Download the sample import-template CSV."""

    def get(self, _request):
        """Return the template CSV content."""
        content = exports.generate_sample_template()
        response = HttpResponse(content, content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="floppy_import_template.csv"'
        )
        return response
