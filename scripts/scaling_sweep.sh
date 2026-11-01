#!/usr/bin/env bash
# Run scripts/surface_sweep.py against each synthetic DB from scripts/scaling_seed.py.
# Own DB file, own port, own Redis db 5 / prefix "scale"; never the dev DB.
#   scripts/scaling_sweep.sh <label> <size>...   (sizes: 0 100 1000 ... or "shapes")
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
DIR="${SCALE_DIR:-/private/tmp/floppy-scale}"
PORT="${SCALE_PORT:-8100}"
label="${1:?label}"; shift
cat >"$DIR/scale_settings.py" <<PY
import os
from pathlib import Path
from config.settings import *  # noqa
DATABASES["default"]["NAME"] = Path(os.environ["SCALE_DB"])  # noqa
IS_PROD = False
PY
for size in "$@"; do
  db="$DIR/s${size}.sqlite3"; [ "$size" = shapes ] && db="$DIR/shapes.sqlite3"
  # work on a throwaway copy so write actions never dirty the seed
  rm -f "$DIR"/run.sqlite3*; cp "$db" "$DIR/run.sqlite3"
  export SCALE_DB="$DIR/run.sqlite3" PYTHONPATH="$DIR:$REPO/src" DJANGO_SETTINGS_MODULE=scale_settings
  export REDIS_URL=redis://localhost:6379/5 REDIS_PREFIX=scale ALLOWED_HOSTS=localhost,127.0.0.1
  export FLOPPY_AUTO_LOGIN_USERNAME=scale PERF_LOG_SLOW_REQUEST_MS=100000 SECRET=scaling-test
  export FLOPPY_PROCESS_ROLE=web OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
  redis-cli -n 5 flushdb >/dev/null
  (cd src && uv run --project "$REPO" --no-sync gunicorn --bind "localhost:$PORT" --workers 1 --timeout 600 \
     --config python:config.gunicorn config.wsgi:application >"$DIR/gunicorn_$size.log" 2>&1) &
  for _ in $(seq 120); do curl -s -o /dev/null "http://localhost:$PORT/ping/" && break; sleep 1; done
  BENCH_DIR="$DIR/out" python3 scripts/surface_sweep.py --base "http://localhost:$PORT" --runs 3 \
    --flush-cmd "redis-cli -n 5 flushdb" --label "${label}_$size" --fragments >"$DIR/sweep_${label}_$size.txt" 2>&1
  pkill -f "gunicorn.*$PORT" || true; sleep 2
  echo "done $size"; uptime
done
