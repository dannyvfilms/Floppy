# Server and database measurements (BENCH-04)

This opt-in runner reuses Floppy's `RequestPerformanceLoggingMiddleware`,
`request_timing.profile_sql`, `db_diagnostics` and the
[deterministic fixture/resource helpers](benchmark-fixtures.md). It adds no
production imports, middleware or request-path work. No running app, browser,
Redis, Celery worker or provider credentials are required.

From the repository root:

```bash
uv sync --locked
uv run --no-sync python scripts/benchmark_server.py --profile --output /tmp/server-before
uv run --no-sync python scripts/benchmark_server.py --profile --output /tmp/server-after --baseline /tmp/server-before/report.json
```

Each command runs two fresh processes, creates anonymous 1k tracking datasets
with seed 1729, and measures three cold and three warm requests for eight routes,
with performance middleware both enabled and disabled. Alternate processes
reverse mode order. Output directories must be new. Run on an otherwise idle
machine. If the default uv cache is restricted, prefix commands with
`UV_CACHE_DIR=/tmp/floppy-uv-cache`.

Other sizes, routes and repeat counts:

```bash
uv run --no-sync python scripts/benchmark_server.py --size 10000 --runs 5 --repeats 2 --routes movies tv history collection --output /tmp/server-10k
uv run --no-sync python scripts/benchmark_server.py --size 50000 --profile --output /tmp/server-50k
```

Sizes must be multiples of ten, at least ten; runs and repetitions must each be
at least two. Routes: `home movies tv music podcasts history collection lists`.
This is a scoped server benchmark; the separate
[browser runner](browser-benchmarks.md) covers network, mobile and browser work.

## Artifacts and interpretation

`report.json` (schema 1, protocol `bench04-server-v1`) contains machine/limit
metadata, git SHA/dirty flag, relevant source and dependency checksums, database
settings, fixture checksums, process settings, every raw sample, summaries and
optional baseline comparison. `report.md` provides wall/CPU/SQL tables, CV,
min/max, overhead ratios, resource examples and unavailable-metric notes.
Each `repeat-N/` retains a portable `fixture.json.gz` and raw `sample.json`.
SQLite databases and lock files are removed; PostgreSQL databases are dropped
even if a worker fails. Delete the output folder to dispose of artifacts.

Fixture contents/checksums repeat with pinned code, dependencies, seed, size
and database backend. Clock is fixed at 2025-01-01 UTC and hash seed is zero.
Runtime, CPU, memory and query plans are expected to vary. An incompatible
protocol, source checksum, machine, scenario, database or process policy
produces explicit comparison mismatches and no ratios. Commands recorded in
reports replace output paths with placeholders; retain exact local commands
in your experiment notes. No statistical significance or production speedup
is implied by these samples.

The Django Client exercises actual authenticated middleware, views and template
rendering. It does not include HTTP transport, Gunicorn queues, static requests
or browser readiness. Responses must be HTTP 200; auth redirects fail the run.
Cold trials clear the isolated local cache and close the database connection;
they do not evict OS/database page caches. Warm trials prime once per mode/route.
The enriched fixture adds only synthetic Home rows to BENCH-01's media/history,
imports, users, music/podcasts and collection custom fields.

Raw outer wall and process CPU timers bracket the Client request. Existing
middleware logs supply query count, SQL execute duration, thread CPU, provider
time/calls and inflight count, plus authenticated `Server-Timing`. Middleware
wall brackets its downstream chain and differs from outer wall. Log values
are rounded by the existing contract (wall to 1 ms; CPU/SQL to 0.1 ms). SQL time
includes execution and lock waits; later cursor fetching is not independently
timed. SQL/CPU/wall overlap and must not be added together.

Process RSS/USS/PSS snapshots are outside timed requests. Values are bytes,
with null for unsupported/denied metrics; snapshots are not peaks and shared
RSS may double count. PostgreSQL server processes are not included in Python
resource totals. Twenty memory probes are timed separately per worker.
Enabled/control median ratios estimate existing middleware collection cost
within this harness, including forced diagnostic log formatting/capture.
Disabled controls retain other production middleware; existing installed
boundary wrappers have a no-tally fast path. Neither this comparison nor an
idle probe is a universal production overhead estimate. Ratios below one
reflect noise/cache/order effects, not negative instrumentation cost.

