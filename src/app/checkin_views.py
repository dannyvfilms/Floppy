"""HTTP endpoint behind the Check-in button on a detail page."""

import logging

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST

from app import checkin, checkin_session

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


@require_POST
def checkin_action(request, source, media_type, media_id):
    """Run one Check-in action, then have htmx refresh the page it came from."""
    name = request.POST.get("action")
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

    if request.POST.get("then") == "edit":
        # The page opens the edit dialog itself, and refreshes when that is saved.
        return HttpResponse(status=204)
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
