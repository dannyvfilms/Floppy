import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="Refresh Plex library sections")
def refresh_plex_sections(user_id):
    """Refresh and persist cached Plex library sections for a user."""
    from integrations import plex as plex_api

    user = get_user_model().objects.get(id=user_id)
    account = getattr(user, "plex_account", None)
    if not account or not account.plex_token:
        return

    try:
        sections = plex_api.list_sections(account.plex_token)
    except plex_api.PlexAuthError as exc:
        logger.warning(
            "Plex token expired while refreshing sections for user %s: %s",
            user.username,
            exc,
        )
        return
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Could not refresh Plex libraries for user %s: %s", user.username, exc
        )
        return

    account.sections = sections
    account.sections_refreshed_at = timezone.now()
    account.save(update_fields=["sections", "sections_refreshed_at"])
