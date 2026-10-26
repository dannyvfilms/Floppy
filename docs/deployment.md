# Configuration and deployment

The operator reference for running Floppy: Compose by hand, PostgreSQL, Docker Run,
Portainer and Unraid, environment variables, small hosts, upgrades, persistence,
startup recovery and diagnostics, reverse proxies, and image tags.

New to Floppy? The [guided installer](install.md) is the shorter path on Linux,
macOS and Windows. This page is for configuring an installation by hand or
looking something up.

## Docker Compose (recommended)

One stack, app plus Redis. Save it as `docker-compose.yml` and run `docker compose up -d`, or paste it straight into a Portainer stack.


```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    container_name: floppy
    restart: unless-stopped
    stop_grace_period: 150s
    depends_on:
      redis:
        condition: service_healthy
    environment:
      - SECRET=${SECRET:?Set SECRET to a long random signing key}
      - REDIS_URL=redis://redis:6379
      - REGISTRATION=True
      - DEMO_ACCOUNT_ENABLED=False
      - TZ=America/Chicago
      - TMDB_API=your_tmdb_api_key
    volumes:
      - floppy_db:/floppy/db
      - floppy_backups:/floppy/backups
    ports:
      - "8000:8000"
    networks:
      - floppy-net

  redis:
    image: redis:8-alpine
    container_name: floppy-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--save", "", "--maxmemory", "256mb", "--maxmemory-policy", "volatile-lru"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10
    volumes:
      - redis_data:/data
    networks:
      - floppy-net

volumes:
  floppy_db:
  floppy_backups:
  redis_data:

networks:
  floppy-net:
    driver: bridge
```

Open `http://localhost:8000`, create your account, then set `REGISTRATION=False` and redeploy so strangers can't sign up.

The examples above set `DEMO_ACCOUNT_ENABLED=False` for clarity; it is also the default. Set `DEMO_ACCOUNT_ENABLED=True` only if you actually want a shared demo account — it provisions a publicly known `demo` / `demodemo` login after migrations.

That's the whole install. `SECRET` is the only variable you truly must set; `TMDB_API` is what makes movie and TV metadata work, and every other API key is optional until you want that media type. Everything else — Postgres, reverse proxies, the full environment variable list, Docker Run, Portainer specifics — follows below.


## SQLite data paths

Floppy uses these rules when `DB_HOST` is not set:

1. `FLOPPY_DB_PATH` selects the SQLite file.
2. If `FLOPPY_DB_PATH` is not set, Floppy uses
   `FLOPPY_DATA_DIR/db.sqlite3`.
3. If neither variable is set, Floppy uses
   `/floppy/db/db.sqlite3` in the container.

An empty value does not override a path. A relative path starts from the
process working directory. Use absolute paths so that each process uses the
same location.

If `SECRET` and `SECRET_FILE` are not set, the container stores its generated
`secret_key` in `FLOPPY_DATA_DIR`. Floppy stores backups in `BACKUP_DIR`;
`FLOPPY_DATA_DIR` does not change that setting. Logs go to `LOG_DIR`, which
defaults to a `logs` folder inside `FLOPPY_DATA_DIR`, so they sit on the same
volume as the database and survive the container being recreated.

If the container keeps crashing, that folder holds `floppy.log` (application
log, with a memory line every 5 minutes and a note on the next start when the
previous run did not shut down cleanly), `restart-history.log` (one line per
start: whether the last run stopped cleanly, how long it was up and down,
whether the container or version changed, and how long startup took),
`supervisord.log` (which process exited and how) and `faulthandler.log`
(Python traceback after a segfault). A run that "restarts daily" but always
reads "stopped cleanly" was stopped from outside Floppy (a scheduler, backup
job or updater), not crashed. It can be read from the host even while the
container is down. Settings → Advanced → Download Sanitized Logs bundles all
four and redacts known credential
patterns. The download can still contain private activity or unrecognized secrets;
review it before sharing.

If the container is stopped from outside (`docker stop`, a restart, a NAS
scheduled task), the next start logs `Previous run was stopped by SIGTERM`.
Docker kills a container that is still shutting down after 10 seconds by
default, but celery waits up to 60 seconds for a running task, so the compose
files set `stop_grace_period: 150s` (`--stop-timeout 150` for `docker run`). A
stop that is cut short is logged as an unclean shutdown that names the stop
request. If you wrote your own compose file, add the setting to the `floppy`
service.

`BACKUP_DIR` defaults to `/floppy/backups` inside the container. The
Settings → Export page shows this path, but it is a container path, not a
host path — mount it to a host directory or the scheduled CSVs disappear
whenever the container is recreated:

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    volumes:
      - ./backups:/floppy/backups
