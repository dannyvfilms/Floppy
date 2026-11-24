#!/usr/bin/env bash
# Boot-level checks for the Floppy (Bundled) image.
#   scripts/bundled_smoke.sh <bundled-image>
# Covers: clean boot, restart on the same volumes, service recovery, backup then
# restore into a brand new volume, and the refusals that protect data.
set -euo pipefail

IMAGE=${1:?usage: bundled_smoke.sh <image>}
RUN=$(mktemp -d)
NAME=floppy-bundled-smoke
# Files in the mounts belong to the container's user, so remove them from inside.
wipe() { docker run --rm --entrypoint sh -v "$1:/w" "$IMAGE" -c 'rm -rf /w/* /w/.[!.]*' >/dev/null 2>&1 || true; }
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true; wipe "$RUN"; rm -rf "$RUN" 2>/dev/null || true' EXIT
mkdir -p "$RUN"/{db,pg,backups}
chmod 777 "$RUN"/{db,pg,backups}

start() { # extra docker args...
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" -p 18000:8000 \
    -e SECRET="smoke-$(basename "$RUN")" -e DEMO_ACCOUNT_ENABLED=False \
    -v "$RUN/db:/floppy/db" -v "$RUN/pg:/floppy/pgdata" -v "$RUN/backups:/floppy/backups" \
    "$@" "$IMAGE" >/dev/null
}
healthy() {
  for _ in $(seq 1 150); do
    curl -fsS --max-time 5 http://127.0.0.1:18000/health/ >/dev/null 2>&1 && return 0
    [ "$(docker inspect -f '{{.State.Status}}' "$NAME")" = running ] || return 1
    sleep 3
  done
  return 1
}
sql() { docker exec "$NAME" psql -h /run/floppy-pg -U floppy -d floppy -tAc "$1"; }
step() { echo "== $*"; }

step "clean boot"
start
healthy || { docker logs "$NAME" 2>&1 | tail -40; exit 1; }
test "$(sql "select extname from pg_extension where extname='vector'")" = vector
docker exec "$NAME" sh -c 'valkey-cli -h 127.0.0.1 ping' | grep -q PONG
# Not exposed: no TCP listener for PostgreSQL, Valkey on loopback only.
! docker exec "$NAME" sh -c 'netstat -ln | grep -E ":5432 "' >/dev/null
docker exec "$NAME" sh -c 'netstat -ln | grep ":6379 " | grep -q 127.0.0.1'
# An exec shell must reach the embedded PostgreSQL, never create a SQLite file.
docker exec "$NAME" python manage.py migrate --check --noinput
! docker exec "$NAME" test -e /floppy/db/db.sqlite3
sql "create table smoke_marker(v int); insert into smoke_marker values (42)" >/dev/null
SECRET_BEFORE=$(docker exec "$NAME" cat /floppy/db/secret_key 2>/dev/null || echo env)

step "service recovery (postgres killed)"
docker exec "$NAME" sh -c 'kill -9 $(head -1 /floppy/pgdata/postmaster.pid)'
for _ in $(seq 1 30); do sql "select 1" >/dev/null 2>&1 && break; sleep 2; done
test "$(sql "select v from smoke_marker")" = 42

step "graceful stop and restart on the same volumes"
docker stop -t 150 "$NAME" >/dev/null
out=$(docker logs "$NAME" 2>&1)
grep -qi "database system is shut down" <<<"$out"
start
healthy
test "$(sql "select v from smoke_marker")" = 42
test "$(docker exec "$NAME" cat /floppy/db/secret_key 2>/dev/null || echo env)" = "$SECRET_BEFORE"

step "backup"
docker exec "$NAME" floppy-bundled-backup
ls "$RUN"/backups/postgres/floppy-*.dump >/dev/null
DUMP=$(basename "$(ls "$RUN"/backups/postgres/floppy-*.dump | head -1)")
docker rm -f "$NAME" >/dev/null

step "refuses to replace a lost database volume"
wipe "$RUN/pg"
start
sleep 20
out=$(docker logs "$NAME" 2>&1)
grep -q "initialised before" <<<"$out"
docker rm -f "$NAME" >/dev/null

step "restore into the empty volume"
echo "$DUMP" > "$RUN/backups/postgres/RESTORE"
start
healthy
test "$(sql "select v from smoke_marker")" = 42
test -f "$RUN/backups/postgres/RESTORE.done"
docker rm -f "$NAME" >/dev/null

step "refuses an unmounted data directory"
out=$(docker run --rm -e SECRET=x "$IMAGE" 2>&1 || true)
grep -q "not a mounted volume" <<<"$out"

step "external services keep the embedded ones off"
start -e DB_HOST=127.0.0.1 -e DB_NAME=x -e DB_USER=x -e DB_PASSWORD=x -e DB_PORT=5999 -e REDIS_URL=redis://127.0.0.1:6390
sleep 15
out=$(docker logs "$NAME" 2>&1)
grep -q "embedded PostgreSQL stays off" <<<"$out"
grep -q "embedded Valkey stays off" <<<"$out"
! docker exec "$NAME" pgrep -x valkey-server >/dev/null

echo "bundled smoke passed"
