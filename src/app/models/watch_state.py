"""Canonical watched/played state, its ordered change log, and the sequence source.

Completion state is spread across six stores today: ``Media.status``/``end_date``
(where a repeat is another *row*, not a column), ``Episode`` rows, ``MoviePlay``
alongside duplicate ``Movie`` rows, ``PlaybackProgress.completed``, historical
music/podcast rows used as play records, and ``Season.rewatch_started_at``
windowing all of it. Nothing can answer "is this watched, who said so, and when
did we last agree with a provider about it" without re-deriving from all six.

``WatchState`` is that answer: one row per (user, item), written through from the
existing stores rather than replacing them. The legacy stores stay the source of
truth for *history*; this is the source of truth for *current state* and for the
provenance that integration synchronization needs.

Keying is ``unique(user, item)`` and nothing more. ``Item`` already carries
``library_media_type``, ``season_number`` and ``episode_number`` inside its own
unique constraints, so grouped anime (TV-shaped rows in the anime bucket) and
episode granularity are inherited for free. Repeating those discriminators here
would create a second source of truth for the thing ``Item`` already guarantees.
"""

import hashlib
import json

from django.conf import settings
from django.db import models

from app.models.item import Item


class WatchStateOrigin(models.TextChoices):
    """Where an accepted state change came from."""

    LOCAL_UI = "local_ui", "Local UI"
    LOCAL_API = "local_api", "Local API"
    WEBHOOK = "webhook", "Provider webhook"
    PROVIDER_PULL = "provider_pull", "Provider pull"
    IMPORT = "import", "Import"
    BACKFILL = "backfill", "Backfill"
    RECONCILE = "reconcile", "Reconciliation"


class WatchStateChangeKind(models.TextChoices):
    """Whether a change asserts state or retracts it.

    A retraction is always explicit. Absence from a provider's response is never
    a delete.
    """

    UPSERT = "upsert", "Upsert"
    DELETE = "delete", "Delete"


def calculate_state_digest(watched, play_count, last_watched_at):
    """Return the digest identifying one exact state.

    Two sides agree when their digests match, so the digest is what the apply
    algorithm compares instead of field-by-field equality. ``last_watched_at``
    is truncated to the second because providers round timestamps differently
    and a sub-second difference is not a disagreement.
    """
    payload = {
        "watched": bool(watched),
        "play_count": int(play_count or 0),
        "last_watched_at": (
            last_watched_at.replace(microsecond=0).isoformat()
            if last_watched_at
            else None
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class WatchState(models.Model):
    """Canonical completion state for one user and one item."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watch_states",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="watch_states",
    )

    watched = models.BooleanField(default=False)
    # Projection only. Floppy models a repeat as an extra row while every
    # provider models it as a scalar with no per-play identity, so this is
    # readable but never crosses an integration boundary.
    play_count = models.PositiveIntegerField(default=0)
    first_watched_at = models.DateTimeField(null=True, blank=True)
    last_watched_at = models.DateTimeField(null=True, blank=True)

    # Causal counter for this (user, item). Every accepted change bumps it, so
    # a baseline pinned to a revision can tell "we moved" from "they moved".
    revision = models.PositiveIntegerField(default=0)
    # Server sequence of the change that produced this state. Zero means the
    # state was projected or backfilled without emitting a change.
    sequence = models.BigIntegerField(default=0)
    state_digest = models.CharField(max_length=64, blank=True, default="")

    origin_kind = models.CharField(
        max_length=24,
        choices=WatchStateOrigin,
        default=WatchStateOrigin.BACKFILL.value,
    )
    origin_key = models.CharField(max_length=128, blank=True, default="")

    # Set when an observation could not be applied without losing information.
    # Propagation for this item pauses until a person resolves it.
    conflicted = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options for the model."""

        ordering = ["user", "item"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"],
                name="app_watchstate_unique_user_item",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["user", "sequence"]),
            models.Index(fields=["item"]),
            models.Index(
                fields=["user"],
                condition=models.Q(conflicted=True),
                name="app_watchstate_conflicted",
            ),
        ]

    def __str__(self):
        """Return the item and whether it is watched."""
        return f"{self.item} ({'watched' if self.watched else 'unwatched'})"

    def recalculate_digest(self):
        """Return the digest for this row's current values."""
        return calculate_state_digest(
            self.watched,
            self.play_count,
            self.last_watched_at,
        )


class WatchStateChange(models.Model):
    """One accepted state transition, in server order.

    Ordered by ``sequence``, which is allocated from ``WatchStateSequence`` under
    a row lock inside the same transaction as the change. That makes sequence
    order equal commit order: paginating by an autoincrement primary key would
    not, because PostgreSQL allocates those before commit and a reader can skip
    a row that was allocated earlier but committed later.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watch_state_changes",
    )
    # Survives an item merge so the log stays readable afterwards.
    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="watch_state_changes",
    )

    sequence = models.BigIntegerField()
    revision = models.PositiveIntegerField()
    # The revision this change was applied on top of. Null marks a genesis
    # change, which is what a first observation produces.
    previous_revision = models.PositiveIntegerField(null=True, blank=True)

    kind = models.CharField(
        max_length=8,
        choices=WatchStateChangeKind,
        default=WatchStateChangeKind.UPSERT.value,
    )
    watched = models.BooleanField(null=True, blank=True)
    play_count = models.PositiveIntegerField(null=True, blank=True)
    watched_at = models.DateTimeField(null=True, blank=True)
    # The digest of the state *after* this change applied.
    state_digest = models.CharField(max_length=64, blank=True, default="")

    origin_kind = models.CharField(max_length=24, choices=WatchStateOrigin)
    # The binding's origin key, or "ui"/"backfill" for local changes. Kept as an
    # opaque string rather than a foreign key: app must not import integrations,
    # and change history has to outlive the binding that produced it.
    origin_key = models.CharField(max_length=128, blank=True, default="")
    # The provider's own event id, when it supplies one. Together with the
    # origin key this is what makes a replayed provider event a no-op.
    origin_event_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    origin_observed_at = models.DateTimeField(null=True, blank=True)

    # Identity of the fan-out chain, minted at the first ingress and copied into
    # every downstream change and delivery, so a loop is recognisable.
    correlation_id = models.UUIDField(db_index=True)
    causation_id = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta options for the model."""

        ordering = ["user", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "sequence"],
                name="app_watchstatechange_unique_user_sequence",
            ),
            models.UniqueConstraint(
                fields=["user", "origin_key", "origin_event_id"],
                condition=models.Q(origin_event_id__isnull=False),
                name="app_watchstatechange_unique_origin_event",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "item", "-sequence"]),
        ]

    def __str__(self):
        """Return the sequence and what it asserted."""
        return f"#{self.sequence} {self.kind} {self.item}"


class WatchStateSequence(models.Model):
    """Per-user allocator for ``WatchStateChange.sequence``.

    Per-user is the only tenancy that matters: every change feed is scoped to a
    binding, and every binding is scoped to one user.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watch_state_sequence",
    )
    last_sequence = models.BigIntegerField(default=0)
    # Whether local state movements are recorded as changes. Off until the user
    # activates their first synchronizing connection, so a library nobody is
    # syncing pays nothing for the log, and an upgrade's backfill cannot emit a
    # change for every item the user has ever tracked.
    emit_changes = models.BooleanField(default=False)

    class Meta:
        """Meta options for the model."""

        ordering = ["user"]

    def __str__(self):
        """Return the user and the last allocated sequence."""
        return f"{self.user} @ {self.last_sequence}"
