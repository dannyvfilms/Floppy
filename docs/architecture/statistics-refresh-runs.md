# Statistics refresh runs

A Statistics refresh used to be one Celery task body. This records why that
was a problem for the interactive lane, what replaced it, and what a local
Docker session still has to measure.

## The problem

Floppy runs a dedicated interactive Celery worker. It exists because of a real
product failure: user-facing async work used to sit behind long imports and
backfills on the shared background worker for minutes. The interactive lane is
the fix, and it carries the work that has to land promptly — Plex and Stremio
webhook scrobbles, live playback image resolution, Plex section refreshes.

It also carried `app.tasks.refresh_statistics_cache_task`, and that task was
not short. Production has seen Statistics refreshes take tens of seconds
routinely, over 40 seconds often, and one observed All Time refresh took
roughly 189 seconds.

The interactive worker runs at concurrency 1 with `prefetch_multiplier=1`. One
monolithic Statistics refresh therefore owned the entire fast lane for its
whole duration, which recreates exactly the problem the lane was built to
avoid. Moving the task elsewhere would not have fixed it; it would have moved
it onto the queue that is already congested.

## The single-shot state machine that was there

`refresh_statistics_cache(user_id, range_name)` did all of this in one task:

1. resolve the range's `start_date`/`end_date` and its `day_list`
   (`_iter_day_range` for a bounded range, `_get_sparse_activity_days` for
   All Time);
2. load the dirty-day set;
3. pick warm days (today and yesterday), days with no cached payload, dirty
   days inside the range, and days whose cached reading score went stale;
4. build **one range-wide prefetch** over every media model for the union;
5. read the history version once;
6. build every day back to back, buffering payloads 500 at a time and writing
   them with `cache.set_many`;
7. keep the payloads of any day whose cache write was *reported as failed* in
   a Python dict for the whole run;
8. accumulate a backfill collector (four id sets) across the whole run and
   enqueue once at the end;
9. aggregate the whole `day_list`, publish the range cache, clear the dirty
   days it processed, and delete the refresh lock.

Everything between steps 4 and 9 lived only in the Python memory of one task
invocation: the range-wide prefetch (the largest single allocation), the
backfill collector, the cache-write fallback payloads, the credit-backfill
hint counter, and the day lists. There was no point at which the task
returned, so there was no point at which a webhook could be serviced.

## The run

A refresh is now a **run**: one START, a bounded sequence of CHUNKs, one
FINISH. Each stage is its own Celery message on the interactive queue, so the
worker is free between stages.

```
schedule_statistics_refresh()
   -> app.tasks.refresh_statistics_cache_task      START  (plan + claim)
   -> app.tasks.continue_statistics_refresh_task   CHUNK  (<= N days, return)
   -> app.tasks.continue_statistics_refresh_task   CHUNK
   -> ...
   -> app.tasks.continue_statistics_refresh_task   FINISH (aggregate, publish)
```

`app/statistics_refresh_run.py` holds the machine.
`refresh_statistics_cache()` is now an **inline driver** over the same
functions: it walks START → CHUNK… → FINISH to completion in-process and
returns the payload. That keeps the eager/test path and the
Celery-unavailable fallback working, and it means both drivers share one
implementation rather than one being a re-derivation of the other.

### What is bounded

`STATISTICS_REFRESH_CHUNK_DAYS` (default 25, env-configurable) is the number of
days one CHUNK builds. The bound the interactive lane actually cares about is
wall-clock, not days, so this is the knob a Docker session turns until the
slowest chunk fits its latency budget. It is deliberately *not* derived from
production timings that cannot be reproduced without a real library.

Chunk size cannot change the result — that is a test
(`test_chunk_size_cannot_change_the_result`, run at 1, 3 and 10 000 days
across five ranges).

### Yielding the lane

A chunk schedules exactly one continuation and returns. It does not loop.

The continuation is published at
`CELERY_TASK_PRIORITY_STATISTICS_CONTINUATION = 3`, above
`CELERY_TASK_PRIORITY_INTERACTIVE = 0`. Redis priorities are inverted relative
to AMQP: kombu publishes priority *N* to the key `<queue>:N` (priority 0 uses
the bare `<queue>`), and the worker BRPOPs those keys in ascending order. A
webhook published at 0 therefore lands on `interactive` and is drained before a
continuation sitting on `interactive:3`. A run that started first does **not**
outrank a webhook that arrived later.

Continuations use **no countdown** by default. Celery's Redis transport hands
an ETA task to the worker immediately and holds it in memory until due; with
`prefetch_multiplier=1` that held message occupies the worker's only prefetch
slot, which is the opposite of yielding. `STATISTICS_REFRESH_CHUNK_COUNTDOWN`
exists if a broker ever needs the breathing room, but priority — not delay —
is what keeps the lane fair.

## Where the run state lives, and why it is the cache

Run state is a small dict stored in the **existing refresh-lock key**
(`_refresh_lock_key(user_id, range_name)`), not in a new database model. This
was the main architecture decision, and it went the way it did for four
reasons:

