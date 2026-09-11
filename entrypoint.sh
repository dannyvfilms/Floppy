#!/bin/sh

set -e

# A stray environment override (an orchestrator's persisted .env, a leftover
# manual "docker run -e", etc.) can shadow the image's own VERSION/COMMIT_SHA
# and make every VERSION/COMMIT_SHA reader in this container -- this script,
# Django's own settings, the startup-status sidecar -- silently misreport
# which build is actually running. This file is baked into the image and
# cannot be shadowed that way, so it is authoritative here whenever present;
# exporting it early means every later reader, including child processes,
# sees the corrected value.
if [ -f /etc/floppy-build-info ]; then
    . /etc/floppy-build-info
    export VERSION COMMIT_SHA
fi

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

# Point the operator at the diagnostic at the moment it is needed, which is the
# only moment they are reading these lines. The two forms are not
# interchangeable: "docker exec" needs a running container, so it works while
# startup is parked and fails with "Container is restarting" once a path exits
# and a restart policy takes over. Each failure below prints the form that works
# for it.
# HOSTNAME is the Docker container ID, which is stable for the life of one
# container but changes on every recreation, so a command captured from an
# earlier log becomes unusable. HOST_CONTAINERNAME (set by the orchestrator,
# e.g. Unraid) or the Compose service name survive recreation and stay valid.
PREFLIGHT_HINT_EXEC="For a full diagnosis run: docker exec ${HOST_CONTAINERNAME:-floppy} python manage.py floppy_preflight"
PREFLIGHT_HINT_RUN="For a full diagnosis run: docker compose run --rm floppy python manage.py floppy_preflight"

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
BACKUP_DIR_INPUT=${BACKUP_DIR:-/floppy/backups}
BACKUP_DIR_PATH=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$BACKUP_DIR_INPUT")

reject_unsafe_managed_directory FLOPPY_DATA_DIR "$DATA_DIR"
reject_unsafe_managed_directory LOG_DIR "$LOG_DIR_PATH"
reject_unsafe_managed_directory BACKUP_DIR "$BACKUP_DIR_PATH"

# Check the mounts with the shell, before anything imports Django.
#
# A read-only or wrongly owned mount is the most common reason a container will
# not start, and it is the one failure floppy_preflight cannot report: Django
# opens its log file while it loads settings, so the process dies with a
# traceback before the command runs. Test it here, where a clear message is
# still possible, and say which directory and which fix.
# Name an unwritable directory before Django loads.
#
# This reports and never stops. The gates that follow already stop: the
# ownership step exits when it cannot chown the data directory, and Django
# raises when it cannot create the generated secret. What neither of them gives
# is a readable line for the log directory, because Django opens its log file
# while it loads settings, so the process dies with a logging traceback before
# any of Floppy's own messages appear. This is that line.
#
# Reporting rather than exiting also keeps the check harmless: a pre-check that
# can fail a start which would otherwise have worked is worse than no check.
warn_when_not_writable() {
    name=$1
    directory=$2
    if [ ! -d "$directory" ]; then
        # Absent is normal on a first start. Django creates both of these.
        return 0
    fi
    probe="${directory}/.floppy-write-probe.$$"
    if ! (: > "$probe") 2>/dev/null; then
        echo "[entrypoint] WARNING: ${name} ${directory} is not writable." >&2
        echo "[entrypoint] The mount is read-only, or it belongs to another user. Give it to PUID=${PUID:-1000} PGID=${PGID:-1000} on the host. Startup will fail until then." >&2
        return 0
    fi
    rm -f "$probe"
    return 0
}

warn_when_not_writable FLOPPY_DATA_DIR "$DATA_DIR"
warn_when_not_writable LOG_DIR "$LOG_DIR_PATH"
warn_when_not_writable BACKUP_DIR "$BACKUP_DIR_PATH"

# Safe identifiers only, so this line can be pasted into a bug report without
# redaction. Correlates a log against the image that produced it, and against
# a specific container instance when HOSTNAME/HOST_CONTAINERNAME diverge.
echo "[entrypoint] Floppy runtime: version=${VERSION:-unknown} commit=${COMMIT_SHA:-unknown} hostname=${HOSTNAME:-unknown} container_name=${HOST_CONTAINERNAME:-floppy}" >&2

