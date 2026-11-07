# https://docs.djangoproject.com/en/stable/ref/templates/api/#writing-your-own-context-processors

from django.conf import settings
from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _

from app.models import MediaTypes, Sources, Status
from users.helpers import is_first_run
from users.release_notes import release_tag


def _update_banner_props(request, tag):
    """Return the shared update banner props for superusers on a release build."""
    user = getattr(request, "user", None)
    if not tag or user is None or not user.is_authenticated or not user.is_superuser:
        return None
    return {
        "kind": "banner",
        "releaseTag": tag,
        "whatsNewUrl": f"{reverse('about')}#whats-new",
        "labels": {
            "updated": _("Floppy was updated to {tag}."),
            "whatsNew": _("See what's new"),
            "dismiss": _("Dismiss update notice"),
        },
    }


def export_vars(request):
    """Export variables to templates."""
    tag = release_tag(settings.VERSION)
    return {
        "REGISTRATION": settings.REGISTRATION,
        "REDIRECT_LOGIN_TO_SSO": settings.REDIRECT_LOGIN_TO_SSO,
        "IMG_NONE": settings.IMG_NONE,
        "TRACK_TIME": settings.TRACK_TIME,
        "FORK_OWNER_NAME": settings.FORK_OWNER_NAME,
        "FORK_OWNER_URL": settings.FORK_OWNER_URL,
        "IS_FIRST_RUN": SimpleLazyObject(is_first_run),
        "RELEASE_TAG": tag,
        "UPDATE_BANNER_PROPS": _update_banner_props(request, tag),
    }


def media_enums(request):
    """Export media enums to templates."""
    return {
        "MediaTypes": MediaTypes,
        "Sources": Sources,
        "Status": Status,
    }
