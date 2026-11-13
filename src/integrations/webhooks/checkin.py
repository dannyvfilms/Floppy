"""Durable-write processor for Floppy's own Check-in button (see app.checkin)."""

from .generic_scrobble import GenericScrobbleProcessor


class CheckInProcessor(GenericScrobbleProcessor):
    """Writes check-in rows through the shared scrobble logic.

    A separate class only so the rows say "via Check-in".
    """

    SOURCE_LABEL = "check-in"
