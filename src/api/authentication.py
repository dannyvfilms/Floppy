"""Authentication classes for API requests."""

import hashlib
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from api.scopes import ANY_SCOPE, NEVER, resolve_required_scope
from integrations.models import IntegrationToken
from users.models import User

# Bound how often a request writes ``last_used_at``. Every authenticated request
# would otherwise write a row, which is the hot path for a scrobbling client.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)


def _touch_last_used(token: IntegrationToken) -> None:
    """Record token use, at most once per :data:`LAST_USED_WRITE_INTERVAL`."""
    now = timezone.now()
    if token.last_used_at and now - token.last_used_at < LAST_USED_WRITE_INTERVAL:
        return
    # Filtered UPDATE rather than save(): concurrent requests collapse into one
    # write instead of racing, and no other field can be clobbered.
    IntegrationToken.objects.filter(pk=token.pk).update(last_used_at=now)
    token.last_used_at = now


def authenticate_token(raw_token: str):
    """Authenticate raw token against IntegrationToken or fallback to User.token."""
    if not raw_token:
        msg = "Invalid token"
        raise AuthenticationFailed(msg)

    token_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    try:
        integration_token = IntegrationToken.objects.select_related("user").get(
            token_digest=token_digest
        )
    except IntegrationToken.DoesNotExist:
        pass
    else:
        if not integration_token.is_valid():
            msg = "Invalid token"
            raise AuthenticationFailed(msg)
        _touch_last_used(integration_token)
        return (integration_token.user, integration_token)

    try:
        user = User.objects.get(token=raw_token)
    except User.DoesNotExist:
        msg = "Invalid token"
        raise AuthenticationFailed(msg) from None
    return (user, None)


class BearerAuthentication(BaseAuthentication):
    """Bearer or Token Authorization header authentication."""

    keywords = ("bearer", "token")

    def authenticate(self, request):
        """Authenticate the user with Bearer or Token header."""
        auth = request.headers.get("Authorization")
        if not auth:
            return None
        parts = auth.split()
        if len(parts) != 2 or parts[0].lower() not in self.keywords:  # noqa: PLR2004
            return None
        token = parts[1]
        return authenticate_token(token)


class ListenBrainzTokenAuthentication(BaseAuthentication):
    """ListenBrainz-style `Authorization: Token <token>` authentication.

    Exists so ListenBrainz-compatible scrobble clients (Multi-Scrobbler,
    Navidrome, Pano Scrobbler, ...) can authenticate against the ingest
    endpoints. Supports both IntegrationToken and legacy User.token.
    """

    keyword = "Token"

    def authenticate_header(self, request):
        """Return the WWW-Authenticate value so DRF answers 401, not 403.

        The ListenBrainz protocol specifies 401 for a missing or invalid token,
        and clients branch on it.
        """
        return self.keyword

    def authenticate(self, request):
        """Authenticate the user with a ListenBrainz-style token."""
        auth = request.headers.get("Authorization")
        if not auth:
            return None
        parts = auth.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():  # noqa: PLR2004
            return None
        token = parts[1]
        return authenticate_token(token)


class APIKeyAuthentication(BaseAuthentication):
    """API Key Authentication via X-API-Key header."""

    def authenticate(self, request):
        """Authenticate the user with API Key."""
        auth = request.headers.get("X-API-Key")
        if not auth:
            return None
        return authenticate_token(auth.strip())


class HasScope(BasePermission):
    """Enforce the scope map against the credential the request authenticated with.

    Session logins and legacy ``User.token`` credentials carry no token object
    (``request.auth is None``) and keep full access. A scoped ``IntegrationToken``
    must hold the scope ``api.scopes`` maps to this view and method; an unmapped
    endpoint is denied, so a new route cannot silently become reachable.
    """

    required_scope = None

    def __init__(self, required_scope=None):
        """Initialize permission class with an optional required scope."""
        if required_scope is not None:
            self.required_scope = required_scope

    def has_permission(self, request, view):
        """Return True if the request user and token scopes satisfy requirements."""
        if not request.user or not request.user.is_authenticated:
            return False

        token = request.auth
        if token is None or not hasattr(token, "has_scope"):
            return True

        scope = self.required_scope or resolve_required_scope(view, request.method)
        if scope == ANY_SCOPE:
            return True
        if scope is None or scope == NEVER:
            return False
        return token.has_scope(scope)


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CanWriteBoundList(BasePermission):
    """Restrict a scoped token's list writes to the lists it is bound to.

    Installed globally rather than per view: there are thirteen list-writing
    endpoints across two modules, and a per-view opt-in is a control that gets
    forgotten the fourteenth time.

    Two rules:

    - a token with a populated ``writable_list_ids`` may write only those lists
    - no external token may write a smart list, whatever it is bound to, because
      a computed list's contents come from its rules and an external write would
      be silently recomputed away
    """

    def has_permission(self, request, view):
        """Return whether this request may write the list it names."""
        token = request.auth
        if token is None or not hasattr(token, "may_write_list"):
            return True
        if request.method in SAFE_METHODS:
            return True

        list_id = (getattr(view, "kwargs", None) or {}).get("list_id")
        if list_id is None:
            return True

        if not token.may_write_list(list_id):
            return False

        from lists.models import CustomList

        return not CustomList.objects.filter(pk=list_id, is_smart=True).exists()
