"""Floppy MCP server.

Wraps the Floppy REST API (src/api/) with a small set of agent-shaped
tools rather than a 1:1 mapping of every REST route. Each tool fans out to
one or more underlying endpoints. Configure via FLOPPY_URL and
FLOPPY_TOKEN environment variables (see client.py).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP

from .client import (
    FloppyAPIError,
    FloppyConfigError,
    fetch_public_contract,
    get_client,
)
from .resolve import resolve_candidates

mcp = FastMCP(
    name="floppy",
    instructions=(
        "Tools for tracking movies, TV, anime, manga, books, comics, games, "
        "board games, music, and podcasts in a user's Floppy library, plus "
        "custom lists, history, statistics, and account settings. Call "
        "search_media before track_media when you don't already have a "
        "known source/media_id — track_media requires exact identifiers."
    ),
)


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, FloppyAPIError):
        return {"error": True, "status_code": exc.status_code, "detail": exc.detail}
    if isinstance(exc, FloppyConfigError):
        return {"error": True, "detail": str(exc)}
    return {"error": True, "detail": str(exc)}


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await get_client().request(method, path, **kwargs)
    except (FloppyAPIError, FloppyConfigError, httpx.RequestError) as exc:
        return _error_payload(exc)


@mcp.resource("floppy://domain-context")
async def domain_context() -> str:
    """Return the instance's JSON-LD domain context.

    Optional grounding aid: it types Floppy's own nouns (Item, Consumption,
    Media type, Celery queue) and maps them to schema.org where an equivalent
    exists. No tool reads this resource, so an instance that cannot serve it
    still supports every tool - a fetch failure returns a structured error
    here and nowhere else.
    """
    try:
        return await fetch_public_contract("api/context.jsonld")
    except (FloppyAPIError, FloppyConfigError, httpx.RequestError) as exc:
        return json.dumps(_error_payload(exc))


# The REST API's wire format for status is a numeric code, not the display
# name (see api/helpers.py MEDIA_STATUS_MAP) — translate for ergonomics.
_STATUS_CODES = {
    "Planning": 0,
    "In progress": 1,
    "Paused": 2,
    "Completed": 3,
    "Dropped": 4,
}


_STATUS_NAMES = {code: name for name, code in _STATUS_CODES.items()}
MAX_SCORE = 10


def _status_code(status: str | None) -> int | None:
    if status is None:
        return None
    if status in _STATUS_CODES:
        return _STATUS_CODES[status]
    msg = f"Invalid status {status!r}; choices: {sorted(_STATUS_CODES)}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Discovery & search
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_media(media_type: str, query: str, page: int = 1) -> Any:
    """Search a provider for media to track.

    media_type: one of tv, movie, anime, manga, game, book, comic,
    boardgame, music, podcast, comicissue.
    Returns provider results including the source and media_id needed by
    track_media. For games, each result also includes "platforms" and
    "year" so you can pick the right release (e.g. the GameCube version vs.
    a remaster) without a follow-up get_media call. If a title is ambiguous
    across platforms, prefer showing the candidates to the user over
    guessing one.
    """
    return await _call(
        "get",
        f"search/{media_type}",
        params={"search": query, "page": page},
    )


def _search_failure(error: dict[str, Any]) -> dict[str, Any]:
    """Tag a failed provider search so an outage never reads as "no such game"."""
    code = error.get("status_code")
    detail = str(error.get("detail", "")).lower()
    if code is None:
        kind = "unreachable"
    elif code == httpx.codes.INTERNAL_SERVER_ERROR and "lookup failed" in detail:
        kind = "provider_unavailable"
    elif code in {httpx.codes.BAD_REQUEST, httpx.codes.FORBIDDEN}:
        kind = "invalid_input" if code == httpx.codes.BAD_REQUEST else "forbidden"
    else:
        kind = "backend_error"
    return {**error, "error_kind": kind}


@mcp.tool()
async def resolve_game(
    title: str,
    platform: str | None = None,
    year: int | None = None,
    year_to: int | None = None,
    aliases: list[str] | None = None,
) -> Any:
    """Resolve a game title + optional platform/year to an exact source/media_id.

    The source and media_id are what track_media, get_media and get_history
    take. Optional helper over search_media (which is unchanged): use it when you
    have a title and constraints instead of an ID. year_to makes year a range
    (an era); aliases are alternate titles to search too. Platform accepts
    provider names or common short forms (N64, GC, DS, 3DS, PS2, PC, ...).

    Returns {"status", "selected", "likely", "candidates"}:
    - "exact": one candidate fits every constraint you gave, backed by
      provider data. "selected" is {source, media_id}; pass them on directly.
    - "likely": one candidate fits but a constraint is unknown in the
      catalog or the title only partly matches. "likely" holds it; confirm.
    - "ambiguous": several fit. Show "candidates" to the user, do not guess.
    - "no_match": nothing fits; "candidates" holds near misses. This means
      the search found no such release, not that the game is untracked.
    Each candidate carries source, media_id, title, year, platforms,
    "evidence" (title exact/partial; platform and year true/false/null where
    null means the catalog has no data; edition_words found in the title)
    and the "original" search result. The catalog does not say whether a
    release is a port, remaster or remake: edition_words is a hint, not a
    verdict. A provider outage returns {"error": true, "error_kind":
    "provider_unavailable"} instead of a result, so retry rather than
    concluding the game does not exist.
    """
    results: list[dict[str, Any]] = []
    media_type = "game"
    for name in dict.fromkeys([title, *(aliases or [])]):
        found = await _call(
            "get",
            f"search/{media_type}",
            params={"search": name, "limit": 50},
        )
        if isinstance(found, dict) and found.get("error"):
            return _search_failure(found)
        results.extend((found or {}).get("results") or [])
    return resolve_candidates(results, title, aliases, platform, year, year_to)


@mcp.tool()
async def search_tracked_media(query: str) -> Any:
    """Search the user's own tracked library by title (not a provider search)."""
    return await _call("get", "media", params={"search": query})


