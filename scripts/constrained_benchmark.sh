#!/usr/bin/env bash
# Validate issue #521's fix under the exact reported constraint: 2 vCPU,
# 2 GB RAM, no swap, Postgres + Redis co-located, sustained page traffic
# plus background webhook/reconcile work.
#
# Usage:
#   scripts/constrained_benchmark.sh [--duration-seconds 600] [--image floppy:issue521-validation]
#
# The script never touches the application's compose project or volumes.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="floppy:issue521-validation"
DURATION="${CONSTRAINED_BENCHMARK_DURATION:-600}"
SAMPLE_INTERVAL="${CONSTRAINED_BENCHMARK_SAMPLE_INTERVAL:-15}"
OUTPUT_DIR="${CONSTRAINED_BENCHMARK_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/floppy-constrained.XXXXXX")}"
PROJECT="floppy-constrained-$$"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --duration-seconds) DURATION="${2:?}"; shift 2 ;;
    --image) IMAGE="${2:?}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?}"; shift 2 ;;
    --help|-h) echo "See header comment for usage."; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUTPUT_DIR"
SAMPLES_CSV="$OUTPUT_DIR/samples.csv"
PROBES_CSV="$OUTPUT_DIR/http_probes.csv"
printf '%s\n' 'elapsed_s,cgroup_bytes,redis_used_memory,redis_maxmemory,io_read_bytes,io_write_bytes' >"$SAMPLES_CSV"
printf '%s\n' 'elapsed_s,route,status,latency_ms' >"$PROBES_CSV"

compose() {
  FLOPPY_BENCHMARK_IMAGE="$IMAGE" docker compose -p "$PROJECT" -f docker-compose.constrained-benchmark.yml "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Building/starting constrained stack (image=$IMAGE) ..." >&2
compose up -d --wait --wait-timeout 180

echo "Running migrations ..." >&2
compose exec -T floppy python manage.py migrate --noinput >/dev/null

echo "Creating benchmark user ..." >&2
TOKEN=$(compose exec -T floppy python manage.py shell -c '
from users.models import User
user, _ = User.objects.get_or_create(username="constrained-benchmark", defaults={"is_active": True})
print(user.token)
' | tr -d '\r')

if [ -z "$TOKEN" ]; then
  echo "Failed to obtain webhook token" >&2
  exit 1
fi

BASE_URL="http://localhost:18000"
JELLYFIN_URL="$BASE_URL/integrations/jellyfin/webhook/$TOKEN"

io_stat() {
  # cgroup v2 io.stat: sum rbytes/wbytes across devices for the floppy container.
  compose exec -T floppy sh -c 'cat /sys/fs/cgroup/io.stat 2>/dev/null' 2>/dev/null | awk '
    { for (i = 2; i <= NF; i++) { split($i, kv, "="); sum[kv[1]] += kv[2] } }
    END { printf "%d,%d", sum["rbytes"]+0, sum["wbytes"]+0 }
  '
}

sample_metrics() {
  local elapsed="$1" cgroup redis_used redis_max io read_b write_b
  cgroup=$(compose exec -T floppy sh -c 'cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes' 2>/dev/null || echo 0)
  redis_used=$(compose exec -T redis redis-cli --raw INFO memory 2>/dev/null | awk -F: '/^used_memory:/ { gsub("\r","",$2); print $2 }')
  redis_max=$(compose exec -T redis redis-cli --raw INFO memory 2>/dev/null | awk -F: '/^maxmemory:/ { gsub("\r","",$2); print $2 }')
  io=$(io_stat)
  IFS=, read -r read_b write_b <<<"${io:-0,0}"
  printf '%s,%s,%s,%s,%s,%s\n' "$elapsed" "${cgroup:-0}" "${redis_used:-0}" "${redis_max:-0}" "${read_b:-0}" "${write_b:-0}" >>"$SAMPLES_CSV"
}

now_ms() {
  python3 -c 'import time; print(int(time.time() * 1000))'
}

probe_route() {
  local elapsed="$1" label="$2" url="$3" start status latency
  start=$(now_ms)
  status=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$url" || echo "000")
  latency=$(( $(now_ms) - start ))
  printf '%s,%s,%s,%s\n' "$elapsed" "$label" "$status" "$latency" >>"$PROBES_CSV"
}

fire_jellyfin_webhook() {
  local season=$((RANDOM % 5 + 1)) episode=$((RANDOM % 20 + 1))
  curl -s -o /dev/null -m 15 -X POST "$JELLYFIN_URL" \
    -H 'Content-Type: application/json' \
    -d "$(printf '{"Event":"Stop","Item":{"Type":"Episode","Name":"Load Test Episode","ProviderIds":{"Tvdb":"303821"},"SeriesName":"Load Test Show","ParentIndexNumber":%d,"IndexNumber":%d,"UserData":{"Played":true}}}' "$season" "$episode")" || true
}

echo "Warming up (30s) ..." >&2
sleep 30

echo "Running sustained load for ${DURATION}s (page traffic + webhooks + real Celery beat schedule) ..." >&2
START_TS=$(date +%s)
NEXT_SAMPLE=0
while :; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TS))
  [ "$ELAPSED" -ge "$DURATION" ] && break

  probe_route "$ELAPSED" home "$BASE_URL/" &
  probe_route "$ELAPSED" history "$BASE_URL/history?media_type=tv&media_id=1668&source=tmdb" &
  fire_jellyfin_webhook &
  wait

  if [ "$ELAPSED" -ge "$NEXT_SAMPLE" ]; then
    sample_metrics "$ELAPSED"
    NEXT_SAMPLE=$((ELAPSED + SAMPLE_INTERVAL))
  fi

  sleep 2
