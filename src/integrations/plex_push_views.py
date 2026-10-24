"""The Send Watched to Plex modal: choose a Plex user, preview, then send.

The Home user token lives for one request; the preview is rendered straight
from the plan and nothing about it is stored. Only the send writes, in a
background task the popup polls.
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from kombu.exceptions import OperationalError as BrokerOperationalError

from integrations import plex as plex_api
from integrations import plex_watched_push
from integrations.models import PlexAccount
from integrations.safe_fetch import UnsafeUrlError

TARGETS_TEMPLATE = "users/components/plex_push_targets.html"
PREVIEW_TEMPLATE = "users/components/plex_push_preview.html"
RESULT_TEMPLATE = "users/components/plex_push_result.html"
# Long enough to cover a request that hits the web worker's timeout.
PREVIEW_LOCK_SECONDS = 300


_SESSION_ERRORS = (
    plex_watched_push.PlexPushError,
    plex_api.PlexAuthError,
    plex_api.PlexClientError,
    UnsafeUrlError,
)


def _account(user):
    account = PlexAccount.objects.filter(user=user).first()
    return account if account and account.plex_token else None


def _with_session(request, template, action):
    """Open a Plex session for the posted user and render ``action``'s context.

    One preview or send runs at a time per user, so a double click cannot
    send twice.
    """
    account = _account(request.user)
    if account is None:
        return render(request, template, {"error": "Connect Plex first."})

    lock = plex_watched_push.lock_key(request.user.pk)
    if not cache.add(lock, 1, timeout=PREVIEW_LOCK_SECONDS):
        error = "A check or send is already running. Wait for it to finish."
        return render(request, template, {"error": error})
    try:
        session = plex_watched_push.open_session(
            account,
            request.POST.get("user_uuid", ""),
            request.POST.get("machine_identifier", ""),
            request.POST.get("pin") or None,
        )
        context = action(account, session)
    except _SESSION_ERRORS as error:
        return render(request, template, {"error": plex_watched_push.describe_error(error)})
    finally:
        cache.delete(lock)
    return render(request, template, {"session": session, **context})


@login_required
@require_GET
def plex_push_targets(request):
    """Render the Plex user and server pickers."""
    account = _account(request.user)
    if account is None:
        return render(request, TARGETS_TEMPLATE, {"error": "Connect Plex first."})
    try:
        users, servers = plex_watched_push.list_targets(account)
    except plex_api.PlexAuthError:
        error = "Plex rejected the saved token. Reconnect Plex."
        return render(request, TARGETS_TEMPLATE, {"error": error})
    except plex_api.PlexClientError:
        error = "Plex could not be reached. Try again."
        return render(request, TARGETS_TEMPLATE, {"error": error})
    return render(request, TARGETS_TEMPLATE, {"users": users, "servers": servers})


@login_required
@require_POST
def plex_push_preview(request):
    """Render what a push would change for the chosen Plex user. Writes nothing."""
    return _with_session(
        request,
        PREVIEW_TEMPLATE,
        lambda account, session: {
            "plan": plex_watched_push.build_plan(request.user, account, session),
        },
    )


@login_required
@require_POST
def plex_push_send(request):
    """Queue marking the ticked preview rows watched in Plex for the chosen user."""
    selected = set()
    for value in request.POST.get("writes", "").split(","):
        rating_key, _, item_id = value.rpartition(":")
        if rating_key and item_id.isdigit():
            selected.add((rating_key, int(item_id)))
    if not selected:
        return render(request, RESULT_TEMPLATE, {"error": "Tick at least one item."})
    account = _account(request.user)
    if account is None:
        return render(request, RESULT_TEMPLATE, {"error": "Connect Plex first."})

    user_id = request.user.pk
    lock = plex_watched_push.lock_key(user_id)
    if not cache.add(lock, 1, timeout=plex_watched_push.LOCK_SECONDS):
        error = "A check or send is already running. Wait for it to finish."
        return render(request, RESULT_TEMPLATE, {"error": error})
    from integrations.tasks._plex_push import send_plex_watched_push

    pin = request.POST.get("pin") or None
    try:
        # Opened here only to refuse a wrong PIN or server before queueing.
        session = plex_watched_push.open_session(
            account,
            request.POST.get("user_uuid", ""),
            request.POST.get("machine_identifier", ""),
            pin,
        )
    except _SESSION_ERRORS as error:
        cache.delete(lock)
        return render(
            request,
            RESULT_TEMPLATE,
            {"error": plex_watched_push.describe_error(error)},
        )

    cache.set(
        plex_watched_push.status_key(user_id),
        {"done": False, "current": 0, "total": len(selected)},
        plex_watched_push.STATUS_SECONDS,
    )
    if pin:
        cache.set(plex_watched_push.pin_key(user_id), pin, plex_watched_push.LOCK_SECONDS)
    try:
        send_plex_watched_push.delay(
            user_id,
            session.target.uuid,
            session.server.machine_identifier,
            sorted(selected),
        )
    except BrokerOperationalError:
        cache.delete_many(
            [lock, plex_watched_push.pin_key(user_id), plex_watched_push.status_key(user_id)],
        )
        error = "The send could not be started. Try again."
        return render(request, RESULT_TEMPLATE, {"error": error})
    return _render_status(request)


@login_required
@require_GET
def plex_push_status(request):
    """Render the progress or the result of the user's latest send."""
    return _render_status(request)


def _render_status(request):
    status = cache.get(plex_watched_push.status_key(request.user.pk))
    if status is None:
        return render(request, RESULT_TEMPLATE, {"error": "No send is running."})
    return render(request, RESULT_TEMPLATE, status)
