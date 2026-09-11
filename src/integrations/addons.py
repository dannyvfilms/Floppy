"""Registering and refreshing declarative remote add-ons.

Fetching goes through `integrations.safe_fetch`, and parsing through
`integrations.addon_manifest`. Neither this module nor anything it calls
executes remote code; an add-on is a description of an HTTP capability.
"""

import logging

from django.utils import timezone
from requests import RequestException

from integrations.addon_manifest import InvalidManifestError, parse_manifest
from integrations.models import RemoteAddon
from integrations.safe_fetch import UnsafeUrlError, safe_fetch

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_ERROR = "error"
REASON_TRANSPORT = "transport_error"
REASON_BAD_STATUS = "bad_status"


def refresh_addon(addon):
    """Fetch and revalidate one add-on, recording the outcome.

    Never raises for a remote failure. A broken add-on records its reason code
    and keeps its last good manifest, so one unreachable host does not empty a
    working install.
    """
    try:
        response, body = safe_fetch(addon.manifest_url)
    except UnsafeUrlError as error:
        return _record_failure(addon, error.reason_code)
    except RequestException:
        # The exception text can contain the configured URL, so only the code
        # is recorded. See docs/architecture/outbound-fetch.md.
        return _record_failure(addon, REASON_TRANSPORT)

    if response.status_code >= 400:  # noqa: PLR2004
        return _record_failure(addon, REASON_BAD_STATUS)

    try:
        manifest = parse_manifest(body)
    except InvalidManifestError as error:
        return _record_failure(addon, error.reason_code)

    addon.manifest = manifest
    addon.addon_id = manifest["id"]
    addon.name = manifest["name"]
    addon.version = manifest["version"]
    addon.description = manifest["description"]
    addon.last_fetched_at = timezone.now()
    addon.last_status = STATUS_OK
    addon.last_error_code = ""
    addon.save(
        update_fields=[
            "manifest",
            "addon_id",
            "name",
            "version",
            "description",
            "last_fetched_at",
            "last_status",
            "last_error_code",
        ],
    )
    return addon


def _record_failure(addon, reason_code):
    """Record a failed refresh without discarding the last good manifest."""
    addon.last_fetched_at = timezone.now()
    addon.last_status = STATUS_ERROR
    addon.last_error_code = reason_code[:64]
    if addon.pk:
        addon.save(
            update_fields=["last_fetched_at", "last_status", "last_error_code"],
        )
    logger.info(
        "remote_addon_refresh_failed addon_id=%s reason=%s",
        addon.pk,
        reason_code,
    )
    return addon


def register_addon(user, manifest_url):
    """Register a new add-on, validating it before it is stored.

    Raises UnsafeUrlError or InvalidManifestError so the caller can show the
    user why. Nothing is saved unless the manifest validates: a registry full
    of unreachable entries helps nobody.
    """
    response, body = safe_fetch(manifest_url)
    if response.status_code >= 400:  # noqa: PLR2004
        msg = "That address did not return a manifest."
        raise InvalidManifestError(REASON_BAD_STATUS, msg)

    manifest = parse_manifest(body)

    addon, _created = RemoteAddon.objects.update_or_create(
        user=user,
        manifest_url=manifest_url,
        defaults={
            "addon_id": manifest["id"],
            "name": manifest["name"],
            "version": manifest["version"],
            "description": manifest["description"],
            "manifest": manifest,
            "enabled": True,
            "last_fetched_at": timezone.now(),
            "last_status": STATUS_OK,
            "last_error_code": "",
        },
    )
    return addon
