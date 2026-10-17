#!/usr/bin/env bash
# Local dev server: migrate, then runserver with DEBUG on. Python edits restart
# the server and template/static edits refresh the open browser tab.
#
#   scripts/dev.sh             web only, on PORT (default 8000)
#   scripts/dev.sh --css       also run the Tailwind watcher
#   scripts/dev.sh --celery    also run both Celery workers
#
# The Tailwind watcher rewrites the committed src/static/css/main.css, and a
# build that cannot see every template (a worktree without wiki/, for example)
# drops classes. Only pass --css when you add utilities, and review the diff.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
WITH_CSS=false
WITH_CELERY=false
for arg in "$@"; do
  case "$arg" in
    --css) WITH_CSS=true ;;
    --celery) WITH_CELERY=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$ROOT"
if [[ ! -f .env ]]; then
  echo ".env is missing. See README.md for the required values." >&2
  exit 1
fi
set -a
source .env
set +a
export DEBUG=True

REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
if ! redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
  echo "Redis is not answering at $REDIS_URL. Start it (brew services start redis) and retry." >&2
  exit 1
fi

pids=()
cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd src
uv run --no-sync python manage.py migrate --no-input

if $WITH_CSS; then
  [[ -d "$ROOT/node_modules" ]] || npm --prefix "$ROOT" install --no-audit --no-fund
  "$ROOT/node_modules/.bin/tailwindcss" -i ./static/css/input.css -o ./static/css/main.css --watch &
  pids+=($!)
fi

if $WITH_CELERY; then
  uv run --no-sync celery -A config worker --queues interactive --hostname "celery-interactive@%h" --loglevel INFO &
  pids+=($!)
  uv run --no-sync celery -A config worker --queues celery --beat --scheduler django --hostname "celery@%h" --loglevel INFO &
  pids+=($!)
fi

uv run --no-sync python manage.py runserver "127.0.0.1:$PORT"
