# Watched-state synchronization

How completion state is represented, how it moves between Floppy and a media
server, and — mostly — what stops it moving when it shouldn't.

The governing asymmetry: **a wrong "watched" costs a checkmark; a wrong
"unwatched" costs someone's history.** Nearly every rule below is that
asymmetry applied to a specific situation.

## The problem this replaces

Completion state was spread across six stores with no single answer:

| Store | What it holds |
|---|---|
| `Media.status` / `end_date` | Per-row status; a *repeat is another row*, not a column |
| `Episode` rows | One row per watch, plus a redundant `dropped` flag |
| `MoviePlay` | Plays from `Movie.watch()` — importers instead add duplicate `Movie` rows |
| `PlaybackProgress.completed` | A third completion boolean, per (user, item) |
| `HistoricalMusic` / `HistoricalPodcast` | Play records for audio types |
| `Season.rewatch_started_at` | Windows all of the above into a rewatch pass |

Two consequences drove this work. Nothing could answer "is this watched, who
said so, and when did we last agree with a provider about it". And Jellyfin's
`MarkUnplayed` ran a bare `.delete()` over every row matching a title, so one
click could remove years of rewatches — while silently doing nothing at all on
TVDB-sourced or grouped-anime items, because the filter hardcoded TMDB.

## Records

### `app.WatchState` — canonical state

One row per `(user, item)` and **nothing else in the key**. `Item` already
encodes `library_media_type`, `season_number` and `episode_number` in its own
unique constraints, so grouped anime (TV-shaped rows in the anime bucket) and
episode granularity are inherited. Repeating those discriminators here would
create a second source of truth for something `Item` already guarantees.

Container types (TV shows, seasons) get no row: their state is derived from
children. Podcast *episodes* get none either — they have no `Item` at all — and
that is a declared capability limitation, not an oversight.

`play_count` is a **projection only**. Floppy models a repeat as an extra row;
every provider models it as a scalar with no per-play identity, and Jellyfin's
write is a *set*, not an increment. Only the `watched` boolean crosses a
binding. Without that restriction "a retry is not a rewatch" is unenforceable.

### `app.WatchStateChange` — the ordered log

Ordered by `sequence`, allocated from `WatchStateSequence` under a row lock
inside the change's own transaction. **Not** an autoincrement primary key:
PostgreSQL allocates those *before* commit, so a cursor paginating by key can
silently skip a row allocated earlier but committed later. Locking makes
sequence order equal commit order by construction.

`WatchStateSequence.emit_changes` gates the whole log. It is off until a user
activates their first synchronizing connection, so a library nobody syncs pays
nothing, and an upgrade's backfill cannot emit a change per item.

### `integrations` records

| Record | Job |
|---|---|
| `SyncBinding` | One approved relation to one external profile. The unit of authorization. |
| `SyncCheckpoint` | Last applied position per binding, resource and direction. Never cache-only. |
| `ProviderStateObservation` | **The merge base.** What the provider said, and what we held when it said it. |
| `OutboundStateDelivery` | Durable intent to tell one provider about one revision. |
| `StateConflict` | A disagreement held for a person; dedupes by occurrence. |
| `UnresolvedExternalReference` | An id that could not be resolved, with a reason and no secrets. |

Without `ProviderStateObservation`'s `local_revision_at_observation` and
`local_digest_at_observation`, "they moved" and "we moved" are
indistinguishable and every disagreement collapses into last-write-wins.

## How a local change becomes a change row

Projection is a *recompute*, not a delta: given a `(user, item)` it reads the
legacy stores and upserts one row. That makes it idempotent, so a double
invocation is harmless and a path signals cannot see (`bulk_create`) is
repairable by calling the same function again.

Projection is also the local change detector. Once `emit_changes` is on, a
recompute that finds the stores have moved records that movement as a properly
ordered change — so the UI, the API, the webhooks and the importers all emit
ordered changes without any of them being edited.

Backfill passes `record_changes=False`. Those rows were already there; calling
them new decisions would deliver a whole library outward on upgrade.

The backfill runs by itself once per `REPAIR_VERSION`
(`app/tasks_watch_state.py`, `Ensure watch state repair`): the startup hook
queues it, the beat entry resumes a library too large for one five-minute run,
and per-user cursor rows in `BackfillReconcileState` keep it from restarting.
It exists because bulk writes skip save signals: before 2026-10-18 an
overwrite import projected "unwatched" while deleting rows and never projected
the rows it wrote back. Any bulk write of a projected type must call
`helpers.project_imported_watch_state`; bump `REPAIR_VERSION` when one is found
that did not.

