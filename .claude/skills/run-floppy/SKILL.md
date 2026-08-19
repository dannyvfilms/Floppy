---
name: run-floppy
description: Launch Floppy locally and drive it in a headless browser to see a change working in the real app. Use this whenever you need to run, start, serve, or screenshot Floppy, log into it, click through its pages, or confirm a change renders correctly rather than only passing tests - and also when a local run is already misbehaving with a 403 on login, unstyled pages, or missing static files, because those are the three things that reliably go wrong here and this skill has the fixes.
---

# Running Floppy locally

Floppy normally runs as one container with nginx in front of gunicorn, three
Celery workers, and beat, all under supervisord. Locally you run the pieces
directly, and three things break in ways whose error messages point somewhere
misleading. This skill exists mostly to save you from rediscovering those.

## The short version

```bash
cd <repo>/src
redis-server --port 6379 --daemonize yes --save '' --dir /tmp
uv run --project .. --no-sync python manage.py migrate --noinput
uv run --project .. --no-sync python manage.py collectstatic --noinput --settings=local_serve   # see below
uv run --project .. --no-sync bash ../.claude/skills/run-floppy/scripts/serve.sh start
uv run --project .. --no-sync python ../.claude/skills/run-floppy/scripts/smoke.py --base http://localhost:8299
uv run --project .. --no-sync bash ../.claude/skills/run-floppy/scripts/serve.sh stop
```

`serve.sh` and `smoke.py` encode everything below. Read on when you need to
deviate — a different tier, real background tasks, a specific page.

## The three things that go wrong

### 1. Login returns 403, and it is not CSRF

Posting the login form to gunicorn directly gives a 403 page saying "You don't
have permission to access this resource", and gunicorn logs
`Forbidden (Permission denied): /accounts/login/`. That reads like a CSRF
failure and isn't — the CSRF cookie settings are fine over plain HTTP.

The cause is `settings.py`: when `IS_PROD` is true it sets
`ALLAUTH_TRUSTED_CLIENT_IP_HEADER = "X-Real-IP"`, and allauth refuses requests
that don't carry that header. nginx sets it in production; you aren't running
nginx. `IS_PROD` is derived from `sys.argv`, so it's true for gunicorn and
false only for `runserver`/`test`.

Two ways out, and which you pick depends on what you're checking:

- **Send the header.** Keeps `IS_PROD` true, so you're exercising the same code
  path production does. `smoke.py` does this via Playwright's
  `extra_http_headers`. Use this when the thing you're verifying could plausibly
  behave differently in prod mode.
- **Override `IS_PROD = False`** in a settings module (below). Simpler, and it
  also fixes static files. `scripts/bench.sh` in this repo does exactly this, so
  it's an established pattern here. Use this for ordinary UI checks. Note:
  `ALLAUTH_TRUSTED_CLIENT_IP_HEADER` is set inside `if IS_PROD:` at
  `config/settings.py` *import time*, so re-assigning `IS_PROD = False`
  afterward doesn't undo it — the override module must also clear that
  setting explicitly (see the `local_serve.py` snippet below), or login
  still 403s with `Unable to determine client IP address`.

### 2. Pages render unstyled

nginx serves `/static/` in production, so gunicorn 404s every asset and you get
a working but unstyled DOM. Django only serves static itself when `IS_PROD` is
false, and the files have to be collected first.

Create `src/local_serve.py`:

```python
"""Local settings: no nginx, so let Django serve /static/."""
from config.settings import *  # noqa: F403

# Gates Django's static serving. Same override scripts/bench.sh uses.
IS_PROD = False
# config.settings sets this inside `if IS_PROD:` at import time, before this
# override runs, so it survives IS_PROD = False above unless cleared here too.
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = None
```

Then run the collectstatic command through uv:

```bash
uv run --project .. --no-sync python manage.py collectstatic --noinput --settings=local_serve
```

Start gunicorn through uv with `DJANGO_SETTINGS_MODULE=local_serve`.

The stylesheet is `static/css/main.css` and it is committed pre-built — there is
no npm build step, and `package.json` has no scripts. If you find yourself
looking for a Tailwind build, you've gone wrong; the file is already there.

`local_serve.py` is a local convenience, not something to commit. Delete it when
you're done, or add it to `.gitignore` if you keep it around.

### 3. Stopping the server can kill your own session

`pkill -f "gunicorn.*config.wsgi"` matches the shell command line that contains
that pattern — including yours. Kill by port listener instead:

```bash
lsof -ti:8299 -sTCP:LISTEN | xargs -r kill
```

