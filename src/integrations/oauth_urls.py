"""URL routes for Floppy's OAuth device flow."""

from django.urls import path

from integrations.oauth_device import oauth_device, oauth_device_authorization
from integrations.oauth_management import oauth_applications, oauth_revoke_application
from integrations.oauth_metadata import (
    oauth_authorization_server_metadata,
    oauth_scope_metadata,
)
from integrations.oauth_revocation import oauth_revoke
from integrations.oauth_token import oauth_token

urlpatterns = [
    path(
        ".well-known/oauth-authorization-server",
        oauth_authorization_server_metadata,
        name="oauth_authorization_server_metadata",
    ),
    path(
        "oauth/device/authorization",
        oauth_device_authorization,
        name="oauth_device_authorization",
    ),
    path("oauth/device", oauth_device, name="oauth_device"),
    path("oauth/token", oauth_token, name="oauth_token"),
    path("oauth/revoke", oauth_revoke, name="oauth_revoke"),
    path("oauth/scopes", oauth_scope_metadata, name="oauth_scope_metadata"),
    path(
        "settings/integrations/applications",
        oauth_applications,
        name="oauth_applications",
    ),
    path(
        "settings/integrations/applications/<str:client_id>/revoke",
        oauth_revoke_application,
        name="oauth_revoke_application",
    ),
]
