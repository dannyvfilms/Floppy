"""Create one provider-backed consumption, and plan it without writing.

``MediaTypeListView.post`` and the batch endpoint both go through here so there
is one definition of what appending a consumption means. ``plan_consumption``
never writes: it reads the provider and the user's own rows only.
"""

from dataclasses import dataclass, field
from http import HTTPStatus as HTTP  # noqa: N814

from app import metadata_utils
from app.forms import get_form_class
from app.models import BasicMedia, Item, MediaTypes
from app.providers import services
from app.services import metadata_resolution
from users.models import MediaStatusChoices

from .helpers import (
    MEDIA_TYPE_COMPLETE_MODEL_MAP,
    apply_image_url,
    check_source_type,
    check_valid_type,
    get_media_status,
    resolve_item_queryset,
)
from .serializers import HistorySerializer, serialize_data


class ConsumptionError(Exception):
    """A request the caller must change; carries the HTTP status and body."""

    def __init__(self, status, payload):
        """Store the response status and JSON payload."""
        super().__init__(payload.get("detail", ""))
        self.status = status
        self.payload = payload


@dataclass
class ConsumptionPlan:
    """What creating a consumption would do, decided without writing."""

    outcome: str
    item: Item | None = None
    existing: list = field(default_factory=list)
    errors: dict | None = None
    detail: str | None = None
    consumption_id: int | None = None


def normalize_body(media_type, raw_body):
    """Return the mutable form body ``post`` builds for a provider source."""
    body = raw_body.dict() if hasattr(raw_body, "dict") else dict(raw_body)
    body["media_type"] = media_type
    body["status"] = (
        get_media_status(body["status"], reverse=True)
        if "status" in body
        # default status when tracking a new media will be "planning"
        else MediaStatusChoices.PLANNING
    )
    return body


def _fetch_metadata(user, media_type, body):
    return services.get_media_metadata(
        media_type,
        body.get("media_id"),
        body["source"],
        [body.get("season_number")],
        language=metadata_resolution.metadata_language_default(user),
    )


def _library_media_type(body, metadata):
    return body.get("library_media_type") or metadata.get("library_media_type") or None


def _form(media_type, body, item, instance):
    media_data = dict(body)
    media_data.update({"source": item.source, "media_id": item.media_id})
    return get_form_class(media_type)(media_data, instance=instance)


def create_provider_consumption(user, media_type, body):
    """Append one consumption for a provider item and return the saved row.

    ``body`` is the output of ``normalize_body`` with a non-manual ``source``.
    Raises ``ConsumptionError`` for invalid input; database and provider
    failures propagate so each caller can map them.
    """
    media_id = body.get("media_id")
    if not media_id:
        raise ConsumptionError(
            HTTP.BAD_REQUEST,
            {"detail": "'media_id' is required for provider sources."},
        )

    season_number = body.get("season_number")
    metadata = _fetch_metadata(user, media_type, body)

    # FORK: bucket-aware item resolution + localized title fields. A raw
    # get_or_create on media_id/source/media_type can match the wrong
    # library bucket (grouped anime) or raise MultipleObjectsReturned, and
    # raw title/image defaults would drop original/localized titles.
    library_media_type = _library_media_type(body, metadata)
    item = resolve_item_queryset(
        media_id,
        body["source"],
        media_type,
        season_number=season_number,
        library_media_type=library_media_type,
    ).first()

    if item is None:
        item = Item.objects.create(
            media_id=media_id,
            source=body["source"],
            media_type=media_type,
            season_number=season_number,
            library_media_type=library_media_type or "",
            image=metadata.get("image") or "",
            **Item.title_fields_from_metadata(metadata),
        )

    model = MEDIA_TYPE_COMPLETE_MODEL_MAP.get(media_type)
    if model is None:
        raise ConsumptionError(
            HTTP.BAD_REQUEST,
            {"detail": "Unsupported media type."},
        )

    media_form = _form(media_type, body, item, model(item=item, user=user))
    if not media_form.is_valid():
        raise ConsumptionError(
            HTTP.BAD_REQUEST,
            {"detail": "Invalid media data.", "errors": media_form.errors},
        )

    media_form.save()
    apply_image_url(item, media_form.cleaned_data.get("image_url"))
    episode_count_fields = metadata_utils.apply_provider_episode_count(item, metadata)
    if episode_count_fields:
        item.save(update_fields=episode_count_fields)
    BasicMedia.objects.annotate_episode_progress([media_form.instance], media_type)
    return media_form.instance


