# FORK: settings endpoints for the native app, mirroring the web settings pages
# that only had session views (appearance, cards, home screen, access, users,
# advanced, about, data). Business logic stays in the web view modules; session
# views that already answer JSON or redirect-with-messages are reached through
# `_delegate`, which adapts them to credentials the API authenticates (Bearer
# token or session cookie). URL wiring lives in fork_urls.py.
import datetime as dt
import json
import logging
import uuid
from datetime import timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.contrib.messages import constants as message_levels
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse, QueryDict
from django.http.request import HttpHeaders
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

logger = logging.getLogger(__name__)

_DEMO_DETAIL = "This section is view-only for demo accounts."


def _demo_denied(user):
    if getattr(user, "is_demo", False):
        return Response({"detail": _DEMO_DETAIL}, status=HTTP.FORBIDDEN)
    return None


def _superuser_denied(user):
    if not user.is_superuser:
        return Response(
            {"detail": "Superuser access is required."}, status=HTTP.FORBIDDEN
        )
    return None


def _json_body(request):
    data = request.data
    return data if isinstance(data, dict) else {}


def _delegate(request, view, *args, post=None, method="POST"):
    """Call a session view with the API-authenticated user and adapt its reply.

    JSON replies pass through (an ``error`` key becomes ``detail``). Redirect
    replies become ``{"ok", "messages"}`` from the Django messages the view
    queued, which are drained so they never surface later on a web page.
    """
    django_request = request._request
    django_request.META["HTTP_ACCEPT"] = "application/json"
    # `headers` is cached from META on first use, so rebuild it after the edit.
    django_request.headers = HttpHeaders(django_request.META)
    # The session views are POST-only; the API uses PATCH/DELETE for the same act.
    django_request.method = method
    if post is not None:
        form = QueryDict(mutable=True)
        for key, value in post.items():
            if isinstance(value, (list, tuple)):
                form.setlist(key, [str(item) for item in value])
            elif isinstance(value, bool):
                form[key] = "true" if value else "false"
            elif value is not None:
                form[key] = str(value)
        django_request.POST = form
    # Messages queued before this call (an unrendered web flash) belong to
    # another request; only what this view adds decides the outcome.
    storage = get_messages(django_request)
    earlier = len(list(storage))
    storage.used = False
    response = view(django_request, *args)
    notes = [
        {"level": message.level, "text": str(message.message)}
        for message in list(get_messages(django_request))[earlier:]
    ]
    failed = any(note["level"] >= message_levels.ERROR for note in notes)
    texts = [note["text"] for note in notes]
    if isinstance(response, JsonResponse):
        body = json.loads(response.content or b"{}")
        if response.status_code >= HTTP.BAD_REQUEST:
            detail = body.get("error") or body.get("message") or "Request failed."
            return Response({"detail": detail}, status=response.status_code)
        if isinstance(body, dict) and texts and "message" not in body:
            body["message"] = texts[0]
        return Response(body, status=response.status_code)
    if isinstance(response, HttpResponseRedirect):
        # Callers that must read where the view sent the browser (a provider
        # authorize URL) find it here; the reply itself stays unchanged.
        django_request.delegated_location = response.url
        payload = {"ok": not failed, "messages": texts}
        if failed:
            payload["detail"] = texts[-1]
        return Response(payload, status=HTTP.BAD_REQUEST if failed else HTTP.OK)
    if response.status_code == HTTP.FORBIDDEN:
        return Response({"detail": "Permission denied."}, status=HTTP.FORBIDDEN)
    return response


# /api/v1/user/preferences/choices/
class UserPreferencesChoicesView(drf_views.APIView):
    """Watch-provider region and metadata-language options (TMDB lists)."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the same option lists the web preferences page renders."""
        from api.fork_views_users import tmdb_preference_choices

        return Response(tmdb_preference_choices(), status=HTTP.OK)


