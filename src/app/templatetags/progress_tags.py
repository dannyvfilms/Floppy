"""Resolve detail progress once per template render, including OOB cards."""

from django import template
from django.urls import reverse
from django.utils.translation import gettext as _

from app.models import Season
from app.services.progress_breakdown import build_progress_breakdown

register = template.Library()


@register.simple_tag(takes_context=True)
def detail_progress(context, instance):
    """Share the breakdown's projection with the card."""
    cache = context.render_context.setdefault("detail_progress", {})
    key = (type(instance), instance.pk)
    if key not in cache:
        cache[key] = build_progress_breakdown(
            **({"season": instance} if isinstance(instance, Season) else {"tv": instance}),
        )
        if cache[key].catalogue_unavailable and instance.is_rewatching:
            # A provider outage cannot erase an explicit, locally known pass.
            percent = instance.rewatch_percentage
            cache[key] = {
                "percent": instance.watched_once_percentage,
                "rewatch_percent": percent, "rewatch_offset": 0,
                "rewatch_width": percent or 0, "run_key": "",
                "rewatch_label": _("Rewatching · %(percent)s%%") % {"percent": percent},
            }
    return cache[key]


def _value(display, name):
    """Read a projection value from either the breakdown or its outage dict."""
    if isinstance(display, dict):
        return display.get(name)
    return getattr(display, name, None)


@register.simple_tag(takes_context=True)
def detail_progress_card(context, instance, media_type):
    """Build the shared card and dialog contract for the browser adapter."""
    display = detail_progress(context, instance)
    percent = _value(display, "percent")
    if percent is None:
        percent = instance.watched_once_percentage
    rewatch_percent = _value(display, "rewatch_percent")
    rewatch = None
    if rewatch_percent is not None:
        rewatch = {
            "percent": rewatch_percent,
            "offset": _value(display, "rewatch_offset") or 0,
            "width": _value(display, "rewatch_width") or 0,
            "label": _value(display, "rewatch_label") or "",
        }
    url_name = "season_progress_breakdown" if media_type == "season" else "tv_progress_breakdown"
    return {
        "card": {
            "percent": percent,
            "caughtUp": bool(_value(display, "caught_up")),
            "runKey": _value(display, "run_key") or "",
            "rewatch": rewatch,
        },
        "control": {
            "openUrl": reverse(url_name, args=[instance.id]),
            "cancelUrl": reverse("cancel_progress_rewatch"),
            "mediaType": media_type,
            "instanceId": instance.id,
            "tvId": instance.related_tv_id if media_type == "season" else instance.id,
            "title": instance.item.title,
        },
        "labels": {
            "yourProgress": _("Your Progress"),
            "caughtUp": _("Caught Up"),
            "aboutProgress": _("About your progress"),
            "progressTip": _("Your progress is how much of the show you have watched at least once. While you rewatch, a glowing line shows how far along the rewatch is."),
            "openBreakdown": _("Open the season and episode breakdown"),
            "cancelRewatch": _("Cancel rewatch"),
            "cancelling": _("Cancelling…"),
            "close": _("Close"),
            "loading": _("Loading…"),
            "loadError": _("Your progress could not be loaded. Close this and try again."),
        },
    }
