from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint

from app.models.choices import MediaTypes, Sources
from app.models.item import Item

CREDITS_BACKFILL_VERSION = 4
DISCOVER_MOVIE_METADATA_BACKFILL_VERSION = 1
TRAKT_POPULARITY_BACKFILL_VERSION = 1


class ItemProviderLink(models.Model):
    """Cross-provider ID mapping for a tracked item."""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="provider_links",
    )
    provider = models.CharField(max_length=20, choices=Sources.choices)
    provider_media_id = models.CharField(max_length=32)
    provider_media_type = models.CharField(max_length=10, choices=MediaTypes.choices)
    season_number = models.PositiveIntegerField(null=True, blank=True)
    episode_offset = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model and field configuration."""

        ordering = [
            "provider",
            "provider_media_type",
            "provider_media_id",
            "season_number",
        ]
        constraints = [
            UniqueConstraint(
                fields=["item", "provider", "provider_media_type", "season_number"],
                name="%(app_label)s_%(class)s_unique_item_provider_type",
            ),
            UniqueConstraint(
                fields=[
                    "provider",
                    "provider_media_type",
                    "provider_media_id",
                    "season_number",
                ],
                name="%(app_label)s_%(class)s_unique_provider_lookup",
            ),
        ]
        indexes = [
            models.Index(
                fields=["provider", "provider_media_type", "provider_media_id"]
            ),
            models.Index(fields=["item", "provider"]),
        ]

    def __str__(self):
        """Return a readable mapping label."""
        season_suffix = (
            f" S{self.season_number}" if self.season_number is not None else ""
        )
        return (
            f"{self.item_id}:{self.provider}/{self.provider_media_type}/"
            f"{self.provider_media_id}{season_suffix}"
        )


class MetadataProviderPreference(models.Model):
    """Per-user display-provider override for a tracked item."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="metadata_provider_preferences",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="metadata_provider_preferences",
    )
    provider = models.CharField(max_length=20, choices=Sources.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model and field configuration."""

        constraints = [
            UniqueConstraint(
                fields=["user", "item"],
                name="%(app_label)s_%(class)s_unique_user_item",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "provider"]),
            models.Index(fields=["item", "provider"]),
        ]

    def __str__(self):
        """Return the display-provider preference label."""
        return f"{self.user_id}:{self.item_id}->{self.provider}"


class HardcoverEditionPreference(models.Model):
    """Per-user Hardcover edition override for a tracked book item."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hardcover_edition_preferences",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="hardcover_edition_preferences",
    )
    edition_id = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model and field configuration."""

        constraints = [
            UniqueConstraint(
                fields=["user", "item"],
                name="%(app_label)s_%(class)s_unique_user_item",
            ),
        ]

    def __str__(self):
        """Return the edition preference label."""
        return f"{self.user_id}:{self.item_id}->edition/{self.edition_id}"


class MetadataBackfillField(models.TextChoices):
    """Fields that can be backfilled from external metadata."""

    RUNTIME = "runtime", "Runtime"
    GENRES = "genres", "Genres"
    CREDITS = "credits", "Credits"
    RELEASE = "release", "Release Date"
    DISCOVER = "discover", "Discover Metadata"
    GAME_LENGTHS = "game_lengths", "Game Lengths"
    TRAKT_POPULARITY = "trakt_popularity", "Trakt Popularity"
    IGDB_RATINGS = "igdb_ratings", "IGDB Ratings"
    WATCH_PROVIDERS = "watch_providers", "Watch Providers"


class MetadataBackfillState(models.Model):
    """Track metadata backfill attempts to avoid endless retries."""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="metadata_backfill_states",
    )
    field = models.CharField(
        max_length=20,
        choices=MetadataBackfillField.choices,
    )
    fail_count = models.PositiveIntegerField(default=0)
    strategy_version = models.PositiveIntegerField(default=1)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    give_up = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model and field configuration."""

        constraints = [
            UniqueConstraint(
                fields=["item", "field"],
                name="unique_metadata_backfill_state",
            ),
        ]
        indexes = [
            models.Index(fields=["field", "next_retry_at"]),
            models.Index(fields=["field", "give_up"]),
        ]

    def __str__(self):
        """Return the item and field this backfill state tracks."""
        return f"{self.item} {self.field}"