# /api/v1/user/appearance/
class UserAppearanceView(drf_views.APIView):
    """Read or save the theme, custom palette and detail-page layouts."""

    @staticmethod
    def _payload(user):
        from users import appearance as config

        saved = user.custom_theme if isinstance(user.custom_theme, dict) else {}
        palette = {
            key: saved.get(key, definition["default"])
            for key, definition in config.CUSTOM_THEME_COLORS.items()
        }
        palette.update(
            {
                key: saved.get(key, definition["default"])
                for key, definition in config.CUSTOM_THEME_EFFECTS.items()
            }
        )
        return {
            "theme": user.theme,
            "presets": config.THEME_PRESETS,
            "colors": config.CUSTOM_THEME_COLORS,
            "effects": config.CUSTOM_THEME_EFFECTS,
            "palette": palette,
            "families": config.DETAIL_LAYOUT_FAMILIES,
            "layouts": config.resolved_detail_layouts(user.detail_page_layouts),
        }

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return presets, palette definitions and the user's saved values."""
        return Response(self._payload(request.user), status=HTTP.OK)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Validate the whole payload, then save theme, palette and layouts."""
        from django.core.exceptions import ValidationError

        from users import appearance as config
        from users.models import ThemeChoices

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        theme = body.get("theme")
        if theme not in ThemeChoices.values:
            return Response({"detail": "Unsupported theme."}, status=HTTP.BAD_REQUEST)
        try:
            custom_theme = config.parse_custom_theme(
                json.dumps(body.get("custom_theme", body.get("palette", {})))
            )
            layouts = config.parse_detail_layouts(
                json.dumps(body.get("detail_layouts", body.get("layouts", {})))
            )
        except ValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=HTTP.BAD_REQUEST)
        user = request.user
        user.theme = theme
        user.custom_theme = custom_theme
        user.detail_page_layouts = layouts
        user.save(update_fields=["theme", "custom_theme", "detail_page_layouts"])
        return Response(self._payload(user), status=HTTP.OK)


# /api/v1/user/cards/
class UserCardsView(drf_views.APIView):
    """Read or save the per-media-type card subtitle profiles."""

    @staticmethod
    def _payload(user):
        from users.card_metadata import PROFILE_TYPES, editor_catalog, resolve_profile

        return {
            "catalog": editor_catalog(),
            "profiles": {
                media_type: resolve_profile(user, media_type)
                for media_type in PROFILE_TYPES
            },
            "clickable_media_cards": user.clickable_media_cards,
        }

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the editor catalog and the resolved saved profiles."""
        return Response(self._payload(request.user), status=HTTP.OK)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Save card profiles (`card_metadata`) and the touch-action toggle."""
        from users.card_metadata import parse_card_metadata

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        user = request.user
        fields = []
        if "card_metadata" in body:
            user.card_metadata = parse_card_metadata(body["card_metadata"])
            fields.append("card_metadata")
        if "clickable_media_cards" in body:
            if not isinstance(body["clickable_media_cards"], bool):
                return Response(
                    {"detail": "clickable_media_cards must be a boolean."},
                    status=HTTP.BAD_REQUEST,
                )
            user.clickable_media_cards = body["clickable_media_cards"]
            fields.append("clickable_media_cards")
        if fields:
            user.save(update_fields=fields)
        return Response(self._payload(user), status=HTTP.OK)


# /api/v1/user/cards/preview/
class UserCardPreviewView(drf_views.APIView):
    """Return a real card model for one media type drawn with a draft profile."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Build the card the Media Cards page previews; nothing is saved."""
        from app.card_surfaces import card_context
        from app.media_card_model import card_model
        from users.card_metadata import PROFILE_TYPES, parse_card_metadata
        from users.views import _card_preview_sample, _card_preview_stand_in

        body = _json_body(request)
        media_type = body.get("type")
        if media_type not in PROFILE_TYPES:
            media_type = "movie"
        draft = body.get("draft") if isinstance(body.get("draft"), dict) else {}
        if "types" not in draft and media_type in draft:
            draft = {"version": 1, "types": {media_type: draft}}
        user = request.user
        user.card_metadata = parse_card_metadata(draft)
        sample = _card_preview_sample(user, media_type)
        public_view = sample is None
        item, media = _card_preview_stand_in(media_type) if public_view else sample
        context = card_context(
            {"user": user, "request": request},
            "library",
            {
                "item": item,
                "media": media,
                "card_media_type": media_type,
                "public_view": public_view,
            },
        )
        return Response({"card": card_model(context)}, status=HTTP.OK)


# /api/v1/user/home-screen/
class UserHomeScreenView(drf_views.APIView):
    """Read or save the Home screen sections, headers and media-type chips."""

    @staticmethod
    def _payload(user):
        from app.icon_specs import icon_spec
        from users.home_screen import serialize_settings_sections
        from users.media_type_chips import (
            HOME_MEDIA_TYPE_CHIP_TYPES,
            default_media_type_chip_color,
            normalize_media_type_chip_colors,
        )

        sections = serialize_settings_sections(user)
        saved_colors = normalize_media_type_chip_colors(
            user.home_media_type_chip_colors
        )
        for section in sections:
            section["icon"] = icon_spec(section["icon_svg"])
            media_type = section["media_type"]
            section["media_type_chip_color"] = (
                saved_colors.get(media_type, default_media_type_chip_color(media_type))
                if media_type in HOME_MEDIA_TYPE_CHIP_TYPES
                else None
            )
        return {
            "sections": sections,
            "show_media_type_headers": user.home_show_media_type_headers,
            "media_type_chips_enabled": user.home_media_type_chips_enabled,
            "media_type_chip_style": user.home_media_type_chip_style,
            "media_type_chip_styles": [
                {"value": "solid", "label": "Solid"},
                {"value": "soft", "label": "Soft"},
                {"value": "outline", "label": "Outline"},
            ],
            "direction_choices": [
                {"value": "asc", "label": "Ascending"},
                {"value": "desc", "label": "Descending"},
            ],
        }

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the sections, headers toggle and chip settings."""
        return Response(self._payload(request.user), status=HTTP.OK)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Validate and save sections, then the header and chip settings."""
        from users.home_screen import (
            HomeScreenValidationError,
            save_home_screen_configuration,
        )
        from users.media_type_chips import (
            HOME_MEDIA_TYPE_CHIP_STYLES,
            HOME_MEDIA_TYPE_CHIP_TYPES,
            normalize_media_type_chip_colors,
        )

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        user = request.user
        try:
            save_home_screen_configuration(user, json.dumps(body.get("sections", [])))
        except HomeScreenValidationError as exc:
            return Response({"detail": str(exc)}, status=HTTP.BAD_REQUEST)
        fields = []
        headers = bool(body.get("show_media_type_headers"))
        if user.home_show_media_type_headers != headers:
            user.home_show_media_type_headers = headers
            fields.append("home_show_media_type_headers")
        if "media_type_chips_enabled" in body:
            enabled = bool(body["media_type_chips_enabled"])
            if user.home_media_type_chips_enabled != enabled:
                user.home_media_type_chips_enabled = enabled
                fields.append("home_media_type_chips_enabled")
            style = body.get("media_type_chip_style")
            if (
                style in HOME_MEDIA_TYPE_CHIP_STYLES
                and user.home_media_type_chip_style != style
            ):
                user.home_media_type_chip_style = style
                fields.append("home_media_type_chip_style")
        submitted = {
            section["media_type"]: section.get("media_type_chip_color")
            for section in body.get("sections", [])
            if isinstance(section, dict)
            and section.get("media_type") in HOME_MEDIA_TYPE_CHIP_TYPES
            and section.get("media_type_chip_color")
        }
        if submitted:
            colors = normalize_media_type_chip_colors(user.home_media_type_chip_colors)
            colors.update(normalize_media_type_chip_colors(submitted))
            if user.home_media_type_chip_colors != colors:
                user.home_media_type_chip_colors = colors
                fields.append("home_media_type_chip_colors")
        if fields:
            user.save(update_fields=fields)
        return Response(self._payload(user), status=HTTP.OK)


