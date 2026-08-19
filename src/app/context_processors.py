# https://docs.djangoproject.com/en/stable/ref/templates/api/#writing-your-own-context-processors

from django.conf import settings
from django.utils.functional import SimpleLazyObject

from app.models import MediaTypes, Sources, Status
from users.helpers import is_first_run


def export_vars(request):
    """Export variables to templates."""
    return {
        "REGISTRATION": settings.REGISTRATION,
        "REDIRECT_LOGIN_TO_SSO": settings.REDIRECT_LOGIN_TO_SSO,
        "IMG_NONE": settings.IMG_NONE,
        "TRACK_TIME": settings.TRACK_TIME,
        "FORK_OWNER_NAME": settings.FORK_OWNER_NAME,
        "FORK_OWNER_URL": settings.FORK_OWNER_URL,
        "IS_FIRST_RUN": SimpleLazyObject(is_first_run),
    }


def media_enums(request):
    """Export media enums to templates."""
    return {
        "MediaTypes": MediaTypes,
        "Sources": Sources,
        "Status": Status,
    }
