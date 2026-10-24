"""Send a reviewed Plex watched push in the background.

A send is a fresh plan plus three Plex requests per item, which a large
selection cannot finish inside a web request. The view validates the session
and queues this task; the popup polls the status key until it is done.

The PIN, when the Home user has one, is handed over through the cache and
deleted on first read, so it never appears in the task's stored arguments.
"""

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.core.cache import cache

from integrations import plex as plex_api
from integrations import plex_watched_push
from integrations.models import PlexAccount
from integrations.plex_watched_push import (
    LOCK_SECONDS,
    STATUS_SECONDS,
    describe_error,
    lock_key,
    pin_key,
    status_key,
)
from integrations.safe_fetch import UnsafeUrlError


@shared_task(name="Send watched to Plex", queue="celery")
def send_plex_watched_push(user_id, user_uuid, machine_identifier, selected):
    """Mark the selected ``[rating_key, item_id]`` pairs watched in Plex."""
    pin = cache.get(pin_key(user_id))
    cache.delete(pin_key(user_id))
    status = {"done": True, "user_title": "", "result": None, "error": ""}
    try:
        user = get_user_model().objects.filter(pk=user_id).first()
        account = PlexAccount.objects.filter(user_id=user_id).first()
        if user is None or account is None or not account.plex_token:
            status["error"] = "Connect Plex first."
            return
        session = plex_watched_push.open_session(
            account,
            user_uuid,
            machine_identifier,
            pin,
        )
        status["user_title"] = session.target.title

        def progress(done, total):
            cache.set(
                status_key(user_id),
                {"done": False, "current": done, "total": total},
                STATUS_SECONDS,
            )
            cache.touch(lock_key(user_id), LOCK_SECONDS)

        status["result"] = plex_watched_push.send(
            user,
            account,
            session,
            {(rating_key, item_id) for rating_key, item_id in selected},
            progress,
        )
    except (
        plex_watched_push.PlexPushError,
        plex_api.PlexAuthError,
        plex_api.PlexClientError,
        UnsafeUrlError,
    ) as error:
        status["error"] = describe_error(error)
    except SoftTimeLimitExceeded:
        status["error"] = "The send ran out of time. Check again to send the rest."
    finally:
        if status["result"] is None and not status["error"]:
            status["error"] = "The send failed. Check again to see what is left."
        cache.set(status_key(user_id), status, STATUS_SECONDS)
        cache.delete(lock_key(user_id))