# /api/v1/user/home-screen/lists/
class UserHomeScreenListsView(drf_views.APIView):
    """List suggestions for a Home row's list picker."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return accessible lists matching `q` for `media_type`."""
        from users.home_screen import search_home_screen_lists

        return Response(
            {
                "results": search_home_screen_lists(
                    request.user,
                    request.GET.get("q", ""),
                    request.GET.get("media_type", ""),
                ),
            },
            status=HTTP.OK,
        )


# /api/v1/user/home-screen/filter-fields/
class UserHomeScreenFilterFieldsView(drf_views.APIView):
    """Filter field options for one Home section, computed on demand."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the filter fields for `media_type`."""
        from users.home_screen import (
            get_home_configurable_media_types,
            serialize_settings_filter_fields,
        )

        media_type = request.GET.get("media_type", "")
        if media_type not in get_home_configurable_media_types(request.user):
            return Response({"detail": "Unknown media type."}, status=HTTP.NOT_FOUND)
        return Response(
            {
                "filter_fields": serialize_settings_filter_fields(
                    request.user, media_type
                )
            },
            status=HTTP.OK,
        )


# ---------------------------------------------------------------- credentials


def _iso(value):
    return value.isoformat() if value else None


# /api/v1/user/token/
class UserTokenView(drf_views.APIView):
    """The account API token. Session-only, including for first-party app tokens."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the account token the web Access page shows."""
        return Response({"token": request.user.token or ""}, status=HTTP.OK)


# /api/v1/user/account/
class UserAccountView(drf_views.APIView):
    """Account and sign-in security: the web Account page's native JSON contract.

    Full account access, so never for scoped tokens. It exists so the Floppy
    app can manage the account with a bearer credential, which the session view
    cannot read. The session view keeps every rule (demo guard, re-entering the
    password, rate limit); its JSON comes back unchanged so field errors survive.
    """

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the account payload."""
        return self._account(request)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Apply one account form (username, password, authenticator, deletion)."""
        return self._account(request)

    def _account(self, request):
        from users.views import account

        credential_session = isinstance(request.successful_authenticator, SessionAuthentication)
        if request.method == "POST" and not credential_session:
            data = request.data
            if not isinstance(data, (dict, QueryDict)):
                return Response({"detail": "An object is required."}, status=HTTP.BAD_REQUEST)
            profile_only = isinstance(data, (dict, QueryDict)) and set(data) == {"username"}
            delete_account = data.get("action") == "delete_account" and not any(
                key in data for key in ("old_password", "new_password1", "new_password2")
            )
            if not profile_only and not delete_account:
                return Response(
                    {"detail": "Sign in with your username and password to manage this."},
                    status=HTTP.FORBIDDEN,
                )
        django_request = request._request
        django_request.account_credentials_allowed = credential_session
        django_request.META["HTTP_X_FLOPPY_CLIENT"] = "native"
        django_request.headers = HttpHeaders(django_request.META)
        if request.method == "POST":
            data = request.data
            if not isinstance(data, QueryDict):
                form = QueryDict(mutable=True)
                for key, value in (data.items() if isinstance(data, dict) else ()):
                    if value is not None:
                        form[key] = str(value)
                data = form
            django_request.POST = data
        response = account(django_request)
        if not isinstance(response, JsonResponse):
            return Response({"detail": "Request failed."}, status=HTTP.BAD_REQUEST)
        payload = json.loads(response.content or b"{}")
        if not credential_session:
            payload["credentialSessionRequired"] = True
            authenticator = payload.get("authenticator")
            if isinstance(authenticator, dict):
                authenticator.update({"setup": False, "secret": "", "provisioningUri": "", "qrDataUri": ""})
            payload["freshRecoveryCodes"] = []
        return Response(payload, status=response.status_code)


def _token_row(token):
    return {
        "id": token.id,
        "name": token.name,
        "prefix": token.token_prefix,
        "scopes": list(token.scopes or []),
        "created_at": _iso(token.created_at),
        "last_used_at": _iso(token.last_used_at),
        "expires_at": _iso(token.expires_at),
    }


