# FORK: provider directory, provider detail and the connection, sync-direction,
# device-approval and match-review endpoints for the native app. The web
# session views stay the single owner of the business logic: the directory and
# detail endpoints reuse their view models, and every write is delegated to the
# existing session view through ``_delegate``. Stored provider secret fields
# are not returned. Ordinary configuration permits legacy and first-party
# full-access tokens; credential-bearing guides and device approval require
# session authentication. Scoped integration tokens cannot pass NEVER routes.
# URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied
from django.http import QueryDict
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

from api.fork_views_settings import _delegate, _demo_denied, _json_body
from api.helpers import body_too_large_response
from app import helpers as app_helpers
from app.log_safety import redact_secrets

logger = logging.getLogger(__name__)

# Providers whose account is linked through a browser or device-code hand-off.
# Their state lives in the web session, so native opens the provider page.
BROWSER_HANDOFF = frozenset({"plex", "trakt", "simkl", "mal", "anilist", "wetrakr", "tmdb", "storyteller"})
# Providers whose connection a saved account can re-probe.
TESTABLE = frozenset({"jellyfin", "radarr", "sonarr", "mylar", "kapowarr"})
# Providers whose "Sync now" posts only saved-account parameters on the web.
SYNC_NOW = frozenset({
    "audiobookshelf", "radarr", "sonarr", "mylar", "kapowarr", "stremio", "storyteller", "koreader",
    "pocketcasts", "gpodder", "xbox", "psn", "lastfm", "koito",
})
# Providers whose web "Sync now" posts to a route not named ``import_<slug>``.
SYNC_ROUTES = {"lastfm": "poll_lastfm_manual", "koito": "poll_koito_manual"}
# Username-driven imports and schedules: provider slug -> web import route.
IMPORT_ROUTES = {
    "mal": "import_mal",
    "kitsu": "import_kitsu",
    "steam": "import_steam",
    "anilist": "import_anilist_public",
}
_HIDDEN_KEYS = frozenset({"csrf", "next", "pinUrl", "setupUrl", "saveUrl", "clearUrl", "personalUrl"})


def _clean(value):
    """Make a view model JSON-safe and drop browser-only keys (CSRF, web URLs)."""
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if key not in _HIDDEN_KEYS}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_clean(item) for item in value)
    return value


def _call(request, view, *args, post=None, method="POST"):
    """Run a session view and always answer with a DRF Response."""
    response = _delegate(request, view, *args, post=post, method=method)
    if isinstance(response, Response):
        return response
    status = response.status_code
    if status == HTTP.FORBIDDEN:
        return Response({"detail": "Permission denied."}, status=status)
    if status == HTTP.NOT_FOUND:
        return Response({"detail": "Not found."}, status=status)
    if status >= HTTP.BAD_REQUEST:
        return Response({"detail": "Request failed."}, status=status)
    return Response({"ok": True, "messages": []}, status=HTTP.OK)


def _demo_blocked(request, url_name):
    """Refuse what DemoAccountGuardMiddleware refuses for the web route name.

    The middleware matches web URL names, so an API route that delegates to a
    guarded session view must apply the same set itself.
    """
    from app.middleware import DemoAccountGuardMiddleware

    if url_name in DemoAccountGuardMiddleware.BLOCKED_ROUTES:
        return _demo_denied(request.user)
    return None


def _view_for(name):
    try:
        return resolve(reverse(name)).func
    except NoReverseMatch:
        return None


def _catalog_item(slug):
    from users.provider_catalog import catalog

    return next((item for item in catalog() if item["slug"] == slug), None)


def _status(state):
    return {"label": state["connection"], "tone": state["connection_tone"]}


