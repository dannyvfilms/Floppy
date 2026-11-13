# Reliable constrained comparisons (BENCH-06)

This manual runner reuses the [fixture](benchmark-fixtures.md) and
[Celery](celery-benchmarks.md) workers in a separate locked Docker image.
It provides reproducible application quotas, SQLite/PostgreSQL, controlled
async load checks, process/cgroup resource samples and JSON/Markdown artifacts.
It adds no production request work and does not start the application stack.

Prerequisites: Docker with Linux containers and at least4GiB available to its
VM, Python3.12 and the locked development environment. No running app, browser,
Redis, beat, provider credentials or application database is needed.

From the repo root:

```bash
uv sync --locked
docker pull postgres:16-alpine
uv run --no-sync python scripts/benchmark_matrix.py --build --output /tmp/matrix-before
uv run --no-sync python scripts/benchmark_matrix.py --output /tmp/matrix-after --baseline /tmp/matrix-before/report.json
```

Use new output directories. Prefix with `UV_CACHE_DIR=/tmp/floppy-uv-cache`
if the normal uv cache is restricted. The first build needs network access
for pinned base images, locked dependencies and Redis's OS package. **Measurement
containers have no external network.** The resulting image ID, dependency-layer
hash and source hash are recorded; do not rebuild between identical repeats.
An image with a source label that differs from the checkout is rejected. Redis's OS package repository is not snapshot-pinned: preserve the built image with
`docker save`/`docker load` for exact cross-host reuse. A changed dependency layer
causes comparison rejection even if package version strings happen to match.

Defaults run16 serial cells per command: two quota profiles × two databases ×
two workloads × two fresh repetitions. Fixture size1000, seed1729, three cold
and three warm DB probes per workload; synthetic Celery jobs include controls,
retry and overlap. Cold clears the local application cache and closes the DB
connection; it does not evict OS/database page caches. Expect several minutes,
not a fast CI test.

```bash
# Smaller smoke matrix; the same correctness checks still apply.
uv run --no-sync python scripts/benchmark_matrix.py --build --size 20 --profiles minimal --output /tmp/matrix-smoke
# Larger input or a scoped workload.
uv run --no-sync python scripts/benchmark_matrix.py --size 10000 --workloads fixtures --output /tmp/matrix-10k
uv run --no-sync python scripts/benchmark_matrix.py --size 50000 --profiles constrained --workloads fixtures --output /tmp/matrix-50k
# Lower sampling frequency; do not compare against a different sampling policy.
uv run --no-sync python scripts/benchmark_matrix.py --sample-interval 2 --output /tmp/matrix-coarse
```

Size must be at least ten, divisible by ten. Runs/repetitions must be at least
two. Large fixtures may exceed smaller quotas; an OOM/failure is a failed
measurement, not a zero-duration sample. Build-only changes are cached by
Docker; an image is inferred from the allowlisted source hash, or selected with
`--image`. Changing the dataset does not require rebuilding the image.

## Quotas and isolation scope

| Profile | Application CPU quota | Application RAM | Swap allowance | PID cap |
|---|---:|---:|---:|---:|
| minimal | 1 CPU | 1GiB | zero extra swap |128|
| constrained | 2 CPU | 2GiB | zero extra swap |128|

These match `constrained_benchmark.sh`'s **application** quotas. The application
container includes sampler, offline Django worker, and synthetic Redis/Celery
children for the load workload. PostgreSQL has its own fixed0.5CPU/256MiB,
zero-extra-swap, PID128 budget. These are not total physical-host budgets.
Application limits and OOM status are independently read back from Docker;
cgroup metrics record effective limits, usage, pressure, IO and peak memory.
PostgreSQL process CPU/USS/PSS are outside the application samples.

Each PostgreSQL cell starts a new local server with no TCP host port or external
network. The app shares its isolated network namespace, so BENCH-02's existing
loopback-only database safety check stays intact. Each worker creates/drops its
own benchmark database. SQLite uses only the new output directory. No production
volume is mounted. Images are read-only; runtime temp/log state is tmpfs; only
the new cell output is writable. Containers and PG anonymous volumes are removed
in `finally`, including interruption. Output exports remain until deleted.

Build context contains tracked `src/`, `scripts/`, `mcp_server/` and dependency
files, plus the newly introduced matrix sources. Symlinks are rejected. Runtime
database/log/backup folders, `.env*`, Git metadata, untracked personal files and
the master report/evidence folder are excluded. Stage intentional new application
source files before building; untracked source files are excluded by design.
No live DB/cookies are copied.

## Noise and CI policy