# /api/v1/user/tokens/
class UserIntegrationTokensView(drf_views.APIView):
    """Named, scoped app tokens (the web "App tokens" card)."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return live tokens and the scope vocabulary."""
        from api import scopes as api_scopes
        from integrations.models import DEFAULT_INTEGRATION_SCOPES, IntegrationToken

        tokens = IntegrationToken.objects.filter(
            user=request.user, client_identifier="", revoked_at__isnull=True
        ).order_by("-created_at")
        return Response(
            {
                "results": [_token_row(token) for token in tokens],
                "scope_choices": [
                    {
                        "value": scope,
                        "description": description,
                        "default": scope in DEFAULT_INTEGRATION_SCOPES,
                    }
                    for scope, description in sorted(
                        api_scopes.SCOPE_DESCRIPTIONS.items()
                    )
                ],
            },
            status=HTTP.OK,
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        """Mint a token; the secret is returned this once and never stored."""
        from api import scopes as api_scopes
        from integrations.models import IntegrationToken
        from users.views import MAX_TOKEN_NAME_LENGTH

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        name = str(body.get("name") or "").strip()[:MAX_TOKEN_NAME_LENGTH]
        if not name:
            return Response(
                {"detail": "Give the token a name so you can recognise it later."},
                status=HTTP.BAD_REQUEST,
            )
        requested = body.get("scopes")
        scopes = [
            scope
            for scope in (requested if isinstance(requested, list) else [])
            if scope in api_scopes.ALL_SCOPES
        ]
        if not scopes:
            return Response(
                {"detail": "Select at least one permission for the token."},
                status=HTTP.BAD_REQUEST,
            )
        expires_at = None
        raw_expiry = str(body.get("expires_in_days") or "").strip()
        if body.get("expires_in_days") == 0:
            raw_expiry = "0"
        if raw_expiry:
            try:
                days = int(raw_expiry)
            except ValueError:
                return Response(
                    {"detail": "Expiry must be a number of days."},
                    status=HTTP.BAD_REQUEST,
                )
            if days < 1:
                return Response(
                    {"detail": "Expiry must be at least one day."},
                    status=HTTP.BAD_REQUEST,
                )
            expires_at = timezone.now() + timedelta(days=days)
        token, raw_token = IntegrationToken.generate(
            user=request.user, name=name, scopes=scopes, expires_at=expires_at
        )
        return Response({**_token_row(token), "secret": raw_token}, status=HTTP.CREATED)


# /api/v1/user/tokens/<id>/
class UserIntegrationTokenDetailView(drf_views.APIView):
    """Revoke one app token."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, token_id):
        """Revoke the token (the web view does the same, soft)."""
        from integrations.models import IntegrationToken

        denied = _demo_denied(request.user)
        if denied:
            return denied

        token = IntegrationToken.objects.filter(
            pk=token_id,
            user=request.user,
            client_identifier="",
            revoked_at__isnull=True,
        ).first()
        if token is None:
            return Response({"detail": "Token not found."}, status=HTTP.NOT_FOUND)
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        return Response({"id": token.id, "revoked": True}, status=HTTP.OK)


def _grant_row(grant):
    return {
        "id": grant.id,
        "name": grant.name,
        "allow_playback_start": grant.allow_playback_start,
        "created_at": _iso(grant.created_at),
        "last_used_at": _iso(grant.last_used_at),
    }


# /api/v1/user/catalog-grants/
class UserCatalogGrantsView(drf_views.APIView):
    """Add-on install credentials (the web Stremio connection tab)."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return live grants. The URL token is only shown at creation."""
        from integrations.models import CatalogGrant

        grants = CatalogGrant.objects.filter(
            user=request.user, revoked_at__isnull=True
        ).order_by("-created_at")
        return Response(
            {"results": [_grant_row(grant) for grant in grants]}, status=HTTP.OK
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        """Mint an add-on install credential."""
        from integrations.models import CatalogGrant
        from users.views import MAX_TOKEN_NAME_LENGTH

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        name = str(body.get("name") or "").strip()[:MAX_TOKEN_NAME_LENGTH]
        if not name:
            return Response(
                {"detail": "Give the install a name so you can recognise it."},
                status=HTTP.BAD_REQUEST,
            )
        grant, token = CatalogGrant.generate(
            user=request.user,
            name=name,
            allow_playback_start=bool(body.get("allow_playback_start", False)),
        )
        return Response({**_grant_row(grant), "secret": token}, status=HTTP.CREATED)


# /api/v1/user/catalog-grants/<id>/
class UserCatalogGrantDetailView(drf_views.APIView):
    """Revoke one add-on install credential."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, grant_id):
        """Revoke the grant."""
        from integrations.models import CatalogGrant

        denied = _demo_denied(request.user)
        if denied:
            return denied

        grant = CatalogGrant.objects.filter(
            pk=grant_id, user=request.user, revoked_at__isnull=True
        ).first()
        if grant is None:
            return Response({"detail": "Grant not found."}, status=HTTP.NOT_FOUND)
        grant.revoked_at = timezone.now()
        grant.save(update_fields=["revoked_at"])
        return Response({"id": grant.id, "revoked": True}, status=HTTP.OK)


# /api/v1/user/oauth-applications/
class UserOAuthApplicationsView(drf_views.APIView):
    """Applications that currently hold usable OAuth credentials."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return connected applications, as the web page lists them."""
        from integrations.models import IntegrationToken
        from integrations.oauth_models import OAuthClient, OAuthRefreshToken
        from integrations.oauth_scope_info import scope_details

        now = timezone.now()
        access_tokens = list(
            IntegrationToken.objects.filter(
                user=request.user,
                client_identifier__startswith="flp_oauth_",
                revoked_at__isnull=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .order_by("-created_at")
        )
        refresh_tokens = list(
            OAuthRefreshToken.objects.select_related("client").filter(
                user=request.user, revoked_at__isnull=True, expires_at__gt=now
            )
        )
        client_ids = {token.client_identifier for token in access_tokens}
        client_ids.update(token.client.client_id for token in refresh_tokens)
        clients = {
            client.client_id: client
            for client in OAuthClient.objects.filter(client_id__in=client_ids)
        }
        results = []
        for client_id in sorted(clients, key=lambda value: clients[value].name.lower()):
            client = clients[client_id]
            mine = [t for t in access_tokens if t.client_identifier == client_id]
            refresh = [t for t in refresh_tokens if t.client_id == client.pk]
            scopes = sorted({s for t in (*mine, *refresh) for s in t.scopes})
            created = [t.created_at for t in (*mine, *refresh)]
            used = [t.last_used_at for t in mine if t.last_used_at]
            results.append(
                {
                    "client_id": client.client_id,
                    "name": client.name,
                    "scopes": scope_details(scopes),
                    "connected_at": _iso(min(created)) if created else None,
                    "last_used_at": _iso(max(used)) if used else None,
                }
            )
        return Response({"results": results}, status=HTTP.OK)


# /api/v1/user/oauth-applications/<client_id>/
class UserOAuthApplicationDetailView(drf_views.APIView):
    """Revoke every OAuth credential issued to one application."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, client_id):
        """Revoke access for the application."""
        from integrations.oauth_models import OAuthClient
        from integrations.oauth_revocation import revoke_user_client_tokens

        denied = _demo_denied(request.user)
        if denied:
            return denied

        client = OAuthClient.objects.filter(client_id=client_id).first()
        if client is None:
            return Response({"detail": "Application not found."}, status=HTTP.NOT_FOUND)
        revoke_user_client_tokens(user=request.user, client=client)
        return Response({"client_id": client_id, "revoked": True}, status=HTTP.OK)


# ----------------------------------------------------------------------- users


# /api/v1/admin/users/
class ManagedUsersView(drf_views.APIView):
    """List accounts and create one. Superusers only; credentials never scoped."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return accounts, the current user id and the page copy."""
        from users.views import (
            _managed_user_payload,
            _managed_users_labels,
            _managed_users_query,
        )

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        return Response(
            {
                "users": [
                    _managed_user_payload(member, request.user)
                    for member in _managed_users_query()
                ],
                "currentUserId": request.user.pk,
                "labels": _managed_users_labels(),
            },
            status=HTTP.OK,
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Create an account (the session view validates and enforces superuser)."""
        from users.views import create_managed_user

        return _delegate(request, create_managed_user)


# /api/v1/admin/users/<id>/
class ManagedUserDetailView(drf_views.APIView):
    """Update (activate, promote) or delete one account."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request, user_id):
        """Update role or active state."""
        from users.views import update_managed_user

        return _delegate(request, update_managed_user, user_id)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, user_id):
        """Delete the account."""
        from users.views import delete_managed_user

        return _delegate(request, delete_managed_user, user_id)


# /api/v1/admin/users/<id>/password/
class ManagedUserPasswordView(drf_views.APIView):
    """Set another account's password."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, user_id):
        """Set the password."""
        from users.views import set_managed_user_password

        return _delegate(request, set_managed_user_password, user_id)


# -------------------------------------------------------------- advanced/about


# /api/v1/user/advanced/
class AdvancedSettingsView(drf_views.APIView):
    """Advanced page state. Superuser fields are only filled for superusers."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return logs, image cache and server-port state."""
        from pathlib import Path

        from django.conf import settings
        from django.utils.dateparse import parse_datetime

        from app import image_cache
        from config import run_state
        from users.advanced_props import advanced_props as build_advanced_props
        from users.advanced_props import server_port_props
        from users.views import _first_log_time, _log_files

        user = request.user
        payload = {"isSuperuser": bool(user.is_superuser)}
        if user.is_superuser:
            stats = image_cache.cache_stats()
            log_files = _log_files(Path(settings.LOG_FILE).name)
            context = {
                "tmdb_proxy_configured": bool(user.tmdb_proxy_url),
                "image_caching_enabled": image_cache.is_enabled(),
                "image_cache_stats": stats,
                "image_cache_size": image_cache.format_bytes(stats["bytes"]),
                "bug_report_title": "[BUG] ",
                "bug_report_body": (
                    f"**Floppy version:** {settings.VERSION}\n\n"
                    "**Describe the issue:**\n\n\n**Steps to reproduce:**\n\n\n"
                    "**Logs:** attach the file downloaded from Settings > Advanced > "
                    "Download Sanitized Logs"
                ),
                "logs_since": _first_log_time(log_files[0]) if log_files else "",
                "last_unclean_exit": parse_datetime(
                    (run_state.read_state() or {}).get("last_unclean_at") or "",
                ),
            }
            props = build_advanced_props(request._request, context)
            payload.update(
                {
                    "logsSince": props["logsSince"],
                    "lastUncleanExit": props["lastUncleanExit"],
                    "bugReportUrl": props["bugReportUrl"],
                    "imageEnabled": props["imageEnabled"],
                    "imageCount": props["imageCount"],
                    "imageSize": props["imageSize"],
                    "labels": props["labels"],
                    "icons": props["icons"],
                }
            )
            port = server_port_props(request._request)
            payload["icons"].update(port["icons"])
            payload["labels"]["serverPort"] = port["labels"]
            payload["serverPort"] = {
                key: value
                for key, value in port.items()
                if key not in {"csrfToken", "labels", "icons", "urls"}
            }
        return Response(payload, status=HTTP.OK)


# /api/v1/user/advanced/image-cache/
class ImageCacheView(drf_views.APIView):
    """Toggle (PUT) or clear (DELETE) the external image cache. Superusers only."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Enable or disable external image caching."""
        from users.views import update_image_cache

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        enabled = bool(_json_body(request).get("enabled"))
        return _delegate(
            request,
            update_image_cache,
            post={"image_caching_enabled": "1" if enabled else "0"},
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request):
        """Clear every derived provider image."""
        from users.views import clear_image_cache

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        return _delegate(request, clear_image_cache, post={})


# /api/v1/user/advanced/caches/<kind>/
class CacheClearView(drf_views.APIView):
    """Clear one cache (search, history, statistics, discover) or all."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request, kind):
        """Clear the named cache."""
        from users import views

        handlers = {
            "search": views.clear_search_cache,
            "history": views.clear_history_cache,
            "statistics": views.clear_statistics_cache,
            "discover": views.clear_discover_cache,
            "all": views.clear_all_caches,
        }
        handler = handlers.get(kind)
        if handler is None:
            return Response({"detail": "Unknown cache."}, status=HTTP.NOT_FOUND)
        return _delegate(request, handler, post={})


# /api/v1/user/advanced/server-port/
class ServerPortView(drf_views.APIView):
    """Save (PUT {port}) or reset (DELETE) the server port. Superusers only."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Save the port."""
        from users.server_port_views import update_server_port

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        port = _json_body(request).get("port")
        return _delegate(
            request, update_server_port, post={"action": "save", "port": port}
        )

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def delete(self, request):
        """Remove the saved port."""
        from users.server_port_views import update_server_port

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        return _delegate(request, update_server_port, post={"action": "reset"})


# /api/v1/user/advanced/logs/
class LogsExportView(drf_views.APIView):
    """Redacted log text. Superusers only (the session view enforces it)."""

    @extend_schema(responses={200: OpenApiTypes.STR})
    def get(self, request):
        """Stream the sanitized logs."""
        from users.views import export_logs

        denied = _superuser_denied(request.user)
        if denied:
            return denied
        return export_logs(request._request)


# /api/v1/user/advanced/diagnostics/
class DiagnosticsExportView(drf_views.APIView):
    """The sanitized diagnostic report any signed-in user may download."""

    @extend_schema(responses={200: OpenApiTypes.STR})
    def get(self, request):
        """Return server details and recent warnings and errors as text."""
        from users.views import export_diagnostics

        return export_diagnostics(request._request)


# /api/v1/user/about/
class AboutSettingsView(drf_views.APIView):
    """About page data: version, release notes, resources, specs, licenses."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the same props the web About page renders."""
        from django.conf import settings

        from users import release_notes
        from users.advanced_props import about_props

        props = about_props(request._request)
        installed = release_notes.release_tag(settings.VERSION)
        releases = props["whatsNew"].get("releases") or []
        newer = [release for release in releases if release.get("newer")]
        return Response(
            {
                "version": settings.VERSION,
                "commit": settings.COMMIT_SHA_SHORT or "",
                "releaseTag": installed,
                "updateAvailable": bool(newer),
                "releases": releases,
                "releasesLoaded": props["whatsNew"].get("releasesLoaded", False),
                "releasesUrl": props["whatsNew"].get("releasesUrl", ""),
                "guideUrl": props["install"].get("guideUrl", ""),
                "sponsorUrl": props["overview"].get("sponsorUrl", ""),
                "presentation": {
                    name: {
                        "labels": props[name].get("labels", {}),
                        "icons": props[name].get("icons", {}),
                    }
                    for name in (
                        "overview", "whatsNew", "install", "resources", "specs",
                        "attributions", "licenses",
                    )
                },
                "resources": props["resources"]["items"],
                "specs": props["specs"]["items"],
                "attributions": props["attributions"]["items"],
                "licenses": props["licenses"]["items"],
            },
            status=HTTP.OK,
        )


# /api/v1/user/about/whats-new/
class WhatsNewView(drf_views.APIView):
    """Fetch release notes (network) for the About page."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return releases with installed/newer flags."""
        from users.views import whats_new

        django_request = request._request
        django_request.GET = QueryDict("format=json")
        return _delegate(request, whats_new, method="GET")


# ------------------------------------------------------------------ data


def _schedule_row(entry):
    task = entry["task"]
    return {
        "task_name": task.name,
        "frequency": entry["schedule"],
        "last_run": _iso(entry["last_run"]),
        "next_run": _iso(entry["next_run"]),
        "media_types": entry["media_types"] or [],
        "include_lists": entry["include_lists"],
        "include_collection": entry["include_collection"],
    }


# /api/v1/exports/schedules/
class ExportSchedulesView(drf_views.APIView):
    """Recurring backup export schedules."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the schedules and the exportable media types."""
        from app.models import MediaTypes
        from app.templatetags import app_tags

        tasks = request.user.get_export_tasks()
        return Response(
            {
                "results": [_schedule_row(entry) for entry in tasks["schedules"]],
                "media_types": [
                    {
                        "value": media_type.value,
                        "label": str(
                            app_tags.media_type_readable_plural(media_type.value)
                        ),
                    }
                    for media_type in MediaTypes
                    if media_type.value
                    not in (MediaTypes.EPISODE.value, MediaTypes.SEASON.value)
                ],
            },
            status=HTTP.OK,
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={201: OpenApiTypes.OBJECT})
    def post(self, request):
        """Create a recurring schedule (one-off exports use /export/csv/)."""
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        from integrations.imports.helpers import periodic_task_user_kwargs

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        frequency = body.get("frequency", "daily")
        media_types = body.get("media_types") or []
        include_lists = bool(body.get("include_lists"))
        include_collection = bool(body.get("include_collection"))
        if not isinstance(media_types, list) or not (
            media_types or include_lists or include_collection
        ):
            return Response(
                {
                    "detail": "Select at least one media type, Custom Lists, or "
                    "Collection to export.",
                },
                status=HTTP.BAD_REQUEST,
            )
        try:
            parsed_time = dt.datetime.strptime(  # noqa: DTZ007
                body.get("time", "03:00"), "%H:%M"
            ).time()
        except (TypeError, ValueError):
            return Response({"detail": "Invalid export time."}, status=HTTP.BAD_REQUEST)
        day_of_week = {"daily": "*", "2days": "*/2", "weekly": "0"}.get(frequency)
        if day_of_week is None:
            return Response(
                {"detail": "Invalid export frequency."}, status=HTTP.BAD_REQUEST
            )
        crontab, _ = CrontabSchedule.objects.get_or_create(
            hour=parsed_time.hour,
            minute=parsed_time.minute,
            day_of_week=day_of_week,
            timezone=timezone.get_default_timezone(),
        )
        for existing in PeriodicTask.objects.filter(
            task="Scheduled backup export",
            **periodic_task_user_kwargs(request.user.id),
            enabled=True,
            crontab=crontab,
        ):
            kwargs = json.loads(existing.kwargs)
            if (
                sorted(kwargs.get("media_types") or []) == sorted(media_types)
                and kwargs.get("include_lists") == include_lists
                and kwargs.get("include_collection") == include_collection
            ):
                return Response(
                    {"detail": "An identical backup schedule already exists."},
                    status=HTTP.CONFLICT,
                )
        task = PeriodicTask.objects.create(
            name=(
                f"Backup export for {request.user.username} at {parsed_time} "
                f"{frequency} ({uuid.uuid4().hex[:8]})"
            ),
            task="Scheduled backup export",
            crontab=crontab,
            kwargs=json.dumps(
                {
                    "user_id": request.user.id,
                    "media_types": media_types,
                    "include_lists": include_lists,
                    "include_collection": include_collection,
                }
            ),
            start_time=timezone.now(),
            enabled=True,
        )
        return Response({"task_name": task.name}, status=HTTP.CREATED)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def delete(self, request):
        """Delete one schedule by `task_name`."""
        from users.views import delete_export_schedule

        return _delegate(
            request,
            delete_export_schedule,
            post={"task_name": _json_body(request).get("task_name")},
        )


# /api/v1/exports/backup-status/
class ExportBackupStatusView(drf_views.APIView):
    """Where scheduled exports and database snapshots are written, and how fresh."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the web page's backup status sections (paths stay session-only)."""
        from users import views

        backup = views._backup_dir_status(request.user)
        snapshot = views._db_snapshot_status()
        return Response(
            {"sections": views.backup_panel_props(backup, snapshot)}, status=HTTP.OK
        )


# /api/v1/export/letterboxd/
class LetterboxdExportView(drf_views.APIView):
    """Stream watched movies as a Letterboxd import CSV."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Mirror the web "Export for Other Websites" Letterboxd download."""
        from django.http import StreamingHttpResponse

        from integrations import exports

        now = timezone.localtime()
        logger.info("User %s started Letterboxd CSV export", request.user.username)
        return StreamingHttpResponse(
            streaming_content=exports.generate_letterboxd_rows(request.user),
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="letterboxd_{now}.csv"',
            },
        )


# /api/v1/user/import-settings/
class UserImportSettingsView(drf_views.APIView):
    """Frequency, time and mode shared by the imports that support them."""

    @staticmethod
    def _payload(user):
        from users.models import ImportFrequencyChoices, ImportModeChoices

        return {
            "frequency": user.import_frequency,
            "time": str(user.import_time)[:5],
            "mode": user.import_mode,
            "watchlist_status": user.watchlist_import_status,
            "clz_wishlist_status": user.clz_wishlist_status,
            "frequencies": [
                {"value": value, "label": str(label)}
                for value, label in ImportFrequencyChoices.choices
            ],
            "modes": [
                {"value": value, "label": str(label)}
                for value, label in ImportModeChoices.choices
            ],
        }

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the saved import preferences and their choices."""
        return Response(self._payload(request.user), status=HTTP.OK)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def put(self, request):
        """Save any of `frequency`, `time` (HH:MM) and `mode`."""
        from users.models import ImportFrequencyChoices, ImportModeChoices

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        user = request.user
        fields = []
        if "frequency" in body:
            if body["frequency"] not in ImportFrequencyChoices.values:
                return Response({"detail": "Invalid frequency."}, status=HTTP.BAD_REQUEST)
            user.import_frequency = body["frequency"]
            fields.append("import_frequency")
        if "time" in body:
            try:
                dt.datetime.strptime(body["time"], "%H:%M")  # noqa: DTZ007
            except (TypeError, ValueError):
                return Response({"detail": "Invalid import time."}, status=HTTP.BAD_REQUEST)
            user.import_time = body["time"]
            fields.append("import_time")
        if "mode" in body:
            if body["mode"] not in ImportModeChoices.values:
                return Response({"detail": "Invalid mode."}, status=HTTP.BAD_REQUEST)
            user.import_mode = body["mode"]
            fields.append("import_mode")
        from app.models import Status

        for key, field in (
            ("watchlist_status", "watchlist_import_status"),
            ("clz_wishlist_status", "clz_wishlist_status"),
        ):
            if key in body:
                if body[key] not in Status.values:
                    return Response({"detail": "Invalid status."}, status=HTTP.BAD_REQUEST)
                setattr(user, field, body[key])
                fields.append(field)
        if fields:
            user.save(update_fields=fields)
        return Response(self._payload(user), status=HTTP.OK)


# /api/v1/exports/history/
class ExportHistoryView(drf_views.APIView):
    """Scheduled export runs of the last seven days."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return recent runs (summaries only, never tracebacks)."""
        tasks = request.user.get_export_tasks()
        return Response(
            {
                "results": [
                    {
                        "date": _iso(entry["date"]),
                        "status": entry["status"],
                        "summary": entry["summary"],
                    }
                    for entry in tasks["results"]
                ],
            },
            status=HTTP.OK,
        )


# /api/v1/user/restore/
class RestoreBackupView(drf_views.APIView):
    """Queue a restore from backup CSV text (no multipart needed by clients)."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={202: OpenApiTypes.OBJECT})
    def post(self, request):
        """Stage `content` as an upload and queue the Floppy/Yamtrack import."""
        from api.fork_views_integrations import _queue_failure_response, _resolve_mode
        from integrations import tasks
        from integrations.upload_staging import (
            enqueue_staged_task,
            stage_uploaded_file,
            staging_failure_message,
        )

        denied = _demo_denied(request.user)
        if denied:
            return denied
        mode = _resolve_mode(request)
        if mode is None:
            return Response({"detail": "Invalid mode."}, status=HTTP.BAD_REQUEST)
        content = _json_body(request).get("content")
        if not isinstance(content, str) or not content.strip():
            return Response(
                {"detail": "Choose a backup file to restore."}, status=HTTP.BAD_REQUEST
            )
        upload = SimpleUploadedFile(
            "floppy-backup.csv", content.encode("utf-8"), content_type="text/csv"
        )
        try:
            staged = str(stage_uploaded_file(upload))
        except OSError as error:
            logger.exception("Could not stage restore upload")
            return Response(
                {"detail": staging_failure_message(error)},
                status=HTTP.INSUFFICIENT_STORAGE,
            )
        try:
            task = enqueue_staged_task(
                tasks.import_yamtrack,
                user_id=request.user.id,
                file=staged,
                mode=mode,
                staged_paths=(staged,),
            )
        except Exception as error:
            logger.exception("Could not queue restore")
            return _queue_failure_response(error)
        return Response({"task_id": task.id}, status=HTTP.ACCEPTED)


# /api/v1/user/rss/
class UserRssView(drf_views.APIView):
    """Discover row feed builder data. The URL embeds the account token."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return media types, their rows and the feed URL template."""
        from django.utils.translation import gettext

        from app.discover.feeds import get_external_row_definitions
        from app.discover.registry import DISCOVER_MEDIA_TYPES
        from app.models import MediaTypes

        placeholder_type = DISCOVER_MEDIA_TYPES[0]
        placeholder_row = "trending_right_now"
        template = request.build_absolute_uri(
            reverse(
                "discover_row_feed",
                kwargs={
                    "token": request.user.token,
                    "media_type": placeholder_type,
                    "row_key": placeholder_row,
                },
            ),
        )
        template = template.replace(
            f"/{placeholder_type}/", "/MEDIA_TYPE_PLACEHOLDER/"
        ).replace(f"{placeholder_row}.xml", "ROW_KEY_PLACEHOLDER.xml")
        return Response(
            {
                "media_types": [
                    {
                        "value": media_type,
                        "label": gettext(MediaTypes(media_type).label),
                        "rows": [
                            {"key": row.key, "title": gettext(row.title)}
                            for row in get_external_row_definitions(media_type)
                        ],
                    }
                    for media_type in DISCOVER_MEDIA_TYPES
                ],
                "feed_url_template": template,
            },
            status=HTTP.OK,
        )


# /api/v1/user/rss/preview/
class UserRssPreviewView(drf_views.APIView):
    """The first items a Discover row feed would publish."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return a short preview for `media_type` and `row_key`."""
        from app.discover.feeds import (
            _parse_bool_param,
            get_external_row_definitions,
            get_feed_row,
        )

        media_type = request.GET.get("media_type", "")
        row_key = request.GET.get("row_key", "")
        if not any(
            row.key == row_key for row in get_external_row_definitions(media_type)
        ):
            return Response({"detail": "Unknown feed row."}, status=HTTP.NOT_FOUND)
        row = get_feed_row(
            request.user,
            media_type,
            row_key,
            skip_planning=_parse_bool_param(request._request, "skip_planning"),
            skip_collected=_parse_bool_param(request._request, "skip_collected"),
        )
        items = list(row.items) if row else []
        return Response(
            {
                "items": [
                    {
                        "id": f"{item.source}:{item.media_id}",
                        "title": item.title,
                        "subtitle": " · ".join(
                            part
                            for part in (
                                str(item.media_type).replace("_", " ").title(),
                                str(getattr(item, "release_date", "") or ""),
                            )
                            if part
                        ),
                    }
                    for item in items[:12]
                ],
            },
            status=HTTP.OK,
        )


# /api/v1/user/library-maintenance/
class LibraryMaintenanceView(drf_views.APIView):
    """Library repair and bulk-delete actions from the Data page danger zone."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the media types a library delete may target."""
        from app.tasks_anime_library_repair import duplicate_pair_count
        from app.templatetags import app_tags
        from users.views import DELETABLE_MEDIA_TYPES

        return Response(
            {
                "duplicate_anime_count": (
                    duplicate_pair_count(user_id=request.user.id)
                    if request.user.anime_enabled else 0
                ),
                "media_types": [
                    {
                        "value": media_type,
                        "label": str(app_tags.media_type_readable_plural(media_type)),
                    }
                    for media_type in DELETABLE_MEDIA_TYPES
                ],
            },
            status=HTTP.OK,
        )

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Run `convert_tv_library`, `repair_anime_libraries` or `delete_media_type`."""
        from users import views

        denied = _demo_denied(request.user)
        if denied:
            return denied
        body = _json_body(request)
        action = body.get("action")
        if action == "convert_tv_library":
            return _delegate(request, views.convert_tv_library, post={})
        if action == "repair_anime_libraries":
            return _delegate(request, views.repair_duplicate_anime_libraries, post={})
        if action == "delete_media_type":
            return _delegate(
                request,
                views.bulk_delete_by_media_type,
                post={
                    "media_type": body.get("media_type"),
                    "delete_metadata": bool(body.get("delete_metadata")),
                },
            )
        return Response({"detail": "Unknown action."}, status=HTTP.BAD_REQUEST)
