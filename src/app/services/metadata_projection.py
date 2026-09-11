"""Normalized metadata projections with provenance and freshness.

What a client gets when it asks Floppy what it knows about an item, and where
that knowledge came from.

Nothing here fetches. It projects what is already stored, so publishing it does
not extend any provider's terms beyond what Floppy already cached.

**Not yet separated: user overrides.** Floppy writes a manual metadata edit onto
the item row itself, so a correction someone typed and a value a provider
returned are the same field by the time they reach here, and this cannot tell
them apart. Splitting them is Nuvio programme B9 and needs the custom-metadata
write path to store overrides separately first. Until then this projection
reports what Floppy holds, not who authored it — so do not use it to decide
whether a refresh may overwrite a field.
"""

from django.utils import timezone

# Beyond this a projection is served but labelled stale, so a client can choose
# to refresh rather than trust it silently.
STALE_AFTER_DAYS = 30

PROVIDER_FIELDS = (
    "title",
    "original_title",
    "synopsis",
    "image",
    "release_datetime",
    "runtime_minutes",
    "genres",
    "country",
    "languages",
    "studios",
    "format",
    "status",
)


def _freshness(item):
    """Return the freshness block for one item."""
    refreshed = getattr(item, "metadata_refreshed_at", None)
    if refreshed is None:
        # Not the same claim as "refreshed long ago", and reported as its own
        # state so a client does not treat unknown as stale or as fresh.
        return {"refreshed_at": None, "age_days": None, "state": "unknown"}

    age = (timezone.now() - refreshed).days
    return {
        "refreshed_at": refreshed,
        "age_days": age,
        "state": "stale" if age >= STALE_AFTER_DAYS else "fresh",
    }


def project_item_metadata(item):
    """Return the normalized projection for one item."""
    provider = {}
    for field in PROVIDER_FIELDS:
        value = getattr(item, field, None)
        if value in (None, "", [], {}):
            continue
        provider[field] = value

    return {
        "identity": {
            "media_id": item.media_id,
            "source": item.source,
            "media_type": item.media_type,
            "season_number": item.season_number,
            "episode_number": item.episode_number,
            "external_ids": dict(item.provider_external_ids or {}),
        },
        "attribution": {
            # Named so a client can honour a provider's display requirements,
            # which several of them make a condition of use.
            "source": item.source,
            "source_url": item.source_url or None,
        },
        "freshness": _freshness(item),
        "fields": provider,
        # Authorship is not yet distinguishable; see the module docstring.
        "authorship": "unseparated",
    }