## Opt-in SQL profiling and EXPLAIN

`--profile` clears the local cache and closes the DB connection before one
separate cold request per route with the existing bounded
SQL attribution profiler (64 fingerprints, eight sites each). Its timing is
separate from regular samples; compare against cold enabled requests only
as a noisy indication of profiling overhead. At most 32 standalone SELECTs
per request are retained privately for subsequent plan requests. Overflow
counts are explicit. CTEs and mutations are excluded.

SQLite uses `EXPLAIN QUERY PLAN`; PostgreSQL uses `EXPLAIN (FORMAT JSON)`.
Parameters are bound unchanged. No ANALYZE is run. Exported plans allow only
SQLite operation/id/parent, or PostgreSQL structural node types, costs,
estimated rows/width and children. Predicates, literals, relation/index names,
raw SQL, bound parameters and SQL shapes are omitted. Plans are correlated by
statement index/fingerprint, with query timing/site attribution available
separately. This privacy boundary intentionally omits detailed predicates
and index names; investigate them separately on synthetic data if needed.

## SQLite contention attribution

Each SQLite worker also creates a distinct two-connection WAL probe database.
It runs uncontended writes, writes released after a nominal 40 ms hold, and
writes that exceed an 80 ms busy timeout. An event establishes that the waiter
started before the owner is released. Raw samples record actual execution
duration, thread CPU, known synthetic writer overlap, outcome and existing
`db_diagnostics` error classification/failed-execution duration.

The overlap is a wall-clock attribution interval, not measured native lock
sleep. Scheduler delays, execution and SQLite's busy retry granularity remain
in the duration. `native_busy_sleep_s` is explicitly null. Production SQLite
does not reveal the owning request or exact busy-handler sleep through this
API; an ordinary failed execution duration is only an upper bound. A WAL
reader, deferred lock upgrade and a production import workload are different
scenarios. The existing `investigate_performance.py --sqlite-contention`
experiment covers import/foreground interactions; this probe supplies a small
repeatable calibration without duplicating that experiment.

## Disposable PostgreSQL

Use a dedicated loopback PostgreSQL server and an account with CREATEDB:

```bash
BENCH_POSTGRES_USER=bench BENCH_POSTGRES_PASSWORD=bench BENCH_POSTGRES_PORT=55439 \
  uv run --no-sync python scripts/benchmark_server.py --database postgresql --profile --output /tmp/server-pg
```

The BENCH-02 helper creates a unique `floppy_bench02_*` database from template0
and drops it with FORCE in `finally`. Non-loopback hosts are rejected. No
configured application database is opened. SQLite lock results are null with
an explicit PostgreSQL note; PostgreSQL lock attribution is outside this task.

## Safety and validation

Settings are isolated before Django starts. The current-model schema is built
with syncdb; this is not a migration replay. Cache is LocMem, broker is memory,
provider HTTP raises synthetic offline errors, and task publication is mocked.
Mock attempts are counted. The existing offline guard also blocks accidental
provider access. Fixtures have synthetic integration tokens and unusable
passwords; never restore them into a production database. No real database,
session, user data or personal browser cookie is copied. Reports export no
response bodies, headers beyond numeric Server-Timing, error text, environment
dump, SQL/parameters or absolute source paths. Profile sites are repo relative.

```bash
SECRET=test-only FLOPPY_TEST_FAST_DB=1 RUN_SERVER_BENCHMARKS=1 scripts/test.sh app.tests.test_server_benchmarks app.tests.test_request_performance_logging app.tests.test_db_diagnostics app.tests.test_benchmark_fixtures --parallel 1
uv run --no-sync ruff check src
uv run --no-sync ruff check scripts/benchmark_server.py
```

New benchmark integration tests carry `slow`/`benchmark` tags. The subprocess
request test additionally requires `RUN_SERVER_BENCHMARKS=1`; ordinary contract
tests are fast. No application behavior, models or production settings change.
