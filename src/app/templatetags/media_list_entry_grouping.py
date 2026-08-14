"""Template state for the media-list entry-grouping control."""

from django import template

from app.media_list_entry_grouping import (
    preference_field,
    show_separate_entries,
)

register = template.Library()


@register.simple_tag
def media_list_entry_grouping_control(request):
    """Return the supported state for the current media-list route."""
    resolver_match = request.resolver_match
    media_type = (
        resolver_match.kwargs.get("media_type")
        if resolver_match is not None
        else None
    )
    supported = preference_field(media_type) is not None
    enabled = supported and show_separate_entries(request.user, media_type)
    return {
        "enabled": enabled,
        "next_value": "false" if enabled else "true",
        "state_label": "On" if enabled else "Off",
        "supported": supported,
    }
