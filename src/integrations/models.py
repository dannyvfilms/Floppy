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
    section_settings = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Per-library import settings keyed by '<machine_identifier>::"
            "<section_id>', e.g. {'abc::3': {'content_kind': 'audiobook'}}"
        ),
    )
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

    @staticmethod
    def library_key(machine_identifier, section_id):
        """Return the '<machine>::<section>' key used to address a library.

        Matches the value the import form posts as `library` and the key the
        Plex webhook builds from Server.uuid + Metadata.librarySectionID.
        """
        if not machine_identifier or section_id in (None, ""):
            return None
        return f"{machine_identifier}::{section_id}"

    def content_kind(self, machine_identifier, section_id):
        """Return how a library should be imported: auto, music or audiobook."""
        from integrations.imports.plex_audiobooks import (
            CONTENT_KIND_AUTO,
            CONTENT_KINDS,
        )

        key = self.library_key(machine_identifier, section_id)
        settings_map = self.section_settings or {}
        kind = (settings_map.get(key) or {}).get("content_kind")
        return kind if kind in CONTENT_KINDS else CONTENT_KIND_AUTO

    def set_content_kind(self, machine_identifier, section_id, kind):
        """Persist how a library should be imported. Returns True when changed."""
        from integrations.imports.plex_audiobooks import CONTENT_KINDS

        key = self.library_key(machine_identifier, section_id)
        if not key or kind not in CONTENT_KINDS:
            return False
        settings_map = dict(self.section_settings or {})
        entry = dict(settings_map.get(key) or {})
        if entry.get("content_kind") == kind:
            return False
        entry["content_kind"] = kind
        settings_map[key] = entry
        self.section_settings = settings_map
        return True


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
    source_server_id = models.CharField(max_length=255, blank=True, default="")
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
                fields=["user", "item", "source_username", "source_server_id"],
                name="integrations_plexwatchlistsyncitem_unique_user_item_server",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "source_username"]),
            models.Index(fields=["user", "source_server_id"]),
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
    last_full_resync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time a full (non-incremental) GPodder history resync ran",
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
    abs_user_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Audiobookshelf user id, used to scope a sync binding.",
    )
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


class RadarrInstance(models.Model):
    """Store connection settings and sync state for one Radarr instance.

    A user may connect more than one Radarr server (e.g. a 4K instance and
    an anime instance), so this is a ForeignKey rather than a OneToOne like
    the other single-account integrations in this file.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="radarr_instances",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional label to distinguish multiple instances, e.g. '4K' or 'Anime'",
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

        verbose_name = "Radarr instance"
        verbose_name_plural = "Radarr instances"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "base_url"],
                name="integrations_radarrinstance_unique_user_base_url",
            ),
        ]

    def __str__(self):
        """Return a readable label for this radarr instance."""
        return f"{self.display_name} ({self.user})"

    @property
    def display_name(self):
        """Return the instance's label, falling back to a generic name."""
        return self.name or "Radarr"

    def is_connected(self):
        """Return True when the instance appears connected."""
        return bool(self.base_url and self.api_key) and not self.connection_broken


