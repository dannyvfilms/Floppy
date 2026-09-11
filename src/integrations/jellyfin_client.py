"""Thin REST client for pushing watched state to a Jellyfin server."""

import logging
from http import HTTPStatus

import requests

logger = logging.getLogger(__name__)

LIBRARY_PAGE_SIZE = 500


class JellyfinClientError(Exception):
    """Base Jellyfin API error."""


class JellyfinAuthError(JellyfinClientError):
    """Raised when the Jellyfin API key is invalid or unauthorized."""


class JellyfinClient:
    """Client for the subset of the Jellyfin REST API needed to push watched state."""

    def __init__(self, base_url: str, api_key: str, user_id: str | None = None):
        """Store the extra keyword arguments this form needs."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f'MediaBrowser Token="{self.api_key}"',
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=15,
                **kwargs,
            )
        except requests.RequestException as exc:
            msg = f"Could not reach Jellyfin: {exc}"
            raise JellyfinClientError(msg) from exc

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            msg = "Jellyfin API key is invalid or unauthorized"
            raise JellyfinAuthError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            body_snippet = (response.text or "").strip()[:200]
            logger.warning(
                "Jellyfin request failed: %s %s -> %s %s",
                method,
                path,
                response.status_code,
                body_snippet,
            )
            message = f"Jellyfin request failed ({response.status_code}) for {path}"
            if body_snippet:
                message = f"{message}: {body_snippet}"
            raise JellyfinClientError(message)
        return response

    def healthcheck(self) -> dict:
        """Verify the server is reachable and the API key is valid."""
        return self._request("GET", "/System/Info").json()

    def get_current_user(self) -> dict | None:
        """Resolve the Jellyfin user tied to this API key, if any.

        Dashboard API keys have no user context, so Jellyfin answers
        /Users/Me with a 4xx; treat that as "no user" rather than an error
        so callers can fall back to a username lookup.
        """
        try:
            response = self._request("GET", "/Users/Me")
        except JellyfinAuthError:
            raise
        except JellyfinClientError:
            return None
        if not response.content:
            return None
        return response.json()

    def find_user_by_name(self, username: str) -> dict | None:
        """Fall back lookup for server-admin API keys that can't resolve Users/Me."""
        users = self._request("GET", "/Users").json()
        for user in users:
            if str(user.get("Name", "")).strip().lower() == username.strip().lower():
                return user
        return None

    def iter_library_items(self):
        """Yield Movie/Episode/Series items with provider ids and play state."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)

        start_index = 0
        while True:
            payload = self._request(
                "GET",
                f"/Users/{self.user_id}/Items",
                params={
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Episode,Series",
                    "Fields": "ProviderIds",
                    "StartIndex": start_index,
                    "Limit": LIBRARY_PAGE_SIZE,
                },
            ).json()

            items = payload.get("Items") or []
            yield from items

            start_index += len(items)
            total = payload.get("TotalRecordCount", start_index)
            if not items or start_index >= total:
                break

    def find_item_by_provider_id(self, provider: str, provider_id: str):
        """Return the single item matching one provider id, or None.

        Returns None when the query matches nothing *or* more than one thing.
        An ambiguous match must not become a write: picking one of two
        candidates would eventually mark the wrong episode watched.
        """
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)

        payload = self._request(
            "GET",
            f"/Users/{self.user_id}/Items",
            params={
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Episode",
                "Fields": "ProviderIds",
                "AnyProviderIdEquals": f"{provider.lower()}.{provider_id}",
                "Limit": 2,
            },
        ).json()

        items = payload.get("Items") or []
        if len(items) != 1:
            return None
        return items[0]

    def get_item_user_data(self, item_id: str):
        """Return one item's UserData for the connected user, or None.

        Used to read back what a write actually did, and to check state before
        retrying an uncertain write.
        """
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)

        payload = self._request(
            "GET",
            f"/Users/{self.user_id}/Items/{item_id}",
        ).json()
        return payload.get("UserData")

    def mark_played(self, item_id: str) -> None:
        """Mark a Jellyfin item as played for the connected user."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)
        self._request("POST", f"/Users/{self.user_id}/PlayedItems/{item_id}")

    def mark_unplayed(self, item_id: str) -> None:
        """Mark a Jellyfin item as unplayed for the connected user."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)
        self._request("DELETE", f"/Users/{self.user_id}/PlayedItems/{item_id}")

    def probe_playback_reporting(self) -> bool:
        """Return True when the Playback Reporting plugin's API is reachable.

        Every route on this controller requires an admin ("RequiresElevation")
        API key, so a regular user's key returns False here just like a
        missing plugin does -- both mean "fall back to the core-API tier".
        """
        try:
            self._request("GET", "/user_usage_stats/type_filter_list")
        except JellyfinClientError:
            return False
        return True

    def fetch_playback_activity(self, since_rowid: int, limit: int) -> list[dict]:
        """Return new Playback Reporting rows (with ``rowid``) after ``since_rowid``.

        Uses the plugin's ``submit_custom_query`` endpoint, the same table
        its own TSV export reads from, ordered by rowid for stable
        pagination/cursoring.
        """
        # ints coerced above, not user-controlled strings
        query = (
            "SELECT rowid, DateCreated, UserId, ItemId, ItemType, ItemName, "  # noqa: S608
            "PlaybackMethod, ClientName, DeviceName, PlayDuration "
            f"FROM PlaybackActivity WHERE rowid > {int(since_rowid)} "
            f"ORDER BY rowid ASC LIMIT {int(limit)}"
        )
        results = self._submit_custom_query(query)
        columns = (
            "rowid",
            "date_created",
            "user_id",
            "item_id",
            "item_type",
            "item_name",
            "playback_method",
            "client_name",
            "device_name",
            "play_duration",
        )
        return [dict(zip(columns, row, strict=True)) for row in results]

    def fetch_max_playback_activity_rowid(self) -> int:
        """Return the highest existing Playback Activity rowid, or 0 if empty."""
        results = self._submit_custom_query(
            "SELECT MAX(rowid) FROM PlaybackActivity",
        )
        if not results or results[0][0] is None:
            return 0
        return int(results[0][0])

    def _submit_custom_query(self, query: str) -> list[list]:
        response = self._request(
            "POST",
            "/user_usage_stats/submit_custom_query",
            json={"CustomQueryString": query, "ReplaceUserId": False},
        ).json()
        return response.get("results") or []
