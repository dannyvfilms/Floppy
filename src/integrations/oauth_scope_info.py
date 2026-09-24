"""OAuth scope metadata shared by the authorisation and settings flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from integrations.models import DEFAULT_INTEGRATION_SCOPES

if TYPE_CHECKING:
    from collections.abc import Iterable

OAUTH_SCOPE_OPTIONS = (
    ("catalog:read", "Catalog Read", "Read provider-backed catalogue metadata."),
    ("progress:read", "Progress Read", "Read watch history and playback progress."),
    ("progress:write", "Progress Write", "Update watched state and playback progress."),
    ("watchlist:read", "Library State Read", "Read tracked library state and collections."),
    ("watchlist:write", "Library State Write", "Change tracked library state and collections."),
    ("scrobble:write", "Scrobble Write", "Submit playback and ListenBrainz events."),
    ("sync:read", "Sync Read", "Read sync connections, change feeds and conflicts."),
)

OAUTH_SCOPE_INFO = {
    scope: {"label": label, "description": description}
    for scope, label, description in OAUTH_SCOPE_OPTIONS
}
OAUTH_ALLOWED_SCOPES = frozenset(DEFAULT_INTEGRATION_SCOPES)


def normalise_scopes(scopes: str | Iterable[str] | None, *, default: Iterable[str] = ()) -> list[str]:
    """Return a stable, deduplicated OAuth scope list."""
    if scopes is None:
        values = list(default)
    elif isinstance(scopes, str):
        values = scopes.split()
    else:
        values = [str(scope) for scope in scopes]
    return list(dict.fromkeys(scope.strip() for scope in values if scope.strip()))


def serialise_scopes(scopes: Iterable[str]) -> str:
    """Serialise scopes using the OAuth space-delimited representation."""
    return " ".join(scopes)


def scope_details(scopes: Iterable[str]) -> list[dict[str, str]]:
    """Return human-readable metadata for the supplied scopes."""
    return [
        {
            "scope": scope,
            "label": OAUTH_SCOPE_INFO.get(scope, {}).get("label", scope),
            "description": OAUTH_SCOPE_INFO.get(scope, {}).get("description", "This application requested this permission."),
        }
        for scope in scopes
    ]
