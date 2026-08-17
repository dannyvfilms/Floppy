#!/bin/sh

set -e

# The packaged runtime wrapper passes the already-resolved public listener.
# Direct entrypoint use can omit it; the recovery server then uses the same
# local resolver itself if database recovery is needed.
RUNTIME_SERVER_PORT=${1:-}

# Keep the application virtual environment first even if an orchestrator
# restores a stale PATH. A matching entry later in PATH is not sufficient,
# because an earlier system Python would still be selected (issue #762).
if [ -d "/opt/venv/bin" ]; then
    VIRTUAL_ENV="/opt/venv"
elif [ -d "/floppy/.venv/bin" ]; then
    VIRTUAL_ENV="/floppy/.venv"
elif [ -n "$VIRTUAL_ENV" ] && [ -d "$VIRTUAL_ENV/bin" ] && [ "$VIRTUAL_ENV" != "$PWD/.venv" ]; then
    VIRTUAL_ENV="$VIRTUAL_ENV"
else
    VIRTUAL_ENV=""
fi

if [ -n "$VIRTUAL_ENV" ]; then
    case "$PATH" in
        "$VIRTUAL_ENV/bin"|"$VIRTUAL_ENV/bin:"*) ;;
        *) PATH="$VIRTUAL_ENV/bin${PATH:+:$PATH}" ;;
    esac
    export VIRTUAL_ENV PATH
fi

reject_unsafe_managed_directory() {
    managed_name=$1
    managed_dir=$2
    case "$managed_dir" in
        /|/bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/libx32|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/usr/bin|/usr/include|/usr/lib|/usr/lib32|/usr/lib64|/usr/libx32|/usr/local|/usr/sbin|/usr/share|/usr/src|/var/backups|/var/cache|/var/lib|/var/local|/var/lock|/var/log|/var/mail|/var/opt|/var/spool|/var/tmp)
            echo "[entrypoint] ${managed_name} must resolve to a dedicated directory, not system directory ${managed_dir}." >&2
            exit 1
            ;;
    esac
}

DATA_DIR_INPUT=${FLOPPY_DATA_DIR:-/floppy/db}
DATA_DIR=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$DATA_DIR_INPUT")
LOG_DIR_INPUT=${LOG_DIR:-/floppy/logs}
LOG_DIR_PATH=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$LOG_DIR_INPUT")

reject_unsafe_managed_directory FLOPPY_DATA_DIR "$DATA_DIR"
reject_unsafe_managed_directory LOG_DIR "$LOG_DIR_PATH"

if [ -z "$DB_HOST" ]; then
    DB_FILE_INPUT=${FLOPPY_DB_PATH:-"${DATA_DIR_INPUT}/db.sqlite3"}
    DB_FILE=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$DB_FILE_INPUT")
    DB_PARENT=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).parent)' "$DB_FILE")

    reject_unsafe_managed_directory FLOPPY_DB_PATH "$DB_PARENT"

    # Check storage before migrations. Known disposable album credits are
    # repaired; other conflicts require an incident-scoped operator choice.
    if [ -f "$DB_FILE" ]; then
        while :; do
            echo "[entrypoint] Checking SQLite storage and relationships for ${DB_FILE}" >&2
            integrity_status=0
            integrity_pid=
            # One bound, used by the command and its operator message, so the two
            # can never drift apart.
            integrity_timeout=600
            trap 'kill "$integrity_pid" 2>/dev/null || :; wait "$integrity_pid" 2>/dev/null || :; exit 0' TERM INT
            timeout "$integrity_timeout" python -c 'from config.sqlite_integrity import check_database_integrity; import sys; check_database_integrity(sys.argv[1])' "$DB_FILE" &
            integrity_pid=$!
            wait "$integrity_pid" || integrity_status=$?
            trap - TERM INT
            if [ "$integrity_status" -eq 0 ]; then
                break
            fi
            case "$integrity_status" in
                124|143)
                    echo "[entrypoint] SQLite integrity check exceeded its ${integrity_timeout}s timeout; startup is paused before migrations and services. The container will remain unhealthy and idle." >&2
                    ;;
                *)
                    echo "[entrypoint] SQLite startup is paused because the integrity check failed; migrations and services were not started. The container will remain unhealthy and idle." >&2
                    ;;
            esac
            decision_file="${DB_FILE}.integrity.decision"
            # The check above consumes a choice it can act on. Anything left is
            # stale, and a stale file would defeat the parking guard below and
            # spin this loop without a bound. Clear it before serving the page,
            # so only a choice made in this pass can resume startup.
            rm -f "$decision_file"
            parking_pid=
            trap 'kill "$parking_pid" 2>/dev/null || :; wait "$parking_pid" 2>/dev/null || :; exit 0' TERM INT
            # Show the recovery page. It writes a copy beside the database, then
            # serves it. If a choice is submitted, the server exits cleanly so
            # the loop can apply the decision and continue to migrations.
            if [ -n "$RUNTIME_SERVER_PORT" ]; then
                python -m config.sqlite_recovery_server "$DB_FILE" "$RUNTIME_SERVER_PORT" &
            else
                python -m config.sqlite_recovery_server "$DB_FILE" &
            fi
            parking_pid=$!
            wait "$parking_pid" || :
            if [ ! -f "$decision_file" ]; then
                while :; do
                    sleep 86400 &
                    parking_pid=$!
                    wait "$parking_pid" || :
                done
            fi
            trap - TERM INT
        done
    fi
fi

