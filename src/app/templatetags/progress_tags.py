"""Resolve detail progress once per template render, including OOB cards."""

from django import template
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