def _overlaps(entry, start, end):
    entry_start = getattr(entry, "start_date", None)
    entry_end = getattr(entry, "end_date", None)
    if not (entry_start and entry_end and start and end):
        return False
    return entry_start <= end and entry_end >= start


def matching_equivalent(entries, skip_if_existing, form_data):
    """Return the first entry the caller declared equivalent, else ``None``.

    Equivalence is only what the caller states: an optional status and, with
    ``overlaps``, a date range that intersects the requested one.
    """
    if not skip_if_existing:
        return None
    status = skip_if_existing.get("status")
    wanted = get_media_status(status, reverse=True) if status else None
    for entry in entries:
        if wanted is not None and entry.status != wanted:
            continue
        if skip_if_existing.get("overlaps") and not _overlaps(
            entry,
            form_data.get("start_date"),
            form_data.get("end_date"),
        ):
            continue
        return entry
    return None


def plan_consumption(user, spec):
    """Decide what ``create_provider_consumption`` would do; never writes."""
    media_type = spec.get("media_type")
    source = spec.get("source")
    if not check_valid_type(media_type, complete=True):
        return ConsumptionPlan("invalid", detail="Unsupported media type.")
    if media_type in (MediaTypes.VIDEO.value, MediaTypes.EPISODE.value):
        return ConsumptionPlan(
            "invalid",
            detail=f"`{media_type}` consumptions are not supported by batches.",
        )
    if not source or not check_source_type(media_type, source):
        return ConsumptionPlan(
            "invalid",
            detail=f"Cannot use `{source}` for `{media_type}` media type",
        )
    if not spec.get("media_id"):
        return ConsumptionPlan("invalid", detail="'media_id' is required.")

    body = normalize_body(
        media_type,
        {k: v for k, v in spec.items() if k not in {"client_ref", "skip_if_existing"}},
    )
    try:
        metadata = _fetch_metadata(user, media_type, body)
    except services.ProviderAPIError as error:
        if error.status_code == HTTP.NOT_FOUND:
            return ConsumptionPlan("not_found", detail="Not found at the provider.")
        return ConsumptionPlan(
            "unavailable", detail=f"Could not reach {error.provider_label}."
        )

    items = list(
        resolve_item_queryset(
            body["media_id"],
            source,
            media_type,
            season_number=body.get("season_number"),
            library_media_type=_library_media_type(body, metadata),
        )[:2],
    )
    if len(items) > 1:
        return ConsumptionPlan(
            "ambiguous",
            detail="More than one library item matches; pass library_media_type.",
        )

    item = items[0] if items else None
    model = MEDIA_TYPE_COMPLETE_MODEL_MAP[media_type]
    preview = item or Item(
        media_id=body["media_id"],
        source=source,
        media_type=media_type,
        season_number=body.get("season_number"),
    )
    media_form = _form(media_type, body, preview, model(item=preview, user=user))
    if not media_form.is_valid():
        return ConsumptionPlan(
            "invalid",
            item=item,
            errors={k: list(v) for k, v in media_form.errors.items()},
            detail="Invalid media data.",
        )

    if item is None:
        return ConsumptionPlan("would_create")
    entries = list(model.objects.filter(user=user, item=item).order_by("id"))
    existing = serialize_data(entries, serializer_class=HistorySerializer, many=True)
    match = matching_equivalent(
        entries,
        spec.get("skip_if_existing"),
        media_form.cleaned_data,
    )
    if match is not None:
        return ConsumptionPlan(
            "skip",
            item=item,
            existing=existing,
            detail=f"Equivalent consumption {match.id} exists.",
            consumption_id=match.id,
        )
    return ConsumptionPlan("would_append", item=item, existing=existing)
