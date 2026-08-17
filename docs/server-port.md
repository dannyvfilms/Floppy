# Server port configuration

Floppy listens on TCP port `8000` by default. Change the internal listener only when another process in the same network namespace already owns that port.

A normal Docker host-port change does **not** need this setting.

## Choose the correct case

### Change only the host port

Keep Floppy on its default internal listener and change the Docker mapping:

```yaml
ports:
  - "9000:8000"
```

Floppy still listens on `8000` inside its container. Open `http://HOST:9000`.

### Change Floppy's internal listener

Set `FLOPPY_PORT` and publish the same internal port:

```yaml
environment:
  - FLOPPY_PORT=9000
ports:
  - "9000:9000"
```

Use this form when port `8000` is already in use inside Floppy's network namespace.

### Share another container's network namespace

If Floppy uses a configuration such as:

```yaml
network_mode: "service:gluetun"
```

Floppy and that service use one network namespace. Two processes in that namespace cannot listen on the same address and TCP port.

Select an unused `FLOPPY_PORT`, for example `9000`. Publish that port on the service that owns the namespace. Do not add a separate `ports` mapping to Floppy in this mode.

## Configuration priority

Floppy resolves the public listener in this order:

1. `FLOPPY_PORT`
2. the saved instance value
3. default `8000`

`FLOPPY_PORT` is authoritative while it is present. A saved value cannot replace an active environment value.

All accepted values are decimal integers from `1` through `65535`. Invalid values stop startup with a configuration error. They are not passed to Nginx or a shell command.

## Environment

Example:

```bash
FLOPPY_PORT=9000
```

For Docker Compose:

```yaml
environment:
  - FLOPPY_PORT=9000
ports:
  - "9000:9000"
```

The default Compose example does not set `FLOPPY_PORT`. This is intentional. If Compose always supplied `FLOPPY_PORT=8000`, it would hide a value saved through the CLI or administrator UI.

## CLI

The CLI uses the same resolver as the runtime and does not need Django, Redis, a database connection, or network access.

From a source checkout, run it from the application source directory:

```bash
cd src
python -m config.server_port
```

Inside the standard container, run the same module with `docker exec`:

```bash
docker exec floppy python -m config.server_port
```

The remaining examples below show only the module arguments. Use the same source-directory or `docker exec floppy` prefix for your install.

Print only the effective value:

```bash
python -m config.server_port --value
```

Print machine-readable status:

```bash
python -m config.server_port --json
```

Save a listener for the next restart:

```bash
python -m config.server_port --set 9000
```

Remove the saved value:

```bash
python -m config.server_port --reset
```

A saved value is stored under `FLOPPY_DATA_DIR`, so it persists when that directory is persisted.

## App UI

A superuser can open **Settings → Advanced → Server port**.

Advanced remains one Settings destination. Floppy does not add a separate Server settings page for this one instance control.

The panel shows three separate states:

- **Running listener** — the port reported by the current packaged launcher.
- **Configured port** — the value that the resolver currently selects and its source.
- **Saved fallback** — the persisted value that can apply when no environment override exists.

Normal users can continue to use Advanced but do not see the instance port panel and cannot call its mutation endpoint.

Saving a different port does not restart Floppy. The panel reports the restart requirement and tells container users to update the published target before restart when the internal listener changes.

When `FLOPPY_PORT` is active, the panel shows that environment ownership in text and disables the conflicting save control. An administrator can still remove a stale or malformed saved fallback.

The control uses a normal numeric field, normal form submission, visible labels and state text, keyboard-accessible controls, and no timed or automatic focus changes.

## Saved instance value

The saved configuration is:

```text
FLOPPY_DATA_DIR/server-port.json
```

When `FLOPPY_DATA_DIR` is not set, the application data directory is used.

Writes use a temporary file in the same directory and an atomic replace. The saved file uses private POSIX permissions when the platform supports them. The save path does not require POSIX-only file APIs, so a future Windows-compatible packaged launcher can use the same configuration model. Reads reject non-regular files and use no-follow semantics where the platform provides them.

A malformed saved file fails closed when it is the active source. If a valid `FLOPPY_PORT` is present, Floppy can continue to use that environment value while the Advanced panel reports the bad saved fallback for repair or reset.

## Container startup and health

The packaged container resolves the listener once at startup. It then:

