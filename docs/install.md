# Guided installation

One command installs Floppy, starts it, and hands you a URL. It asks a few
plain questions and never asks for a password or an API key.

```bash
curl -fsSL https://raw.githubusercontent.com/dannyvfilms/Floppy/latest/scripts/install.sh -o /tmp/floppy-install.sh && bash /tmp/floppy-install.sh
```

The download and the run are separate steps on purpose: the installer is
interactive, and piping it straight into a shell would leave it without a
terminal to ask questions on.

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
| WSL2 | Yes | Use Docker |

An unsupported host is told exactly which prerequisite is missing rather than
being half-installed.

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
cannot touch the database. Backing up the installation root backs up Floppy.

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
docker compose -f ~/floppy/docker-compose.yml pull \
  && docker compose -f ~/floppy/docker-compose.yml up -d  # upgrade
```

**Source, Linux**

```bash
sudo systemctl start floppy
sudo systemctl stop floppy
git -C ~/floppy/repo pull && ~/floppy/bin/uv sync --locked --no-default-groups \
  && sudo systemctl restart floppy
```

**Source, macOS**

```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.floppy.app.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.floppy.app.plist
git -C ~/floppy/repo pull && ~/floppy/bin/uv sync --locked --no-default-groups \
  && sudo launchctl kickstart -k system/com.floppy.app
```

Metadata API keys are entered in Floppy itself, under **Settings → Metadata**.
Floppy works without them.

## What this does not do

Automatic upgrades, moving an installation between Docker and source,
PostgreSQL setup, and public HTTPS are all deliberately out of scope. The
existing Compose and Unraid instructions in [README.md](../README.md) are
unchanged and remain the right path for those.

## If it does not finish

The installer waits five minutes for Floppy to answer. On a timeout it leaves
the services running and your data alone, says startup may still be in
progress, and prints bounded diagnostics. Run it again to resume, or run the
built-in check:

```bash
docker compose -f ~/floppy/docker-compose.yml exec floppy python manage.py floppy_preflight
```
