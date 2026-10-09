"""Floppy-owned asynchronous channels and their AsyncAPI 3.0 renderer.

Scope is deliberately narrow, per the grounding design: verified inbound
message channels plus ownership and routing for the three Celery queues.
Polling importers, Apprise destinations, and shared base classes are not
channels and are excluded on purpose - describing them here would make the
artifact a liability rather than a contract.

Celery messages cross the wire as ``application/x-python-serialize``. This
module therefore documents logical task arguments through ``x-floppy-*``
metadata and never claims a portable JSON payload schema for them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config.runtime_profile import TIERS, celery_queue_plan

CONTRACT_PATH = Path(__file__).resolve().parent / "contracts" / "asyncapi.json"
ASYNCAPI_VERSION = "3.0.0"
CONTRACT_VERSION = "1.0.0"
CONTRACT_REGENERATION_COMMAND = (
    "PYTHONPATH=src uv run --no-sync python -m api.channel_registry"
)

# Celery serializes task messages with pickle. Declaring a JSON payload schema
# here would be a lie a consumer could act on.
CELERY_CONTENT_TYPE = "application/x-python-serialize"


@dataclass(frozen=True)
class InboundChannel:
    """One verified inbound message surface owned by Floppy."""

    key: str
    address: str
    provider: str
    summary: str
    # Which Celery queue the accepted message is handed to, if any.
    dispatches_to: str | None


@dataclass(frozen=True)
class CeleryQueue:
    """One Celery queue Floppy owns, with its routing facts."""

    name: str
    summary: str
    default_priority: int


# Every entry is a real route that accepts a message from an external system.
# `test_api_contracts` proves the provider set equals WEBHOOK_PROCESSORS and
# that each address resolves to a registered Django route.
INBOUND_CHANNELS: tuple[InboundChannel, ...] = (
    InboundChannel(
        key="plexWebhook",
        address="webhook/plex/{token}",
        provider="plex",
        summary="Plex playback and scrobble webhook.",
        dispatches_to="celery",
    ),
    InboundChannel(
        key="jellyfinWebhook",
        address="webhook/jellyfin/{token}",
        provider="jellyfin",
        summary="Jellyfin playback, user-rating, and watched-toggle webhook.",
        dispatches_to="celery",
    ),
    InboundChannel(
        key="embyWebhook",
        address="webhook/emby/{token}",
        provider="emby",
        summary="Emby playback webhook.",
        dispatches_to="celery",
    ),
    InboundChannel(
        key="jellyseerrWebhook",
        address="webhook/jellyseerr/{token}",
        provider="seerr",
        summary="Jellyseerr request webhook scoped to one user token.",
        dispatches_to="celery",
    ),
    InboundChannel(
        key="seerrGlobalWebhook",
        address="webhook/seerr/global/",
        provider="seerr",
        summary=(
            "Overseerr or Jellyseerr global webhook. Floppy resolves the owning "
            "user from the payload instead of a token in the path."
        ),
        dispatches_to="celery",
    ),
    InboundChannel(
        key="kodiWebhook",
        address="webhook/kodi/{token}",
        provider="kodi",
        summary="Kodi playback webhook.",
        dispatches_to="celery",
    ),
    InboundChannel(
        key="stremioAddonSubtitles",
        address="stremio-addon/{token}/subtitles/{media_type}/{media_id}.json",
        provider="stremio",
        summary=(
            "Stremio subtitles request used as a playback-start signal. Stremio "
            "re-requests on seek and quality change, so Floppy throttles to one "
            "scrobble per item per window."
        ),
        dispatches_to="celery",
    ),
    InboundChannel(
        key="stremioAddonPlayer",
        address=(
            "stremio-addon/{token}/player/{media_type}/{media_id}/"
            "position=0&duration=0.json"
        ),
        provider="stremio",
        summary=(
            "Stremio player event carrying a playback position and duration in "
            "the extra. Sent on play, pause, and stop, and the one source of a "
            "resume position for a client that cannot emit a stop."
        ),
        dispatches_to="celery",
    ),
    InboundChannel(
        key="stremioAddonLibrary",
        address=(
            "stremio-addon/{token}/library/{media_type}/{media_id}/"
            "action=watched.json"
        ),
        provider="stremio",
        summary=(
            "Stremio library change (add, remove, watched, unwatched) for one "
            "item, carrying the affected episode ids in `videoId` so a batch "
            "arrives as one request."
        ),
        dispatches_to="celery",
    ),
    InboundChannel(
        key="listenBrainzSubmitListens",
        address="apis/listenbrainz/1/submit-listens",
        provider="listenbrainz",
        summary=(
            "ListenBrainz-compatible listen submission. Handled synchronously by "
            "the REST API, not by the webhook task, and described in OpenAPI as "
            "well because it has an exact HTTP wire shape."
        ),
        dispatches_to=None,
    ),
)

# `listenbrainz` has its own inbound HTTP surface and no WEBHOOK_PROCESSORS
# entry, so it is excluded when comparing against that registry.
NON_WEBHOOK_PROVIDERS = frozenset({"listenbrainz"})

CELERY_QUEUES: tuple[CeleryQueue, ...] = (
    CeleryQueue(
        name="celery",
        summary=(
            "Background work. Default queue for tasks with no explicit override, "
            "including webhook processing and metadata backfills."
        ),
        default_priority=5,
    ),
    CeleryQueue(
        name="interactive",
        summary=(
            "Latency-sensitive work a user is waiting on. Kept isolated so bulk "
            "backfills cannot starve it."
        ),
        default_priority=0,
    ),
    CeleryQueue(
        name="discover",
        summary="Discover cache rebuilds.",
        default_priority=9,
    ),
)


def worker_plan_by_tier() -> dict[str, str]:
    """Return the queues each resource tier's background worker consumes."""
    return {tier: celery_queue_plan(_profile_for(tier))["queues"] for tier in TIERS}