```

The default `docker-compose.yml` in this repo already includes this mount.
The PostgreSQL example also persists `/floppy/db` for logs and any generated
signing key, and `/floppy/backups` for exports; the database itself lives in
the separate `postgres_data` volume.

`BACKUP_DIR` holds two different things, and only one of them can replace a
damaged `db.sqlite3`:

- `BACKUP_DIR/<username>/floppy_<date>.csv` &mdash; scheduled CSV data
  exports from Settings → Export. These restore media, ratings, and lists via
  **Settings → Import**, but only into an already-working install; they do
  not restore accounts, integration credentials, or preferences, and they
  cannot replace the database file itself.
- `BACKUP_DIR/database/` &mdash; a verified raw snapshot of `db.sqlite3`,
  written on a schedule (`DB_SNAPSHOT_ENABLED`, default on). This is what to
  restore from after physical corruption. When Floppy stops at the
  "cannot read the database file" page, the page lists these snapshots and
  can restore one for you: it checks the snapshot, moves the damaged
  database and its `-wal`/`-shm` files to `sqlite-recovery/` beside
  `db.sqlite3`, and starts Floppy. To do it by hand, stop Floppy, preserve the
  damaged database and any `-wal`/`-shm` files elsewhere, then restore a
  verified snapshot without stale companion files. Keep the original signing key and
  configuration. Restore the matching application version first, verify the
  library and integrations, then upgrade separately.

Raw SQLite snapshots default to 02:37 in `TZ`, with seven completed files kept
(`DB_SNAPSHOT_HOUR`, `DB_SNAPSHOT_MINUTE`, `DB_SNAPSHOT_RETENTION_COUNT`). They
need beat, Redis, a live worker, writable storage and disk headroom. There is
no immediate first-install or guaranteed pre-upgrade snapshot. Check actual
task completion and file freshness; web/container health does not prove a
backup exists. Keep encrypted off-host copies and rehearse restoration with
the matching application, original key and configuration.

CSV exports are partial, unencrypted exports. An interrupted export can leave
an incomplete final file, and exports do not have built-in retention. Verify
completion and importability before relying on one. They are not substitutes
for a verified database snapshot or PostgreSQL dump.

This example stores the SQLite file and the generated key in one mounted
directory:

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    environment:
      FLOPPY_DATA_DIR: /data/floppy
    volumes:
      - ./floppy-data:/data/floppy
    ports:
      - "8000:8000"
```

This example stores the SQLite file in a separate mounted directory:

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    environment:
      FLOPPY_DATA_DIR: /data/floppy
      FLOPPY_DB_PATH: /database/floppy/db.sqlite3
    volumes:
      - ./floppy-data:/data/floppy
      - ./floppy-database:/database/floppy
    ports:
      - "8000:8000"
```

Use a dedicated parent directory when `FLOPPY_DB_PATH` is outside
`FLOPPY_DATA_DIR`. At startup, Floppy changes ownership only on the selected
data, database, and log directory entries and on Floppy's generated key,
SQLite files, and current log file. It does not change unrelated files inside
those directories.

Use local storage or block storage for SQLite. Do not use NFS, SMB/CIFS, or
another network filesystem.

Floppy does not move existing data when you set these variables. Use this
procedure to change a path:

1. Stop the Floppy container.
2. Back up the current SQLite file.
3. Copy the SQLite file to the new path. Copy its `-wal` and `-shm` companion
   files if they are present.
4. Copy the generated `secret_key` to the new data directory. You can set
   `SECRET` instead if you already manage the key outside the data directory.
5. Set the new path variables and mount each selected directory.
6. Start Floppy and confirm that the existing library is present.

If the database file is missing, Floppy creates an empty database. The
deployment can then appear to have lost its library. If the old generated key
is missing, existing sessions and signed data can become invalid, and saved
integration credentials encrypted with that key cannot be decrypted. Preserve
the original key with the database backup; generating a replacement is not a
recovery procedure.

## PostgreSQL

Floppy uses PostgreSQL only when `DB_HOST` is set. Without it, it uses
`FLOPPY_DB_PATH`; the container default is `/floppy/db/db.sqlite3`.
`DATABASE_URL` is not supported — set the individual `DB_*` variables.

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    container_name: floppy
    restart: unless-stopped
    stop_grace_period: 150s
    depends_on:
      - db
      - redis
    environment:
      - SECRET=${SECRET:?Set SECRET to a long random signing key}
      - REDIS_URL=redis://redis:6379
      - DEMO_ACCOUNT_ENABLED=False
      - TZ=America/New_York
      - DB_HOST=db
      - DB_NAME=floppy
      - DB_USER=floppy
      - DB_PASSWORD=change-this-password
      - DB_PORT=5432
    volumes:
      - ./db:/floppy/db
      - ./backups:/floppy/backups
    ports:
      - "8000:8000"
    networks:
      - floppy-net

  db:
    image: postgres:16-alpine
    container_name: floppy-db
    restart: unless-stopped
    environment:
      - POSTGRES_DB=floppy
      - POSTGRES_USER=floppy
      - POSTGRES_PASSWORD=change-this-password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - floppy-net

  redis:
    image: redis:8-alpine
    container_name: floppy-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--save", "", "--maxmemory", "256mb", "--maxmemory-policy", "volatile-lru"]
    volumes:
      - redis_data:/data
    networks:
      - floppy-net

volumes:
  postgres_data:
  redis_data:

networks:
  floppy-net:
    driver: bridge
```

> Already running Postgres with `DB_NAME=yamtrack`? Leave those values alone. Renaming the database, role, or password against an existing volume breaks the deployment.

PostgreSQL backups are operator-managed; Floppy's raw SQLite snapshot task does
not back up PostgreSQL. Use a consistent `pg_dump`, check its exit status before
retaining the archive, and test restoration into a separate empty database with
`pg_restore --exit-on-error --no-owner` for custom-format dumps. A failed restore
can leave partial objects: recreate that disposable destination before retrying.
Preserve required roles/extensions, the original signing key and configuration;
encrypt off-host copies. An ordinary live PostgreSQL volume copy is not a
consistent database backup, and an older image cannot undo migrated data.

## Docker Run

No compose file needed:

