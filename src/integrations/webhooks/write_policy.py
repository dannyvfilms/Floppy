"""When a playback webhook may write tracking rows.

Every media-server webhook asks this module before it creates or changes a
Movie/Episode row. Play, resume and pause only update the Now Playing card;
a stop, scrobble or manual mark is what writes. Clients that only ever send
"play" (e.g. Bunny Ears TV in activity-only mode, 82e424f2) could otherwise
leave items stuck In Progress, and every progress tick would get another
chance to write to a mis-resolved show (#1250).

Each integration has one row in ``WEBHOOK_WRITE_POLICIES``, keyed by its
processor's ``SOURCE_LABEL``. Exceptions live here too, with their reason.
See docs/architecture/webhook-write-rules.md.
"""

import logging
from enum import StrEnum

logger = logging.getLogger(__name__)

# An unfinished stop reported before this much playback is a skim, not a start.
# The floor applies to every title; longer titles also need 5% progress, up to
# a three-minute ceiling so a two-hour film still counts after a short start.
MIN_STOP_POSITION_SECONDS = 60
MAX_STOP_POSITION_SECONDS = 3 * 60
STOP_POSITION_RATIO = 0.05

LIVE_EVENTS = frozenset({"media.play", "media.resume", "media.pause"})
FINAL_EVENTS = frozenset({"media.scrobble", "mark"})


class WritePolicy(StrEnum):
    """How an integration's events map to tracking writes."""

    # Play/resume/pause never write. A stop writes if played, or if its
    # position is unknown or at least the minimum stop position. Scrobbles
    # and manual marks always write.
    STOP_ONLY = "stop_only"
    # The source has no stop signal, so its start ping records In Progress.
    START_ONLY = "start_only"
    # Every event the source sends is already a finished play.
    FINAL_ONLY = "final_only"


WEBHOOK_WRITE_POLICIES = {
    "plex": (WritePolicy.STOP_ONLY, "Sends stop and scrobble."),
    "jellyfin": (WritePolicy.STOP_ONLY, "Sends stop; manual marks are 'mark'."),
    "emby": (WritePolicy.STOP_ONLY, "Sends playback.stop."),
    "kodi": (WritePolicy.STOP_ONLY, "Sends stop and end."),
    "stremio": (
        WritePolicy.START_ONLY,
        "Stremio only sends a start ping; completion comes from the delayed "
        "verifier, so the start is the only In Progress signal there is.",
    ),
    "scrobble": (
        WritePolicy.FINAL_ONLY,
        "The scrobble API only accepts stop/completion events.",
    ),
    "check-in": (
        WritePolicy.FINAL_ONLY,
        "Floppy's own Check-in button; every call is a deliberate user action.",
    ),
}


def policy_for(source_label):
    """Return the write policy for an integration, failing loudly if unlisted."""
    try:
        return WEBHOOK_WRITE_POLICIES[source_label][0]
    except KeyError:
        msg = (
            f"No webhook write policy for source {source_label!r}. Add a row to "
            "WEBHOOK_WRITE_POLICIES in integrations/webhooks/write_policy.py "
            "(see docs/architecture/webhook-write-rules.md)."
        )
        raise LookupError(msg) from None


def minimum_stop_position_seconds(duration_seconds=None):
    """Return how far into a title a stop must be to count as a start.

    Longer titles need proportionally more progress, but the floor and the
    ceiling keep both a ten-minute video and a two-hour film reasonable.
    """
    if duration_seconds is None or duration_seconds <= 0:
        return MIN_STOP_POSITION_SECONDS
    proportional = duration_seconds * STOP_POSITION_RATIO
    return min(
        MAX_STOP_POSITION_SECONDS,
        max(MIN_STOP_POSITION_SECONDS, proportional),
    )


def should_record(
    source_label,
    event,
    *,
    played,
    position_seconds,
    duration_seconds=None,
):
    """Decide whether a webhook event may write tracking rows.

    ``event`` uses the Now Playing vocabulary (media.play, media.resume,
    media.pause, media.stop, media.scrobble) plus "mark" for a manual
    watched/unwatched toggle.
    """
    policy = policy_for(source_label)

    if policy is WritePolicy.FINAL_ONLY or event in FINAL_EVENTS:
        return True

    if event in LIVE_EVENTS:
        record = policy is WritePolicy.START_ONLY
    elif event == "media.stop":
        minimum = minimum_stop_position_seconds(duration_seconds)
        record = played or position_seconds is None or position_seconds >= minimum
    else:
        record = False

    if not record:
        logger.debug(
            "Not recording %s %s event under %s policy (position=%s duration=%s)",
            source_label,
            event,
            policy,
            position_seconds,
            duration_seconds,
        )
    return record
