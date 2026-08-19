from drf_spectacular.extensions import (
    OpenApiAuthenticationExtension,
    OpenApiSerializerFieldExtension,
)
from drf_spectacular.utils import OpenApiParameter

from api.helpers import (
    MEDIA_STATUS_MAP,
    MEDIA_TYPE_COMPLETE_VALID_LIST,
    MEDIA_TYPE_VALID_LIST,
)

STATUS_LABELS_BY_CODE = {code: label for label, code in MEDIA_STATUS_MAP.items()}

MEDIA_TYPE_PARAM = OpenApiParameter(
    name="media_type",
    type=str,
    location=OpenApiParameter.PATH,
    enum=MEDIA_TYPE_VALID_LIST,
    description="Media type. Does not include `season`/`episode` — those are "
    "addressed via separate path segments under `tv`.",
)

MEDIA_TYPE_COMPLETE_PARAM = OpenApiParameter(
    name="media_type",
    type=str,
    location=OpenApiParameter.PATH,
    enum=MEDIA_TYPE_COMPLETE_VALID_LIST,
    description=(
        "Media type, including `season` and `episode`. POST to a media-type "
        "collection creates a new consumption; omitted status defaults to "
        "Planning. Use the history/{consumption_id} route to update one "
        "specific existing consumption."
    ),
)

MEDIA_TYPE_TV_ONLY_PARAM = OpenApiParameter(
    name="media_type",
    type=str,
    location=OpenApiParameter.PATH,
    enum=["tv"],
    description="Episode-level operations are only supported for `tv` media.",
)


class BearerAuthenticationScheme(OpenApiAuthenticationExtension):
    """Describe the custom bearer token auth scheme for OpenAPI generation."""

    target_class = "api.authentication.BearerAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, _auto_schema):
        """Return the OpenAPI security scheme for bearer authentication."""
        return {
            "type": "http",
            "scheme": "bearer",
        }


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """Describe the custom API key auth scheme for OpenAPI generation."""

    target_class = "api.authentication.APIKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, _auto_schema):
        """Return the OpenAPI security scheme for header-based API keys."""
        return {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        }


class StatusFieldExtension(OpenApiSerializerFieldExtension):
    """Describe the real wire format of StatusField for OpenAPI generation."""

    target_class = "api.serializers.StatusField"

    def map_serializer_field(self, auto_schema, direction):
        """Return the OpenAPI schema for status: integer code, string label on write."""
        return {
            "type": "integer",
            "enum": sorted(STATUS_LABELS_BY_CODE),
            "x-enumNames": [
                STATUS_LABELS_BY_CODE[code] for code in sorted(STATUS_LABELS_BY_CODE)
            ],
            "description": (
                "Responses always return the integer code. Requests (POST/PATCH) "
                "may alternatively send the status label as a case-insensitive "
                'string (e.g. "completed", "In Progress") instead of the integer '
                "code.\n\nInteger mapping: "
                + ", ".join(
                    f"{code} = {STATUS_LABELS_BY_CODE[code]}"
                    for code in sorted(STATUS_LABELS_BY_CODE)
                )
            ),
            "nullable": True,
        }
