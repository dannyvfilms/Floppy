"""Media-list routes for explicit entry-grouping preferences."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from app import cache_utils
from app.media_list_entry_grouping import (
    entry_grouping_mode,
    preference_field,
    show_separate_entries,
)
from app.media_list_views import media_list as base_media_list
from app.models.choices import MediaTypes

_BOOLEAN_VALUES = {"false": False, "true": True}


def _safe_return_url(request, media_type: str) -> str:
    target = (request.POST.get("next") or "").strip()
    if target.startswith("/") and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("medialist", args=[media_type])


@login_required
@require_GET
def media_list(request, media_type: str):
    """Render a media list with one request-scoped grouping policy."""
    if media_type not in MediaTypes.values:
        raise Http404

    field_name = preference_field(media_type)
    mode = show_separate_entries(request.user, media_type) if field_name else None

    original_query = request.GET
    if "separate_plays" in original_query:
        request.GET = original_query.copy()
        request.GET.pop("separate_plays", None)

    try:
        with entry_grouping_mode(mode):
            return base_media_list(request, media_type)
    finally:
        request.GET = original_query


@login_required
@require_POST
def update_entry_grouping(request, media_type: str):
    """Save whether a supported media list groups matching entries."""
    field_name = preference_field(media_type)
    if field_name is None:
        return HttpResponseBadRequest(
            "This media type does not support separate entries."
        )

    raw_value = request.POST.get("show_separate_entries")
    if raw_value not in _BOOLEAN_VALUES:
        return HttpResponseBadRequest("Select a valid entry display setting.")

    enabled = _BOOLEAN_VALUES[raw_value]
    if getattr(request.user, field_name) != enabled:
        request.user.update_preference(field_name, enabled)
        cache_utils.clear_media_list_cache_for_user(request.user.id)

    message = (
        "Matching entries are now shown separately."
        if enabled
        else "Matching entries are now grouped."
    )
    messages.success(request, message)
    return redirect(_safe_return_url(request, media_type))