## The apply algorithm

`integrations/state/apply.py`. The order is the design — each rule exists
because a specific failure has to be impossible.

1. **Replay** — same provider event twice. *A retry is not a rewatch.*
2. **Convergent** — they already agree. Agreement is not an event. This is the
   fail-safe: if every other rule were wrong, identical states still write
   nothing.
3. **Echo** — they are telling us what we just told them. Correlated against a
   durable delivery row and a **fresh read-back**, never a cache timeout,
   because a slow echo and a genuine second play look identical to a clock.
4. **Stale remote** — the provider has not moved since we last agreed, so only
   we changed. We owe them a delivery, not a rollback, and it is not a
   disagreement.
5. **Fast-forward** — the last state we demonstrably agreed on is still ours,
   so nothing local moved and the remote change applies.
6. **Diverged** — both sides moved off the same ancestor.

Divergence resolution is deliberately non-destructive:

- A watch on either side wins — union, not last-write.
- `play_count` never decreases; a remote decrement is reported, never applied.
- **A remote unwatch while diverged is never auto-applied.** It opens a
  conflict and preserves local state. Unwatch applies only on the fast-forward
  path, and only when the binding holds `watched.write_unplayed`.

A first observation is a **baseline, not an instruction**. An unwatched first
observation in particular is not an instruction to unwatch — that is what stops
connecting a provider from wiping a library it simply does not know about.

Missing items, partial scans and authorization failures must reach the engine
as *no observation*, never as `watched=False`. `read_state` returning `None`
means unknown.

## Delivery

A transactional outbox. The delivery row is written in the same transaction as
the change, so state cannot move without a durable intent to tell someone. The
Celery kick is an optimisation; a sweeper covers a lost one, so correctness
never depends on the broker.

- **Claim before writing.** A conditional update moves `pending` to
  `in_flight`, and a partial unique index on `(binding, item) where
  status='in_flight'` lets only one hold it. Serialization is the database's
  job, not a cache lock a crashed worker could hold forever.
- **Retry by reading first.** Any attempt after the first reads provider state
  before re-issuing. A write that timed out after applying becomes an
  acknowledgement rather than a second play.
- **Coalesce** pending writes for the same item; never supersede an in-flight
  one, whose receipt must become durable first.
- **Own-origin skip.** A change is never delivered to the binding that caused
  it. Combined with echo correlation this covers both `A → Floppy → A` and
  `A → Floppy → B → Floppy`.

Celery owns no retry: `deliver_watched_state` is `max_retries=0` and the row's
`next_attempt_at` owns backoff, because a Celery retry would skip read-first.

## Imports are marked, and a destination can decline them

Importers write through the same projection as the UI, so an imported play and
a play made a second ago look identical. `import_media` now wraps every importer
in `importing_watch_state()`, which records the resulting changes with
`WatchStateOrigin.IMPORT`. An adapter that sets `ACCEPTS_IMPORTED_CHANGES =
False` receives no delivery for them. The default is `True`, so Jellyfin, Emby
and Kodi behave as before. A destination that shows deliveries as new activity
(a dated play log such as WeTrakr) should set it to `False` and receive imported
history only through an explicit export.

Adapters are found through `integrations.state.registry.ADAPTER_MODULES`: one
line per `SyncClientKind`, plus an adapter module with `build_adapter(binding)`.

## Plays, statuses and batching

Three more delivery operations sit beside `watched` and `rating`:

- `play` is one dated watch (`payload.watched_at`). It is queued only when a
  change adds a play (the play count rose), never for a date edit, and never
  coalesced: a rewatch is a second play. An unwatch queues no play. Removing a
  sent play is a separate, explicit operation (`play_remove`) that nothing queues
  yet.
- `status` is the tracking status of a movie or show (`payload.status`), queued
  from the `Movie`/`TV` save signal when the status changed. The latest waiting
  one wins. Mapping Floppy's statuses to a service's is the adapter's job.
- Both need their own approved capability (`play.push`, `status.push`), so a
  service can be given one without the other.

