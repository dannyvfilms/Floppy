from typing import NamedTuple


class HTTPRoute(NamedTuple):
    """One immutable MCP tool branch mapped to its OpenAPI operation."""

    tool: str
    method: str
    path: str


def canonical_openapi_path(relative_path: str) -> str:
    """Convert an MCP client-relative path to canonical OpenAPI form."""
    return f"/api/v1/{relative_path.strip('/')}/"


MCP_HTTP_MANIFEST = (
    HTTPRoute("search_media", "get", canonical_openapi_path("search/{media_type}")),
    HTTPRoute("resolve_game", "get", canonical_openapi_path("search/{media_type}")),
    HTTPRoute("search_tracked_media", "get", canonical_openapi_path("media")),
    HTTPRoute("get_discover", "get", canonical_openapi_path("discover")),
    HTTPRoute("get_home", "get", canonical_openapi_path("home")),
    HTTPRoute(
        "get_media",
        "get",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}"),
    ),
    HTTPRoute(
        "get_media",
        "get",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}"
        ),
    ),
    HTTPRoute(
        "get_media",
        "get",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}"
        ),
    ),
    HTTPRoute(
        "get_media_state",
        "get",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}/state"),
    ),
    HTTPRoute(
        "get_media_state",
        "get",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/state"
        ),
    ),
    HTTPRoute(
        "get_media_state",
        "get",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}/state"
        ),
    ),
    HTTPRoute("list_tracked_media", "get", canonical_openapi_path("media")),
    HTTPRoute(
        "list_tracked_media",
        "get",
        canonical_openapi_path("media/{media_type}"),
    ),
    HTTPRoute(
        "track_media",
        "get",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}"),
    ),
    HTTPRoute(
        "track_media",
        "patch",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/history/{consumption_id}"
        ),
    ),
    HTTPRoute(
        "track_media",
        "patch",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}"),
    ),
    HTTPRoute("track_media", "post", canonical_openapi_path("media/{media_type}")),
    HTTPRoute(
        "untrack_media",
        "delete",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}"),
    ),
    HTTPRoute(
        "untrack_media",
        "delete",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}"
        ),
    ),
    HTTPRoute(
        "untrack_media",
        "delete",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}"
        ),
    ),
    HTTPRoute(
        "update_progress",
        "post",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}/progress"),
    ),
    HTTPRoute(
        "update_progress",
        "post",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/progress"
        ),
    ),
    HTTPRoute(
        "log_episode_play",
        "post",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/{season_number}/episodes/"
            "{episode_number}/watch"
        ),
    ),
    HTTPRoute(
        "log_song_play", "post", canonical_openapi_path("music/songs/plays")
    ),
    HTTPRoute(
        "log_podcast_play",
        "post",
        canonical_openapi_path("podcasts/episodes/plays"),
    ),
    HTTPRoute("list_custom_lists", "get", canonical_openapi_path("lists")),
    HTTPRoute("manage_list", "post", canonical_openapi_path("lists")),
    HTTPRoute("manage_list", "patch", canonical_openapi_path("lists/{list_id}")),
    HTTPRoute("manage_list", "delete", canonical_openapi_path("lists/{list_id}")),
    HTTPRoute(
        "manage_list", "get", canonical_openapi_path("lists/{list_id}/items")
    ),
    HTTPRoute(
        "manage_list",
        "put",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/lists/{list_id}"
        ),
    ),
    HTTPRoute(
        "manage_list",
        "delete",
        canonical_openapi_path(
            "media/{media_type}/{source}/{media_id}/lists/{list_id}"
        ),
    ),
    HTTPRoute("manage_tags", "get", canonical_openapi_path("tags")),
    HTTPRoute("manage_tags", "post", canonical_openapi_path("tags")),
    HTTPRoute("manage_tags", "patch", canonical_openapi_path("tags/{tag_id}")),
    HTTPRoute("manage_tags", "delete", canonical_openapi_path("tags/{tag_id}")),
    HTTPRoute(
        "manage_tags",
        "get",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}/tags"),
    ),
    HTTPRoute(
        "manage_tags",
        "put",
        canonical_openapi_path("media/{media_type}/{source}/{media_id}/tags"),
    ),
    HTTPRoute("get_history", "get", canonical_openapi_path("history")),
    HTTPRoute(
        "get_statistics", "get", canonical_openapi_path("statistics/overview")
    ),
    HTTPRoute("run_import", "post", canonical_openapi_path("imports/{service}")),
    HTTPRoute(
        "get_task_status", "get", canonical_openapi_path("tasks/{task_id}")
    ),
    HTTPRoute(
        "manage_settings", "get", canonical_openapi_path("user/preferences")
    ),
    HTTPRoute(
        "manage_settings", "patch", canonical_openapi_path("user/preferences")
    ),
)
