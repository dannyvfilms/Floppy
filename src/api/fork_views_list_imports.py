# FORK: JSON endpoints for list imports (Trakt, MDBList, CSV) and CSV export,
# for clients that cannot post the web's HTML forms. Each view reuses the web
# view's services and Celery tasks. URL wiring lives in fork_urls.py.
import logging
from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.redis_diagnosis import queue_failure_message
from integrations import exports
from integrations.imports import helpers as import_helpers
from integrations.imports import trakt as trakt_imports
from integrations.models import MDBListAccount, TraktAccount
from integrations.upload_staging import (
    enqueue_staged_task,
    stage_uploaded_file,
    staging_failure_message,
)
from lists import tasks as list_tasks
from lists.imports import mdblist as mdblist_imports
from lists.models import CustomList
from lists.views_helpers import _get_trakt_credentials
from lists.views_mdblist import FREQUENCY_CRONTABS, _ensure_mdblist_schedule

logger = logging.getLogger(__name__)

_OBJ_READ = extend_schema(responses={200: OpenApiTypes.OBJECT})
_OBJ_WRITE = extend_schema(
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT},
)

MAX_CSV_BYTES = 10 * 1024 * 1024
_DEVICE_KEY = "api_trakt_lists_device:{user_id}"


def _bad_request(detail):
    return Response({"detail": detail}, status=HTTP.BAD_REQUEST)


# /api/v1/lists/import/
class ListImportStatusView(drf_views.APIView):
    """What the caller has connected for list imports."""

    @_OBJ_READ
    def get(self, request):
        """Return the Trakt and MDBList connection state."""
        trakt = TraktAccount.objects.filter(user=request.user).first()
        mdblist = MDBListAccount.objects.filter(user=request.user).first()
        return Response(
            {
                "trakt": {
                    "has_credentials": bool(trakt and trakt.is_configured),
                },
                "mdblist": {
                    "connected": mdblist is not None,
                    "sync_frequency": mdblist.sync_frequency if mdblist else None,
                    "frequency_choices": [
                        {"value": value, "label": str(label)}
                        for value, label in MDBListAccount.SYNC_FREQUENCY_CHOICES
                    ],
                    "default_frequency": MDBListAccount._meta.get_field("sync_frequency").default,
                    "connection_broken": bool(mdblist and mdblist.connection_broken),
                    "last_error_message": (
                        mdblist.last_error_message if mdblist else ""
                    ),
                },
            },
            status=HTTP.OK,
        )


# /api/v1/lists/import/csv/
class ListImportCsvView(drf_views.APIView):
    """Queue a single-list CSV import from uploaded text or a file."""

    @_OBJ_WRITE
    def post(self, request):
        """Accept `csv_file` (multipart) or `text` (JSON) and queue the import."""
        upload = request.FILES.get("csv_file")
        if upload is None:
            text = request.data.get("text")
            if not isinstance(text, str) or not text.strip():
                return _bad_request("Select a CSV file to import.")
            data = text.encode("utf-8")
            if len(data) > MAX_CSV_BYTES:
                return _bad_request("The CSV file is too large.")
            upload = ContentFile(data, name="list.csv")
        if upload.size > MAX_CSV_BYTES:
            return _bad_request("The CSV file is too large.")
        try:
            staged_file = str(stage_uploaded_file(upload))
        except OSError as error:
            logger.exception("Could not stage custom list CSV upload")
            return Response(
                {"detail": staging_failure_message(error)},
                status=HTTP.SERVICE_UNAVAILABLE,
            )
        try:
            enqueue_staged_task(
                list_tasks.import_list_csv_task,
                request.user.id,
                staged_file,
                "new",
                staged_paths=(staged_file,),
            )
        except Exception as error:
            logger.exception("Could not queue custom list CSV import")
            return Response(
                {
                    "detail": queue_failure_message(
                        error,
                        "The list import could not be queued.",
                        "Try again.",
                        settings.CELERY_BROKER_URL,
                    ),
                },
                status=HTTP.SERVICE_UNAVAILABLE,
            )
        return Response({"detail": "List import started in the background."}, status=HTTP.ACCEPTED)


