"""Portable collection descriptors.

A descriptor is a versioned, self-describing document of a collection's layout
and the items it points at. It travels between Floppy instances, so it must
survive round-tripping through a version that does not understand all of it.

Three rules make that work:

- **Never export a credential.** A descriptor is shared, and a share is a
  publication. Nothing here reads a token, a URL with a secret, or a
  collaborator's account details.
- **Never export executable content.** A collection describes what to show, not
  code to run.
- **Preserve unknown fields on import.** A descriptor written by a newer Floppy
  must survive a round trip through an older one; silently dropping what it did
  not recognise is how a shared collection quietly loses half its contents.
"""

DESCRIPTOR_VERSION = 1
DESCRIPTOR_KIND = "floppy.collection"

MAX_ITEMS = 5000

# Keys this version owns. Anything else in an imported descriptor is unknown,
# and is carried through untouched rather than dropped.
KNOWN_KEYS = frozenset(
    {"kind", "version", "name", "description", "tags", "layout", "items"},
)


class InvalidDescriptorError(Exception):
    """Raised when a descriptor cannot be trusted, with a stable reason code."""

    def __init__(self, reason_code, message):
        """Store the reason code alongside the message."""
        super().__init__(message)
        self.reason_code = reason_code


REASON_NOT_OBJECT = "descriptor_not_object"
REASON_WRONG_KIND = "descriptor_wrong_kind"
REASON_UNSUPPORTED_VERSION = "descriptor_unsupported_version"
REASON_BAD_FIELD = "descriptor_bad_field"
REASON_TOO_MANY_ITEMS = "descriptor_too_many_items"


def export_collection(custom_list, memberships):
    """Return a portable descriptor for one list.

    ``memberships`` is the ordered CustomListItem queryset, so the caller
    decides the order rather than this guessing at it.
    """
    items = []
    for membership in memberships[:MAX_ITEMS]:
        item = membership.item
        items.append(
            {
                # External references only. An item id is meaningless on
                # another instance, so exporting one would produce a
                # descriptor that imports as garbage.
                "media_type": item.media_type,
                "source": item.source,
                "media_id": item.media_id,
                "season_number": item.season_number,
                "episode_number": item.episode_number,
                "external_ids": dict(item.provider_external_ids or {}),
                "title": item.title,
            },
        )

    return {
        "kind": DESCRIPTOR_KIND,
        "version": DESCRIPTOR_VERSION,
        "name": custom_list.name,
        "description": custom_list.description or "",
        "tags": list(custom_list.tags or []),
        "layout": {
            # Layout, not behaviour: how to show it, never what to run.
            "is_smart": bool(custom_list.is_smart),
            "allow_recommendations": bool(custom_list.allow_recommendations),
        },
        "items": items,
    }


def parse_descriptor(document):
    """Validate a descriptor and return it with its unknown fields preserved."""
    if not isinstance(document, dict):
        msg = "A collection descriptor must be an object."
        raise InvalidDescriptorError(REASON_NOT_OBJECT, msg)

    if document.get("kind") != DESCRIPTOR_KIND:
        msg = "This is not a Floppy collection descriptor."
        raise InvalidDescriptorError(REASON_WRONG_KIND, msg)

    version = document.get("version")
    if not isinstance(version, int) or version < 1:
        msg = "This descriptor does not declare a usable version."
        raise InvalidDescriptorError(REASON_UNSUPPORTED_VERSION, msg)
    if version > DESCRIPTOR_VERSION:
        # Refused rather than half-applied: importing a newer descriptor by
        # ignoring what we do not understand produces a collection that looks
        # complete and is not.
        msg = "This descriptor was written by a newer version of Floppy."
        raise InvalidDescriptorError(REASON_UNSUPPORTED_VERSION, msg)

    name = document.get("name")
    if not isinstance(name, str) or not name.strip():
        msg = "A collection descriptor must have a name."
        raise InvalidDescriptorError(REASON_BAD_FIELD, msg)

    raw_items = document.get("items", [])
    if not isinstance(raw_items, list):
        msg = "'items' must be a list."
        raise InvalidDescriptorError(REASON_BAD_FIELD, msg)
    if len(raw_items) > MAX_ITEMS:
        msg = "This descriptor holds more items than Floppy will import."
        raise InvalidDescriptorError(REASON_TOO_MANY_ITEMS, msg)

    items = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        media_type = entry.get("media_type")
        media_id = entry.get("media_id")
        source = entry.get("source")
        if not all(isinstance(v, str) and v for v in (media_type, media_id, source)):
            # Unresolvable rather than fatal: one bad row must not cost the
            # user the other four thousand.
            continue
        items.append(entry)

    unknown = {k: v for k, v in document.items() if k not in KNOWN_KEYS}

    return {
        "kind": DESCRIPTOR_KIND,
        "version": version,
        "name": name.strip()[:255],
        "description": (
            document["description"]
            if isinstance(document.get("description"), str)
            else ""
        ),
        "tags": [t for t in document.get("tags", []) if isinstance(t, str)]
        if isinstance(document.get("tags"), list)
        else [],
        "layout": document["layout"]
        if isinstance(document.get("layout"), dict)
        else {},
        "items": items,
        # Carried, not honoured. Round-tripping through this version must not
        # destroy what a newer one wrote.
        "unknown_fields": unknown,
        "skipped_items": len(raw_items) - len(items),
    }
