from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.translation import gettext

from app.models import MediaTypes

if TYPE_CHECKING:
    from app.columns import ColumnDef

DATE_COLUMNS = {
    "date_added",
    "end_date",
    "last_watched",
    "next_episode_air_date",
    "release_date",
    "album_date_added",
    "album_release_date",
    "artist_date_added",
    "artist_end_date",
    "artist_release_date",
    "artist_start_date",
    "start_date",
}

ASCENDING_SORTS = {
    "author",
    "media_type",
    "next_episode_air_date",
    "platform",
    "popularity",
    "release_date",
    "runtime",
    "start_date",
    "tier",
    "time_left",
    "time_to_beat",
    "title",
}

CENTER_COLUMNS = {
    "album_score",
    "album_status",
    "artist_score",
    "artist_status",
    "critic_rating",
    "episodes_left",
    "last_watched",
    "media_type",
    "next_episode_air_date",
    "platform",
    "popularity",
    "progress",
    "runtime",
    "score",
    "status",
    "time_left",
    "time_to_beat",
    "time_watched",
    "user_rating",
    "album_date_added",
    "album_release_date",
    "artist_date_added",
    "artist_end_date",
    "artist_release_date",
    "artist_start_date",
    "date_added",
    "end_date",
    "release_date",
    "start_date",
}

WIDE_COLUMNS = {"album_title", "artist_name", "title"}

LABELS = {
    "image": "",
    "title": "Title",
    "author": "Author",
    "channel": "Channel",
    "media_type": "Media Type",
    "score": "Score",
    "critic_rating": "Critic Rating",
    "progress": "Progress",
    "episodes_left": "Episodes Left",
    "time_left": "Time Left",
    "time_to_beat": "Time to Beat",
    "runtime": "Runtime",
    "time_watched": "Time Watched",
    "popularity": "Popularity",
    "user_rating": "User Rating",
    "platform": "Platform",
    "last_watched": "Last Watched",
    "genres": "Genres",
    "tags": "Tags",
    "status": "Status",
    "release_date": "Release Date",
    "next_episode_air_date": "Episode Air Date",
    "date_added": "Date Added",
    "start_date": "Start Date",
    "end_date": "End Date",
    "entry_source": "Source",
    "notes": "Notes",
    "synopsis": "Description",
    "artist_name": "Artist",
    "album_title": "Album",
    "album_artist": "Artist",
    "album_score": "Score",
    "album_status": "Status",
    "album_release_date": "Release Date",
    "album_date_added": "Date Added",
    "artist_score": "Score",
    "artist_status": "Status",
    "artist_release_date": "Release Date",
    "artist_date_added": "Date Added",
    "artist_start_date": "Start Date",
    "artist_end_date": "End Date",
}