# /api/v1/providers/
class ProvidersView(drf_views.APIView):
    """The provider directory: the shared directory model plus connection state."""

    @extend_schema(operation_id="listProviders", responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the filtered directory with every provider's connection status."""
        from users import provider_views
        from users.provider_catalog import catalog, provider_state

        django_request = request._request
        query = QueryDict(mutable=True)
        for key in ("q", "capability", "media"):
            if request.query_params.get(key):
                query[key] = request.query_params[key]
        query["format"] = "json"
        django_request.GET = query
        response = provider_views.providers(django_request)
        import json

        model = json.loads(response.content)
        by_slug = {item["slug"]: item for item in catalog()}
        for row in model["items"]:
            item = by_slug.get(row["slug"])
            if item is not None:
                row["status"] = _status(provider_state(item, request.user))
            row.pop("url", None)
        return Response(_clean(model), status=HTTP.OK)


# /api/v1/providers/pin/
class ProviderPinView(drf_views.APIView):
    """Pin or unpin a provider in the directory."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Body: {"provider": slug, "pinned": bool}."""
        from users import provider_views

        body = _json_body(request)
        return _call(
            request,
            provider_views.pin_provider,
            post={"provider": body.get("provider"), "pinned": "1" if body.get("pinned") else "0"},
        )


def _import_tasks(user, slug):
    from users.provider_catalog import activity_sources

    return user.get_import_tasks(sources=activity_sources(slug), refresh_results=False)


def _schedule_rows(user, slug):
    data = _import_tasks(user, slug)
    return [
        {
            "task_name": entry["task"].name if entry.get("task") else "",
            "source": entry.get("source"),
            "username": entry.get("username"),
            "last_run": entry.get("last_run"),
            "next_run": entry.get("next_run"),
            "frequency": entry.get("schedule"),
            "mode": entry.get("mode"),
        }
        for entry in data.get("schedules", [])
        if entry.get("task")
    ]


def _activity_rows(user, slug):
    data = _import_tasks(user, slug)
    return [
        {
            "source": entry.get("source"),
            "status": entry.get("status"),
            "date": entry.get("date"),
            "summary": redact_secrets(str(entry.get("summary") or "")),
        }
        for entry in data.get("results", [])[:20]
    ]


def _connection_block(slug, context, item, request):
    """Describe how the app connects this provider, without any saved secret."""
    connection = context.get("account_connection")
    web_url = app_helpers.build_absolute_app_url(
        request._request,
        reverse("provider_detail", args=[slug]) + "?tab=connection",
    )
    if slug in BROWSER_HANDOFF:
        mode = "browser"
    elif (connection and connection.get("fields")) or (
        {"koreader", "seerr_settings"} & set(context.get("provider_forms") or {})
    ):
        mode = "form"
    elif connection and connection.get("connectUrl"):
        mode = "browser"
    elif connection:
        mode = "none"
    else:
        mode = "browser" if item.get("connection") and not item.get("credential") else "none"
    return {
        "mode": mode,
        "browserUrl": web_url,
        "account": _clean(connection) if connection else None,
        "canLink": slug in BROWSER_HANDOFF,
        "canTest": slug in TESTABLE,
        "canSync": slug in SYNC_NOW,
        "canSchedule": slug in IMPORT_ROUTES,
    }


def _trakt_file_import(slug, page, context):
    """Trakt's export upload lives in the web import modal; describe it like the other file imports."""
    if slug != "trakt" or page.get("tab") != "import":
        return None
    from django.utils.translation import gettext as _

    preferences = context.get("import_preferences") or {}
    return {
        "values": preferences.get("values") or {},
        "description": _("Upload the .zip from a Trakt data export to import your history, ratings, watchlist, collection and lists. Individual .json files and the older .csv export also work. Importing lists replaces any lists previously imported from Trakt."),
        "selectLabel": _("Select Export File"),
        "fileField": "trakt_export",
        "accept": ".zip,.json,.csv",
        "binary": True,
        "mediaTypes": [],
        "postFields": [{"name": "mode", "key": "mode"}],
        "multiple": False,
        "autoSubmit": True,
        "submitLabel": _("Import"),
        "textFields": [],
        "note": "",
        "blockedLabel": _("This import mode is not supported by this provider."),
    }


# /api/v1/providers/<slug>/
class ProviderDetailView(drf_views.APIView):
    """One provider's page model: overview, connection, credentials, guides, import."""

    @extend_schema(operation_id="getProvider", responses={200: OpenApiTypes.OBJECT})
    def get(self, request, slug):
        """Return the shared provider view model for ?tab= (default overview)."""
        from users import provider_views

        item = _catalog_item(slug)
        if item is None:
            return Response({"detail": "Unknown provider."}, status=HTTP.NOT_FOUND)
        django_request = request._request
        django_request.provider_context_only = True
        context = provider_views.provider_detail(django_request, slug)
        page = context["provider_page"]
        copy_values = context.get("guide_copy") or {}
        # Webhook and addon URLs disclose permanent account/install credentials.
        # Keep ordinary provider configuration available without those guides.
        guides_session_required = bool(copy_values) and slug in {
            "plex", "jellyfin", "emby", "kodi", "seerr", "stremio",
        } and not isinstance(request.successful_authenticator, SessionAuthentication)
        payload = {
            "slug": slug,
            "page": _clean(page),
            "state": _clean(context["provider"]["state"]),
            "pinned": slug in (request.user.pinned_settings_providers or []),
            "capabilities": _clean(context.get("capability_rows") or []),
            "connection": _connection_block(slug, context, item, request),
            "credentials": _clean(context.get("credentials_model") or page.get("credentials")),
            "guides": [] if guides_session_required else _clean(context.get("setup_guides") or []),
            "guideCopy": {} if guides_session_required else _clean(copy_values),
            "guidesSessionRequired": guides_session_required,
            "forms": _clean(context.get("provider_forms") or {}),
            "importPreferences": _clean(context.get("import_preferences")),
            "fileImport": _clean(context.get("file_import") or _trakt_file_import(slug, page, context)),
            "accountImportAction": _clean(context.get("account_import_action")),
            "schedules": _schedule_rows(request.user, slug),
            "activity": _clean(_activity_rows(request.user, slug)),
            "readOnly": bool(request.user.is_demo),
        }
        return Response(payload, status=HTTP.OK)


# /api/v1/providers/<slug>/forms/<form_key>/
class ProviderFormView(drf_views.APIView):
    """Save one of the option forms the detail payload lists under ``forms``."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug, form_key):
        """Body: {"tab": str, "values": {field: value}}.

        The form model is rebuilt on the server, so only the action the page
        itself offers can be reached. Toggles follow the checkbox contract the
        session view reads: a key means on, no key means off.
        """
        from users import provider_views

        if _catalog_item(slug) is None:
            return Response({"detail": "Unknown provider."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        django_request = request._request
        django_request.provider_context_only = True
        query = QueryDict(mutable=True)
        query["tab"] = str(body.get("tab") or "overview")
        django_request.GET = query
        django_request.method = "GET"
        context = provider_views.provider_detail(django_request, slug)
        form = (context.get("provider_forms") or {}).get(form_key)
        if form is None:
            return Response({"detail": "Unknown form."}, status=HTTP.NOT_FOUND)
        post = {key: value for key, value in (form.get("hidden") or {}).items() if value is not None}
        for field in form["fields"]:
            name = field["name"]
            if field["type"] == "toggle":
                if values.get(name):
                    post[name] = field.get("onValue", "on")
            elif name in values and values[name] is not None:
                post[name] = values[name]
        post["next"] = form["next"]
        try:
            match = resolve(urlsplit(form["action"]).path)
        except Resolver404:
            return Response({"detail": "Unknown form."}, status=HTTP.BAD_REQUEST)
        denied = _demo_blocked(request, match.url_name)
        if denied:
            return denied
        return _call(request, match.func, post=post)


# Upper bound for one uploaded import file, decoded (the web has no explicit cap).
MAX_FILE_IMPORT_BYTES = 100 * 1024 * 1024
# Provider slug -> the file-import service key when they differ.
FILE_IMPORT_SERVICES = {"youtube": "youtube-takeout", "trakt": "trakt-export"}
# What each service accepts, matching the web file pickers (provider_ui.FILE_IMPORTS).
FILE_IMPORT_EXTENSIONS = {
    "yamtrack": (".csv",),
    "trakt-collection": (".csv",),
    "trakt-export": (".zip", ".json", ".csv"),
    "hltb": (".csv",),
    "playnite": (".csv",),
    "grouvee": (".json", ".zip"),
    "imdb": (".csv",),
    "goodreads": (".csv",),
    "hardcover": (".csv",),
    "storygraph": (".csv",),
    "youtube-takeout": (".json", ".html", ".zip"),
}


def _upload_bytes(body):
    """Return (bytes, None) from the request body, or (None, error Response)."""
    import base64
    import binascii

    encoded = body.get("contentBase64")
    if isinstance(encoded, str) and encoded:
        if len(encoded) > MAX_FILE_IMPORT_BYTES * 4 // 3 + 8:
            return None, Response({"detail": "This file is too large to import."}, status=HTTP.REQUEST_ENTITY_TOO_LARGE)
        try:
            return base64.b64decode(encoded, validate=True), None
        except (binascii.Error, ValueError):
            return None, Response({"detail": "The file could not be read."}, status=HTTP.BAD_REQUEST)
    text = body.get("content")
    if isinstance(text, str) and text.strip():
        return text.encode("utf-8"), None
    return b"", None


def _upload_error(name, data, service, label):
    """Validate size and type the way the web pickers do; None when the file is fine."""
    allowed = FILE_IMPORT_EXTENSIONS.get(service, (".csv",))
    lowered = str(name or "").lower()
    if not data:
        return Response({"detail": f"Choose a {label} file to import."}, status=HTTP.BAD_REQUEST)
    if len(data) > MAX_FILE_IMPORT_BYTES:
        return Response({"detail": "This file is too large to import."}, status=HTTP.REQUEST_ENTITY_TOO_LARGE)
    if not lowered.endswith(allowed):
        kinds = ", ".join(allowed)
        return Response({"detail": f"Choose a {kinds} file."}, status=HTTP.UNSUPPORTED_MEDIA_TYPE)
    if lowered.endswith(".zip"):
        if not data.startswith(b"PK\x03\x04"):
            return Response({"detail": "That file is not a valid zip."}, status=HTTP.UNSUPPORTED_MEDIA_TYPE)
    elif b"\x00" in data[:4096]:
        return Response({"detail": "That file is not a text file."}, status=HTTP.UNSUPPORTED_MEDIA_TYPE)
    return None


# /api/v1/providers/<slug>/file-import/
class ProviderFileImportView(drf_views.APIView):
    """Queue a file import (CSV, JSON or zip) sent as JSON, for clients without multipart."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={202: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: {"name", "content" (text) or "contentBase64" (binary), "mode"}.

        Validated like the web picker (extension, text or zip signature) with an
        an explicit 100 MiB upper bound. A single Trakt .json is repackaged into a zip like the web does.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile

        from api.fork_views_integrations import (
            _FILE_IMPORTS,
            _queue_failure_response,
            _resolve_mode,
        )
        from integrations import tasks
        from integrations.upload_staging import (
            enqueue_staged_task,
            stage_uploaded_file,
            staging_failure_message,
        )

        too_large = body_too_large_response(
            request, MAX_FILE_IMPORT_BYTES, "This file is too large to import.",
        )
        if too_large is not None:
            return too_large
        service = FILE_IMPORT_SERVICES.get(slug, slug)
        if service not in _FILE_IMPORTS:
            return Response({"detail": "This provider has no file import."}, status=HTTP.NOT_FOUND)
        if request.user.is_demo:
            return Response({"detail": "This section is view-only for demo accounts."}, status=HTTP.FORBIDDEN)
        mode = _resolve_mode(request)
        if mode is None:
            return Response({"detail": "Invalid mode."}, status=HTTP.BAD_REQUEST)
        body = _json_body(request)
        name = str(body.get("name") or f"{slug}.csv")
        if slug == "trakt" and name.lower().endswith(".csv"):
            service = "trakt-collection"
        task_export, label = _FILE_IMPORTS[service]
        data, failure = _upload_bytes(body)
        if failure is not None:
            return failure
        failure = _upload_error(name, data, service, label)
        if failure is not None:
            return failure
        if service == "trakt-export" and name.lower().endswith(".json"):
            import io
            import zipfile

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(name.rsplit("/", 1)[-1], data)
            data, name = buffer.getvalue(), "trakt-export.zip"
        upload = SimpleUploadedFile(name, data)
        try:
            staged = str(stage_uploaded_file(upload))
        except OSError as error:
            logger.exception("Could not stage %s upload", label)
            return Response({"detail": staging_failure_message(error)}, status=HTTP.INSUFFICIENT_STORAGE)
        try:
            task = enqueue_staged_task(
                getattr(tasks, task_export), user_id=request.user.id, file=staged, mode=mode, staged_paths=(staged,),
            )
        except Exception as error:
            logger.exception("Could not queue %s upload", label)
            return _queue_failure_response(error)
        return Response({"task_id": task.id, "bytes": len(data)}, status=HTTP.ACCEPTED)


def _action_view(slug, suffix):
    if _catalog_item(slug) is None:
        return None
    return _view_for(f"{slug}_{suffix}")


# /api/v1/providers/<slug>/connect/
class ProviderConnectView(drf_views.APIView):
    """Save an account connection through the provider's own session view."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: the provider's connection fields (see `connection.account.fields`)."""
        if slug in BROWSER_HANDOFF:
            return Response(
                {"detail": "Finish connecting in the browser.", "handoff": True},
                status=HTTP.CONFLICT,
            )
        view = _action_view(slug, "connect")
        if view is None:
            return Response({"detail": "This provider has no account form."}, status=HTTP.NOT_FOUND)
        denied = _demo_blocked(request, f"{slug}_connect")
        if denied:
            return denied
        return _call(request, view, post=_json_body(request))


# /api/v1/providers/<slug>/metadata/
class ProviderMetadataActionView(drf_views.APIView):
    """Run one of the Metadata tab's actions through the web view that owns it."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Run a metadata action.

        Body: {"action": "source", "key", "source", "animeMode"?} saves the default
        provider for a media type; {"action": "move", "key": "tv"|"anime"} moves or
        converts existing entries; {"action": "proxy", "proxyUrl"} sets or clears the
        TMDB proxy (superuser only, as on the web).
        """
        from users import metadata_views
        from users import views as user_views

        if _catalog_item(slug) is None:
            return Response({"detail": "Unknown provider."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        action = body.get("action")
        key = str(body.get("key") or "")
        if action == "source":
            denied = _demo_blocked(request, "set_media_type_provider")
            if denied:
                return denied
            post = {"source": body.get("source") or ""}
            if body.get("animeMode"):
                post["anime_library_mode"] = body["animeMode"]
            return _call(request, metadata_views.set_media_type_provider, key, post=post)
        if action == "move":
            view = {"tv": user_views.convert_tv_library, "anime": user_views.convert_anime_library}.get(key)
            if view is None:
                return Response({"detail": "Nothing to move for this type."}, status=HTTP.BAD_REQUEST)
            denied = _demo_blocked(request, view.__name__)
            return denied or _call(request, view, post={})
        if action == "proxy":
            denied = _demo_blocked(request, "update_tmdb_proxy")
            if denied:
                return denied
            return _call(request, user_views.update_tmdb_proxy, post={"tmdb_proxy_url": body.get("proxyUrl") or ""})
        return Response({"detail": "Unknown action."}, status=HTTP.BAD_REQUEST)


# /api/v1/providers/<slug>/disconnect/
class ProviderDisconnectView(drf_views.APIView):
    """Remove the saved account (or one instance, with `instance_id`)."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: optional {"instance_id": n} for multi-instance providers."""
        view = _action_view(slug, "disconnect")
        if view is None:
            return Response({"detail": "This provider has nothing to disconnect."}, status=HTTP.NOT_FOUND)
        return _call(request, view, post=_json_body(request))


# /api/v1/providers/<slug>/credentials/
class ProviderCredentialsView(drf_views.APIView):
    """Save or clear API credentials. Saved values are never returned."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request, slug):
        """Body: {"scope": "instance" | "personal", "values": {field: value}}."""
        from users import metadata_views

        body = _json_body(request)
        values = body.get("values") if isinstance(body.get("values"), dict) else {}
        view = (
            metadata_views.save_personal_credential
            if body.get("scope") == "personal"
            else metadata_views.save_provider_credential
        )
        denied = _demo_blocked(request, view.__name__)
        if denied:
            return denied
        return _call(request, view, slug, post=values)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, slug):
        """Remove the instance-wide credentials (superuser only)."""
        from users import metadata_views

        denied = _demo_blocked(request, "clear_provider_credential")
        if denied:
            return denied
        return _call(request, metadata_views.clear_provider_credential, slug, post={})


# /api/v1/providers/<slug>/test/
class ProviderTestView(drf_views.APIView):
    """Re-probe a saved connection and record the result like a scheduled run."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Return {"ok": bool, "message": str} for Jellyfin and the *arr servers."""
        from integrations import connection_health
        from integrations.imports import helpers as import_helpers
        from integrations.jellyfin_client import (
            JellyfinAuthError,
            JellyfinClient,
            JellyfinClientError,
        )

        if slug not in TESTABLE:
            return Response({"detail": "This provider cannot be tested here."}, status=HTTP.BAD_REQUEST)
        if slug == "jellyfin":
            targets = [(getattr(request.user, "jellyfin_account", None), JellyfinClient, (JellyfinAuthError,))]
            errors = (JellyfinAuthError, JellyfinClientError)
        else:
            from integrations.imports.kapowarr import KapowarrClient
            from integrations.imports.mylar import MylarClient
            from integrations.imports.radarr import RadarrClient
            from integrations.imports.sonarr import SonarrClient

            client = {
                "radarr": RadarrClient,
                "sonarr": SonarrClient,
                "mylar": MylarClient,
                "kapowarr": KapowarrClient,
            }[slug]
            body = _json_body(request)
            rows = getattr(request.user, f"{slug}_instances").all()
            if body.get("instance_id"):
                rows = rows.filter(pk=body["instance_id"])
            targets = [(row, client, (import_helpers.ConnectionAuthError,)) for row in rows]
            errors = (import_helpers.MediaImportError,)
        targets = [target for target in targets if target[0] is not None]
        if not targets:
            return Response({"detail": "Connect this provider first."}, status=HTTP.NOT_FOUND)
        for account, client_class, auth_errors in targets:
            try:
                client_class(account.base_url, import_helpers.decrypt(account.api_key)).healthcheck()
            except errors as error:
                connection_health.record_failure(account, str(error), auth=isinstance(error, auth_errors))
                return Response({"ok": False, "message": "The server rejected or could not answer the check."})
            connection_health.record_success(account)
        return Response({"ok": True, "message": "Connection is working."})


# /api/v1/providers/<slug>/sync/
class ProviderSyncView(drf_views.APIView):
    """Queue an import now for a saved account."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: optional {"instance_id": n} for multi-instance providers."""
        if slug not in SYNC_NOW:
            return Response({"detail": "Sync now is not available for this provider."}, status=HTTP.BAD_REQUEST)
        view = _view_for(SYNC_ROUTES.get(slug, f"import_{slug}"))
        if view is None:
            return Response({"detail": "Not found."}, status=HTTP.NOT_FOUND)
        # The web form posts the saved import preferences along with the click.
        post = {
            "mode": request.user.import_mode,
            "frequency": "once",
            "time": str(request.user.import_time)[:5],
            **_json_body(request),
        }
        return _call(request, view, post=post)


# /api/v1/providers/<slug>/import/
class ProviderImportView(drf_views.APIView):
    """Run a username import once, or create/replace its recurring schedule."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: {"user", "mode", "frequency": once|daily|2days, "time": "HH:MM"}."""
        route = IMPORT_ROUTES.get(slug)
        view = _view_for(route) if route else None
        if view is None:
            return Response({"detail": "Use the import endpoint for this provider."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        post = {
            "user": body.get("user") or body.get("username"),
            "mode": body.get("mode") or request.user.import_mode,
            "frequency": body.get("frequency") or "once",
            "time": body.get("time") or str(request.user.import_time)[:5],
        }
        return _call(request, view, post=post)


# /api/v1/providers/<slug>/schedules/
class ProviderSchedulesView(drf_views.APIView):
    """Recurring import schedules for one provider."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, slug):
        """List this provider's schedules."""
        if _catalog_item(slug) is None:
            return Response({"detail": "Unknown provider."}, status=HTTP.NOT_FOUND)
        return Response({"results": _clean(_schedule_rows(request.user, slug))})

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, slug):
        """Body: {"task_name"} from the list; ownership is checked by the web view."""
        from users.views import delete_import_schedule

        names = {row["task_name"] for row in _schedule_rows(request.user, slug)}
        task_name = _json_body(request).get("task_name")
        if task_name not in names:
            return Response({"detail": "Import schedule not found."}, status=HTTP.NOT_FOUND)
        return _call(request, delete_import_schedule, post={"task_name": task_name})


# ---------------------------------------------------------------- connections


def _binding_row(row, user):
    from users.templatetags.user_tags import user_datetime_format

    return {
        "id": row["id"],
        "client_kind": row["client_kind"],
        "label": row["label"],
        "status": row["status"],
        "is_operational": row["is_operational"],
        "kill_switch": row["kill_switch"],
        "direction": row["direction"],
        "direction_label": row["direction_label"],
        "direction_choices": [{"value": value, "label": label} for value, label in row["direction_choices"]],
        "capabilities": _clean(row["capability_rows"]),
        "has_adapter": row["has_adapter"],
        "can_write": row["can_write"],
        "last_reconciled_at": row["last_reconciled_at"],
        "last_reconciled_label": user_datetime_format(row["last_reconciled_at"], user) if row["last_reconciled_at"] else "",
        "last_error_message": row["last_error_message"],
        "pending_deliveries": row["pending_deliveries"],
        "failed_deliveries": row["failed_deliveries"],
        "open_conflicts": row["open_conflicts"],
    }


# /api/v1/connections/
class ConnectionsView(drf_views.APIView):
    """Connected accounts, sync connections and open conflicts in one read."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Mirror the web Connections section."""
        from integrations.state import settings_view
        from users.provider_catalog import catalog, provider_state

        accounts = []
        for item in catalog():
            if not item.get("connection"):
                continue
            state = provider_state(item, request.user)
            if state["connection"] in {"Needs setup", "No connection required", "Public API active"}:
                continue
            accounts.append(
                {
                    "slug": item["slug"],
                    "label": item["label"],
                    "status": _status(state),
                    "attention": bool(state["attention"]),
                },
            )
        conflicts = [
            {
                "id": conflict.pk,
                "title": str(conflict.item),
                "media_type": conflict.item.media_type,
                "client_kind": conflict.binding.client_kind,
                "client_label": conflict.binding.get_client_kind_display(),
                "reason": conflict.reason,
                "local": conflict.local_snapshot,
                "remote": conflict.remote_snapshot,
                "updated_at": conflict.updated_at,
            }
            for conflict in settings_view.open_conflicts(request.user)
        ]
        return Response(
            {
                "accounts": accounts,
                "sync": [_binding_row(row, request.user) for row in settings_view.binding_rows(request.user)],
                "conflicts": _clean(conflicts),
            },
            status=HTTP.OK,
        )


# /api/v1/connections/<binding_id>/direction/
class ConnectionDirectionView(drf_views.APIView):
    """Choose which way watched state may travel for one connection."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, binding_id):
        """Body: {"direction": off | inbound | outbound | both}."""
        from integrations.views import sync_direction_settings

        return _call(
            request,
            sync_direction_settings,
            post={"binding_id": binding_id, "direction": _json_body(request).get("direction", "")},
        )


# /api/v1/connections/<binding_id>/pause/
class ConnectionPauseView(drf_views.APIView):
    """Kill switch: stop or resume one connection without losing approvals."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, binding_id):
        """Body: {"paused": bool}."""
        from integrations.views import sync_kill_switch

        post = {"binding_id": binding_id}
        if _json_body(request).get("paused"):
            post["kill_switch"] = "on"
        return _call(request, sync_kill_switch, post=post)


# /api/v1/connections/device/
class DeviceApprovalView(drf_views.APIView):
    """Approve or deny an application that is waiting on a device code."""

    @staticmethod
    def _authorization(user_code):
        from integrations.oauth_models import OAuthDeviceAuthorization

        return OAuthDeviceAuthorization.for_user_code((user_code or "").strip()) if user_code else None

    @staticmethod
    def _problem(authorization):
        if authorization is None:
            return "That device code is not valid."
        if authorization.is_expired:
            return "That device code has expired."
        if not authorization.client.is_active:
            return "That application registration has been revoked."
        if authorization.consumed_at is not None:
            return "That device code has already been used."
        return ""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Look up ?user_code= and describe the application and its scopes."""
        from integrations.oauth_scope_info import scope_details

        authorization = self._authorization(request.query_params.get("user_code"))
        problem = self._problem(authorization)
        if problem:
            return Response({"detail": problem}, status=HTTP.NOT_FOUND if authorization is None else HTTP.BAD_REQUEST)
        return Response(
            {
                "user_code": request.query_params["user_code"].strip(),
                "application": authorization.client.name,
                "scopes": scope_details(authorization.requested_scopes),
            },
            status=HTTP.OK,
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Body: {"user_code", "action": approve | deny}."""
        from integrations.oauth_models import DeviceAuthorizationStateError

        body = _json_body(request)
        authorization = self._authorization(body.get("user_code"))
        problem = self._problem(authorization)
        if problem:
            return Response({"detail": problem}, status=HTTP.BAD_REQUEST)
        action = body.get("action")
        try:
            if action == "approve":
                authorization.approve(request.user)
            elif action == "deny":
                authorization.deny(request.user)
            else:
                return Response({"detail": "Choose whether to approve or deny this application."}, status=HTTP.BAD_REQUEST)
        except DeviceAuthorizationStateError as error:
            return Response({"detail": error.message}, status=HTTP.BAD_REQUEST)
        return Response({"ok": True, "action": action}, status=HTTP.OK)


# ------------------------------------------------------------ metadata review


def _item_row(item):
    if item is None:
        return None
    return {
        "id": item.pk,
        "title": item.title,
        "media_type": item.media_type,
        "source": item.source,
        "media_id": item.media_id,
        "image": item.image,
    }


def _reference_row(reference):
    return {
        "id": reference.pk,
        "integration": reference.integration,
        "media_type": reference.media_type,
        "status": reference.review_status,
        "identity": reference.external_identity,
        "title": (reference.metadata or {}).get("title") or reference.external_identity,
        "review_status_label": reference.get_review_status_display(),
        "matched": _item_row(reference.matched_item),
        "corrected": _item_row(reference.corrected_item),
        "updated_at": reference.updated_at,
    }


# /api/v1/metadata-review/
class MetadataReviewQueueView(drf_views.APIView):
    """References that need a decision, and the corrections already saved."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Mirror the match review lists (newest first, 100 each)."""
        from integrations.models import ExternalReference, ExternalReferenceReviewStatus

        base = ExternalReference.objects.filter(user=request.user).select_related("matched_item", "corrected_item")
        queue = base.filter(review_status=ExternalReferenceReviewStatus.NEEDS_REVIEW.value).order_by("-updated_at")[:100]
        saved = base.filter(
            review_status__in=(
                ExternalReferenceReviewStatus.CORRECTED.value,
                ExternalReferenceReviewStatus.IGNORED.value,
            ),
        ).order_by("-updated_at")[:100]
        return Response(
            {
                "needs_review": [_reference_row(row) for row in queue],
                "saved": [_reference_row(row) for row in saved],
            },
            status=HTTP.OK,
        )


# /api/v1/metadata-review/references/<reference_id>/
class MetadataReviewReferenceView(drf_views.APIView):
    """Skip (ignore) a source identity, or remove a saved correction."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, reference_id):
        """Body: {"action": "ignored" | "remove"}."""
        from integrations.views import match_reference_status

        action = _json_body(request).get("action")
        if action not in {"ignored", "remove"}:
            return Response({"detail": "Unknown match decision."}, status=HTTP.BAD_REQUEST)
        return _call(request, match_reference_status, reference_id, action)


def _match_source(request, item_id):
    from django.http import Http404

    from integrations.views import _match_source_for_user

    try:
        return _match_source_for_user(request._request, item_id)
    except Http404:
        return None


def _provider_choice(request, source_item):
    from app.models import Sources
    from app.services import metadata_resolution
    from integrations.views import _match_providers

    providers = _match_providers(request.user, source_item)
    provider = request.query_params.get("provider") or _json_body(request).get("provider")
    if provider not in providers:
        provider = Sources.TMDB.value
    return provider, [
        {"value": key, "label": metadata_resolution.metadata_provider_label(key)} for key in providers
    ]


# /api/v1/metadata-review/items/<item_id>/candidates/
class MetadataMatchCandidatesView(drf_views.APIView):
    """Search a provider for the correct title of a tracked movie or show."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, item_id):
        """Query: q, provider."""
        from app.providers import services
        from integrations.views import _match_candidate_rows

        source_item = _match_source(request, item_id)
        if source_item is None:
            return Response({"detail": "Not found."}, status=HTTP.NOT_FOUND)
        provider, providers = _provider_choice(request, source_item)
        query = (request.query_params.get("q") or "").strip()
        candidates = []
        if query:
            try:
                results = services.search(source_item.media_type, query, 1, source=provider, user=request.user)
            except services.ProviderAPIError as error:
                return Response({"detail": f"Could not search {error.provider_label}."}, status=HTTP.BAD_GATEWAY)
            candidates = [
                {
                    "media_id": row["media_id"],
                    "title": row["title"],
                    "year": row["result"].get("year"),
                    "image": row["result"].get("image") or row["result"].get("poster_path") or "",
                }
                for row in _match_candidate_rows(results.get("results", []))
            ]
        return Response(
            {
                "source": _item_row(source_item),
                "provider": provider,
                "providers": providers,
                "query": query,
                "candidates": candidates,
            },
            status=HTTP.OK,
        )


def _correction_errors():
    from integrations.match_corrections import (
        InvalidMatchCorrectionError,
        MissingEpisodeMappingError,
        StaleCorrectionPreviewError,
    )

    return InvalidMatchCorrectionError, MissingEpisodeMappingError, StaleCorrectionPreviewError


def _preview_payload(request, source_item, preview):
    from app.models import MediaTypes
    from integrations.views import _match_reference_ids, _match_review

    review = _match_review(source_item, preview) if source_item.media_type == MediaTypes.TV.value else None
    return {
        "token": preview["token"],
        "source": _item_row(source_item),
        "destination": _item_row(preview["destination"]),
        "counts": preview["counts"],
        "scalar_conflicts": _clean(preview.get("scalar_conflicts") or {}),
        "reference_count": len(_match_reference_ids(request.user, source_item)),
        "rows": list(review["rows"].values()) if review else [],
        "episodes": review["episodes"] if review else [],
    }


# /api/v1/metadata-review/items/<item_id>/preview/
class MetadataMatchPreviewView(drf_views.APIView):
    """Preview what moving a tracked title to a chosen candidate would change."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, item_id):
        """Body: {"provider", "q", "destination_media_id"}."""
        from app.providers import services
        from integrations.match_corrections import preview_match_correction
        from integrations.views import (
            _match_candidate_rows,
            _match_destination_from_result,
        )

        source_item = _match_source(request, item_id)
        if source_item is None:
            return Response({"detail": "Not found."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        provider, _providers = _provider_choice(request, source_item)
        query = str(body.get("q") or "").strip()
        try:
            results = services.search(source_item.media_type, query, 1, source=provider, user=request.user)
        except services.ProviderAPIError as error:
            return Response({"detail": f"Could not search {error.provider_label}."}, status=HTTP.BAD_GATEWAY)
        chosen = next(
            (
                row
                for row in _match_candidate_rows(results.get("results", []))
                if row["media_id"] == str(body.get("destination_media_id"))
            ),
            None,
        )
        destination = (
            _match_destination_from_result(chosen["result"], source_item.media_type, provider) if chosen else None
        )
        if destination is None:
            return Response({"detail": "Choose a valid same-type destination."}, status=HTTP.BAD_REQUEST)
        try:
            preview = preview_match_correction(request.user, source_item, destination)
            return Response(_preview_payload(request, source_item, preview), status=HTTP.OK)
        except _correction_errors() as error:
            return Response({"detail": error.message}, status=HTTP.BAD_REQUEST)


# /api/v1/metadata-review/items/<item_id>/apply/
class MetadataMatchApplyView(drf_views.APIView):
    """Apply a previewed correction; the token must still match current data."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, item_id):
        """Body: {"destination_item_id", "token", "mapping": {rowId: destId}, "decisions", "note"}."""
        from app.models import Item
        from integrations.match_corrections import (
            apply_match_correction,
            preview_match_correction,
        )
        from integrations.views import (
            _match_posted_mapping,
            _match_reference_ids,
            _match_review,
        )

        source_item = _match_source(request, item_id)
        if source_item is None:
            return Response({"detail": "Not found."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        destination = Item.objects.filter(pk=body.get("destination_item_id")).first()
        if destination is None or not body.get("token"):
            return Response({"detail": "Refresh the correction preview before applying."}, status=HTTP.BAD_REQUEST)
        invalid, missing, stale = _correction_errors()
        try:
            preview = preview_match_correction(request.user, source_item, destination)
            mapping = None
            if source_item.media_type == "tv":
                review = _match_review(source_item, preview)
                posted = {f"map_{key}": value for key, value in (body.get("mapping") or {}).items()}
                mapping = _match_posted_mapping(posted, {row["id"] for row in review["episodes"]})
            decisions = {key: value for key, value in (body.get("decisions") or {}).items() if value}
            corrected = apply_match_correction(
                request.user,
                source_item.pk,
                destination.pk,
                body["token"],
                episode_mapping=mapping,
                decisions=decisions,
                reference_ids=_match_reference_ids(request.user, source_item),
                note=str(body.get("note") or ""),
            )
        except stale as error:
            return Response({"detail": error.message}, status=HTTP.CONFLICT)
        except (invalid, missing) as error:
            return Response({"detail": error.message}, status=HTTP.BAD_REQUEST)
        except PermissionDenied:
            return Response({"detail": "Permission denied."}, status=HTTP.FORBIDDEN)
        return Response({"ok": True, "item": _item_row(corrected)}, status=HTTP.OK)
