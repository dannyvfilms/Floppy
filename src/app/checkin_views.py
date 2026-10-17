"""HTTP endpoint behind the Check-in button on a detail page."""

import logging

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_POST

from app import checkin, checkin_session, helpers, live_playback
from app.activity_builders import _build_detail_activity_state
from app.models import BasicMedia, MediaTypes
from app.services.completion import select_preferred_activity_entry
from app.templatetags.app_tags import media_url

logger = logging.getLogger(__name__)

ACTIONS = {
    "start": checkin.start,
    "resume": checkin.start,
    "pause": checkin.pause,
    "finish": checkin.finish,
    "cancel": checkin.cancel,
}


SESSION_ACTIONS = {
    "start": checkin_session.start,
    "stop": checkin_session.stop,
    "cancel": checkin_session.cancel,
    "log_play": lambda user, source, media_type, media_id: checkin_session.log_play(
        user,
        source,
        media_id,
    ),
}


INLINE_TYPES = {MediaTypes.GAME.value, MediaTypes.MOVIE.value}


@require_POST
def checkin_action(request, source, media_type, media_id):
    """Run a Check-in action; games and movies update without replacing artwork."""
    name = request.POST.get("action")
    if name == "refresh" and media_type in INLINE_TYPES:
        return _render_checkin_state(request, source, media_type, media_id)
    from_card = request.POST.get("from_now_playing") == "1"
    if from_card:
        state = live_playback.peek_user_playback_state(request.user.id) or {}
        control = checkin.card_control(request.user.id, state)
        if not control or (
            control["token"] != request.POST.get("checkin_token")
            or control["source"] != source
            or control["media_type"] != media_type
            or str(control["media_id"]) != str(media_id)
            or name not in (control["action"], "cancel")
        ):
            return HttpResponseBadRequest("This check-in is no longer active.")
    if checkin_session.supports(media_type):
        action = SESSION_ACTIONS.get(name)
        arguments = (request.user, source, media_type, media_id)
    else:
        action = ACTIONS.get(name) if checkin.supports(media_type, source) else None
        arguments = (request.user, media_type, media_id)
    if action is None:
        return HttpResponseBadRequest("Unsupported check-in")

    try:
        action(*arguments)
    except checkin.CheckInError as error:
        return HttpResponseBadRequest(error.message)
    except Exception:
        logger.exception("Check-in action failed")
        return HttpResponse("Check-in failed. Try again.", status=502)

    if from_card:
        card = live_playback.build_home_playback_card(request.user)
        if card is None:
            return HttpResponse("")
        return render(request, "app/components/active_playback_card.html", {
            "active_playback_card": card,
        })
    if request.POST.get("then") == "edit":
        # The page opens the edit dialog itself, and refreshes when that is saved.
        return HttpResponse(status=204)
    if media_type in INLINE_TYPES:
        return _render_checkin_state(request, source, media_type, media_id)
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


def _render_checkin_state(request, source, media_type, media_id):
    """Render only tracking state, using stored entries and cached metadata."""
    # A timed refresh can settle a movie; read entries after that write.
    checkin.settle(request.user.id)
    checkin_session.settle(request.user.id)
    queryset = BasicMedia.objects.filter_media_prefetch(
        request.user,
        media_id,
        media_type,
        source,
    )
    current = select_preferred_activity_entry(queryset)
    if current is None:
        return HttpResponseBadRequest("Track this before checking in.")
    entries = sorted(queryset, key=helpers.entry_activity_key, reverse=True)
    metadata = cache.get(f"{source}_{media_type}_{media_id}") or current.item
    play_stats, subtitle = _build_detail_activity_state(
        media_type,
        {},
        current_instance=current,
        user_medias=entries,
    )
    response = render(
        request,
        "app/components/detail_checkin_state.html",
        {
            "media": metadata,
            "media_type": media_type,
            "current_instance": current,
            "user_medias": entries,
            "play_stats": play_stats,
            "activity_subtitle": subtitle,
            "detail_return_url": media_url(current.item),
        },
    )
    response["Cache-Control"] = "no-store"
    return response
