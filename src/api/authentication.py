from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from users.models import User


class BearerAuthentication(BaseAuthentication):
    """Bearer Authentication."""

    keyword = "Bearer"

    def authenticate(self, request):
        """Authenticate the user with Bearer token."""
        auth = request.headers.get("Authorization")
        if not auth:
            return None
        parts = auth.split()
        if len(parts) != 2 or parts[0] != self.keyword:  # noqa: PLR2004
            return None
        token = parts[1]
        try:
            user = User.objects.get(token=token)
        except User.DoesNotExist:
            msg = "Invalid token"
            raise AuthenticationFailed(msg) from None
        return (user, None)


class ListenBrainzTokenAuthentication(BaseAuthentication):
    """ListenBrainz-style `Authorization: Token <token>` authentication.

    Exists so ListenBrainz-compatible scrobble clients (Multi-Scrobbler,
    Navidrome, Pano Scrobbler, ...) can authenticate against the ingest
    endpoints. Uses the same `User.token` as the rest of the API.
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
        try:
            user = User.objects.get(token=token)
        except User.DoesNotExist:
            msg = "Invalid token"
            raise AuthenticationFailed(msg) from None
        return (user, None)


class APIKeyAuthentication(BaseAuthentication):
    """API Key Authentication."""

    def authenticate(self, request):
        """Authenticate the user with API Key."""
        auth = request.headers.get("X-API-Key")
        if not auth:
            return None
        try:
            user = User.objects.get(token=auth)
        except User.DoesNotExist:
            msg = "Invalid token"
            raise AuthenticationFailed(msg) from None
        return (user, None)
