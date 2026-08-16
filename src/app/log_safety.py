"""Helpers for security-conscious logging and stable keyed digests."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

# Keywords that end the name of a value that carries a secret across Floppy's
# integrations (Plex, Jellyfin, Trakt, TMDB, Last.fm, Koito, Pocket Casts,
# gpodder, Stremio). Match the keyword at the end of the name and allow any
# prefix, because the same credential reaches the log in many spellings:
# "access_token", "authToken", "X-Plex-Token", "X-Api-Key", "TMDB_API_KEY".
# A list of exact spellings cannot cover them and lets secrets through.
_SECRET_NAME_KEYWORDS = (
    "token",
    "secret",
    "password",
    "passwd",
    "apikey",
    "npsso",
    "api_key",
    "api-key",
    "sessionid",
)
# Match the keyword alone and let the name prefix stay where it is. The rules
# below require a "=" or a ":" directly after the keyword, so the keyword must
# be the last part of the name: "token_count=512", "status_code=200" and
# "tokenizer_config=default" stay readable.
_SECRET_NAME_PATTERN = "|".join(
    re.escape(keyword) for keyword in _SECRET_NAME_KEYWORDS
)

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.~+/]+=*"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/]+=*"),
        "Basic [REDACTED]",
    ),
    (
        re.compile(r"(?im)\b(Authorization|Cookie|Set-Cookie)\s*:\s*[^\r\n]+"),
        r"\1: [REDACTED]",
    ),
    (
        # Remove credentials from URLs such as proxy and database connection
        # strings. The host and path stay visible for diagnosis.
        # The user part excludes ":" so that only one split of "user:password"
        # is possible. If both parts accept ":", a long line that holds a
        # scheme and many colons but no "@" makes the engine try every split,
        # which costs seconds of processor time for one log record.
        re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)([^:/@\s]*):([^@/\s]{1,256})@"),
        r"\1[REDACTED]:[REDACTED]@",
    ),
    (
        # List values, such as the QueryDict repr Django writes for form data:
        # {'password': ['secret']}. Redact the full list. Without this rule the
        # unquoted rule below stops at the first quote and leaves the value.
        re.compile(
            rf"(?i)({_SECRET_NAME_PATTERN})([\"']?\s*[=:]\s*)\[[^\]\r\n]*\]",
        ),
        r"\1\2[REDACTED]",
    ),
    (
        # Quoted JSON, Python repr, and assignment values can contain spaces.
        re.compile(
            rf'(?i)({_SECRET_NAME_PATTERN})(["\']?\s*[=:]\s*)'
            r'"(?:\\.|[^"\\\r\n])*"',
        ),
        r'\1\2"[REDACTED]"',
    ),
    (
        re.compile(
            rf"(?i)({_SECRET_NAME_PATTERN})([\"']?\s*[=:]\s*)"
            r"'(?:\\.|[^'\\\r\n])*'",
        ),
        r"\1\2'[REDACTED]'",
    ),
    (
        # Unquoted URL, form, header, and assignment values stop at the next
        # delimiter. Quoted and list values are handled by the rules above, so
        # this rule does not start on a quote or a bracket.
        re.compile(
            rf"(?i)({_SECRET_NAME_PATTERN})[\"']?\s*[=:]\s*"
            r"[^&\s\"'<>\[\]]+",
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


_REDACTING_FACTORY_MARKER = "_floppy_redacts_secrets"


def install_redacting_log_record_factory() -> None:
    """Redact each Python log record before any handler can write it."""
    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, _REDACTING_FACTORY_MARKER, False):
        return

    exception_formatter = logging.Formatter()

    def redacting_factory(*args, **kwargs):
        record = current_factory(*args, **kwargs)
        try:
            # Resolve lazy %-style arguments once, then store only the redacted
            # text. All handlers receive the same safe record.
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
            if record.exc_info:
                record.exc_text = redact_secrets(
                    exception_formatter.formatException(record.exc_info),
                )
                # Structured handlers can inspect LogRecord attributes without
                # using Formatter. Keep only the safe exception text.
                record.exc_info = None
            if record.stack_info:
                record.stack_info = redact_secrets(record.stack_info)
        except Exception:
            # Do not send the original record to a handler when rendering or
            # redaction fails. Logging must not expose data or interrupt work.
            record.msg = "Log message redaction failed"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return record

    setattr(redacting_factory, _REDACTING_FACTORY_MARKER, True)
    logging.setLogRecordFactory(redacting_factory)


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
    """Return a URL with credentials, query parameters and fragments removed.

    Credentials travel in three places in a URL. Query parameters carry them in
    public feeds, fragments carry them in OAuth redirects, and the authority
    carries them as ``user:password@`` in private podcast feeds and in Redis and
    database connection strings. All three are dropped here rather than matched
    by pattern: a URL has structure, and parsing that structure cannot miss a
    spelling the way a keyword list can.
    """
    if not value:
        return ""

    parts = urlsplit(str(value))
    if not parts.scheme and not parts.netloc:
        return parts.path

    # Rebuild the authority from its host and port so any userinfo is left
    # behind. The port is absent from most URLs and ``parts.port`` is then None,
    # which an unconditional f-string would render as the text "None".
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


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
