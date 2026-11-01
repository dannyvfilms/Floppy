"""Wire-only serializers for the verified OpenAPI consumer contract."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

SCORED_AT_HELP = (
    "When the score was last set, changed or cleared; null when never scored "
    "or when the rating predates this field."
)


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


class HltbGameLengthSummarySerializer(serializers.Serializer):
    """HLTB main/main+extras/completionist/all-styles minute estimates."""

    main_minutes = serializers.IntegerField(allow_null=True)
    main_plus_minutes = serializers.IntegerField(allow_null=True)
    completionist_minutes = serializers.IntegerField(allow_null=True)
    all_styles_minutes = serializers.IntegerField(allow_null=True)


class IgdbGameLengthSummarySerializer(serializers.Serializer):
    """IGDB hastily/normally/completely second estimates."""

    hastily_seconds = serializers.IntegerField()
    normally_seconds = serializers.IntegerField()
    completely_seconds = serializers.IntegerField()
    count = serializers.IntegerField()


class ProviderGameLengthsSummarySerializer(serializers.Serializer):
    """Search-result length summary: totals only, no per-platform tables."""

    active_source = serializers.CharField(allow_blank=True)
    hltb_summary = HltbGameLengthSummarySerializer(required=False)
    igdb_summary = IgdbGameLengthSummarySerializer(required=False)


class HltbGameLengthSerializer(serializers.Serializer):
    """Full persisted HLTB game-length detail."""

    game_id = serializers.IntegerField()
    url = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    release_year = serializers.IntegerField(allow_null=True)
    summary = HltbGameLengthSummarySerializer()
    counts = serializers.DictField(child=serializers.IntegerField())
    single_player_table = serializers.ListField(child=serializers.DictField())
    platform_table = serializers.ListField(child=serializers.DictField())


class IgdbGameLengthSerializer(serializers.Serializer):
    """Full persisted IGDB game-length detail."""

    game_id = serializers.IntegerField()
    summary = IgdbGameLengthSummarySerializer()


class ProviderGameLengthsSerializer(serializers.Serializer):
    """Full persisted game-length payload, as returned on the detail endpoint."""

    active_source = serializers.CharField(allow_blank=True)
    state = serializers.ChoiceField(choices=["ready", "pending", "unavailable"])
    hltb = HltbGameLengthSerializer(required=False)
    igdb = IgdbGameLengthSerializer(required=False)


class SearchResultSerializer(serializers.Serializer):
    """Fields guaranteed by every provider search result."""

    media_id = MediaIdField()
    source = serializers.CharField()
    media_type = serializers.CharField()
    title = serializers.CharField(allow_blank=True, allow_null=True)
    image = serializers.CharField(allow_blank=True, allow_null=True)
    provider_game_lengths_summary = ProviderGameLengthsSummarySerializer(
        required=False,
    )


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
    # How this entry was created ("plex", "jellyfin", "trakt", "manual", …).
    # Distinct from the top-level `source` field on TrackMediaRequestSerializer,
    # which identifies the metadata provider.
    entry_source = serializers.CharField(
        required=False, allow_blank=True, allow_null=True,
    )


class TrackedMediaUpdateRequestSerializer(MediaUpdateRequestSerializer):
    """Tracked-media PATCH fields, including the shared item's artwork URL."""

    image_url = serializers.URLField(required=False, allow_blank=True)


class NextEpisodeSerializer(serializers.Serializer):
    """The next released, unwatched TV-like episode."""

    season_number = serializers.IntegerField(allow_null=True)
    episode_number = serializers.IntegerField()
    air_date = serializers.DateTimeField(allow_null=True)
    title = serializers.CharField(
        allow_null=True,
        help_text="The episode's own name; null when unknown, never the show's title.",
    )
    episode_code = serializers.CharField(
        allow_null=True,
        help_text="SxxEyy code, as in history entries; null without a season number.",
    )
    image = serializers.CharField(allow_null=True, allow_blank=True)
    ids = serializers.DictField(child=serializers.CharField())
    url = serializers.CharField(allow_null=True)