class SonarrInstance(models.Model):
    """Store connection settings and sync state for one Sonarr instance.

    A user may connect more than one Sonarr server (e.g. a 4K instance and
    an anime instance), so this is a ForeignKey rather than a OneToOne like
    the other single-account integrations in this file.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sonarr_instances",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional label to distinguish multiple instances, e.g. '4K' or 'Anime'",
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

        verbose_name = "Sonarr instance"
        verbose_name_plural = "Sonarr instances"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "base_url"],
                name="integrations_sonarrinstance_unique_user_base_url",
            ),
        ]

    def __str__(self):
        """Return a readable label for this sonarr instance."""
        return f"{self.display_name} ({self.user})"

    @property
    def display_name(self):
        """Return the instance's label, falling back to a generic name."""
        return self.name or "Sonarr"

    def is_connected(self):
        """Return True when the instance appears connected."""
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
    server_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Jellyfin server GUID. Scopes a sync binding to one server, so "
            "pointing the same account at a different server stops rather than "
            "silently writing to it."
        ),
    )
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
    pull_history_enabled = models.BooleanField(
        default=True,
        help_text="Automatically pull Jellyfin watch history on a recurring schedule",
    )
    playback_reporting_available = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Whether the Playback Reporting plugin's API was reachable with "
            "this account's key. Unknown (null) until the first pull runs."
        ),
    )
    playback_reporting_last_rowid = models.BigIntegerField(null=True, blank=True)
    library_backfill_completed_at = models.DateTimeField(null=True, blank=True)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    last_pull_error_message = models.TextField(blank=True, default="")
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
        ("jellyfin", "Jellyfin"),
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
    source_instance_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "PK of the RadarrInstance/SonarrInstance this row came from; "
            "unused for plex/jellyfin"
        ),
    )
    quality_label = models.CharField(max_length=80, blank=True, default="")
    last_source_updated_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "source"],
                condition=models.Q(source_instance_id__isnull=True),
                name="integrations_collectionsourcestate_unique_user_item_source",
            ),
            models.UniqueConstraint(
                fields=["user", "item", "source", "source_instance_id"],
                condition=models.Q(source_instance_id__isnull=False),
                name="integrations_collectionsourcestate_unique_user_item_source_instance",
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


class KoreaderAccount(models.Model):
    """Store KOReader sync server connection settings and sync state for a user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="koreader_account",
    )
    server_url = models.URLField(help_text="KOReader sync server URL")
    username = models.CharField(max_length=150)
    auth_key = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted MD5 hash of the KOReader sync password",
    )
    verify_ssl = models.BooleanField(
        default=True,
        help_text="Verify TLS certificates when connecting to the sync server",
    )
    create_missing = models.BooleanField(
        default=False,
        help_text="Create Floppy book entries when KOReader documents match providers",
    )
    skip_finished_books = models.BooleanField(
        default=True,
        help_text="Skip progress fetches for books already marked completed in Floppy",
    )
    finished_threshold = models.FloatField(
        default=1.0,
        help_text="Reading progress fraction (0-1) at which a synced book is marked completed",
    )
    supports_document_list = models.BooleanField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "KOReader account"
        verbose_name_plural = "KOReader accounts"

    def __str__(self):
        """Readable representation."""
        return f"KoreaderAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return True when the account appears connected."""
        return (
            bool(self.server_url and self.username and self.auth_key)
            and not self.connection_broken
        )


class KoreaderDocumentLink(models.Model):
    """Map a KOReader document hash to a Floppy book item for a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="koreader_document_links",
    )
    document_hash = models.CharField(max_length=32, db_index=True)
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="koreader_document_links",
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model options."""

        verbose_name = "KOReader document link"
        verbose_name_plural = "KOReader document links"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document_hash"],
                name="integrations_koreaderdocumentlink_unique_user_hash",
            ),
            models.UniqueConstraint(
                fields=["user", "item"],
                name="integrations_koreaderdocumentlink_unique_user_item",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"KoreaderDocumentLink({self.user.username}, {self.document_hash[:8]}…)"


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


# What a tracking client needs and no more. Mirrored by api.scopes.TRACKING_PRESET,
# which a test holds equal to this list. sync:read is not optional for such a
# client: the change feed is how it learns what moved, so a token without it is
# a sync client that cannot sync. sync:write stays out — resolving a conflict is
# a deliberate human act, not routine client traffic.
DEFAULT_INTEGRATION_SCOPES = [
    "scrobble:write",
    "progress:read",
    "progress:write",
    "watchlist:read",
    "watchlist:write",
    "catalog:read",
    "sync:read",
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
    # Empty means every list the user owns, which is what lists:write meant
    # before this existed. A populated list is an allowlist of CustomList ids,
    # so a token can be given one shared list without the rest of the library.
    writable_list_ids = models.JSONField(default=list, blank=True)
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
        return self.revoked_at is None and not self.is_expired()

    def is_expired(self) -> bool:
        """Return True if the token has passed its expiry."""
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def may_write_list(self, list_id) -> bool:
        """Return whether this token may write one list.

        An empty allowlist keeps the previous behaviour. A populated one is
        exact: a token bound to one list must not reach another by id.
        """
        allowed = self.writable_list_ids or []
        if not allowed:
            return True
        return list_id in allowed or str(list_id) in [str(x) for x in allowed]

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
    # Receipts scope to the binding when there is one. Two devices on the same
    # account routinely mint the same client event id ("1", a per-install
    # counter), and a user-wide constraint turns the second device's first
    # event into a bogus idempotency conflict.
    binding = models.ForeignKey(
        "SyncBinding",
        on_delete=models.CASCADE,
        related_name="event_receipts",
        null=True,
        blank=True,
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
            # Conditional pair rather than one constraint over both columns:
            # NULL never equals NULL, so a plain unique(binding, event_id) would
            # stop deduplicating entirely for unbound credentials.
            models.UniqueConstraint(
                fields=["user", "client_event_id"],
                condition=models.Q(binding__isnull=True),
                name="unique_unbound_user_client_event_id",
            ),
            models.UniqueConstraint(
                fields=["binding", "client_event_id"],
                condition=models.Q(binding__isnull=False),
                name="unique_binding_client_event_id",
            ),
        ]
        indexes = [
            # Drives retention compaction.
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"IntegrationEventReceipt({self.user.username}, {self.client_event_id})"




class CatalogGrant(models.Model):
    """A revocable, per-resource grant for published read-only catalogs.

    The Stremio add-on install URL carries its credential in the path, which
    means it lands in server logs, browser history and any screenshot of the
    settings page. Before this that credential was the account token: full
    API access, and revoking it broke every webhook and integration at once.

    A grant reads the selected catalogs and nothing else, and revoking one
    affects only the install it was minted for.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="catalog_grants",
    )
    name = models.CharField(max_length=255)
    # Stored in the clear, unlike IntegrationToken: Stremio replays the install
    # URL on every request, so there is nothing to compare a digest against
    # without indexing the digest anyway. Entropy is the control here, plus
    # the narrow read-only scope and independent revocation.
    token = models.CharField(max_length=64, unique=True, db_index=True)
    # Empty means every supported catalog. A populated list is an allowlist of
    # CatalogSpec.catalog_id values.
    catalog_ids = models.JSONField(default=list)
    # The add-on marks an item in progress when Stremio asks for subtitles.
    # On by default because that is what the install is for; still far narrower
    # than the account token, which reaches the whole API.
    allow_playback_start = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "Catalog grant"
        verbose_name_plural = "Catalog grants"
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"CatalogGrant({self.name}, {self.user.username})"

    @classmethod
    def generate(cls, user, name, catalog_ids=None, *, allow_playback_start=True):
        """Mint a grant and return it with its URL token."""
        token = f"cat_{secrets.token_urlsafe(24)}"
        instance = cls.objects.create(
            user=user,
            name=name,
            token=token,
            catalog_ids=list(catalog_ids or []),
            allow_playback_start=allow_playback_start,
        )
        return instance, token

    def is_valid(self) -> bool:
        """Return whether this grant may still serve a catalog."""
        return self.revoked_at is None

    def allows_catalog(self, catalog_id: str) -> bool:
        """Return whether this grant covers one catalog."""
        if not self.catalog_ids:
            return True
        return catalog_id in self.catalog_ids


class RemoteAddon(models.Model):
    """A declarative remote HTTP capability the user registered.

    Declarative means declarative: Floppy stores what the manifest said and
    fetches from the URL through the outbound boundary. No code from the remote
    host is ever executed, and an executable plugin is not a thing this can
    become. See docs/architecture/outbound-fetch.md.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="remote_addons",
    )
    # The configured URL can itself carry a secret, so it is masked in the UI
    # and never logged; only the reason code of a failure is.
    manifest_url = models.URLField(max_length=2048)
    addon_id = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")
    version = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")
    # The validated projection of the manifest, never the raw document.
    manifest = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    enabled = models.BooleanField(default=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=32, blank=True, default="")
    # A stable reason code, never a raw URL or response body.
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model options."""

        verbose_name = "Remote add-on"
        verbose_name_plural = "Remote add-ons"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "manifest_url"],
                name="unique_remote_addon_per_user",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"RemoteAddon({self.name or self.addon_id}, {self.user.username})"

    def masked_url(self) -> str:
        """Return the manifest URL with its path and query hidden.

        A configured URL frequently carries the credential in its path, which
        is exactly how the Stremio add-on protocol works.
        """
        from urllib.parse import urlparse

        try:
            parsed = urlparse(self.manifest_url)
        except ValueError:
            return "(invalid URL)"
        if not parsed.hostname:
            return "(invalid URL)"
        return f"{parsed.scheme}://{parsed.hostname}/…"


class SyncClientKind(models.TextChoices):
    """The kind of external system a binding points at."""

    PLEX = "plex", "Plex"
    JELLYFIN = "jellyfin", "Jellyfin"
    EMBY = "emby", "Emby"
    KODI = "kodi", "Kodi"
    STREMIO = "stremio", "Stremio"
    AUDIOBOOKSHELF = "audiobookshelf", "Audiobookshelf"
    GENERIC = "generic", "Generic client"


class SyncDirection(models.TextChoices):
    """Which way state is allowed to travel for one resource."""

    INBOUND = "inbound", "Provider to Floppy"
    OUTBOUND = "outbound", "Floppy to provider"


class SyncBindingStatus(models.TextChoices):
    """Whether a binding may move state."""

    PENDING = "pending", "Pending approval"
    ACTIVE = "active", "Active"
    NEEDS_REAPPROVAL = "needs_reapproval", "Needs reapproval"
    DISABLED = "disabled", "Disabled"


# Capability names. A direction ships enabled only where the adapter has been
# shown to hold the contract, so these are declared per binding rather than
# inferred from the provider's identity.
CAPABILITY_WATCHED_READ = "watched.read"
CAPABILITY_WATCHED_WRITE_PLAYED = "watched.write_played"
CAPABILITY_WATCHED_WRITE_UNPLAYED = "watched.write_unplayed"
CAPABILITY_WATCHED_PUSH_PLAYED = "watched.push_played"
CAPABILITY_WATCHED_PUSH_UNPLAYED = "watched.push_unplayed"
CAPABILITY_LISTEN_READ = "listen.read"


class SyncBinding(models.Model):
    """One approved relation between a Floppy user and one external profile.

    Binding identity is what origin derivation, cursors, receipts and conflicts
    scope to. An integration token's client identifier is not a substitute: one
    token can address several servers, and one server has several profiles.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_bindings",
    )
    client_kind = models.CharField(max_length=32, choices=SyncClientKind)
    # Identifies the server or service instance. Empty until the first payload
    # that carries it; filling an empty value in is a narrowing, not a change of
    # identity, so it does not force reapproval.
    instance_key = models.CharField(max_length=255, blank=True, default="")
    # Identifies the user account on that instance. A change here always forces
    # reapproval: writing another person's library is the failure this prevents.
    profile_key = models.CharField(max_length=255, blank=True, default="")
    # Stable opaque string stamped onto every change and delivery this binding
    # produces, so a state movement can be traced back and never echoed home.
    origin_key = models.CharField(max_length=128, unique=True)

    approved_capabilities = models.JSONField(default=list)
    approved_directions = models.JSONField(default=list)
    status = models.CharField(
        max_length=24,
        choices=SyncBindingStatus,
        default=SyncBindingStatus.PENDING.value,
    )
    # Operator stop switch. Independent of status so disabling for safety does
    # not discard the user's approvals.
    kill_switch = models.BooleanField(default=False)

    label = models.CharField(max_length=255, blank=True, default="")
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "Sync binding"
        verbose_name_plural = "Sync bindings"
        ordering = ["user", "client_kind", "instance_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "client_kind", "instance_key", "profile_key"],
                name="unique_sync_binding_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"SyncBinding({self.client_kind}, {self.user.username})"

    def is_operational(self) -> bool:
        """Return whether this binding may move state right now."""
        return self.status == SyncBindingStatus.ACTIVE.value and not self.kill_switch

    def has_capability(self, capability: str) -> bool:
        """Return whether the user approved one capability."""
        return capability in (self.approved_capabilities or [])

    def allows(self, direction: str, capability: str) -> bool:
        """Return whether one direction and capability are both approved.

        Both are required. An approved direction with an unverified capability
        must not write, and a verified capability the user has not pointed in
        that direction must not either.
        """
        if not self.is_operational():
            return False
        return direction in (
            self.approved_directions or []
        ) and self.has_capability(capability)


class SyncCheckpoint(models.Model):
    """The last applied position for one binding, resource and direction.

    Advanced only after the page it describes has committed, and never stored
    only in cache: a checkpoint lost to a restart re-reads, but a checkpoint
    advanced ahead of its data skips silently.
    """

    binding = models.ForeignKey(
        SyncBinding,
        on_delete=models.CASCADE,
        related_name="checkpoints",
    )
    resource = models.CharField(max_length=64)
    direction = models.CharField(max_length=16, choices=SyncDirection)
    # Opaque server cursor for Floppy-side change feeds.
    cursor = models.CharField(max_length=512, blank=True, default="")
    last_sequence = models.BigIntegerField(default=0)
    # The provider's own cursor, where it has one: a playback-reporting row id,
    # a millisecond sync stamp, a viewedAt watermark.
    provider_cursor = models.CharField(max_length=512, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Sync checkpoint"
        verbose_name_plural = "Sync checkpoints"
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "resource", "direction"],
                name="unique_sync_checkpoint_position",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"SyncCheckpoint({self.binding_id}, {self.resource}, {self.direction})"


class ProviderStateObservation(models.Model):
    """What a provider last told us, and what we held when it did.

    This is the merge base. Without the local revision and digest captured at
    observation time there is no way to tell "they moved" from "we moved", and
    every disagreement collapses into last-write-wins.
    """

    binding = models.ForeignKey(
        SyncBinding,
        on_delete=models.CASCADE,
        related_name="observations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_state_observations",
    )
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="provider_state_observations",
    )
    external_id = models.CharField(max_length=255, blank=True, default="")

    watched = models.BooleanField(default=False)
    play_count = models.PositiveIntegerField(default=0)
    watched_at = models.DateTimeField(null=True, blank=True)
    provider_digest = models.CharField(max_length=64, blank=True, default="")

    local_revision_at_observation = models.PositiveIntegerField(default=0)
    local_digest_at_observation = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )

    source = models.CharField(max_length=32, blank=True, default="")
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        """Model options."""

        verbose_name = "Provider state observation"
        verbose_name_plural = "Provider state observations"
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "item"],
                name="unique_provider_observation_per_item",
            ),
        ]
        indexes = [
            models.Index(fields=["binding", "observed_at"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"ProviderStateObservation({self.binding_id}, {self.item_id})"


class StateConflictReason(models.TextChoices):
    """Why an observation could not be applied without losing information."""

    DIVERGENT_WATCHED = "divergent_watched", "Both sides changed watched state"
    DIGEST_MISMATCH = "digest_mismatch", "States diverged"
    UNATTRIBUTABLE_UNWATCH = (
        "unattributable_unwatch",
        "Nothing identifiable to retract",
    )
    AMBIGUOUS_MATCH = "ambiguous_match", "More than one item matched"


class StateConflictStatus(models.TextChoices):
    """Whether a conflict still blocks propagation."""

    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


class StateConflict(models.Model):
    """A disagreement held for a person to settle.

    Propagation pauses for this item and this binding only. Everything else
    keeps flowing, because one unresolvable title must not stop a library.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="state_conflicts",
    )
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="state_conflicts",
    )
    binding = models.ForeignKey(
        SyncBinding,
        on_delete=models.CASCADE,
        related_name="conflicts",
    )
    reason = models.CharField(max_length=32, choices=StateConflictReason)
    status = models.CharField(
        max_length=16,
        choices=StateConflictStatus,
        default=StateConflictStatus.OPEN.value,
    )

    local_snapshot = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    remote_snapshot = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    base_snapshot = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    occurrence_count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "State conflict"
        verbose_name_plural = "State conflicts"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "binding", "reason"],
                condition=models.Q(status="open"),
                name="unique_open_state_conflict",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"StateConflict({self.reason}, item={self.item_id})"


class UnresolvedReferenceReason(models.TextChoices):
    """Why an external reference could not be turned into an item."""

    UNKNOWN_ID = "unknown_id", "No matching item"
    UNSUPPORTED_NAMESPACE = "unsupported_namespace", "Identifier type unsupported"
    AMBIGUOUS = "ambiguous", "More than one item matched"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type", "Media type unsupported"


class ExternalReferenceReviewStatus(models.TextChoices):
    """Resolution state for a user-owned integration identity."""

    RESOLVED = "resolved", "Resolved automatically"
    NEEDS_REVIEW = "needs_review", "Needs review"
    CORRECTED = "corrected", "Corrected"
    IGNORED = "ignored", "Ignored"


class ExternalReference(models.Model):
    """A user-scoped, stable source identity and its Floppy match.

    The source identity is intentionally independent of the destination Item.
    In particular, Plex rating keys are scoped by server/account and Trakt ids
    are scoped by source account, so a bad destination match can be corrected
    without losing the key used by the next import.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="external_references",
    )
    integration = models.CharField(max_length=32)
    source_account = models.CharField(max_length=255, blank=True, default="")
    external_namespace = models.CharField(max_length=32)
    external_identity = models.CharField(max_length=500)
    media_type = models.CharField(
        max_length=10,
        choices=(
            ("tv", "TV Show"),
            ("movie", "Movie"),
            ("episode", "Episode"),
        ),
    )
    matched_item = models.ForeignKey(
        "app.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_external_references",
    )
    corrected_item = models.ForeignKey(
        "app.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corrected_external_references",
    )
    review_status = models.CharField(
        max_length=20,
        choices=ExternalReferenceReviewStatus.choices,
        default=ExternalReferenceReviewStatus.RESOLVED.value,
    )
    # Source episode coordinate -> destination coordinate.  Kept on the
    # show reference so one correction applies to every future episode event.
    episode_mapping = models.JSONField(default=dict, blank=True)
    # Only allow-listed, non-secret display/context fields are written here.
    metadata = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    decision_note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "integration",
                    "source_account",
                    "external_namespace",
                    "external_identity",
                    "media_type",
                ],
                name="unique_user_external_reference",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "review_status"]),
            models.Index(fields=["user", "integration", "source_account"]),
            models.Index(fields=["matched_item", "media_type"]),
        ]

    def __str__(self):
        """Return a safe readable identity."""
        return f"ExternalReference({self.integration}:{self.external_identity})"