* **Failure domain.** Every input a run consumes already lives in the cache:
  the per-day payloads, the dirty-day set, the per-user history version, the
  published range entry. Durable run state would outlive the data it
  orchestrates and would resume against day caches that are no longer there.
* **The broker is the same Redis.** Continuation messages live in the broker.
  A database run record would survive a Redis loss into a world with no
  continuation message and nothing scheduled to notice it — a genuinely stuck
  run instead of a self-healing one.
* **Loss is already safe.** If the run evaporates, the published range entry
  is still stale, and the next reader (`get_statistics_data`) schedules a fresh
  refresh. That is the existing recovery path, not a new one.
* **Reuse beats invention.** Putting the run in the refresh-lock value means
  `_lock_is_stale`, `_any_range_refreshing`, the statistics polling view and
  `get_statistics_data`'s "refresh in progress" branch all keep working across
  a multi-task run with no changes at all.

The lock is now a **heartbeat lease**: every chunk re-stamps `started_at` and
re-sets the key with `STATISTICS_REFRESH_RUN_LEASE` (default 300 s). If a chunk
dies, the lease stops being renewed, `_lock_is_stale` starts reporting the run
dead after `STATISTICS_REFRESH_LOCK_MAX_AGE`, and the next request starts a
fresh run. There is no immortal lock.

No migration was added.

### What the run record holds

Control state only:

```
run_id, range_name, history_version, state, cursor, chunk_index, chunk_size,
total_days, day_count, credit_backfill_hints, stale_score_days,
failed_write_days (capped), failed_write_count, created_at, started_at
```

Two small scratch keys hang off `run_id`:

* the **work list** — the days this run owes, as `YYYYMMDD` tokens. Eight bytes
  a day; a decade of daily activity is under 40 KiB. `_normalize_day_value`
  already round-trips that format.
* the **dirty days this run covers** — identifiers, so FINISH knows exactly
  which dirty entries it earned the right to clear.

No day payloads, no aggregates, no prefetch structures, no model
representations are persisted anywhere.

## Semantics the redesign had to preserve

### Atomicity

Only FINISH calls `cache_statistics_data`. A half-built run publishes nothing,
so the previously completed result stays usable for the whole rebuild. A run
that is superseded, aborted or abandoned publishes nothing at all.

### History version

The run records the history version it was planned against. It is re-checked
at the start of every chunk, before aggregation in FINISH, and again after
aggregation (aggregation reads the database, so history can move while it
runs). On a mismatch the run:

* does not publish,
* does not clear any dirty day,
* releases its lock and scratch keys,
* records a follow-up so a fresh run is started against the new version.

A version-A FINISH therefore cannot overwrite a version-B result.

### Locking and run identity

* **Active run** — lock present, `run_id` set, lease fresh.
* **Stale/dead run** — lease not renewed; `_lock_is_stale` reports it dead and
  the next request claims a new run.
* **Duplicate request** — a second normal request sees the active run and is
  refused. Two normal requests never become two heavy concurrent runs.
* **Obsolete continuation** — a continuation whose `run_id` does not match the
  active record logs `statistics_refresh_run_abort … superseded` and does
  nothing.

### Forced refresh

`schedule_statistics_refresh(..., force=True)` — and the long-standing
`debounce_seconds=0` spelling the Refresh button uses, which is mapped onto it
— is never silently dropped:

* no active run → it bypasses the freshness check and the scheduling dedupe
  window and starts a run immediately;
* active run → it is recorded in a dedicated rerun key and a fresh run is
  scheduled the moment the active run finishes.

The rerun flag lives in its own key rather than on the run record, because the
record is rewritten by every chunk and a flag set there could be lost to a
concurrent write.

### Dirty days

A run snapshots the dirty days its plan covers at START. FINISH removes
**only** those, from a freshly loaded dirty set, and only after the range cache
has been published. A run that fails or aborts halfway clears nothing, so every
day it owed is still discoverable. Days that go dirty after the plan was made
survive the run.

### Cache-write failures

The single-shot refresh kept a failed day's payload in Python and handed it to
the aggregator as `prebuilt_days`. A run cannot carry payloads across task
boundaries, so instead:

1. a reported `set_many` failure is **retried once** immediately;
2. days that still fail are recorded as *identifiers* (capped, for telemetry);
3. FINISH aggregates with `build_missing=True`, which already rebuilds any day
   it cannot read from the cache.

`build_stats_for_day` is deterministic for the same database state and history
version, so the published numbers are unchanged. The cost of the rare failure
path is a rebuild instead of a retained payload, and nothing unbounded is held
between chunks.

### Backfill collector

The run-wide collector is gone. Each chunk accumulates its own hints and
flushes them through `_enqueue_collected_backfills` before returning. That is
safe to repeat: `enqueue_runtime_backfill_items`, `enqueue_genre_backfill_items`,
`enqueue_credits_backfill_items` and `enqueue_episode_runtime_backfill` all
filter already-satisfied items and write into set-backed queues, so an id
repeated across chunks is a no-op.

## The prefetch trade

