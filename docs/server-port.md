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

If Floppy uses `network_mode: "service:gluetun"`, both services use one network namespace. Two processes in that namespace cannot listen on the same address and TCP port.

Select an unused `FLOPPY_PORT`. Publish that port on the service that owns the namespace.

## Configuration priority

Floppy resolves the public listener in this order:

1. `FLOPPY_PORT`
2. the saved instance value
3. default `8000`

`FLOPPY_PORT` is authoritative while it is present. A saved value cannot replace an active environment value.

All accepted values are decimal integers from `1` through `65535`. Invalid values stop startup before they reach Nginx or shell state.

## CLI

The CLI uses the same local resolver as startup. It does not need Django, Redis, a database connection, or internet access.

From a source checkout:

```bash
cd src
python -m config.server_port
```

Inside the standard container:

```bash
docker exec floppy python -m config.server_port
```

Useful actions:

```bash
python -m config.server_port --value
python -m config.server_port --json
python -m config.server_port --set 9000
python -m config.server_port --reset
```

The saved value is stored under `FLOPPY_DATA_DIR` and applies on a later restart when no environment override is active.

## App UI

Open **Settings → Advanced → Server port**.

Every signed-in user can see a safe, read-only summary of the listener. This includes the normal account created through the standard Docker setup.

The read-only view shows:

- **Running listener** — the port reported by the packaged launcher.
- **Configured port** — the value selected by the resolver and its source.

A normal user cannot save or reset the listener. A direct mutation request from a non-superuser is also rejected by the server. If local port configuration is malformed, the read-only view shows only a generic administrator-attention state. It does not show local configuration paths or detailed recovery errors.

A superuser sees the full control in the same location. The administrator view can also show:

- the saved fallback;
- environment-override ownership;
- detailed configuration errors and recovery controls;
- save and reset actions.

Saving does not restart Floppy. If the internal listener changes, update the target side of the container port mapping before restart.

Advanced remains one Settings destination. Floppy does not add a separate Server settings page for this one instance setting.

## Saved instance value

The saved configuration file is:

```text
FLOPPY_DATA_DIR/server-port.json
```

Writes use a temporary file in the same directory and an atomic replace. Reads reject non-regular files and use no-follow behavior where the platform supports it.

A malformed saved file fails closed when it is the active source. A valid `FLOPPY_PORT` can keep the instance running while a superuser repairs or resets the bad fallback.

## Container startup and health

The packaged container resolves the listener once at startup. It then:

1. renders the IPv4 and IPv6 Nginx listener configuration;
2. writes the validated running port to `/run/floppy/server-port`;
3. passes that listener to the normal entrypoint;
4. starts normal services after startup checks pass.

The health check reads `/run/floppy/server-port`. It does not import Django or parse persistent configuration on each probe.

`EXPOSE 8000` remains default image metadata. It is not the runtime source of truth.

Floppy's private Gunicorn hop on `127.0.0.1:8001` remains internal and is not changed by this setting.

## SQLite recovery

If SQLite startup pauses for a recovery decision, the recovery page uses the same validated public listener selected for that startup.

If the instance uses port `9000`, the recovery page also binds to `9000`. The HTML copy written beside the database names the same listener.

The recovery server returns `503` on its health path while startup is paused. The recovery page can stay reachable without reporting the application as healthy.

The recovery path does not require Django, Redis, a database service, or internet access.

## MCP behavior

An explicit `FLOPPY_URL` remains authoritative for the MCP server.

A standalone MCP installation requires `FLOPPY_URL`. The MCP server bundled in the Floppy container can use `/run/floppy/server-port` as a local fallback when `FLOPPY_URL` is not set.

## Performance and offline behavior

This setting adds no background process, polling loop, database lookup, or network lookup.

- The packaged listener is resolved once during startup.
- Health probes read one small runtime file.
- Normal application requests do not resolve the port.
- The Advanced panel and CLI use local environment/file work only when opened or called.
- The read-only status view reuses the same local status computation as the administrator view.

A future native or desktop launcher can reuse the resolver and saved file without copying Docker-specific logic.

## Troubleshooting

### I can see the status but not the save or reset controls

Only a superuser can change the saved listener from the web interface. If you manage the host with a normal Floppy account, use `FLOPPY_PORT` or the CLI.

### Floppy still opens on the old port after saving

Restart the Floppy process or container. Saving the value does not restart the service.

If Docker publishes Floppy's internal port, update the target side of the mapping before restart.

### The UI will not let an administrator save

Check whether `FLOPPY_PORT` is set. Environment configuration is authoritative.

### Docker says the host port is already allocated

This is a host publishing conflict. Change the left side of the mapping, for example `9000:8000`. You do not need to change Floppy's internal listener unless the collision exists inside the same network namespace.

### The saved configuration is invalid

A superuser can use **Settings → Advanced → Server port → Reset saved value**. A host administrator can also run:

```bash
python -m config.server_port --reset
```

Then restart Floppy.

## Related work

- Floppy issue `#837` owns the configurable listener behavior and this visibility correction.
- Floppy PR `#838` introduced the configurable listener and administrator mutation control.
- Floppy PR `#839` identified the recovery-page fixed-port gap while keeping its test repair separate.
- Floppy issue `#597` owns broader deployment preflight work.
- Floppy issue `#512` is the performance baseline.
- Floppy issue `#60` records earlier host-port versus internal-port confusion.
- Upstream Yamtrack issue `#1668` describes the shared-network-namespace collision that exposed the fixed listener.
