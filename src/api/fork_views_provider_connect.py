# FORK: start, poll and cancel an account link for the providers that connect
# through a device code (Trakt on an HTTP instance, Storyteller, WeTrakr) or a
# browser redirect (Trakt, Plex, SIMKL, MyAnimeList, AniList, TMDb) so the
# native app can drive them with JSON. The web views stay the owner of the
# logic: start runs the web start view, poll runs the web poll, and the pending
# state both read lives in integrations.pending_auth, keyed per user. A
# redirect start answers with the provider's authorize URL; the browser then
# finishes on the web callback and returns to the app only through its own
# deep-link scheme (or a same-origin path). Session or legacy token only.
from http import HTTPStatus as HTTP  # noqa: N814

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from api.fork_views_providers import _call, _catalog_item, _demo_blocked, _view_for
from api.fork_views_settings import _delegate, _json_body
from integrations import pending_auth

START_ROUTES = {
    "trakt": "trakt_oauth",
    "simkl": "simkl_oauth",
    "mal": "mal_oauth",
    "anilist": "import_anilist_oauth",
    "plex": "plex_connect",
    "tmdb": "tmdb_connect",
    "storyteller": "storyteller_connect",
    "wetrakr": "wetrakr_connect",
}
CANCEL_ROUTES = {"storyteller": "storyteller_cancel", "wetrakr": "wetrakr_cancel"}
DEVICE_PROVIDERS = frozenset({"trakt", "storyteller", "wetrakr"})
IMPORT_MODES = ("new", "overwrite")


def _valid_return(target):
    """Accept only the app's own deep link or a same-origin path."""
    if not target:
        return True
    if pending_auth.is_native_return(target):
        return True
    return (
        isinstance(target, str)
        and target.startswith("/")
        and not target.startswith("//")
        and "\\" not in target
        and "\n" not in target
        and "\r" not in target
    )


def _device(code, url, open_url, interval, expires_at):
    return {
        "kind": "device",
        "userCode": code,
        "verificationUrl": url,
        "openUrl": open_url or url,
        "interval": int(interval or 5),
        "expiresAt": expires_at,
    }


def _trakt_device(user):
    state = pending_auth.get("trakt_device_auth", user.pk)
    if not state:
        return None
    url = state["verification_url"]
    return _device(
        state["user_code"],
        url,
        f"{url.rstrip('/')}/{state['user_code']}",
        state["interval"],
        state["expires_at"],
    )


def _storyteller_device(user):
    state = pending_auth.get("storyteller_pending_auth", user.pk)
    if not state:
        return None
    return _device(
        state["user_code"],
        state.get("verification_uri") or "",
        state.get("verification_uri_complete") or state.get("verification_uri"),
        state["interval"],
        state["expires_at"],
    )


def _wetrakr_device(user):
    from integrations.models import WeTrakrAccount

    account = WeTrakrAccount.objects.filter(user=user).first()
    if account is None or not account.is_pending:
        return None
    expires = account.device_expires_at.isoformat() if account.device_expires_at else None
    return _device(
        account.user_code,
        account.verification_url,
        account.verification_url,
        account.device_interval,
        expires,
    )


DEVICE_READERS = {
    "trakt": _trakt_device,
    "storyteller": _storyteller_device,
    "wetrakr": _wetrakr_device,
}


# /api/v1/providers/<slug>/connect/start/
class ProviderConnectStartView(drf_views.APIView):
    """Begin a device-code or redirect connect for one provider."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Body: {"mode", "frequency", "time", "serverUrl" (Storyteller), "returnTo"}.

        Answers {"kind": "device", userCode, verificationUrl, openUrl, interval,
        expiresAt} for a device code, or {"kind": "redirect", authorizeUrl} for a
        browser sign-in. ``returnTo`` may only be the app's own deep link or a
        same-origin path; anything else is refused.
        """
        route = START_ROUTES.get(slug)
        if route is None or _catalog_item(slug) is None:
            return Response({"detail": "This provider has no sign-in flow."}, status=HTTP.NOT_FOUND)
        body = _json_body(request)
        return_to = body.get("returnTo")
        if not _valid_return(return_to):
            return Response({"detail": "Invalid return address."}, status=HTTP.BAD_REQUEST)
        mode = body.get("mode") or "new"
        if mode not in IMPORT_MODES:
            return Response({"detail": "Invalid mode."}, status=HTTP.BAD_REQUEST)
        view = _view_for(route)
        denied = _demo_blocked(request, route)
        if denied:
            return denied
        django_request = request._request
        django_request.native_connect = True
        django_request.delegated_location = None
        post = {
            "mode": mode,
            "frequency": body.get("frequency") or "once",
            "time": body.get("time") or "00:00",
            "next": return_to or "",
            "server_url": body.get("serverUrl") or "",
        }
        result = _delegate(request, view, post=post)
        if result.status_code >= HTTP.BAD_REQUEST:
            return result
        location = django_request.delegated_location or ""
        reader = DEVICE_READERS.get(slug)
        if reader and (slug != "trakt" or location == reverse("trakt_device_verify")):
            device = reader(request.user)
            if device is None:
                return Response({"detail": "The provider did not start a login."}, status=HTTP.BAD_GATEWAY)
            return Response(device)
        if location.startswith(("https://", "http://")):
            return Response({"kind": "redirect", "authorizeUrl": location})
        return Response({"detail": "The provider did not return a sign-in address."}, status=HTTP.BAD_GATEWAY)


def _status_for(payload, message):
    """Map each web poll reply onto one vocabulary."""
    raw = payload.get("status") or payload.get("state") or "idle"
    status = {"approved": "connected", "failed": "error"}.get(raw, raw)
    if status == "error" and "denied" in (message or "").lower():
        status = "denied"
    if status == "error" and "expired" in (message or "").lower():
        status = "expired"
    return status


# /api/v1/providers/<slug>/connect/poll/
class ProviderConnectPollView(drf_views.APIView):
    """Check once whether the pending device login was approved."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, slug):
        """Answer {"status": idle|pending|connected|expired|denied|error, "message"}."""
        if slug not in DEVICE_PROVIDERS:
            return Response({"status": "idle", "message": ""})
        denied = _demo_blocked(request, START_ROUTES[slug])
        if denied:
            return denied
        if slug == "trakt":
            from integrations.views import poll_trakt_device

            status, message, _state = poll_trakt_device(request._request)
            return Response({"status": _status_for({"status": status}, message), "message": message})
        if slug == "storyteller":
            from integrations.views import storyteller_poll

            result = _delegate(request, storyteller_poll, method="GET")
        else:
            from integrations.wetrakr_views import wetrakr_poll

            result = _delegate(request, wetrakr_poll)
        if result.status_code >= HTTP.BAD_REQUEST:
            return result
        payload = result.data if isinstance(result.data, dict) else {}
        message = payload.get("message") or payload.get("detail") or ""
        return Response({"status": _status_for(payload, message), "message": message})


# /api/v1/providers/<slug>/connect/cancel/
class ProviderConnectCancelView(drf_views.APIView):
    """Abandon a pending device login."""

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, slug):
        """Forget the pending login; other providers have nothing to cancel."""
        if slug == "trakt":
            pending_auth.clear("trakt_device_auth", request.user.pk)
            return Response({"ok": True})
        route = CANCEL_ROUTES.get(slug)
        if route is None:
            return Response({"ok": True})
        return _call(request, _view_for(route))

