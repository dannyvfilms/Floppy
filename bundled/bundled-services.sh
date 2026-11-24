#!/bin/sh
# Floppy (Bundled): embedded PostgreSQL 18 + pgvector and Valkey.
#
# Sourced by entrypoint.sh when FLOPPY_BUNDLED=true (set only in the bundled
# image). Never runs in the standard image. See docs/deployment-bundled.md.
#
# Contract:
#   * Embedded PostgreSQL listens on a unix socket only; Valkey on 127.0.0.1.
#   * A service the operator points elsewhere (DB_HOST / REDIS_URL) stays off.
#   * A missing or wrong data directory is an error, never a fresh database.

PGMAJOR=18
PGDATA=${FLOPPY_BUNDLED_PGDATA:-/floppy/pgdata}
PGSOCKET=${FLOPPY_BUNDLED_PGSOCKET:-/tmp/floppy-pg}
VALKEY_DIR=${FLOPPY_BUNDLED_VALKEY_DIR:-/floppy/valkey}
VALKEY_PORT=6379
PG_BACKUP_DIR="${BACKUP_DIR_PATH}/postgres"
BUNDLED_MARKER="${DATA_DIR}/.floppy-bundled-initialized"
RESTORE_FLAG="${PG_BACKUP_DIR}/RESTORE"
SUPERVISOR_FRAGMENTS=/tmp/floppy-runtime/supervisord.d
BUNDLED_DOCS="https://github.com/dannyvfilms/Floppy/blob/latest/docs/deployment-bundled.md"

bundled_fail() {
    echo "[bundled] ERROR: $1" >&2
    echo "[bundled] See ${BUNDLED_DOCS}" >&2
    exit 1
}

# Run a command as the unprivileged service user (or as ourselves when the
# container was started non-root).
as_service_user() {
    if [ "$RUNNING_AS_ROOT" = true ]; then
        su-exec abc "$@"
    else
        "$@"
    fi
}

is_mountpoint() {
    awk -v p="$1" '$5 == p { found = 1 } END { exit !found }' /proc/self/mountinfo
}

bundled_select_services() {
    BUNDLED_PG=true
    BUNDLED_VALKEY=true
    if [ -n "$DB_HOST" ]; then
        BUNDLED_PG=false
        echo "[bundled] DB_HOST is set (${DB_HOST}): using that PostgreSQL; embedded PostgreSQL stays off." >&2
    fi
    if [ -n "$REDIS_URL" ]; then
        BUNDLED_VALKEY=false
        echo "[bundled] REDIS_URL is set: using that Redis/Valkey; embedded Valkey stays off." >&2
    fi
    if [ "$BUNDLED_PG" = true ]; then
        export DB_HOST="$PGSOCKET" DB_NAME=floppy DB_USER=floppy DB_PORT=5432
        # Unix socket, peer-local only: no password exists or is needed.
        export DB_SSL_MODE=disable
        export DB_PASSWORD=
    fi
    if [ "$BUNDLED_VALKEY" = true ]; then
        export REDIS_URL="redis://127.0.0.1:${VALKEY_PORT}"
    fi
}

bundled_prepare_users() {
    # PUID/PGID are normally applied later; the database files must belong to
    # the final identity, so map it now (the later step repeats it harmlessly).
    if [ "$RUNNING_AS_ROOT" = true ]; then
        groupmod -o -g "${PGID:-1000}" abc
        usermod -o -u "${PUID:-1000}" abc
    fi
}

