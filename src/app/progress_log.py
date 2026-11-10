"""Progress lines for work that takes time, safe to show to non-admin users.

Long-running work (an import, a sync, a task) writes a start line, progress
lines and a finish line here instead of through its module logger. The lines go
to the same log file at INFO, carrying a visible tag. The diagnostic report any
signed-in user can download keeps the tagged lines and drops other INFO lines,
which can name what an account watched. See ``docs/architecture/log-levels.md``.

Only write safe identifiers: ids, counts, durations, provider and task names.
Never a username, email address, media title or URL.
"""

import logging

PROGRESS_TAG = "[progress]"

logger = logging.getLogger("floppy.progress")


def progress(message: str, *args) -> None:
    """Log one tagged progress line, e.g. ``progress("plex_sync_finished ...")``."""
    logger.info("%s %s", PROGRESS_TAG, message % args if args else message)
