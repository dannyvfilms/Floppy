"""Models for integration data."""

import hashlib
import secrets

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


class LastFMHistoryImportStatus(models.TextChoices):
    """History import states for Last.fm backfills."""

    IDLE = "idle", "Idle"
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    FAILED = "failed", "Failed"
    COMPLETED = "completed", "Completed"


class PlexAccount(models.Model):
    """Store Plex authentication and cached library data for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plex_account",
    )
    plex_token = models.CharField(max_length=255)
    plex_username = models.CharField(max_length=255)
    plex_account_id = models.CharField(max_length=255, blank=True, null=True)
    server_name = models.CharField(max_length=255, blank=True, null=True)
    machine_identifier = models.CharField(max_length=255, blank=True, null=True)
    sections = models.JSONField(default=list, blank=True)
    sections_refreshed_at = models.DateTimeField(blank=True, null=True)
    watchlist_sync_enabled = models.BooleanField(
        default=False,
        help_text="Whether recurring Plex watchlist sync is enabled",
    )
    watchlist_last_synced_at = models.DateTimeField(blank=True, null=True)
    watchlist_last_error = models.TextField(
        blank=True,
        default="",
        help_text="Last Plex watchlist sync error",
    )
    watchlist_last_error_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Plex account"
        verbose_name_plural = "Plex accounts"

    def __str__(self):
        """Readable representation."""
        return f"PlexAccount({self.plex_username})"

    @property
    def is_connected(self):
        """Return True when we have a token stored."""
        return bool(self.plex_token)


class PlexWebhookShare(models.Model):
    """Share one user's Plex webhook with another Floppy user."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plex_webhook_shares",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_plex_webhook_shares",
    )
    plex_username = models.CharField(max_length=255)
    allowed_libraries = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Plex library keys accepted for this share; null means all libraries.",
    )
    recipient_enabled = models.BooleanField(
        default=False,
        help_text="Whether the recipient has opted into this shared webhook.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Plex webhook share"
        verbose_name_plural = "Plex webhook shares"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "recipient"],
                name="integrations_plexwebhookshare_unique_owner_recipient",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner", "recipient_enabled"],
                name="plexshare_owner_enabled_idx",
            ),
        ]

    def __str__(self):
        """Return a readable representation."""
        return f"PlexWebhookShare({self.owner.username} -> {self.recipient.username})"

    @property
    def all_libraries(self):
        """Return whether this share accepts every Plex library."""
        return self.allowed_libraries is None