The range-wide `_build_prefetch_for_range` was the structure that made chunking
unsafe, and the largest single allocation in an All Time rebuild. Each chunk
now builds a prefetch over **its own days only**.

This costs more queries: roughly the same ~13 bulk queries per *chunk* instead
of per *run*, so a 1 000-day rebuild at chunk size 25 issues about 40× the
prefetch queries it used to. That is the deliberate trade — bounded memory,
queue fairness, responsiveness and recoverability, bought with throughput.
`test_prefetch_is_built_per_chunk_not_once_for_the_range` pins that the trade
actually happened, and chunk size is the dial between the two.

## Structured logging

Every stage emits a single-line structured record. None of them log payloads.

| event | fields |
| --- | --- |
| `statistics_refresh_run_start` | `run_id user_id range history_version day_count work_days chunk_size chunks` |
| `statistics_refresh_chunk_start` | `run_id user_id range chunk_index cursor total_days` |
| `statistics_refresh_chunk_end` | `run_id user_id range chunk_index days nonempty elapsed_ms cache_write_failures remaining_chunks` |
| `statistics_refresh_chunk_failed` | `run_id user_id range chunk_index` (with traceback) |
| `statistics_refresh_run_finish` | `run_id user_id range chunks work_days day_count cache_write_failures history_version total_elapsed_ms totals` |
| `statistics_refresh_run_abort` | `run_id user_id range reason expected_version actual_version chunk_index` |
| `statistics_refresh_followup_requested` | `user_id range reason` |
| `statistics_refresh_followup_scheduled` | `user_id range reason` |

The pre-existing `stats_range_summary` line is still emitted by FINISH so
existing log tooling keeps working.

`statistics_refresh_chunk_end.elapsed_ms` is the number the chunk-size knob is
tuned against.

## What this session could not measure

This work was done in a cloud session with no Docker, so **no RAM or latency
claim is made here**. Nothing below has been measured:

* interactive child peak or retained PSS;
* the largest single chunk duration on a real library;
* webhook queue wait time while Statistics is active;
* total refresh duration before vs after.

## Docker validation plan for the next local session

Measure **before** (a monolithic refresh, i.e. `STATISTICS_REFRESH_CHUNK_DAYS`
set larger than the library's active-day count) against **after** (the default
chunk size), on a real library, for an All Time rebuild:

1. **Chunk duration.** Grep `statistics_refresh_chunk_end` and take the maximum
   `elapsed_ms`. Tune `STATISTICS_REFRESH_CHUNK_DAYS` until the slowest chunk
   fits the interactive latency budget. Record the chosen value and the library
   size it was chosen for.
2. **Interactive child memory.** Per-process PSS/private-anon for the
   `celery-interactive` child, sampled across a full run. Compare peak and
   retained. The expectation to test is that peak scales with chunk size rather
   than with total active days.
3. **The product test.** Start a very large All Time rebuild, then inject Plex
   and Stremio webhooks while it runs. Success is: Statistics keeps
   progressing, webhooks are serviced *between* chunks rather than after the
   whole rebuild, and no single Statistics operation owns the worker for tens
   or hundreds of seconds. Measure webhook queue wait time directly.
4. **Total duration and queries.** Compare `statistics_refresh_run_finish`
   `total_elapsed_ms` before and after, and count prefetch queries, to put a
   real number on the throughput cost of per-chunk prefetch.
5. **Result equivalence on real data.** Rebuild the same range both ways and
   diff the published cache entry.
6. **Worker recycling and settling.** `CELERY_WORKER_MAX_TASKS_PER_CHILD` now
   counts chunks rather than whole refreshes, so a run of N chunks retires the
   child sooner. Confirm that is healthy (it should return memory more often,
   not thrash) and adjust the ceiling if a rebuild now recycles mid-run more
   than is useful.
7. **Repeated cycles.** Run several rebuild cycles back to back and confirm the
   interactive child settles rather than climbing.

## Known unresolved edges

* **START claim race.** Two START messages that arrive in the same instant can
  both plan a run; the loser's continuation chain dies at its next chunk on the
  `run_id` mismatch. Self-correcting, but it can cost one wasted chunk. The
  cache has no atomic compare-and-swap, and the window is small enough that
  paying for one would not be worth it.
* **Eager mode recursion.** With `CELERY_TASK_ALWAYS_EAGER`, a run scheduled
  through `schedule_statistics_refresh` executes its continuations
  recursively rather than iteratively. The inline driver
  (`refresh_statistics_cache`) loops instead and is what the request paths and
  tests use, so this only affects a test that deliberately schedules rather
  than calls.
* **`max_tasks_per_child` accounting.** Noted above — the interactive child now
  retires mid-run rather than between runs. Correct (a run is resumable), but
  worth watching.
* **FINISH is as bounded as it was.** FINISH aggregates the whole day list
  through the existing 50-day-chunked reader. Its accumulators still grow with
  the number of *distinct items* in the range, which is unchanged from before
  this work and is the next thing to look at if FINISH turns out to be the new
  high-water mark.
