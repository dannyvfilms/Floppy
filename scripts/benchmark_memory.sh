#!/usr/bin/env bash
# Compare the idle memory of two Floppy images in disposable Compose projects.
#
# Usage:
#   scripts/benchmark_memory.sh --baseline-image floppy:before --candidate-image floppy:after
# Optional: --workload-script /absolute/path/to/workload.sh. The script receives
# FLOPPY_BENCHMARK_PROJECT and FLOPPY_BENCHMARK_IMAGE, logs durations/row counts,
# and must fail if work is incomplete. Default container limit is 1,000,000,000
# bytes with no swap; FLOPPY_BENCHMARK_MEMORY_LIMIT can override it for diagnosis.
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
STARTUP_TIMEOUT_SECONDS="${MEMORY_BENCHMARK_STARTUP_TIMEOUT_SECONDS:-600}"
WORKLOAD_SCRIPT=""
OUTPUT_DIR="${MEMORY_BENCHMARK_OUTPUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/floppy-memory.XXXXXX")}" 

usage() {
  awk 'NR > 1 && /^set -euo/ { exit } NR > 1' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --workload-script) WORKLOAD_SCRIPT="${2:?missing workload script}"; shift 2 ;;
    --baseline-image) BASELINE_IMAGE="${2:?missing baseline image}"; shift 2 ;;
    --candidate-image) CANDIDATE_IMAGE="${2:?missing candidate image}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?missing output directory}"; shift 2 ;;
    --runs) RUNS="${2:?missing run count}"; shift 2 ;;
    --samples) SAMPLES="${2:?missing sample count}"; shift 2 ;;
    --warmup-seconds) WARMUP_SECONDS="${2:?missing warmup seconds}"; shift 2 ;;
    --sample-interval-seconds) SAMPLE_INTERVAL_SECONDS="${2:?missing interval}"; shift 2 ;;
    --startup-timeout-seconds) STARTUP_TIMEOUT_SECONDS="${2:?missing timeout}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$BASELINE_IMAGE" ] || [ -z "$CANDIDATE_IMAGE" ]; then
  echo "Both --baseline-image and --candidate-image are required." >&2
  usage >&2
  exit 2
fi

for value in "$RUNS" "$SAMPLES" "$WARMUP_SECONDS" "$SAMPLE_INTERVAL_SECONDS" "$STARTUP_TIMEOUT_SECONDS"; do
  case "$value" in
    ''|*[!0-9]*|0) echo "Run, sample, warmup, and interval values must be positive integers." >&2; exit 2 ;;
  esac
done

if [ -n "$WORKLOAD_SCRIPT" ] && [ ! -f "$WORKLOAD_SCRIPT" ]; then
  echo "Workload script not found: $WORKLOAD_SCRIPT" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR/processes" "$OUTPUT_DIR/cgroups"
SUMMARY_CSV="$OUTPUT_DIR/summary.csv"
FAILURES_CSV="$OUTPUT_DIR/failures.csv"
printf '%s\n' 'label,run,phase' >"$FAILURES_CSV"
printf '%s\n' 'image,label,run,sample,cgroup_bytes,pss_kib,rss_kib,private_kib,cgroup_minus_pss_bytes,anon_bytes,file_bytes,kernel_bytes,slab_bytes,redis_used_memory,redis_maxmemory,process_count' >"$SUMMARY_CSV"

cleanup_project() {
  docker compose -p "$1" -f docker-compose.memory-benchmark.yml down --volumes --remove-orphans >/dev/null 2>&1 || true
}

