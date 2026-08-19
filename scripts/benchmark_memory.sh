#!/usr/bin/env bash
# Compare the idle memory of two Floppy images in disposable Compose projects.
#
# Usage:
#   scripts/benchmark_memory.sh --baseline-image floppy:before --candidate-image floppy:after
#
# The script never uses the application's compose project, volumes, or host ports.
set -euo pipefail

cd "$(dirname "$0")/.."

BASELINE_IMAGE=""
CANDIDATE_IMAGE=""
RUNS="${MEMORY_BENCHMARK_RUNS:-3}"
SAMPLES="${MEMORY_BENCHMARK_SAMPLES:-5}"
WARMUP_SECONDS="${MEMORY_BENCHMARK_WARMUP_SECONDS:-90}"
SAMPLE_INTERVAL_SECONDS="${MEMORY_BENCHMARK_SAMPLE_INTERVAL_SECONDS:-10}"
OUTPUT_DIR="${MEMORY_BENCHMARK_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/floppy-memory.XXXXXX")}" 

usage() {
  awk 'NR > 1 && /^set -euo/ { exit } NR > 1' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --baseline-image) BASELINE_IMAGE="${2:?missing baseline image}"; shift 2 ;;
    --candidate-image) CANDIDATE_IMAGE="${2:?missing candidate image}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?missing output directory}"; shift 2 ;;
    --runs) RUNS="${2:?missing run count}"; shift 2 ;;
    --samples) SAMPLES="${2:?missing sample count}"; shift 2 ;;
    --warmup-seconds) WARMUP_SECONDS="${2:?missing warmup seconds}"; shift 2 ;;
    --sample-interval-seconds) SAMPLE_INTERVAL_SECONDS="${2:?missing interval}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$BASELINE_IMAGE" ] || [ -z "$CANDIDATE_IMAGE" ]; then
  echo "Both --baseline-image and --candidate-image are required." >&2
  usage >&2
  exit 2
fi

for value in "$RUNS" "$SAMPLES" "$WARMUP_SECONDS" "$SAMPLE_INTERVAL_SECONDS"; do
  case "$value" in
    ''|*[!0-9]*|0) echo "Run, sample, warmup, and interval values must be positive integers." >&2; exit 2 ;;
  esac
done

mkdir -p "$OUTPUT_DIR/processes"
SUMMARY_CSV="$OUTPUT_DIR/summary.csv"
printf '%s\n' 'image,label,run,sample,cgroup_bytes,pss_kib,rss_kib,redis_used_memory,redis_maxmemory,process_count' >"$SUMMARY_CSV"

cleanup_project() {
  docker compose -p "$1" -f docker-compose.memory-benchmark.yml down --volumes --remove-orphans >/dev/null 2>&1 || true
}

sample_floppy() {
  local project="$1" label="$2" image="$3" run="$4" sample="$5"
  local cgroup redis process_file totals redis_used redis_max pss rss count
  cgroup=$(docker compose -p "$project" -f docker-compose.memory-benchmark.yml exec -T floppy sh -c 'cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes')
  redis=$(docker compose -p "$project" -f docker-compose.memory-benchmark.yml exec -T redis redis-cli --raw INFO memory | awk -F: '
    /^used_memory:/ { used = $2 }
    /^maxmemory:/ { max = $2 }
    END { gsub("\\r", "", used); gsub("\\r", "", max); print used "," max }
  ')
  IFS=, read -r redis_used redis_max <<<"$redis"
  process_file="$OUTPUT_DIR/processes/${label}-run${run}-sample${sample}.csv"
  {
    printf '%s\n' 'pid,name,pss_kib,rss_kib'
    docker compose -p "$project" -f docker-compose.memory-benchmark.yml exec -T --user abc floppy sh -c '
      for rollup in /proc/[0-9]*/smaps_rollup; do
        [ -r "$rollup" ] || continue
        pid=${rollup#/proc/}; pid=${pid%/smaps_rollup}
        name=$(tr "\\000" " " <"/proc/$pid/cmdline" | tr "," " ")
        pss=$(awk "/^Pss:/ { sum += \$2 } END { print sum + 0 }" "$rollup" 2>/dev/null) || continue
        rss=$(awk "/^Rss:/ { sum += \$2 } END { print sum + 0 }" "$rollup" 2>/dev/null) || continue
        printf "%s,%s,%s,%s\\n" "$pid" "$name" "$pss" "$rss"
      done
    ' >>"$process_file"
  }
  totals=$(awk -F, 'NR > 1 { pss += $3; rss += $4; count += 1 } END { printf "%d,%d,%d", pss, rss, count }' "$process_file")
  IFS=, read -r pss rss count <<<"$totals"
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$image" "$label" "$run" "$sample" "$cgroup" "$pss" "$rss" "$redis_used" "$redis_max" "$count" >>"$SUMMARY_CSV"
}

run_image() {
  local label="$1" image="$2" run project sample
  for run in $(seq 1 "$RUNS"); do
    project="floppy-memory-${label}-${run}-$$"
    trap 'cleanup_project "$project"' EXIT INT TERM
    echo "Starting $label run $run/$RUNS ($image)"
    FLOPPY_BENCHMARK_IMAGE="$image" docker compose --progress quiet -p "$project" -f docker-compose.memory-benchmark.yml up -d --wait --wait-timeout 180
    sleep "$WARMUP_SECONDS"
    for sample in $(seq 1 "$SAMPLES"); do
      sample_floppy "$project" "$label" "$image" "$run" "$sample"
      [ "$sample" = "$SAMPLES" ] || sleep "$SAMPLE_INTERVAL_SECONDS"
    done
    cleanup_project "$project"
    trap - EXIT INT TERM
  done
}

run_image baseline "$BASELINE_IMAGE"
run_image candidate "$CANDIDATE_IMAGE"

python3 - "$SUMMARY_CSV" "$OUTPUT_DIR/summary.json" <<'PY'
import csv
import json
import statistics
import sys

rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
for row in rows:
    for key in (
        "run", "sample", "cgroup_bytes", "pss_kib", "rss_kib",
        "redis_used_memory", "redis_maxmemory", "process_count",
    ):
        row[key] = int(row[key])

by_label = {}
for label in ("baseline", "candidate"):
    label_rows = [row for row in rows if row["label"] == label]
    medians = {
        key: statistics.median(row[key] for row in label_rows)
        for key in ("cgroup_bytes", "pss_kib", "rss_kib", "redis_used_memory", "process_count")
    }
    by_label[label] = {"samples": len(label_rows), "median": medians}

baseline = by_label["baseline"]["median"]["cgroup_bytes"]
candidate = by_label["candidate"]["median"]["cgroup_bytes"]
delta = (candidate - baseline) / baseline * 100 if baseline else None
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump(
        {"runs": rows, "by_label": by_label, "cgroup_delta_percent": delta},
        output,
        indent=2,
    )

print(f"baseline median cgroup: {baseline / 1024 / 1024:.1f} MiB")
print(f"candidate median cgroup: {candidate / 1024 / 1024:.1f} MiB")
print(f"delta: {delta:+.1f}%")
PY

echo "Reports written to $OUTPUT_DIR"
