# Celery work tracing (BENCH-05)

The opt-in runner inventories configured static beat schedules, direct dynamic
schedule creation sites and synthetic `django-celery-beat` rows. It exercises
real asynchronous Celery tasks through a new socket-only Redis instance,
correlating publish/start/end/retry by deterministic job ID and attempt number.
It reuses existing task SQL/provider/CPU diagnostics and
[fixture/resource helpers](benchmark-fixtures.md). Production code does not
import this instrumentation. No running application, account, broker, beat or
provider credentials are needed.

From the repository root, with `redis-server` installed (`brew install redis`
on macOS, or your system package manager):

```bash
uv sync --locked
uv run --no-sync python scripts/benchmark_celery.py --output /tmp/celery-before
uv run --no-sync python scripts/benchmark_celery.py --output /tmp/celery-after --baseline /tmp/celery-before/report.json
```

Directories must be new. Run sequentially on an otherwise idle host. If uv's
cache is restricted, prefix commands with `UV_CACHE_DIR=/tmp/floppy-uv-cache`.
OS permissions may prevent USS/PSS collection; those values are null rather
than zero. Linux typically exposes PSS; Darwin does not. A local execution
outside the filesystem sandbox can expose USS where sandbox execution cannot.

Each command launches two fresh repeat processes. Each process builds a 1k
anonymous media/history/import/user/music/podcast/collection fixture (seed1729)
and four dynamic schedules: enabled interval, disabled interval, cron and
clocked one-off. Clock is fixed at 2025-01-01 for Django fixture timestamps;
Celery ETA and monotonic timers use real elapsed time. No beat is started.
Each repeat runs a fresh two-slot worker in control and enabled modes, reversing
mode order on alternate repeats.

Six deterministic jobs read a bounded page from the fixture, perform seeded
PBKDF2 work and call a mocked provider. The first two jobs use a bounded barrier
to guarantee an observable overlap opportunity. One job retries once with a
50ms countdown; seven attempts yield six successful logical jobs. Each batch
makes nine mocked provider calls (eight on successful attempts, one on the
retrying attempt). Unexpected setup HTTP or task publication fails the run.
No production scheduled task is executed by this calibration.

Other fixture sizes, waits and profiling:

```bash
uv run --no-sync python scripts/benchmark_celery.py --size 10000 --repeats 3 --provider-ms 40 --output /tmp/celery-10k
uv run --no-sync python scripts/benchmark_celery.py --size 50000 --output /tmp/celery-50k
uv run --no-sync python scripts/benchmark_celery.py --size 20 --profile --output /tmp/celery-profile
```

Size must be at least ten and divisible by ten; repeats at least two;
provider-ms between1 and1000. Only prefork is supported. Concurrency is fixed at
two because the overlap barrier requires two slots. The worker consumes only
`bench05.background` and `bench05.interactive`. The existing `investigate_performance.py` supports separate thread-pool experiments.
This tests synthetic routing
and queue delays; it does not reproduce Floppy's dedicated production
interactive/background worker topology.

## Outputs and reproducibility

`report.json` (schema1, protocol `bench05-celery-v1`) and `report.md` contain
metadata, raw measurements, variability, overhead and unavailable-metric notes.
Each `repeat-N/` retains `sample.json` and portable `fixture.json.gz`.
Receipts include git SHA/dirty status, source/lockfile hashes, machine/RAM/CPU
and limits, Python/Celery/Kombu/Redis versions, database settings, worker pool,
concurrency/prefetch, synthetic plan, fixture/plan/inventory hashes and controls.
Output paths are placeholders in recorded commands; retain exact local
commands in the experiment record. Runtime differences cause baseline
comparison mismatches instead of misleading ratios.

Fixture, plan and inventory hashes must match between workers of a command.
They repeat for pinned source/runtime/backend, seed, settings and size. Timing,
resource samples, worker labels, event order, actual queue delays and overlap
vary. The event graph checksum excludes times/order/resource values; it checks
job/attempt/state/event-kind membership, not byte equality of traces. Backend
fixture byte equality across SQLite and PostgreSQL is not asserted.

The Markdown report provides batch medians/range/CV, per-attempt timings,
resource examples and schedule counts. JSON retains unrounded samples,
parent probe costs, numeric existing task diagnostics and the overlap pairs.
Six jobs per batch and two repeats are a small calibration, not a significance
test. No production speedup is inferred from instrumentation.

## Schedule inventory and privacy

Static inventory reads `CELERY_BEAT_SCHEDULE` and configured task routes after
settings load, recording cadence and whether arguments exist. Values of
args/kwargs are omitted. Dynamic inventory reads only the new disposable DB;
it is not a dump of the user's configured schedules. Row names, descriptions,
args, kwargs, headers and solar coordinates are omitted. Synthetic aliases
replace schedule IDs. Solar cadence is identified with location omitted.