1. renders the IPv4 and IPv6 Nginx listener configuration from the checked-in template;
2. writes the validated running port to `/run/floppy/server-port`;
3. passes that same validated port to the normal Floppy entrypoint;
4. starts the normal Floppy services when startup checks pass.

The container health check reads `/run/floppy/server-port`. It does not import Django or parse persistent configuration on every health probe.

`EXPOSE 8000` remains in the image as default image metadata. It is not the runtime source of truth and it cannot represent a dynamic port.

Floppy's private Gunicorn hop on `127.0.0.1:8001` is not part of this setting. It remains internal.

## SQLite recovery

SQLite integrity checks run before Django, Nginx, and the other normal services start. If Floppy pauses for a database recovery decision, the small recovery server uses the same validated public listener selected for that startup.

For example, if the instance is configured for port `9000`, the recovery page also binds to `9000`. It does not fall back to `8000`.

The HTML copy written beside the database also names the selected port. This keeps the offline fallback useful if the container is stopped or if the recovery server cannot bind.

The recovery server answers the health path with `503` on purpose. The recovery page can therefore stay reachable while Docker still reports that the application is not healthy and normal startup is paused.

The recovery path has no Django, Redis, database-service, or internet dependency. Direct recovery invocation uses the same local port resolver when a packaged launcher has not already supplied the validated listener.

## MCP behavior

An explicit `FLOPPY_URL` remains authoritative for the MCP server.

A standalone MCP installation still requires `FLOPPY_URL` because it does not know where the Floppy instance is hosted.

The MCP server bundled in the Floppy container has one additional fallback. If `FLOPPY_URL` is not set, it can read `/run/floppy/server-port` and connect to the local packaged instance. This keeps `docker exec` workflows aligned with a non-default listener without adding another port setting.

## Performance

This setting adds no background process, polling loop, database lookup, or network lookup.

- The packaged listener is resolved once during startup.
- Health probes read one small runtime file.
- Normal application requests do not resolve the port.
- The Advanced panel and CLI use local environment/file work only when they are opened or called.
- SQLite recovery reuses the already-resolved packaged value instead of adding another startup lookup.

## Offline and packaged launchers

The resolver is a small standard-library module. It has no database or network dependency. A future native or desktop launcher can use the same functions and saved file instead of copying Docker-specific logic.

A packaged launcher should:

1. resolve the port before it starts the HTTP listener;
2. validate before it builds command-line or server configuration;
3. record the actual running listener for local status and health checks;
4. pass that listener to any pre-application recovery surface;
5. show a restart requirement when the saved value changes;
6. keep an explicit launcher or environment override higher priority than a saved fallback.

The application remains usable without internet access. Port resolution never contacts an external service.

## Troubleshooting

### Floppy still opens on the old port after saving

Restart the Floppy process or container. Saving the value does not restart the service.

If Docker publishes Floppy's internal port, update the target side of the mapping before restart. For example, an internal listener of `9000` needs a mapping such as `9000:9000` unless you intentionally use a different host port.

### The UI will not let me save

Check whether `FLOPPY_PORT` is set. Environment configuration is authoritative by design.

### Docker says the host port is already allocated

This is a host publishing conflict. Change the left side of the mapping, for example `9000:8000`. You do not need to change Floppy's listener unless the collision exists inside the same network namespace.

### Floppy cannot start because port 8000 is already used in a shared namespace

Set an unused `FLOPPY_PORT`, update the namespace owner's published port, and restart the shared services. If SQLite recovery pauses that startup, open the recovery page on the same selected port.

### The saved configuration is invalid

Use **Settings → Advanced → Server port → Reset saved value** as a superuser, or run from the application source directory:

```bash
python -m config.server_port --reset
```

Then restart Floppy.

## Related work

- Floppy issue `#837` owns the configurable listener behavior.
- Floppy PR `#839` identified the recovery-page fixed-port gap while keeping its App Test workflow repair scoped to CI reliability.
- Floppy issue `#597` can report the effective listener as part of deployment preflight work.
- Floppy issue `#512` is the performance baseline; this setting adds no steady-state request task or daemon.
- Floppy issue `#60` records earlier host-port versus internal-port confusion.
- Upstream Yamtrack issue `#1668` describes the shared-network-namespace collision that exposed the fixed internal listener.