bundled_init_postgres() {
    mkdir -p "$PGSOCKET" "$PG_BACKUP_DIR" "$PGDATA" 2>/dev/null || true
    if [ "$RUNNING_AS_ROOT" = true ]; then
        chown abc:abc "$PGSOCKET" "$PG_BACKUP_DIR" "$PGDATA" 2>/dev/null || true
    fi
    chmod 700 "$PGSOCKET"
    # A stale socket or lock from an unclean stop would block the next start.
    rm -f "$PGSOCKET"/.s.PGSQL.* 2>/dev/null || true

    restore_requested=false
    if [ -f "$RESTORE_FLAG" ]; then restore_requested=true; fi

    if [ -f "$PGDATA/PG_VERSION" ]; then
        found=$(cat "$PGDATA/PG_VERSION")
        if [ "$found" != "$PGMAJOR" ]; then
            bundled_fail "The database in ${PGDATA} is PostgreSQL ${found}, this image runs PostgreSQL ${PGMAJOR}. A major version is never upgraded automatically. Run the previous image, take a backup (floppy-bundled-backup), then follow the major-upgrade steps."
        fi
        [ -f "$BUNDLED_MARKER" ] || : > "$BUNDLED_MARKER"
        return 0
    fi

    # No cluster yet. Decide whether creating one is safe.
    if [ -n "$(ls -A "$PGDATA" 2>/dev/null | grep -v '^lost+found$')" ]; then
        bundled_fail "${PGDATA} is not empty but holds no PostgreSQL cluster. Refusing to initialise over it."
    fi
    if [ "${FLOPPY_BUNDLED_ALLOW_EPHEMERAL:-false}" != true ] && ! is_mountpoint "$PGDATA"; then
        bundled_fail "${PGDATA} is not a mounted volume, so the database would vanish when the container is recreated. Mount a host path at ${PGDATA} (or set FLOPPY_BUNDLED_ALLOW_EPHEMERAL=true for a throwaway test)."
    fi
    if [ -f "$BUNDLED_MARKER" ] && [ "$restore_requested" != true ]; then
        bundled_fail "This installation was initialised before, but ${PGDATA} is empty: the database volume is missing or was replaced. Mount the original volume, or restore a backup by placing a RESTORE file (see docs)."
    fi
    if [ ! -f "$BUNDLED_MARKER" ] && [ -s "${FLOPPY_DB_PATH:-${DATA_DIR}/db.sqlite3}" ]; then
        bundled_fail "Found an existing SQLite database at ${DATA_DIR}. The bundled image does not convert existing data. Keep using the standard image, or follow the migration guide."
    fi

    echo "[bundled] Initialising a new PostgreSQL ${PGMAJOR} cluster in ${PGDATA}" >&2
    as_service_user initdb -D "$PGDATA" -U floppy --auth-local=trust --auth-host=reject \
        --encoding=UTF8 --locale=C.UTF-8 >/dev/null || bundled_fail "initdb failed."
    : > "$BUNDLED_MARKER"
    BUNDLED_FRESH_CLUSTER=true
}

bundled_start_postgres() {
    as_service_user pg_ctl -D "$PGDATA" -w -t 120 \
        -o "-c listen_addresses='' -c unix_socket_directories='$PGSOCKET' -c unix_socket_permissions=0700" \
        start >/dev/null || bundled_fail "PostgreSQL did not start. Check ${PGDATA}/log or run the container logs."
    if [ "${BUNDLED_FRESH_CLUSTER:-false}" = true ] || ! as_service_user psql -h "$PGSOCKET" -U floppy -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='floppy'" | grep -q 1; then
        as_service_user createdb -h "$PGSOCKET" -U floppy floppy || bundled_fail "Could not create the floppy database."
    fi
    as_service_user psql -h "$PGSOCKET" -U floppy -d floppy -qc "CREATE EXTENSION IF NOT EXISTS vector" \
        || bundled_fail "pgvector is not available in this image."
}