done

echo "Final sample ..." >&2
sample_metrics "$DURATION"

OOM_KILLED=$(docker inspect --format '{{.State.OOMKilled}}' "$(compose ps -q floppy)" 2>/dev/null || echo "unknown")
RUNNING=$(docker inspect --format '{{.State.Running}}' "$(compose ps -q floppy)" 2>/dev/null || echo "unknown")

python3 - "$SAMPLES_CSV" "$PROBES_CSV" "$OUTPUT_DIR/summary.json" "$OOM_KILLED" "$RUNNING" <<'PY'
import csv
import json
import sys

samples_path, probes_path, summary_path, oom_killed, running = sys.argv[1:6]

samples = list(csv.DictReader(open(samples_path, newline="", encoding="utf-8")))
for row in samples:
    for key in ("elapsed_s", "cgroup_bytes", "redis_used_memory", "redis_maxmemory", "io_read_bytes", "io_write_bytes"):
        row[key] = int(row[key] or 0)

probes = list(csv.DictReader(open(probes_path, newline="", encoding="utf-8")))
for row in probes:
    row["elapsed_s"] = int(row["elapsed_s"])
    row["latency_ms"] = int(row["latency_ms"])

timeouts = [p for p in probes if p["status"] in ("000", "500", "502", "503", "504")]
redis_peak = max((s["redis_used_memory"] for s in samples), default=0)
redis_ceiling = next((s["redis_maxmemory"] for s in samples if s["redis_maxmemory"]), 0)
mem_peak = max((s["cgroup_bytes"] for s in samples), default=0)
io_write_total = (samples[-1]["io_write_bytes"] - samples[0]["io_write_bytes"]) if len(samples) >= 2 else 0

summary = {
    "oom_killed": oom_killed,
    "container_running_at_end": running,
    "http_probe_failures": len(timeouts),
    "http_probe_total": len(probes),
    "redis_used_memory_peak_bytes": redis_peak,
    "redis_maxmemory_bytes": redis_ceiling,
    "redis_within_ceiling": redis_peak <= redis_ceiling if redis_ceiling else None,
    "container_memory_peak_bytes": mem_peak,
    "container_memory_limit_bytes": 2 * 1024**3,
    "io_write_bytes_over_run": io_write_total,
}
json.dump(summary, open(summary_path, "w", encoding="utf-8"), indent=2)
print(json.dumps(summary, indent=2))
PY

echo "Reports written to $OUTPUT_DIR"
