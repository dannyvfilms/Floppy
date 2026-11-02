#!/usr/bin/env bash
# Validate issue #521's fix under the exact reported constraint: 2 vCPU,
# 2 GB RAM, no swap, Postgres + Redis co-located, sustained page traffic
# plus background webhook/reconcile work.
#
# Usage:
#   scripts/constrained_benchmark.sh [--duration-seconds 600] [--image floppy:issue521-validation]
#   scripts/constrained_benchmark.sh --profile minimal  # 1 CPU / 1 GiB, no swap
#   scripts/constrained_benchmark.sh --database sqlite
#
# The script never touches the application's compose project or volumes.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="floppy:issue521-validation"
DURATION="${CONSTRAINED_BENCHMARK_DURATION:-600}"
SAMPLE_INTERVAL="${CONSTRAINED_BENCHMARK_SAMPLE_INTERVAL:-15}"
OUTPUT_DIR="${CONSTRAINED_BENCHMARK_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/floppy-constrained.XXXXXX")}"
PROJECT="floppy-constrained-$$"
PROFILE="constrained"
DATABASE="postgres"
COMPOSE_FILES=(-f docker-compose.constrained-benchmark.yml)

while [ "$#" -gt 0 ]; do
  case "$1" in
    --duration-seconds) DURATION="${2:?}"; shift 2 ;;
    --image) IMAGE="${2:?}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?}"; shift 2 ;;
    --profile) PROFILE="${2:?}"; shift 2 ;;
    --database) DATABASE="${2:?}"; shift 2 ;;
    --help|-h) echo "See header comment for usage."; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$PROFILE" in
  minimal) export FLOPPY_BENCHMARK_MEMORY=1g FLOPPY_BENCHMARK_CPUS=1.0 ;;
  constrained) export FLOPPY_BENCHMARK_MEMORY=2g FLOPPY_BENCHMARK_CPUS=2.0 ;;
  *) echo "Profile must be minimal or constrained" >&2; exit 2 ;;
esac

case "$DATABASE" in
  postgres) ;;
  sqlite) COMPOSE_FILES+=(-f docker-compose.constrained-benchmark.sqlite.yml) ;;
  *) echo "Database must be sqlite or postgres" >&2; exit 2 ;;
esac

mkdir -p "$OUTPUT_DIR"
SAMPLES_CSV="$OUTPUT_DIR/samples.csv"
PROBES_CSV="$OUTPUT_DIR/http_probes.csv"
RESOURCE_JSONL="$OUTPUT_DIR/resources.jsonl"
: >"$RESOURCE_JSONL"
printf '%s\n' 'elapsed_s,cgroup_bytes,redis_used_memory,redis_maxmemory,io_read_bytes,io_write_bytes' >"$SAMPLES_CSV"
printf '%s\n' 'elapsed_s,route,status,latency_ms,curl_exit' >"$PROBES_CSV"

