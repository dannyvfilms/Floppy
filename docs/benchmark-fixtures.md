# Deterministic fixtures and measurement runner (BENCH-01 / BENCH-02)

For browser journeys, mobile viewports, LCP, long tasks and polling, use the
[BENCH-03 browser harness](browser-benchmarks.md), which reuses these fixtures.

For request/SQL timers, opt-in EXPLAIN and controlled SQLite lock attribution,
use the [BENCH-04 server harness](server-benchmarks.md).

For schedule inventory, task attempts, retries, queue delay and worker overlap,
use the [BENCH-05 Celery harness](celery-benchmarks.md).

For capped SQLite/PostgreSQL matrices, controlled load and comparison eligibility,
use the [BENCH-06 comparison harness](comparison-benchmarks.md).

From the repository root, with locked development dependencies installed:

```bash
uv sync --locked
uv run --no-sync python scripts/benchmark_fixtures.py --output /tmp/floppy-bench01 --profile
```

The output directory must not already exist. This runs **two fresh processes for
each of 1,000, 10,000 and 50,000 tracking rows**, with seed `1729`, one warm-up and
five measured probes per cold/warm phase per workload. Use an otherwise idle
machine. No Redis,
Celery worker, provider credentials, local database copy or running server is
needed. The harness overrides the configured database, cache and broker before
Django starts, installs the existing offline network guard, and creates its own
SQLite database. It never seeds, flushes or migrates the application database.

For a quick check or a larger dataset:

```bash
uv run --no-sync python scripts/benchmark_fixtures.py --sizes 1000 --output /tmp/floppy-bench-small
uv run --no-sync python scripts/benchmark_fixtures.py --sizes 100000 --seed 1729 --repeats 2 --runs 5 --output /tmp/floppy-bench-large
```

Sizes must be multiples of ten. `--keep-database` retains each disposable
`dataset.sqlite3`; otherwise it is deleted after export. Deleting the output
directory disposes of the run. Fixtures contain known synthetic integration
tokens and unusable passwords: **never load them into a production database**.
No real titles, accounts, emails, provider identifiers, secrets or history are
copied. Machine receipts omit hostname and arbitrary environment values. Output and
baseline paths in recorded commands are redacted; review separately saved local
invocations before sharing them.

## Repeat and compare measurements (BENCH-02)

The same runner supplies the measurement protocol; there is no second fixture
generator or production instrumentation. For a small before/after comparison:

```bash
uv run --no-sync python scripts/benchmark_fixtures.py --sizes 1000 --output /tmp/bench-before --profile
uv run --no-sync python scripts/benchmark_fixtures.py --sizes 1000 --output /tmp/bench-after --profile --baseline /tmp/bench-before/report.json
```

Each command independently runs two fresh workers with the same fixture seed.
`report.json` schema version 2 records protocol `bench02-data-v1`, raw CPU/wall and
RSS/USS/PSS snapshots, database settings, process settings, repetitions, fixture
hashes, source/lockfile hashes, Git SHA and tracked-code diff hash/dirty status.
No source diff, credentials, hostname or environment dump is exported. Command
output/baseline paths are redacted to portable placeholders; keep the exact local
invocations separately when writing an experiment report.

Application-cold trials clear the isolated locmem cache and close Django's
database connection before each sample. Reset cost is recorded separately;
opening the next connection is part of the operation. Then one unmeasured
priming call precedes the warm trials. These phases do not reset OS page
caches, database-server buffers, Python imports, registries or user-object
caches. Fixture generation/export already touched the database. They are not
process-start or deployment cold-start measurements.

Process metadata includes DEBUG, cache/broker, task eager mode, schema setup,
warm-up/reset policy, connection age, timezone, Python hash seed and numeric
thread-limit environment values. Workers use UTC and `PYTHONHASHSEED=0`.
Database metadata includes backend/version and an allowlist of effective SQLite
PRAGMAs or PostgreSQL settings; database names, hosts, usernames and passwords
are omitted. Provider HTTP and task dispatch are mocked as failures throughout
the worker, and any attempted call invalidates the run.

`--baseline` emits per-size/state/workload median timing ratios, sample counts
and percentage changes in JSON and Markdown. It compares only matching fixture
seed/checksum, protocol, machine/runtime/limits, database settings and process
policies. Incompatible groups get explicit notes and no ratio. Repetition counts
may differ. Git/source changes are recorded rather than rejected, because
measuring code changes is the purpose. Comparisons describe observations, not
statistical significance or production speedups. Historical BENCH-01 schema-v1
reports lack phase/settings metadata and are rejected as comparison baselines;
keep them as historical evidence and establish a new v2 baseline.

