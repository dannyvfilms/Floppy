#!/usr/bin/env bash
# Verify the standard-tier Celery worker topology in a disposable Compose project.
#
# Usage:
#   scripts/smoke_worker_topology.sh --image floppy:worker-topology
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${FLOPPY_WORKER_TOPOLOGY_IMAGE:-floppy:worker-topology}"

usage() {
  echo "Usage: $0 [--image IMAGE]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image)
      IMAGE="${2:?missing image after --image}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

PROJECT="floppy-worker-topology-$$"
COMPOSE=(docker compose --progress quiet -p "$PROJECT" -f docker-compose.memory-benchmark.yml)

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting standard-tier worker topology smoke test with $IMAGE"
FLOPPY_BENCHMARK_IMAGE="$IMAGE" "${COMPOSE[@]}" up -d --wait --wait-timeout 180

active_queues=$("${COMPOSE[@]}" exec -T floppy celery --app config inspect active_queues --timeout=10 --json)
printf '%s\n' "$active_queues" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise SystemExit("active_queues did not return a worker mapping")

def queues_for(value):
    if isinstance(value, dict) and "ok" in value:
        value = value["ok"]
    if not isinstance(value, list):
        return set()
    return {entry.get("name") for entry in value if isinstance(entry, dict)}

workers = {name: queues_for(queues) for name, queues in payload.items()}
background = {name: queues for name, queues in workers.items() if name.startswith("celery@")}
interactive = {
    name: queues
    for name, queues in workers.items()
    if name.startswith("celery-interactive@")
}
discover = {
    name: queues
    for name, queues in workers.items()
    if name.startswith("celery-discover@")
}

if len(background) != 1 or next(iter(background.values())) != {"celery", "discover"}:
    raise SystemExit(f"unexpected background topology: {background}")
if len(interactive) != 1 or next(iter(interactive.values())) != {"interactive"}:
    raise SystemExit(f"unexpected interactive topology: {interactive}")
if discover:
    raise SystemExit(f"discover worker must be merged on standard tier: {discover}")

print("Verified:")
for name, queues in sorted(workers.items()):
    print(f"  {name}: {sorted(queues)}")
'

processes=$("${COMPOSE[@]}" exec -T floppy sh -c 'ps 2>/dev/null || true')
if printf '%s\n' "$processes" | grep -Fq 'celery-discover'; then
  echo "unexpected celery-discover process on standard tier" >&2
  exit 1
fi

api_key=$("${COMPOSE[@]}" exec -T floppy python manage.py shell -v 0 -c '
from django.contrib.auth import get_user_model
user = get_user_model().objects.create_user(username="worker-topology-smoke")
print(user.token)
' | tail -n 1)
background_task_id=$("${COMPOSE[@]}" exec -T floppy celery --app config call "Warm History Day Cache Coverage")
api_response=$("${COMPOSE[@]}" exec -T -e SMOKE_API_KEY="$api_key" floppy sh -c '
    wget --quiet --timeout=5 --output-document=- \
        --header="X-API-Key: $SMOKE_API_KEY" \
        "http://127.0.0.1:8000/api/v1/history/?limit=1"
')
printf '%s\n' "$api_response" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if not isinstance(payload, dict) or "results" not in payload:
    raise SystemExit(f"unexpected authenticated history response: {payload!r}")
if len(payload["results"]) > 1:
    raise SystemExit("authenticated history response exceeded limit=1")
'
echo "Authenticated history request remained responsive while background task ${background_task_id} was queued"

echo "Worker topology smoke test passed"
