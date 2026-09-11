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
| Plex | Existing webhooks and history | `/:/scrobble` is undocumented | inbound only |
| Stremio | Existing bitfield parsing | `datastorePut` is a read-modify-write of an opaque bitfield with no CAS | inbound only |
| Audiobookshelf | Existing pull | Documented, unverified | inbound only |
| Last.fm / ListenBrainz / Koito | Listens | Append-only | out of scope — listens have no unwatch |

**Never emulate unwatched by deleting listens.**

## Retraction

`app/services/unwatch.py`. Marking unwatched and deleting history are separate
operations.

- With an identifiable play (`MoviePlay.external_id`,
  `Episode.watch_operation_id`) exactly that play is removed.
- Without one, an episode retraction drops the latest play and keeps the rest;
  a movie retraction keeps every play and reverts the row's status. A provider
  saying "unwatched" is at most evidence about the most recent viewing.
- Episode retraction is scoped to `library_media_type`, so retracting a
  grouped-anime watch cannot touch the TV-bucket row for the same episode.

## Known gaps

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
