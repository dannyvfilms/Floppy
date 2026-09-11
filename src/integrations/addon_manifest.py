"""Validation for a declarative add-on manifest.

An add-on is a description of an HTTP capability, never code. Nothing here
executes anything a remote host sends: the manifest is parsed, checked against
this schema, and stored. A field this module does not know about is dropped
rather than kept, so a future manifest cannot smuggle behaviour past it.

Shape follows the Stremio add-on manifest closely enough that an existing
add-on validates, because that is the population of manifests that exists.
"""

import json

MAX_MANIFEST_BYTES = 256 * 1024
MAX_STRING = 512
MAX_COLLECTION = 64

SUPPORTED_RESOURCES = frozenset({"catalog", "meta", "stream", "subtitles"})
SUPPORTED_TYPES = frozenset(
    {"movie", "series", "channel", "tv", "book", "music", "other"},
)

REASON_NOT_JSON = "manifest_not_json"
REASON_NOT_OBJECT = "manifest_not_object"
REASON_MISSING_FIELD = "manifest_missing_field"
REASON_BAD_FIELD = "manifest_bad_field"
REASON_TOO_LARGE = "manifest_too_large"
REASON_NO_USABLE_RESOURCE = "manifest_no_usable_resource"


class InvalidManifestError(Exception):
    """Raised when a manifest cannot be trusted, with a stable reason code."""

    def __init__(self, reason_code, message):
        """Store the reason code alongside the message."""
        super().__init__(message)
        self.reason_code = reason_code


def _clean_string(value, field):
    """Return a bounded string, or raise."""
    if not isinstance(value, str) or not value.strip():
        msg = f"'{field}' must be a non-empty string."
        raise InvalidManifestError(REASON_BAD_FIELD, msg)
    return value.strip()[:MAX_STRING]


def _clean_string_list(value, field, *, allowed=None):
    """Return a bounded list of strings, dropping anything unsupported."""
    if not isinstance(value, list):
        msg = f"'{field}' must be a list."
        raise InvalidManifestError(REASON_BAD_FIELD, msg)

    cleaned = []
    for entry in value[:MAX_COLLECTION]:
        if not isinstance(entry, str):
            continue
        text = entry.strip()[:MAX_STRING]
        if not text:
            continue
        if allowed is not None and text not in allowed:
            # Dropped, not rejected: an add-on offering a resource Floppy does
            # not consume is still usable for the ones it does.
            continue
        cleaned.append(text)
    return cleaned


def parse_manifest(body):
    """Parse and validate a manifest body, returning only known fields.

    Accepts bytes or str. Raises InvalidManifestError with a stable reason code.
    """
    if isinstance(body, (bytes, bytearray)):
        if len(body) > MAX_MANIFEST_BYTES:
            msg = "This manifest is larger than Floppy will accept."
            raise InvalidManifestError(REASON_TOO_LARGE, msg)
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError as error:
            msg = "This manifest is not valid UTF-8."
            raise InvalidManifestError(REASON_NOT_JSON, msg) from error

    if isinstance(body, str) and len(body.encode("utf-8")) > MAX_MANIFEST_BYTES:
        msg = "This manifest is larger than Floppy will accept."
        raise InvalidManifestError(REASON_TOO_LARGE, msg)

    if isinstance(body, str):
        try:
            document = json.loads(body)
        except ValueError as error:
            msg = "This manifest is not valid JSON."
            raise InvalidManifestError(REASON_NOT_JSON, msg) from error
    else:
        document = body

    if not isinstance(document, dict):
        msg = "A manifest must be a JSON object."
        raise InvalidManifestError(REASON_NOT_OBJECT, msg)

    for field in ("id", "version", "name"):
        if field not in document:
            msg = f"A manifest must declare '{field}'."
            raise InvalidManifestError(REASON_MISSING_FIELD, msg)

    resources = _clean_string_list(
        document.get("resources", []),
        "resources",
        allowed=SUPPORTED_RESOURCES,
    )
    if not resources:
        msg = "This add-on offers nothing Floppy can use."
        raise InvalidManifestError(REASON_NO_USABLE_RESOURCE, msg)

    catalogs = []
    raw_catalogs = document.get("catalogs", [])
    if not isinstance(raw_catalogs, list):
        msg = "'catalogs' must be a list."
        raise InvalidManifestError(REASON_BAD_FIELD, msg)
    for entry in raw_catalogs[:MAX_COLLECTION]:
        if not isinstance(entry, dict):
            continue
        try:
            catalogs.append(
                {
                    "type": _clean_string(entry.get("type"), "catalog.type"),
                    "id": _clean_string(entry.get("id"), "catalog.id"),
                    "name": _clean_string(
                        entry.get("name", entry.get("id")),
                        "catalog.name",
                    ),
                },
            )
        except InvalidManifestError:
            # One malformed catalog does not condemn the add-on.
            continue

    # Only these keys are kept. Anything else the remote sent is discarded,
    # so a manifest cannot carry a field a later Floppy version might honour.
    return {
        "id": _clean_string(document["id"], "id"),
        "version": _clean_string(document["version"], "version"),
        "name": _clean_string(document["name"], "name"),
        "description": (
            _clean_string(document["description"], "description")
            if isinstance(document.get("description"), str)
            and document["description"].strip()
            else ""
        ),
        "resources": resources,
        "types": _clean_string_list(
            document.get("types", []),
            "types",
            allowed=SUPPORTED_TYPES,
        ),
        "catalogs": catalogs,
    }
