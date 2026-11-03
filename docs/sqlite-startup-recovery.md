# Floppy will not start: "SQLite startup needs maintenance"

Floppy checked its SQLite database before starting and stopped. **No data was changed.**
This usually follows a crash, power loss, or a check that timed out. It does not mean the
database is damaged. Floppy waits idle (the container stays up, unhealthy) until you run the
fix below.

## Fix

1. Make sure nothing else uses the database: no second Floppy container, no other tool on
   `db.sqlite3`. The waiting Floppy container is idle and counts as safe.
2. Back up your data folder if you can (copy `db.sqlite3` and any `-wal`/`-shm` files).
3. Run the command for your setup and wait for it to finish (large libraries can take
   minutes; the limit is one hour).
4. Restart Floppy.

### Docker Compose

```bash
docker compose run --rm --no-deps --entrypoint python floppy manage.py sqlite_startup --prepare-migrations
docker compose up -d floppy
```

### Plain Docker (container still running, waiting)

Find the name with `docker ps`, then:

```bash
docker exec -it floppy python manage.py sqlite_startup --prepare-migrations
docker restart floppy
```

The command must be `python manage.py ...` run in `/floppy`, which is the container's
default directory. `sqlite_startup` on its own is not a program, and running
`sqlite_startup.py` directly fails with `No module named config`.

### Unraid / Portainer

Stop the Floppy container, then run a one-off container from the same image with the same
volume and environment settings, and the command
`python manage.py sqlite_startup --prepare-migrations`. Alternatively, open the waiting
container's console and run the same command there. Start Floppy normally afterwards.

## What the result means

- **Finishes without error:** the database passed its checks and a recovery snapshot was
  saved under your backup folder. Restart Floppy.
- **Reports an unresolved recovery incident or foreign-key conflicts:** stop here. Open the
  recovery page Floppy serves and read the report; do not delete files. Ask for help.
- **Times out or errors again:** check free disk space and that the database is on local
  storage, then ask for help.

## Asking for help

Run `docker compose logs floppy` (or `docker logs <container>`; Floppy's own log files are
not the right place) and include the lines starting with `[entrypoint]` and
`[sqlite-`. Remove any secrets first. Also helpful:

```bash
docker exec floppy python manage.py floppy_preflight
```

Ask on [Discord](https://discord.gg/uFgha7Kb6n) or
[open an issue](https://github.com/dannyvfilms/Floppy/issues).

For how startup admission works, see [architecture/sqlite-startup.md](architecture/sqlite-startup.md).
