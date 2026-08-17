<p align="center">
  <img alt="Floppy — everything in one place" src="docs/brand/floppy-wallpaper.png" width="880" />
</p>

<p align="center">
  <b>Self-hosted media tracking for people who miss Trakt and TV Time.</b><br>
  Movies, TV, anime, manga, books, comics, games, board games, music, and podcasts. <br>
  One library, one history, and one set of stats for everything you watch, read, play, or listen to.
</p>

<p align="center">
  <a href="https://yamtrack.dannyvfilms.com">Demo</a> ·
  <a href="https://github.com/dannyvfilms/Floppy/pkgs/container/floppy">Docker Image</a> ·
  <a href="https://discord.gg/uFgha7Kb6n">Discord</a> ·
  <a href="https://github.com/dannyvfilms/Floppy/wiki">Wiki</a> ·
  <a href="https://github.com/dannyvfilms/Floppy/releases">Releases</a> ·
  <a href="https://github.com/dannyvfilms/Floppy/issues">Report a Bug</a>
</p>

Floppy is a self-hosted, all-in-one media tracker and personal media diary, a broader alternative to Trakt, Letterboxd, and TV Time for people who want one place for everything they watch, read, play, or listen to. It gives you a real progress view that tells you what to watch next, a unified history you can actually scan, recap-style statistics, shareable lists, owned-media collections, and integrations that sync instead of asking you to upload a file every few months.

It runs in Docker, keeps your data on your own hardware, and treats music and podcasts as first-class media rather than bolt-ons.

