import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app import config
from app.models import MediaTypes, Movie, Sources
from app.providers import services
from events.models import Event

from .helpers import date_parser

logger = logging.getLogger(__name__)


def process_other(item, events_bulk):
    """Process other types of items and add events to the event list.

    Returns True when the item was successfully checked (including when there was
    nothing to schedule), False when the provider call failed. Callers use this to
    decide whether to record the check, so a failed fetch is retried rather than
    being suppressed by the staleness window.
    """
    logger.info("Fetching releases for %s", item)
    try:
        metadata = services.get_media_metadata(
            item.media_type,
            item.media_id,
            item.source,
        )
    except services.ProviderAPIError:
        logger.warning(
            "Failed to fetch metadata for %s",
            item,
        )
        return False

    date_key = config.get_date_key(item.media_type)
    content_number = metadata["max_progress"]
    details = metadata["details"]
    fallback_date_key = None

    if item.media_type == MediaTypes.COMIC_ISSUE.value and not details.get(date_key):
        fallback_date_key = "cover_date"

    selected_date_key = fallback_date_key or date_key
    selected_date_value = details.get(selected_date_key)

    if selected_date_key in details and content_number:
        if selected_date_value:
            try:
                content_datetime = date_parser(selected_date_value)
            except ValueError:
                logger.warning(
                    "Invalid %s date for %s: %s",
                    selected_date_key,
                    item,
                    selected_date_value,
                )
                return True
        else:
            content_datetime = datetime.min.replace(tzinfo=ZoneInfo("UTC"))

        if item.media_type == MediaTypes.MOVIE.value:
            content_number = None

        events_bulk.append(
            Event(
                item=item,
                content_number=content_number,
                datetime=content_datetime,
            ),
        )

        if item.media_type == MediaTypes.MOVIE.value:
            events_bulk.extend(movie_release_type_events(item, metadata))

    elif (
        item.media_type == MediaTypes.GAME.value
        and selected_date_key in details
        and selected_date_value
    ):
        try:
            content_datetime = date_parser(selected_date_value)
        except ValueError:
            logger.warning(
                "Invalid %s date for %s: %s",
                selected_date_key,
                item,
                selected_date_value,
            )
            return True

        events_bulk.append(
            Event(
                item=item,
                content_number=None,
                datetime=content_datetime,
            ),
        )

    elif item.source == Sources.MANGAUPDATES.value and content_number:
        content_datetime = datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        events_bulk.append(
            Event(
                item=item,
                content_number=content_number,
                datetime=content_datetime,
            ),
        )

    return True


def movie_release_type_events(item, metadata):
    """Return digital and physical release events for the users' regions.

    Those dates differ per country, so only the regions of users tracking the
    movie get events. Users without a region have none.
    """
    release_types = metadata.get("release_types") or {}
    if not release_types:
        return []

    regions = set(
        Movie.objects.filter(item=item)
        .exclude(user__watch_provider_region__in=["", "UNSET"])
        .values_list("user__watch_provider_region", flat=True),
    )

    events = []
    for region in sorted(regions):
        for release_type, release_date in (release_types.get(region) or {}).items():
            try:
                content_datetime = date_parser(release_date)
            except ValueError:
                logger.warning(
                    "Invalid %s release date for %s: %s",
                    release_type,
                    item,
                    release_date,
                )
                continue
            events.append(
                Event(
                    item=item,
                    content_number=None,
                    datetime=content_datetime,
                    release_type=release_type,
                    region=region,
                ),
            )
    return events
