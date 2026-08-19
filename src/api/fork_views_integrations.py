# FORK: import/export endpoints mirroring the web import-data page's
# one-off import dispatches, CSV export, and import activity.
# OAuth-based connects (Trakt/Plex/SIMKL/AniList-private) stay web-only.
# URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import views as drf_views
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from integrations import exports, tasks
from integrations.views import _read_uploaded_file
from users.models import ImportModeChoices

logger = logging.getLogger(__name__)

# Username-driven imports: service -> (task, identifier label).
_USERNAME_IMPORTS = {
    "mal": (tasks.import_mal, "MyAnimeList username"),
    "anilist": (tasks.import_anilist, "AniList username"),
    "kitsu": (tasks.import_kitsu, "Kitsu user ID"),
    "steam": (tasks.import_steam, "Steam ID"),
}

# File-driven imports: service -> (task, file label).
_FILE_IMPORTS = {
    # Service key stays "yamtrack": it is a public API parameter value.
    "yamtrack": (tasks.import_yamtrack, "Floppy backup or Yamtrack CSV"),
    "trakt-collection": (tasks.import_trakt_collection_csv, "Trakt collection CSV"),
    "trakt-export": (tasks.import_trakt_export, "Trakt data export zip"),
    "hltb": (tasks.import_hltb, "HowLongToBeat CSV"),
    "grouvee": (tasks.import_grouvee, "Grouvee JSON"),
    "imdb": (tasks.import_imdb, "IMDB CSV"),
    "goodreads": (tasks.import_goodreads, "Goodreads CSV"),
    "hardcover": (tasks.import_hardcover, "Hardcover CSV"),
    "storygraph": (tasks.import_storygraph, "StoryGraph CSV"),
}


def _resolve_mode(request):
    """Validate the import mode (defaults to the user's preference)."""
    mode = request.data.get("mode") or request.user.import_mode
    if mode not in ImportModeChoices.values:
        return None
    return mode


# /api/v1/imports/[service]/
class ImportDispatchView(drf_views.APIView):
    """Queue a one-off import for a service (mirrors the web import forms).

    Username services (mal, anilist, kitsu, steam) take {"username", "mode"}.
    File services (yamtrack, trakt-collection, trakt-export, hltb, grouvee,
    imdb, goodreads, hardcover, storygraph) take a multipart upload in the
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

        if service in _USERNAME_IMPORTS:
            task_fn, label = _USERNAME_IMPORTS[service]
            username = (str(request.data.get("username") or "")).strip()
            if not username:
                return Response(
                    {"detail": f"{label} is required in 'username'."},
                    status=HTTP.BAD_REQUEST,
                )
            task = task_fn.delay(
                username=username,
                user_id=request.user.id,
                mode=mode,
            )
            return Response({"task_id": task.id}, status=HTTP.ACCEPTED)

        if service in _FILE_IMPORTS:
            task_fn, label = _FILE_IMPORTS[service]
            file = request.FILES.get("file")
            if not file:
                return Response(
                    {"detail": f"{label} upload is required in 'file'."},
                    status=HTTP.BAD_REQUEST,
                )
            task = task_fn.delay(
                user_id=request.user.id,
                file=_read_uploaded_file(file),
                mode=mode,
            )
            return Response({"task_id": task.id}, status=HTTP.ACCEPTED)

        return Response(
            {
                "detail": "Unknown import service.",
                "services": sorted([*_USERNAME_IMPORTS, *_FILE_IMPORTS]),
            },
            status=HTTP.NOT_FOUND,
        )


# /api/v1/imports/activity/
class ImportActivityView(drf_views.APIView):
    """Recent import task history (mirrors the web import activity panel)."""

    def get(self, request):
        """Return the user's recent import task results and schedules."""
        data = request.user.get_import_tasks()
        results = [
            {
                "source": entry.get("source"),
                "status": entry.get("status"),
                "date": entry.get("date"),
                "summary": entry.get("summary"),
                "errors": entry.get("errors"),
            }
            for entry in data.get("results", [])
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
        return Response(
            {"results": results, "schedules": schedules},
            status=HTTP.OK,
        )


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
