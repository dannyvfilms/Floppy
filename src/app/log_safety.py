"""Helpers for security-conscious logging and stable keyed digests."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

# Query/form/header param names that commonly carry secrets across Floppy's
# integrations (Plex, Jellyfin, Trakt, TMDB, Last.fm, Koito, Pocket Casts,
# gpodder, Stremio). Matches "name=value" (URL/form encoded) up to the next
# delimiter, or "Name: value" (header style) to end of line.
_SECRET_PARAM_NAMES = (
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "client_secret",
    "client_id",
    "password",
    "passwd",
    "secret",
    "x-plex-token",
)

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.~+/]+=*"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(" + "|".join(_SECRET_PARAM_NAMES) + r")\s*[=:]\s*[^&\s\"'<>]+"
        ),
        r"\1=[REDACTED]",
    ),
]


def redact_secrets(text: str) -> str:
    """Strip common secret/token patterns out of raw log text.

    Unlike the structured helpers below, this scrubs text that may already
    contain a raw token (e.g. logged before a call site adopted these
    conventions, or from a third-party library's own log lines).
    """
    if not text:
        return ""

    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def exception_summary(exc: BaseException | None) -> str:
    """Return a compact exception summary without request data."""
    if exc is None:
        return "unknown"

    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    name = type(exc).__name__
    if status_code is not None:
        return f"{name}(status={status_code})"
    return name


def mapping_keys(value: Any) -> list[str]:
    """Return sorted mapping keys for safe structural logging."""
    if not isinstance(value, Mapping):
        return []
    return sorted(str(key) for key in value)


def presence_map(
    values: Mapping[str, Any] | None, keys: Iterable[str]
) -> dict[str, bool]:
    """Return whether selected keys are present/truthy without exposing values."""
    mapping = values if isinstance(values, Mapping) else {}
    return {str(key): bool(mapping.get(key)) for key in keys}


def safe_url(value: str | None) -> str:
    """Return a URL with query parameters and fragments removed."""
    if not value:
        return ""

    parts = urlsplit(str(value))
    if not parts.scheme and not parts.netloc:
        return parts.path
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def stable_hmac(value: str, *, namespace: str, length: int | None = None) -> str:
    """Return a deterministic keyed digest suitable for cache and dedupe keys."""
    message = f"{namespace}:{value}".encode()
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    if length is not None:
        return digest[:length]
    return digest
