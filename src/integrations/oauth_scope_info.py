"""OAuth scope metadata shared by the authorisation and settings flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    ("lists:read", "Lists Read", "Read your lists, their items and collaborators."),
    ("lists:write", "Lists Write", "Create, change and delete your lists and their items."),
)

OAUTH_SCOPE_INFO = {
    scope: {"label": label, "description": description}
    for scope, label, description in OAUTH_SCOPE_OPTIONS
}
# Every scope a public client may be granted. The tracking preset
# (DEFAULT_INTEGRATION_SCOPES) stays what a client gets when it names none.
OAUTH_ALLOWED_SCOPES = frozenset(scope for scope, _label, _description in OAUTH_SCOPE_OPTIONS)


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