In addition to the existing memory-probe calibration, `collector_overhead` times
50 complete measurements around an empty function and 50 bare calls to that
same function. This exposes end-to-end timer/memory-collection cost separately
from operation durations. `--profile` still adds separate SQL/allocation trials,
with explicit warm-median timing ratios. Normal production paths are untouched.

## Disposable PostgreSQL execution

Generation/measurement defaults to SQLite. To run the same protocol against
PostgreSQL, start an isolated server, for example (synthetic credentials only):

```bash
docker run --detach --rm --name floppy-bench-postgres --cpus 1 --memory 256m --tmpfs /var/lib/postgresql/data -e POSTGRES_USER=benchmark -e POSTGRES_PASSWORD=bench-only -p 127.0.0.1:55439:5432 postgres:16-alpine
docker exec floppy-bench-postgres pg_isready -U benchmark
BENCH_POSTGRES_USER=benchmark BENCH_POSTGRES_PASSWORD=bench-only BENCH_POSTGRES_PORT=55439 uv run --no-sync python scripts/benchmark_fixtures.py --database postgresql --sizes 1000 --output /tmp/bench-pg-before --profile
BENCH_POSTGRES_USER=benchmark BENCH_POSTGRES_PASSWORD=bench-only BENCH_POSTGRES_PORT=55439 uv run --no-sync python scripts/benchmark_fixtures.py --database postgresql --sizes 1000 --output /tmp/bench-pg-after --profile --baseline /tmp/bench-pg-before/report.json
docker stop floppy-bench-postgres
```

Wait until `pg_isready` succeeds before running the command. Stop the container
even if the measurement command fails. `BENCH_POSTGRES_HOST` defaults to
`127.0.0.1` and accepts only loopback addresses/localhost. The explicitly supplied
user needs CREATEDB access to the server's `postgres` database. Each worker
creates a fresh `floppy_bench02_<random>` database from `template0` and drops
that database only in a `finally` block, including on Python errors.
`--keep-database` is SQLite-only. A server disconnect, SIGKILL or host crash can
prevent cleanup; any leftover benchmark databases contain synthetic data.
Use a disposable server as above, separate from the application server.

PostgreSQL schema/generation/export, both cache phases, comparisons and zero
leftover databases were verified at 1k on PostgreSQL 16.13. Larger PostgreSQL
runs remain unmeasured. Database-server CPU/memory and its container limits are
not collected by this in-process protocol; record the container command/limits
with the experiment. Existing constrained and memory harnesses provide server,
Redis, worker and cgroup measurements and remain the deployment tools.

## Data contract

Size means the total number of user tracking rows, excluding supporting items,
episode plays, audit history and collection rows. Each ten-row block contains a
TV tracker, its season, two movies, a book, game, music track, podcast episode,
anime and manga. Blocks rotate across three users; all five statuses are used.
All dates derive from `2025-01-01T00:00:00Z`. A local seeded PRNG supplies ratings
and activity dates; no clock or global random state supplies fixture content.

Each show has twelve episode items and two completed plays per episode. Every
tracking row and episode play has two audit revisions. Music links to an artist,
album and track; podcasts link to a show and episode catalogue. Half the trackers
link to completed synthetic import runs with consistent created counts. Four
collection copies per block reference the owning user's select custom field.

At 50k this means 50k trackers, 110k items, 120k episode plays, 340k audit
revisions and 20k collection copies. These are **persisted import outcomes**,
created through bulk writes that bypass save hooks, providers and task dispatch;
they do not measure importer parsing, provider matching, replays or scheduling.
Audit revisions deliberately include an initial in-progress state. TV/season
activity derives from child episodes, including when the parent has a held
status. This is a synthetic workload, not a model of every real library.

## Output and interpretation

- `report.json`: schema/protocol version, Git SHA, generator/lockfile SHA-256 hashes,
  runtime versions, machine limits, comparisons and all raw samples.
- `report.md`: readable checksum and timing/variance tables with limitations.
- `<size>-<repeat>/fixture.json.gz`: deterministic, dependency-ordered Django
  JSON fixture; gzip header has no timestamp or filename.
- `<size>-<repeat>/sample.json`: counts, fixture checksum/bytes, schema creation,
  generation/export costs, raw workload samples and instrumentation overhead.

Checksums must agree between repeat processes; disagreement fails the command.
Expect exact compressed bytes for the same seed, size, source, Python, Django,
SQLite and zlib versions. Schema/runtime changes may change checksums. There is
no timing pass/fail threshold: the report includes min/max and population CV
(standard deviation / mean). Two process repetitions establish repeatability,
not statistical confidence; increase `--repeats` for performance experiments.

