"""Send a library's existing plays to SIMKL, on request.

SIMKL's history is a list of dated watches, and an import from SIMKL itself
would otherwise be sent straight back, so imported history never reaches it by
itself (``ACCEPTS_IMPORTED_CHANGES`` is off). This is the one way it does, and
only when the user asks on the settings card. The queuing is shared with every
other destination (``integrations.state.export``).

Plays without a date are left out unless the user chose to send them: SIMKL has
no "no date" of its own, so they go out with its "I don't remember" date.
"""

from celery import shared_task
from django.contrib.auth import get_user_model

from integrations.models import SimklAccount, SyncBinding, SyncClientKind
from integrations.state import export


def simkl_play_rows(user, *, include_undated):
    """Return every dated play, and the undated ones when asked for."""
    rows = [*export.movie_plays(user), *export.episode_plays(user)]
    if include_undated:
        rows.extend(export.undated_plays(user))
    return rows


@shared_task(name="Export library to SIMKL", queue="celery")
def export_simkl_library(user_id):
    """Queue every play SIMKL takes, once."""
    user = get_user_model().objects.filter(pk=user_id).first()
    account = SimklAccount.objects.filter(user_id=user_id).first() if user else None
    binding = (
        SyncBinding.objects.filter(
            user_id=user_id,
            client_kind=SyncClientKind.SIMKL.value,
            profile_key=account.profile_key,
        ).first()
        if account and account.profile_key
        else None
    )
    if binding is None:
        return 0
    return export.queue_library(
        binding,
        user,
        client_kind=SyncClientKind.SIMKL.value,
        play_rows=lambda: simkl_play_rows(user, include_undated=account.send_undated),
    )