# /api/v1/lists/import/mdblist/
class ListImportMdblistView(drf_views.APIView):
    """Connect MDBList, import one list by reference, sync now, or disconnect."""

    @_OBJ_WRITE
    def post(self, request):
        """Act on `action`: connect (default), import, sync or disconnect."""
        action = str(request.data.get("action") or "connect")
        account = MDBListAccount.objects.filter(user=request.user).first()
        if action == "connect":
            return self._connect(request)
        if action == "disconnect":
            from lists.views_mdblist import _remove_mdblist_schedule

            _remove_mdblist_schedule(request.user)
            MDBListAccount.objects.filter(user=request.user).delete()
            return Response({"detail": "MDBList disconnected."}, status=HTTP.OK)
        if account is None:
            return _bad_request("Connect your MDBList account first.")
        if action == "import":
            reference = str(request.data.get("list_reference") or "").strip()
            if not reference:
                return _bad_request("Provide an MDBList list URL or ID.")
            list_tasks.import_mdblist_list_by_reference_task.delay(
                request.user.id,
                reference,
            )
            return Response(
                {"detail": "MDBList list import started in the background."},
                status=HTTP.ACCEPTED,
            )
        if action == "sync":
            if account.connection_broken:
                account.connection_broken = False
                account.last_error_message = ""
                account.save(update_fields=["connection_broken", "last_error_message"])
            _ensure_mdblist_schedule(request.user, account)
            list_tasks.import_mdblist_lists_task.delay(request.user.id)
            return Response(
                {"detail": "MDBList sync started in the background."},
                status=HTTP.ACCEPTED,
            )
        return _bad_request("Unknown action.")

    def _connect(self, request):
        api_key = str(request.data.get("api_key") or "").strip()
        frequency = str(request.data.get("sync_frequency") or "24h")
        if frequency not in FREQUENCY_CRONTABS:
            frequency = "24h"
        if not api_key:
            return _bad_request("An MDBList API key is required.")
        try:
            mdblist_imports.validate_api_key(api_key)
        except import_helpers.MediaImportError:
            return _bad_request(
                "Could not validate the MDBList API key. Check it and try again.",
            )
        account, _ = MDBListAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "api_key": import_helpers.encrypt(api_key),
                "sync_frequency": frequency,
                "connection_broken": False,
                "last_error_message": "",
            },
        )
        _ensure_mdblist_schedule(request.user, account)
        list_tasks.import_mdblist_lists_task.delay(request.user.id)
        return Response(
            {"detail": "MDBList connected. Your lists are being imported."},
            status=HTTP.ACCEPTED,
        )


# /api/v1/lists/import/trakt/
class ListImportTraktView(drf_views.APIView):
    """Trakt list import through the device-code flow (no redirect URI needed)."""

    @_OBJ_WRITE
    def post(self, request):
        """Act on `action`: credentials, start or poll."""
        action = str(request.data.get("action") or "")
        if action == "credentials":
            return self._credentials(request)
        if action == "start":
            return self._start(request)
        if action == "poll":
            return self._poll(request)
        return _bad_request("Unknown action.")

    def _credentials(self, request):
        client_id = str(request.data.get("client_id") or "").strip()
        client_secret = str(request.data.get("client_secret") or "").strip()
        if not client_id:
            return _bad_request("Trakt client ID is required.")
        TraktAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "client_id": import_helpers.encrypt(client_id),
                "client_secret": (
                    import_helpers.encrypt(client_secret) if client_secret else None
                ),
            },
        )
        return Response({"detail": "Trakt credentials saved."}, status=HTTP.OK)

    def _start(self, request):
        credentials = _get_trakt_credentials(request.user)
        if not credentials:
            return _bad_request("Add your Trakt client ID before authorizing.")
        try:
            device = trakt_imports.request_device_code(client_id=credentials[0])
        except import_helpers.MediaImportError as error:
            return _bad_request(str(error))
        expires_in = int(device["expires_in"])
        cache.set(
            _DEVICE_KEY.format(user_id=request.user.id),
            {
                "device_code": device["device_code"],
                "expires_at": (
                    timezone.now() + timedelta(seconds=expires_in)
                ).isoformat(),
            },
            timeout=expires_in,
        )
        return Response(
            {
                "user_code": device["user_code"],
                "verification_url": device["verification_url"],
                "interval": device["interval"],
                "expires_in": expires_in,
            },
            status=HTTP.OK,
        )

    def _poll(self, request):
        state = cache.get(_DEVICE_KEY.format(user_id=request.user.id))
        credentials = _get_trakt_credentials(request.user)
        if not state or not credentials:
            return _bad_request("The Trakt authorization code expired. Start again.")
        client_id, client_secret = credentials
        try:
            result = trakt_imports.poll_device_token(
                state["device_code"],
                client_id=client_id,
                client_secret=client_secret,
            )
        except import_helpers.MediaImportError as error:
            cache.delete(_DEVICE_KEY.format(user_id=request.user.id))
            return _bad_request(str(error))
        if result is None:
            return Response({"status": "pending"}, status=HTTP.OK)
        cache.delete(_DEVICE_KEY.format(user_id=request.user.id))
        list_tasks.import_trakt_lists_task.delay(
            request.user.id,
            result["access_token"],
            client_id=client_id,
        )
        return Response(
            {
                "status": "authorized",
                "detail": "Trakt authorization successful. Your lists are being imported.",
            },
            status=HTTP.ACCEPTED,
        )


# /api/v1/lists/[list_id]/export/
class ListExportCsvView(drf_views.APIView):
    """A list's contents as CSV text, for clients that save the file themselves."""

    @_OBJ_READ
    def get(self, request, list_id):
        """Return `{filename, content}` for a list the caller can view."""
        from django.utils.text import slugify

        custom_list = CustomList.objects.filter(id=list_id).first()
        if custom_list is None or not custom_list.user_can_view(request.user):
            return Response({"detail": "List not found."}, status=HTTP.NOT_FOUND)
        return Response(
            {
                "filename": f"{slugify(custom_list.name) or 'list'}.csv",
                "content": "".join(exports.generate_list_csv(custom_list)),
            },
            status=HTTP.OK,
        )
