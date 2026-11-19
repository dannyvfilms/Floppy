"""OAuth scope metadata shared by the authorisation and settings flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

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

# The built-in Floppy app's device-flow client. Registered ids are
# ``flp_oauth_`` plus 32 random characters, so registration can never produce
# this one; the prefix keeps it listed and revocable with other applications.
FIRST_PARTY_CLIENT_ID = "flp_oauth_floppy_app"
FIRST_PARTY_CLIENT_NAME = "Floppy app (full access)"
# The full-account marker. Never in OAUTH_ALLOWED_SCOPES or api.scopes.ALL_SCOPES,
# so no client can request it and no settings-made token can hold it: the device
# flow adds it server-side, only for FIRST_PARTY_CLIENT_ID.
FULL_ACCOUNT_SCOPE = "floppy:account"
FULL_ACCOUNT_INFO = {
    "label": "Full account access",
    "description": "Everything you can do when signed in, including account settings, connections and tokens.",
}


def first_party_full_access_enabled() -> bool:
    """Return whether the Floppy app may hold full account access (the kill switch)."""
    return bool(getattr(settings, "FLOPPY_APP_FULL_ACCESS", False))


def has_full_account_access(token) -> bool:
    """Return whether a token is a first-party Floppy app token with full access.

    Both the issuing client and the server-added marker must match, and the
    setting must be on, so turning it off withdraws access from live tokens.
    """
    if token is None or not first_party_full_access_enabled():
        return False
    return getattr(token, "client_identifier", "") == FIRST_PARTY_CLIENT_ID and (
        FULL_ACCOUNT_SCOPE in (getattr(token, "scopes", None) or [])
    )


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
    info = {**OAUTH_SCOPE_INFO, FULL_ACCOUNT_SCOPE: FULL_ACCOUNT_INFO}
    return [
        {
            "scope": scope,
            "label": info.get(scope, {}).get("label", scope),
            "description": info.get(scope, {}).get("description", "This application requested this permission."),
        }
        for scope in sorted(scopes, key=lambda value: value != FULL_ACCOUNT_SCOPE)
    ]
