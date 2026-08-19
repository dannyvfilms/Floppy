import contextlib

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

from app.models import (
    DeletedMedia,
    Episode,
    Item,
    ItemProviderLink,
    MetadataProviderPreference,
    MoviePlay,
    PlaybackProgress,
)


# Custom ModelAdmin classes with search functionality
@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Custom admin for Item model with search and filter options."""

    search_fields = ["title", "media_id", "source"]
    list_display = [
        "title",
        "media_id",
        "season_number",
        "episode_number",
        "media_type",
        "source",
    ]
    list_filter = ["media_type", "source"]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    """Custom admin for Episode model with search and filter options."""

    search_fields = ["item__title", "related_season__item__title"]
    list_display = ["__str__", "end_date"]


@admin.register(MoviePlay)
class MoviePlayAdmin(admin.ModelAdmin):
    """Custom admin for MoviePlay model with search and filter options."""

    search_fields = ["movie__item__title"]
    list_display = ["__str__", "end_date", "external_id"]


class MediaAdmin(admin.ModelAdmin):
    """Custom admin for regular media model with search and filter options."""

    search_fields = ["item__title", "user__username", "notes"]
    list_display = ["__str__", "status", "score", "user"]
    list_filter = ["status"]


# Register models with custom admin classes


class ArtistAdmin(admin.ModelAdmin):
    """Custom admin for Artist model."""

    search_fields = ["name", "musicbrainz_id"]
    list_display = ["name", "sort_name", "musicbrainz_id"]


class AlbumAdmin(admin.ModelAdmin):
    """Custom admin for Album model."""

    search_fields = ["title", "musicbrainz_release_id", "artist__name"]
    list_display = ["title", "artist", "release_date", "tracks_populated"]
    list_filter = ["release_date", "tracks_populated"]


class TrackAdmin(admin.ModelAdmin):
    """Custom admin for Track model."""

    search_fields = ["title", "musicbrainz_recording_id", "album__title"]
    list_display = [
        "title",
        "album",
        "track_number",
        "disc_number",
        "duration_formatted",
    ]
    list_filter = ["album"]


# Auto-register remaining models
app_models = apps.get_app_config("app").get_models()
# Models that don't use MediaAdmin (either registered separately or excluded)
SpecialModels = [
    "Item",
    "Episode",
    "MoviePlay",
    "BasicMedia",
    "Artist",
    "Album",
    "AlbumArtist",
    "ArtistMember",
    "Track",
    "ArtistTracker",
    "AlbumTracker",
    "PodcastShow",
    "PodcastEpisode",
    "Person",
    "Studio",
    "ItemPersonCredit",
    "ItemStudioCredit",
    "MetadataBackfillState",
    "BackfillReconcileState",
    "ItemProviderLink",
    "MetadataProviderPreference",
    "HardcoverEditionPreference",
    "CollectionEntry",
    "Tag",
    "ItemTag",
    "DiscoverFeedback",
    "DiscoverApiCache",
    "DiscoverTasteProfile",
    "DiscoverRowCache",
    "DeletedMedia",
    "PlaybackProgress",
]
for model in app_models:
    if (
        not model.__name__.startswith("Historical")
        and model.__name__ not in SpecialModels
    ):
        with contextlib.suppress(AlreadyRegistered):
            admin.site.register(model, MediaAdmin)


# Register Artist, Album, Track, ArtistTracker, and AlbumTracker with custom admin classes
from app.models import (  # noqa: E402
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    BackfillReconcileState,
    MetadataBackfillState,
    Track,
)


class ArtistTrackerAdmin(admin.ModelAdmin):
    """Admin for ArtistTracker."""

    list_display = ["user", "artist", "status", "score", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "artist__name"]
    raw_id_fields = ["user", "artist"]


class AlbumTrackerAdmin(admin.ModelAdmin):
    """Admin for AlbumTracker."""

    list_display = ["user", "album", "status", "score", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["user__username", "album__title", "album__artist__name"]
    raw_id_fields = ["user", "album"]


admin.site.register(Artist, ArtistAdmin)
admin.site.register(Album, AlbumAdmin)
admin.site.register(Track, TrackAdmin)
admin.site.register(ArtistTracker, ArtistTrackerAdmin)
admin.site.register(AlbumTracker, AlbumTrackerAdmin)


class MetadataBackfillStateAdmin(admin.ModelAdmin):
    """Admin for metadata backfill tracking."""

    list_display = [
        "item",
        "field",
        "fail_count",
        "give_up",
        "next_retry_at",
        "last_attempt_at",
        "last_success_at",
    ]
    list_filter = ["field", "give_up"]
    search_fields = ["item__title", "item__media_id", "last_error"]
    raw_id_fields = ["item"]


admin.site.register(MetadataBackfillState, MetadataBackfillStateAdmin)


class BackfillReconcileStateAdmin(admin.ModelAdmin):
    """Admin for whole-library reconcile sweep progress."""

    list_display = [
        "key",
        "strategy_version",
        "completed_at",
        "last_run_at",
        "next_run_after",
        "consecutive_no_op_runs",
        "last_cursor_item_id",
    ]
    list_filter = ["key"]
    search_fields = ["key"]


admin.site.register(BackfillReconcileState, BackfillReconcileStateAdmin)


class ItemProviderLinkAdmin(admin.ModelAdmin):
    """Admin for provider-link mappings."""

    list_display = [
        "item",
        "provider",
        "provider_media_type",
        "provider_media_id",
        "season_number",
        "episode_offset",
        "updated_at",
    ]
    list_filter = ["provider", "provider_media_type"]
    search_fields = ["item__title", "item__media_id", "provider_media_id"]
    raw_id_fields = ["item"]


class MetadataProviderPreferenceAdmin(admin.ModelAdmin):
    """Admin for per-user metadata provider preferences."""

    list_display = ["user", "item", "provider", "updated_at"]
    list_filter = ["provider"]
    search_fields = ["user__username", "item__title", "item__media_id"]
    raw_id_fields = ["user", "item"]


admin.site.register(ItemProviderLink, ItemProviderLinkAdmin)
admin.site.register(
    MetadataProviderPreference,
    MetadataProviderPreferenceAdmin,
)


class PodcastShowAdmin(admin.ModelAdmin):
    """Custom admin for PodcastShow model."""

    search_fields = ["title", "podcast_uuid", "author"]
    list_display = ["title", "author", "podcast_uuid"]
    list_filter = ["language"]


class PodcastEpisodeAdmin(admin.ModelAdmin):
    """Custom admin for PodcastEpisode model."""

    search_fields = ["title", "episode_uuid", "show__title"]
    list_display = ["title", "show", "published", "duration_formatted", "is_deleted"]
    list_filter = ["is_deleted", "episode_type", "show"]
    raw_id_fields = ["show"]


# Register PodcastShow and PodcastEpisode with custom admin classes
from app.models import PodcastEpisode, PodcastShow  # noqa: E402

admin.site.register(PodcastShow, PodcastShowAdmin)
admin.site.register(PodcastEpisode, PodcastEpisodeAdmin)


class CollectionEntryAdmin(admin.ModelAdmin):
    """Admin for CollectionEntry model."""

    list_display = [
        "user",
        "item",
        "collected_at",
        "media_type",
        "resolution",
        "audio_codec",
        "bitrate",
        "purchase_price",
        "purchase_location",
    ]
    list_filter = ["media_type", "resolution", "hdr", "is_3d", "collected_at"]
    search_fields = ["user__username", "item__title", "purchase_location"]
    readonly_fields = ["collected_at", "updated_at"]
    raw_id_fields = ["user", "item"]


# Register CollectionEntry with custom admin class
from app.models import CollectionEntry  # noqa: E402

admin.site.register(CollectionEntry, CollectionEntryAdmin)


class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    search_fields = ["name", "user__username"]
    list_display = ["name", "user", "created_at"]
    list_filter = ["user"]
    raw_id_fields = ["user"]


class ItemTagAdmin(admin.ModelAdmin):
    """Admin for ItemTag model."""

    search_fields = ["tag__name", "item__title"]
    list_display = ["tag", "item", "created_at"]
    raw_id_fields = ["tag", "item"]


from app.models import ItemTag, Tag  # noqa: E402

admin.site.register(Tag, TagAdmin)
admin.site.register(ItemTag, ItemTagAdmin)


class DiscoverApiCacheAdmin(admin.ModelAdmin):
    """Admin for DiscoverApiCache model."""

    list_display = ["provider", "endpoint", "fetched_at", "expires_at"]
    list_filter = ["provider", "expires_at"]
    search_fields = ["provider", "endpoint", "params_hash"]


class DiscoverTasteProfileAdmin(admin.ModelAdmin):
    """Admin for DiscoverTasteProfile model."""

    list_display = ["user", "media_type", "computed_at", "expires_at"]
    list_filter = ["media_type", "expires_at"]
    search_fields = ["user__username", "media_type"]
    raw_id_fields = ["user"]


class DiscoverFeedbackAdmin(admin.ModelAdmin):
    """Admin for DiscoverFeedback model."""

    list_display = ["user", "item", "feedback_type", "source_context", "updated_at"]
    list_filter = ["feedback_type", "source_context", "updated_at"]
    search_fields = ["user__username", "item__title", "item__media_id"]
    raw_id_fields = ["user", "item"]


class DiscoverRowCacheAdmin(admin.ModelAdmin):
    """Admin for DiscoverRowCache model."""

    list_display = ["user", "media_type", "row_key", "built_at", "expires_at"]
    list_filter = ["media_type", "row_key", "expires_at"]
    search_fields = ["user__username", "media_type", "row_key"]
    raw_id_fields = ["user"]


from app.models import (  # noqa: E402
    DiscoverApiCache,
    DiscoverFeedback,
    DiscoverRowCache,
    DiscoverTasteProfile,
)


class DeletedMediaAdmin(admin.ModelAdmin):
    """Admin for DeletedMedia tombstones."""

    list_display = ["user", "media_type", "source", "media_id", "deleted_at"]
    list_filter = ["media_type", "source", "deleted_at"]
    search_fields = ["user__username", "media_id"]
    raw_id_fields = ["user"]


class PlaybackProgressAdmin(admin.ModelAdmin):
    """Admin for durable resume positions."""

    list_display = ["user", "item", "position_seconds", "completed", "updated_at"]
    list_filter = ["completed", "updated_at"]
    search_fields = ["user__username", "item__title"]
    raw_id_fields = ["user", "item"]


admin.site.register(DeletedMedia, DeletedMediaAdmin)
admin.site.register(PlaybackProgress, PlaybackProgressAdmin)
admin.site.register(DiscoverFeedback, DiscoverFeedbackAdmin)
admin.site.register(DiscoverApiCache, DiscoverApiCacheAdmin)
admin.site.register(DiscoverTasteProfile, DiscoverTasteProfileAdmin)
admin.site.register(DiscoverRowCache, DiscoverRowCacheAdmin)
