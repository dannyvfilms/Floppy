"""Kapowarr importer for comic issue collection ownership sync."""

import logging
from http import HTTPStatus

import requests

from integrations import import_progress
from integrations.imports.helpers import ConnectionAuthError, MediaImportError
from integrations.imports.mylar import MylarImporter
from integrations.models import KapowarrInstance
from integrations.safe_fetch import send_to_self_hosted

logger = logging.getLogger(__name__)


class KapowarrClient:
    """Thin API client for the Kapowarr ``/api`` endpoints."""

    def __init__(self, base_url: str, api_key: str):
        """Store the server URL and API key."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, path: str):
        try:
            response = send_to_self_hosted(
                requests.get,
                f"{self.base_url}/api/{path}",
                params={"api_key": self.api_key},
                timeout=20,
            )
        except requests.RequestException as error:
            # The key travels in the query string, so the exception text (which
            # repeats the URL) must not reach the stored error message.
            msg = f"Could not reach Kapowarr ({type(error).__name__})"
            raise MediaImportError(msg) from error
        # Kapowarr answers a wrong key with 401 and error "ApiKeyInvalid".
        if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            msg = "Kapowarr API key is invalid or unauthorized"
            raise ConnectionAuthError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            msg = f"Kapowarr request failed ({response.status_code}) for {path}"
            raise MediaImportError(msg)
        try:
            payload = response.json()
        except ValueError as error:
            msg = f"Kapowarr returned an unreadable response for {path}"
            raise MediaImportError(msg) from error
        if not isinstance(payload, dict) or payload.get("error"):
            error = payload.get("error") if isinstance(payload, dict) else None
            msg = f"Kapowarr request failed for {path}: {error or 'unknown error'}"
            raise MediaImportError(msg)
        return payload.get("result")

    def healthcheck(self):
        """Verify connection."""
        return self._request("system/about")

    def volumes(self):
        """Fetch the volumes in the library."""
        return self._request("volumes") or []

    def volume(self, volume_id):
        """Fetch one volume with its issues and their files."""
        return self._request(f"volumes/{volume_id}") or {}


def importer(identifier, user, mode, instance_id=None):
    """Import Kapowarr collection ownership."""
    instance = (
        KapowarrInstance.objects.get(pk=instance_id, user=user) if instance_id else None
    )
    return KapowarrImporter(user, instance=instance).import_data()


class KapowarrImporter(MylarImporter):
    """Mark the comic issues a Kapowarr library has files for as owned."""

    source = "kapowarr"
    label = "Kapowarr"
    instances_attr = "kapowarr_instances"
    client_class = KapowarrClient

    def _owned_issues(self):
        """Yield (Comic Vine issue id, title, image) for each issue with a file."""
        volumes = self.client.volumes()
        total = len(volumes)
        for i, volume in enumerate(volumes, start=1):
            import_progress.report(i, total, self.label)
            # The list already counts downloaded issues; skip empty volumes
            # instead of fetching each one.
            if not volume.get("id") or not volume.get("issues_downloaded"):
                continue
            detail = self.client.volume(volume["id"])
            volume_title = detail.get("title") or volume.get("title") or ""
            for issue in detail.get("issues") or []:
                if not issue.get("files"):
                    continue
                title = f"{volume_title} #{issue.get('issue_number') or '?'}"
                if issue.get("title"):
                    title = f"{title}: {issue['title']}"
                yield issue.get("comicvine_id"), title, None