def _profile_for(tier: str):
    """Return a resource profile stub carrying only the tier."""
    from config.runtime_profile import PROFILE

    # celery_queue_plan reads `.tier` and nothing else.
    return PROFILE.__class__(
        tier=tier,
        memory_bytes=PROFILE.memory_bytes,
        available_bytes=PROFILE.available_bytes,
        swap_bytes=PROFILE.swap_bytes,
        cpus=PROFILE.cpus,
        overridden=PROFILE.overridden,
    )


def _channel_entry(channel: InboundChannel) -> dict[str, object]:
    """Render one AsyncAPI channel object."""
    entry: dict[str, object] = {
        "address": f"/{channel.address}",
        "title": channel.key,
        "summary": channel.summary,
        "messages": {
            "request": {"$ref": f"#/components/messages/{channel.key}Request"},
        },
        "x-floppy-provider": channel.provider,
    }
    if channel.dispatches_to:
        entry["x-floppy-dispatches-to-queue"] = channel.dispatches_to
    return entry


def render_asyncapi() -> str:
    """Render the committed AsyncAPI 3.0 contract."""
    channels = {channel.key: _channel_entry(channel) for channel in INBOUND_CHANNELS}
    operations = {
        f"receive{channel.key[0].upper()}{channel.key[1:]}": {
            "action": "receive",
            "channel": {"$ref": f"#/channels/{channel.key}"},
            "summary": channel.summary,
        }
        for channel in INBOUND_CHANNELS
    }
    messages = {
        f"{channel.key}Request": {
            "name": f"{channel.key}Request",
            "title": channel.summary,
            "contentType": "application/json",
            # Provider payloads are third-party shapes Floppy does not own, so
            # no field-level schema is claimed for them.
            "payload": {"type": "object"},
            "x-floppy-payload-owner": (
                "floppy" if channel.provider == "listenbrainz" else "third-party"
            ),
        }
        for channel in INBOUND_CHANNELS
    }

    document = {
        "asyncapi": ASYNCAPI_VERSION,
        "info": {
            "title": "Floppy asynchronous channels",
            "version": CONTRACT_VERSION,
            "description": (
                "Verified inbound message channels and Celery queue ownership for "
                "a Floppy instance. Scope is deliberately narrow: polling "
                "importers, Apprise notification destinations, and shared base "
                "classes are not channels and are excluded."
            ),
            "contact": {"url": "https://github.com/dannyvfilms/Floppy/issues"},
            "license": {
                "name": "AGPL-3.0",
                "url": "https://www.gnu.org/licenses/agpl-3.0.html",
            },
        },
        "defaultContentType": "application/json",
        "channels": channels,
        "operations": operations,
        "components": {
            "messages": messages,
        },
        "x-floppy-celery-queues": {
            queue.name: {
                "summary": queue.summary,
                "defaultPriority": queue.default_priority,
                "contentType": CELERY_CONTENT_TYPE,
            }
            for queue in CELERY_QUEUES
        },
        "x-floppy-worker-plan": {
            "description": (
                "Queues the background worker consumes at each resource tier. A "
                "tier that omits a queue from this list starts a dedicated worker "
                "for it instead; no queue is ever dropped."
            ),
            "byTier": worker_plan_by_tier(),
        },
    }
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the committed contract or check it for drift."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = render_asyncapi().encode("utf-8")

    if args.check:
        if not CONTRACT_PATH.exists():
            return 1
        return int(CONTRACT_PATH.read_bytes() != rendered)

    CONTRACT_PATH.write_bytes(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