bundled_apply_restore() {
    [ -f "$RESTORE_FLAG" ] || return 0
    name=$(tr -d '\r\n' < "$RESTORE_FLAG")
    dump="${PG_BACKUP_DIR}/$(basename "$name")"
    if [ ! -s "$dump" ]; then
        bundled_fail "RESTORE names ${name}, but ${dump} does not exist. Fix or delete ${RESTORE_FLAG}."
    fi
    echo "[bundled] Restoring database from ${dump}" >&2
    as_service_user dropdb -h "$PGSOCKET" -U floppy --if-exists floppy
    as_service_user createdb -h "$PGSOCKET" -U floppy floppy
    as_service_user psql -h "$PGSOCKET" -U floppy -d floppy -qc "CREATE EXTENSION IF NOT EXISTS vector" || true
    as_service_user pg_restore -h "$PGSOCKET" -U floppy -d floppy --no-owner --exit-on-error "$dump" \
        || bundled_fail "pg_restore failed; the RESTORE file was left in place."
    # Consume only after success, so a restart never replays it.
    mv "$RESTORE_FLAG" "${RESTORE_FLAG}.done"
    secret_copy="${dump%.dump}.secret_key"
    if [ -f "$secret_copy" ] && [ -n "${SECRET:-}${SECRET_FILE:-}" ]; then
        echo "[bundled] WARNING: SECRET or SECRET_FILE is set, so the secret saved with the backup was not restored. Set it to the original value or saved integration credentials will not decrypt." >&2
    elif [ -f "$secret_copy" ] && [ ! -e "${DATA_DIR}/secret_key" ]; then
        cp "$secret_copy" "${DATA_DIR}/secret_key"
        chmod 600 "${DATA_DIR}/secret_key"
        if [ "$RUNNING_AS_ROOT" = true ]; then chown abc:abc "${DATA_DIR}/secret_key"; fi
        echo "[bundled] Restored the signing secret saved with the backup." >&2
    fi
    echo "[bundled] Restore complete." >&2
}

bundled_start_valkey() {
    mkdir -p "$VALKEY_DIR"
    if [ "$RUNNING_AS_ROOT" = true ]; then chown abc:abc "$VALKEY_DIR" 2>/dev/null; fi
    as_service_user valkey-server --bind 127.0.0.1 --port "$VALKEY_PORT" --dir "$VALKEY_DIR" \
        --save "300 1" --daemonize yes --pidfile "$VALKEY_DIR/valkey.pid" --logfile "" >/dev/null
    i=0
    until valkey-cli -h 127.0.0.1 -p "$VALKEY_PORT" ping 2>/dev/null | grep -q PONG; do
        i=$((i + 1))
        if [ "$i" -gt 30 ]; then bundled_fail "Valkey did not become ready."; fi
        sleep 1
    done
}

# Called before migrations: bring both services up for the one-shot work.
bundled_start() {
    bundled_select_services
    bundled_prepare_users
    if [ "$BUNDLED_PG" = true ]; then
        bundled_init_postgres
        bundled_start_postgres
        bundled_apply_restore
    fi
    if [ "$BUNDLED_VALKEY" = true ]; then bundled_start_valkey; fi
    echo "[bundled] postgres=${BUNDLED_PG} valkey=${BUNDLED_VALKEY}" >&2
}

# Called after migrations: stop the one-shot instances (clean, fast shutdown)
# and register the supervised ones. supervisord owns them from here.
bundled_handoff() {
    if [ "$BUNDLED_PG" = true ]; then as_service_user pg_ctl -D "$PGDATA" -m fast -w -t 120 stop >/dev/null; fi
    if [ "$BUNDLED_VALKEY" = true ]; then
        valkey-cli -h 127.0.0.1 -p "$VALKEY_PORT" shutdown save >/dev/null 2>&1 || true
    fi
    mkdir -p "$SUPERVISOR_FRAGMENTS"
    rm -f "$SUPERVISOR_FRAGMENTS"/*.conf
    if [ "$BUNDLED_PG" = true ]; then cp /etc/supervisord.d/postgres.conf /etc/supervisord.d/pg-backup.conf "$SUPERVISOR_FRAGMENTS"/; fi
    if [ "$BUNDLED_VALKEY" = true ]; then cp /etc/supervisord.d/valkey.conf "$SUPERVISOR_FRAGMENTS"/; fi
    if [ "$RUNNING_AS_ROOT" = false ]; then
        sed -i '/^user=/d' "$SUPERVISOR_FRAGMENTS"/*.conf 2>/dev/null || true
    fi
}