```bash
docker network create floppy-net

docker run -d \
  --name floppy-redis \
  --network floppy-net \
  --restart unless-stopped \
  -v floppy-redis-data:/data \
  redis:8-alpine \
  redis-server --appendonly yes --save "" --maxmemory 256mb --maxmemory-policy volatile-lru

docker run -d \
  --name floppy \
  --network floppy-net \
  --restart unless-stopped \
  --stop-timeout 150 \
  -e ALLOWED_HOSTS=floppy.yourdomain.com,your.lan.ip.address \
  -e DEBUG=False \
  -e DEMO_ACCOUNT_ENABLED=False \
  -e IGDB_ID=your_igdb_client_id \
  -e IGDB_SECRET=your_igdb_client_secret \
  -e LASTFM_API_KEY=your_lastfm_api_key \
  -e MAL_API=your_mal_client_id \
  -e PGID=1000 \
  -e PUID=1000 \
  -e REDIS_URL=redis://floppy-redis:6379 \
  -e REGISTRATION=True \
  -e SECRET=your_django_secret_key \
  -e TMDB_API=your_tmdb_api_key \
  -e TVDB_API_KEY=your_tvdb_api_key \
  -e TZ=America/Chicago \
  -v floppy-db:/floppy/db \
  -v floppy-backups:/floppy/backups \
  -p 8000:8000 \
  ghcr.io/dannyvfilms/floppy:latest
```

Leave `REGISTRATION=True` for your first run, then recreate the container with `False` once your account exists.

## Portainer and Unraid

Prefer **Stacks** over **Containers → Add container**. Stacks let you paste a complete Compose configuration and avoid missing required volumes or environment variables. This is also the recommended path for **Unraid**: rather than installing from a Community Applications template and standing up Redis separately, paste one compose file into a stack via the Portainer plugin and both containers come up together.

1. Go to **Stacks** → **Add Stack**
2. Name it `floppy`
3. Paste one of the compose configurations above
4. Set `SECRET` to a secure random string, and fill in whichever metadata API keys you have
5. Deploy the stack
6. Create your account while `REGISTRATION=True`, then set it to `False` and redeploy

If you use **Containers → Add container** anyway: always set `SECRET` and `REDIS_URL`; for SQLite mount persistent storage to `/floppy/db`; for PostgreSQL set the `DB_*` variables on the Floppy container and persist `/var/lib/postgresql/data` on the Postgres container; publish port `8000`; and leave `Command` and `Entrypoint` empty.

## Floppy can't reach Redis

**Symptoms:** imports say they could not be queued, or the logs show
`Name does not resolve`, `Name or service not known`, or
`Error -2 connecting to redis:6379`.

**Cause:** Floppy finds Redis by its service name, `redis` in
`REDIS_URL=redis://redis:6379`. Docker resolves service names only on a
user-defined network. Some tools (ZimaOS, CasaOS, and some Portainer setups)
place the containers on Docker's default `bridge` network instead, or add
`network_mode: bridge`. On that network the name `redis` does not resolve.

**Fix:** declare a shared network, as the compose files above do. Add this to
every service in the stack (Floppy, Redis, and Postgres if you use it):

```yaml
    networks:
      - floppy-net
```

Then add this once at the bottom of the file:

```yaml
networks:
  floppy-net:
    driver: bridge
```

Remove any `network_mode:` line, then redeploy the stack. Alternatively, set
`REDIS_URL` to an address the Floppy container can reach, such as the host's
IP and Redis's published port.

**Check:** `docker exec floppy python manage.py floppy_preflight` names the
problem and reports `redis: ok` once Floppy can reach Redis.

## Environment variables

The only universally required variable is `SECRET`. For Docker installs you should also set `REDIS_URL`.

**Optional but recommended:**

