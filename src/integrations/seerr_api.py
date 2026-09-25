"""Request movies and shows through the user's own Seerr instance (#772).

The URL is one the user configured for their own server, which is almost always
on the LAN, so this calls it directly like the Radarr/Sonarr clients rather than
through `safe_fetch` (which refuses private addresses by design).

No `connection_broken` bookkeeping: Seerr answers 403 both for a bad API key and
for a permission or quota refusal, so a rejected call cannot be read as rejected
credentials (see docs/architecture/connection-health.md). Errors are shown in
the request panel instead.
"""

import requests

from app.log_safety import exception_summary
from app.models import MediaTypes
from integrations.imports.helpers import decrypt_or_raise

MEDIA_STATUSES = {
    1: "unknown",
    2: "pending",
    3: "processing",
    4: "partially_available",
    5: "available",
    6: "blocklisted",
    7: "deleted",
}
REQUESTABLE_STATUSES = {"unknown", "deleted"}
USER_NAME_FIELDS = ("username", "email", "plexUsername", "jellyfinUsername")
ACTIVE_REQUEST_STATUSES = {1, 2}


class SeerrError(Exception):
    """Seerr could not be reached or refused the call."""


class SeerrClient:
    """Thin client for the two Seerr v1 endpoints Floppy needs."""

    def __init__(self, base_url, api_key):
        """Store the connection settings."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @classmethod
    def for_user(cls, user):
        """Build a client from the user's stored Seerr settings."""
        return cls(user.seerr_url, decrypt_or_raise(user.seerr_api_key))

    def _call(self, method, path, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}/api/v1{path}",
                headers={"X-Api-Key": self.api_key},
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as error:
            # Not str(error): it carries the configured URL (outbound-fetch.md).
            msg = f"Could not reach Seerr ({exception_summary(error)})"
            raise SeerrError(msg) from error
        if not response.ok:
            try:
                detail = response.json().get("message") or ""
            except ValueError:
                detail = ""
            msg = f"Seerr refused the request ({response.status_code}) {detail}"
            raise SeerrError(msg.strip())
        return response.json() if response.content else {}

    def media(self, media_type, tmdb_id):
        """Return Seerr's view of a movie or show, request state included."""
        return self._call("GET", f"/{media_type}/{tmdb_id}")

    def find_user_id(self, name):
        """Return the id of the Seerr user whose login is exactly `name`."""
        wanted = name.strip().lower()
        data = self._call("GET", "/user", params={"q": wanted, "take": 50})
        # The search is a substring match, so keep exact (case-insensitive) hits.
        ids = {
            user["id"]
            for user in data.get("results") or []
            if wanted
            in {str(user.get(field) or "").lower() for field in USER_NAME_FIELDS}
        }
        if len(ids) != 1:
            msg = (
                f"No Seerr user named '{name}'."
                if not ids
                else f"Several Seerr users match '{name}'; use their email."
            )
            raise SeerrError(msg)
        return ids.pop()

    def request(self, media_type, tmdb_id, user_id, seasons=None):
        """Create a request as Seerr user `user_id`; `seasons` None means all."""
        body = {"mediaType": media_type, "mediaId": tmdb_id, "userId": user_id}
        if media_type == MediaTypes.TV.value:
            body["seasons"] = seasons or "all"
        return self._call("POST", "/request", json=body)


def summarize(media_type, data):
    """Reduce a Seerr media payload to what the request panel renders."""
    media_info = data.get("mediaInfo") or {}
    status = MEDIA_STATUSES.get(media_info.get("status", 1), "unknown")
    if media_type == MediaTypes.MOVIE.value:
        return {"status": status, "requestable": status in REQUESTABLE_STATUSES}

    season_statuses = {
        season.get("seasonNumber"): MEDIA_STATUSES.get(
            season.get("status", 1), "unknown"
        )
        for season in media_info.get("seasons") or []
    }
    requested = {
        season.get("seasonNumber")
        for request in media_info.get("requests") or []
        if request.get("status") in ACTIVE_REQUEST_STATUSES
        for season in request.get("seasons") or []
    }
    seasons = []
    # Specials are skipped, matching Seerr's own "all" expansion.
    for season in data.get("seasons") or []:
        number = season.get("seasonNumber")
        if not number or not season.get("episodeCount"):
            continue
        season_status = season_statuses.get(number, "unknown")
        if season_status in REQUESTABLE_STATUSES and number in requested:
            season_status = "pending"
        seasons.append(
            {
                "number": number,
                "name": season.get("name") or f"Season {number}",
                "status": season_status,
                "requestable": season_status in REQUESTABLE_STATUSES,
            }
        )
    return {
        "status": status,
        "seasons": seasons,
        "requestable": any(season["requestable"] for season in seasons),
    }