An adapter that declares `BATCH_SIZE` takes writes in groups (`write_batch`) and
the engine holds its deliveries instead of sending each at once:

- Each new delivery gets `next_attempt_at` from the binding's `delivery_schedule`:
  *Live* waits a ten-second window so a burst (a season marked watched) leaves as
  one request, *Hourly* and *Daily* wait for the next UTC hour or midnight.
  Because the release time is the normal `next_attempt_at`, the sweeper needs no
  second idea of "due". `set_delivery_schedule` moves waiting deliveries too.
- `flush_binding` claims what is due, at most one delivery per item and operation
  (the in-flight index allows no more), sends up to `BATCH_SIZE` per request and
  repeats until nothing is due. A per-binding cache lock keeps two flushes from
  spending the provider's rate limit twice.
- The adapter answers per item (delivered with the provider's receipt, skipped,
  failed, or retry). A whole-request failure raises: transient errors reschedule
  every item and honour `retry_after`, terminal errors fail them.
- A retry goes out apart from new work, so the same set is sent again under the
  same `Idempotency-Key` (a UUID derived from the deliveries' `client_event_id`s).
  The receipt is stored on the delivery (`payload.receipt`).
- Adapters that take one write at a time (Jellyfin, Emby, Kodi, TMDb) are not
  affected: no hold, no batching, and the schedule does not apply to them.

The sweeper (`sweep_watched_state_deliveries`) is on the Celery beat schedule
every minute. It flushes batch bindings and runs the single-write deliveries.
It also puts any delivery still `in_flight` thirty minutes after its claim
(`claimed_at`) back in the queue: its worker died, and the next attempt is safe
because it reads first, or is sent under the same idempotency key.

## Provider capability matrix

A direction ships enabled only after its adapter has been shown to hold the
contract. Adapters declare `CAPABILITIES`, the engine intersects those with
what the user approved, and the settings page names the shortfall as
**unavailable** rather than hiding it.

| Provider | Read | Write | Ships |
|---|---|---|---|
| Jellyfin | Yes | Yes — `PlayedItems` is a *set*, so read-first retry is safe | inbound + outbound |
| Emby | Yes | Unverified here | inbound only |
| Kodi | Yes, via library id lookup | Unverified; its write assigns a *count* | inbound only |
| Plex | Existing webhooks and history; manual marks via an opt-in 15-minute history poll (Plex sends no webhook for them) | `/:/scrobble` is undocumented | inbound only |
| Stremio | Existing bitfield parsing | `datastorePut` is a read-modify-write of an opaque bitfield with no CAS | inbound only |
| Audiobookshelf | Existing pull | Documented, unverified | inbound only |
| WeTrakr | No | Batched plays (dated), statuses and ratings with a per-item reply; no unwatch yet | outbound only, see [WeTrakr](../integrations/wetrakr.md) |
| Last.fm / ListenBrainz / Koito | Listens | Append-only | out of scope — listens have no unwatch |

**Never emulate unwatched by deleting listens.**

## Retraction

`app/services/unwatch.py`. Marking unwatched and deleting history are separate
operations.

- With an identifiable play (`MoviePlay.external_id`,
  `Episode.external_id`, `Episode.watch_operation_id`) exactly that play is
  removed.
- Without one, an episode retraction drops the latest play and keeps the rest;
  a movie retraction keeps every play and reverts the row's status. A provider
  saying "unwatched" is at most evidence about the most recent viewing.
- Episode retraction is scoped to `library_media_type`, so retracting a
  grouped-anime watch cannot touch the TV-bucket row for the same episode.

## Known gaps

Rating sync reuses this outbox and its delivery tasks with a separate operation
and adapter capability. See [Rating sync-back](rating-sync.md) for the shared
contract and TMDb behavior.

- The projection dual-writes alongside the legacy stores until
  `effective_state()` becomes the only reader.
- `Movie.unwatch()` drops the play but leaves `status` at Completed, so the
  stores contradict each other; the projection reports the status the user is
  shown.
- The unplayed webhook lookup still hardcodes `Sources.TMDB`. Widening it would
  newly match items untouched today, so it wants its own patch.
- Reconciliation records the attempt but does not yet enumerate providers.
- **No write direction has been verified against a real server.** Before one
  ships enabled it needs a disposable library, a round trip, and evidence that
  the echo produces zero extra history rows.