class PlexWatchlistSyncItem(models.Model):
    """Persist the last-known Plex watchlist state for a user/item pair."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="plex_watchlist_sync_items",
    )
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="plex_watchlist_sync_items",
    )
    source_username = models.CharField(max_length=255, blank=True, default="")
    source_account_id = models.CharField(max_length=255, blank=True, default="")
    plex_rating_key = models.CharField(max_length=50, blank=True, default="")
    plex_guid = models.CharField(max_length=255, blank=True, default="")
    tmdb_id = models.CharField(max_length=32, blank=True, default="")
    tvdb_id = models.CharField(max_length=32, blank=True, default="")
    imdb_id = models.CharField(max_length=32, blank=True, default="")
    created_by_sync = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    removed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        """Model options."""

        verbose_name = "Plex watchlist sync item"
        verbose_name_plural = "Plex watchlist sync items"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "source_username"],
                name="integrations_plexwatchlistsyncitem_unique_user_item_source",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "source_username"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"PlexWatchlistSyncItem({self.user.username}, {self.item_id})"


class PocketCastsAccount(models.Model):
    """Store Pocket Casts authentication tokens for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pocketcasts_account",
    )
    access_token = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted JWT access token (cached from login)",
    )
    refresh_token = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted refresh token (cached from login)",
    )
    email = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted email address for login",
    )
    password = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted password for login",
    )
    token_expires_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(
        default=False,
        help_text="True if connection is broken (refresh failed) but credentials are preserved",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Pocket Casts account"
        verbose_name_plural = "Pocket Casts accounts"

    def __str__(self):
        """Readable representation."""
        return f"PocketCastsAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when we have a valid connection.

        A connection is valid if:
        - We have email AND password (can always re-login), OR
        - We have an access token (and it's not expired, or we have refresh token to renew it)
        - Connection is not marked as broken
        """
        # If we have credentials (email and password), we can always reconnect
        has_credentials = bool(self.email and self.password)

        # If connection is marked as broken and we don't have credentials, not connected
        if self.connection_broken and not has_credentials:
            return False

        # If we have credentials, we're connected (can always re-login)
        if has_credentials:
            return True

        # Legacy: check for access token
        if not self.access_token:
            return False

        # If connection is marked as broken, not connected
        if self.connection_broken:
            return False

        # If token is not expired, we're connected
        if not self.is_token_expired:
            return True

        # An expired token is still usable while a refresh token exists.
        return bool(self.refresh_token)

    @property
    def is_token_expired(self):
        """Return True if the token is expired."""
        if not self.token_expires_at:
            return False
        return timezone.now() >= self.token_expires_at


class GPodderAccount(models.Model):
    """Store GPodder connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gpodder_account",
    )
    server_url = models.TextField(
        help_text="Encrypted GPodder-compatible server URL",
    )
    username = models.TextField(
        help_text="Encrypted username for HTTP Basic authentication",
    )
    password = models.TextField(
        help_text="Encrypted password or app password for HTTP Basic authentication",
    )
    device_id = models.CharField(
        max_length=255,
        help_text="Floppy-managed GPodder device identifier",
    )
    device_filter = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional upstream device filter for imported actions",
    )
    episode_actions_since = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Last successfully imported GPodder episode actions cursor",
    )
    subscription_since = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Reserved for future incremental subscription sync",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "GPodder account"
        verbose_name_plural = "GPodder accounts"

    def __str__(self):
        """Readable representation."""
        return f"GPodderAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return (
            bool(self.server_url and self.username and self.password)
            and not self.connection_broken
        )


class AudiobookshelfAccount(models.Model):
    """Store Audiobookshelf connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="audiobookshelf_account",
    )
    base_url = models.URLField(help_text="Audiobookshelf server URL")
    api_token = models.TextField(help_text="Encrypted Audiobookshelf API token")
    sync_finished = models.BooleanField(
        default=True,
        help_text="Import finished items as completed entries",
    )
    create_missing = models.BooleanField(
        default=True,
        help_text="Create Floppy items when ABS items cannot be matched",
    )
    last_sync_ms = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Last imported Audiobookshelf progress timestamp (milliseconds)",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Audiobookshelf account"
        verbose_name_plural = "Audiobookshelf accounts"

    def __str__(self):
        """Readable representation."""
        return f"AudiobookshelfAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.base_url and self.api_token) and not self.connection_broken


class LastFMAccount(models.Model):
    """Store Last.fm username and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lastfm_account",
    )
    lastfm_username = models.CharField(max_length=255)
    last_fetch_timestamp_uts = models.IntegerField(
        null=True,
        blank=True,
        help_text="Unix timestamp (seconds) of last successful poll",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(
        default=False,
        help_text="True if connection is broken (invalid username or persistent errors)",
    )
    failure_count = models.IntegerField(
        default=0,
        help_text="Number of consecutive failures",
    )
    last_error_code = models.CharField(
        max_length=10,
        blank=True,
        help_text="Last.fm API error code (e.g., '29' for rate limit)",
    )
    last_error_message = models.TextField(
        blank=True,
        help_text="Human-readable error message",
    )
    last_failed_at = models.DateTimeField(null=True, blank=True)
    history_import_status = models.CharField(
        max_length=20,
        choices=LastFMHistoryImportStatus.choices,
        default=LastFMHistoryImportStatus.IDLE,
        help_text="Current Last.fm history import state",
    )
    history_import_cutoff_uts = models.IntegerField(
        null=True,
        blank=True,
        help_text="Upper timestamp bound for the current history import",
    )
    history_import_next_page = models.PositiveIntegerField(
        default=1,
        help_text="Next Last.fm history page to import",
    )
    history_import_total_pages = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total page count reported by Last.fm for the current history import",
    )
    history_import_started_at = models.DateTimeField(null=True, blank=True)
    history_import_completed_at = models.DateTimeField(null=True, blank=True)
    history_import_last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Last.fm account"
        verbose_name_plural = "Last.fm accounts"

    def __str__(self):
        """Readable representation."""
        return f"LastFMAccount({self.lastfm_username})"

    @property
    def is_connected(self):
        """Return True when we have a valid connection."""
        return bool(self.lastfm_username) and not self.connection_broken

    @property
    def history_import_is_active(self):
        """Return True when a history backfill is queued or running."""
        return self.history_import_status in {
            LastFMHistoryImportStatus.QUEUED,
            LastFMHistoryImportStatus.RUNNING,
        }

    @property
    def history_import_can_start(self):
        """Return True when the user can start or rerun a history backfill."""
        return self.history_import_status in {
            LastFMHistoryImportStatus.IDLE,
            LastFMHistoryImportStatus.FAILED,
            LastFMHistoryImportStatus.COMPLETED,
        }

    def reset_history_import(self, cutoff_uts: int):
        """Prepare state for a fresh history backfill."""
        self.history_import_status = LastFMHistoryImportStatus.QUEUED
        self.history_import_cutoff_uts = cutoff_uts
        self.history_import_next_page = 1
        self.history_import_total_pages = None
        self.history_import_started_at = None
        self.history_import_completed_at = None
        self.history_import_last_error_message = ""


