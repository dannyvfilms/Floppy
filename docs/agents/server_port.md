# Server port implementation notes

Use `src/config/server_port.py` as the single owner of Floppy's public HTTP listener setting.

## Invariants

- Default public listener: `8000`.
- Priority: `FLOPPY_PORT` → saved instance value → default.
- Accepted value: decimal integer `1` through `65535`.
- Gunicorn `127.0.0.1:8001` is a private internal hop. Do not connect this user setting to it.
- Port resolution must work before Django, Redis, database access, or network access.
- Do not add a second port parser in Docker scripts, recovery code, views, MCP code, or future launchers.
- Do not make the Nginx bind address configurable as part of a server-port change.
- A pre-application recovery surface must use the same validated public listener as the startup that entered recovery.

## Runtime surfaces

The container launcher resolves the value once, renders Nginx, records the active listener in `/run/floppy/server-port`, and passes the validated value to the normal entrypoint.

If SQLite integrity checks pause startup, the recovery server binds to that passed listener. Its written HTML fallback must name the same port. Do not restore a recovery-only fixed port or a second recovery setting.

When the recovery module is invoked directly without a packaged launcher value, it uses `src/config/server_port.py` to resolve the same environment → saved → default priority locally.

The health check reads the runtime file. The recovery server answers its health path with `503` so the recovery page can remain reachable without reporting the application as healthy.

The status surface lives under **Settings → Advanced → Server port**. Do not add a second Settings destination for this one instance setting.

All signed-in users can see safe read-only listener status. Only superusers can see or use save/reset controls. The POST endpoint must keep its server-side superuser check even when the template hides the controls.

Do not expose detailed local configuration errors, saved paths, or recovery controls to a non-superuser. Show a generic administrator-attention state instead.

The Advanced panel reads the same persistent setting. It must not claim that a saved value overrides an active `FLOPPY_PORT`.

The CLI imports the same module directly. Keep it usable without a configured Django environment.

The bundled MCP client can use the validated runtime file only as a local packaged-container fallback. An explicit `FLOPPY_URL` remains authoritative, and standalone MCP use still requires an explicit URL.

## Saved configuration

The saved file is `FLOPPY_DATA_DIR/server-port.json`.

Keep writes atomic. Keep reads defensive against malformed files and non-regular files. Never interpolate unvalidated configuration into Nginx, shell commands, or recovery HTML.

## Packaging

Future launchers should call this module rather than copying the Docker wrapper behavior. A launcher can use the saved value before network startup and publish its actual running listener through its own local runtime-status mechanism.

If a packaged launcher can enter a recovery mode before the full application starts, pass the validated listener from startup into that recovery surface. Do not make recovery infer a different listener after startup already chose one.

Do not introduce a Docker-only setting for a behavior that must also work in source and packaged installs. Keep POSIX-only file operations optional so Windows-compatible launchers can use the same saved configuration path.

## Performance and offline rules

- Do not add a daemon, worker, or polling loop for this setting.
- Do not add database or network work to request paths.
- Resolve the packaged listener once at startup where possible.
- Recovery reuses that already-resolved packaged listener.
- Health checks read the already-resolved runtime value.
- UI and CLI reads are local environment/file operations only.
- The setting and the recovery page must remain usable with no internet connection.

## UI review checklist

For changes to **Settings → Advanced → Server port**:

- signed-in users can find the Server port status in Advanced;
- non-superusers receive read-only running/configured status only;
- non-superusers do not receive mutation controls, mutation URLs, detailed local errors, or configuration paths;
- superusers retain the full save/reset control;
- the POST view independently rejects non-superusers;
- visible current listener;
- visible configuration source;
- visible saved fallback for a superuser;
- explicit restart state for a superuser after a saved change;
- environment override shown in text for a superuser;
- normal form controls with labels;
- keyboard operation without custom interaction code;
- no timers or automatic focus changes;
- administrator errors remain next to the setting and include a recovery action;
- host-port and internal-port guidance remain distinct;
- changing the internal listener warns container users to update the published target before restart.

For the SQLite recovery page:

- the served page binds to the selected public listener;
- the written offline copy names the same listener;
- `/health` and `/health/` remain `503` while startup is paused;
- no external asset is required to read or use the page;
- keyboard, focus, contrast, and screen-reader behavior must remain usable before the main app starts.

## Validation

At minimum, run focused tests for:

```bash
scripts/test.sh config.tests.test_server_port
scripts/test.sh config.tests.test_server_port_recovery
scripts/test.sh config.tests.test_sqlite_recovery_server
scripts/test.sh users.tests.views.test_server_port
```

Run the MCP tests when local-URL behavior changes:

```bash
uv run --project mcp_server pytest mcp_server/tests/test_client.py
```

Then run the repository quality workflow required by `AGENTS.md` and `CONTRIBUTING.md`.

When the status-panel authorization changes, test both a normal signed-in account and a superuser in a real browser. Capture the resulting Advanced-settings states. Do not mark the UI change ready only from template tests.

When container startup changes, validate the built image with the default listener. A non-default container smoke is also required before claiming packaged non-default behavior is fully verified; do not weaken repository workflow protections to add that check inside an unrelated PR.

A recovery smoke must also confirm that a configured non-default listener remains reachable when SQLite startup is intentionally paused. The container must stay unhealthy during that recovery state.

## Contract surfaces

This launcher setting is not a REST resource. Do not add it to OpenAPI, AsyncAPI, or JSON-LD unless a supported network API or event contract is deliberately introduced later.

If a future API is added, define its authorization and restart semantics before exposing it. An API that changes the saved file but looks like a live listener mutation would be misleading.

See `docs/server-port.md` for operator-facing behavior and examples.
