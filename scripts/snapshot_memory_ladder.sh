#!/usr/bin/env bash
# Answer what memory limit the database snapshot actually REQUIRES.
#
# Production showed the snapshot taking the cgroup from ~400 MB to ~2.14 GB of
# filesystem cache while process RSS moved 0.2 MB, with a historical peak near
# 4.84 GB. That is reclaimable cache, not a Python heap -- but "reclaimable" is
# not an excuse, because a 1 GB cgroup limit is still a limit. The useful
# question is therefore not "how much cache does Linux take when given 32 GiB"
# but "does the backup still complete, and how fast, inside 512 MiB".
#
# So this runs the real `write_database_snapshot` task against a real database
# at each rung of a memory ladder, one fresh container per rung, and reports
# success/failure, duration, OOM kills, memory.peak, the anon/file split, I/O
# and post-run settling.
#
# Usage:
#   scripts/snapshot_memory_ladder.sh --image floppy:phase7 \
#     --database /path/to/db.sqlite3 [--limits 512m,768m,1g,1.5g,2g]
#
# `--limits 0` runs a single unconstrained rung, which is how to record the
# natural peak before constraining anything.
#
# `--no-fadvise` additionally repeats the last rung with os.posix_fadvise
# hidden, confirming the snapshot still publishes when the hint is unavailable.
#
# The database is COPIED into a disposable volume; the file given is never
# opened by the container. Each rung gets its own volume, so no rung inherits
# another's page cache.
#
# DISK: each rung needs room for the database AND a full second copy of it, so
# budget at least 3x the database size in Docker's storage. On Docker Desktop
# that is the VM disk, not the host's. A rung that cannot fit scores "no_disk"
# and is skipped rather than being reported as a memory failure.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE=""
DATABASE=""
LIMITS="${FLOPPY_SNAPSHOT_LIMITS:-512m,768m,1g,1.5g,2g}"
READY_TIMEOUT="${FLOPPY_SNAPSHOT_READY_TIMEOUT:-900}"
SNAPSHOT_TIMEOUT="${FLOPPY_SNAPSHOT_TIMEOUT:-1800}"
OUTPUT_DIR="${FLOPPY_SNAPSHOT_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/floppy-snapshot-ladder.XXXXXX")}"
NO_FADVISE_RUN=0
# Settling deltas after the snapshot, in seconds: +30 s, +60 s, +5 min. Only
# shortened for smoke-testing the harness itself; the defaults are what the
# validation plan calls for.
SETTLE_1="${FLOPPY_SNAPSHOT_SETTLE_1:-30}"
SETTLE_2="${FLOPPY_SNAPSHOT_SETTLE_2:-30}"
SETTLE_3="${FLOPPY_SNAPSHOT_SETTLE_3:-240}"

usage() { awk 'NR > 1 && /^set -euo/ { exit } NR > 1' "$0"; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --image) IMAGE="${2:?missing image}"; shift 2 ;;
    --database) DATABASE="${2:?missing database}"; shift 2 ;;
    --limits) LIMITS="${2:?missing limits}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?missing output directory}"; shift 2 ;;
    --ready-timeout) READY_TIMEOUT="${2:?missing timeout}"; shift 2 ;;
    --snapshot-timeout) SNAPSHOT_TIMEOUT="${2:?missing timeout}"; shift 2 ;;
    --no-fadvise) NO_FADVISE_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$IMAGE" ] || { echo "--image is required." >&2; exit 2; }
[ -f "$DATABASE" ] || { echo "--database must be an existing SQLite file." >&2; exit 2; }

# GNU coreutils `timeout` is absent on macOS, where this harness is often
# driven from. Without the guard the trigger fails instantly and every rung
# scores "failed" for a reason that has nothing to do with memory.
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(timeout --kill-after=30s "$SNAPSHOT_TIMEOUT")
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(gtimeout --kill-after=30s "$SNAPSHOT_TIMEOUT")
else
  echo "note: no timeout(1) available; a wedged snapshot will not be cut off." >&2
  TIMEOUT_CMD=()
fi