if [ -z "$DB_HOST" ]; then
    DB_FILE_INPUT=${FLOPPY_DB_PATH:-"${DATA_DIR_INPUT}/db.sqlite3"}
    DB_FILE=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$DB_FILE_INPUT")
    DB_PARENT=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).parent)' "$DB_FILE")

    reject_unsafe_managed_directory FLOPPY_DB_PATH "$DB_PARENT"

    # Check storage before migrations. The recovery policy preserves rows when
    # a broken nullable reference can be cleared, removes only known derived
    # relationship rows automatically, and requires an incident-scoped operator
    # choice before a row with a required missing parent can be removed.
    if [ -f "$DB_FILE" ]; then
        while :; do
            echo "[entrypoint] Checking SQLite storage and relationships for ${DB_FILE}" >&2
            integrity_status=0
            integrity_pid=
            heartbeat_pid=
            # One bound, used by the command and its operator message, so the two
            # can never drift apart.
            integrity_timeout=600
            trap 'kill "$integrity_pid" 2>/dev/null || :; wait "$integrity_pid" 2>/dev/null || :; kill "$heartbeat_pid" 2>/dev/null || :; wait "$heartbeat_pid" 2>/dev/null || :; exit 0' TERM INT
            timeout "$integrity_timeout" python -c 'from config.sqlite_recovery_policy import check_database_for_startup; import sys; check_database_for_startup(sys.argv[1])' "$DB_FILE" &
            integrity_pid=$!
            # Heartbeats come from the status sidecar the scan itself writes,
            # not from polling the scanner's PID, so a missing or malformed
            # sidecar can never take the entrypoint down under "set -e".
            (
                while :; do
                    sleep 30
                    python -c 'from config.sqlite_integrity import print_startup_heartbeat; import sys; print_startup_heartbeat(sys.argv[1])' "$DB_FILE" 2>&1 || :
                done
            ) &
            heartbeat_pid=$!
            wait "$integrity_pid" || integrity_status=$?
            kill "$heartbeat_pid" 2>/dev/null || :
            wait "$heartbeat_pid" 2>/dev/null || :
            trap - TERM INT
            if [ "$integrity_status" -eq 0 ]; then
                break
            fi
            case "$integrity_status" in
                124|143)
                    # The scanner may have been killed before it could publish
                    # its own terminal status, so the sidecar is confirmed here.
                    python -c 'from config.sqlite_integrity import mark_startup_status_timeout; import sys; mark_startup_status_timeout(sys.argv[1], float(sys.argv[2]))' "$DB_FILE" "$integrity_timeout" 2>&1 || :
                    echo "[entrypoint] SQLite integrity check exceeded its ${integrity_timeout}s timeout; startup is paused before migrations and services. The container will remain unhealthy and idle." >&2
                    ;;
                *)
                    echo "[entrypoint] SQLite startup is paused because the integrity check failed; migrations and services were not started. The container will remain unhealthy and idle." >&2
                    ;;
            esac
            # The container stays up while it is parked, so "exec" can attach.
            echo "[entrypoint] ${PREFLIGHT_HINT_EXEC}" >&2
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
            # the loop can apply the decision before migrations run.
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
        # This path exits, so a restart policy puts the container into a restart
        # loop. "exec" cannot attach to a restarting container, so name the
        # one-off form here instead.
        echo "[entrypoint] ${PREFLIGHT_HINT_RUN}" >&2
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

# "backups" holds scheduled CSV exports (settings.BACKUP_DIR). It can be an
# operator-selected bind mount too, and a fresh one is root-owned like any
# other new bind mount, so give it the same non-fatal chown as LOG_DIR rather
# than leaving abc-owned processes unable to write scheduled exports.
if [ -e "$BACKUP_DIR_PATH" ] && ! timeout 600 chown abc:abc -- "$BACKUP_DIR_PATH"; then
    echo "[entrypoint] WARNING: chown of ${BACKUP_DIR_PATH} failed or timed out (stalled mount?); continuing" >&2
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

# Docker 25+ and recent containerd give a container an effectively unlimited
# RLIMIT_NOFILE, so SC_OPEN_MAX inside it reads as 2147483584. Celery's
# embedded beat calls billiard's close_open_fds() during startup, which closes
# every descriptor up to that number one at a time: the process pins a core for
# hours before "beat: Starting..." appears, and no scheduled task runs until it
# does (celery/celery#8306, still open). Lower the soft limit here, once, so
# every supervised child inherits it. The hard limit is untouched, so an
# operator who needs more can raise FLOPPY_NOFILE_LIMIT or the soft limit again.
NOFILE_SOFT=${FLOPPY_NOFILE_LIMIT:-65536}
current_nofile=$(ulimit -n 2>/dev/null || echo unlimited)
if [ "$current_nofile" = "unlimited" ] || [ "$current_nofile" -gt "$NOFILE_SOFT" ] 2>/dev/null; then
    if ulimit -n "$NOFILE_SOFT" 2>/dev/null; then
        echo "[entrypoint] Open-file soft limit lowered from ${current_nofile} to ${NOFILE_SOFT} (celery/celery#8306)" >&2
    else
        echo "[entrypoint] WARNING: open-file soft limit is ${current_nofile} and could not be lowered; celery beat may take hours to start" >&2
    fi
fi

echo "[entrypoint] Starting services" >&2
exec supervisord -c /etc/supervisord.conf