@mcp.tool()
async def get_discover(media_type: str | None = None) -> Any:
    """Return personalized Discover recommendation rows for a media type."""
    return await _call("get", "discover", params={"media_type": media_type})


@mcp.tool()
async def get_home() -> Any:
    """Return the user's home-page rows (continue watching, per-type lists, etc.)."""
    return await _call("get", "home")


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_media(
    media_type: str,
    source: str,
    media_id: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> Any:
    """Get details for one media item (and season/episode if given).

    For a season, pass season_number; for an episode, pass both
    season_number and episode_number. media_type/source/media_id always
    describe the parent show for seasons/episodes.
    """
    if season_number is None:
        return await _call("get", f"media/{media_type}/{source}/{media_id}")
    if episode_number is None:
        return await _call(
            "get",
            f"media/{media_type}/{source}/{media_id}/{season_number}",
        )
    return await _call(
        "get",
        f"media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}",
    )


@mcp.tool()
async def get_media_state(
    media_type: str,
    source: str,
    media_id: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> Any:
    """Say whether an item exists, is tracked, and list every play.

    Returns resolved, tracked and consumptions (each with a stable
    consumption_id). A valid but untracked item is a normal 200 with
    tracked=false and consumptions=[]; use this before track_media or
    before adding a play. An error with code MEDIA_NOT_FOUND means the
    id is invalid; PROVIDER_UNAVAILABLE means the lookup failed and can
    be retried. For a season or episode pass season_number (and
    episode_number) with the parent show's identifiers.
    """
    if season_number is None:
        return await _call("get", f"media/{media_type}/{source}/{media_id}/state")
    if episode_number is None:
        return await _call(
            "get",
            f"media/{media_type}/{source}/{media_id}/{season_number}/state",
        )
    return await _call(
        "get",
        f"media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}/state",
    )


@mcp.tool()
async def list_tracked_media(
    media_type: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> Any:
    """List the user's tracked library, optionally filtered by type/status."""
    if media_type:
        return await _call(
            "get",
            f"media/{media_type}",
            params={"status": status, "sort": sort, "limit": limit, "offset": offset},
        )
    return await _call(
        "get",
        "media",
        params={
            "media_type": media_type,
            "status": status,
            "sort": sort,
            "limit": limit,
            "offset": offset,
        },
    )


_TrackMediaType = Literal[
    "tv",
    "movie",
    "anime",
    "manga",
    "game",
    "book",
    "comic",
    "boardgame",
    "music",
    "podcast",
    "comicissue",
    "season",
    "episode",
]
_TrackStatus = Literal["Planning", "In progress", "Paused", "Completed", "Dropped"]
_TrackMode = Literal["auto", "new_play", "update"]

# Statuses where the server may have committed before the response was lost.
_UNCERTAIN_STATUSES = {
    499,
    httpx.codes.BAD_GATEWAY,
    httpx.codes.GATEWAY_TIMEOUT,
}
_APPLIED_FIELDS = (
    "status",
    "score",
    "progress",
    "progress_unit",
    "progress_scope",
    "start_date",
    "end_date",
)


def _parse_when(name: str, value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        msg = (
            f"Invalid {name} {value!r}; use ISO 8601, e.g. 2019-03-07 or "
            "2019-03-07T21:30:00+00:00"
        )
        raise ValueError(msg) from None


def _validate_track_input(
    score: float | None,
    progress: int | None,
    start_date: str | None,
    end_date: str | None,
) -> str | None:
    """Return a human-readable problem, or None when the input is coherent."""
    try:
        start = _parse_when("start_date", start_date) if start_date else None
        end = _parse_when("end_date", end_date) if end_date else None
    except ValueError as exc:
        return str(exc)
    if (
        start
        and end
        and (start.tzinfo is None) == (end.tzinfo is None)
        and start > end
    ):
        return f"start_date {start_date!r} is after end_date {end_date!r}"
    if progress is not None and progress < 0:
        return f"progress must be >= 0, got {progress}"
    if score is not None and not 0 <= score <= MAX_SCORE:
        return f"score must be between 0 and {MAX_SCORE}, got {score}"
    return None


def _classify_write_error(error: dict[str, Any]) -> dict[str, Any]:
    """Tag a failed write with its kind and whether it may have been applied."""
    code = error.get("status_code")
    detail_text = json.dumps(error.get("detail", "")).lower()
    if code is None:
        # No HTTP response. A refused connection never reached the server; a
        # timeout or dropped connection may have been committed.
        kind, state = (
            ("unreachable", "not_applied")
            if error.get("connect_failed")
            else ("unknown_write_outcome", "uncertain")
        )
    elif code in _UNCERTAIN_STATUSES:
        kind, state = "unknown_write_outcome", "uncertain"
    elif code == httpx.codes.SERVICE_UNAVAILABLE or "locked" in detail_text:
        kind, state = "busy", "not_applied"
    elif code in {httpx.codes.BAD_REQUEST, httpx.codes.UNPROCESSABLE_ENTITY}:
        kind, state = "invalid_input", "not_applied"
    elif code == httpx.codes.NOT_FOUND:
        kind, state = "not_found", "not_applied"
    elif code == httpx.codes.CONFLICT:
        kind, state = "conflict", "not_applied"
    else:
        kind, state = "backend_error", "uncertain"
    error.pop("connect_failed", None)
    return {**error, "error_kind": kind, "write_state": state}


async def _write(method: str, path: str, **kwargs: Any) -> Any:
    """Like _call, but flags transport failures that may have committed."""
    try:
        return await get_client().request(method, path, **kwargs)
    except httpx.ConnectError as exc:
        payload = _error_payload(exc)
        payload["connect_failed"] = True
        return payload
    except (FloppyAPIError, FloppyConfigError, httpx.RequestError) as exc:
        return _error_payload(exc)


def _verify_ref(
    media_type: str,
    source: str,
    media_id: str,
    consumption_id: int | None,
) -> dict[str, Any]:
    return {
        "get_media": {
            "media_type": media_type,
            "source": source,
            "media_id": media_id,
        },
        "history_path": f"/api/v1/media/{media_type}/{source}/{media_id}/history/",
        "consumption_id": consumption_id,
        "note": (
            "Read the history list and match consumption_id (or the dates/"
            "progress you sent) to confirm exactly what was written."
        ),
    }


def _same_play(consumption: dict[str, Any], body: dict[str, Any]) -> bool:
    """Report whether a consumption already carries the requested play."""
    if not any(k in body for k in ("start_date", "end_date")):
        return False  # nothing identifies a play without dates
    for field in ("start_date", "end_date", "progress"):
        if field in body and not _matches(consumption.get(field), body[field]):
            return False
    return "status" not in body or consumption.get("status") in {
        body["status"],
        _STATUS_NAMES.get(body["status"]),
    }


def _matches(have: Any, want: Any) -> bool:
    if have == want:
        return True
    if isinstance(have, str) and isinstance(want, str):
        try:
            a, b = datetime.fromisoformat(have), datetime.fromisoformat(want)
        except ValueError:
            return False
        if len(want) == len("2020-01-01"):
            # A bare date matches any stored timestamp on that calendar day.
            return a.date() == b.date()
        if (a.tzinfo is None) != (b.tzinfo is None):
            return False
        return a == b
    return False


def _envelope(
    response: Any,
    outcome: str,
    media: tuple[str, str, str],
    consumption_id: int | None,
    **extra: Any,
) -> Any:
    if not isinstance(response, dict):
        response = {"result": response}
    if consumption_id is None:
        consumption_id = response.get("consumption_id")
    operation = {
        "outcome": outcome,
        "identity": dict(zip(("media_type", "source", "media_id"), media, strict=True)),
        "consumption_id": consumption_id,
        "applied": {k: response[k] for k in _APPLIED_FIELDS if k in response},
        "verify": _verify_ref(*media, consumption_id),
        **extra,
    }
    return {**response, "operation": operation}


@mcp.tool()
async def track_media(  # noqa: C901, PLR0911, PLR0912
    media_type: _TrackMediaType,
    source: str,
    media_id: str,
    status: _TrackStatus | None = None,
    score: float | None = None,
    progress: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
    new_play: bool = False,  # noqa: FBT001, FBT002
    mode: _TrackMode = "auto",
    skip_if_duplicate: bool = False,  # noqa: FBT001, FBT002
) -> Any:
    """Start tracking a media item, or update it if already tracked.

    status is one of "Completed", "In progress", "Planning", "Paused",
    "Dropped". score is 0-10. Only pass the fields you want to set.

    mode chooses between a NEW consumption and editing the current one:
    "auto" (default) updates a tracked item and creates an untracked one;
    "new_play" always appends a separate consumption (same as
    new_play=True); "update" only edits and refuses if nothing is tracked.

    start_date/end_date are ISO 8601 (2019-03-07 or a full timestamp) and
    are stored as given, so historical plays stay historical. They are
    validated before anything is written.

    progress is always the value for THIS ONE tracked entry, never a sum
    across a user's other entries for the same item (each response also
    carries progress_scope="entry" for clarity). Its unit depends on
    media_type: minutes for games, episodes for tv/season/anime,
    plays for boardgame/music, percentage/pages/chapters for book/manga/comic
    depending on the user's preference and format, minutes for podcast.
    Each response's progress_unit field states the unit actually in use;
    check it rather than assuming from media_type alone.

    Every success result keeps the API body and adds "operation":
    outcome (created | appended | updated | skipped), identity,
    consumption_id, applied (status/progress/progress_unit/dates as
    returned) and verify (where to read the entry back).

    Failures carry error_kind (invalid_input, not_found, conflict, busy,
    unreachable, backend_error, unknown_write_outcome) and write_state
    (not_applied | uncertain). unknown_write_outcome means a timeout or
    gateway error: the write MAY have committed, so do not blindly retry.
    Read the verify reference first, or retry with skip_if_duplicate=True
    plus start_date/end_date, which skips the POST when a consumption with
    the same dates, progress and status already exists. That check is
    best-effort (read, then write), not a server-side lock.
    """
    new_play = new_play or mode == "new_play"
    if new_play and mode == "update":
        return {
            "error": True,
            "error_kind": "invalid_input",
            "write_state": "not_applied",
            "detail": 'new_play=True conflicts with mode="update"',
        }
    try:
        status_code = _status_code(status)
    except ValueError as exc:
        return {
            "error": True,
            "error_kind": "invalid_input",
            "write_state": "not_applied",
            "detail": str(exc),
        }
    problem = _validate_track_input(score, progress, start_date, end_date)
    if problem:
        return {
            "error": True,
            "error_kind": "invalid_input",
            "write_state": "not_applied",
            "detail": problem,
        }
    media = (media_type, source, media_id)
    body = {
        "source": source,
        "status": status_code,
        "score": score,
        "progress": progress,
        "start_date": start_date,
        "end_date": end_date,
        "notes": notes,
    }
    body = {k: v for k, v in body.items() if v is not None}
    # media/{type}/{source}/{id} resolves provider metadata for ANY known
    # item, tracked or not — it 200s even when nothing is tracked yet (it
    # returns {"tracked": False, "id": None, ...} in that case). Checking
    # only "did the GET error" therefore always looked truthy and this
    # always PATCHed, even for brand-new items, which the API 404s on.
    # The correct signal for "does a consumption record already exist" is
    # the `tracked` flag (or a non-null `id`), not just GET success.
    existing = await _call("get", f"media/{media_type}/{source}/{media_id}")
    if (
        isinstance(existing, dict)
        and existing.get("error")
        and not (
            existing.get("status_code") == httpx.codes.NOT_FOUND
            or (
                source == "manual"
                and existing.get("status_code") == httpx.codes.INTERNAL_SERVER_ERROR
            )
        )
    ):
        return existing
    tracked = (
        isinstance(existing, dict)
        and not existing.get("error")
        and bool(existing.get("tracked"))
    )
    consumptions = (existing.get("consumptions") or []) if tracked else []
    if mode == "update" and not tracked:
        return {
            "error": True,
            "error_kind": "not_found",
            "write_state": "not_applied",
            "detail": 'mode="update" but this item is not tracked yet',
        }
    if tracked and not new_play:
        if status_code == _STATUS_CODES["Completed"]:
            for consumption in consumptions:
                if consumption.get("status") in {"Planning", "In progress", 0, 1}:
                    consumption_id = consumption["consumption_id"]
                    result = await _write(
                        "patch",
                        f"media/{media_type}/{source}/{media_id}/history/{consumption_id}",
                        json=body,
                    )
                    if isinstance(result, dict) and result.get("error"):
                        return {
                            **_classify_write_error(result),
                            "verify": _verify_ref(*media, consumption_id),
                        }
                    return _envelope(
                        result,
                        "updated",
                        media,
                        consumption_id,
                        consumption_target="pending_consumption",
                    )
        result = await _write(
            "patch",
            f"media/{media_type}/{source}/{media_id}",
            json=body,
        )
        if isinstance(result, dict) and result.get("error"):
            return {
                **_classify_write_error(result),
                "verify": _verify_ref(*media, None),
            }
        return _envelope(result, "updated", media, None, consumption_target="current")
    if skip_if_duplicate and new_play:
        for consumption in consumptions:
            if _same_play(consumption, body):
                return _envelope(
                    consumption,
                    "skipped",
                    media,
                    consumption.get("consumption_id"),
                    reason="an identical consumption already exists",
                )
    body["media_id"] = media_id
    result = await _write("post", f"media/{media_type}", json=body)
    if isinstance(result, dict) and result.get("error"):
        return {**_classify_write_error(result), "verify": _verify_ref(*media, None)}
    return _envelope(result, "appended" if tracked else "created", media, None)


@mcp.tool()
async def untrack_media(
    media_type: str,
    source: str,
    media_id: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> Any:
    """Remove a tracked media item (or a specific season/episode) from the library."""
    if season_number is None:
        return await _call("delete", f"media/{media_type}/{source}/{media_id}")
    if episode_number is None:
        return await _call(
            "delete",
            f"media/{media_type}/{source}/{media_id}/{season_number}",
        )
    return await _call(
        "delete",
        f"media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}",
    )


@mcp.tool()
async def update_progress(
    media_type: str,
    source: str,
    media_id: str,
    operation: str,
    season_number: int | None = None,
) -> Any:
    """Increase or decrease progress by one step (operation: "increase"|"decrease").

    For TV shows, pass season_number to advance/rewind that season's next
    episode; omit it for movies, games, books, etc. The step size is not
    always 1: games step by 30 minutes, and book/manga/comic step by one
    percentage point when percentage tracking is on. To log an exact
    duration or amount instead of stepping, use track_media with an
    explicit progress value (and new_play=True for a fresh session).
    """
    if season_number is not None:
        return await _call(
            "post",
            f"media/{media_type}/{source}/{media_id}/{season_number}/progress",
            json={"operation": operation},
        )
    return await _call(
        "post",
        f"media/{media_type}/{source}/{media_id}/progress",
        json={"operation": operation},
    )


@mcp.tool()
async def log_episode_play(
    source: str,
    media_id: str,
    season_number: int,
    episode_number: int,
    end_date: str | None = None,
) -> Any:
    """Record a watch of a TV episode (creates the show/season if needed)."""
    media_type = "tv"
    return await _call(
        "post",
        f"media/{media_type}/{source}/{media_id}/{season_number}/episodes/{episode_number}/watch",
        json={"end_date": end_date} if end_date else {},
    )


@mcp.tool()
async def log_song_play(
    album_id: int,
    track_id: int | None = None,
    recording_id: str | None = None,
    end_date: str | None = None,
) -> Any:
    """Record a listen for a song on a music album."""
    body = {
        "album_id": album_id,
        "track_id": track_id,
        "recording_id": recording_id,
        "end_date": end_date,
    }
    return await _call(
        "post",
        "music/songs/plays",
        json={k: v for k, v in body.items() if v is not None},
    )


@mcp.tool()
async def log_podcast_play(
    show_id: int,
    episode_id: int | None = None,
    episode_uuid: str | None = None,
    end_date: str | None = None,
) -> Any:
    """Record a play for a podcast episode."""
    body = {
        "show_id": show_id,
        "episode_id": episode_id,
        "episode_uuid": episode_uuid,
        "end_date": end_date,
    }
    return await _call(
        "post",
        "podcasts/episodes/plays",
        json={k: v for k, v in body.items() if v is not None},
    )


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_custom_lists() -> Any:
    """List the user's custom lists."""
    return await _call("get", "lists")


@mcp.tool()
async def manage_list(  # noqa: PLR0911 — action dispatch, one return per action
    action: str,
    list_id: int | None = None,
    name: str | None = None,
    description: str | None = None,
    media_type: str | None = None,
    source: str | None = None,
    media_id: str | None = None,
) -> Any:
    """Create/rename/delete a list, or add/remove a tracked media item.

    action: "create" (needs name), "rename" (needs list_id, name),
    "delete" (needs list_id), "list_items" (needs list_id), "add_item"
    (needs list_id, media_type, source, media_id — the item must already
    be tracked via track_media), "remove_item" (same as add_item).
    """
    if action == "create":
        return await _call(
            "post",
            "lists",
            json={"name": name, "description": description},
        )
    if action == "rename":
        return await _call(
            "patch",
            f"lists/{list_id}",
            json={"name": name, "description": description},
        )
    if action == "delete":
        return await _call("delete", f"lists/{list_id}")
    if action == "list_items":
        return await _call("get", f"lists/{list_id}/items")
    if action == "add_item":
        return await _call(
            "put",
            f"media/{media_type}/{source}/{media_id}/lists/{list_id}",
            json={},
        )
    if action == "remove_item":
        return await _call(
            "delete",
            f"media/{media_type}/{source}/{media_id}/lists/{list_id}",
        )
    return {"error": True, "detail": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@mcp.tool()
async def manage_tags(  # noqa: PLR0911 — action dispatch, one return per action
    action: str,
    tag_id: int | None = None,
    name: str | None = None,
    media_type: str | None = None,
    source: str | None = None,
    media_id: str | None = None,
    tag_ids: list[int] | None = None,
) -> Any:
    """Create/rename/delete tags, or read/replace tags on a media item.

    action: "list" (all tags), "create" (needs name), "rename" (needs
    tag_id, name), "delete" (needs tag_id), "get_for_item" (needs
    media_type/source/media_id), "set_for_item" (needs
    media_type/source/media_id, tag_ids).
    """
    if action == "list":
        return await _call("get", "tags")
    if action == "create":
        return await _call("post", "tags", json={"name": name})
    if action == "rename":
        return await _call("patch", f"tags/{tag_id}", json={"name": name})
    if action == "delete":
        return await _call("delete", f"tags/{tag_id}")
    if action == "get_for_item":
        return await _call("get", f"media/{media_type}/{source}/{media_id}/tags")
    if action == "set_for_item":
        return await _call(
            "put",
            f"media/{media_type}/{source}/{media_id}/tags",
            json={"tag_ids": tag_ids or []},
        )
    return {"error": True, "detail": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# History & statistics
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_history(
    media_type: str | None = None,
    genre: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> Any:
    """Return the day-grouped consumption timeline, optionally filtered."""
    return await _call(
        "get",
        "history",
        params={
            "media_type": media_type,
            "genre": genre,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        },
    )


@mcp.tool()
async def get_statistics(
    start_date: str | None = None,
    end_date: str | None = None,
) -> Any:
    """Return the full statistics dashboard payload for a date range.

    Pass start_date="all" and end_date="all" for All Time. Omit both to use
    the user's preferred default range.
    """
    return await _call(
        "get",
        "statistics/overview",
        params={"start_date": start_date, "end_date": end_date},
    )


# ---------------------------------------------------------------------------
# Imports & account
# ---------------------------------------------------------------------------


@mcp.tool()
async def run_import(
    service: str,
    username: str | None = None,
    mode: str = "new",
) -> Any:
    """Queue a one-off library import from an already-connected username-based service.

    service: one of mal, anilist, kitsu, steam. mode: "new" (only sync new
    items) or "overwrite" (sync new and overwrite existing). Returns a
    task_id — poll get_task_status to see when it's done. File-based imports
    (CSV uploads) aren't available through this tool.
    """
    return await _call(
        "post",
        f"imports/{service}",
        json={"username": username, "mode": mode},
    )


@mcp.tool()
async def get_task_status(task_id: str) -> Any:
    """Check the status of a background task (import, bulk play, sync, etc.)."""
    return await _call("get", f"tasks/{task_id}")


@mcp.tool()
async def manage_settings(action: str, fields: dict[str, Any] | None = None) -> Any:
    """Read or update the user's preferences.

    action: "get" (returns current values and valid choices) or "update"
    (pass a fields object, e.g. {"rating_scale": "0-10"}).
    """
    if action == "get":
        return await _call("get", "user/preferences")
    if action == "update":
        return await _call("patch", "user/preferences", json=fields or {})
    return {"error": True, "detail": f"Unknown action: {action}"}


def main() -> None:
    """Entry point for `python -m floppy_mcp.server` / console script."""
    mcp.run()


if __name__ == "__main__":
    main()
