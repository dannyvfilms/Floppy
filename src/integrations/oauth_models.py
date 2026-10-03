"""Models for Floppy's public-client OAuth device flow."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from integrations.models import DEFAULT_INTEGRATION_SCOPES, IntegrationToken

OAUTH_DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
OAUTH_REFRESH_TOKEN_GRANT = "refresh_token"  # noqa: S105
OAUTH_SUPPORTED_GRANT_TYPES = (
    OAUTH_DEVICE_CODE_GRANT,
    OAUTH_REFRESH_TOKEN_GRANT,
)

OAUTH_DEVICE_CODE_LIFETIME_SECONDS = 600
OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS = 3600
OAUTH_REFRESH_TOKEN_LIFETIME_SECONDS = 90 * 24 * 60 * 60
OAUTH_DEVICE_POLL_INTERVAL_SECONDS = 5

_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def oauth_token_digest(raw_token: str) -> str:
    """Return the SHA-256 digest used for transient OAuth secrets."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def default_oauth_grant_types() -> list[str]:
    """Return the supported public-client grant types."""
    return list(OAUTH_SUPPORTED_GRANT_TYPES)


def default_oauth_scopes() -> list[str]:
    """Return a fresh copy of Floppy's supported integration scopes."""
    return list(DEFAULT_INTEGRATION_SCOPES)


def normalise_user_code(user_code: str) -> str:
    """Canonicalise a human-entered device user code."""
    return "".join(character for character in user_code.upper() if character.isalnum())


