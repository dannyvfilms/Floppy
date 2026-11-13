"""Tell React cards that an item's status or score changed.

The save and score responses still swap their server fragments out of band for
pages that render them. Cards the shared React component owns ignore that swap
and listen for this event instead.
"""

import json

from app.media_card_model import rating_model
from app.templatetags import app_tags


def card_update_event(item, media, user):
    """Return the detail a card needs to refresh its status chip and rating."""
    kind = item.media_type
    status = None
    statusless = False
    rating = None
    if media is not None:
        status = getattr(media, "aggregated_status", None) or media.status or None
        statusless = bool(getattr(media, "is_statusless", False))
        rating = rating_model({"user": user, "media": media, "item": item}, kind)
    return {
        "cardKey": app_tags.item_slot_id("media-card", item),
        "status": status,
        "statusless": statusless,
        "statusColor": app_tags.status_color(status) if status else None,
        "rating": rating,
    }


def add_card_update(response, item, media, user):
    """Add the card update to ``response``'s HX-Trigger header."""
    existing = response.get("HX-Trigger")
    triggers = {}
    if existing:
        try:
            triggers = json.loads(existing)
        except ValueError:
            triggers = {existing: {}}
    triggers["floppyCardUpdate"] = card_update_event(item, media, user)
    response["HX-Trigger"] = json.dumps(triggers)
    return response