class ShowSerializer(serializers.Serializer):
    """The parent show/podcast for an episode-like tracked media entry."""

    id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField(allow_blank=True)
    slug = serializers.CharField(allow_blank=True)
    podcast_uuid = serializers.CharField(allow_null=True)
    image = serializers.CharField(allow_blank=True)
    website_url = serializers.CharField(allow_blank=True)


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
    scored_at = serializers.DateTimeField(
        allow_null=True,
        help_text=SCORED_AT_HELP,
    )
    status = serializers.IntegerField(allow_null=True)
    progress = serializers.FloatField(allow_null=True)
    episodes_left = serializers.IntegerField(allow_null=True)
    total_episodes_left = serializers.IntegerField(allow_null=True)
    progress_scope = serializers.CharField(allow_null=True)
    progress_unit = serializers.CharField(allow_null=True)
    progressed_at = serializers.DateTimeField(allow_null=True)
    start_date = serializers.DateTimeField(allow_null=True)
    end_date = serializers.DateTimeField(allow_null=True)
    notes = serializers.CharField(allow_blank=True, allow_null=True)
    source = serializers.CharField(allow_blank=True, allow_null=True)
    lists = serializers.ListField(child=serializers.DictField())
    next_episode = NextEpisodeSerializer(allow_null=True)
    show = ShowSerializer(allow_null=True)


class TrackedMediaEnvelopeSerializer(serializers.Serializer):
    """Paginated tracked-media collection."""

    pagination = PaginationSerializer()
    results = TrackedMediaResponseSerializer(many=True)


class ConsumptionResponseSerializer(serializers.Serializer):
    """Exact HistorySerializer representation."""

    consumption_id = serializers.IntegerField()
    created = serializers.DateTimeField(allow_null=True)
    score = serializers.FloatField(allow_null=True)
    scored_at = serializers.DateTimeField(
        allow_null=True,
        help_text=SCORED_AT_HELP,
    )
    progress = serializers.FloatField(allow_null=True)
    progressed_at = serializers.DateTimeField(allow_null=True)
    status = serializers.IntegerField(allow_null=True)
    start_date = serializers.DateTimeField(allow_null=True)
    end_date = serializers.DateTimeField(allow_null=True)
    notes = serializers.CharField(allow_blank=True, allow_null=True)
    source = serializers.CharField(allow_blank=True, allow_null=True)
    external_id = serializers.CharField(allow_blank=True, allow_null=True)


class MediaTypeStatusSerializer(serializers.Serializer):
    """Whether the media type of this item is enabled for the user."""

    media_type = serializers.CharField()
    enabled = serializers.BooleanField()
    message = serializers.CharField(allow_blank=True, allow_null=True)


class CompleteMediaResponseSerializer(serializers.Serializer):
    """Exact top-level CompleteMediaSerializer envelope."""

    id = serializers.IntegerField(allow_null=True)
    media_id = serializers.CharField(allow_null=True)
    source = serializers.CharField(allow_null=True)
    source_url = serializers.CharField(allow_blank=True, allow_null=True)
    media_type = serializers.CharField()
    title = serializers.CharField(allow_blank=True, allow_null=True)
    max_progress = serializers.IntegerField()
    episodes_left = serializers.IntegerField(allow_null=True)
    total_episodes_left = serializers.IntegerField(allow_null=True)
    image = serializers.CharField(allow_blank=True, allow_null=True)
    # FORK: 16:9 artwork
    backdrop = serializers.CharField(allow_null=True)
    synopsis = serializers.CharField(allow_blank=True, allow_null=True)
    genres = serializers.ListField(child=serializers.CharField(), allow_null=True)
    score = serializers.FloatField(allow_null=True)
    score_count = serializers.IntegerField(allow_null=True)
    # FORK: IMDb rating alongside TMDB-based score
    imdb_rating = serializers.FloatField(allow_null=True)
    imdb_rating_count = serializers.IntegerField(allow_null=True)
    cast = serializers.ListField(child=serializers.DictField())
    crew = serializers.ListField(child=serializers.DictField())
    details = serializers.DictField()
    related = serializers.DictField()
    item_id = serializers.CharField(allow_null=True)
    parent_id = serializers.CharField(allow_null=True)
    tracked = serializers.BooleanField()
    consumptions_number = serializers.IntegerField()
    consumptions = ConsumptionResponseSerializer(many=True)
    lists = serializers.ListField(child=serializers.DictField())
    media_type_status = MediaTypeStatusSerializer(allow_null=True)


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