compose() {
  FLOPPY_BENCHMARK_IMAGE="$IMAGE" docker compose -p "$PROJECT" "${COMPOSE_FILES[@]}" "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "Starting constrained stack (image=$IMAGE must already exist) ..." >&2
compose up -d --wait --wait-timeout 180

echo "Running migrations ..." >&2
compose exec -T floppy python manage.py migrate --noinput >/dev/null

echo "Creating benchmark user ..." >&2
IDENTITY=$(compose exec -T floppy python manage.py shell -c '
from importlib import import_module
from django.conf import settings
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from users.models import User
user, _ = User.objects.get_or_create(username="constrained-benchmark", defaults={"is_active": True})
session = import_module(settings.SESSION_ENGINE).SessionStore()
session[SESSION_KEY] = str(user.pk)
session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
session[HASH_SESSION_KEY] = user.get_session_auth_hash()
session.save()
print("BENCHMARK_IDENTITY=" + str(user.token) + "," + settings.SESSION_COOKIE_NAME + "=" + session.session_key)
' | tr -d '\r')
IDENTITY=$(printf '%s\n' "$IDENTITY" | awk '/^BENCHMARK_IDENTITY=/ { sub(/^BENCHMARK_IDENTITY=/, ""); print }')
IFS=, read -r TOKEN SESSION_COOKIE <<<"$IDENTITY"

if [ -z "$TOKEN" ] || [ -z "$SESSION_COOKIE" ]; then
  echo "Failed to obtain disposable benchmark identity" >&2
  exit 1
fi

BASE_URL="http://localhost:18000"
JELLYFIN_URL="$BASE_URL/integrations/jellyfin/webhook/$TOKEN"

# Only an allowlist of effective settings: never write URLs, credentials or the
# disposable session/token to diagnostic artifacts.
compose exec -T floppy python manage.py shell -c '
import json
from django.conf import settings
from django.db import connection
from config.runtime_profile import sizing_report
names = ("CELERY_WORKER_CONCURRENCY", "CELERY_WORKER_PREFETCH_MULTIPLIER",
         "CELERY_WORKER_MAX_TASKS_PER_CHILD", "CELERY_WORKER_MAX_MEMORY_PER_CHILD",
         "STATISTICS_SYNC_TASK_BUDGET_SECONDS", "DB_POOL_ENABLED", "DB_POOL_MAX",
         "DB_POOL_TIMEOUT", "SQLITE_BUSY_TIMEOUT_SECONDS")
report = sizing_report()
report["settings"] = {name: getattr(settings, name, None) for name in names}
report["database_vendor"] = "sqlite" if settings.USING_SQLITE_DATABASE else "postgresql"
if connection.vendor == "sqlite":
    import sqlite3
    with connection.cursor() as cursor:
        report["sqlite"] = {"version": sqlite3.sqlite_version}
        for pragma in ("journal_mode", "synchronous", "busy_timeout"):
            cursor.execute("PRAGMA " + pragma)
            report["sqlite"][pragma] = cursor.fetchone()[0]
report["cache_shared_with_broker"] = settings.REDIS_CACHE_URL == settings.CELERY_BROKER_URL
print("BENCHMARK_SETTINGS=" + json.dumps(report))
' | awk '/^BENCHMARK_SETTINGS=/ { sub(/^BENCHMARK_SETTINGS=/, ""); print }' >"$OUTPUT_DIR/effective_settings.json"

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
  compose exec -T floppy python - "$elapsed" <<'PY' >>"$RESOURCE_JSONL"
import json
import os
import time
from pathlib import Path
import sys
import redis

def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None

root = Path("/sys/fs/cgroup")
report = {"elapsed_s": int(sys.argv[1])}
report["cgroup"] = {name: read(root / name) for name in (
    "cpu.max", "cpu.stat", "cpu.pressure", "memory.max", "memory.events",
    "memory.pressure", "io.pressure", "pids.current", "pids.max",
)}
# /proc is the container PID namespace. Counts exclude command arguments.
processes = {}
for directory in Path("/proc").iterdir():
    if directory.name.isdigit():
        name = read(directory / "comm")
        if name:
            processes[name] = processes.get(name, 0) + 1
report["process_counts"] = processes
for label, variable in (("cache", "REDIS_CACHE_URL"), ("broker", "CELERY_BROKER_URL")):
    client = redis.Redis.from_url(
        os.environ.get(variable) or os.environ.get("REDIS_URL", "redis://redis:6379"),
        socket_timeout=2, socket_connect_timeout=2,
    )
    try:
        started = time.monotonic()
        client.ping()
        ping_ms = (time.monotonic() - started) * 1000
        info = client.info()
        fields = ("used_memory", "used_memory_peak", "used_memory_rss", "maxmemory", "evicted_keys",
                  "keyspace_hits", "keyspace_misses", "blocked_clients",
                  "connected_clients", "instantaneous_ops_per_sec", "total_commands_processed",
                  "used_cpu_sys", "used_cpu_user", "aof_delayed_fsync",
                  "aof_pending_bio_fsync", "aof_rewrite_in_progress",
                  "aof_enabled", "aof_last_write_status", "aof_last_bgrewrite_status",
                  "rdb_bgsave_in_progress", "rdb_last_bgsave_status")
        report[label] = {name: info.get(name) for name in fields}
        report[label]["ping_ms"] = round(ping_ms, 3)
        if label == "broker":
            prefix = os.environ.get("REDIS_PREFIX", "")
            pipe = client.pipeline(transaction=False)
            for queue in ("celery", "interactive", "discover"):
                for priority in range(10):
                    pipe.llen(prefix + queue + (f":{priority}" if priority else ""))
            counts = pipe.execute()
            report[label]["queue_messages"] = {
                queue: sum(counts[index * 10:(index + 1) * 10])
                for index, queue in enumerate(("celery", "interactive", "discover"))
            }
    except redis.RedisError as error:
        report[label] = {"error_type": type(error).__name__}
    finally:
        client.close()
print(json.dumps(report))
PY
}

probe_route() {
  local elapsed="$1" label="$2" url="$3" result status seconds latency curl_exit=0
  result=$(curl -s -o /dev/null -w '%{http_code},%{time_total}' -m 10 \
    --cookie "$SESSION_COOKIE" "$url") || curl_exit=$?
  IFS=, read -r status seconds <<<"$result"
  latency=$(awk -v seconds="${seconds:-0}" 'BEGIN { printf "%.3f", seconds * 1000 }')
  printf '%s,%s,%s,%s,%s\n' "$elapsed" "$label" "${status:-000}" "$latency" "$curl_exit" >>"$PROBES_CSV"
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
  probe_route "$ELAPSED" active_playback "$BASE_URL/api/active-playback/" &
  probe_route "$ELAPSED" library "$BASE_URL/medialist/tv" &
  probe_route "$ELAPSED" settings "$BASE_URL/settings/account" &
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

python3 - "$SAMPLES_CSV" "$PROBES_CSV" "$OUTPUT_DIR/summary.json" "$OOM_KILLED" "$RUNNING" "$PROFILE" <<'PY'
import csv
import json
import sys

samples_path, probes_path, summary_path, oom_killed, running, profile = sys.argv[1:7]

samples = list(csv.DictReader(open(samples_path, newline="", encoding="utf-8")))
for row in samples:
    for key in ("elapsed_s", "cgroup_bytes", "redis_used_memory", "redis_maxmemory", "io_read_bytes", "io_write_bytes"):
        row[key] = int(row[key] or 0)

probes = list(csv.DictReader(open(probes_path, newline="", encoding="utf-8")))
for row in probes:
    row["elapsed_s"] = int(row["elapsed_s"])
    row["latency_ms"] = float(row["latency_ms"])
    row["curl_exit"] = int(row["curl_exit"])

timeouts = [p for p in probes if p["curl_exit"] or p["status"] != "200"]
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
    "runtime_profile_requested": profile,
    "container_memory_limit_bytes": (1 if profile == "minimal" else 2) * 1024**3,
    "io_write_bytes_over_run": io_write_total,
    "latency_source": "curl time_total (milliseconds; excludes Python process startup)",
    "resource_samples": "resources.jsonl",
    "effective_settings": "effective_settings.json",
    "routes": {},
}
def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)

for route in sorted({p["route"] for p in probes}):
    rows = [p for p in probes if p["route"] == route]
    successful = [p["latency_ms"] for p in rows if not p["curl_exit"] and p["status"] == "200"]
    errors = len(rows) - len(successful)
    summary["routes"][route] = {
        "requests": len(rows), "errors": errors,
        "error_rate": errors / len(rows),
        "p50_ms": percentile(successful, 0.5),
        "p95_ms": percentile(successful, 0.95),
        "p99_ms": percentile(successful, 0.99),
    }
json.dump(summary, open(summary_path, "w", encoding="utf-8"), indent=2)
print(json.dumps(summary, indent=2))
PY

echo "Reports written to $OUTPUT_DIR"
