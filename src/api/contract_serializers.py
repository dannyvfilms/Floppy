"""Wire-only serializers for the verified OpenAPI consumer contract."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(
    {"oneOf": [{"type": "string"}, {"type": "integer"}]}
)
class MediaIdField(serializers.Field):
    """Provider media identifiers are strings or integers on the wire."""


@extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}]})
class StatusInputField(serializers.Field):
    """Status accepts its numeric code or case-insensitive label."""


@extend_schema_field(
    {
        "type": "string",
        "description": "ISO 8601 date or date-time accepted by this deployment.",
    }
)
class DateOrDateTimeField(serializers.Field):
    """TRACK_TIME determines whether dates retain a time component."""


class SearchResultSerializer(serializers.Serializer):
    """Fields guaranteed by every provider search result."""

    media_id = MediaIdField()
    source = serializers.CharField()
    media_type = serializers.CharField()
    title = serializers.CharField(allow_blank=True, allow_null=True)
    image = serializers.CharField(allow_blank=True, allow_null=True)


class PaginationSerializer(serializers.Serializer):
    """Stable limit/offset response metadata."""

    total = serializers.IntegerField()
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


class SearchEnvelopeSerializer(serializers.Serializer):
    """Search response envelope."""

    pagination = PaginationSerializer()
    results = SearchResultSerializer(many=True)


class TrackMediaRequestSerializer(serializers.Serializer):
    """Accepted provider, manual-item, and tracking fields."""

    source = serializers.CharField(required=False)
    media_id = MediaIdField(required=False)
    title = serializers.CharField(required=False, allow_blank=True)
    image = serializers.CharField(required=False, allow_blank=True)
    image_url = serializers.URLField(required=False, allow_blank=True)
    season_number = serializers.IntegerField(required=False, allow_null=True)
    episode_number = serializers.IntegerField(required=False, allow_null=True)
    parent_tv = serializers.IntegerField(required=False)
    parent_season = serializers.IntegerField(required=False)
    library_media_type = serializers.CharField(required=False, allow_blank=True)
    score = serializers.FloatField(required=False, allow_null=True)
    status = StatusInputField(required=False, allow_null=True)
    progress = serializers.FloatField(required=False, allow_null=True)
    start_date = DateOrDateTimeField(required=False, allow_null=True)
    end_date = DateOrDateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class MediaUpdateRequestSerializer(serializers.Serializer):
    """Fields accepted by tracked-media PATCH operations."""

    score = serializers.FloatField(required=False, allow_null=True)
    status = StatusInputField(required=False, allow_null=True)
    progress = serializers.FloatField(required=False, allow_null=True)
    start_date = DateOrDateTimeField(required=False, allow_null=True)
    end_date = DateOrDateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class NextEpisodeSerializer(serializers.Serializer):
    """The next released, unwatched TV-like episode."""

    season_number = serializers.IntegerField(allow_null=True)
    episode_number = serializers.IntegerField()
    air_date = serializers.DateTimeField(allow_null=True)


class TrackedMediaResponseSerializer(serializers.Serializer):
    """Exact MediaSerializer representation returned after tracking."""

    id = serializers.IntegerField(allow_null=True)
    consumption_id = serializers.IntegerField(allow_null=True)
    item = serializers.DictField(allow_null=True)
    item_id = serializers.CharField(allow_null=True)
    parent_id = serializers.CharField(allow_null=True)
    tracked = serializers.BooleanField()
    created_at = serializers.DateTimeField(allow_null=True)
    score = serializers.FloatField(allow_null=True)
    status = serializers.IntegerField(allow_null=True)
    progress = serializers.FloatField(allow_null=True)
    progress_scope = serializers.CharField(allow_null=True)
    progress_unit = serializers.CharField(allow_null=True)
    progressed_at = serializers.DateTimeField(allow_null=True)
    start_date = serializers.DateTimeField(allow_null=True)
    end_date = serializers.DateTimeField(allow_null=True)
    notes = serializers.CharField(allow_blank=True, allow_null=True)
    lists = serializers.ListField(child=serializers.DictField())
    next_episode = NextEpisodeSerializer(allow_null=True)


class TrackedMediaEnvelopeSerializer(serializers.Serializer):
    """Paginated tracked-media collection."""

    pagination = PaginationSerializer()
    results = TrackedMediaResponseSerializer(many=True)


class ConsumptionResponseSerializer(serializers.Serializer):
    """Exact HistorySerializer representation."""

    consumption_id = serializers.IntegerField()
    created = serializers.DateTimeField(allow_null=True)
    score = serializers.FloatField(allow_null=True)
    progress = serializers.FloatField(allow_null=True)
    progressed_at = serializers.DateTimeField(allow_null=True)
    status = serializers.IntegerField(allow_null=True)
    start_date = serializers.DateTimeField(allow_null=True)
    end_date = serializers.DateTimeField(allow_null=True)
    notes = serializers.CharField(allow_blank=True, allow_null=True)


class CompleteMediaResponseSerializer(serializers.Serializer):
    """Exact top-level CompleteMediaSerializer envelope."""

    id = serializers.IntegerField(allow_null=True)
    media_id = serializers.CharField(allow_null=True)
    source = serializers.CharField(allow_null=True)
    source_url = serializers.CharField(allow_blank=True, allow_null=True)
    media_type = serializers.CharField()
    title = serializers.CharField(allow_blank=True, allow_null=True)
    max_progress = serializers.IntegerField()
    image = serializers.CharField(allow_blank=True, allow_null=True)
    synopsis = serializers.CharField(allow_blank=True, allow_null=True)
    genres = serializers.ListField(child=serializers.CharField(), allow_null=True)
    score = serializers.FloatField(allow_null=True)
    score_count = serializers.IntegerField(allow_null=True)
    details = serializers.DictField()
    related = serializers.DictField()
    item_id = serializers.CharField(allow_null=True)
    parent_id = serializers.CharField(allow_null=True)
    tracked = serializers.BooleanField()
    consumptions_number = serializers.IntegerField()
    consumptions = ConsumptionResponseSerializer(many=True)
    lists = serializers.ListField(child=serializers.DictField())


class EpisodeDetailsSerializer(serializers.Serializer):
    """Stable episode detail fields plus provider-owned nested records."""

    air_date = serializers.CharField(allow_null=True)
    episode_number = serializers.IntegerField()
    season_number = serializers.IntegerField()
    runtime = serializers.IntegerField(allow_null=True)
    episode_type = serializers.CharField(allow_null=True)
    crew = serializers.ListField(child=serializers.DictField())
    guest_stars = serializers.ListField(child=serializers.DictField())


class CompleteEpisodeResponseSerializer(CompleteMediaResponseSerializer):
    """Episode detail uses the same envelope with numbers inside details."""

    details = EpisodeDetailsSerializer()


class InfoResponseSerializer(serializers.Serializer):
    """Exact public info response."""

    version = serializers.CharField()
    debug = serializers.BooleanField()
    frontend_url = serializers.CharField()
    language = serializers.CharField()
    timezone = serializers.CharField()
    admin_enabled = serializers.BooleanField()
    track_time = serializers.BooleanField()


class DetailErrorSerializer(serializers.Serializer):
    """Shared API error body."""

    detail = serializers.CharField()
    errors = serializers.JSONField(required=False)


class ListenBrainzErrorSerializer(serializers.Serializer):
    """ListenBrainz-compatible error body."""

    code = serializers.IntegerField()
    error = serializers.CharField()


class ListenBrainzStatusSerializer(serializers.Serializer):
    """Successful submission response."""

    status = serializers.CharField()


class ListenBrainzTokenSerializer(serializers.Serializer):
    """Successful token validation response."""

    code = serializers.IntegerField()
    message = serializers.CharField()
    valid = serializers.BooleanField()
    user_name = serializers.CharField()