class KoitoAccount(models.Model):
    """Store Koito connection settings and sync state for a user.

    Receive-only: Floppy polls Koito for listens and never submits back to it.
    Reuses LastFMHistoryImportStatus for the backfill state machine since the
    states are identical.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="koito_account",
    )
    base_url = models.URLField(help_text="Koito server URL")
    api_key = models.TextField(help_text="Encrypted Koito API key")
    last_fetch_timestamp_uts = models.IntegerField(
        null=True,
        blank=True,
        help_text="Unix timestamp (seconds) of last successful poll",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(
        default=False,
        help_text="True if connection is broken (invalid key or persistent errors)",
    )
    failure_count = models.IntegerField(
        default=0,
        help_text="Number of consecutive failures",
    )
    last_error_message = models.TextField(blank=True, default="")
    last_failed_at = models.DateTimeField(null=True, blank=True)
    history_import_status = models.CharField(
        max_length=20,
        choices=LastFMHistoryImportStatus.choices,
        default=LastFMHistoryImportStatus.IDLE,
        help_text="Current Koito history import state",
    )
    history_import_started_at = models.DateTimeField(null=True, blank=True)
    history_import_completed_at = models.DateTimeField(null=True, blank=True)
    history_import_last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Koito account"
        verbose_name_plural = "Koito accounts"

    def __str__(self):
        """Readable representation."""
        return f"KoitoAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.base_url and self.api_key) and not self.connection_broken

    @property
    def history_import_is_active(self):
        """Return True when a history backfill is queued or running."""
        return self.history_import_status in {
            LastFMHistoryImportStatus.QUEUED,
            LastFMHistoryImportStatus.RUNNING,
        }

    @property
    def history_import_can_start(self):
        """Return True when the user can start or rerun a history backfill."""
        return self.history_import_status in {
            LastFMHistoryImportStatus.IDLE,
            LastFMHistoryImportStatus.FAILED,
            LastFMHistoryImportStatus.COMPLETED,
        }

    def reset_history_import(self):
        """Prepare state for a fresh history backfill."""
        self.history_import_status = LastFMHistoryImportStatus.QUEUED
        self.history_import_started_at = None
        self.history_import_completed_at = None
        self.history_import_last_error_message = ""


class RadarrAccount(models.Model):
    """Store Radarr connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="radarr_account",
    )
    base_url = models.URLField(help_text="Radarr server URL")
    api_key = models.TextField(help_text="Encrypted Radarr API key")
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Radarr account"
        verbose_name_plural = "Radarr accounts"

    @property
    def __str__(self):
        """Return a readable label for this radarr account."""
        return f"{self.user}"

    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.base_url and self.api_key) and not self.connection_broken