class UnresolvedExternalReference(models.Model):
    """An external id that could not be resolved, deduplicated by occurrence.

    Holds enough to explain the problem and nothing that could carry a secret:
    a namespace, a value, a reason, and the media shape it claimed to be.
    """

    binding = models.ForeignKey(
        SyncBinding,
        on_delete=models.CASCADE,
        related_name="unresolved_references",
    )
    namespace = models.CharField(max_length=32)
    value = models.CharField(max_length=255)
    reason_code = models.CharField(max_length=32, choices=UnresolvedReferenceReason)
    context = models.JSONField(default=dict, encoder=DjangoJSONEncoder)

    occurrence_count = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "Unresolved external reference"
        verbose_name_plural = "Unresolved external references"
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "namespace", "value", "reason_code"],
                name="unique_unresolved_external_reference",
            ),
        ]

    def __str__(self):
        """Readable representation."""
        return f"UnresolvedExternalReference({self.namespace}:{self.value})"


class OutboundDeliveryStatus(models.TextChoices):
    """Lifecycle of one outbound state write."""

    PENDING = "pending", "Pending"
    IN_FLIGHT = "in_flight", "In flight"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    SUPERSEDED = "superseded", "Superseded"
    SKIPPED = "skipped", "Skipped"


class OutboundStateDelivery(models.Model):
    """A durable intent to tell one provider about one state revision.

    Written in the same transaction as the change that caused it, so a crash
    between "we changed state" and "we told them" is impossible: either both
    rows exist or neither does. The Celery kick that follows is an optimisation,
    and a sweeper picks up anything a lost kick dropped, so correctness never
    depends on the broker being up.
    """

    binding = models.ForeignKey(
        SyncBinding,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="state_deliveries",
    )
    item = models.ForeignKey(
        "app.Item",
        on_delete=models.CASCADE,
        related_name="state_deliveries",
    )
    change = models.ForeignKey(
        "app.WatchStateChange",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    # The revision this write is trying to make true remotely, and the digest
    # that revision describes. Both are needed: the revision orders the write,
    # the digest is what a read-back is compared against.
    target_revision = models.PositiveIntegerField(default=0)
    target_digest = models.CharField(max_length=64, blank=True, default="")
    intent = models.BooleanField(
        default=True,
        help_text="True to mark played remotely, False to mark unplayed.",
    )

    status = models.CharField(
        max_length=16,
        choices=OutboundDeliveryStatus,
        default=OutboundDeliveryStatus.PENDING.value,
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True, default="")

    client_event_id = models.CharField(max_length=255, blank=True, default="")
    correlation_id = models.UUIDField(null=True, blank=True, db_index=True)
    # A fresh read of provider state taken *after* the write returned, not the
    # value we intended to write. This is what makes echo detection independent
    # of any timeout.
    readback_digest = models.CharField(max_length=64, blank=True, default="")
    echo_seen_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model options."""

        verbose_name = "Outbound state delivery"
        verbose_name_plural = "Outbound state deliveries"
        ordering = ["binding", "item", "target_revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "item", "target_revision"],
                name="unique_delivery_per_revision",
            ),
            # Serialization primitive: at most one write per (destination, item)
            # can be in flight, enforced by the database rather than by a lock
            # that a crashed worker could hold forever.
            models.UniqueConstraint(
                fields=["binding", "item"],
                condition=models.Q(status="in_flight"),
                name="unique_inflight_delivery_per_item",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["binding", "status"]),
        ]

    def __str__(self):
        """Readable representation."""
        return f"OutboundStateDelivery({self.binding_id}, item={self.item_id})"


class EmbyAccount(models.Model):
    """Store Emby connection settings for a user.

    Emby currently authenticates its webhook off the account token in the URL,
    which is enough to receive playback but not to read library state or write
    anything back. A real connection is what lets reconciliation notice a manual
    change — most providers have no event for "user ticked watched", so the only
    way to find out is to look.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="emby_account",
    )
    base_url = models.URLField(help_text="Emby server URL")
    api_key = models.TextField(help_text="Encrypted Emby API key")
    emby_user_id = models.CharField(max_length=255, blank=True, default="")
    emby_username = models.CharField(max_length=255, blank=True, default="")
    server_id = models.CharField(max_length=255, blank=True, default="")

    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Emby account"
        verbose_name_plural = "Emby accounts"

    def __str__(self):
        """Readable representation."""
        return f"EmbyAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return whether the connection is usable."""
        return bool(self.base_url and self.api_key and not self.connection_broken)


class KodiAccount(models.Model):
    """Store Kodi JSON-RPC connection settings for a user.

    Kodi identifies media by *local library id*, not by a provider id, so
    nothing can be written to it without first resolving identity through its
    library. That is what this connection is for; the webhook alone cannot do it.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kodi_account",
    )
    base_url = models.URLField(help_text="Kodi JSON-RPC endpoint URL")
    username = models.CharField(max_length=255, blank=True, default="")
    password = models.TextField(
        blank=True,
        default="",
        help_text="Encrypted Kodi JSON-RPC password",
    )
    instance_uuid = models.CharField(max_length=255, blank=True, default="")

    connection_broken = models.BooleanField(default=False)
    last_error_message = models.TextField(blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        verbose_name = "Kodi account"
        verbose_name_plural = "Kodi accounts"

    def __str__(self):
        """Readable representation."""
        return f"KodiAccount({self.user.username})"

    @property
    def is_connected(self):
        """Return whether the connection is usable."""
        return bool(self.base_url and not self.connection_broken)