This is a manual local/dedicated-host tool, **not a hosted-CI performance gate**.
Hosted CI is rejected even with `--dedicated-host`. A dedicated self-hosted runner
must explicitly declare both `RUNNER_ENVIRONMENT=self-hosted` and
`--dedicated-host`; configure it for one benchmark at a time. No automatic timing
workflow, PR pass/fail threshold or new GitHub issue is introduced.

A host-local advisory lock prevents two copies of this matrix running together.
Before every cell, up to30 seconds of0.5-second idle CPU probes seek two consecutive
samples at/below25% host CPU. All observations and elapsed settling time are
retained. Failed settling and noisy immediate post-run probes mark the **whole
report ineligible**; comparison ratios are withheld. Correctness/input drift,
wrong limits or OOM also invalidate eligibility. The threshold is a screening
policy, not a confidence interval or proof that a host is dedicated. External
Docker workloads, OS cache, thermal throttling and storage noise can remain.

`--max-host-cpu-percent` and `--quiet-wait-seconds` explicitly change that policy;
do not raise them after seeing a noisy result to claim comparability. Failed
screens are useful evidence: keep the artifacts and rerun on a quieter host.
This infrastructure refuses a performance conclusion when qualification fails.

## Artifacts and metric definitions

`report.json` schema1 / protocol `bench06-matrix-v1` contains raw cells, git SHA,
source/method/dependency-layer/image hashes, host and Linux-container metadata,
Docker version, policy, input checksums, correctness, eligibility and comparisons.
`report.md` contains group medians, N, range, CV and overhead/availability notes.
Each profile/database/workload/repetition directory contains `cell.json`,
`worker.log`, and `work/sample.json` / `fixture.json.gz` from the existing worker.
Recorded commands replace output paths with a placeholder; retain exact local
commands when reporting an experiment.

- **Container wall** brackets the child worker from process launch through exit;
  it includes schema, fixture generation/export, worker startup/shutdown and load.
  It excludes image/PG startup, settling, parent idle calibration and final
  verification/report serialization. Existing receipts retain narrower per-phase
  CPU/wall samples, cold/warm state or per-attempt queue/provider metrics.
- **CPU**: cgroup `cpu.stat` before/after provides container aggregate CPU counters;
  sampled processes retain user+system CPU. Sampler process CPU is separately
  measured across the child interval, and20 idle process-tree probes are timed.
  Collection CPU is included, never subtracted. Child exit churn can lose sampled
  per-process CPU; use aggregate counters for totals. PG server CPU is unmeasured.
- **Memory**: per-process RSS/USS/PSS snapshots, anonymous stable labels per cell,
  cgroup memory.current/peak/events and existing worker high-water metrics.
  RSS sums may double count sharing. Sample maxima are not exact peaks;
  memory.peak is the kernel peak observed after calibration/load/verification,
  before final report serialization; it is not an exit-time peak. Unsupported/denied metrics stay null, never zero.
- **Correctness**: compressed fixture SHA is independently recomputed, JSON is
  parsed, three synthetic users are checked, and exported model counts match the
  fixture worker. Load results must match independently recomputed CPU checksums,
  retry counts and provider counts; trace must have seven attempts/nine provider
  calls, overlap and no missing/duplicate boundaries. Failure aborts the cell.
  Inputs/results must agree across profiles, allowing intentional tier-dependent
  schedule inventory changes; each profile's full invariants match its repeats.
- **Overhead**: raw sampler CPU and idle calibration are portable measurements,
  not a universal overhead estimate. Existing receipts retain their own timer,
  SQL/profiling and memory-probe costs. Use BENCH-04/05's separate optional profiles
  for attribution; do not mix profiled and unprofiled timing policies.

Fixture/plan/graph hashes repeat under pinned source/runtime/backend/seed. Byte
identity across backends/runtime compressors is not assumed. Timings, snapshots,
process assignment and overlap pairs vary. Two repetitions are a protocol smoke
test, not sufficient evidence for tail latency or a production optimization.

## Comparing application revisions

Default comparison requires the exact source and image, as used to demonstrate
repeatability. For a controlled application change, explicitly opt in:

```bash
# After changing application code, build its own matching source image.
uv run --no-sync python scripts/benchmark_matrix.py --build --output /tmp/matrix-candidate --baseline /tmp/matrix-before/report.json --compare-code-change
```

This permits differing application source/image IDs only when benchmark-method
hash, base/dependency layers, inputs/results, PostgreSQL image, quotas, sampling,
versions and host metadata still match and both reports qualify. The runtime
hash covers image layers before the final src/scripts copies; the Dockerfile is
itself part of the method hash. A methodology/dependency/data change produces
mismatches and no ratios. Git SHA/source/image provenance are always retained.
No automatic ratio is labelled a speedup or accepted as a production result.

