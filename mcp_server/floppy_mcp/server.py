"""Floppy MCP server.

Wraps the Floppy REST API (src/api/) with a small set of agent-shaped
tools rather than a 1:1 mapping of every REST route. Each tool fans out to
one or more underlying endpoints. Configure via FLOPPY_URL and
FLOPPY_TOKEN environment variables (see client.py).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import FloppyAPIError, FloppyConfigError, get_client

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
    except (FloppyAPIError, FloppyConfigError) as exc:
        return _error_payload(exc)


# The REST API's wire format for status is a numeric code, not the display
# name (see api/helpers.py MEDIA_STATUS_MAP) — translate for ergonomics.
_STATUS_CODES = {
    "Planning": 0,
    "In progress": 1,
    "Paused": 2,
    "Completed": 3,
    "Dropped": 4,
}


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
    path = f"media/{media_type}/{source}/{media_id}"
    if season_number is not None:
        path += f"/{season_number}"
        if episode_number is not None:
            path += f"/{episode_number}"
    return await _call("get", path)


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


@mcp.tool()
async def track_media(
    media_type: str,
    source: str,
    media_id: str,
    status: str | None = None,
    score: float | None = None,
    progress: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
    new_play: bool = False,  # noqa: FBT001, FBT002
) -> Any:
    """Start tracking a media item, or update it if already tracked.

    status is one of "Completed", "In progress", "Planning", "Paused",
    "Dropped". score is 0-10. Only pass the fields you want to set. Set
    new_play=True to append a separate consumption instead of updating an
    existing one.

    progress is always the value for THIS ONE tracked entry, never a sum
    across a user's other entries for the same item (each response also
    carries progress_scope="entry" for clarity). Its unit depends on
    media_type: minutes for games, episodes for tv/season/anime, plays for
    boardgame/music, percentage/pages/chapters for book/manga/comic
    depending on the user's preference and format, seconds for podcast.
    Each response's progress_unit field states the unit actually in use;
    check it rather than assuming from media_type alone.
    """
    try:
        status_code = _status_code(status)
    except ValueError as exc:
        return {"error": True, "detail": str(exc)}
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
        and not existing.get("error")
        and existing.get("tracked")
        and not new_play
    ):
        if status_code == _STATUS_CODES["Completed"]:
            for consumption in existing.get("consumptions") or []:
                if consumption.get("status") in {"Planning", "In progress", 0, 1}:
                    return await _call(
                        "patch",
                        f"media/{media_type}/{source}/{media_id}/history/"
                        f"{consumption['consumption_id']}",
                        json=body,
                    )
        return await _call(
            "patch",
            f"media/{media_type}/{source}/{media_id}",
            json=body,
        )
    body["media_id"] = media_id
    return await _call("post", f"media/{media_type}", json=body)


@mcp.tool()
async def untrack_media(
    media_type: str,
    source: str,
    media_id: str,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> Any:
    """Remove a tracked media item (or a specific season/episode) from the library."""
    path = f"media/{media_type}/{source}/{media_id}"
    if season_number is not None:
        path += f"/{season_number}"
        if episode_number is not None:
            path += f"/{episode_number}"
    return await _call("delete", path)


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
    path = f"media/{media_type}/{source}/{media_id}"
    if season_number is not None:
        path += f"/{season_number}"
    return await _call("post", f"{path}/progress", json={"operation": operation})


@mcp.tool()
async def log_episode_play(
    source: str,
    media_id: str,
    season_number: int,
    episode_number: int,
    end_date: str | None = None,
) -> Any:
    """Record a watch of a TV episode (creates the show/season if needed)."""
    return await _call(
        "post",
        f"media/tv/{source}/{media_id}/{season_number}/episodes/{episode_number}/watch",
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
async def manage_settings(action: str, **fields: Any) -> Any:
    """Read or update the user's preferences.

    action: "get" (returns current values and valid choices) or "update"
    (pass preference fields as kwargs, e.g. rating_scale="0-10").
    """
    if action == "get":
        return await _call("get", "user/preferences")
    if action == "update":
        return await _call("patch", "user/preferences", json=fields)
    return {"error": True, "detail": f"Unknown action: {action}"}


def main() -> None:
    """Entry point for `python -m floppy_mcp.server` / console script."""
    mcp.run()


if __name__ == "__main__":
    main()