Use `lsof`, not `ss`. In this container `ss -ltnp` prints **nothing at all** — it
can't read the socket table — so the obvious `ss | grep :8299 | grep -oP 'pid=\K…'`
pipeline finds no listener, exits cleanly, and leaves the server running while
telling you it stopped. That false success is worth more caution than the
original problem: the next `start` then fails on an occupied port and you go
looking in the wrong place.

`serve.sh stop` tries `lsof`, then `ss`, then `fuser`, and afterwards curls
`/health/` to confirm the port really is quiet — reporting failure if it isn't
rather than assuming.

## Choosing a resource tier

`config/runtime_profile.py` detects the host's memory, swap and CPU and picks a
tier that determines how many gunicorn workers and Celery workers run.
`entrypoint.sh` probes it once and exports the result; reproduce that with:

```bash
eval "$(uv run --project .. --no-sync python -c 'from config.runtime_profile import emit_env; emit_env()')"
```

That sets `WEB_CONCURRENCY`, `GUNICORN_THREADS`, `FLOPPY_CELERY_QUEUES`,
`FLOPPY_CELERY_ROLE` and the two `FLOPPY_START_*_WORKER` flags. Force a specific
tier with `FLOPPY_RESOURCE_TIER=minimal|constrained|standard` — useful for
checking behaviour on a small host without having one.

## Background tasks

Gunicorn alone is enough for page rendering, but anything the app defers to a
worker will simply never happen. Most visibly, Statistics shows `--`
placeholders: a cache miss schedules a refresh task and returns immediately, by
design, so with no worker the values never arrive. That is not a bug — don't go
hunting for one.

Start a worker when you need that path:

```bash
FLOPPY_PROCESS_ROLE=background uv run --project .. --no-sync celery --app config worker \
  --queues "${FLOPPY_CELERY_QUEUES:-celery}" --loglevel INFO \
  --without-mingle --without-gossip &
```

`serve.sh start --with-worker` does this.

## Driving the browser

There is no `chromium-cli` here. Playwright's Python bindings and a pinned
Chromium are preinstalled under `/opt/pw-browsers/chromium-*/chrome-linux/chrome`
— glob it rather than hardcoding, the version directory changes. Never run
`playwright install`.

`scripts/smoke.py` logs in and sweeps the pages that exercise the cache-heavy
views, reporting HTTP status, whether a server-error page rendered, and console
errors, then writes screenshots. Point it at a single page with `--only`, or add
paths with `--pages`.

Form details, since they're easy to get wrong: the login fields are `#id_login`
and `#id_password` (allauth names them `login`/`password`), and the submit
control is `button[type="submit"]`. The markup formats attributes across
multiple lines, so grepping for `<button` in the HTML finds nothing — don't
conclude the button is missing.

**Look at the screenshots.** A 200 status proves the view didn't raise; it does
not prove the page rendered. Read the PNGs.

## Getting a user to log in as

Registration is off by default and the demo account only exists when
`DEMO_ACCOUNT_ENABLED` is set. Make one directly:

```bash
uv run --project .. --no-sync python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','local_serve')
django.setup()
from django.contrib.auth import get_user_model
u, _ = get_user_model().objects.get_or_create(username='smoke')
u.set_password('smoketest12345'); u.save()
"
```

## Creating data without the network

An empty library renders empty states, which is fine for a smoke test but not
for checking anything that displays data. Search and any TMDB-backed item need
outbound network, so in a sandbox without egress use `Sources.MANUAL` items —
they need no provider call:

```python
import events.tasks  # noqa: F401  - signal handlers reach events.tasks lazily
from app.models import Item, Movie, MediaTypes, Sources, Status
```

That first import is load-bearing. Saving a `Movie` fires a signal that calls
`events.tasks.reload_calendar`, and from a bare script `events.tasks` hasn't been
imported yet, so you get
`AttributeError: module 'events' has no attribute 'tasks'`. The app imports it at
startup; a one-off script doesn't.

## Expected failures without outbound network

In a sandbox with egress blocked, these fail and are not your change:

- `/search?q=...` → **503**, with `ERR_TUNNEL_CONNECTION_FAILED` in the console.
  A handled provider outage, which is the correct behaviour.
- Any page fetching a remote poster → one console error per image.
- Tests under `app/tests/providers/`, `app/tests/models/test_media.py` and
  `integrations/tests/imports/` need TMDB/TVDB/MAL and fail wholesale.

Before blaming a change for a browser-console error, check whether the diff even
touches templates, JS or CSS — `git diff --name-only <base> | grep -E '\.(html|js|css)$'`.
If it doesn't, an Alpine.js error is pre-existing.
