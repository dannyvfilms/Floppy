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

MEDIA_LIST_FILTER_PARAMS = [
    OpenApiParameter(
        name="status",
        type=str,
        location=OpenApiParameter.QUERY,
        many=True,
        description=(
            "Repeated status values. Accepts numeric codes 0=Planning, "
            "1=In progress, 2=Paused, 3=Completed, 4=Dropped; labels; "
            "`all`; and `no_status`."
        ),
    ),
    OpenApiParameter(
        name="rating",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["all", "rated", "not_rated"],
    ),
    OpenApiParameter(
        name="collection",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["all", "collected", "not_collected"],
    ),
    OpenApiParameter(
        name="progress",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["all", "caught_up", "not_caught_up"],
        description="Currently meaningful for TV and anime lists.",
    ),
    OpenApiParameter(name="genre", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="implied_genre",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Music-only implied genre filter.",
    ),
    OpenApiParameter(name="year", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="release",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["all", "released", "not_released"],
    ),
    OpenApiParameter(name="source", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="media_status",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Provider metadata status, not the user's tracking status.",
    ),
    OpenApiParameter(name="language", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="country", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="platform",
        type=str,
        location=OpenApiParameter.QUERY,
        many=True,
        description="Repeat for multiple platforms; comma-separated values are also accepted.",
    ),
    OpenApiParameter(
        name="platform_mode",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["and", "or", "not"],
    ),
    OpenApiParameter(name="origin", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="format", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="author", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(name="provider", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="tag",
        type=str,
        location=OpenApiParameter.QUERY,
        many=True,
        description="Repeat for multiple tags; comma-separated values are also accepted.",
    ),
    OpenApiParameter(
        name="tag_mode",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["and", "or", "not"],
    ),
    OpenApiParameter(
        name="tag_exclude",
        type=str,
        location=OpenApiParameter.QUERY,
        description="Legacy alias for `tag=<value>&tag_mode=not`.",
    ),
    OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY),
    OpenApiParameter(
        name="sort",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=[
            "score",
            "critic_rating",
            "title",
            "author",
            "popularity",
            "progress",
            "runtime",
            "time_to_beat",
            "platform",
            "plays",
            "time_watched",
            "release_date",
            "date_added",
            "start_date",
            "end_date",
            "next_episode_air_date",
            "time_left",
            "added",
            "updated",
            "itemid",
            "mediaid",
            "type",
            "source",
            "id",
            "ended",
            "started",
        ],
        description="Legacy `field_asc`/`field_desc` suffixes remain accepted.",
    ),
    OpenApiParameter(
        name="direction",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=["asc", "desc"],
    ),
    OpenApiParameter(
        name="limit",
        type=int,
        location=OpenApiParameter.QUERY,
        description="Maximum 200; defaults to 20.",
    ),
    OpenApiParameter(
        name="offset",
        type=int,
        location=OpenApiParameter.QUERY,
        description="Zero-based result offset; defaults to 0.",
    ),
]

MEDIA_LIST_ROOT_PARAMS = [
    OpenApiParameter(
        name="media_type",
        type=str,
        location=OpenApiParameter.QUERY,
        enum=MEDIA_TYPE_COMPLETE_VALID_LIST,
        description="Optional type restriction; omitted returns the default media types.",
    ),
    OpenApiParameter(
        name="exclude",
        type=str,
        location=OpenApiParameter.QUERY,
        many=True,
        description="Root-list type exclusions; repeated and comma-separated syntax are accepted.",
    ),
    *MEDIA_LIST_FILTER_PARAMS,
]


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


class ListenBrainzAuthenticationScheme(OpenApiAuthenticationExtension):
    """Describe the ListenBrainz-compatible token header."""

    target_class = "api.authentication.ListenBrainzTokenAuthentication"
    name = "listenBrainzToken"

    def get_security_definition(self, _auto_schema):
        """Return the protocol's ``Authorization: Token <token>`` scheme."""
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "ListenBrainz token in the form `Token <token>`.",
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
