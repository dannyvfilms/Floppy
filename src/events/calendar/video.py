import logging

from django.utils import timezone

from events.models import Event

logger = logging.getLogger(__name__)


def process_video(item, events_bulk):
    """Add a calendar event on a video's upload date.

    Videos have no metadata provider, so this reads the date the client
    reported (`Item.release_datetime`). The Calendar shows when a video you
    watched was uploaded, never an upcoming release.

    Always returns True: there is nothing to retry.
    """
    release_datetime = item.release_datetime
    if not release_datetime:
        logger.debug("Skipping video %s - no upload date reported", item)
        return True

    if timezone.is_naive(release_datetime):
        release_datetime = timezone.make_aware(release_datetime)

    events_bulk.append(Event(item=item, datetime=release_datetime))
    return True
