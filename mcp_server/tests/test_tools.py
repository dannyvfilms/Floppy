"""Verify each MCP tool issues the correct HTTP request against the API."""
import json

import httpx
import respx
from httpx import Response

from floppy_mcp import server


def ok(payload=None):
    return Response(200, json=payload if payload is not None else {"ok": True})


async def test_search_media(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/search/movie").mock(return_value=ok())
        await server.search_media("movie", "matrix", page=2)
        req = route.calls.last.request
        assert req.url.params["search"] == "matrix"
        assert req.url.params["page"] == "2"


async def test_search_tracked_media(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media").mock(return_value=ok())
        await server.search_tracked_media("dune")
        assert route.calls.last.request.url.params["search"] == "dune"


async def test_get_discover(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/discover").mock(return_value=ok())
        await server.get_discover(media_type="tv")
        assert route.calls.last.request.url.params["media_type"] == "tv"


async def test_get_home(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/home").mock(return_value=ok())
        result = await server.get_home()
        assert route.called
        assert result == {"ok": True}


async def test_get_media_show(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media/tv/tmdb/123").mock(return_value=ok())
        await server.get_media("tv", "tmdb", "123")
        assert route.called


async def test_get_media_episode(api_base_url):
    with respx.mock:
        route = respx.get(
            f"{api_base_url}/media/tv/tmdb/123/1/5",
        ).mock(return_value=ok())
        await server.get_media("tv", "tmdb", "123", season_number=1, episode_number=5)
        assert route.called


async def test_list_tracked_media_by_type(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media/movie").mock(return_value=ok())
        await server.list_tracked_media(media_type="movie", status="Completed")
        assert route.calls.last.request.url.params["status"] == "Completed"


async def test_list_tracked_media_aggregate(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media").mock(return_value=ok())
        await server.list_tracked_media()
        assert route.called


async def test_track_media_creates_when_untracked(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=Response(404, json={"detail": "not found"}),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )
        await server.track_media("movie", "tmdb", "1", status="Completed", score=9)
        body = create_route.calls.last.request.content
        payload = json.loads(body)
        assert payload["media_id"] == "1"
        assert payload["source"] == "tmdb"
        assert payload["status"] == 3
        assert payload["score"] == 9


async def test_track_media_stops_after_lookup_connection_error(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            side_effect=httpx.ConnectError("Connection failed"),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )

        result = await server.track_media("movie", "tmdb", "1")

        assert result == {"error": True, "detail": "Connection failed"}
        assert not create_route.called


async def test_track_media_stops_after_lookup_api_error(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=Response(401, json={"detail": "Unauthorized"}),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )

        result = await server.track_media("movie", "tmdb", "1")

        assert result == {
            "error": True,
            "status_code": 401,
            "detail": {"detail": "Unauthorized"},
        }
        assert not create_route.called


async def test_track_media_manual_source_creates_after_lookup_500(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/manual/1").mock(
            return_value=Response(500, json={"detail": "Provider error"}),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )

        result = await server.track_media("movie", "manual", "1")

        assert result["ok"] is True
        assert result["operation"]["outcome"] == "created"
        assert create_route.called


async def test_track_media_invalid_status_rejected():
    result = await server.track_media("movie", "tmdb", "1", status="Watching")
    assert result["error"] is True


async def test_track_media_updates_when_tracked(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=ok({"tracked": True, "consumptions": []}),
        )
        patch_route = respx.patch(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=Response(200, json={"ok": True}),
        )
        await server.track_media("movie", "tmdb", "1", score=8)
        assert patch_route.called


async def test_track_media_completion_targets_pending_consumption(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=ok(
                {
                    "tracked": True,
                    "consumptions": [
                        {"consumption_id": 42, "status": "Planning"},
                        {"consumption_id": 17, "status": "Completed"},
                    ],
                },
            ),
        )
        patch_route = respx.patch(
            f"{api_base_url}/media/movie/tmdb/1/history/42",
        ).mock(return_value=Response(200, json={"ok": True}))

        await server.track_media("movie", "tmdb", "1", status="Completed")

        assert patch_route.called
        assert not respx.calls[1].request.url.path.endswith("/media/movie/tmdb/1")


async def test_track_media_can_append_explicit_new_play(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=ok({"tracked": True, "consumptions": []}),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )

        await server.track_media(
            "movie",
            "tmdb",
            "1",
            status="Completed",
            new_play=True,
        )

        assert create_route.called


async def test_track_media_untracked_omits_status_for_api_default(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=Response(404, json={"detail": "not found"}),
        )
        create_route = respx.post(f"{api_base_url}/media/movie").mock(
            return_value=Response(201, json={"ok": True}),
        )

        await server.track_media("movie", "tmdb", "1")

        assert "status" not in json.loads(create_route.calls.last.request.content)


def _tracked(consumptions):
    return ok({"tracked": True, "consumptions": consumptions})


async def test_track_media_result_reports_created_operation(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=Response(404, json={"detail": "nope"}),
        )
        respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(
                201,
                json={
                    "consumption_id": 9,
                    "status": "Completed",
                    "progress": 600,
                    "progress_unit": "minutes",
                    "progress_scope": "entry",
                    "start_date": "2019-03-01",
                    "end_date": "2019-03-07",
                },
            ),
        )
        result = await server.track_media(
            "game",
            "igdb",
            "7",
            status="Completed",
            progress=600,
            start_date="2019-03-01",
            end_date="2019-03-07",
        )
    op = result["operation"]
    assert op["outcome"] == "created"
    assert op["consumption_id"] == 9
    assert op["identity"] == {"media_type": "game", "source": "igdb", "media_id": "7"}
    assert op["applied"]["progress_unit"] == "minutes"
    assert op["applied"]["end_date"] == "2019-03-07"
    assert op["verify"]["history_path"].endswith("/media/game/igdb/7/history/")
    assert result["progress"] == 600  # raw body is still present


async def test_track_media_completing_planned_reports_updated(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=_tracked([{"consumption_id": 4, "status": "Planning"}]),
        )
        respx.patch(f"{api_base_url}/media/game/igdb/7/history/4").mock(
            return_value=Response(200, json={"status": "Completed"}),
        )
        result = await server.track_media("game", "igdb", "7", status="Completed")
    assert result["operation"]["outcome"] == "updated"
    assert result["operation"]["consumption_id"] == 4


async def test_track_media_new_play_on_completed_reports_appended(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=_tracked([{"consumption_id": 4, "status": "Completed"}]),
        )
        post = respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(201, json={"consumption_id": 5}),
        )
        result = await server.track_media(
            "game",
            "igdb",
            "7",
            status="Completed",
            mode="new_play",
            start_date="2020-01-01",
            end_date="2020-01-02",
        )
    assert post.called
    assert result["operation"]["outcome"] == "appended"
    assert result["operation"]["consumption_id"] == 5


async def test_track_media_update_mode_refuses_untracked(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=Response(404, json={"detail": "nope"}),
        )
        post = respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(201, json={}),
        )
        result = await server.track_media("game", "igdb", "7", mode="update")
    assert result["error_kind"] == "not_found"
    assert not post.called


async def test_track_media_rejects_bad_dates_before_any_request():
    for kwargs in (
        {"start_date": "yesterday"},
        {"start_date": "2020-02-01", "end_date": "2020-01-01"},
        {"progress": -5},
        {"score": 11},
    ):
        result = await server.track_media("game", "igdb", "7", **kwargs)
        assert result["error_kind"] == "invalid_input"
        assert result["write_state"] == "not_applied"


async def test_track_media_write_timeout_is_uncertain_not_failed(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=Response(404, json={"detail": "nope"}),
        )
        respx.post(f"{api_base_url}/media/game").mock(
            side_effect=httpx.ReadTimeout("timed out"),
        )
        result = await server.track_media("game", "igdb", "7", status="Completed")
    assert result["error"] is True
    assert result["error_kind"] == "unknown_write_outcome"
    assert result["write_state"] == "uncertain"
    assert result["verify"]["history_path"]


async def test_track_media_499_is_uncertain(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=Response(404, json={"detail": "nope"}),
        )
        respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(499, json={"detail": "client closed"}),
        )
        result = await server.track_media("game", "igdb", "7")
    assert result["write_state"] == "uncertain"
    assert result["detail"] == {"detail": "client closed"}


async def test_track_media_classifies_busy_and_validation_errors(api_base_url):
    cases = [
        (503, {"detail": "Database is busy."}, "busy", "not_applied"),
        (400, {"detail": "Invalid"}, "invalid_input", "not_applied"),
    ]
    for code, payload, kind, state in cases:
        with respx.mock:
            respx.get(f"{api_base_url}/media/game/igdb/7").mock(
                return_value=Response(404, json={"detail": "nope"}),
            )
            respx.post(f"{api_base_url}/media/game").mock(
                return_value=Response(code, json=payload),
            )
            result = await server.track_media("game", "igdb", "7")
        assert (result["error_kind"], result["write_state"]) == (kind, state)
        assert result["detail"] == payload


async def test_track_media_retry_after_timeout_does_not_duplicate(api_base_url):
    sent = {
        "status": "Completed",
        "progress": 90,
        "mode": "new_play",
        "start_date": "2020-01-01",
        "end_date": "2020-01-02",
        "skip_if_duplicate": True,
    }
    committed = {
        "consumption_id": 12,
        "status": "Completed",
        "progress": 90,
        "start_date": "2020-01-01T00:00:00Z",
        "end_date": "2020-01-02T00:00:00Z",
    }
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=_tracked([committed]),
        )
        post = respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(201, json={}),
        )
        result = await server.track_media("game", "igdb", "7", **sent)
    assert not post.called
    assert result["operation"]["outcome"] == "skipped"
    assert result["operation"]["consumption_id"] == 12


async def test_untrack_media(api_base_url):
    with respx.mock:
        route = respx.delete(f"{api_base_url}/media/movie/tmdb/1").mock(
            return_value=Response(204),
        )
        await server.untrack_media("movie", "tmdb", "1")
        assert route.called


async def test_untrack_episode(api_base_url):
    with respx.mock:
        route = respx.delete(f"{api_base_url}/media/tv/tmdb/1/1/2").mock(
            return_value=Response(204),
        )
        await server.untrack_media("tv", "tmdb", "1", season_number=1, episode_number=2)
        assert route.called


async def test_update_progress_movie(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/media/movie/tmdb/1/progress").mock(
            return_value=ok(),
        )
        await server.update_progress("movie", "tmdb", "1", "increase")
        assert json.loads(route.calls.last.request.content) == {"operation": "increase"}


async def test_update_progress_season(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/media/tv/tmdb/1/1/progress").mock(
            return_value=ok(),
        )
        await server.update_progress("tv", "tmdb", "1", "decrease", season_number=1)
        assert route.called


async def test_log_episode_play(api_base_url):
    with respx.mock:
        route = respx.post(
            f"{api_base_url}/media/tv/tmdb/1/1/episodes/3/watch",
        ).mock(return_value=Response(201, json={"ok": True}))
        await server.log_episode_play("tmdb", "1", 1, 3, end_date="2024-01-01")
        body = json.loads(route.calls.last.request.content)
        assert body == {"end_date": "2024-01-01"}


async def test_log_song_play(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/music/songs/plays").mock(
            return_value=Response(201, json={"ok": True}),
        )
        await server.log_song_play(album_id=5, track_id=10)
        payload = json.loads(route.calls.last.request.content)
        assert payload == {"album_id": 5, "track_id": 10}


async def test_log_podcast_play(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/podcasts/episodes/plays").mock(
            return_value=Response(201, json={"ok": True}),
        )
        await server.log_podcast_play(show_id=2, episode_id=7)
        assert json.loads(route.calls.last.request.content) == {
            "show_id": 2,
            "episode_id": 7,
        }


async def test_list_custom_lists(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/lists").mock(return_value=ok())
        await server.list_custom_lists()
        assert route.called


async def test_manage_list_create(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/lists").mock(
            return_value=Response(201, json={"ok": True}),
        )
        await server.manage_list("create", name="Favorites")
        assert route.called


async def test_manage_list_add_item(api_base_url):
    with respx.mock:
        route = respx.put(f"{api_base_url}/media/movie/tmdb/1/lists/1").mock(
            return_value=Response(200, json={"ok": True}),
        )
        await server.manage_list(
            "add_item",
            list_id=1,
            media_type="movie",
            source="tmdb",
            media_id="1",
        )
        assert route.called


async def test_manage_list_remove_item(api_base_url):
    with respx.mock:
        route = respx.delete(f"{api_base_url}/media/movie/tmdb/1/lists/1").mock(
            return_value=Response(204),
        )
        await server.manage_list(
            "remove_item",
            list_id=1,
            media_type="movie",
            source="tmdb",
            media_id="1",
        )
        assert route.called


async def test_manage_list_list_items(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/lists/1/items").mock(return_value=ok())
        await server.manage_list("list_items", list_id=1)
        assert route.called


async def test_manage_list_unknown_action():
    result = await server.manage_list("bogus")
    assert result["error"] is True


async def test_manage_tags_list(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/tags").mock(return_value=ok())
        await server.manage_tags("list")
        assert route.called


async def test_manage_tags_set_for_item(api_base_url):
    with respx.mock:
        route = respx.put(
            f"{api_base_url}/media/movie/tmdb/1/tags",
        ).mock(return_value=ok())
        await server.manage_tags(
            "set_for_item",
            media_type="movie",
            source="tmdb",
            media_id="1",
            tag_ids=[1, 2],
        )
        assert json.loads(route.calls.last.request.content) == {"tag_ids": [1, 2]}


async def test_get_history(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/history").mock(return_value=ok())
        await server.get_history(media_type="movie", limit=10)
        assert route.calls.last.request.url.params["media_type"] == "movie"


async def test_get_statistics(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/statistics/overview").mock(return_value=ok())
        await server.get_statistics(start_date="all", end_date="all")
        assert route.calls.last.request.url.params["start_date"] == "all"


async def test_run_import(api_base_url):
    with respx.mock:
        route = respx.post(f"{api_base_url}/imports/mal").mock(
            return_value=Response(202, json={"task_id": "abc"}),
        )
        result = await server.run_import("mal", username="someone")
        assert result == {"task_id": "abc"}
        assert route.called


async def test_get_task_status(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/tasks/abc").mock(return_value=ok())
        await server.get_task_status("abc")
        assert route.called


async def test_manage_settings_get(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/user/preferences").mock(return_value=ok())
        await server.manage_settings("get")
        assert route.called


async def test_manage_settings_update(api_base_url):
    with respx.mock:
        route = respx.patch(f"{api_base_url}/user/preferences").mock(return_value=ok())
        await server.manage_settings("update", fields={"rating_scale": "0-10"})
        assert json.loads(route.calls.last.request.content) == {"rating_scale": "0-10"}


async def test_manage_settings_get_through_mcp(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/user/preferences").mock(return_value=ok())
        await server.mcp.call_tool("manage_settings", {"action": "get"})
        assert route.called


async def test_manage_settings_update_through_mcp(api_base_url):
    with respx.mock:
        route = respx.patch(f"{api_base_url}/user/preferences").mock(return_value=ok())
        await server.mcp.call_tool(
            "manage_settings",
            {"action": "update", "fields": {"rating_scale": "0-10"}},
        )
        assert json.loads(route.calls.last.request.content) == {"rating_scale": "0-10"}


async def test_error_from_api_is_surfaced_not_raised(api_base_url):
    """Tools catch API errors and return a structured payload instead of raising."""
    with respx.mock:
        respx.get(f"{api_base_url}/media/movie/tmdb/999").mock(
            return_value=Response(404, json={"detail": "Item not found."}),
        )
        result = await server.get_media("movie", "tmdb", "999")
        assert result["error"] is True
        assert result["status_code"] == 404


async def test_connection_error_is_surfaced_not_raised(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/home").mock(
            side_effect=httpx.ConnectError("Connection failed"),
        )
        result = await server.get_home()
        assert result == {"error": True, "detail": "Connection failed"}


async def test_domain_context_resource_returns_the_served_context():
    with respx.mock:
        respx.get("https://floppy.test/api/context.jsonld").mock(
            return_value=Response(200, text='{"@context": {"@version": 1.1}}'),
        )
        body = await server.domain_context()
        assert json.loads(body)["@context"]["@version"] == 1.1


async def test_domain_context_resource_reports_failure_without_blocking_tools():
    """A missing context must degrade to a structured error, not an exception."""
    with respx.mock:
        respx.get("https://floppy.test/api/context.jsonld").mock(
            return_value=Response(404, text="not found"),
        )
        respx.get("https://floppy.test/api/v1/search/movie").mock(
            return_value=ok({"results": []}),
        )

        error = json.loads(await server.domain_context())
        assert error["error"] is True
        assert error["status_code"] == 404

        # The tool path is unaffected by the resource failure.
        assert await server.search_media("movie", "matrix") == {"results": []}


async def test_every_public_tool_is_registered_on_the_dispatcher():
    """The dispatcher registration is the contract agents see.

    ``@mcp.tool()`` registers as a side effect and returns the plain
    function, so a tool missing the decorator still passes direct-function
    tests while being invisible to agents. Pin the dispatched surface
    exactly: additions and removals both show up here deliberately.
    """
    tools = {tool.name for tool in await server.mcp.list_tools()}
    assert tools == {
        "search_media",
        "resolve_game",
        "get_media_state",
        "search_tracked_media",
        "get_discover",
        "get_home",
        "get_media",
        "get_statistics",
        "get_history",
        "manage_settings",
        "manage_tags",
        "manage_list",
        "track_media",
        "untrack_media",
        "update_progress",
        "run_import",
        "get_task_status",
        "list_custom_lists",
        "list_tracked_media",
        "log_episode_play",
        "log_podcast_play",
        "log_song_play",
    }

    # Each registered tool must describe itself: a schema the dispatcher
    # cannot build is as unusable as a missing registration.
    for tool in await server.mcp.list_tools():
        assert tool.name
        assert tool.inputSchema, tool.name


async def test_get_media_state(api_base_url):
    with respx.mock:
        route = respx.get(f"{api_base_url}/media/game/igdb/2186/state").mock(
            return_value=ok()
        )
        await server.get_media_state("game", "igdb", "2186")
        assert route.called


def _game(media_id, title, year, platforms):
    return {
        "media_id": str(media_id),
        "source": "igdb",
        "media_type": "game",
        "title": title,
        "year": year,
        "platforms": platforms,
    }


MARIO_64 = [
    _game(1, "Super Mario 64", 1996, ["Nintendo 64"]),
    _game(2, "Super Mario 64 DS", 2004, ["Nintendo DS"]),
    _game(3, "Super Mario 64", 2006, ["Wii"]),
    _game(4, "Super Mario 3D All-Stars", 2020, ["Nintendo Switch"]),
]


async def _resolve(api_base_url, results, **kwargs):
    with respx.mock:
        respx.get(f"{api_base_url}/search/game").mock(
            return_value=ok({"results": results}),
        )
        return await server.resolve_game(**kwargs)


async def test_resolve_game_platform_disambiguates(api_base_url):
    out = await _resolve(
        api_base_url, MARIO_64, title="Super Mario 64", platform="N64", year=1996
    )
    assert out["status"] == "exact"
    assert out["selected"] == {"source": "igdb", "media_id": "1"}
    assert out["candidates"][0]["original"] == MARIO_64[0]


async def test_resolve_game_same_title_is_ambiguous_not_guessed(api_base_url):
    out = await _resolve(api_base_url, MARIO_64, title="Super Mario 64")
    assert out["status"] == "ambiguous"
    assert out["selected"] is None
    assert {c["media_id"] for c in out["candidates"][:2]} == {"1", "3"}


async def test_resolve_game_port_vs_remake_kept_distinct(api_base_url):
    results = [
        _game(10, "Resident Evil", 1996, ["PlayStation"]),
        _game(11, "Resident Evil", 2002, ["Nintendo GameCube"]),
        _game(12, "Resident Evil Remake HD Remaster", 2015, ["PC (Microsoft Windows)"]),
    ]
    out = await _resolve(
        api_base_url, results, title="Resident Evil", platform="GameCube"
    )
    assert out["status"] == "exact"
    assert out["selected"]["media_id"] == "11"
    remaster = next(c for c in out["candidates"] if c["media_id"] == "12")
    assert remaster["evidence"]["title"] == "partial"
    assert {"remake", "remaster", "hd"} <= set(remaster["evidence"]["edition_words"])


async def test_resolve_game_alias_and_year_range(api_base_url):
    results = [_game(20, "Mario Kart 64", 1996, ["Nintendo 64"])]
    out = await _resolve(
        api_base_url,
        results,
        title="MK64",
        aliases=["Mario Kart 64"],
        year=1995,
        year_to=1997,
    )
    assert out["status"] == "exact"
    assert out["candidates"][0]["evidence"]["year"] is True


async def test_resolve_game_missing_data_is_likely_not_exact(api_base_url):
    results = [_game(30, "Obscure Game", None, [])]
    out = await _resolve(
        api_base_url, results, title="Obscure Game", platform="PC", year=1999
    )
    assert out["status"] == "likely"
    assert out["selected"] is None
    assert out["likely"]["media_id"] == "30"
    assert out["candidates"][0]["evidence"]["platform"] is None


async def test_resolve_game_no_exact_match(api_base_url):
    out = await _resolve(
        api_base_url, MARIO_64, title="Super Mario 64", platform="Xbox 360"
    )
    assert out["status"] == "no_match"
    assert out["selected"] is None
    assert len(out["candidates"]) == 3  # near misses are preserved


async def test_resolve_game_provider_outage_is_an_error_not_no_match(api_base_url):
    with respx.mock:
        respx.get(f"{api_base_url}/search/game").mock(
            return_value=Response(500, json={"detail": "IGDB lookup failed."}),
        )
        out = await server.resolve_game(title="Super Mario 64")
    assert out["error"] is True
    assert out["error_kind"] == "provider_unavailable"
    assert "status" not in out


async def test_track_media_multiple_game_sessions_stay_separate(api_base_url):
    first = {
        "consumption_id": 1,
        "status": "Completed",
        "progress": 120,
        "start_date": "2019-01-01",
        "end_date": "2019-01-02",
    }
    with respx.mock:
        respx.get(f"{api_base_url}/media/game/igdb/7").mock(
            return_value=_tracked([first]),
        )
        post = respx.post(f"{api_base_url}/media/game").mock(
            return_value=Response(
                201,
                json={"consumption_id": 2, "progress": 90, "progress_unit": "minutes"},
            ),
        )
        result = await server.track_media(
            "game",
            "igdb",
            "7",
            status="Completed",
            progress=90,
            mode="new_play",
            start_date="2020-05-01",
            end_date="2020-05-02",
            skip_if_duplicate=True,
        )
    assert post.called
    assert result["operation"]["outcome"] == "appended"
    assert result["operation"]["consumption_id"] == 2
    assert result["operation"]["applied"]["progress_unit"] == "minutes"