def _first(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _tracker(row):
    return (
        getattr(row, "_source_media", None)
        or getattr(row, "media", None)
        or row
    )


def _item(row, tracker):
    holder = getattr(row, "item", None)
    item = getattr(holder, "item", holder)
    return item or getattr(tracker, "item", None)


def _attr(*objects, name):
    for obj in objects:
        if obj is None:
            continue
        try:
            value = getattr(obj, name, None)
        except AttributeError:
            continue
        if value is not None:
            return value
    return None


def _date(value, user):
    if not value:
        return ""
    from users.templatetags.user_tags import user_date_format

    return str(user_date_format(value, user) or "")


def _score(value, user):
    if value is None:
        return ""
    from app.templatetags.app_tags import score_display

    return str(score_display(value, user))


def _status(value):
    from app.templatetags.app_tags import media_status_readable

    return str(media_status_readable(value))


def _media_type(media_type):
    from app.templatetags.app_tags import media_type_readable

    if not media_type:
        return ""
    try:
        return str(media_type_readable(media_type))
    except (ValueError, KeyError):
        return str(media_type)


def _entry_source(value):
    from app.templatetags.app_tags import entry_source_label

    return str(entry_source_label(value))


def _tags(item, user):
    relation = getattr(item, "item_tags", None)
    if relation is None:
        return []
    from app.templatetags.app_tags import user_tag_names

    return list(user_tag_names(relation.all(), user) or [])


def _repeat_suffix(tracker, item, user, label):
    repeats = getattr(tracker, "repeats", 1) or 1
    if repeats <= 1:
        return ""
    media_type = getattr(item, "media_type", "")
    if (
        media_type in (MediaTypes.GAME.value, MediaTypes.BOARDGAME.value)
        and getattr(user, "game_logging_style", "") == "sessions"
    ):
        return ""
    return label


def _image_cell(row, item, table_type):
    from app.templatetags.app_tags import image_url

    if table_type == "artist":
        target = getattr(row, "artist", None)
        title = getattr(target, "name", "")
    elif table_type == "album":
        target = getattr(row, "album", None)
        title = getattr(target, "title", "")
    else:
        target = item
        title = getattr(item, "title", "")
    src = getattr(target, "image", None)
    return {
        "kind": "image",
        "src": image_url(src) if src else "",
        "alt": str(title or ""),
    }


def _title_cell(row, item, table_type, public_list_reference):
    from app.templatetags.app_tags import (
        media_url,
        music_album_url,
        music_artist_url,
    )

    tracker = _tracker(row)
    if table_type == "artist":
        artist = getattr(row, "artist", None)
        return {
            "kind": "title",
            "text": str(getattr(artist, "name", "") or "-"),
            "href": music_artist_url(artist) if artist else "",
        }
    if table_type == "album":
        album = getattr(row, "album", None)
        return {
            "kind": "title",
            "text": str(getattr(album, "title", "") or "-"),
            "href": music_album_url(album) if album else "",
        }
    href = media_url(item) if item is not None else ""
    if public_list_reference and href:
        href = f"{href}?public_view=1&public_list={public_list_reference}"
    return {
        "kind": "title",
        "text": str(getattr(item, "title", "") or str(item or "-")),
        "href": href,
        "repeats": getattr(tracker, "repeats", 1) or 1,
    }


def cell_for_column(
    column: ColumnDef,
    row: Any,
    *,
    user: Any,
    table_type: str,
    media_type: str,
    public_view: bool,
    public_list_reference: str = "",
    show_public_notes: bool = True,
) -> dict[str, Any]:
    """Return the shared cell description for one column and row."""
    key = column.key
    tracker = _tracker(row)
    item = _item(row, tracker)

    if key == "image":
        return _image_cell(row, item, table_type)
    if key in {"title", "artist_name", "album_title"}:
        return _title_cell(row, item, table_type, public_list_reference)

    if key in {"author", "channel"}:
        authors = _attr(tracker, row, item, name="display_authors")
        if authors:
            return {"kind": "text", "text": ", ".join(str(author) for author in authors)}
        return {"kind": "text", "text": "-", "muted": True}

    if key == "media_type":
        value = getattr(item, "media_type", "")
        return {"kind": "text", "text": _media_type(value)}

    if key in {"score", "album_score", "artist_score"}:
        aggregated = _attr(tracker, row, item, name="aggregated_score")
        raw = aggregated if aggregated is not None else _attr(tracker, row, name="score")
        if raw is None:
            raw = _attr(tracker, name="score")
        if raw is None and not (key == "score" and getattr(tracker, "is_untracked", False)):
            return {"kind": "score", "rated": False, "text": ""}
        return {
            "kind": "score",
            "rated": raw is not None,
            "text": _score(raw, user),
            "note": _repeat_suffix(tracker, item, user, "Latest"),
        }

    if key in {"status", "album_status", "artist_status"}:
        aggregated = _attr(tracker, row, name="aggregated_status")
        raw = aggregated or _attr(tracker, row, name="status")
        if not raw and getattr(tracker, "is_statusless", False):
            return {"kind": "status", "text": "No Status", "muted": True}
        if not raw:
            return {"kind": "status", "text": "-", "muted": True}
        return {
            "kind": "status",
            "text": _status(raw),
            "note": _repeat_suffix(tracker, item, user, "Latest"),
        }

    if key == "progress":
        aggregated = _attr(tracker, name="aggregated_progress")
        progress = aggregated if aggregated is not None else _attr(tracker, name="progress")
        if progress is None:
            return {"kind": "text", "text": "-", "muted": True}
        text = _attr(tracker, name="formatted_aggregated_progress") if aggregated is not None else _attr(tracker, name="formatted_progress")
        max_progress = _attr(tracker, name="max_progress")
        max_text = ""
        if max_progress and not _attr(tracker, name="progress_is_percentage"):
            max_text = f" / {_attr(tracker, name='formatted_max_progress') or max_progress}"
        return {
            "kind": "progress",
            "text": str(text if text is not None else progress),
            "maxText": max_text,
            "note": _repeat_suffix(tracker, item, user, "Total"),
        }

    if key in {"episodes_left", "time_left"}:
        value = _attr(tracker, name="episodes_left_display" if key == "episodes_left" else "time_left_display")
        return {
            "kind": "progress",
            "text": str(value or "-"),
            "note": _repeat_suffix(tracker, item, user, "Remaining" if key == "episodes_left" else "Total"),
        }

    if key == "time_to_beat":
        return {"kind": "text", "text": str(_attr(item, name="formatted_game_time_to_beat") or "-")}

    if key == "runtime":
        return {"kind": "text", "text": str(_attr(tracker, name="formatted_total_runtime") or "-")}

    if key == "time_watched":
        return {"kind": "text", "text": str(_attr(tracker, name="formatted_time_watched") or "-")}

    if key == "popularity":
        rank = _attr(item, name="trakt_popularity_rank")
        return {"kind": "text", "text": f"#{rank}" if rank else "-", "muted": not rank}

    if key == "user_rating":
        value = _attr(item, name="igdb_user_rating")
        return {"kind": "text", "text": f"{value:.1f}" if value is not None else "-", "muted": value is None}

    if key == "critic_rating":
        value = _attr(item, name="provider_rating")
        return {"kind": "text", "text": f"{value:.1f}" if value is not None else "-", "muted": value is None}

    if key == "platform":
        value = _attr(row, name="display_platform")
        return {"kind": "text", "text": str(value or "-"), "muted": not value}

    if key == "last_watched":
        value = _attr(tracker, row, name="last_watched")
        return {"kind": "text", "text": str(value or "-"), "muted": not value}

    if key == "genres":
        genres = list(getattr(item, "genres", None) or [])
        if not genres:
            return {"kind": "text", "text": "-", "muted": True}
        return {
            "kind": "genres",
            "items": [{"label": str(genre)} for genre in genres],
        }

    if key == "tags":
        tag_names = _tags(item, user)
        if not tag_names:
            return {"kind": "text", "text": "-", "muted": True}
        return {
            "kind": "tags",
            "items": [{"label": str(name)} for name in tag_names],
        }

    if key == "notes":
        notes = _attr(tracker, row, name="notes")
        if not show_public_notes or not notes:
            return {"kind": "text", "text": "-", "muted": True, "limitLines": 1}
        return {"kind": "text", "text": str(notes), "limitLines": 2}

    if key == "synopsis":
        synopsis = _attr(item, name="synopsis")
        return {
            "kind": "text",
            "text": str(synopsis or "-"),
            "muted": not synopsis,
            "limitLines": 2,
        }

    if key == "entry_source":
        source = _attr(tracker, row, name="entry_source")
        if public_view or not source:
            return {"kind": "text", "text": "-", "muted": True}
        return {"kind": "text", "text": _entry_source(source)}

    if key == "album_artist":
        album = getattr(row, "album", None)
        credit_rows = list(getattr(album, "artist_credits", None).all()) if getattr(album, "artist_credits", None) is not None else []
        if credit_rows:
            names = [getattr(credit, "artist", None) for credit in credit_rows]
            return {"kind": "text", "text": ", ".join(str(getattr(artist, "name", "")) for artist in names if artist)}
        artist = getattr(album, "artist", None)
        return {"kind": "text", "text": str(getattr(artist, "name", "") or "-"), "muted": not artist}

    if key == "artist_release_date":
        value = _attr(row, name="first_release_date")
    elif key == "album_release_date":
        value = _attr(getattr(row, "album", None), name="release_date")
    elif key == "release_date":
        value = _first(_attr(tracker, name="release_datetime"), _attr(item, name="release_datetime"))
    elif key == "next_episode_air_date":
        value = _attr(row, name="next_episode_air_date")
    elif key == "start_date":
        value = _first(_attr(tracker, name="aggregated_start_date"), _attr(tracker, name="start_date"))
    elif key == "end_date":
        value = _first(_attr(tracker, name="aggregated_end_date"), _attr(tracker, name="end_date"))
    elif key == "artist_start_date":
        value = _attr(row, name="start_date")
    elif key == "artist_end_date":
        value = _attr(row, name="end_date")
    elif key in {"date_added", "album_date_added", "artist_date_added"}:
        value = _attr(row, tracker, name="created_at")
    else:
        value = None

    if value:
        return {"kind": "text", "text": _date(value, user)}
    return {"kind": "text", "text": "-", "muted": True}


def table_json_url(request, page: int) -> str:
    """Return the bounded JSON page URL for the same table request."""
    params = request.GET.copy()
    params["page"] = str(page)
    params["table_json"] = "1"
    return f"{request.path}?{params.urlencode()}"


def column_width(key: str) -> int:
    """Return the presentation width for one column key."""
    if key == "image":
        return 56
    if key in WIDE_COLUMNS:
        return 154
    if key in {"genres", "tags", "notes", "synopsis"}:
        return 80
    if key in {"author", "channel", "album_artist"}:
        return 70
    return 56


def column_descriptor(column: ColumnDef) -> dict[str, Any]:
    """Return the shared presentation descriptor for one column."""
    return {
        "key": column.key,
        "label": gettext(column.label) if column.label else "",
        "width": column_width(column.key),
        "align": "center" if column.key in CENTER_COLUMNS else "left",
        "primary": column.key in WIDE_COLUMNS,
    }


def build_table_rows(
    rows,
    resolved_columns: list[ColumnDef],
    *,
    user,
    table_type: str,
    media_type: str,
    public_view: bool,
    public_list_reference: str = "",
    show_public_notes: bool = True,
) -> list[dict[str, Any]]:
    """Project table rows into shared cell descriptions."""
    projected = []
    for row in rows:
        item = _item(row, _tracker(row))
        cells = {
            column.key: cell_for_column(
                column,
                row,
                user=user,
                table_type=table_type,
                media_type=media_type,
                public_view=public_view,
                public_list_reference=public_list_reference,
                show_public_notes=show_public_notes,
            )
            for column in resolved_columns
        }
        title_key = next(
            (key for key in ("title", "artist_name", "album_title") if key in cells),
            None,
        )
        title_cell = cells.get(title_key, {}) if title_key else {}
        projected.append(
            {
                "id": getattr(row, "item_id", None) or getattr(item, "id", None) or str(len(projected)),
                "title": title_cell.get("text") or str(getattr(item, "title", "") or ""),
                "href": title_cell.get("href") or "",
                "cells": cells,
            },
        )
    return projected


def build_table_browser_props(
    *,
    rows,
    resolved_columns: list[ColumnDef],
    column_config: list[dict[str, Any]],
    default_column_config: list[dict[str, Any]],
    user,
    table_type: str,
    media_type: str,
    current_sort: str,
    current_direction: str,
    update_url: str,
    refresh_url: str,
    refresh_target: str,
    refresh_include: str,
    csrf_token: str,
    public_view: bool = False,
    public_list_reference: str = "",
    show_public_notes: bool = True,
    next_url: str = "",
) -> dict[str, Any]:
    """Build the shared table and column-menu props for one page."""
    fixed_columns = [
        {
            "key": column.key,
            "label": gettext(column.label) if column.label else "",
            "fixed": True,
            "visible": True,
        }
        for column in resolved_columns
        if not column.user_hideable
    ]
    menu_columns = fixed_columns + [
        {
            "key": entry["key"],
            "label": gettext(entry["label"]) if entry["label"] else entry["key"],
            "visible": entry["visible"],
            "fixed": False,
        }
        for entry in (column_config or [])
    ]
    default_hidden = [
        entry["key"]
        for entry in (default_column_config or [])
        if not entry.get("visible", True)
    ]
    return {
        "table": {
            "columns": [column_descriptor(column) for column in resolved_columns],
            "rows": build_table_rows(
                rows,
                resolved_columns,
                user=user,
                table_type=table_type,
                media_type=media_type,
                public_view=public_view,
                public_list_reference=public_list_reference,
                show_public_notes=show_public_notes,
            ),
            "sort": current_sort,
            "sortDirection": current_direction,
            "nextUrl": next_url,
            "resultCount": len(rows),
        },
        "menu": {
            "columns": menu_columns,
            "defaultOrder": [entry["key"] for entry in (default_column_config or [])],
            "defaultHidden": default_hidden,
            "updateUrl": update_url,
            "refreshUrl": refresh_url,
            "refreshTarget": refresh_target,
            "refreshInclude": refresh_include,
            "csrfToken": csrf_token,
            "tableType": table_type,
            "mediaTypeKey": media_type,
            "sort": current_sort,
        },
        "sorts": {
            "defaultDirection": "asc" if current_sort in ASCENDING_SORTS else "desc",
            "ascending": sorted(ASCENDING_SORTS),
        },
    }
