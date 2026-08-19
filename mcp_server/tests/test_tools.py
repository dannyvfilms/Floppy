"""Verify each MCP tool issues the correct HTTP request against the API."""
import json

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
        assert req.url.params["q"] == "matrix"
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
        await server.manage_settings("update", rating_scale="0-10")
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