DATABASE_BYTES="$(wc -c <"$DATABASE" | tr -d ' ')"
mkdir -p "$OUTPUT_DIR"
RESULTS_CSV="$OUTPUT_DIR/rungs.csv"
printf '%s\n' 'limit,fadvise,status,duration_s,oom_kills,peak_bytes,file_peak_bytes,anon_peak_bytes,file_before_bytes,file_after_bytes,file_settled_bytes,io_read_bytes,io_write_bytes,snapshot_bytes' >"$RESULTS_CSV"
echo "Output: $OUTPUT_DIR"

SUFFIX="$$"
NETWORK="floppy-snap-net-$SUFFIX"
REDIS="floppy-snap-redis-$SUFFIX"
APP=""
VOLUME=""

cleanup_rung() {
  [ -n "$APP" ] && docker rm -f "$APP" >/dev/null 2>&1 || true
  [ -n "$VOLUME" ] && docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  APP=""
  VOLUME=""
}

cleanup() {
  cleanup_rung
  docker rm -f "$REDIS" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create "$NETWORK" >/dev/null
docker run -d --name "$REDIS" --network "$NETWORK" redis:8-alpine \
  redis-server --appendonly no --save "" --maxmemory 256mb --maxmemory-policy volatile-lru >/dev/null

# Read the counters that decide whether a peak is a requirement or just cache.
# Traced from inside the container: on Docker Desktop the VM's cgroup tree is
# not reachable from the host, and `docker stats` reports neither memory.peak
# nor the anon/file split.
read_counters() {
  docker exec "$1" sh -c '
    cur=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
    peak=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo 0)
    anon=$(awk "/^anon /{print \$2}" /sys/fs/cgroup/memory.stat 2>/dev/null || echo 0)
    file=$(awk "/^file /{print \$2}" /sys/fs/cgroup/memory.stat 2>/dev/null || echo 0)
    kills=$(awk "/^oom_kill /{print \$2}" /sys/fs/cgroup/memory.events 2>/dev/null || echo 0)
    io=$(awk "{ for (i = 2; i <= NF; i++) { split(\$i, kv, \"=\"); sum[kv[1]] += kv[2] } }
         END { printf \"%d %d\", sum[\"rbytes\"], sum[\"wbytes\"] }" /sys/fs/cgroup/io.stat 2>/dev/null || echo "0 0")
    echo "${cur:-0} ${peak:-0} ${anon:-0} ${file:-0} ${kills:-0} ${io:-0 0}"
  ' 2>/dev/null || echo "0 0 0 0 0 0 0"
}

run_rung() {
  local limit="$1" fadvise="$2"
  local label="${limit}-${fadvise}"
  local rung_dir="$OUTPUT_DIR/$label"
  mkdir -p "$rung_dir"
  echo "=== rung limit=$limit fadvise=$fadvise ===" >&2

  APP="floppy-snap-app-$SUFFIX-$(echo "$label" | tr -c 'a-zA-Z0-9' '-')"
  VOLUME="floppy-snap-db-$SUFFIX-$(echo "$label" | tr -c 'a-zA-Z0-9' '-')"

  # A fresh volume per rung: new inodes, so no rung starts warm on the
  # previous rung's page cache.
  docker volume create "$VOLUME" >/dev/null
  docker run --rm -v "$VOLUME:/db" -v "$(cd "$(dirname "$DATABASE")" && pwd):/src:ro" \
    alpine:3.20 sh -c "cp /src/$(basename "$DATABASE") /db/db.sqlite3 && mkdir -p /db/backups && chown -R 1000:1000 /db" >/dev/null

  # Fail fast on disk, not ten minutes later. The snapshot needs room for a
  # whole second copy of the database, and Floppy's own pre-flight refuses the
  # backup without it -- which would otherwise score the rung "unverified" only
  # after a full boot and integrity scan. Docker Desktop's VM disk is the usual
  # culprit.
  local free_kib needed_kib
  free_kib=$(docker run --rm -v "$VOLUME:/db" alpine:3.20 sh -c "df -Pk /db | awk 'NR==2 {print \$4}'" 2>/dev/null | tr -d ' \r')
  needed_kib=$(( DATABASE_BYTES / 1024 ))
  if [ -n "$free_kib" ] && [ "$free_kib" -lt "$needed_kib" ] 2>/dev/null; then
    echo "  insufficient disk: ${free_kib} KiB free, ${needed_kib} KiB needed for the copy" >&2
    printf '%s,%s,no_disk,,,,,,,,,,,\n' "$limit" "$fadvise" >>"$RESULTS_CSV"
    cleanup_rung
    return 0
  fi

  local limit_args=()
  if [ "$limit" != "0" ]; then
    # No swap: a limit the backup can only meet by swapping is not a limit it
    # meets.
    limit_args=(--memory "$limit" --memory-swap "$limit")
  fi

  docker run -d --name "$APP" --network "$NETWORK" ${limit_args[@]+"${limit_args[@]}"} \
    -v "$VOLUME:/floppy/db" \
    -e SECRET=snapshot-ladder-only-secret \
    -e REDIS_URL="redis://$REDIS:6379" \
    -e DEBUG=False -e DEMO_ACCOUNT_ENABLED=False -e REGISTRATION=False \
    -e WEB_CONCURRENCY=1 \
    -e DB_SNAPSHOT_ENABLED=True \
    -e BACKUP_DIR=/floppy/db/backups \
    "$IMAGE" >/dev/null

  local deadline ready status
  ready=""
  deadline=$(( $(date +%s) + READY_TIMEOUT ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! docker inspect -f '{{.State.Running}}' "$APP" 2>/dev/null | grep -q true; then
      break
    fi
    case "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$APP" 2>/dev/null)" in
      healthy) ready=1; break ;;
      none)
        if docker exec "$APP" sh -c 'wget -q -O /dev/null -T 5 http://127.0.0.1:8000/accounts/login/' >/dev/null 2>&1; then
          ready=1; break
        fi
        ;;
    esac
    sleep 2
  done

  if [ -z "$ready" ]; then
    echo "  container never became ready" >&2
    docker logs "$APP" >"$rung_dir/container.log" 2>&1 || true
    printf '%s,%s,not_ready,,,,,,,,,,,\n' "$limit" "$fadvise" >>"$RESULTS_CSV"
    cleanup_rung
    return 0
  fi

  # Settle before the "before" reading, so boot cache is not counted as the
  # snapshot's.
  sleep 20

  docker exec -d "$APP" sh -c '
    while true; do
      now=$(date +%s)
      cur=$(cat /sys/fs/cgroup/memory.current 2>/dev/null)
      peak=$(cat /sys/fs/cgroup/memory.peak 2>/dev/null)
      anon=$(awk "/^anon /{print \$2}" /sys/fs/cgroup/memory.stat 2>/dev/null)
      file=$(awk "/^file /{print \$2}" /sys/fs/cgroup/memory.stat 2>/dev/null)
      kills=$(awk "/^oom_kill /{print \$2}" /sys/fs/cgroup/memory.events 2>/dev/null)
      echo "$now cur=$cur peak=$peak anon=$anon file=$file oom_kill=$kills" >>/tmp/snapshot-trace
      sleep 1
    done
  ' || echo "  warning: could not attach the cgroup tracer" >&2

  read -r _ _ anon_before file_before _ io_r_before io_w_before <<<"$(read_counters "$APP")"

  # `--no-fadvise` hides os.posix_fadvise before Django loads, so the
  # feature-detection fallback in _release_page_cache is the path under test.
  local trigger
  if [ "$fadvise" = "off" ]; then
    trigger='import os; del os.posix_fadvise; '
  else
    trigger=''
  fi

  local started ended
  started=$(date +%s)
  if ${TIMEOUT_CMD[@]+"${TIMEOUT_CMD[@]}"} docker exec -u 1000 -w /floppy "$APP" \
    python manage.py shell -c "${trigger}from app.tasks_db_backup import write_database_snapshot; print(write_database_snapshot())" \
    >"$rung_dir/snapshot.out" 2>"$rung_dir/snapshot.err"; then
    status="ok"
  else
    status="failed"
  fi
  ended=$(date +%s)
  # The task returns a dict; a zero exit with an error status is still a
  # failure, and silently scoring it "ok" is how a ladder lies.
  if [ "$status" = "ok" ] && ! grep -q "'status': 'ok'" "$rung_dir/snapshot.out" 2>/dev/null; then
    status="unverified"
  fi

  read -r _ peak anon_after file_after kills io_r_after io_w_after <<<"$(read_counters "$APP")"

  # Post-run settling: the question the production graph could not answer is
  # whether the cache is given back or ratchets.
  sleep "$SETTLE_1"
  read -r _ _ _ file_30 _ _ _ <<<"$(read_counters "$APP")"
  sleep "$SETTLE_2"
  read -r _ _ _ file_60 _ _ _ <<<"$(read_counters "$APP")"
  sleep "$SETTLE_3"
  read -r _ _ _ file_300 _ _ _ <<<"$(read_counters "$APP")"

  local snapshot_bytes
  # stat, not `cat | wc -c`: reading the 2 GB copy back would re-warm exactly
  # the cache these numbers are measuring.
  snapshot_bytes=$(docker exec "$APP" sh -c 'stat -c %s /floppy/db/backups/database/*.sqlite3 2>/dev/null | head -1' 2>/dev/null | tr -d ' \r' || echo 0)

  docker exec "$APP" sh -c 'cat /tmp/snapshot-trace 2>/dev/null' >"$rung_dir/cgroup-trace.txt" 2>/dev/null || true
  docker logs "$APP" >"$rung_dir/container.log" 2>&1 || true
  # The in-process counterpart to the cgroup trace.
  grep -E 'db_snapshot|page_cache_release' "$rung_dir/container.log" >"$rung_dir/db_snapshot.log" 2>/dev/null || true
  grep -oE 'file=[0-9]+' "$rung_dir/cgroup-trace.txt" 2>/dev/null | cut -d= -f2 | sort -n | tail -1 >"$rung_dir/file_peak" || echo 0 >"$rung_dir/file_peak"
  grep -oE 'anon=[0-9]+' "$rung_dir/cgroup-trace.txt" 2>/dev/null | cut -d= -f2 | sort -n | tail -1 >"$rung_dir/anon_peak" || echo 0 >"$rung_dir/anon_peak"

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$limit" "$fadvise" "$status" "$((ended - started))" "${kills:-0}" "${peak:-0}" \
    "$(cat "$rung_dir/file_peak" 2>/dev/null || echo 0)" \
    "$(cat "$rung_dir/anon_peak" 2>/dev/null || echo 0)" \
    "${file_before:-0}" "${file_after:-0}" "${file_300:-0}" \
    "$(( ${io_r_after:-0} - ${io_r_before:-0} ))" \
    "$(( ${io_w_after:-0} - ${io_w_before:-0} ))" \
    "${snapshot_bytes:-0}" >>"$RESULTS_CSV"

  {
    echo "limit=$limit fadvise=$fadvise status=$status"
    echo "duration_s=$((ended - started)) oom_kills=${kills:-0}"
    echo "anon_before=${anon_before:-0} anon_after=${anon_after:-0}"
    echo "file_before=${file_before:-0} file_after=${file_after:-0}"
    echo "file_plus30=${file_30:-0} file_plus60=${file_60:-0} file_plus300=${file_300:-0}"
    echo "database_bytes=$DATABASE_BYTES snapshot_bytes=${snapshot_bytes:-0}"
    echo "exit_state=$(docker inspect -f '{{.State.Status}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}' "$APP" 2>/dev/null)"
  } >"$rung_dir/result.txt"
  cat "$rung_dir/result.txt"

  cleanup_rung
}

IFS=',' read -r -a RUNGS <<<"$LIMITS"
for limit in "${RUNGS[@]}"; do
  [ -n "$limit" ] || continue
  run_rung "$limit" "on"
done

if [ "$NO_FADVISE_RUN" = "1" ]; then
  run_rung "${RUNGS[${#RUNGS[@]}-1]}" "off"
fi

echo
echo "Ladder complete. The answer is the smallest rung with status=ok and oom_kills=0."
column -s, -t <"$RESULTS_CSV" 2>/dev/null || cat "$RESULTS_CSV"