## Validation and limits

```bash
SECRET=test-only FLOPPY_TEST_FAST_DB=1 scripts/test.sh app.tests.test_benchmark_matrix app.tests.test_benchmark_fixtures app.tests.test_celery_benchmarks --parallel 1
uv run --no-sync ruff check src scripts/benchmark_matrix.py
```

Fast contracts test CI/noise guards, source privacy/symlinks, metadata comparison,
explicit revision comparison, checksum/count corruption and idle qualification.
The actual matrix is the Docker integration validation; the separate BENCH-05
integration remains opt-in. No production paths, settings, models, migrations
or dependency lock are modified. This does not replace the existing full-stack
constrained benchmark for Gunicorn/webhooks/real beat topology, or long-run leak
studies. Failures may retain partial private output/logs instead of a full report;
delete that new output directory to dispose of it. No production speedup claimed.


## BENCH-10 attribution extension

The v2 matrix retains the BENCH-06 lock, quotas, offline workers, correctness
checks and host-noise threshold. Each run retains source/image hashes, raw
failures and scoped validation receipts in its chosen local output directory.
No production behavior or CI timing gate changes.

Each cell records setup, workload launch, application exit, support shutdown,
and verified removal boundaries. The existing pre-cleanup CPU screen remains
visible and gated; a second screen runs after owned-container cleanup. A busy
pre-cleanup screen is **not attributed to external contention**. PostgreSQL CPU
is read independently at workload boundaries; its startup/shutdown and the
Docker client are not included in that delta. `--postgres-tmpfs` selects a
bounded 128 MiB disposable data directory and records a different storage
policy. It cannot be compared as the same disk-backed baseline. PostgreSQL
logs survive failed readiness; no global Docker pruning is performed.

Source manifests travel inside the image. The supervised worker checks the
origins and SHA256 of actually imported project modules against that manifest;
a mount, source label or `PYTHONPATH` declaration alone is insufficient. Keep
the source frozen during building and execution, particularly when other chats
are editing imports. Loaded-origin checks cover the supervised Python process;
they do not instrument every interpreter inside Celery.

Use matched incremental observer controls, outside production requests:

```bash
# Build once from frozen source, then retain the same image for all runs.
uv run --no-sync python scripts/benchmark_matrix.py --build --profiles minimal --databases sqlite --workloads empty idle --observer off --control-seconds 5 --output /tmp/controls-off
uv run --no-sync python scripts/benchmark_matrix.py --profiles minimal --databases sqlite --workloads empty idle --observer on --control-seconds 5 --output /tmp/controls-on
# Repeat both commands with new output directories, then the identical fixed-work
# fixtures/Celery matrix with both observer settings and both database backends.
```

Observer-off retains process supervision, timing, the existing worker's own
instrumentation and two full boundary samples. It disables periodic process /
cgroup samples and their calibration. Compare absolute CPU/wall differences
and percentages against observer-off; never subtract an estimated observer cost
from observed application CPU. The report's `sampler_cpu_s` is supervisor-process
CPU during worker execution, not total Docker/OS collection cost.

The sampler adds global Linux VM CPU ticks, memory availability and numeric PSI,
owned-visible-cgroup counters, collector capture CPU, wall/monotonic/boottime
exposure, and PID/start-tick identities. Global-minus-owned remains unknown,
not an external-work measurement. Shared-VM counters do not measure the macOS
host. Matrix process snapshots can miss short-lived Redis/worker lifetimes;
Redis is embedded in the application cgroup, and its exact independent CPU is
unsupported. Boundary cgroup deltas exclude some setup/exit work and do not
measure the whole container lifecycle.

`memory_aging_report.py` reports gaps, suspend exposure, reset/boot warnings,
unusable files retained on disk, and splits aging tracks on membership/start
identity changes. Unknown GC, CoW and cache causes remain unknown. Resource
counters alone do not distinguish those causes. `memory_aging.sh` and the
existing disposable real-task recipes remain opt-in for 20–30 minute idle /
loaded windows and 2+ hour growth. Use fixed synthetic media counts, blocked
providers and a genuinely exclusive quiet host; hold the matrix's same local
lock around those recipes. Existing aging recipes do not themselves guarantee
that all these qualification requirements hold.

`eligible` remains the matrix's coarse calibration screen. The new
`resource_claim_eligible` is explicitly false: this extension does not establish
exclusive-host ownership, complete Redis/collector lifetime cost or qualified
long-window resource evidence. A dedicated-host flag alone cannot change that.
BENCH-10 remains open until those missing completion gates are demonstrated.
