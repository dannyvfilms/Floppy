"""Custom rating scale rules: scoring, validation and scale/entry persistence.

The final score always lands on Floppy's internal 0-10 `score`. Criteria with
different ranges are normalised to 0-10 first, so a 1-100 criterion has no more
influence than a 1-5 one; the tier (`weight`) is then the only thing that
changes influence. Empty criteria are left out of the average; 0 is a score.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from users.rating_scale_models import EntryRating, RatingCriterion, RatingScale

TEN = Decimal(10)
MAX_CRITERIA = 30
MAX_TIERS = 10
MAX_RANGE_VALUE = Decimal(1000)
ONE_DECIMAL = Decimal("0.1")
NOT_A_NUMBER = "Enter a number."


class RatingScaleError(ValueError):
    """Raised for invalid scale or rating input; `message` is user-facing.

    The text lives on `message`, never in `args`, so a handler can only ever
    return text written for the user and not exception internals.
    """

    def __init__(self, message):
        """Keep the user-facing text off the exception args."""
        super().__init__()
        self.message = str(message)


def _decimal(value):
    """Return a finite Decimal, or None for empty input."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as error:
        raise RatingScaleError(NOT_A_NUMBER) from error
    if not number.is_finite():
        raise RatingScaleError(NOT_A_NUMBER)
    return number


def normalize(value, minimum, maximum):
    """Map a criterion value onto the internal 0-10 range."""
    span = Decimal(maximum) - Decimal(minimum)
    if span <= 0:
        return Decimal(0)
    return (Decimal(value) - Decimal(minimum)) / span * TEN


def compute_score(criteria, values):
    """Return the weighted 0-10 score, or None when nothing is filled in.

    `criteria` are RatingCriterion-like objects (id, minimum, maximum, weight);
    `values` maps str(criterion id) to a number or None.
    """
    total = Decimal(0)
    weights = Decimal(0)
    for criterion in criteria:
        raw = values.get(str(criterion.id))
        if raw is None or raw == "":
            continue
        weight = Decimal(criterion.weight)
        total += weight * normalize(raw, criterion.minimum, criterion.maximum)
        weights += weight
    if not weights:
        return None
    return (total / weights).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def active_criteria(scale):
    """Criteria in display order (tier, then position), archived ones left out."""
    return [c for c in scale.criteria.all() if c.archived_at is None]


def clean_values(scale, raw):
    """Validate submitted values against each criterion's own range.

    Unknown ids are ignored so a stale form cannot attach values to a criterion
    the scale no longer has. Returns {str(id): Decimal}.
    """
    cleaned = {}
    for criterion in active_criteria(scale):
        number = _decimal((raw or {}).get(str(criterion.id)))
        if number is None:
            continue
        if not criterion.minimum <= number <= criterion.maximum:
            message = f"{criterion.name} must be between {criterion.minimum:g} and {criterion.maximum:g}."
            raise RatingScaleError(message)
        cleaned[str(criterion.id)] = number
    return cleaned


def scale_payload(scale):
    """Serialise a scale for the editor, the tracking form and the API."""
    criteria = [
        {
            "id": str(c.id),
            "name": c.name,
            "min": float(c.minimum),
            "max": float(c.maximum),
            "weight": c.weight,
            "position": c.position,
        }
        for c in active_criteria(scale)
    ]
    return {"id": str(scale.id), "name": scale.name, "criteria": criteria}


def user_scales(user):
    """Return the user's live (not archived) scales, criteria prefetched."""
    return list(
        user.rating_scales.filter(archived_at__isnull=True).prefetch_related("criteria"),
    )


def user_scales_by_id(user, scale_id):
    """One of the user's live scales by id, or None (also for malformed ids)."""
    try:
        return (
            user.rating_scales.filter(id=scale_id, archived_at__isnull=True)
            .prefetch_related("criteria")
            .first()
        )
    except (ValueError, TypeError, ValidationError):
        return None


def _tiers(criteria):
    """Weight tiers must be 1..n with no gaps; each tier needs a criterion."""
    weights = sorted({c["weight"] for c in criteria})
    if weights != list(range(1, len(weights) + 1)):
        message = "Weight tiers must be consecutive."
        raise RatingScaleError(message)