class SonarrAccount(models.Model):
    """Store Sonarr connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sonarr_account",
    )
    base_url = models.URLField(help_text="Sonarr server URL")
    api_key = models.TextField(help_text="Encrypted Sonarr API key")
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Sonarr account"
        verbose_name_plural = "Sonarr accounts"

    @property
    def __str__(self):
        """Return a readable label for this sonarr account."""
        return f"{self.user}"

    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.base_url and self.api_key) and not self.connection_broken


class MDBListAccount(models.Model):
    """Store MDBList connection settings and sync state for a user."""

    SYNC_FREQUENCY_CHOICES = [
        ("6h", "Every 6 hours"),
        ("12h", "Every 12 hours"),
        ("24h", "Every 24 hours"),
        ("weekly", "Weekly"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mdblist_account",
    )
    api_key = models.TextField(help_text="Encrypted MDBList API key")
    sync_frequency = models.CharField(
        max_length=10,
        choices=SYNC_FREQUENCY_CHOICES,
        default="24h",
    )
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "MDBList account"
        verbose_name_plural = "MDBList accounts"

    @property
    def __str__(self):
        """Return a readable label for this m d b list account."""
        return f"{self.user}"

    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.api_key) and not self.connection_broken


class JellyfinAccount(models.Model):
    """Store Jellyfin connection settings and push-sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jellyfin_account",
    )
    base_url = models.URLField(help_text="Jellyfin server URL")
    api_key = models.TextField(help_text="Encrypted Jellyfin API key")
    jellyfin_user_id = models.CharField(max_length=255, blank=True, default="")
    jellyfin_username = models.CharField(max_length=255, blank=True, default="")
    push_watched_enabled = models.BooleanField(
        default=True,
        help_text="Push Floppy 'watched' status to Jellyfin",
    )
    push_unwatched_enabled = models.BooleanField(
        default=False,
        help_text="Push Floppy 'unwatched' status to Jellyfin",
    )
    scheduled_push_enabled = models.BooleanField(
        default=False,
        help_text="Push watched state to Jellyfin on a recurring schedule",
    )
    instant_push_enabled = models.BooleanField(
        default=False,
        help_text="Push watched state to Jellyfin right after a webhook event",
    )
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Jellyfin account"
        verbose_name_plural = "Jellyfin accounts"

    def __str__(self):
        """Readable representation."""
        return f"JellyfinAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.base_url and self.api_key) and not self.connection_broken


class CollectionSourceState(models.Model):
    """Track source-specific collection metadata freshness for each user+item."""

    SOURCE_CHOICES = [
        ("plex", "Plex"),
        ("radarr", "Radarr"),
        ("sonarr", "Sonarr"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="collection_source_states",
    )
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="source_states",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    quality_label = models.CharField(max_length=80, blank=True, default="")
    last_source_updated_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "source"],
                name="integrations_collectionsourcestate_unique_user_item_source",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "source"]),
            models.Index(fields=["user", "item"]),
        ]

    def __str__(self):
        """Return a readable label for this collection source state."""
        return f"{self.user}"


class StorytellerAccount(models.Model):
    """Store Storyteller connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="storyteller_account",
    )
    server_url = models.URLField(help_text="Storyteller server URL")
    auth_token = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted Storyteller access token",
    )
    finished_threshold = models.FloatField(
        default=0.95,
        help_text="Reading progress fraction (0-1) at which a book is marked read",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Storyteller account"
        verbose_name_plural = "Storyteller accounts"

    def __str__(self):
        """Readable representation."""
        return f"StorytellerAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.server_url and self.auth_token) and not self.connection_broken


class StremioAccount(models.Model):
    """Store Stremio API credentials and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stremio_account",
    )
    auth_key = models.TextField(help_text="Encrypted Stremio auth key")
    email = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted Stremio account email (display only)",
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Stremio account"
        verbose_name_plural = "Stremio accounts"

    def __str__(self):
        """Readable representation."""
        return f"StremioAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.auth_key) and not self.connection_broken