class GameDetailsSerializer(serializers.Serializer):
    """Game detail fields plus the provider-owned game-lengths record."""

    provider_game_lengths = ProviderGameLengthsSerializer(
        allow_null=True,
        required=False,
    )


class CompleteGameResponseSerializer(CompleteMediaResponseSerializer):
    """Game detail uses the same envelope with lengths data inside details."""

    details = GameDetailsSerializer()


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


class CaseInsensitiveChoiceField(serializers.ChoiceField):
    """Accept a choice in any case with surrounding spaces."""

    def to_internal_value(self, data):
        """Normalize a string before matching it against the choices."""
        if isinstance(data, str):
            data = data.strip().lower()
        return super().to_internal_value(data)


class ListItemsReorderRequestSerializer(serializers.Serializer):
    """Move one list item to the front, back, next or last position."""

    ACTIONS = ("first", "back", "next", "last")

    item_id = serializers.IntegerField(
        min_value=1,
        help_text=(
            "Floppy's numeric Item id, the `id` field of an entry in "
            "GET /api/v1/lists/{list_id}/items/ (not the `item_id` string)."
        ),
    )
    action = CaseInsensitiveChoiceField(
        choices=ACTIONS,
        help_text=(
            "first: move to the top. back: swap with the item above. "
            "next: swap with the item below. last: move to the bottom."
        ),
    )


class ListItemsOrderRequestSerializer(serializers.Serializer):
    """Replace the order of a list's items."""

    item_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        min_length=1,
        help_text=(
            "Floppy's numeric Item ids in the new order, the `id` field of an "
            "entry in GET /api/v1/lists/{list_id}/items/ (not the `item_id` "
            "string). Send every item of the list, or only a subset: the "
            "listed items take the positions they already occupy, in the "
            "order given, and the other items stay where they are. Each id "
            "must appear once and belong to this list; otherwise the request "
            "is rejected with 400 and nothing changes."
        ),
    )


class ListItemRankSerializer(serializers.Serializer):
    """One item's rank in an outside ranking."""

    item_id = serializers.IntegerField(
        min_value=1,
        help_text=(
            "Floppy's numeric Item id, the `id` field of an entry in "
            "GET /api/v1/lists/{list_id}/items/ (not the `item_id` string)."
        ),
    )
    rank = serializers.IntegerField(
        min_value=1,
        max_value=2_147_483_647,
        allow_null=True,
        help_text="The item's rank, such as 81 for #81. null clears its rank.",
    )


class ListItemsRanksRequestSerializer(serializers.Serializer):
    """Set or clear the ranks of some items in a list."""

    ranks = serializers.ListField(
        child=ListItemRankSerializer(),
        allow_empty=False,
        min_length=1,
        help_text=(
            "Only the items listed change; every other item keeps its rank. "
            "Each item_id may appear once and must belong to this list; "
            "otherwise the request is rejected with 400 and nothing changes. "
            "Different items may share a rank (a tie). Saving the ranks also "
            "puts the ranked items of the list in rank order."
        ),
    )


class ListItemResponseSerializer(TrackedMediaResponseSerializer):
    """A list entry: the tracked media plus its rank in this list."""

    rank = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "The item's rank in an outside ranking, set with PUT "
            "/api/v1/lists/{list_id}/items/ranks/; null when it has none. "
            "The order of the entries is the list's custom order."
        ),
    )


class ListItemsEnvelopeSerializer(serializers.Serializer):
    """Paginated list entries."""

    pagination = PaginationSerializer()
    results = ListItemResponseSerializer(many=True)


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


class ListenBrainzListenSerializer(serializers.Serializer):
    """One recorded listen in ListenBrainz's response shape."""

    listened_at = serializers.IntegerField()
    track_metadata = serializers.DictField()


class ListenBrainzListensPayloadSerializer(serializers.Serializer):
    """Page of listens for a user."""

    count = serializers.IntegerField()
    listens = ListenBrainzListenSerializer(many=True)
    latest_listen_ts = serializers.IntegerField()
    oldest_listen_ts = serializers.IntegerField()


class ListenBrainzListensSerializer(serializers.Serializer):
    """ListenBrainz `user/listens` response wrapper."""

    payload = ListenBrainzListensPayloadSerializer()