def _clean_criterion(raw, index):
    name = str(raw.get("name") or "").strip()
    if not name:
        message = "Every criterion needs a name."
        raise RatingScaleError(message)
    minimum = _decimal(raw.get("min"))
    maximum = _decimal(raw.get("max"))
    if minimum is None or maximum is None:
        message = f"{name} needs a minimum and a maximum."
        raise RatingScaleError(message)
    if maximum <= minimum:
        message = f"{name}: maximum must be above the minimum."
        raise RatingScaleError(message)
    if abs(minimum) > MAX_RANGE_VALUE or abs(maximum) > MAX_RANGE_VALUE:
        message = f"{name}: range is too large."
        raise RatingScaleError(message)
    try:
        weight = int(raw.get("weight") or 1)
    except (TypeError, ValueError) as error:
        message = f"{name}: invalid weight."
        raise RatingScaleError(message) from error
    return {
        "id": str(raw.get("id") or ""),
        "name": name[:60],
        "minimum": minimum,
        "maximum": maximum,
        "weight": weight,
        "position": index,
    }


@transaction.atomic
def save_scale(user, data, scale=None):
    """Create or update a scale from editor data.

    Criteria are matched by id, so renaming and reordering keep historical
    ratings attached. A criterion missing from `data` is archived rather than
    deleted, so saved values stay readable.
    """
    name = str(data.get("name") or "").strip()
    if not name:
        message = "Give the rating scale a name."
        raise RatingScaleError(message)
    raw_criteria = data.get("criteria") or []
    if not raw_criteria:
        message = "Add at least one criterion."
        raise RatingScaleError(message)
    if len(raw_criteria) > MAX_CRITERIA:
        message = f"A scale can have up to {MAX_CRITERIA} criteria."
        raise RatingScaleError(message)
    criteria = [_clean_criterion(raw, index) for index, raw in enumerate(raw_criteria)]
    _tiers(criteria)
    if max(c["weight"] for c in criteria) > MAX_TIERS:
        message = f"A scale can have up to {MAX_TIERS} weight tiers."
        raise RatingScaleError(message)

    if scale is None:
        scale = RatingScale.objects.create(
            user=user,
            name=name[:60],
            position=user.rating_scales.count(),
        )
    else:
        scale.name = name[:60]
        scale.save(update_fields=["name", "updated_at"])

    existing = {str(c.id): c for c in scale.criteria.all()}
    kept = set()
    for item in criteria:
        row = existing.get(item["id"])
        fields = {
            "name": item["name"],
            "minimum": item["minimum"],
            "maximum": item["maximum"],
            "weight": item["weight"],
            "position": item["position"],
            "archived_at": None,
        }
        if row is None:
            row = RatingCriterion.objects.create(scale=scale, **fields)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            row.save()
        kept.add(str(row.id))
    now = timezone.now()
    for key, row in existing.items():
        if key not in kept and row.archived_at is None:
            row.archived_at = now
            row.save(update_fields=["archived_at"])
    return RatingScale.objects.prefetch_related("criteria").get(pk=scale.pk)


@transaction.atomic
def delete_scale(user, scale):
    """Remove a scale. One with saved ratings is archived so history survives."""
    if user.custom_rating_scale_id == scale.id:
        user.custom_rating_scale = None
        user.save(update_fields=["custom_rating_scale"])
    if scale.entry_ratings.exists():
        scale.archived_at = timezone.now()
        scale.save(update_fields=["archived_at", "updated_at"])
        return "archived"
    scale.delete()
    return "deleted"


def get_entry_rating(entry):
    """Return the stored EntryRating for an entry, or None."""
    if entry is None or entry.pk is None:
        return None
    content_type = ContentType.objects.get_for_model(entry)
    return (
        EntryRating.objects.select_related("scale")
        .filter(content_type=content_type, object_id=entry.pk)
        .first()
    )


def entry_payload(user, entry):
    """Return the active scale with this entry's values for forms and the API."""
    scale = getattr(user, "custom_rating_scale", None)
    if scale is None:
        return None
    payload = scale_payload(scale)
    stored = get_entry_rating(entry)
    same_scale = stored is not None and stored.scale_id == scale.id
    values = stored.values if same_scale else {}
    payload["values"] = {
        key: float(Decimal(str(value))) for key, value in values.items()
    }
    payload["computed"] = (
        float(stored.computed_score) if same_scale and stored.computed_score is not None else None
    )
    payload["manual"] = bool(same_scale and stored.is_manual)
    return payload


