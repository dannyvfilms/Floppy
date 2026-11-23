"""Connect a WeTrakr account and choose what Floppy sends to it, and when.

The behaviour is shared with every other destination
(``integrations.state.destinations``); this module only says what is particular
to WeTrakr and gives the shared steps their URLs.
"""

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from integrations import wetrakr_api
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    CAPABILITY_PLAY_REMOVE,
    CAPABILITY_RATING_PUSH,
    CAPABILITY_STATUS_PUSH,
    SyncClientKind,
    WeTrakrAccount,
)
from integrations.state.destinations import MIN_POLL_SECONDS, PushDestination

INSTANCE_KEY = "wetrakr.com"
# What the card lets the user switch on, by form field.
SENDABLE = (
    ("plays", CAPABILITY_PLAY_PUSH),
    ("removals", CAPABILITY_PLAY_REMOVE),
    ("statuses", CAPABILITY_STATUS_PUSH),
    ("ratings", CAPABILITY_RATING_PUSH),
)

__all__ = ["MIN_POLL_SECONDS", "wetrakr_status"]


def _library_preview(user):
    from integrations.tasks._wetrakr_export import library_preview

    return library_preview(user)


DESTINATION = PushDestination(
    slug="wetrakr",
    label="WeTrakr",
    kind=SyncClientKind.WETRAKR.value,
    instance_key=INSTANCE_KEY,
    account_model=WeTrakrAccount,
    api=wetrakr_api,
    sendable=SENDABLE,
    passive=frozenset({"removals"}),
    export_task="export_wetrakr_library",
    preview=_library_preview,
)


def wetrakr_status(user):
    """Return bounded connection and delivery state for the settings card."""
    return DESTINATION.status(user)


@login_required
@require_POST
def wetrakr_connect(request):
    """Ask WeTrakr for a login code the user approves on wetrakr.com."""
    return DESTINATION.connect(request)


@login_required
@require_POST
def wetrakr_poll(request):
    """Check once whether the user has approved; the card calls this repeatedly."""
    return DESTINATION.poll(request)


@login_required
@require_POST
def wetrakr_cancel(request):
    """Abandon a login code that has not been approved."""
    return DESTINATION.cancel(request)


@login_required
@require_POST
def wetrakr_settings(request):
    """Choose what is sent, and how soon. Nothing is sent that is switched off."""
    return DESTINATION.save_settings(request)


@login_required
@require_POST
def wetrakr_disconnect(request):
    """Stop locally first, then ask WeTrakr to end the login."""
    return DESTINATION.disconnect(request)


@login_required
@require_POST
def wetrakr_export(request):
    """Queue the user's existing library, only because they asked for it."""
    return DESTINATION.export_library(request)
