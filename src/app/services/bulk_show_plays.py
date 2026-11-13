"""Add plays to History for many selected TV shows at once.

Each show goes through ``apply_bulk_episode_plays``, the same code the single
show "Episode Plays" form uses, so a bulk run keeps every rule of a single run
(season trackers, inherited scores, season completion, History and Statistics
days). This module only decides *which* episodes and *which dates*, and
reports progress so a large selection can run in the background.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from app import bulk_actions
from app.models import Item, MediaTypes, Season, Status
from app.providers import services
from app.services import bulk_episode_tracking, metadata_resolution

logger = logging.getLogger(__name__)

SCOPES = ("aired", "watched", "seasons")
EXISTING_MODES = ("skip", "add")
DATE_MODES = ("air_date", "one_date", "range")
MAX_SHOWS = 1000
STATUS_TTL = 6 * 60 * 60
LOCK_TTL = 15 * 60
MAX_LISTED_PROBLEMS = 50
SAMPLE_SIZE = 5


@dataclass(slots=True)
class PlayOptions:
    """What to add: which episodes, how to treat repeats, which dates."""

    scope: str = "aired"
    season_from: int | None = None
    season_to: int | None = None
    existing: str = "skip"
    date_mode: str = "air_date"
    start: object = None
    end: object = None

    def as_task_kwargs(self) -> dict:
        """Return JSON-safe options for the Celery task."""
        return {
            "scope": self.scope,
            "season_from": self.season_from,
            "season_to": self.season_to,
            "existing": self.existing,
            "date_mode": self.date_mode,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }

    @classmethod
    def from_task_kwargs(cls, data: dict) -> PlayOptions:
        """Rebuild options from ``as_task_kwargs`` output."""
        return cls(
            scope=data["scope"],
            season_from=data.get("season_from"),
            season_to=data.get("season_to"),
            existing=data["existing"],
            date_mode=data["date_mode"],
            start=bulk_episode_tracking.coerce_episode_datetime(data.get("start")),
            end=bulk_episode_tracking.coerce_episode_datetime(data.get("end")),
        )


def status_key(user_id: int, operation_id: str) -> str:
    """Cache key for one job's progress, scoped to its owner."""
    return f"bulk_show_plays:status:{user_id}:{operation_id}"


def lock_key(user_id: int) -> str:
    """Cache key that allows one real run per user at a time."""
    return f"bulk_show_plays:lock:{user_id}"


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_options(data) -> tuple[PlayOptions | None, str]:
    """Validate posted options. Returns ``(options, "")`` or ``(None, error)``."""
    scope = data.get("scope", "")
    existing = data.get("existing", "skip")
    date_mode = data.get("date_mode", "")
    if scope not in SCOPES:
        return None, "Choose which episodes to add."
    if existing not in EXISTING_MODES:
        return None, "Choose how to treat episodes that already have plays."
    if date_mode not in DATE_MODES:
        return None, "Choose how to date the plays."

    options = PlayOptions(scope=scope, existing=existing, date_mode=date_mode)

    if scope == "seasons":
        options.season_from = _int_or_none(data.get("season_from"))
        options.season_to = _int_or_none(data.get("season_to"))
        if options.season_from is None or options.season_to is None:
            return None, "Enter the first and last season."
        if options.season_from < 0 or options.season_from > options.season_to:
            return None, "The first season must not be after the last."

    now = timezone.now()
    if date_mode == "one_date":
        options.start = options.end = bulk_episode_tracking.coerce_episode_datetime(
            data.get("date"),
        )
        if options.start is None:
            return None, "Pick a date."
        if options.start > now:
            return None, "Pick today or an earlier date."
    elif date_mode == "range":
        options.start = bulk_episode_tracking.coerce_episode_datetime(
            data.get("start_date"),
        )
        options.end = bulk_episode_tracking.coerce_episode_datetime(
            data.get("end_date"),
        )
        if options.start is None or options.end is None:
            return None, "Pick a start and an end date."
        if options.start > options.end:
            return None, "The start date must not be after the end date."
        if options.end > now:
            return None, "Pick an end date of today or earlier."

    return options, ""


def route_for_item(item: Item) -> tuple[str, str | None] | None:
    """Return ``(route_media_type, identity_media_type)`` or None if unsupported."""
    if item.media_type == MediaTypes.ANIME.value:
        return MediaTypes.ANIME.value, None
    if item.media_type == MediaTypes.TV.value:
        if item.library_media_type == MediaTypes.ANIME.value:
            return MediaTypes.ANIME.value, MediaTypes.TV.value
        return MediaTypes.TV.value, None
    return None


def build_domain(user, item: Item, route: str):
    """Build the episode domain the single-show form would build for this item."""
    base_metadata = services.get_media_metadata(route, item.media_id, item.source)
    resolution = metadata_resolution.resolve_detail_metadata(
        user,
        item=item,
        route_media_type=route,
        media_id=item.media_id,
        source=item.source,
        base_metadata=base_metadata,
    )
    return bulk_episode_tracking.build_episode_play_domain(
        user,
        route,
        item.source,
        item.media_id,
        metadata_item=item,
        base_metadata=base_metadata,
        metadata_resolution_result=resolution,
    )


