# Guided installation

One command installs Floppy, starts it, and hands you a URL. It asks a few
plain questions and never asks for a password or an API key.

Open **PowerShell** on Windows 10/11 or **Terminal** on macOS/Linux and paste
the same complete line:

```text
echo "\" | Out-Null; irm 'https://raw.githubusercontent.com/dannyvfilms/Floppy/latest/scripts/install.ps1' -ErrorAction Stop | iex; #" >/dev/null; bash -c 'p=$(mktemp) || exit; cleanup() { rm -f "$p"; }; trap cleanup EXIT; curl -fsSL https://raw.githubusercontent.com/dannyvfilms/Floppy/latest/scripts/install.sh -o "$p" && bash "$p"'
```

No Python, Node, or preinstalled Docker is needed to launch it. On Windows,
use PowerShell rather than Command Prompt. On macOS/Linux, use the normal
Terminal shell (Bash, zsh, or sh) with Bash and curl available.

The line selects the existing platform installer without running the other
platform's commands. Unix downloads use a private temporary file, stop on
download errors, and keep terminal input available for the questions. The file
is removed when the installer exits. See [Windows](#windows) for its Docker
Desktop setup and [Where it works](#where-it-works) for supported hosts.

## What it asks

1. **How Floppy should run** - Docker (recommended) or directly on this
   computer.
2. **Who can reach it** - other devices on your network, or only this computer.
3. **Which port**, and **which time zone**. Both come with a detected default.

It then lists anything it needs to install and any step needing administrator
access, and asks before doing it. Nothing is installed without a yes.

Once Floppy answers, the installer prints the address, asks you to create your
account in the browser, and then asks for that username so it can make the
account the owner. It never asks for the password.

## Where it works

| Host | Docker | Directly on this computer |
| --- | --- | --- |
| Ubuntu / Debian | Installs Docker for you, with permission | systemd services |
| Other Linux with Docker | Yes | Use Docker |
| macOS | Needs Docker Desktop running | launchd services, via Homebrew |
| Windows 10 / 11 | Docker Desktop (offers to install it with winget) | Use Docker |
| Inside WSL2 | Yes, with the same command | Use Docker |

An unsupported host is told exactly which prerequisite is missing rather than
being half-installed.

## Windows

`scripts/install.ps1` runs in Windows PowerShell 5.1 or PowerShell 7 and uses
Docker Desktop. If Docker Desktop is missing it offers to install it with
`winget` (Windows asks for permission) and stops so you can finish Docker
Desktop's own first-run setup; paste the command again afterwards. If Docker
Desktop is installed but stopped, it starts it.

It asks the same questions as the macOS/Linux installer (network access, port,
time zone), writes `%USERPROFILE%\floppy\docker-compose.yml` and `floppy.env`,
starts Floppy, waits for it to answer, and then walks through owner setup and
closing registration. Rerunning it keeps the existing configuration and only
starts Floppy again.

Two differences from the macOS/Linux Docker path:

- The database, backups and Redis data live in Docker volumes
  (`floppy_floppy_db`, `floppy_floppy_backups`, `floppy_redis_data`), not
  folders on `C:`. SQLite's file locking is unreliable on Windows folder mounts.
  With Floppy stopped, this PowerShell command copies the database volume to
  `floppy-db.tgz` in the current folder:
  `docker run --rm -v floppy_floppy_db:/data -v "${PWD}:/out" alpine tar czf /out/floppy-db.tgz -C /data .`
- There is no repository checkout, so nothing needs git.

Floppy runs while Docker Desktop runs. Turn on **Start Docker Desktop when you
sign in** in Docker Desktop's settings so Floppy is back after a restart.

## What it creates

```
~/floppy/                 the installation root (you choose the path)
  repo/                   the checkout (currently the latest branch;
                          see the TODO in scripts/install.sh)
  floppy.env              this installation's settings
  install.conf            the answers needed to resume
  db/                     the database and the generated secret key
  backups/                automatic database backups
  logs/                   log files
  redis/                  Redis persistence
  docker-compose.yml      Docker installs only
  run/                    source installs only: service configuration
```

Runtime data lives beside the checkout, never inside it, so updating the code
cannot touch the database. Back up this root with Floppy stopped, or use a
consistent database snapshot; copying a live SQLite file alone is unsafe.
Keep an encrypted copy on another disk or machine, including the original
signing key and external secret files. PostgreSQL needs a consistent
`pg_dump` backup rather than a copy of its live data volume. Native macOS SQLite
snapshots use a private system-temporary workspace, requiring room for another
full database copy there as well as in `backups/`. Linux snapshots stage directly
in the backup directory. Both verify before atomic publication. Monitor backup
file dates and failure logs; a running scheduler does not prove backups succeed.

## Running it again

Rerunning the installer is safe. It never resets the checkout, overwrites the
configuration, changes the installation method, or adopts an installation it
did not create. It offers to start Floppy again, or to finish owner setup if
you skipped it.

## Afterwards

The installer prints the exact start, stop, status, logs, and resume commands
for the method you chose. In short:

**Docker**

```bash
docker compose -f ~/floppy/docker-compose.yml up -d       # start
docker compose -f ~/floppy/docker-compose.yml down        # stop
docker compose -f ~/floppy/docker-compose.yml logs -f     # logs
```

Before upgrading a pickle-era installation, complete the
[Celery drain procedure](security-hardening.md#celery-json-transition) with the
old image and configuration. Stop submissions and beat, drain all old workers
and queues, then stop the workers. Pull/recreate does not drain jobs, and new
workers discard old pickle messages without necessarily marking them failed.
Retain import inputs and inspect partial imports before resubmitting.

For upgrades, record the current image digest, stop Floppy, and make a complete
backup first. Pin the desired image in the generated Compose file, then run
`pull` and `up -d` with that file. Startup applies migrations automatically.
Do not use `down -v`. Rollback requires restoring the pre-upgrade database,
matching key/configuration, and old image together; an older image alone
cannot safely undo database migrations.

**Source, Linux — start and stop**

```bash
sudo systemctl start floppy
sudo systemctl stop floppy
```

**Source, macOS — start and stop**

```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.floppy.app.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.floppy.app.plist
```

**Upgrade validation limits**

The current CI upgrade replay starts at `v26.9.24` and checks representative
tracking data against the candidate source on SQLite and PostgreSQL. Its
presence is not evidence that a particular candidate passed; check that
candidate's Actions results before upgrading. It does not establish every
historical version or an old-container-to-new-container restore path.
`v26.10.1` has a known clean-initialization migration-graph conflict; newer
source joins the conflicting leaves. Do not select that tag for a fresh install.
For an existing installation, keep a verified backup and the matching old image
and configuration before upgrading; report migration errors rather than faking
migration records or deleting data.

Normal `migrate` on an existing database also stops at the `v26.10.1` graph
conflict, before applying migrations. Move to a release/source revision that
contains `users/0141_merge_search_all_discover_seerr.py`, keeping the database
and original key intact. That migration joins the three published leaves; do
not generate a local merge, edit published migrations, or fake their records.
A database already modified by manual repairs needs individual assessment.

**Source upgrades (both systems)**

For a pickle-era installation, first complete the
[Celery drain procedure](security-hardening.md#celery-json-transition) while the
old code, environment and workers are still available. Stop submissions and all
beat producers, drain every queue, then stop the old workers. Stopping the
service or updating dependencies first can strand jobs that the new JSON-only
workers will discard. Do not run old and new workers together.

Stop the service using the command above and back up the installation root
before changing code. Record the old commit. Then, as the installation owner,
run this for the default root (adjust paths if yours differs):

```bash
(
  set -e
  cd ~/floppy/repo
  git pull --ff-only
  ~/floppy/bin/uv sync --locked --no-default-groups
  set -a
  . ~/floppy/floppy.env
  set +a
  .venv/bin/python src/manage.py migrate --noinput
  .venv/bin/python src/manage.py collectstatic --noinput
  .venv/bin/python src/manage.py check
)
```

The installer may use an existing compatible `uv` instead of installing
`~/floppy/bin/uv`; use that executable if the latter is absent. Run the start
command only after every step succeeds. A normal source service start does
not apply migrations or collect static files. A failed migration can leave
earlier migrations applied; restoring the pre-upgrade database and old code
is the reliable fallback, with loss of writes since that backup.

Metadata API keys are entered in Floppy itself, under **Settings → Metadata**.
Floppy works without them.

## What this does not do

Automatic upgrades, moving an installation between Docker and source,
PostgreSQL setup, and public HTTPS are all deliberately out of scope. The
[configuration and deployment reference](deployment.md) covers Compose by
hand, Unraid, PostgreSQL, and reverse proxies.

## If it does not finish

The installer waits five minutes for Floppy to answer. On a timeout it leaves
the services running and your data alone, says startup may still be in
progress, and prints bounded diagnostics. Run it again to resume, or run the
built-in check:

```bash
docker compose -f ~/floppy/docker-compose.yml exec floppy python manage.py floppy_preflight
```
