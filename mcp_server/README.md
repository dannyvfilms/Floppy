# Floppy MCP Server

An MCP (Model Context Protocol) server that wraps the Floppy REST API
(`src/api/`) so AI agents (Claude Code, Claude Desktop, etc.) can search,
track, and manage a user's Floppy library — with the same level of
access as the web UI.

Rather than exposing every REST route 1:1, this server groups them into 20
agent-shaped tools (`search_media`, `track_media`, `manage_list`, ...) so an
agent's tool list stays legible and each call maps to a coherent user
intent.

## Setup

The Docker image bundles this package, so if you're running Floppy via
Docker there's nothing to install — see "Running (Docker)" below. For a
source/non-Docker install:

```bash
cd /path/to/Floppy
uv sync --locked
```

Configure the server with two environment variables:

- `FLOPPY_URL` — base URL of the Floppy instance, e.g.
  `https://floppy.example.com` (no trailing slash needed).
- `FLOPPY_TOKEN` — the user's API token, found under
  Settings → Integrations in the web UI (the same token used for webhooks and
  the iCal feed). Sent as an `X-API-Key` header.

## Running (Docker)

The image ships `floppy_mcp` and already sets `FLOPPY_URL` internally, so
`docker exec` into the running container always runs the MCP server version
that shipped with that image — no separate install or update step, and no
drift between the app and the tool code:

```bash
claude mcp add floppy \
  --env FLOPPY_TOKEN=your-token \
  -- docker exec -i -e FLOPPY_TOKEN floppy python -m floppy_mcp.server
```

(`floppy` is the container name from `docker-compose.yml` — adjust if you
renamed it.)

## Running (source install)

Stdio transport (for Claude Code / Claude Desktop):

```bash
FLOPPY_URL=https://floppy.example.com \
FLOPPY_TOKEN=your-token \
uv run --no-sync python -m floppy_mcp.server
```

Register it with Claude Code:

```bash
claude mcp add floppy \
  --env FLOPPY_URL=https://floppy.example.com \
  --env FLOPPY_TOKEN=your-token \
  -- uv run --directory /path/to/Floppy --no-sync python -m floppy_mcp.server
```

The source workspace is installed from the shared root lock, so changes under
`mcp_server/` are available without a separate package install. Run
`uv sync --locked` again when dependency metadata or `uv.lock` changes. The
Docker exec path above stays current automatically.

For streamable-HTTP transport instead of stdio, call
`mcp.run(transport="streamable-http")` in `server.py` (see the `FastMCP`
docs) or run `uvicorn floppy_mcp.server:mcp.streamable_http_app`.

## Tools

| Tool | Purpose |
|---|---|
| `search_media` | Provider search for new media to track |
| `search_tracked_media` | Search the user's own library by title |
| `get_discover` | Personalized Discover recommendation rows |
| `get_home` | Home-page rows (continue watching, etc.) |
| `get_media` | Detail for one tracked item / season / episode |
| `list_tracked_media` | List the library, filtered by type/status |
| `track_media` | Start or update tracking (status/score/progress/dates) |
| `untrack_media` | Remove a tracked item (or season/episode) |
| `update_progress` | Increase/decrease progress by one unit |
| `log_episode_play` | Record a TV episode watch |
| `log_song_play` | Record a music listen |
| `log_podcast_play` | Record a podcast episode play |
| `list_custom_lists` | List the user's custom lists |
| `manage_list` | Create/rename/delete lists; add/remove tracked items |
| `manage_tags` | Create/rename/delete tags; tag/untag items |
| `get_history` | Day-grouped consumption timeline |
| `get_statistics` | Full statistics dashboard for a date range |
| `run_import` | Queue a one-off library import (mal/anilist/kitsu/steam) |
| `get_task_status` | Poll a background task (import, bulk play, sync, ...) |
| `manage_settings` | Read/update user preferences |

### Notes on tool contracts

- `track_media` reads the title before writing. When completing an already
  tracked title, it targets the returned `Planning`/`In progress` consumption
  with the exact history PATCH route, so automatic completion does not leave a
  stale planning row. Set `new_play=true` to append a separate play; an
  untracked title is created with POST. The underlying generic POST remains an
  append operation and defaults an omitted status to `Planning`.

- **`status`** on `track_media` accepts the display names Floppy uses in
  the UI (`"Planning"`, `"In progress"`, `"Paused"`, `"Completed"`,
  `"Dropped"`); the tool translates them to the API's numeric wire format
  internally.
- **`manage_list`**'s `add_item`/`remove_item` actions operate on already
  *tracked* media (`media_type`/`source`/`media_id`), not on raw list-row
  ids — track the item first with `track_media` if it isn't tracked yet.
- Tools never raise on API errors; they return
  `{"error": true, "status_code": ..., "detail": ...}` so the agent can see
  and react to failures instead of the call blowing up.
- **Known upstream quirk**: `GET` on a `source=manual` media item that
  doesn't exist returns HTTP 500 instead of 404 (the generic media-detail
  view can't distinguish "not found" from other metadata-provider errors
  for sources with no provider). `track_media` already handles this
  gracefully by falling through to create-or-report-validation-errors, but
  other tools calling `get_media` on a manual id that may not exist should
  check `result.get("error")`.

## Testing

```bash
cd /path/to/Floppy
uv sync --locked --package floppy-mcp --extra dev
uv run --package floppy-mcp --extra dev --no-sync pytest mcp_server/tests/ -q
```

Tests mock the REST API with `respx` and assert each tool sends the
expected HTTP method/path/params/body — no live Floppy instance needed
for the unit suite. They were also verified end-to-end against a running
`manage.py runserver` + Celery worker instance covering tracking, list
membership, tags, history, statistics, settings, and async task dispatch.

## Design notes

- One shared `httpx.AsyncClient` per process (`client.py`), created lazily
  on first request so `FLOPPY_URL`/`FLOPPY_TOKEN` can be set after
  import (useful in tests).
- `_call()` in `server.py` is the single place that turns REST errors into
  a structured payload — no tool duplicates that error handling.
- Not a 1:1 route mirror by design — see the plan rationale: ~15–20
  agent-shaped tools beat ~150 raw endpoint wrappers for an agent's context
  budget and decision quality.