def _watched_seasons(user, item: Item) -> set[int] | None:
    """Seasons the user's own status says were watched; None means every season."""
    model = bulk_actions._media_model_for_item(item)
    tracker = model.objects.filter(user=user, item=item).first() if model else None
    if tracker is None:
        return set()
    if tracker.status == Status.COMPLETED.value:
        return None
    return {
        number
        for number in Season.objects.filter(
            user=user,
            related_tv__item=item,
            status=Status.COMPLETED.value,
        ).values_list("item__season_number", flat=True)
        if number is not None
    }


def select_episodes(user, item, domain, options: PlayOptions, now) -> dict:
    """Pick the episodes to add and count the ones left out, with reasons."""
    counts = {"unaired": 0, "no_date": 0, "existing": 0}
    allowed_seasons = None
    if options.scope == "watched":
        allowed_seasons = _watched_seasons(user, item)

    selected = []
    for episode in domain["episodes"]:
        season_number = episode["season_number"]
        if options.scope == "seasons":
            if not options.season_from <= season_number <= options.season_to:
                continue
        elif season_number == 0:
            continue  # Specials are only added when a season range asks for them.
        elif allowed_seasons is not None and season_number not in allowed_seasons:
            continue

        air_date = episode["air_date"]
        if air_date is None:
            counts["no_date"] += 1
            continue
        if air_date > now + timedelta(hours=12):
            counts["unaired"] += 1
            continue
        if options.existing == "skip" and episode["existing_play_count"]:
            counts["existing"] += 1
            continue
        selected.append(episode)
    return {"episodes": selected, **counts}


def process_show(user, item: Item, options: PlayOptions, *, dry_run: bool) -> dict:
    """Plan (and unless ``dry_run``, write) the plays for one show."""
    result = {
        "item_id": item.id,
        "title": item.title,
        "state": "ready",
        "add": 0,
        "existing": 0,
        "unaired": 0,
        "no_date": 0,
        "reason": "",
    }
    route = route_for_item(item)
    if route is None:
        result.update(state="skipped", reason="Not a TV show or anime.")
        return result

    try:
        domain = build_domain(user, item, route[0])
        if not domain:
            result.update(state="skipped", reason="No episodes found.")
            return result
        picked = select_episodes(user, item, domain, options, timezone.now())
        episodes = picked["episodes"]
        result.update(
            add=len(episodes),
            existing=picked["existing"],
            unaired=picked["unaired"],
            no_date=picked["no_date"],
        )
        if not episodes:
            result["state"] = "nothing"
            return result
        if dry_run:
            return result

        applied = bulk_episode_tracking.apply_bulk_episode_plays(
            user,
            domain,
            selected_episodes=episodes,
            write_mode="add",
            distribution_mode=(
                "air_date" if options.date_mode == "air_date" else "even"
            ),
            start_date=options.start,
            end_date=options.end,
        )
        result.update(state="done", add=applied.created_count)
    except Exception as error:
        logger.exception(
            "Bulk show plays failed item_id=%s user_id=%s",
            item.id,
            user.id,
        )
        result.update(state="failed", add=0, reason=str(error)[:200] or "Failed.")
    return result


def _summarise(state: dict, shows: list[dict]) -> dict:
    totals = {"shows": 0, "plays": 0, "existing": 0, "unaired": 0, "no_date": 0}
    problems = []
    samples = []
    for show in shows:
        if show["add"]:
            totals["shows"] += 1
            totals["plays"] += show["add"]
            if len(samples) < SAMPLE_SIZE:
                samples.append({"title": show["title"], "add": show["add"]})
        for key in ("existing", "unaired", "no_date"):
            totals[key] += show[key]
        if show["state"] in {"failed", "skipped"}:
            problems.append(show)
    state["totals"] = totals
    state["samples"] = samples
    state["problem_count"] = len(problems)
    state["problems"] = [
        {"title": p["title"], "state": p["state"], "reason": p["reason"]}
        for p in problems[:MAX_LISTED_PROBLEMS]
    ]
    return state


def run(user, item_ids: list[int], options: PlayOptions, operation_id: str, *, dry_run):
    """Process every selected show, publishing progress for the status endpoint."""
    key = status_key(user.id, operation_id)
    items_by_id = Item.objects.in_bulk(item_ids)
    state = {
        "state": "running",
        "dry_run": dry_run,
        "total": len(item_ids),
        "done": 0,
    }
    shows: list[dict] = []
    try:
        for item_id in item_ids:
            item = items_by_id.get(item_id)
            if item is None:
                shows.append(
                    {
                        "item_id": item_id,
                        "title": "Unknown item",
                        "state": "skipped",
                        "add": 0,
                        "existing": 0,
                        "unaired": 0,
                        "no_date": 0,
                        "reason": "Item not found.",
                    },
                )
            else:
                shows.append(process_show(user, item, options, dry_run=dry_run))
            state["done"] = len(shows)
            cache.set(key, _summarise(dict(state), shows), STATUS_TTL)
            if not dry_run:
                cache.set(lock_key(user.id), operation_id, LOCK_TTL)
        state["state"] = "done"
        cache.set(key, _summarise(dict(state), shows), STATUS_TTL)
    except Exception:
        state["state"] = "error"
        cache.set(key, _summarise(dict(state), shows), STATUS_TTL)
        raise
    finally:
        if not dry_run and cache.get(lock_key(user.id)) == operation_id:
            cache.delete(lock_key(user.id))
    return state
