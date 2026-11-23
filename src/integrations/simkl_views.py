"""Connect a SIMKL account to send plays, and choose when they are sent.

The behaviour is shared with every other destination
(``integrations.state.destinations``); this module only says what is particular
to SIMKL and gives the shared steps their URLs. The import connection on the
same provider page is separate and untouched.
"""

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from integrations import simkl_api
from integrations.models import CAPABILITY_PLAY_PUSH, SimklAccount, SyncClientKind
from integrations.state import export
from integrations.state.destinations import PushDestination

INSTANCE_KEY = "simkl.com"
SENDABLE = (("plays", CAPABILITY_PLAY_PUSH),)


def _library_preview(user):
    """Count what "Send existing library" would queue, without reading history."""
    preview = export.library_preview(user)
    return {"plays": preview["plays"], "undated": preview["undated"]}


DESTINATION = PushDestination(
    slug="simkl",
    label="SIMKL",
    kind=SyncClientKind.SIMKL.value,
    instance_key=INSTANCE_KEY,
    account_model=SimklAccount,
    api=simkl_api,
    sendable=SENDABLE,
    account_flags=("send_undated",),
    export_task="export_simkl_library",
    missing_key_message=(
        "SIMKL needs your own Client ID. Add it in Settings > Metadata, then "
        "connect again."
    ),
    preview=_library_preview,
)


def simkl_status(user):
    """Return bounded connection and delivery state for the settings card."""
    return DESTINATION.status(user)


@login_required
@require_POST
def simkl_connect(request):
    """Ask SIMKL for a login code the user approves on simkl.com."""
    return DESTINATION.connect(request)


@login_required
@require_POST
def simkl_poll(request):
    """Check once whether the user has approved; the card calls this repeatedly."""
    return DESTINATION.poll(request)


@login_required
@require_POST
def simkl_cancel(request):
    """Abandon a login code that has not been approved."""
    return DESTINATION.cancel(request)


@login_required
@require_POST
def simkl_settings(request):
    """Choose what is sent, and how soon. Nothing is sent that is switched off."""
    return DESTINATION.save_settings(request)


@login_required
@require_POST
def simkl_disconnect(request):
    """Stop locally first, then ask SIMKL to revoke the login."""
    return DESTINATION.disconnect(request)


@login_required
@require_POST
def simkl_export(request):
    """Queue the user's existing plays, only because they asked for it."""
    return DESTINATION.export_library(request)