def apply_rating(user, values, manual_score=None):
    """Resolve the score a save should store.

    Returns (score, computed, manual, cleaned_values). `manual_score` is a
    0-10 number the user typed over the calculated one, or None to follow it.
    """
    scale = user.custom_rating_scale
    cleaned = clean_values(scale, values)
    computed = compute_score(active_criteria(scale), cleaned)
    if manual_score is not None:
        return manual_score, computed, True, cleaned
    return computed, computed, False, cleaned


@transaction.atomic
def save_entry_rating(user, entry, cleaned, computed, *, manual):
    """Persist per-criterion values beside the entry's score."""
    content_type = ContentType.objects.get_for_model(entry)
    scale = user.custom_rating_scale
    if not cleaned and not manual:
        EntryRating.objects.filter(
            content_type=content_type,
            object_id=entry.pk,
        ).delete()
        return None
    row, _created = EntryRating.objects.update_or_create(
        content_type=content_type,
        object_id=entry.pk,
        defaults={
            "user": user,
            "scale": scale,
            "values": {key: str(value) for key, value in cleaned.items()},
            "computed_score": computed,
            "is_manual": manual,
        },
    )
    return row


def keeps_plain_score(entry, cleaned, manual):
    """Return True when a save carries no criteria for an entry that had none.

    A historical score (rated before the custom scale, or on a built-in one)
    must survive such a save instead of being replaced by "not rated".
    """
    return not cleaned and not manual and get_entry_rating(entry) is None


def criteria_from_body(user, body, entry=None):
    """Fold an API body's `criteria` into its `score`.

    Pops `criteria` and `score_is_manual` from the mutable `body` and sets
    `body["score"]` to the calculated (or manual) 0-10 score. Returns
    (pending, error); `pending` is what `save_entry_rating` needs, set on the
    entry before it is saved. A flat `score` alone is left untouched.
    """
    raw = body.pop("criteria", None)
    manual_flag = body.pop("score_is_manual", None)
    if raw is None:
        # A flat score on an entry that has criteria is a manual override of them.
        existing = get_entry_rating(entry) if entry is not None else None
        if existing is not None and body.get("score") is not None:
            return {
                "user": user,
                "values": {key: Decimal(str(v)) for key, v in existing.values.items()},
                "computed": existing.computed_score,
                "manual": True,
            }, None
        return None, None
    scale = user.custom_rating_scale
    if scale is None:
        return None, "Choose a custom rating scale before sending criteria."
    if not isinstance(raw, dict):
        return None, "criteria must be an object of criterion id to value."
    manual = manual_flag in {True, "1", "true", "on"}
    try:
        manual_score = None
        if manual and body.get("score") is not None:
            manual_score = Decimal(str(body["score"]))
        score, computed, manual, cleaned = apply_rating(user, raw, manual_score)
    except RatingScaleError as error:
        return None, error.message or "Invalid score."
    except InvalidOperation:
        return None, "Invalid score."
    if entry is not None and keeps_plain_score(entry, cleaned, manual):
        return None, None
    body["score"] = None if score is None else float(score)
    return {"user": user, "values": cleaned, "computed": computed, "manual": manual}, None


def api_criteria(entry):
    """Per-criterion breakdown for API responses, or None without one.

    `[{key, label, weight, min, max, value}]` plus the calculated score and
    whether the stored score is a manual override.
    """
    row = get_entry_rating(entry)
    if row is None:
        return None
    values = row.values
    return {
        "scale": {"id": str(row.scale_id), "name": row.scale.name},
        "computed_score": None if row.computed_score is None else float(row.computed_score),
        "score_is_manual": row.is_manual,
        "criteria": [
            {
                "key": str(c.id),
                "label": c.name,
                "weight": c.weight,
                "min": float(c.minimum),
                "max": float(c.maximum),
                "value": float(Decimal(values[str(c.id)])) if str(c.id) in values else None,
            }
            for c in row.scale.criteria.all()
            if c.archived_at is None
        ],
    }
