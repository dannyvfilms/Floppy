import datetime

from django import template
from django.utils import formats

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using the key."""
    return dictionary.get(key, [])


@register.simple_tag
def day_of_week(day, month, year):
    """Return the day of week given day, month, and year."""
    # Convert to integers
    day = int(day)
    month = int(month)
    year = int(year)

    # Create date object
    date_obj = datetime.date(year, month, day)

    # Get day of week
    return formats.date_format(date_obj, "l")


@register.filter
def calendar_event_url(event):
    """Return the episode page for a TV season event, else the item's page."""
    from app.models import MediaTypes
    from app.templatetags.app_tags import media_url

    item = event.item
    number = event.content_number
    if (
        item.media_type == MediaTypes.SEASON.value
        and item.season_number is not None
        and number is not None
    ):
        is_anime = item.library_media_type == MediaTypes.ANIME.value
        return media_url(
            {
                "media_type": MediaTypes.EPISODE.value,
                "route_media_type": MediaTypes.ANIME.value if is_anime else None,
                "source": item.source,
                "media_id": item.media_id,
                "title": item.title,
                "season_number": item.season_number,
                "episode_number": number,
            },
        )
    return media_url(item)
