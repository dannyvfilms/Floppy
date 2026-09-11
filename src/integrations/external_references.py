"""Persistence and lookup helpers for Plex and Trakt match decisions."""

import hashlib
import json

from django.db import transaction
from django.utils import timezone

from app.models import Episode, MediaTypes, Sources
from integrations.models import ExternalReference, ExternalReferenceReviewStatus

REFERENCE_METADATA_KEYS = frozenset(
    {
        "title",
        "year",
        "series_title",
        "season_number",
        "episode_number",
        "rating_key",
        "guid",
    },
)
PAIR_SIZE = 2


def allowlisted_metadata(metadata):
    """Return only small, non-secret fields useful to a review screen."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key in REFERENCE_METADATA_KEYS
        and isinstance(value, (str, int, float, bool, type(None)))
    }


def plex_source_account(account=None, *, machine_identifier=None, payload=None):
    """Return the stable Plex server/account scope for one observation."""
    payload = payload or {}
    server = payload.get("Server") or {}
    machine_identifier = (
        machine_identifier
        or server.get("uuid")
        or server.get("machineIdentifier")
        or getattr(account, "machine_identifier", None)
        or server.get("uri")
        or "unknown-server"
    )
    account_id = (
        getattr(account, "plex_account_id", None)
        or (payload.get("Account") or {}).get("id")
        or (payload.get("Account") or {}).get("accountID")
        or getattr(account, "plex_username", None)
        or (payload.get("Account") or {}).get("title")
        or "unknown-account"
    )
    return f"{str(machine_identifier).strip()}::{str(account_id).strip()}"


def plex_identity(metadata, *, show=False):
    """Return ``(namespace, identity)`` for a stable Plex source identity."""
    if show:
        value = metadata.get("grandparentRatingKey") or metadata.get("grandparentKey")
        if value:
            return "plex_rating_key", str(value).rstrip("/").rsplit("/", 1)[-1]

    rating_key = metadata.get("ratingKey") or metadata.get("ratingkey")
    if rating_key:
        return "plex_rating_key", str(rating_key).rstrip("/").rsplit("/", 1)[-1]

    guids = metadata.get("Guid") or metadata.get("guid") or []
    if isinstance(guids, (str, dict)):
        guids = [guids]
    for guid in guids:
        value = guid.get("id") if isinstance(guid, dict) else guid
        if isinstance(value, str) and value.lower().startswith("plex://"):
            return "plex_guid", value
    return None


def trakt_identity(entry_data):
    """Return a stable Trakt identity from a show/movie/episode payload."""
    ids = entry_data.get("ids") or {}
    value = ids.get("trakt")
    if value not in (None, ""):
        return "trakt", str(value)
    return None


def _reference_queryset(
    user,
    integration,
    source_account,
    external_namespace,
    external_identity,
    media_type,
):
    return ExternalReference.objects.filter(
        user=user,
        integration=integration,
        source_account=source_account or "",
        external_namespace=external_namespace,
        external_identity=str(external_identity),
        media_type=media_type,
    )


def lookup_reference(
    user,
    integration,
    source_account,
    external_namespace,
    external_identity,
    media_type,
    *,
    include_show_for_episode=True,
):
    """Return the saved decision for an exact source identity."""
    if not external_identity:
        return None
    reference = _reference_queryset(
        user,
        integration,
        source_account,
        external_namespace,
        external_identity,
        media_type,
    ).select_related("matched_item", "corrected_item").first()
    if reference:
        return reference

    if include_show_for_episode and media_type == MediaTypes.EPISODE.value:
        return _reference_queryset(
            user,
            integration,
            source_account,
            external_namespace,
            external_identity,
            MediaTypes.TV.value,
        ).select_related("matched_item", "corrected_item").first()
    return None


def lookup_plex_reference(user, account, metadata, media_type, *, payload=None):
    """Find an episode decision first, then its show-level decision."""
    source_account = plex_source_account(account, payload=payload)
    identity = plex_identity(metadata)
    if identity:
        reference = lookup_reference(
            user,
            "plex",
            source_account,
            *identity,
            media_type,
        )
        if reference:
            return reference
    if media_type == MediaTypes.EPISODE.value:
        show_identity = plex_identity(metadata, show=True)
        if show_identity:
            return lookup_reference(
                user,
                "plex",
                source_account,
                *show_identity,
                MediaTypes.TV.value,
                include_show_for_episode=False,
            )
    return None


def reference_target(reference):
    """Return a valid corrected/current target, if the decision has one."""
    if not reference or reference.review_status == ExternalReferenceReviewStatus.IGNORED:
        return None
    target = reference.corrected_item or reference.matched_item
    if not target or target.source != Sources.TMDB.value:
        return None
    expected_type = (
        MediaTypes.EPISODE.value
        if reference.media_type == MediaTypes.EPISODE.value
        else reference.media_type
    )
    if target.media_type != expected_type:
        return None
    return target


def saved_decision(reference):
    """Return a small resolver-facing decision dictionary."""
    if reference is None:
        return None
    return {
        "ignored": reference.review_status == ExternalReferenceReviewStatus.IGNORED,
        "target": reference_target(reference),
        "episode_mapping": reference.episode_mapping or {},
        "reference": reference,
    }


def map_episode_coordinates(reference, season_number, episode_number):
    """Apply a saved source-to-destination episode mapping, if present."""
    if not reference:
        return season_number, episode_number
    mapping = (
        reference
        if isinstance(reference, dict)
        else reference.episode_mapping or {}
    )
    value = mapping.get(f"{season_number}:{episode_number}")
    if value is None:
        value = mapping.get(f"s{season_number}e{episode_number}")
    if isinstance(value, dict):
        value = (value.get("season"), value.get("episode"))
    if isinstance(value, (list, tuple)) and len(value) == PAIR_SIZE:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return season_number, episode_number
    return season_number, episode_number


def save_observation(
    user,
    integration,
    source_account,
    external_namespace,
    external_identity,
    media_type,
    *,
    matched_item=None,
    metadata=None,
    needs_review=False,
):
    """Create/update a reference without replacing a user decision."""
    if not external_identity:
        return None
    defaults = {
        "matched_item": matched_item,
        "metadata": allowlisted_metadata(metadata),
        "review_status": (
            ExternalReferenceReviewStatus.NEEDS_REVIEW.value
            if needs_review
            else ExternalReferenceReviewStatus.RESOLVED.value
        ),
    }
    with transaction.atomic():
        reference, created = ExternalReference.objects.select_for_update().get_or_create(
            user=user,
            integration=integration,
            source_account=source_account or "",
            external_namespace=external_namespace,
            external_identity=str(external_identity),
            media_type=media_type,
            defaults=defaults,
        )
        if created:
            return reference

        update_fields = []
        if (
            matched_item is not None
            and reference.review_status
            not in {
                ExternalReferenceReviewStatus.CORRECTED.value,
                ExternalReferenceReviewStatus.IGNORED.value,
            }
            and reference.matched_item_id != matched_item.pk
        ):
            reference.matched_item = matched_item
            update_fields.append("matched_item")
        clean_metadata = allowlisted_metadata(metadata)
        if clean_metadata and reference.metadata != clean_metadata:
            reference.metadata = clean_metadata
            update_fields.append("metadata")
        if (
            needs_review
            and reference.review_status == ExternalReferenceReviewStatus.RESOLVED.value
        ):
            reference.review_status = ExternalReferenceReviewStatus.NEEDS_REVIEW.value
            update_fields.append("review_status")
        if update_fields:
            reference.save(update_fields=[*update_fields, "updated_at"])
        return reference


def save_correction(reference_ids, *, user, destination, episode_mapping=None, note=""):
    """Persist a correction for the selected references atomically."""
    with transaction.atomic():
        references = list(
            ExternalReference.objects.select_for_update().filter(
                user=user,
                id__in=reference_ids,
            ),
        )
        if not references:
            return 0
        for reference in references:
            corrected_item = destination
            if reference.media_type == MediaTypes.EPISODE.value:
                source_season = reference.metadata.get("season_number")
                source_episode = reference.metadata.get("episode_number")
                try:
                    destination_season, destination_episode = map_episode_coordinates(
                        episode_mapping or {},
                        int(source_season),
                        int(source_episode),
                    )
                except (TypeError, ValueError):
                    destination_season = destination_episode = None
                if destination_season is not None and destination_episode is not None:
                    destination_episode_row = (
                        Episode.objects.filter(
                            related_season__related_tv__user=user,
                            related_season__related_tv__item=destination,
                            related_season__item__season_number=destination_season,
                            item__episode_number=destination_episode,
                        )
                        .select_related("item")
                        .first()
                    )
                    if destination_episode_row is not None:
                        corrected_item = destination_episode_row.item
            reference.corrected_item = corrected_item
            reference.review_status = ExternalReferenceReviewStatus.CORRECTED.value
            reference.episode_mapping = episode_mapping or {}
            reference.decision_note = note[:500]
            reference.save(
                update_fields=[
                    "corrected_item",
                    "review_status",
                    "episode_mapping",
                    "decision_note",
                    "updated_at",
                ],
            )
        return len(references)


def set_reference_status(reference_id, *, user, status):
    """Set or clear an ignore/correction review status for one user."""
    allowed = {choice for choice, _label in ExternalReferenceReviewStatus.choices}
    if status not in allowed:
        message = "Unsupported external-reference status"
        raise ValueError(message)
    return ExternalReference.objects.filter(user=user, pk=reference_id).update(
        review_status=status,
        updated_at=timezone.now(),
    )


def preview_digest(source_item, destination_item, *, episode_mapping=None):
    """Build a deterministic preview token from affected user-owned state."""
    payload = {
        "source": source_item.pk,
        "destination": destination_item.pk,
        "mapping": episode_mapping or {},
        "source_title": source_item.title,
        "destination_title": destination_item.title,
        "media_type": source_item.media_type,
    }
    # Counts and latest creation timestamps catch concurrent changes without
    # serializing the whole history into the browser.
    for label, item in (("source", source_item), ("destination", destination_item)):
        payload[f"{label}_tv"] = list(
            item.tv_set.values_list("pk", "status", "score", "progress", "end_date")
        ) if hasattr(item, "tv_set") else []
        payload[f"{label}_movie"] = list(
            item.movie_set.values_list("pk", "status", "score", "progress", "end_date")
        ) if hasattr(item, "movie_set") else []
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