An AST inventory finds direct `PeriodicTask.objects.create/get_or_create/`
`update_or_create/bulk_create` calls under `src/`, excluding tests/migrations.
It records source/function/line and a literal task name when resolvable. An
expression such as a per-provider import task remains explicitly unresolved.
This inventories creation entry points across recurring imports, exports,
integrations and lists. It cannot statically resolve aliases, indirect queryset
updates, data-dependent schedules or historical migration outcomes. Source
sites and unresolved flags are evidence to inspect, not inferred active rows.

Arbitrary task bodies/arguments, error/retry text, credentials, headers, raw URLs and
process IDs are not exported. Trace callbacks filter `bench05.*` only, retain
allowlisted numeric fields and replace observed PIDs with local worker labels.
Provider HTTP is mocked, including its latency; no network request is sent.
Optional profiles export only bounded function statistics, with source paths
relative to the repo or library basenames, never full native pstats dumps.

## Metric definitions and overhead

- **Enqueue** is `before_task_publish`; **published** is broker return;
  **start/end** are observed `task_prerun/task_postrun` boundaries. Retry
  publications reuse a logical ID with an incremented attempt number. RETRY
  postrun closes one attempt; the final SUCCESS closes the next.
- **Queue delay** is enqueue intent to observed start. It includes producer
  publication, worker scheduling and retry ETA/countdown. It is not exact
  Redis residence time. Published-to-start can be negative when consumption
  races producer return; raw negatives are preserved. All clocks are on one
  host, not suitable for multi-host queue-delay measurement without clock sync.
- **Overlap** is intersection of observed execution intervals, including
  observer work and waits. It does not prove simultaneous CPU execution.
  Incomplete/duplicate boundaries are explicit and invalidate calibration.
- **CPU** includes per-attempt thread and process CPU, plus producer batch CPU.
  Process CPU can include other threads; shared process totals must not be
  summed across overlapping thread-pool tasks. Prefork child startup, idle
  parent, broker CPU and hard-killed attempts are not attributed to task CPU.
- **Memory** is process RSS/USS/PSS bytes at attempt boundaries. Snapshots are
  not peaks. Null means unsupported/denied; RSS includes shared pages, so sums
  may double count. Twenty parent-process memory probes per mode have separate
  wall/CPU timing; this is not an active-child collector-cost estimate.
- **Provider counts/time** observe mocked request attempts. Existing production
  task diagnostics separately report provider time, SQL count/time, CPU and
  RSS/HWM. They are rounded by their log contract and overlap wall/CPU time.
- **Control** keeps basic body timers/results and mocked calls; **enabled** adds
  existing performance diagnostics, lifecycle signals, Redis event writes and
  resource probes. Batch timing brackets publication through all result gets,
  excluding worker startup/shutdown, final trace drain and calibration probes.
  It includes result delivery/polling, so enabled/control ratios cannot isolate
  one callback's cost. Raw values are never corrected by subtracting overhead.
- `--profile` adds cProfile inside both modes' bodies. Its top20 function rows
  are opt-in, include profiler overhead and cover successful attempts only;
  failed/retry-attempt profile rows are unavailable. Compare only matching
  profile policies. Source hashes and settings gate baseline comparisons.

## Disposable PostgreSQL

The default SQLite file is private to the output directory. To use a dedicated
loopback PostgreSQL server, reuse the BENCH-02 database helper:

```bash
BENCH_POSTGRES_USER=bench BENCH_POSTGRES_PASSWORD=bench BENCH_POSTGRES_PORT=55439 \
  uv run --no-sync python scripts/benchmark_celery.py --database postgresql --output /tmp/celery-pg
```

The account needs CREATEDB. A new `floppy_bench02_*` database is dropped in
`finally`, never the configured application database. Do not point this at a
production server. The Redis socket, broker/result DBs and workers are always
new; no connection to localhost6379 or existing queues is used. Redis has no
TCP listener or persistence. SQLite/WAL/SHM files are removed and Redis stopped;
delete the output folder to discard exported fixtures/reports. A schema failure
before cleanup may retain only its own newly created SQLite output file.

## Validation

```bash
SECRET=test-only FLOPPY_TEST_FAST_DB=1 RUN_CELERY_BENCHMARKS=1 scripts/test.sh app.tests.test_celery_benchmarks app.tests.test_memory_envelope app.tests.test_db_diagnostics app.tests.test_celery_broker --parallel 1
uv run --no-sync ruff check src scripts/benchmark_celery.py scripts/celery_trace.py
```

The real Redis/prefork test is tagged `slow`/`benchmark` and requires
`RUN_CELERY_BENCHMARKS=1`. Fast tests verify privacy, plan determinism, cadence,
unresolved schedule sites, retry/overlap correlation, publication races and
incomplete/duplicate events. Schema uses current models through syncdb, not
migration replay. Existing task diagnostics and production behavior are unchanged.