class ListenBrainzStatsPayloadSerializer(serializers.Serializer):
    """Fields every ListenBrainz user statistics page carries."""

    count = serializers.IntegerField()
    offset = serializers.IntegerField()
    range = serializers.CharField()
    from_ts = serializers.IntegerField()
    to_ts = serializers.IntegerField()
    last_updated = serializers.IntegerField()
    user_id = serializers.CharField()


class ListenBrainzUserArtistSerializer(serializers.Serializer):
    """One artist in a user's ranking."""

    artist_mbid = serializers.CharField(allow_null=True)
    artist_name = serializers.CharField()
    listen_count = serializers.IntegerField()


class ListenBrainzUserArtistsPayloadSerializer(ListenBrainzStatsPayloadSerializer):
    """Page of a user's top artists."""

    artists = ListenBrainzUserArtistSerializer(many=True)
    total_artist_count = serializers.IntegerField()


class ListenBrainzUserArtistsSerializer(serializers.Serializer):
    """ListenBrainz `stats/user/artists` response wrapper."""

    payload = ListenBrainzUserArtistsPayloadSerializer()


class ListenBrainzUserReleaseGroupSerializer(serializers.Serializer):
    """One release group in a user's ranking."""

    artist_mbids = serializers.ListField(child=serializers.CharField())
    artist_name = serializers.CharField()
    release_group_mbid = serializers.CharField(allow_null=True)
    release_group_name = serializers.CharField()
    caa_id = serializers.IntegerField(allow_null=True)
    caa_release_mbid = serializers.CharField(allow_null=True)
    listen_count = serializers.IntegerField()


class ListenBrainzUserReleaseGroupsPayloadSerializer(
    ListenBrainzStatsPayloadSerializer,
):
    """Page of a user's top release groups."""

    release_groups = ListenBrainzUserReleaseGroupSerializer(many=True)
    total_release_group_count = serializers.IntegerField()


class ListenBrainzUserReleaseGroupsSerializer(serializers.Serializer):
    """ListenBrainz `stats/user/release-groups` response wrapper."""

    payload = ListenBrainzUserReleaseGroupsPayloadSerializer()


class ListenBrainzUserRecordingSerializer(serializers.Serializer):
    """One recording in a user's ranking."""

    artist_mbids = serializers.ListField(child=serializers.CharField())
    artist_name = serializers.CharField()
    recording_mbid = serializers.CharField(allow_null=True)
    release_mbid = serializers.CharField(allow_null=True)
    release_name = serializers.CharField(allow_null=True)
    track_name = serializers.CharField()
    listen_count = serializers.IntegerField()


class ListenBrainzUserRecordingsPayloadSerializer(
    ListenBrainzStatsPayloadSerializer,
):
    """Page of a user's top recordings."""

    recordings = ListenBrainzUserRecordingSerializer(many=True)
    total_recording_count = serializers.IntegerField()


class ListenBrainzUserRecordingsSerializer(serializers.Serializer):
    """ListenBrainz `stats/user/recordings` response wrapper."""

    payload = ListenBrainzUserRecordingsPayloadSerializer()


class ListenBrainzGenreActivityEntrySerializer(serializers.Serializer):
    """Plays of one genre in one hour of the day."""

    genre = serializers.CharField()
    hour = serializers.IntegerField(min_value=0, max_value=23)
    listen_count = serializers.IntegerField()


class ListenBrainzGenreActivitySerializer(serializers.Serializer):
    """ListenBrainz `stats/user/genre-activity` response."""

    result = ListenBrainzGenreActivityEntrySerializer(many=True)


class RecommendationSerializer(serializers.Serializer):
    """One recommended title for an external client."""

    media_type = serializers.CharField()
    source = serializers.CharField(help_text="Provider the media_id belongs to.")
    media_id = serializers.CharField()
    title = serializers.CharField()
    release_date = serializers.CharField(allow_null=True)
    genres = serializers.ListField(child=serializers.CharField())
    rating = serializers.FloatField(allow_null=True)
    image = serializers.CharField(allow_null=True)
    ids = serializers.DictField(
        child=serializers.CharField(),
        help_text=(
            "Provider ids as strings, using the keys `tmdb`, `imdb` and `tvdb`. "
            "A key is absent when Floppy could not resolve that id."
        ),
    )


class RecommendationsEnvelopeSerializer(serializers.Serializer):
    """Paginated recommendations."""

    pagination = PaginationSerializer()
    results = RecommendationSerializer(many=True)