class XboxAccount(models.Model):
    """Store OpenXBL credentials and sync state for a user's Xbox account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="xbox_account",
    )
    api_key = models.TextField(help_text="Encrypted OpenXBL API key")
    xuid = models.CharField(max_length=32, blank=True, default="")
    gamertag = models.CharField(max_length=64, blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Xbox account"
        verbose_name_plural = "Xbox accounts"

    def __str__(self):
        """Readable representation."""
        return f"XboxAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.api_key) and not self.connection_broken


class PSNAccount(models.Model):
    """Store PSN credentials and sync state for a user's PlayStation account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="psn_account",
    )
    npsso = models.TextField(help_text="Encrypted PSN NPSSO token")
    account_id = models.CharField(max_length=32, blank=True, default="")
    online_id = models.CharField(max_length=64, blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "PlayStation Network account"
        verbose_name_plural = "PlayStation Network accounts"

    def __str__(self):
        """Readable representation."""
        return f"PSNAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return bool(self.npsso) and not self.connection_broken


class TraktAccount(models.Model):
    """Store Trakt API client credentials for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trakt_account",
    )
    client_id = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted Trakt client ID",
    )
    client_secret = models.TextField(
        blank=True,
        null=True,
        help_text="Encrypted Trakt client secret",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Trakt account"
        verbose_name_plural = "Trakt accounts"

    def __str__(self):
        """Readable representation."""
        return f"TraktAccount({self.user.username})"

    @property
    def is_configured(self):
        """Return True when client credentials are stored."""
        return bool(self.client_id and self.client_secret)


class ImportRun(models.Model):
    """Track a single import run's provenance and progress.

    `source` identifies the importer (e.g. "trakt", "lastfm", "koito") and
    is intentionally separate from `app.models.choices.Sources`, which
    tags metadata *provider* (e.g. "tmdb") and can't distinguish which
    importer created a row.
    """

    class Status(models.TextChoices):
        """Lifecycle states for an import run."""

        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="import_runs",
    )
    source = models.CharField(max_length=32)
    task_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.RUNNING,
    )
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    remaining_estimate = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        """Model options."""

        verbose_name = "import run"
        verbose_name_plural = "import runs"
        indexes = [
            models.Index(fields=["user", "-started_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"ImportRun({self.source}, {self.user.username}, {self.status})"


DEFAULT_INTEGRATION_SCOPES = [
    "scrobble:write",
    "progress:read",
    "progress:write",
    "watchlist:read",
    "watchlist:write",
    "catalog:read",
]


class IntegrationToken(models.Model):
    """Scoped, high-entropy API credential for third-party client integrations."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="integration_tokens",
    )
    name = models.CharField(max_length=255)
    client_identifier = models.CharField(max_length=255, blank=True, default="")
    token_digest = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(max_length=16, blank=True, default="")
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "Integration token"
        verbose_name_plural = "Integration tokens"
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"IntegrationToken({self.name}, {self.user.username})"

    @classmethod
    def generate(
        cls,
        user,
        name: str,
        scopes: list[str] | None = None,
        client_identifier: str = "",
        expires_at: timezone.datetime | None = None,
    ) -> tuple["IntegrationToken", str]:
        """Generate a raw token string and persist its SHA-256 digest."""
        raw_token = f"flp_{secrets.token_urlsafe(32)}"
        token_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_prefix = raw_token[:12]
        if scopes is None:
            scopes = list(DEFAULT_INTEGRATION_SCOPES)
        instance = cls.objects.create(
            user=user,
            name=name,
            client_identifier=client_identifier,
            token_digest=token_digest,
            token_prefix=token_prefix,
            scopes=scopes,
            expires_at=expires_at,
        )
        return instance, raw_token

    def is_valid(self) -> bool:
        """Return True if the token is not revoked and not expired."""
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > timezone.now()
        )

    def has_scope(self, scope: str) -> bool:
        """Return True if '*' is in scopes or the specific scope is in scopes."""
        scopes = self.scopes or []
        return "*" in scopes or scope in scopes


class IntegrationEventReceipt(models.Model):
    """Store client event receipts for idempotency and deduplication."""

    token = models.ForeignKey(
        IntegrationToken,
        on_delete=models.CASCADE,
        related_name="event_receipts",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="event_receipts",
    )
    client_event_id = models.CharField(max_length=255, db_index=True)
    payload_digest = models.CharField(max_length=64)
    response_status_code = models.IntegerField(default=200)
    response_body = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        """Model options."""

        verbose_name = "Integration event receipt"
        verbose_name_plural = "Integration event receipts"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "client_event_id"],
                name="unique_user_client_event_id",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"IntegrationEventReceipt({self.user.username}, {self.client_event_id})"