class OAuthClient(models.Model):
    """Registered public OAuth client allowed to use Floppy's device flow."""

    client_id = models.CharField(max_length=96, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    allowed_scopes = models.JSONField(default=default_oauth_scopes)
    grant_types = models.JSONField(default=default_oauth_grant_types)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model metadata."""

        app_label = "integrations"
        ordering = ["name", "client_id"]

    def __str__(self) -> str:
        """Return a compact client description."""
        return f"OAuthClient({self.name}, {self.client_id})"

    @property
    def is_active(self) -> bool:
        """Return whether the client is still permitted to authorise users."""
        return self.revoked_at is None

    @classmethod
    def register_public_client(
        cls,
        *,
        name: str,
        allowed_scopes: list[str] | None = None,
        grant_types: list[str] | None = None,
        client_type: str = "public",
    ) -> OAuthClient:
        """Register a public OAuth client with explicit scope/grant restrictions."""
        if client_type != "public":
            msg = "Floppy currently supports public OAuth clients only."
            raise ValueError(msg)

        clean_name = name.strip()
        if not clean_name:
            msg = "OAuth client name is required."
            raise ValueError(msg)

        scopes = list(
            dict.fromkeys(
                allowed_scopes
                if allowed_scopes is not None
                else DEFAULT_INTEGRATION_SCOPES
            )
        )
        unknown_scopes = set(scopes) - set(DEFAULT_INTEGRATION_SCOPES)
        if not scopes or unknown_scopes:
            msg = "OAuth clients require one or more supported scopes."
            raise ValueError(msg)

        grants = list(
            dict.fromkeys(
                grant_types if grant_types is not None else OAUTH_SUPPORTED_GRANT_TYPES
            )
        )
        unsupported_grants = set(grants) - set(OAUTH_SUPPORTED_GRANT_TYPES)
        if not grants or unsupported_grants:
            msg = "OAuth client grant types are not supported."
            raise ValueError(msg)

        return cls.objects.create(
            client_id=f"flp_oauth_{secrets.token_urlsafe(24)}",
            name=clean_name,
            allowed_scopes=scopes,
            grant_types=grants,
        )

    def allows_scope(self, scope: str) -> bool:
        """Return whether this active client may request the supplied scope."""
        return self.is_active and scope in self.allowed_scopes

    def allows_grant_type(self, grant_type: str) -> bool:
        """Return whether this active client may use the supplied grant type."""
        return self.is_active and grant_type in self.grant_types

    def revoke(self) -> None:
        """Revoke the client and every OAuth credential issued through it."""
        revoked_at = self.revoked_at or timezone.now()
        if self.revoked_at is None:
            self.revoked_at = revoked_at
            self.save(update_fields=["revoked_at"])

        self.refresh_tokens.filter(revoked_at__isnull=True).update(
            revoked_at=revoked_at
        )
        IntegrationToken.objects.filter(
            client_identifier=self.client_id,
            revoked_at__isnull=True,
        ).update(revoked_at=revoked_at)


class OAuthDeviceAuthorization(models.Model):
    """Short-lived device authorisation awaiting an interactive user decision."""

    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.CASCADE,
        related_name="device_authorizations",
    )
    device_code_digest = models.CharField(max_length=64, unique=True, db_index=True)
    user_code_digest = models.CharField(max_length=64, unique=True, db_index=True)
    requested_scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    interval = models.PositiveSmallIntegerField(
        default=OAUTH_DEVICE_POLL_INTERVAL_SECONDS
    )
    last_polled_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_device_authorizations",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    denied_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model metadata."""

        app_label = "integrations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Return a compact device authorisation description."""
        return f"OAuthDeviceAuthorization({self.client.client_id}, {self.pk})"

    @classmethod
    def issue(
        cls,
        *,
        client: OAuthClient,
        requested_scopes: list[str],
    ) -> tuple[OAuthDeviceAuthorization, str, str]:
        """Create an authorisation while storing only digests of its raw codes."""
        raw_device_code = f"flp_device_{secrets.token_urlsafe(32)}"
        raw_user_code = "".join(
            secrets.choice(_USER_CODE_ALPHABET) for _ in range(8)
        )
        display_user_code = f"{raw_user_code[:4]}-{raw_user_code[4:]}"
        authorization = cls.objects.create(
            client=client,
            device_code_digest=oauth_token_digest(raw_device_code),
            user_code_digest=oauth_token_digest(raw_user_code),
            requested_scopes=requested_scopes,
            expires_at=timezone.now()
            + timedelta(seconds=OAUTH_DEVICE_CODE_LIFETIME_SECONDS),
        )
        return authorization, raw_device_code, display_user_code

    @classmethod
    def for_user_code(
        cls,
        raw_user_code: str,
    ) -> OAuthDeviceAuthorization | None:
        """Resolve a human user code without storing the plaintext value."""
        normalized = normalise_user_code(raw_user_code)
        if not normalized:
            return None
        return (
            cls.objects.select_related("client", "user")
            .filter(user_code_digest=oauth_token_digest(normalized))
            .first()
        )

    @property
    def is_expired(self) -> bool:
        """Return whether this authorisation has passed its deadline."""
        return timezone.now() >= self.expires_at

    @property
    def is_terminal(self) -> bool:
        """Return whether no further approval decision may be made."""
        return any(
            (
                self.is_expired,
                self.approved_at is not None,
                self.denied_at is not None,
                self.consumed_at is not None,
            )
        )

    def approve(self, user: models.Model) -> None:
        """Approve this request for the authenticated user."""
        if self.is_terminal:
            msg = "This device authorisation can no longer be approved."
            raise ValueError(msg)
        self.user = user
        self.approved_at = timezone.now()
        self.save(update_fields=["user", "approved_at"])

    def deny(self, user: models.Model) -> None:
        """Deny this request for the authenticated user."""
        if self.is_terminal:
            msg = "This device authorisation can no longer be denied."
            raise ValueError(msg)
        self.user = user
        self.denied_at = timezone.now()
        self.save(update_fields=["user", "denied_at"])


class OAuthRefreshToken(models.Model):
    """Rotating refresh credential associated with a scoped access token."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_refresh_tokens",
    )
    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    access_token = models.ForeignKey(
        "integrations.IntegrationToken",
        on_delete=models.SET_NULL,
        related_name="oauth_refresh_tokens",
        null=True,
        blank=True,
    )
    token_digest = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(max_length=20, blank=True, default="")
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        related_name="replaces",
        null=True,
        blank=True,
    )

    class Meta:
        """Model metadata."""

        app_label = "integrations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """Return a compact refresh-token description."""
        return f"OAuthRefreshToken({self.client.client_id}, {self.user_id})"

    @classmethod
    def generate(
        cls,
        *,
        user: models.Model,
        client: OAuthClient,
        access_token: models.Model,
        scopes: list[str],
        rotated_from: OAuthRefreshToken | None = None,
    ) -> tuple[OAuthRefreshToken, str]:
        """Create a digest-only rotating refresh credential."""
        raw_token = f"flp_refresh_{secrets.token_urlsafe(40)}"
        refresh_token = cls.objects.create(
            user=user,
            client=client,
            access_token=access_token,
            token_digest=oauth_token_digest(raw_token),
            token_prefix=raw_token[:16],
            scopes=scopes,
            expires_at=timezone.now()
            + timedelta(seconds=OAUTH_REFRESH_TOKEN_LIFETIME_SECONDS),
        )
        if rotated_from is not None:
            rotated_from.replaced_by = refresh_token
            rotated_from.save(update_fields=["replaced_by"])
        return refresh_token, raw_token

    @property
    def is_valid(self) -> bool:
        """Return whether this refresh token may still be exchanged."""
        return self.revoked_at is None and timezone.now() < self.expires_at

    def revoke(self) -> None:
        """Revoke this refresh token."""
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])
