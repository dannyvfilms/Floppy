"""HTTP endpoint behind the Check-in button on a detail page."""

import logging

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST

from app import checkin

logger = logging.getLogger(__name__)

ACTIONS = {
    "start": checkin.start,
    "resume": checkin.start,
    "pause": checkin.pause,
    "finish": checkin.finish,
    "cancel": checkin.cancel,
}


@require_POST
def checkin_action(request, source, media_type, media_id):
    """Run one Check-in action, then have htmx refresh the page it came from."""
    action = ACTIONS.get(request.POST.get("action"))
    if action is None or not checkin.supports(media_type, source):
        return HttpResponseBadRequest("Unsupported check-in")

    try:
        action(request.user, media_type, media_id)
    except checkin.CheckInError as error:
        return HttpResponseBadRequest(str(error))
    except Exception:
        logger.exception("Check-in action failed")
        return HttpResponse("Check-in failed. Try again.", status=502)

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
