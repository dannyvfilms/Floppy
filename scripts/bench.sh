#!/usr/bin/env bash
# Isolated latency-benchmark harness for page-navigation work.
#
# Isolation contract (never touches dev state):
#   - DB:    a .backup copy of src/db/db.sqlite3 in $BENCH_DIR (default
#            ${TMPDIR:-/tmp}/yamtrack-bench). The real dev DB is opened
#            read-only, once, for the copy.
#   - Redis: db 3 with key prefix "bench" (dev uses db 0, unprefixed).
#            `flush` only ever flushes db 3.
#
# Usage:
#   scripts/bench.sh up               Copy DB (reused if present; BENCH_FRESH_DB=1
#                                     forces a fresh copy), migrate it, start gunicorn (port
#                                     $BENCH_PORT, default 8001) + 3 celery
#                                     workers (celery/interactive/discover).
#                                     Runs in the foreground; Ctrl-C stops it.
#   scripts/bench.sh sweep <label>    curl each surface N times ($BENCH_RUNS,
#                                     default 7); median/p90 per endpoint to
#                                     stdout and $BENCH_DIR/results_<label>.tsv.
#   scripts/bench.sh history-api <label>
#                                     Benchmark the authenticated history API
#                                     cases. Requires BENCH_API_KEY.
#   scripts/bench.sh flush            Flush redis db 3 (cold-cache state).
#   scripts/bench.sh down             Stop bench processes.
#
# Protocol used for before/after comparisons (July 2026 pass):
#   1. up (fresh DB copy re-triggers startup backfills = "under load")
#   2. sweep while backfills run, 3-4 reps
#   3. wait for quiet (or SIGSTOP the celery worker), flush, sweep once (cold)
#   4. sweep twice, keep the second (warm steady state)
# Per-request duration_ms + query counts come from slow_request log lines
# (set PERF_LOG_SLOW_REQUEST_MS=25 to log nearly everything).
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"
BENCH_DIR="${BENCH_DIR:-${TMPDIR:-/tmp}/yamtrack-bench}"
BENCH_PORT="${BENCH_PORT:-8001}"
BENCH_RUNS="${BENCH_RUNS:-7}"
BENCH_USER="${BENCH_USER:-dannyvfilms}"
BASE="http://localhost:$BENCH_PORT"

bench_env() {
  export PYTHONPATH="$BENCH_DIR:$REPO/src"
  export DJANGO_SETTINGS_MODULE=bench_settings
  export REDIS_URL=redis://localhost:6379/3
  export REDIS_PREFIX=bench
  export ALLOWED_HOSTS="localhost,127.0.0.1"
  export FLOPPY_AUTO_LOGIN_USERNAME="$BENCH_USER"
  export PERF_LOG_SLOW_REQUEST_MS="${PERF_LOG_SLOW_REQUEST_MS:-25}"
}

write_settings() {
  cat >"$BENCH_DIR/bench_settings.py" <<EOF
"""Bench settings: real settings against an isolated DB copy (generated)."""
from pathlib import Path

from config.settings import *  # noqa: F403

DATABASES["default"]["NAME"] = Path("$BENCH_DIR") / "db.sqlite3"  # noqa: F405
# No nginx in front of the bench gunicorn; let Django serve /static/.
IS_PROD = False
EOF
}

cmd_up() {
  mkdir -p "$BENCH_DIR"
  if [ ! -f "$BENCH_DIR/db.sqlite3" ] || [ "${BENCH_FRESH_DB:-0}" = "1" ]; then
    echo "Copying dev DB (read-only backup) -> $BENCH_DIR/db.sqlite3"
    sqlite3 "file:$REPO/src/db/db.sqlite3?mode=ro" ".backup '$BENCH_DIR/db.sqlite3'"
  fi
  write_settings
  bench_env
  redis-cli -n 3 flushdb >/dev/null
  cd "$REPO/src"
  uv run --project "$REPO" --no-sync python manage.py migrate >/dev/null
  uv run --project "$REPO" --no-sync celery --app config worker --queues celery --hostname "bench-celery@%h" \
    --loglevel INFO --without-mingle --without-gossip \
    >"$BENCH_DIR/celery-background.log" 2>&1 &
  FLOPPY_PROCESS_ROLE=interactive uv run --project "$REPO" --no-sync celery --app config worker --queues interactive \
    --hostname "bench-interactive@%h" --loglevel INFO --without-mingle --without-gossip \
    >"$BENCH_DIR/celery-interactive.log" 2>&1 &
  uv run --project "$REPO" --no-sync celery --app config worker --queues discover --hostname "bench-discover@%h" \
    --loglevel INFO --without-mingle --without-gossip \
    >"$BENCH_DIR/celery-discover.log" 2>&1 &
  echo "Bench up on $BASE (logs in $BENCH_DIR). Ctrl-C to stop."
  export FLOPPY_PROCESS_ROLE=web
  exec uv run --project "$REPO" --no-sync gunicorn --bind "localhost:$BENCH_PORT" \
    --config python:config.gunicorn config.wsgi:application
}

