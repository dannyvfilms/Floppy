# Floppy (Bundled)

One container that runs Floppy with its own PostgreSQL 18 (with pgvector) and
Valkey. Nothing else to install, no network to create, no database password.
It is an additional choice. The standard image, SQLite, external PostgreSQL and
Redis, and the Compose examples are unchanged.

| Tag | Follows |
| --- | --- |
| `ghcr.io/dannyvfilms/floppy:latest-bundled` | `latest` branch |
| `ghcr.io/dannyvfilms/floppy:release-bundled` | `release` branch |
| `ghcr.io/dannyvfilms/floppy:<version>-bundled` | a release tag |

The bundled image is built from the standard image of the same build, passes the
same quality gates, and is published only after they pass.

## Install

Unraid: install **Floppy (Bundled)** from `templates/floppy-bundled.xml`.

Docker:

```bash
docker run -d --name floppy --restart unless-stopped --stop-timeout 150 \
  -p 8000:8000 \
  -v /srv/floppy/db:/floppy/db \
  -v /srv/floppy/pgdata:/floppy/pgdata \
  -v /srv/floppy/backups:/floppy/backups \
  ghcr.io/dannyvfilms/floppy:release-bundled
```

`SECRET` is optional. When it is not set Floppy generates one on first start and
keeps it in `/floppy/db`. Never change a secret you have used. Use `PUID` and
`PGID` as with the standard image; the database files belong to that user.

## What runs, and how it is protected

- PostgreSQL listens on a unix socket inside the container only (no TCP, no
  password, the socket is private to the service user). Valkey listens on
  `127.0.0.1`. Publish only the web port.
- Start order: database and Valkey start, migrations run, they stop cleanly,
  then supervisord starts everything. Stop order is the reverse, so the app
  exits before the database does. Give Docker a long stop timeout (150 s).
- A crashed PostgreSQL or Valkey is restarted by supervisord.
- Set `DB_HOST` and the embedded PostgreSQL stays off and Floppy uses that
  server. Set `REDIS_URL` and the embedded Valkey stays off. The log says which
  was chosen. This is for people who want the image but one external service.
- The sizing in `config/runtime_profile.py` is unchanged, and PostgreSQL and
  Valkey now share the container's memory. Allow roughly 300 MB more than the
  standard image.

## What it refuses to do

The container exits with a message, and does not create anything, when:

- `/floppy/pgdata` is not a mounted volume (the data would vanish on recreate;
  `FLOPPY_BUNDLED_ALLOW_EPHEMERAL=true` is for throwaway tests only);
- this installation was initialised before but the database folder is now empty
  (wrong or missing volume);
- the folder holds something that is not a PostgreSQL cluster;
- `/floppy/db` already has a Floppy SQLite database (it is never converted);
- the database is a different PostgreSQL major version than the image.

## Backups and restore

A dump of the database and a copy of the signing secret are written to
`/floppy/backups/postgres` every day, seven kept (`FLOPPY_BUNDLED_BACKUP_KEEP`,
`0` turns it off). Take one now:

```bash
docker exec floppy floppy-bundled-backup
```

Restore, including onto a brand new volume or machine:

1. Stop the container, empty the database folder (or point it at a new one), and
   keep the dump and its `.secret_key` file in `<backups>/postgres`.
2. Create the file `<backups>/postgres/RESTORE` containing the dump's file name,
   for example `floppy-20261123T040000Z.dump`.
3. Start the container. It restores the database, renames the file to
   `RESTORE.done`, and restores the saved secret if `/floppy/db` has none.

If the restore fails the container stops and leaves `RESTORE` in place.

## PostgreSQL major upgrades

A new major version is never applied by an image update. The container refuses
to start on an older database. To upgrade, with the old image still installed:

1. `docker exec floppy floppy-bundled-backup`
2. Stop the container and move the old `pgdata` folder aside (keep it).
3. Switch to the new image, mount an empty `pgdata`, create the `RESTORE` file as
   above, and start.

The old folder is your way back until you have checked the new install.

## Moving from SQLite or external PostgreSQL

Not automatic. Keep the standard image, or start a fresh bundled install and
import your data through Floppy's export and import.

## Discovery (mDNS)

The bundled container stays on bridge networking, so LAN discovery is not part of
it. Run the optional advertiser separately.
