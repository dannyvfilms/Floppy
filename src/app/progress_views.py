"""The watched-episodes breakdown opened from a show or season progress card."""

import json

from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from app.models import TV, Season
from app.services.progress_breakdown import build_progress_breakdown
from app.services.rewatch_progress import cancel_run, resolve_rewatch


def _response(request, breakdown, instance_id, media_type):
    response = render(request, "app/components/progress_breakdown.html", {"breakdown": breakdown})
    response["HX-Trigger-After-Swap"] = json.dumps({
        "rewatch-progress-resolved": breakdown.display_payload(instance_id, media_type),
    })
    return response


@never_cache
@require_GET
def tv_progress_breakdown(request, tv_id):
    """Return the season and episode breakdown for a tracked show."""
    tv = get_object_or_404(TV.objects.select_related("item"), pk=tv_id, user=request.user)
    return _response(request, build_progress_breakdown(tv=tv), tv.id, "tv")


@never_cache
@require_GET
def season_progress_breakdown(request, season_id):
    """Return the episode breakdown for a tracked season."""
    season = get_object_or_404(
        Season.objects.select_related("item", "related_tv__item"),
        pk=season_id,
        user=request.user,
    )
    return _response(request, build_progress_breakdown(season=season), season.id, "season")


@never_cache
@require_POST
@transaction.atomic
def cancel_progress_rewatch(request):
    """Cancel exactly the displayed run; a stale form cannot cancel its successor."""
    media_type = request.POST.get("media_type")
    if media_type not in {"tv", "season"}:
        return HttpResponseBadRequest("Only shows and seasons have rewatch progress.")
    model = TV if media_type == "tv" else Season
    try:
        instance_id = int(request.POST.get("instance_id", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Enter a valid tracker id.")
    instance = get_object_or_404(model, pk=instance_id, user=request.user)
    tv = instance if media_type == "tv" else instance.related_tv
    # Serialize competing cancellation requests without locking play history.
    TV.objects.select_for_update().get(pk=tv.pk)
    breakdown = build_progress_breakdown(tv=tv)
    run = breakdown.rewatch_run
    if run is None or run.key != request.POST.get("run_key"):
        response = _response(
            request,
            build_progress_breakdown(season=instance) if media_type == "season" else breakdown,
            instance.pk, media_type,
        )
        response["HX-Trigger"] = json.dumps({
            "showToast": {"message": _("Rewatch progress changed. Review the current run."), "type": "info"},
        })
        return response
    cancel_run(tv, run)
    if run.explicit:
        inferred = resolve_rewatch(tv, breakdown.seasons, include_explicit=False, include_candidates=True)
        if inferred is not None:
            cancel_run(tv, inferred)
        if media_type == "tv":
            tv.stop_rewatch()
        else:
            instance.stop_rewatch()
    fresh = build_progress_breakdown(**({"tv": tv} if media_type == "tv" else {"season": instance}))
    return _response(request, fresh, instance.pk, media_type)