Probes reuse the production library-query engine for movie, TV, music and podcast
pages (24 items), plus direct episode-audit and collection queries. They are
in-process probes with explicit application-cold/warm phases, **not HTTP surface
measurements**. Continue using
`benchmark_perf`, `scripts/bench.sh` and constrained/container benchmarks for
their existing purposes. This fixture work does not replace those harnesses.

Wall time and process CPU are collected without SQL capture or tracemalloc in
normal trials. Before/after RSS/USS/PSS snapshots are outside the operation timer;
null means unavailable. macOS usually has no PSS and may deny USS. `psutil` is
optional; without it all three snapshots are null. Lifetime peak RSS comes from
`getrusage`, not a phase peak; snapshots can miss transient allocation spikes.
Memory covers only the worker process, not a database server or descendants.
Schema, generation and export are separate phases; Django startup is excluded.

`--profile` adds one separate SQL-capture/tracemalloc trial per workload and
reports its wall-time ratio to the normal median. It can be materially slower;
the ratio is a noisy single-sample cost estimate. A 50-call memory-probe
calibration records collection cost separately. No profiler is installed in any
production request path. Instrumentation alone establishes no production speedup.
Host CPU/RAM, cgroup-v2 limits (where available), and CPU/address-space rlimits
are reported; null is unavailable and `-1` is unlimited. No resource caps are
imposed by the harness. macOS may represent unlimited rlimits with a large
`RLIM_INFINITY` sentinel instead of `-1`. Record external/container restrictions
separately.

## Portable restore

The fixture is standard Django `loaddata` JSON, with explicit primary keys and
foreign keys. Restore only into an **empty disposable database at the same model
schema**. It includes all synthetic dependencies, but not site configuration,
credentials, auth permissions or statistics snapshots from another instance.

For SQLite, retain the generated database with `--keep-database`, or exercise
`loaddata` using an explicitly isolated settings module. For example:

```bash
mkdir /tmp/floppy-bench-restore
cat > /tmp/floppy-bench-restore/bench_restore_settings.py <<'PY'
from config.test_settings import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/tmp/floppy-bench-restore/db.sqlite3"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_URL = "memory://"
PY
SECRET=test-only PYTHONPATH=src:/tmp/floppy-bench-restore uv run --no-sync python src/manage.py migrate --settings=bench_restore_settings
SECRET=test-only PYTHONPATH=src:/tmp/floppy-bench-restore uv run --no-sync python src/manage.py loaddata /tmp/floppy-bench01/1000-1/fixture.json.gz --settings=bench_restore_settings
```

For PostgreSQL, create a new disposable database and change **only the explicit
`DATABASES` assignment in that temporary module**, for example:

```python
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "floppy_bench01_disposable", "HOST": "127.0.0.1", "PORT": "5432", "USER": "benchmark", "PASSWORD": ""}}
```

Use that database's own credentials, then run the same migrate/loaddata commands.
Do not use the application's default database or load into a populated database:
explicit PKs and custom-field keys assume an empty target. Django resets sequences
on fixture load. A backend restore should preserve the field data/counts; a
compressed-byte checksum across different backends is not promised. SQLite
export/reload is covered by tests. A 1k fixture was also restored to PostgreSQL
16.13 with matching counts, all serialized fields, re-export checksum and verified
sequence reset (current-model schema, not migration replay). Larger PostgreSQL
restores remain unmeasured. BENCH-02 can also generate directly in a fresh
PostgreSQL database using the command above.

## Validation

```bash
SECRET=test-only FLOPPY_TEST_FAST_DB=1 scripts/test.sh app.tests.test_benchmark_fixtures --parallel 1
SECRET=test-only FLOPPY_TEST_FAST_DB=1 LIBRARY_BENCHMARK_OUTPUT=/tmp/library-baseline.json scripts/test.sh app.tests.test_library_scaling_benchmark --tag slow --parallel 1
uv run --no-sync ruff check src
uv run --no-sync ruff check scripts/benchmark_fixtures.py
```

`FLOPPY_TEST_FAST_DB=1` builds schema from models and skips migration replay. This
work changes no models or migrations. Tests check sizes and relationships,
status/import/collection coverage, no provider/task dispatch, export/reload byte
equality, existing-data refusal and memory-access-denied behavior. BENCH-02 tests
also check phase order/warm-up, incompatible-baseline rejection and PostgreSQL
isolation/cleanup on failure. The default
six fresh-process runs provide the independent repeat-generation check. Keep
machine-specific receipts outside the index; the command never commits them.