# Bounded, retrying migrate: a blocked migration must fail loudly and retry
# instead of wedging the container as "unhealthy" forever (issue #341).
# lock_timeout is libpq-only (ignored on SQLite) and fires only while waiting
# on a lock, so long data migrations are unaffected. Retries escalate to
# verbosity 2 so Django names each pre/post-migrate handler phase in the logs.
migrate_attempts=0
migrate_verbosity=1
until echo "[entrypoint] Applying database migrations (attempt $((migrate_attempts + 1)))" >&2 && \
      DB_POOL_ENABLED=false PGOPTIONS="-c lock_timeout=120s" \
      timeout 900 python manage.py migrate --noinput -v "$migrate_verbosity"; do
    migrate_attempts=$((migrate_attempts + 1))
    migrate_verbosity=2
    if [ "$migrate_attempts" -ge 5 ]; then
        echo "[entrypoint] Migrations failed after ${migrate_attempts} attempts, exiting" >&2
        exit 1
    fi
    echo "[entrypoint] Migrations blocked or failed (attempt ${migrate_attempts}), retrying in 15s" >&2
    sleep 15
done

PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "[entrypoint] Fixing file ownership (PUID=${PUID} PGID=${PGID})" >&2

groupmod -o -g "$PGID" abc
usermod -o -u "$PUID" abc

chown abc:abc -- /floppy

if [ -e "$DATA_DIR" ] && ! timeout 600 chown abc:abc -- "$DATA_DIR"; then
    echo "[entrypoint] Cannot set ownership for FLOPPY_DATA_DIR ${DATA_DIR} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
    exit 1
fi

generated_secret_file="${DATA_DIR}/secret_key"
if { [ -e "$generated_secret_file" ] || [ -L "$generated_secret_file" ]; } && \
   ! timeout 600 chown -h abc:abc -- "$generated_secret_file"; then
    echo "[entrypoint] Cannot set ownership for generated secret ${generated_secret_file} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
    exit 1
fi

if [ -z "$DB_HOST" ]; then
    if [ -e "$DB_PARENT" ] && ! timeout 600 chown abc:abc -- "$DB_PARENT"; then
        echo "[entrypoint] Cannot set ownership for FLOPPY_DB_PATH parent ${DB_PARENT} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
        exit 1
    fi
    for path in "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"; do
        if { [ -e "$path" ] || [ -L "$path" ]; } && \
           ! timeout 600 chown -h abc:abc -- "$path"; then
            echo "[entrypoint] Cannot set ownership for SQLite file ${path} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
            exit 1
        fi
    done
fi

# "logs" holds the rotating file handler every process configures at import time
# (settings.LOG_FILE). settings.py creates the directory, so whichever process
# imports settings first as root leaves it root-owned and every abc-owned
# process then dies with "Unable to configure handler 'file'" -- taking gunicorn
# with it, so the container serves 502s while reporting healthy.
#
# The log directory can be an operator-selected mount. Change only that
# directory entry and Floppy's current log file, never unrelated content.
if [ -e "$LOG_DIR_PATH" ] && ! timeout 600 chown abc:abc -- "$LOG_DIR_PATH"; then
    echo "[entrypoint] WARNING: chown of ${LOG_DIR_PATH} failed or timed out (stalled mount?); continuing" >&2
fi
log_file_path="${LOG_DIR_PATH}/floppy.log"
if { [ -e "$log_file_path" ] || [ -L "$log_file_path" ]; } && \
   ! timeout 600 chown -h abc:abc -- "$log_file_path"; then
    echo "[entrypoint] WARNING: chown of ${log_file_path} failed or timed out (stalled mount?); continuing" >&2
fi

# Bound recursive ownership fixes for the image-managed service directories: a
# stalled bind mount must degrade to a warning instead of hanging boot (#341).
for dir in /floppy/staticfiles /var/log/nginx /var/lib/nginx; do
    echo "[entrypoint] Chowning ${dir}" >&2
    timeout 600 chown -R abc:abc -- "$dir" || \
        echo "[entrypoint] WARNING: chown of ${dir} failed or timed out (stalled mount?); continuing" >&2
done

# Probe the host once, here, and export the sizing decision for supervisord to
# expand into each program's command line. Doing it per-process would let the
# six supervised processes disagree about the tier if the host's free memory
# moved between their startups (issue #521). Values already set by the user are
# echoed back untouched, so an explicit WEB_CONCURRENCY always wins.
if resource_env=$(python -c 'from config.runtime_profile import emit_env; emit_env()'); then
    eval "$resource_env"
else
    echo "[entrypoint] WARNING: resource detection failed; using built-in defaults" >&2
fi
export FLOPPY_RESOURCE_TIER="${FLOPPY_RESOURCE_TIER:-standard}"
export FLOPPY_CELERY_QUEUES="${FLOPPY_CELERY_QUEUES:-celery}"
export FLOPPY_CELERY_ROLE="${FLOPPY_CELERY_ROLE:-background}"
export FLOPPY_START_INTERACTIVE_WORKER="${FLOPPY_START_INTERACTIVE_WORKER:-true}"
export FLOPPY_START_DISCOVER_WORKER="${FLOPPY_START_DISCOVER_WORKER:-true}"

if [ "$FLOPPY_START_INTERACTIVE_WORKER" = "true" ]; then
    interactive_topology="on(interactive)"
else
    interactive_topology="off(combined)"
fi
if [ "$FLOPPY_START_DISCOVER_WORKER" = "true" ]; then
    discover_topology="on(discover)"
else
    discover_topology="off(merged)"
fi
echo "[entrypoint] celery workers background=on(${FLOPPY_CELERY_QUEUES}) interactive=${interactive_topology} discover=${discover_topology}" >&2

echo "[entrypoint] Starting services" >&2
exec supervisord -c /etc/supervisord.conf
