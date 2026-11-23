"""Send a library's existing plays, statuses and ratings to WeTrakr, on request.

Plays are WeTrakr's activity feed, so history never reaches it by itself
(``ACCEPTS_IMPORTED_CHANGES`` is off). This is the one way it does, and only
when the user asks for it on the settings card. The queuing is shared with every
other destination (``integrations.state.export``).

Plays without a date are left out rather than given an invented one: WeTrakr
would show them as watched today.
"""

from celery import shared_task
from django.contrib.auth import get_user_model

from integrations.models import SyncBinding, SyncClientKind, WeTrakrAccount
from integrations.state import export
from integrations.state.export import (
    episode_plays as _episode_plays,
)
from integrations.state.export import (
    library_preview,  # noqa: F401  (the settings card imports it from here)
)
from integrations.state.export import (
    movie_plays as _movie_plays,
)
from integrations.state.export import (
    statuses as _statuses,
)


@shared_task(name="Export library to WeTrakr", queue="celery")
def export_wetrakr_library(user_id):
    """Queue every dated play, and the statuses WeTrakr takes, once."""
    user = get_user_model().objects.filter(pk=user_id).first()
    account = WeTrakrAccount.objects.filter(user_id=user_id).first() if user else None
    binding = (
        SyncBinding.objects.filter(
            user_id=user_id,
            client_kind=SyncClientKind.WETRAKR.value,
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
        client_kind=SyncClientKind.WETRAKR.value,
        play_rows=lambda: [*_movie_plays(user), *_episode_plays(user)],
        status_rows=lambda: _statuses(user),
        rate=True,
    )
