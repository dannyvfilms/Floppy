"""Template helpers for user-created scoped integration tokens."""

from django import template

from integrations.models import IntegrationToken

register = template.Library()


def _manual_tokens(user, *, revoked):
    """Return user-created app tokens, excluding OAuth-issued credentials."""
    if not getattr(user, "is_authenticated", False):
        return []

    revoked_filter = {"revoked_at__isnull": not revoked}
    return list(
        IntegrationToken.objects.filter(
            user=user,
            client_identifier="",
            **revoked_filter,
        ).order_by("-created_at")
    )


@register.simple_tag
def active_integration_tokens(user):
    """Return active user-created app tokens for the settings component."""
    return _manual_tokens(user, revoked=False)


@register.simple_tag
def revoked_integration_tokens(user):
    """Return revoked user-created app tokens eligible for deletion."""
    return _manual_tokens(user, revoked=True)