- `TMDB_API` - movie and TV metadata from [TMDB](https://www.themoviedb.org/settings/api)
- `TVDB_API_KEY` / `TVDB_PIN` - TVDB-backed metadata and grouped anime support (`TVDB_PIN` is your **Subscriber PIN**, only required for user-supported API keys)
- `MAL_API` - MyAnimeList **Client ID** for anime metadata ([register here](https://myanimelist.net/apiconfig))
- `IGDB_ID` / `IGDB_SECRET` - game metadata from [IGDB](https://www.igdb.com/api)
- `STEAM_API_KEY` - Steam game imports
- `BGG_API_TOKEN` - board game metadata from [BoardGameGeek](https://boardgamegeek.com/using_the_xml_api)
- `HARDCOVER_API` - Hardcover book metadata/imports. **Required to use Hardcover** ([generate a token](https://hardcover.app/account/api)); Hardcover meters its free tier per account (5000 requests/day), so Floppy ships no shared default and book search falls back to Open Library without one. Individual users can also set a personal token in their own settings.
- `GOOGLE_BOOKS_API_KEY` - optional Google Books book metadata ([Google Books API](https://developers.google.com/books/docs/v1/using)); supports `GOOGLE_BOOKS_API_KEY_FILE` for Docker secrets
- `OPENCRITIC_API_KEY` - optional OpenCritic critic scores for games, from a [RapidAPI key](https://rapidapi.com/opencritic-opencritic-default/api/opencritic-api). The free plan (25 searches and 200 requests a day) is enough: a score is fetched when a game page is opened, and quota left over in the hour before the daily reset fills in tracked games. Supports `OPENCRITIC_API_KEY_FILE`; can also be set in Settings > Metadata
- `COMICVINE_API` - comic metadata
- `MANGABAKA_NSFW` - optional, set to `true` to include erotica and pornographic series in [MangaBaka](https://mangabaka.org/) manga search results. MangaBaka needs no API key and is available as a manga source next to MyAnimeList and MangaUpdates; light novels are left out
- `GCD_USERNAME` / `GCD_PASSWORD` - optional [Grand Comics Database](https://www.comics.org/) comic metadata, as a second comic source next to Comic Vine. Use a free GCD account: GCD limits anonymous API access to 30 requests an hour, so Floppy ships no shared default and the source stays hidden until a login is set. Support `GCD_USERNAME_FILE` / `GCD_PASSWORD_FILE` for Docker secrets; can also be set in Settings > Metadata, then chosen as the default comic source there
- `STEAMGRIDDB_API_KEY` - optional [SteamGridDB](https://www.steamgriddb.com/profile/preferences/api) key. Adds logos and background art for PC, console, retro and non-Steam games on game pages. Supports `STEAMGRIDDB_API_KEY_FILE`; can also be set in Settings > Metadata
- `THEGAMESDB_API_KEY` - optional [TheGamesDB](https://forums.thegamesdb.net/viewforum.php?f=10) key for clear logos and fanart. Supports `THEGAMESDB_API_KEY_FILE`; can also be set in Settings > Metadata
- `SCREENSCRAPER_DEV_ID` / `SCREENSCRAPER_DEV_PASSWORD` / `SCREENSCRAPER_SOFTNAME` - [ScreenScraper](https://www.screenscraper.fr/) developer credentials, which ScreenScraper issues to an application rather than a person. With them set, retro games get ScreenScraper logos and fanart without any member account; without them ScreenScraper stays off. Read only from the environment or `_FILE` secrets (`SCREENSCRAPER_DEV_ID_FILE`, `SCREENSCRAPER_DEV_PASSWORD_FILE`), never shipped with Floppy. `SCREENSCRAPER_SSID` / `SCREENSCRAPER_SSPASSWORD` are an optional ScreenScraper login that raises personal limits; they can also be set in Settings > Metadata
- `WETRAKR_CLIENT_ID` - optional [WeTrakr](https://api.wetrakr.com/) application key, for sending plays, statuses and ratings out to WeTrakr. Floppy ships no shared key: bring your own here, or each member can paste theirs in Settings > Metadata. Supports `WETRAKR_CLIENT_ID_FILE`; see [WeTrakr](integrations/wetrakr.md)
- `LASTFM_API_KEY` - Last.fm integration and scrobble polling
- `MUSICBRAINZ_URL` - custom MusicBrainz-compatible API root, including `/ws/2` (defaults to `https://musicbrainz.org/ws/2`)
- `TRAKT_API` / `TRAKT_API_SECRET` - Trakt private-profile OAuth imports
- `URLS` - your public URL if using a reverse proxy, for example `https://floppy.mydomain.com`
- `ADMIN_ENABLED` - set to `True` to enable the Django admin interface at `/admin/` (see the [Admin Guide](https://github.com/dannyvfilms/Floppy/wiki/6.-Admin-and-Operations#admin-guide))
- `WEB_CONCURRENCY` / `GUNICORN_THREADS` - optional web server concurrency overrides. Leave both unset to use the detected host profile, especially on small or swapless hosts. Total concurrent requests = workers x threads
- `FLOPPY_RESOURCE_TIER` - `standard`, `constrained`, or `minimal`. Floppy normally detects this from the host's memory, swap and CPU and scales its process count, batch sizes and background task cadence to match, so you should not need to set it. Use it to force a tier if detection guesses wrong - for example `standard` on a host whose cgroup understates the memory actually available
- `FLOPPY_REDIS_MAXMEMORY` - Redis memory ceiling Floppy applies at startup when Redis has none of its own, as bytes or a size like `256mb`. Set it to `0` to leave your Redis configuration completely untouched. Floppy never overrides a `maxmemory` you set yourself
- `REDIS_CACHE_URL` - Redis service for the Django cache and cached sessions. The default is `REDIS_URL`
- `CELERY_BROKER_URL` - Redis service for queued Celery work. The default is `REDIS_URL`
- `CELERY_RESULT_BACKEND` - Redis service for Celery results. The default is `REDIS_URL`
- `REDIS_ADMIN_URL` - Redis service that Floppy can tune with `CONFIG`. The default is `REDIS_CACHE_URL`, then `REDIS_URL`
- `DEBUG` - leave unset or `False` in production; enabling it slows every request (debug toolbar, no template caching) and is only meant for troubleshooting
- Anime routing across scrobblers and importers - see the [grouped anime guide](grouped_anime.md)
- `REGISTRATION` - set to `True` to allow new signups (needed for your first account), then set to `False` afterward
- `DEMO_ACCOUNT_ENABLED` - defaults to `False`. Set it to `True` to provision the built-in `demo` / `demodemo` account after migrations (shared-demo installs only). The setting gates provisioning; an account that already exists stays until you deactivate or delete it — `python manage.py floppy_preflight` warns when a known-password demo login is active
- `ALLOWED_HOSTS` / `PUID` / `PGID` - `ALLOWED_HOSTS` is a comma-separated list of hostnames/IPs Django will accept requests for; `PUID` / `PGID` set the file-ownership user/group inside the container (match your host user, e.g. Unraid's `99`/`100`, if you hit permission errors)

For the complete list, see the [Environment Variables documentation](https://github.com/dannyvfilms/Floppy/wiki/6.-Admin-and-Operations#environment-variables).

Example `.env` file:

```bash
TMDB_API=API_KEY
TVDB_API_KEY=TVDB_API_KEY
TVDB_PIN=SUBSCRIBER_PIN (Optional, only for user-supported keys)
MAL_API=CLIENT_ID
IGDB_ID=IGDB_ID
IGDB_SECRET=IGDB_SECRET
STEAM_API_KEY=STEAM_API_SECRET
BGG_API_TOKEN=BGG_API_TOKEN
HARDCOVER_API=HARDCOVER_API
GOOGLE_BOOKS_API_KEY=GOOGLE_BOOKS_API_KEY
COMICVINE_API=COMICVINE_API
LASTFM_API_KEY=LASTFM_API_KEY
SECRET=SECRET
DEBUG=False
```

## Use separate Redis services

The standard configuration needs only `REDIS_URL`. Use the role settings when
cache data and Celery data must use separate Redis services.

```bash
REDIS_URL=redis://limiter:6379/0
REDIS_CACHE_URL=redis://cache:6379/0
CELERY_BROKER_URL=redis://broker:6379/0
CELERY_RESULT_BACKEND=redis://results:6379/0
REDIS_ADMIN_URL=redis://cache:6379/0
```

Floppy applies these rules:

1. `REDIS_CACHE_URL` uses `REDIS_URL` when it is empty or not set.
2. `CELERY_BROKER_URL` uses `REDIS_URL` when it is empty or not set.
3. `CELERY_RESULT_BACKEND` uses `REDIS_URL` when it is empty or not set.
4. `REDIS_ADMIN_URL` uses `REDIS_CACHE_URL`, then `REDIS_URL`.
5. The provider rate limiter continues to use `REDIS_URL`.

Use a `redis://` or `rediss://` URL for Redis administration. Floppy skips
automatic tuning when `REDIS_ADMIN_URL` uses another scheme. Set
`FLOPPY_REDIS_MAXMEMORY=0` to stop all automatic Redis tuning.

Redis `CONFIG` changes the complete Redis server. A database number in a Redis
URL does not isolate this change. `REDIS_ADMIN_URL` must normally select the
cache Redis server. Grant `CONFIG` access only when you want Floppy to manage
the memory limit and change `appendfsync=always` to `everysec`. You can also
configure the Redis server directly.

Plan a service change before you select new URLs:

1. Let queued work finish before you change `CELERY_BROKER_URL`. A new broker
   does not receive queued or unacknowledged work from the old broker.
2. Preserve results that you still need before you change
   `CELERY_RESULT_BACKEND`. The new backend does not contain old results.
3. Expect the new cache to start empty. Floppy reloads sessions from its
   database after a cache miss. Accounts and active sessions remain present.
4. Restart the web, worker, and beat processes together. This makes all
   processes use the same configuration.

## Running on a small host

Floppy sizes itself to the machine it finds. On startup it reads the container's cgroup
memory and CPU limits plus `/proc/meminfo`, picks a resource tier, and scales its process
count, batch sizes, and background task cadence accordingly. The chosen tier and effective
Celery worker topology are logged on the first line of the container's output:

```
[entrypoint] resources tier=minimal mem=1.9GiB swap=0 cpus=2 -> gunicorn 1x2, celery workers background=on(celery,interactive,discover) interactive=off(combined) discover=off(merged)
```

- **standard** (3 GB+): one threaded gunicorn worker and two Celery workers. Discover and
  beat run with the background worker; the interactive worker stays separate so webhook
  scrobbles are never stuck behind a backfill.
- **constrained** (under 3 GB): the same lean process layout as standard, with smaller
  worker-recycling and cache budgets.
- **minimal** (under 1.5 GB): one gunicorn worker and a single Celery worker serving every
  queue.

**On a small host, swap matters as much as the memory figure.** Each Celery worker holds
its own full copy of the application, so below about 6 GB a host with no swap gets bumped
one tier stricter — a memory spike with nowhere to page is what turns a slow container
into a hung one. If you have disabled swap to spare an SSD, 2 GB of RAM lands on
`minimal`, which is supported. Above 6 GB, missing swap changes nothing.

Two things worth knowing:

- If you set no `mem_limit` on the Floppy container, it sees the whole host's memory. That
  is usually what you want on a dedicated VM. On a shared host, set `mem_limit` so Floppy
  sizes itself to its share rather than to the machine.
- Floppy gives Redis a memory ceiling and an LRU eviction policy at startup if Redis has
  none of its own, so an unbounded cache can't exhaust the host. It never overrides a
  `maxmemory` you configured yourself. Run `docker exec floppy python manage.py tune_redis
  --dry-run` to see what it would do.

Override any of it with `FLOPPY_RESOURCE_TIER`, `WEB_CONCURRENCY`, `GUNICORN_THREADS`, or
`FLOPPY_REDIS_MAXMEMORY`.

To verify the standard-tier worker split in a disposable Compose project after building an
image, run:

```bash
scripts/smoke_worker_topology.sh --image floppy:worker-topology
```

## Measuring container memory

Use `scripts/benchmark_memory.sh` to compare two already-built Floppy images without
touching an existing deployment. It starts each image in its own disposable Compose project
with SQLite, samples the healthy warmed container three times, and writes CSV/JSON reports
under a temporary directory:

```bash
scripts/benchmark_memory.sh \
  --baseline-image floppy:baseline \
  --candidate-image floppy:memory-test
```

The report distinguishes cgroup usage from summed process PSS/RSS and Redis usage, so shared
preloaded pages and the separate Redis container are visible instead of being counted as a
single opaque number. It also splits each process's proportional memory into anonymous,
file-backed and shared parts, which is what separates private heap a process is really using
from page cache and preloaded pages it merely shares. Build the candidate image locally
before running the comparison.

To measure a running container instead of a disposable one, pipe the sampler into it:

```bash
docker exec -i floppy python - < scripts/container_memory_sample.py
```

`scripts/` is not part of the image, so the script is fed over standard input. Outside the
benchmark stack the container has no `CAP_SYS_PTRACE`, so `/proc/<pid>/smaps_rollup` is
unreadable and those processes are reported with `"measurement": "rss-only"` — RSS only, with
the proportional counters null and `process_pss_complete` false. The sampler reports the
command name of each process but never its arguments, which can carry connection details.

If an existing deployment has `WEB_CONCURRENCY` or `GUNICORN_THREADS` set from an
older fixed-size configuration, remove those overrides before upgrading on a
small host so the automatic resource profile can take effect.

## Non-Docker Gunicorn installs

Source-based deployments must load Floppy's Gunicorn configuration so the
host-derived worker settings and database/Redis fork-safety hooks are active:

```bash
cd /path/to/floppy/src
uv run --no-sync gunicorn --config python:config.gunicorn config.wsgi:application
```

Do not start the service with bare `gunicorn config.wsgi:application`; that
skips the shipped configuration and its process lifecycle hooks.

Before upgrading a pickle-era installation, follow the
[Celery JSON transition procedure](security-hardening.md#celery-json-transition)
while the old code and workers are still available. Stop submissions and beat,
drain all old queues, then stop the old workers before changing code. Undrained
jobs can be discarded without a failure status; an ordinary restart does not
recover them. This also applies to the source installers on Linux and macOS.

When upgrading a source-based install, run `uv sync --locked --no-default-groups`
after `git pull` and before restarting gunicorn/Celery — the same flag the
[Dockerfile](../Dockerfile) uses, so the runtime dependency set matches the
container image instead of also pulling in lint/test tooling. `pyproject.toml`
and `uv.lock` are the dependency source of truth (see "Local development"
below); skipping this step after a `git pull` leaves new dependencies
uninstalled and can crash Celery with a `ModuleNotFoundError` at runtime.

Gunicorn does not write a request access log. A request line holds the query
string, and a query string can hold an OAuth code or an integration token, so
the container writes one access line at the Nginx boundary instead, with the
path, query string and referrer removed. Gunicorn still writes its error log.

A source-based deployment therefore gets its request log from its own reverse
proxy. Configure that proxy to omit paths, query strings and referrers, since
bearer tokens can also appear in path segments.
The container's format is in `nginx.conf`:

```nginx
log_format floppy_safe '$remote_addr [$time_local] '
                       '"$request_method $server_protocol" '
                       '$status $body_bytes_sent';
```

Application logs are separate and redact known credential patterns before they
are written. They can still contain usernames, media titles and activity;
review downloaded logs before sharing them.
See [docs/architecture/log-redaction.md](architecture/log-redaction.md).

## Upgrading container images

For SQLite upgrades with pending migrations, the container takes a verified
recovery snapshot [automatically at startup](architecture/sqlite-startup.md#pending-migrations-automatic-snapshot-at-startup)
before migrating. Set `FLOPPY_SQLITE_AUTO_SNAPSHOT=false` to require
[offline migration preparation](architecture/sqlite-startup.md#pending-migrations-explicit-offline-preparation)
instead. Routine restarts with no pending migrations do not require this.

**Before pulling or recreating a pickle-era deployment**, complete the
[Celery drain procedure](security-hardening.md#celery-json-transition)
using the old image and configuration. Ordinary pull/recreate commands do not
drain queued, reserved or scheduled jobs; JSON-only workers discard old pickle
messages. Retain import inputs and review partial imports before resubmitting.
Do not use a mixed-version rolling upgrade for this transition.

The migration conflict involving `0147_item_calendar_checked_at` and
`0148_merge_duplicate_item_buckets` is fixed in current images by the
`0149_merge_20260806_1556` merge migration. Pull the updated image before
restarting instead of generating a local merge migration:

```bash
docker compose pull floppy
docker compose up -d --force-recreate floppy
```

Channel and version tags can move. For a fixed deployment, use a verified image digest;
see [verifying a published image](#verifying-a-published-image-actually-has-a-fix).
Maintainers should use the [release checklist](releasing.md), which also
lists the upgrade notices to include with the next hardened release.

## Persistence checklist

- SQLite stores the app database at `/floppy/db/db.sqlite3` by default. Persist
  `/floppy/db`, or persist each configured SQLite data path. Pre-rename
  `/yamtrack/db` mounts still resolve, so existing setups keep working.
- **Do not put the SQLite file on a network filesystem** such as NFS, SMB/CIFS,
  or a NAS share that is mounted into Docker. Floppy uses SQLite WAL mode.
  [SQLite documents](https://sqlite.org/wal.html) that WAL does not work over a
  network filesystem. Use local storage or block storage. Set `DB_HOST` to use
  PostgreSQL if only network storage is available.
- PostgreSQL stores its database files at `/var/lib/postgresql/data`; persist that path on the Postgres container.
- Redis stores sessions and background-task state; resetting Redis can log users out, but it should not delete accounts if the database is persisted.
- Do not assume `DATABASE_URL` enables PostgreSQL. Floppy uses Postgres only when `DB_HOST` is set.

## SQLite startup recovery

Normal restarts use a bounded schema/incident check, with no full-database
warming or integrity scan. Pending migrations require an unchanged recovery
snapshot verified offline against both structural and relational failures.
See [SQLite startup and migration preparation](architecture/sqlite-startup.md)
for the preparation command, background verifier and exact blocking conditions.

This section covers a broken *relationship* between rows, which Floppy can
often repair during explicit offline maintenance. Physical corruption of the file itself is a
different failure: the startup log and recovery page say "Floppy cannot read
the database file," and the fix is to restore a copy of the file, not repair
rows. `sqlite-recovery/` below does not help there, because it is only ever
written while repairing a relationship; use `BACKUP_DIR/database/` instead
(see the SQLite data paths section above).

Stop all database writers and use `python manage.py sqlite_startup --recover`
in a one-off container with the same image and mounts. This invokes the
existing backup-protected recovery policy. If that check finds an album artist credit whose album or artist no longer
exists, Floppy creates a verified backup, removes only that invalid credit,
and checks the database again.

For any other relationship conflict, Floppy writes a bounded report beside
the database as `db.sqlite3.integrity.json`. The report counts every conflict
but includes at most 20 row samples, so a large incident cannot fill the log.
Startup then remains idle and unhealthy without running migrations or services;
this prevents Docker restart policies from repeating the same failure.

The report identifies the incident with a fingerprint and issues a separate
one-time **incident token**. The startup log prints the exact value to set, and
the report repeats it under `actions`. Copy the approval code from the startup
log, or use the matching `incident_token`/`actions` entry in the protected
report; the fingerprint is an identifier, not an approval. There are two
choices:

1. **Restore or repair:** stop Floppy, back up the database with its `-wal` and
   `-shm` files, then restore a known-good copy or repair the named rows.
2. **Quarantine:** set
   `FLOPPY_SQLITE_CONFLICT_ACTION=quarantine:<incident-token>` for the offline
   `sqlite_startup --recover` command. Floppy first writes and verifies a full backup under
   `sqlite-recovery/`, then removes the orphaned child rows and verifies all
   relationships again. Floppy refuses to quarantine a table that has no usable
   SQLite row ID or that carries any trigger; the log names the reason and those
   rows must be repaired manually.

A token is issued per incident and retired once that incident is resolved, so an
old approval cannot apply to a later or changed incident. Remove
`FLOPPY_SQLITE_CONFLICT_ACTION` after a successful start. Backups under
`sqlite-recovery/` are kept until you remove them. Do not delete the live
database or its `-wal` or `-shm` files.

If the log says that the database is busy, another process still holds a
write lock. Stop that process, then restart Floppy. Do not delete the database
or its lock files to resolve this conflict.

## Startup diagnostics

`floppy_preflight` answers one question: can this installation start? It checks
the data paths, the settings, the database, the migrations and every Redis
endpoint, then reports each result and exits non-zero if any check failed.

Use it when the container does not start. Which command to use depends on what
the container is doing:

```bash
# The container runs, but it is unhealthy or idle.
docker exec floppy python manage.py floppy_preflight

# The container restarts or has exited.
docker compose run --rm floppy python manage.py floppy_preflight
```

`docker exec` attaches to a running container, so it cannot reach one that keeps
restarting. Docker answers `Container is restarting, wait until container is
running`; Podman kills the attempt instead and returns exit code 137. Use the
second command in either case. It starts a one-off container that reads the same
volumes, and it replaces the startup script instead of running after it, so the
check runs even when startup is what fails.

Both commands work with `podman` in place of `docker`.

The `docker exec` form above uses the container's Compose service name
(`container_name: floppy`). If you run outside Compose, or under an
orchestrator that renames containers on every recreation (for example
Unraid), set `HOST_CONTAINERNAME` to a name that survives recreation; the
startup log's diagnostic hint and the SQLite recovery page both use it
instead of the container's own, per-instance Docker ID. Verify the name you
are about to use actually matches the running container:

```bash
docker inspect --format '{{.Id}} {{.Name}} {{.Config.Image}}' <container>
```

For a source install, load the environment first. All `manage.py` commands need
`SECRET`:

```bash
SECRET=your-secret uv run --no-sync python src/manage.py floppy_preflight
```

Each check reports one of four results:

| Result | Meaning | Effect on the exit code |
|--------|---------|-------------------------|
| `ok` | The check passed. | none |
| `warn` | Floppy can start, but there is a risk. | none |
| `FAIL` | Floppy cannot start until you correct this. | exit code 1 |
| `skip` | The check did not run. | none |

A failure names the problem, the cause, and what to do. Each instruction starts
with the place to do it: `[HOST]` for the machine that runs Docker, `[COMPOSE]`
for the stack definition, and `[CONTAINER]` for a shell inside Floppy. An
example:

```
paths      ok    /floppy/db (12.4 GB free)
config     ok    no settings errors
database   ok    sqlite storage and relationships are intact
migrations ok    none pending
redis      FAIL  cannot reach redis://redis:6379/0 (celery broker)
                 cause: Error 111 connecting to redis:6379. Connection refused.
                 fix:   [COMPOSE] check that the Redis service is running and reachable
preflight: failed (redis)
```

Options:

| Option | Effect |
|--------|--------|
| `--json` | Print one JSON object and nothing else. |
| `--no-redis` | Do not check Redis. |
| `--auto-migrate` | Apply the pending migrations, then check again. |
| `--timeout SECONDS` | Bound the database storage check (default 600 seconds). Startup does not use a fixed bound. It stops its own check only when the check stops making progress; see `docs/architecture/sqlite-recovery-decisions.md`. |

The command reads only. `--auto-migrate` is the one exception, and it is for an
operator at a terminal. Containers do not need it, because the startup sequence
already applies migrations and retries them.

`--json` prints a `version` field. This number increases only when a key is
removed or renamed. New keys do not change it, so a supervisor that reads the
current keys keeps working.

Use `--json` for a systemd unit that must not start Floppy on a broken
installation:

```ini
[Service]
ExecStartPre=/path/to/.venv/bin/python /path/to/src/manage.py floppy_preflight --json
ExecStart=/path/to/.venv/bin/gunicorn --config python:config.gunicorn config.wsgi:application
```

There is one failure `floppy_preflight` cannot report. If the data directory
denies access to the container user, Django stops while it loads its settings,
which is before this command starts. The startup log reports that condition
directly.

### If the SQLite startup check times out

Admission stops after 30 seconds instead of running a multi-hour scan. Check
the command's diagnosis and storage/lock state. A timeout alone is not a
corruption finding and does not force a scan on the next ordinary restart.
Full verification runs independently after startup or through explicit,
bounded maintenance. Its phase/results live in `<database>.verification.json`;
the container logs report deadline failures. The old recovery scanner's
progress telemetry remains available when explicitly running `--recover`.
See the [startup workflow](architecture/sqlite-startup.md) before retrying
pending migrations or recovery.

### Verifying a published image actually has a fix

When a fix to this startup path ships, confirm the image you pulled actually
contains it before relying on it in production:

```bash
# Pull the exact digest you intend to run, not just a moving tag.
docker pull ghcr.io/dannyvfilms/floppy@sha256:<digest>

# Confirm the baked-in build identity.
docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' ghcr.io/dannyvfilms/floppy@sha256:<digest> | grep -E '^(VERSION|COMMIT_SHA)='

# Run it once, disposably, and check the startup identity line and, if you
# can trigger one, the heartbeat/timeout behavior described above.
docker run --rm ghcr.io/dannyvfilms/floppy@sha256:<digest> 2>&1 | grep 'Floppy runtime:'
```

If a moving tag such as `latest` still reports an older `COMMIT_SHA` after a
verified publish and `docker inspect --format '{{.Id}}'` on the running
container matches the freshly pulled image, that is not a registry or image
problem. It means something in the container's runtime environment — a
value an orchestrator (Portainer, Compose) persisted in a stack's `.env` and
keeps re-applying, or a leftover manual `docker run -e` — is setting
`VERSION`/`COMMIT_SHA` explicitly and shadowing the image's own build
identity. `entrypoint.sh` restores both from `/etc/floppy-build-info`, a file
baked into the image at build time that a runtime environment variable
cannot override, before anything reads either one; the running container's
own identity line and `/api/v1/info/` should reflect the real build
regardless of what the orchestrator's `.env` still says. If they do not,
check `docker exec <container> cat /etc/floppy-build-info` against the
digest you pulled before assuming the image itself is stale.

## Grouped anime migration diagnostics

Grouped anime conversion validates provider data before it writes and commits
the grouped show, seasons, episode history, provider links, preference, and old
MAL-row markers together. A retry after a successful conversion is a no-op.

If Floppy reports `ANIME-MIGRATION-STALE-001`, reload the page and try again so
it can validate the current source row. For `ANIME-MIGRATION-PARTIAL-001` or
`ANIME-MIGRATION-AMBIGUOUS-001`, leave the existing rows unchanged, back up the
database, and include the code when asking for support. Floppy deliberately
does not guess whether coexisting episode rows are migration residue or a
legitimate rewatch.

## Trakt private profile import (OAuth)

If you import from a private Trakt profile, configure OAuth first:

1. Create an app in [Trakt API Apps](https://trakt.tv/oauth/applications).
2. Add this Redirect URI in the Trakt app:
   - `https://your_domain.com/import/trakt/private`
3. Set these environment variables:
   - `TRAKT_API` = your Trakt client ID
   - `TRAKT_API_SECRET` = your Trakt client secret

Behind a reverse proxy, also set `URLS=https://your_domain.com` so Floppy generates the correct external callback URL.

### Instances not served over HTTPS

Trakt rejects any redirect URI that is not HTTPS, unless the host is loopback
(`localhost` or `127.0.0.1`). If Floppy is reached over plain HTTP at a LAN
address such as `http://192.168.1.50:8000`, the browser redirect flow cannot
work at all.

Floppy detects this and uses Trakt's device code flow instead: it shows you an
8-character code to enter at [trakt.tv/activate](https://trakt.tv/activate). In
that case set the Trakt app's Redirect URI to `urn:ietf:wg:oauth:2.0:oob`.

Set `URLS=https://your_domain.com` if you would rather use the one-click browser
flow.

If scheduled Trakt imports fail with "Trakt rejected the token refresh", the
Redirect URI on your Trakt app does not match the one Floppy used when you
connected. Set `URLS=https://your_domain.com`, make sure the Trakt app lists
`https://your_domain.com/import/trakt/private`, and reconnect Trakt.

## Reverse proxy setup

If you are behind a reverse proxy (Nginx, Traefik, Caddy, and so on) and see a `403 Forbidden`, add your URL to the environment:

```yaml
environment:
  - URLS=https://floppy.mydomain.com
```

Multiple origins can be comma-separated, for example `https://floppy.mydomain.com,https://floppy-alt.mydomain.com`.

If callback URLs for AniList and other imports come out wrong, add:

```yaml
environment:
  - USE_X_FORWARDED=True
```

> **Note:** With a Cloudflare Tunnel or any HTTPS-terminating proxy, also set `USE_X_FORWARDED_PROTO=True` — otherwise Django cannot detect the correct scheme and CSRF checks will fail.

## Troubleshooting: I updated and my login is gone

1. If you intended to use PostgreSQL, confirm `DB_HOST` is set. `DATABASE_URL` alone will not enable Postgres.
2. If you intended to use SQLite, confirm `/floppy/db` (or the legacy `/yamtrack/db`) is mounted to persistent storage.
3. If you were only logged out but can sign in again, Redis/session data was reset; your account database is still intact.
4. Do not remove database volumes during updates unless you intentionally want a fresh install.

## Docker image tags

The image lives at `ghcr.io/dannyvfilms/floppy`:

- `:latest` - the latest commit on the `latest` branch
- `:release` - the latest commit on the `release` branch, or the stable alias for a GitHub release tag
- `:X.Y.Z` - versioned release builds from GitHub `vX.Y.Z` tags (the image tag omits `v`)