cmd_down() {
  pkill -f "bench-celery@" 2>/dev/null || true
  pkill -f "bench-interactive@" 2>/dev/null || true
  pkill -f "bench-discover@" 2>/dev/null || true
  pkill -f "gunicorn.*config.wsgi" 2>/dev/null || true
  echo "Bench processes stopped."
}

cmd_flush() {
  redis-cli -n 3 flushdb
}

cmd_sweep() {
  local label="${1:?usage: scripts/bench.sh sweep <label>}"
  mkdir -p "$BENCH_DIR"
  local out="$BENCH_DIR/results_${label}.tsv"
  local endpoints=(
    "home|/"
    "home_rest|/home/rest/"
    "medialist_tv|/medialist/tv"
    "medialist_movie|/medialist/movie"
    "medialist_season|/medialist/season"
    "medialist_game|/medialist/game"
    "medialist_anime|/medialist/anime"
    "statistics|/statistics"
    "history|/history"
    "discover|/discover"
    "calendar|/calendar"
    "lists|/lists"
  )
  echo -e "endpoint\tstatus\tmedian_s\tp90_s\tmin_s\tmax_s\tn" >"$out"
  local entry name path code t stats
  for entry in "${endpoints[@]}"; do
    name="${entry%%|*}"
    path="${entry#*|}"
    local times=()
    for _ in $(seq "$BENCH_RUNS"); do
      # curl -w emits no trailing newline, so read exits nonzero; don't
      # let set -e treat that as a failure.
      read -r code t < <(curl -s -o /dev/null -w '%{http_code} %{time_total}' "$BASE$path") || true
      times+=("$t")
    done
    stats=$(printf '%s\n' "${times[@]}" | sort -g | awk -v n="$BENCH_RUNS" '
      { a[NR]=$1 }
      END {
        mid = (n % 2) ? a[(n+1)/2] : (a[n/2] + a[n/2+1]) / 2
        p90i = int(0.9 * n + 0.999); if (p90i < 1) p90i = 1; if (p90i > n) p90i = n
        printf "%.3f\t%.3f\t%.3f\t%.3f", mid, a[p90i], a[1], a[n]
      }')
    echo -e "${name}\t${code}\t${stats}\t${BENCH_RUNS}" >>"$out"
    echo "$name status=$code $stats"
  done
  echo "saved -> $out"
}

cmd_history_api() {
  local label="${1:?usage: scripts/bench.sh history-api <label>}"
  local api_key="${BENCH_API_KEY:?BENCH_API_KEY is required}"
  mkdir -p "$BENCH_DIR"
  local out="$BENCH_DIR/results_history_api_${label}.tsv"
  local endpoints=(
    "history_types|/api/v1/history/?limit=3&types=episodes,movies"
    "history_media_type|/api/v1/history/?limit=3&media_type=episode,movie"
    "history_all|/api/v1/history/?limit=3"
  )
  echo -e "case\tendpoint\tstatus\tmedian_s\tp90_s\tmin_s\tmax_s\tbytes\tn" >"$out"
  local entry name path code t bytes stats mode
  for mode in cold warm; do
    for entry in "${endpoints[@]}"; do
      name="${entry%%|*}"
      path="${entry#*|}"
      local times=()
      local statuses=()
      local sizes=()
      if [ "$mode" = warm ]; then
        redis-cli -n 3 flushdb >/dev/null
        for _ in 1 2; do
          curl -sS -o /dev/null \
            -H "X-API-Key: $api_key" \
            "$BASE$path" >/dev/null
        done
      fi
      for _ in $(seq "$BENCH_RUNS"); do
        if [ "$mode" = cold ]; then
          redis-cli -n 3 flushdb >/dev/null
        fi
        read -r code t bytes < <(
          curl -sS -o /dev/null \
            -H "X-API-Key: $api_key" \
            -w '%{http_code} %{time_total} %{size_download}' \
            "$BASE$path"
        ) || true
        statuses+=("$code")
        times+=("$t")
        sizes+=("$bytes")
      done
      stats=$(printf '%s\n' "${times[@]}" | sort -g | awk -v n="$BENCH_RUNS" '
      { a[NR]=$1 }
      END {
        mid = (n % 2) ? a[(n+1)/2] : (a[n/2] + a[n/2+1]) / 2
        p90i = int(0.9 * n + 0.999); if (p90i < 1) p90i = 1; if (p90i > n) p90i = n
        printf "%.3f\t%.3f\t%.3f\t%.3f", mid, a[p90i], a[1], a[n]
      }')
      code="${statuses[0]}"
      bytes="${sizes[0]}"
      echo -e "${mode}\t${name}\t${code}\t${stats}\t${bytes}\t${BENCH_RUNS}" >>"$out"
      echo "$mode/$name status=$code $stats bytes=$bytes"
    done
  done
  echo "saved -> $out"
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  flush) cmd_flush ;;
  sweep) shift; cmd_sweep "$@" ;;
  history-api) shift; cmd_history_api "$@" ;;
  *) awk 'NR > 1 && /^set -euo/ { exit } NR > 1' "$0"; exit 1 ;;
esac