**Try it first:** the [demo instance](https://yamtrack.dannyvfilms.com) is open with `demo` / `demodemo`.

*Floppy was formerly published as the `dannyvfilms/Yamtrack` fork. Old links redirect here.*

## Install

One stack, app plus Redis. Save it as `docker-compose.yml` and run `docker compose up -d`, or paste it straight into a Portainer stack.

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    container_name: floppy
    restart: unless-stopped
    depends_on:
      redis:
        condition: service_healthy
    environment:
      - SECRET=change_me_to_a_long_random_string
      - REDIS_URL=redis://redis:6379
      - REGISTRATION=True
      - DEMO_ACCOUNT_ENABLED=False
      - TZ=America/Chicago
      - TMDB_API=your_tmdb_api_key
    volumes:
      - floppy_db:/floppy/db
    ports:
      - "8000:8000"

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

volumes:
  floppy_db:
  redis_data:
```

Open `http://localhost:8000`, create your account, then set `REGISTRATION=False` and redeploy so strangers can't sign up.

`DEMO_ACCOUNT_ENABLED=False` is set above on purpose: it otherwise defaults to `True` and provisions a publicly known `demo` / `demodemo` login after migrations. Leave it off unless you actually want a shared demo account.

That's the whole install. `SECRET` is the only variable you truly must set; `TMDB_API` is what makes movie and TV metadata work, and every other API key is optional until you want that media type. Everything else — Postgres, reverse proxies, the full environment variable list, Docker Run, Portainer specifics — is in [Configuration and deployment](#configuration-and-deployment) further down.

## What Floppy does

Floppy combines the jobs people often split between a watchlist, a media diary, and an owned-media collection: Time Left progress, a unified history feed, recap-style stats, public list sharing, and all-in-one tracking across every media type you care about.

### The big pieces

- **Music**: artist and album pages, track-level history and scoring, play-count and listening-time statistics, bulk save and mark-all-listened; MusicBrainz-backed metadata with discography sync and cover art; fully native in history, search, home rows, and collection, not a thin importer.
- **Podcasts**: dedicated show and episode pages, episode-level tracking, mark-all-played; Pocket Casts account sync as a live integration, not a one-shot file import; podcast listening appears naturally in history, runtime stats, and search.
- **Collections / owned media**: track what you physically or digitally own with copy-level detail: source, resolution, HDR, format, codec, and bitrate; filtered collection views, per-item collection status tied into detail pages and list/smart-list rules; supports Plex collection sync.
- **Discover**: personalized recommendation rows that improve with use: genre, studio, cast, and tag affinity built from your library; not-interested and hide feedback that sticks; background refresh so rows stay current, individually refreshable from the UI, not a static recommendations page.
- **History and statistics**: history is a filterable feed with month navigation, media-type and genre filters, inline duplicate-play cleanup, and a delete flow; statistics offer explicit refresh, compare mode, custom date ranges, top-talent breakdowns, and per-type splits covering TV, film, music, podcasts, and reading with pages read, top authors, reading streaks, and listening time.
- **Lists: public, social, and smart**: public and private lists, custom slugs, public profile pages; RSS and JSON feeds per list; smart-list rules for collection status, release state, platform, origin, author, and tags; recommendations with approval flow; list completion percentages and media-type breakdowns in the index; Trakt list and watchlist import; sort by rating, progress, release date, last watched, or custom manual order.
- **Integration coverage**: Plex full library import, watchlist sync, and ratings sync; Pocket Casts account sync; Last.fm history import and live poll; Audiobookshelf account import; Radarr and Sonarr scheduled library sync; Seerr webhook auto-add, each with dedicated settings and status display.

### Beyond the basics

- **Richer metadata and title control**: localized and original titles switchable per user preference; critic ratings and popularity scores displayed; game-length data; manual metadata overrides; metadata-provider preference; image refresh flows.
- **People, studios, and credit browsing**: actor, director, author, and studio pages with filmographies and top works; person credits visible from detail pages rather than hidden as tooltip data; author pages with top-read breakdowns.
- **Careful anime handling**: proper separation of anime and TV library concerns so mixed libraries stay organized; anime-specific season and episode navigation; grouped-anime routing for franchise-spanning series.
- **Richer episode and book workflows**: episode detail pages with individual scoring; bulk episode save; drop an episode without logging it to history; book-specific: barcode and ISBN scanning from a photo, percentage-based reading progress, top-authors stats, and more resilient import flows.
- **Configurable home screen**: choose what rows appear and in what order; rows from library queries, custom lists, smart lists, or recently played but not rated; direction and media-type filters stored per user.
- **Configurable table columns**: choose and reorder visible columns per view, with media tables and list-detail tables configured independently; available columns include critic rating, episodes left, time left, time to beat, runtime, time watched, last watched, next air date, date added, popularity, and more.
- **Scheduled backups and export management**: recurring export scheduling with media-type and list inclusion options; export history and backup destination visible in settings.
- **Account security**: TOTP authenticator setup and management; recovery codes; password recovery via authenticator or recovery code; session duration as a per-user preference.

### Day-to-day polish

- **Deep preferences**: sort modes for critic rating, popularity, runtime, time to beat, plays, time watched, release date, last watched, next air date, and time left; display preferences for duration format, rating scale, stats default range, compare mode, mobile grid density, subtitle visibility on cards, localized vs. original title display, progress-bar visibility, planned-item home visibility, and obfuscating unseen episode titles.
- **A livelier UI**: a now-playing card showing what is actively playing via Plex, Jellyfin, or Emby webhook; explicit stale and refreshing indicators on history and stats with one-click refresh; lazy-loaded covers and asynchronous fragments throughout.
- **Better search and add flows**: music-native search that creates artist and album entries from search results; improved anime and localized-title search results.
- **Deeper filters**: rated and unrated, collected and not collected, caught-up and not-caught-up, no-status, language, country, platform, origin, format, author, tag inclusion, and tag exclusion; smart-list rules use the same expanded vocabulary, making them meaningfully programmable.
- **More reliable under load**: WAL mode and timeout configuration for SQLite; retry logic for lock and I/O failures; prioritized background task queues for a smoother experience with large libraries.
- **Integration settings and import UX**: import history and status visible per integration in settings; watchlist-only and collection-update-only import modes; Seerr allowed usernames and defaults persisted as preferences; per-user Plex webhook library selection.

### Also included

Multi-user accounts with OIDC and social login; calendar and iCalendar feeds for upcoming releases; release notifications through Apprise; Jellyfin, Plex, and Emby playback integrations; imports from Trakt, Simkl, MyAnimeList, AniList, Kitsu, Steam, Goodreads, StoryGraph, Hardcover, IMDb, HowLongToBeat, Grouvee and more; a REST API at `/api/v1` with an MCP server; and CSV export/import so your data is always yours to take elsewhere.

## Screenshots

### Customizable Home Screen

Change and configure what content is most important to you, making things faster and more tailored to your needs.

<img alt="Floppy home screen" src="https://github.com/user-attachments/assets/9b57dc0f-909f-491d-8941-97507d865de7" />

### Statistics

Statistics are designed for recap-style browsing across time ranges and media types.

<img alt="Screenshot 2026-07-30 at 10 31 12 PM" src="https://github.com/user-attachments/assets/89e9c0f5-5d2f-464e-952e-cebdbc82ee2b" />

### History

History keeps watches and listens in one place so recent activity is easy to scan.

<img alt="Screenshot 2026-07-30 at 10 31 48 PM" src="https://github.com/user-attachments/assets/ed795cb3-7686-49b8-9304-1c9630a808a4" />

### Shareable Lists

Lists can be shared publicly, surfaced on profiles, and used as more than a private backlog.

<img alt="Screenshot 2026-07-30 at 10 32 37 PM" src="https://github.com/user-attachments/assets/21e07055-235c-45c3-950c-c41e675984da" />

### Collections / Owned Media

Collections add ownership context alongside tracking, with room for copy-level detail.

<table>
  <tr>
    <td valign="top">
      <img width="1296" height="643" alt="Collection view" src="https://github.com/user-attachments/assets/28bdac5a-1678-4144-a227-0d361912882c" />
    </td>
    <td valign="top">
      <img width="508" height="631" alt="Copy-level collection detail" src="https://github.com/user-attachments/assets/a2c8deb9-2d92-4aaa-b605-758871f36634" />
    </td>
  </tr>
</table>

## Coming from Yamtrack?

Floppy started as a fork of [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) and has diverged substantially since — the rename exists so the two projects stop being confused for each other. The upgrade path is intentionally boring:

- **Your data moves over as-is.** Export a CSV from Yamtrack and import it under **Settings → Import**; the formats are identical. Floppy's own backups export as `floppy_<date>.csv` and use the same format, so nothing is one-way.
- **Your existing container keeps working.** If you already run this project's image, the rename doesn't break your compose file: the old `/yamtrack/db` mount path still resolves inside the image, and pre-rename `YAMTRACK_*` environment variables are still read.
- **One thing to update:** the image moved to `ghcr.io/dannyvfilms/floppy`. Point your compose file at the new path when convenient — the old path stops receiving new builds.

Floppy retains Yamtrack's core tracking, import, and self-hosting workflows, with the additional capabilities described above.

## Building an integration?

Floppy exposes a REST API at `/api/v1` and ships an [MCP server](mcp_server/). Integrations meant for Floppy should target **this repository** and the `ghcr.io/dannyvfilms/floppy` image — upstream Yamtrack does not carry Floppy's API surface, media types, or integration workflows, so "compatible with Yamtrack" and "compatible with Floppy" are not interchangeable claims.

- `/api/docs/` is the offline, read-only API index.
- `/api/openapi.yaml` is the reviewed, committed 41-operation subset for supported integrations and MCP.
- `/api/schema/` is the full dynamic diagnostic schema.
- [Domain model guide](docs/agents/domain_model.md) lists the local vocabulary used by the API.
- Copy your `API Token` from **Settings → Integrations**. It grants full authenticated API access and also authenticates webhooks and iCal. Never put it in commits, logs, screenshots, or shared shell history. If it is exposed, regenerate it in **Settings → Integrations**.
- Full reference: [API and MCP Server](https://github.com/dannyvfilms/Floppy/wiki/7.-API-and-MCP-Server)

Set the Floppy URL. Include its configured base prefix when it has one, for example `https://YOUR_FLOPPY_HOST/floppy`:

```bash
export FLOPPY_URL="https://YOUR_FLOPPY_HOST"
```

Check the public info endpoint. This request needs no token:

```bash
curl --request GET "$FLOPPY_URL/api/v1/info/"
```

For authenticated commands, set `FLOPPY_TOKEN` in the process environment to your API Token. This harmless request reads your preferences:

```bash
curl --request GET --header "X-API-Key: $FLOPPY_TOKEN" "$FLOPPY_URL/api/v1/user/preferences/"
```

## Configuration and deployment

### SQLite data paths

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
`secret_key` in `FLOPPY_DATA_DIR`. Floppy stores logs and backups in `LOG_DIR`
and `BACKUP_DIR`. `FLOPPY_DATA_DIR` does not change those settings.

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
is missing, existing sessions and signed data can become invalid.

### PostgreSQL

Floppy uses PostgreSQL only when `DB_HOST` is set. Without it, it uses
`FLOPPY_DB_PATH`; the container default is `/floppy/db/db.sqlite3`.
`DATABASE_URL` is not supported — set the individual `DB_*` variables.

```yaml
services:
  floppy:
    image: ghcr.io/dannyvfilms/floppy:latest
    container_name: floppy
    restart: unless-stopped
    depends_on:
      - db
      - redis
    environment:
      - SECRET=your-secret-key-here-change-this
      - REDIS_URL=redis://redis:6379
      - DEMO_ACCOUNT_ENABLED=False
      - TZ=America/New_York
      - DB_HOST=db
      - DB_NAME=floppy
      - DB_USER=floppy
      - DB_PASSWORD=change-this-password
      - DB_PORT=5432
    ports:
      - "8000:8000"

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

  redis:
    image: redis:8-alpine
    container_name: floppy-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--save", "", "--maxmemory", "256mb", "--maxmemory-policy", "volatile-lru"]
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

> Already running Postgres with `DB_NAME=yamtrack`? Leave those values alone. Renaming the database, role, or password against an existing volume breaks the deployment.

### Docker Run

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
  -p 8000:8000 \
  ghcr.io/dannyvfilms/floppy:latest
```

Leave `REGISTRATION=True` for your first run, then recreate the container with `False` once your account exists.

### Portainer and Unraid

Prefer **Stacks** over **Containers → Add container**. Stacks let you paste a complete Compose configuration and avoid missing required volumes or environment variables. This is also the recommended path for **Unraid**: rather than installing from a Community Applications template and standing up Redis separately, paste one compose file into a stack via the Portainer plugin and both containers come up together.

1. Go to **Stacks** → **Add Stack**
2. Name it `floppy`
3. Paste one of the compose configurations above
4. Set `SECRET` to a secure random string, and fill in whichever metadata API keys you have
5. Deploy the stack
6. Create your account while `REGISTRATION=True`, then set it to `False` and redeploy

If you use **Containers → Add container** anyway: always set `SECRET` and `REDIS_URL`; for SQLite mount persistent storage to `/floppy/db`; for PostgreSQL set the `DB_*` variables on the Floppy container and persist `/var/lib/postgresql/data` on the Postgres container; publish port `8000`; and leave `Command` and `Entrypoint` empty.

### Environment variables

The only universally required variable is `SECRET`. For Docker installs you should also set `REDIS_URL`.

**Optional but recommended:**

- `TMDB_API` - movie and TV metadata from [TMDB](https://www.themoviedb.org/settings/api)
- `TVDB_API_KEY` / `TVDB_PIN` - TVDB-backed metadata and grouped anime support (`TVDB_PIN` is your **Subscriber PIN**, only required for user-supported API keys)
- `MAL_API` - MyAnimeList **Client ID** for anime metadata ([register here](https://myanimelist.net/apiconfig))
- `IGDB_ID` / `IGDB_SECRET` - game metadata from [IGDB](https://www.igdb.com/api)
- `STEAM_API_KEY` - Steam game imports
- `BGG_API_TOKEN` - board game metadata from [BoardGameGeek](https://boardgamegeek.com/using_the_xml_api)
- `HARDCOVER_API` - Hardcover book metadata/imports
- `COMICVINE_API` - comic metadata
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
- Grouped anime and Stremio routing - see the [grouped anime/Stremio guide](docs/grouped_anime_stremio.md)
- `REGISTRATION` - set to `True` to allow new signups (needed for your first account), then set to `False` afterward
- `DEMO_ACCOUNT_ENABLED` - defaults to `True`, provisioning the built-in `demo` / `demodemo` account after migrations. The examples above set it to `False`; only turn it on if you want a shared demo login
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
COMICVINE_API=COMICVINE_API
LASTFM_API_KEY=LASTFM_API_KEY
SECRET=SECRET
DEBUG=False
```

### Use separate Redis services

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

### Running on a small host

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

### Measuring container memory

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
single opaque number. Build the candidate image locally before running the comparison.

If an existing deployment has `WEB_CONCURRENCY` or `GUNICORN_THREADS` set from an
older fixed-size configuration, remove those overrides before upgrading on a
small host so the automatic resource profile can take effect.

### Non-Docker Gunicorn installs

Source-based deployments must load Floppy's Gunicorn configuration so the
host-derived worker settings and database/Redis fork-safety hooks are active:

```bash
cd /path/to/floppy/src
uv run --no-sync gunicorn --config python:config.gunicorn config.wsgi:application
```

Do not start the service with bare `gunicorn config.wsgi:application`; that
skips the shipped configuration and its process lifecycle hooks.

Gunicorn does not write a request access log. A request line holds the query
string, and a query string can hold an OAuth code or an integration token, so
the container writes one access line at the Nginx boundary instead, with the
query string and the referrer removed. Gunicorn still writes its error log.

A source-based deployment therefore gets its request log from its own reverse
proxy. Configure that proxy to leave the query string out of its log format.
The container's format is in `nginx.conf`:

```nginx
log_format floppy_safe '$remote_addr [$time_local] '
                       '"$request_method $uri $server_protocol" '
                       '$status $body_bytes_sent';
```

Application logs are separate and are always redacted before they are written.
See [docs/architecture/log-redaction.md](docs/architecture/log-redaction.md).

### Upgrading container images

The migration conflict involving `0147_item_calendar_checked_at` and
`0148_merge_duplicate_item_buckets` is fixed in current images by the
`0149_merge_20260806_1556` merge migration. Pull the updated image before
restarting instead of generating a local merge migration:

```bash
docker compose pull floppy
docker compose up -d --force-recreate floppy
```

Because `latest` is mutable, pin a versioned image tag when reproducible
upgrades matter.

### Persistence checklist

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

### SQLite startup recovery

Floppy checks SQLite storage and relationships before it runs migrations.
If the check finds an album artist credit whose album or artist no longer
exists, Floppy creates a verified backup, removes only that invalid credit,
and checks the database again.

For any other relationship conflict, Floppy writes a bounded report beside
the database as `db.sqlite3.integrity.json`. The report counts every conflict
but includes at most 20 row samples, so a large incident cannot fill the log.
Startup then remains idle and unhealthy without running migrations or services;
this prevents Docker restart policies from repeating the same failure.

The report identifies the incident with a fingerprint and issues a separate
one-time **incident token**. The startup log prints the exact value to set, and
the report repeats it under `actions`. Copy that token; the fingerprint is an
identifier, not an approval. There are three choices:

1. **Restore or repair:** stop Floppy, back up the database with its `-wal` and
   `-shm` files, then restore a known-good copy or repair the named rows.
2. **Accept:** set `FLOPPY_SQLITE_CONFLICT_ACTION=accept:<incident-token>` and
   recreate the container. Floppy starts without changing the conflicting rows.
   Accept gets you back online on your current schema. It is not an upgrade
   path: Django re-checks every foreign key while it applies a migration, so a
   pending migration keeps failing until you repair or quarantine the rows.
3. **Quarantine:** set
   `FLOPPY_SQLITE_CONFLICT_ACTION=quarantine:<incident-token>` and recreate the
   container. Floppy first writes and verifies a full backup under
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

### Startup diagnostics

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
| `--timeout SECONDS` | Bound the database storage check. The default is 600. |

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

### Grouped anime migration diagnostics

Grouped anime conversion validates provider data before it writes and commits
the grouped show, seasons, episode history, provider links, preference, and old
MAL-row markers together. A retry after a successful conversion is a no-op.

If Floppy reports `ANIME-MIGRATION-STALE-001`, reload the page and try again so
it can validate the current source row. For `ANIME-MIGRATION-PARTIAL-001` or
`ANIME-MIGRATION-AMBIGUOUS-001`, leave the existing rows unchanged, back up the
database, and include the code when asking for support. Floppy deliberately
does not guess whether coexisting episode rows are migration residue or a
legitimate rewatch.

### Trakt private profile import (OAuth)

If you import from a private Trakt profile, configure OAuth first:

1. Create an app in [Trakt API Apps](https://trakt.tv/oauth/applications).
2. Add this Redirect URI in the Trakt app:
   - `https://your_domain.com/import/trakt/private`
3. Set these environment variables:
   - `TRAKT_API` = your Trakt client ID
   - `TRAKT_API_SECRET` = your Trakt client secret

Behind a reverse proxy, also set `URLS=https://your_domain.com` so Floppy generates the correct external callback URL.

### Reverse proxy setup

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

### Troubleshooting: I updated and my login is gone

1. If you intended to use PostgreSQL, confirm `DB_HOST` is set. `DATABASE_URL` alone will not enable Postgres.
2. If you intended to use SQLite, confirm `/floppy/db` (or the legacy `/yamtrack/db`) is mounted to persistent storage.
3. If you were only logged out but can sign in again, Redis/session data was reset; your account database is still intact.
4. Do not remove database volumes during updates unless you intentionally want a fresh install.

### Docker image tags

The image lives at `ghcr.io/dannyvfilms/floppy`:

- `:latest` - the latest commit on the `latest` branch
- `:release` - the latest commit on the `release` branch, or the stable alias for a GitHub release tag
- `:vX.Y.Z` - versioned release builds from GitHub release tags

## Local development

For contributing or customizing locally:

```bash
git clone https://github.com/dannyvfilms/Floppy.git
cd Floppy
docker run -d --name redis -p 6379:6379 --restart unless-stopped redis:8-alpine
uv sync --locked
```

Django/manage.py commands require `SECRET`. Create a `.env` with at least `SECRET`, `DEBUG=True`, and whichever metadata API keys you need (same names as the Docker list above), then:

```bash
uv run --no-sync python src/manage.py migrate
uv run --no-sync python src/manage.py createsuperuser
uv run --no-sync python src/manage.py runserver
```

Celery and Tailwind run in separate terminals:

```bash
PYTHONPATH=src uv run --no-sync celery -A config worker --queues interactive --hostname celery-interactive@%h --loglevel DEBUG
PYTHONPATH=src uv run --no-sync celery -A config worker --queues celery --beat --scheduler django --hostname celery@%h --loglevel DEBUG
```

```bash
npx @tailwindcss/cli -i ./src/static/css/input.css -o ./src/static/css/main.css --watch
```

Visit `http://localhost:8000`. A `demo` / `demodemo` account is provisioned after migrations; set `DEMO_ACCOUNT_ENABLED=False` to disable it. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

`pyproject.toml` and `uv.lock` are the dependency source of truth for the app
and bundled MCP workspace. Use uv 0.12.3 and keep the lockfile in sync; the
removed requirements files are not maintained in parallel. The MCP package's
`setuptools>=68` isolated build-backend range is the only build-time resolver
exception to the runtime lock and is intentionally not pinned as an application
dependency.

## Support the project

- Star the repository if you want to help more people find Floppy.
- Join the [Discord channel](https://discord.gg/uFgha7Kb6n) to ask questions, share feedback, and chat with the community.
- Open an [issue](https://github.com/dannyvfilms/Floppy/issues) for bugs, or for feature requests and ideas.
- Open a pull request if you want to contribute code, docs, or polish.

### Contributors

A huge thank you to everyone who has contributed to Floppy and its foundations!

<a href="https://github.com/dannyvfilms/Floppy/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dannyvfilms/Floppy" alt="Contributors" />
</a>

We actively welcome contributions of all kinds — bug fixes, new features, UI polish, or documentation improvements. See our [Contributing Guide](CONTRIBUTING.md) to get started.

## License

AGPL-3.0.

## Origins

Floppy began as a fork of [FuzzyGrim/Yamtrack](https://github.com/FuzzyGrim/Yamtrack) and still shares its foundation and data model — Yamtrack CSV exports import directly, and this repository will keep showing the fork link. Since then it has grown into a distinct project with its own direction: a Trakt-replacement daily driver for people who want something more opinionated and more feature-dense. Thanks to FuzzyGrim and Yamtrack's contributors for the groundwork.