class BackfillReconcileState(models.Model):
    """Track whether a whole-library reconcile sweep still has work to do.

    The reconcilers previously stored this in the cache, which meant it did not
    survive a Redis restart or eviction, and the "done" marker was consulted so
    loosely that a sweep re-enqueued every candidate in the library every five
    minutes forever - the dominant source of idle CPU and Redis churn in issue
    #521. Keeping it in the database makes "this strategy version is finished" a
    durable fact, so the beat entry can poll infrequently and back off.

    One row per reconcile key (not per item - that is MetadataBackfillState).
    "done" is a durable database fact, not cache state.
    """

    key = models.CharField(max_length=100, unique=True)
    strategy_version = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_after = models.DateTimeField(null=True, blank=True)
    consecutive_no_op_runs = models.PositiveIntegerField(default=0)
    last_cursor_item_id = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model and field configuration."""

        indexes = [
            models.Index(fields=["key", "strategy_version"]),
        ]

    def __str__(self):
        """Return the reconcile key and its strategy version."""
        return f"{self.key} v{self.strategy_version}"


class PersonGender(models.TextChoices):
    """Normalized person genders used across providers."""

    UNKNOWN = "unknown", "Unknown"
    FEMALE = "female", "Female"
    MALE = "male", "Male"
    NON_BINARY = "non_binary", "Non-binary"


class CreditRoleType(models.TextChoices):
    """Credit role category."""

    CAST = "cast", "Cast"
    CREW = "crew", "Crew"
    AUTHOR = "author", "Author"


class Person(models.Model):
    """Known cast/crew person."""

    source = models.CharField(
        max_length=20,
        choices=Sources.choices,
        default=Sources.TMDB.value,
    )
    source_person_id = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    image = models.TextField(blank=True, default="")
    known_for_department = models.CharField(max_length=120, blank=True, default="")
    biography = models.TextField(blank=True, default="")
    gender = models.CharField(
        max_length=20,
        choices=PersonGender.choices,
        default=PersonGender.UNKNOWN.value,
    )
    birth_date = models.DateField(null=True, blank=True)
    death_date = models.DateField(null=True, blank=True)
    place_of_birth = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        """Meta options for the model."""

        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_person_id"],
                name="%(app_label)s_%(class)s_unique_source_person",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "source_person_id"]),
        ]

    def __str__(self):
        """Return the person name."""
        return self.name


class Studio(models.Model):
    """Studio/company associated with a media item."""

    source = models.CharField(
        max_length=20,
        choices=Sources.choices,
        default=Sources.TMDB.value,
    )
    source_studio_id = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    # Provider artwork is opaque metadata. Signed/CDN URLs can exceed the
    # URLField default of 200 characters and are not indexed, so storing the
    # complete value is safer than truncating it and works on SQLite/PostgreSQL.
    logo = models.TextField(blank=True, default="")

    class Meta:
        """Meta options for the model."""

        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_studio_id"],
                name="%(app_label)s_%(class)s_unique_source_studio",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "source_studio_id"]),
        ]

    def __str__(self):
        """Return the studio name."""
        return self.name


class ItemPersonCredit(models.Model):
    """Cast/crew credits connecting media items and people."""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="person_credits",
    )
    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="item_credits",
    )
    role_type = models.CharField(max_length=10, choices=CreditRoleType.choices)
    role = models.CharField(max_length=255, blank=True, default="")
    department = models.CharField(max_length=120, blank=True, default="")
    sort_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        """Meta options for the model."""

        ordering = ["sort_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "person", "role_type", "role", "department"],
                name="%(app_label)s_%(class)s_unique_credit",
            ),
        ]
        indexes = [
            models.Index(fields=["item", "role_type"]),
            models.Index(fields=["person", "role_type"]),
            models.Index(fields=["department"]),
        ]

    def __str__(self):
        """Return the credit label."""
        return f"{self.person} - {self.role_type}"


class ItemStudioCredit(models.Model):
    """Studio/company links for media items."""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="studio_credits",
    )
    studio = models.ForeignKey(
        Studio,
        on_delete=models.CASCADE,
        related_name="item_credits",
    )
    sort_order = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        """Meta options for the model."""

        ordering = ["sort_order", "studio__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "studio"],
                name="%(app_label)s_%(class)s_unique_item_studio",
            ),
        ]
        indexes = [
            models.Index(fields=["item"]),
            models.Index(fields=["studio"]),
        ]

    def __str__(self):
        """Return the studio credit label."""
        return f"{self.studio} - {self.item}"