sample_floppy() {
  local project="$1" label="$2" image="$3" run="$4" sample="$5"
  local cgroup_sample redis process_file redis_used redis_max pss rss private count remainder anon file kernel slab
  cgroup_sample="$OUTPUT_DIR/cgroups/${label}-run${run}-sample${sample}.json"
  docker compose -p "$project" -f docker-compose.memory-benchmark.yml exec -T --user root floppy sh -c '
    cgroup_root=/sys/fs/cgroup
    if [ -r "$cgroup_root/memory.current" ]; then
      export FLOPPY_CGROUP_CURRENT_BEFORE_SAMPLER="$(cat "$cgroup_root/memory.current")"
    else
      export FLOPPY_CGROUP_CURRENT_BEFORE_SAMPLER="$(cat "$cgroup_root/memory/memory.usage_in_bytes")"
    fi
    exec python -
  ' <scripts/container_memory_sample.py >"$cgroup_sample" || return 1
  redis=$(docker compose -p "$project" -f docker-compose.memory-benchmark.yml exec -T redis redis-cli --raw INFO memory | awk -F: '
    /^used_memory:/ { used = $2 }
    /^maxmemory:/ { max = $2 }
    END { gsub("\\r", "", used); gsub("\\r", "", max); print used "," max }
  ') || return 1
  IFS=, read -r redis_used redis_max <<<"$redis"
  process_file="$OUTPUT_DIR/processes/${label}-run${run}-sample${sample}.csv"
  IFS=, read -r cgroup pss rss private count remainder anon file kernel slab < <(
    python3 - "$cgroup_sample" "$process_file" <<'PY'
import csv
import json
import sys

sample = json.load(open(sys.argv[1], encoding="utf-8"))
with open(sys.argv[2], "w", newline="", encoding="utf-8") as output:
    fields = ("pid", "ppid", "role", "name", "argv0", "pss_kib", "rss_kib", "private_kib")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(sample["processes"])
stat = sample["memory_stat"]
reconciliation = sample["reconciliation"]
print(",".join(str(value) for value in (
    sample["current_bytes"],
    reconciliation["process_pss_bytes"] // 1024,
    sum(process["rss_kib"] for process in sample["processes"]),
    reconciliation["process_private_bytes"] // 1024,
    len(sample["processes"]),
    reconciliation["cgroup_minus_process_pss_bytes"],
    stat.get("anon", 0),
    stat.get("file", 0),
    stat.get("kernel", 0),
    stat.get("slab", 0),
)))
PY
  )
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' "$image" "$label" "$run" "$sample" "$cgroup" "$pss" "$rss" "$private" "$remainder" "$anon" "$file" "$kernel" "$slab" "$redis_used" "$redis_max" "$count" >>"$SUMMARY_CSV"
}

run_image() {
  local label="$1" image="$2" run project sample ready
  for run in $(seq 1 "$RUNS"); do
    project="floppy-memory-${label}-${run}-$$"
    trap 'cleanup_project "$project"' EXIT INT TERM
    echo "Starting $label run $run/$RUNS ($image)"
    ready=true
    if ! FLOPPY_BENCHMARK_IMAGE="$image" docker compose --progress quiet -p "$project" -f docker-compose.memory-benchmark.yml up -d --wait --wait-timeout "$STARTUP_TIMEOUT_SECONDS"; then
      printf '%s,%s,startup\n' "$label" "$run" >>"$FAILURES_CSV"
      ready=false
    fi
    if [ "$ready" = true ]; then
      sample_floppy "$project" "$label" "$image" "$run" startup || printf '%s,%s,sample-startup\n' "$label" "$run" >>"$FAILURES_CSV"
      sleep "$WARMUP_SECONDS"
      sample_floppy "$project" "$label" "$image" "$run" idle || printf '%s,%s,sample-idle\n' "$label" "$run" >>"$FAILURES_CSV"
    fi
    if [ "$ready" = true ] && [ -n "$WORKLOAD_SCRIPT" ]; then
      # The workload owns fixtures, authenticated traffic and completion checks.
      # Exit nonzero on lost/failed work; stdout should include durations/row counts.
      if ! FLOPPY_BENCHMARK_PROJECT="$project" FLOPPY_BENCHMARK_IMAGE="$image" \
        bash "$WORKLOAD_SCRIPT" >"$OUTPUT_DIR/${label}-run${run}-workload.log" 2>&1; then
        printf '%s,%s,workload\n' "$label" "$run" >>"$FAILURES_CSV"
      fi
      sample_floppy "$project" "$label" "$image" "$run" workload || printf '%s,%s,sample-workload\n' "$label" "$run" >>"$FAILURES_CSV"
    fi
    if [ "$ready" = true ]; then
      for sample in $(seq 1 "$SAMPLES"); do
        sample_floppy "$project" "$label" "$image" "$run" "$sample" || printf '%s,%s,sample\n' "$label" "$run" >>"$FAILURES_CSV"
        [ "$sample" = "$SAMPLES" ] || sleep "$SAMPLE_INTERVAL_SECONDS"
      done
    fi
    docker compose -p "$project" -f docker-compose.memory-benchmark.yml logs --no-color --tail 200 >"$OUTPUT_DIR/${label}-run${run}-container.log" 2>&1 || true
    docker inspect "$(docker compose -p "$project" -f docker-compose.memory-benchmark.yml ps -aq floppy)" >"$OUTPUT_DIR/${label}-run${run}-state.json" 2>/dev/null || true
    cleanup_project "$project"
    trap - EXIT INT TERM
  done
}

run_image baseline "$BASELINE_IMAGE"
run_image candidate "$CANDIDATE_IMAGE"

python3 - "$SUMMARY_CSV" "$OUTPUT_DIR/summary.json" <<'PY'
import csv
import json
from pathlib import Path
import statistics
import sys

rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
for row in rows:
    for key in (
        "run", "cgroup_bytes", "pss_kib", "rss_kib", "private_kib",
        "cgroup_minus_pss_bytes", "anon_bytes", "file_bytes", "kernel_bytes", "slab_bytes",
        "redis_used_memory", "redis_maxmemory", "process_count",
    ):
        row[key] = int(row[key])

by_label = {}
for label in ("baseline", "candidate"):
    label_rows = [
        row for row in rows if row["label"] == label and row["sample"].isdigit()
    ]
    medians = {
        key: statistics.median(row[key] for row in label_rows) if label_rows else 0
        for key in (
            "cgroup_bytes", "pss_kib", "rss_kib", "private_kib",
            "cgroup_minus_pss_bytes", "anon_bytes", "file_bytes", "kernel_bytes",
            "slab_bytes", "redis_used_memory", "process_count",
        )
    }
    by_label[label] = {"samples": len(label_rows), "median": medians}

baseline = by_label["baseline"]["median"]["cgroup_bytes"]
candidate = by_label["candidate"]["median"]["cgroup_bytes"]
delta = (candidate - baseline) / baseline * 100 if baseline else None
cgroup_samples = {
    path.stem: json.loads(path.read_text())
    for path in (Path(sys.argv[1]).parent / "cgroups").glob("*.json") if path.stat().st_size
}
candidate_samples = [value for key, value in cgroup_samples.items() if key.startswith("candidate-")]
role_medians = {}
for label in ("baseline", "candidate"):
    samples = [
        value
        for key, value in cgroup_samples.items()
        if key.startswith(f"{label}-") and key.rsplit("-sample", 1)[-1].isdigit()
    ]
    roles = {}
    for sample in samples:
        for role, values in sample["roles"].items():
            roles.setdefault(role, []).append(values)
    role_medians[label] = {
        role: {
            key: statistics.median(values[key] for values in measurements)
            for key in ("process_count", "pss_kib", "rss_kib", "private_kib")
        }
        for role, measurements in roles.items()
    }
failures = list(csv.DictReader(open(Path(sys.argv[1]).parent / "failures.csv")))
passed = not any(row["label"] == "candidate" for row in failures) and bool(candidate_samples) and all(
    value["peak_bytes"] is not None
    and value["peak_bytes"] < 1_000_000_000
    and value["oom"] == 0
    and value["oom_kill"] == 0
    for value in candidate_samples
)
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump(
        {"runs": rows, "by_label": by_label, "process_role_medians": role_medians,
         "cgroup_delta_percent": delta,
         "failures": failures, "cgroup_samples": cgroup_samples, "candidate_under_1gb_without_oom": passed},
        output,
        indent=2,
    )

print(f"baseline median cgroup: {baseline / 1024 / 1024:.1f} MiB")
print(f"candidate median cgroup: {candidate / 1024 / 1024:.1f} MiB")
print(f"delta: {delta:+.1f}%" if delta is not None else "delta: unavailable")
print(f"candidate below 1GB with no OOM events: {passed}")
if not passed:
    sys.exit(1)
PY

echo "Reports written to $OUTPUT_DIR"
