# Webhook delivery and queue latency

What happens between a media server sending a webhook and Floppy saving the
result, what delay is normal, and how to tell queue wait from processing time.
The acceptance criteria for this contract come from issue #1708.

## Synchronous: the HTTP request

The receiver does only work that must be bounded by the request timeout:

- resolve the per-user token and reject unknown or inactive users
- parse the body (Plex multipart `payload`, Jellyfin/Emby/Kodi JSON)
- hand the payload to the worker with a receipt timestamp and a correlation id
- fan the same payload out to enabled Plex webhook shares
- return `200` (or `503` when the broker refused the task)

No metadata lookups, identity resolution or tracking writes run on the web
worker. A 200 means **queued**, not **processed**: the event will be processed
or logged as failed (see Redelivery).

## Asynchronous: the worker

`integrations.tasks.process_webhook` runs on the dedicated `interactive` queue
at the highest priority (see `CELERY_TASK_ROUTES`). That queue is separate from
imports and backfills, which is what keeps normal webhook latency in the
sub-second to low-seconds range.

Each attempt is bounded:

- soft time limit `120s`, hard time limit `150s`
- `ProviderAPIError`, network errors and the soft time limit retry up to 3
  times with exponential backoff and jitter; malformed payloads fail
  immediately

A worker slot held by a wedged lookup is therefore recoverable, and a retry is
visible in the worker log rather than looking like a mysterious late event.

## Telemetry

Every playback receiver logs at receipt:

```
webhook_received event_id=... provider=plex event=media.play user_id=... rating_key=...
```

The worker logs start, finish and slow waits under `integrations.tasks`:

```
webhook_started event_id=... provider=plex user_id=... event=... rating_key=... queue_delay_ms=... queue_delay_bucket=le_100ms
webhook_finished event_id=... provider=plex user_id=... event=... rating_key=... outcome=persisted elapsed_ms=...
webhook_slow_queue event_id=... ... queue_delay_ms=...
webhook_failed event_id=... provider=plex user_id=... outcome=error retries=3 error=SoftTimeLimitExceeded
```

`webhook_failed` is logged once, at WARNING, when the last attempt fails and
nothing will try the event again. It names the error type only, never payload
values.

`queue_delay_ms` is measured from the HTTP receipt, not from broker enqueue, so
it includes broker and worker-reservation time. `elapsed_ms` is the processing
time after the task starts. `queue_delay_bucket` uses fixed buckets
(`le_100ms`, `le_500ms`, `le_1s`, `le_5s`, `le_10s`, `le_30s`, `gt_30s`) so the
distribution can be charted from logs without a metrics backend. A delay above
`10s` also emits `webhook_slow_queue` at WARNING.

`outcome` is one of:

| outcome | meaning |
| --- | --- |
| `persisted` | a tracking row (or progress row) was written |
| `live` | only the Now Playing card changed (e.g. Plex `media.play`) |
| `unmatched` | the event identity could not be resolved to a title |
| `ignored` | policy, user, library or reference review rejected the event |
| `skipped` | processor returned without a decision (non-playback providers) |
| `error` | processing raised; retries are logged by Celery |

`event_id` is generated at receipt and carried into every task for the same
request, including shared-recipient tasks. Use it to join the web worker log,
the worker start/finish lines and the persisted row's timestamps. The Plex
`ratingKey` and event type are logged alongside it; payload titles, usernames
and addresses are not.

## Redelivery

Once the receiver answers `200`, the broker message is the only copy of the
event. So `process_webhook` acknowledges its message only after it finishes
(`acks_late`), and a worker that dies mid-task hands it back
(`reject_on_worker_lost`):

- A worker child that is killed (out of memory, `kill -9`) gives the message
  back at once; the worker runs it again within seconds.
- A whole worker stopped mid-task (deploy, container restart) leaves the
  message unacknowledged; Redis hands it to a worker after the broker's
  `visibility_timeout` (one hour). That window is far longer than the task's
  150 s limit, so a slow task is never run twice at the same time.
- An attempt that passes the soft time limit is retried like a provider error.
  When retries run out, the task logs `webhook_failed`.

The three Stremio tasks work the same way: `Process Stremio playback webhook`
(a playback start), `Process Stremio tracker event` (player and library events)
and `Verify Stremio playback completion` (the poller that confirms a watch).
Only these four tasks acknowledge late. Imports and rebuilds run for minutes
and are not all repeat-safe, so the global setting stays as it was.

A repeat must save nothing new, and the handlers are built for it:

- A new play is dated by the event's receipt time (`_event_now` in
  `integrations/webhooks/base.py`), not the processing time. A redelivery an
  hour late carries the original `received_at`, so the duplicate-play check
  (`app/fork_services_play_dedupe.py`) sees the same time and skips it.
  Payload times (`viewedAt`, `LastPlayedDate`) still win when present.
- A rating that is already stored is not saved again, so no history row or
  outbound change is added.
- The ordering guard below compares the original receipt time, so a late
  repeat of an old event cannot undo a newer one.
- Each Plex webhook share is its own task and its own message, and each is
  repeat-safe on its own.
- Stremio tracker events are dated by their receipt time and their plays carry
  a session key, so a repeat finds the play it already saved.
- A Stremio start queues its first verifier *before* it stores the playback
  session. A worker lost in between still leaves a verifier waiting; a spare
  verifier for a session that was never stored finds nothing and stops.
- Each Stremio verifier carries the session revision it was queued for, and
  queues the next one before storing the next revision. A redelivered verifier
  for an older revision stops, so there is only ever one polling chain.
- When a verifier confirms a watch it marks the session "completing" (with the
  play to save) instead of deleting it, and closes it only after the play is
  saved. A worker lost in between leaves the claim for the redelivery, which
  saves the play once (its watched time comes from Stremio, so a repeat is a
  duplicate). The claim lasts two hours, longer than the redelivery window.

`integrations/tests/test_webhook_redelivery.py` runs every provider's task
twice with the same arguments (an hour apart) for a completed play, a partial
stop and a rating, and asserts the second run adds no tracking row, play,
history row, watch-state change or outbound delivery. It also stops a first
attempt right after its first write and checks the retry leaves one play.

A message that kills its worker every time it runs (for example, by using too
much memory) would be handed back forever and hold the interactive queue. Each
of these tasks counts how often its message has started (by Celery task id,
which a redelivery and a retry keep, in the cache for six hours) and drops it
after 8 starts with `webhook_failed ... error=TooManyDeliveries`. A
normal event starts at most 4 times (one attempt and three retries). If the
cache is down the count is skipped, never the webhook.

## Ordering

Webhooks are queued, so an older event can be processed after a newer one. The
receipt timestamp is carried into the worker as epoch seconds with its
fraction, because two events can arrive in the same second and a backlog can
process them in reverse. It is used in two places:

- `app.live_playback.apply_playback_event` drops a card update whose receipt
  time is older than the card's last update, so a delayed `media.play` cannot
  replace the card left by a later `media.scrobble`. The card keeps the precise
  time as `event_ts`; its display timestamps (`updated_at_ts` and the expiry
  times) stay whole seconds. A card without `event_ts` (cached before it
  existed, or written without a receipt time) is compared by `updated_at_ts`.
- `api.fork_views_playback.upsert_playback_progress` drops a progress write
  whose receipt time is older than the row's `last_event_at` (the receipt time
  of the newest event it applied), so a delayed Jellyfin Pause or Emby partial
  Stop cannot undo a completed stop. A dropped write saves nothing and
  publishes no progress change. It never compares against `updated_at`, which
  is processing time: a backlog would make every queued event look older than
  the one processed just before it. An equal receipt time applies in
  processing order.

`last_event_at` is unknown (null) on rows written before it existed and on rows
only ever written without a receipt time. It is deliberately not backfilled
from `updated_at`, for the reason above, so the next event on such a row
applies and starts its clock; until then a late event on an upgraded row is not
caught. Writes without a receipt time (the progress API, Check-in, the UI)
always apply and leave `last_event_at` alone. The trade-off: a webhook received
before such a write but processed after it still applies, because a
processing-time stamp on the write would wrongly drop webhooks received just
after it. A match correction that merges two progress rows keeps the newer of
their two clocks, whichever row's values win.

Every provider whose worker carries a receipt time passes it to both the card
and the durable row, including the stop path that writes the row after media
processing (Plex, Emby, Jellyfin). A stop that reached the row without its
receipt time would leave the clock unset, and a Jellyfin Pause or Emby partial
Stop received earlier in the same second could then be dropped by the card
but still reset the row.

Rollout: migration `app.0222` (`last_event_at`) and the worker code must ship
together, so stop and restart every worker before taking webhooks again. An
older worker still running alongside a new one writes progress without
touching `last_event_at`, so its writes bypass the clock in both directions.
Cards cached before the upgrade cannot recover fractional receipt times; they
order by whole seconds until the next event replaces them. The migration adds
the column only if no column of that name exists, which protects an
installation where the column was already added; it does not check that
column's type or repair a mismatched schema, and reversing the migration drops
the column whether or not this migration created it.

Final events still write their history rows regardless of order: Plex plays do
not write tracking rows at all (`STOP_ONLY` policy, see
`webhook-write-rules.md`), and a stop/scrobble persists through its own path.
Ordering drops affect display/progress state, not the historical play.

## Investigating a lag report

1. Find `webhook_received` for the event and note its `event_id`.
2. Search the worker log for the same `event_id`:
   - only `webhook_started` and a large `queue_delay_ms` means queue wait
     (worker busy or broker backlog)
   - `webhook_started` to `webhook_finished` is processing time
   - a second `webhook_started` for the same `event_id` is a retry or a
     redelivery (see Redelivery)
   - `webhook_failed` means every attempt failed and the event was dropped
   - `webhook_slow_queue` at WARNING marks anything past 10 seconds
3. An `outcome=unmatched` line is an identity problem, not a latency problem
   (for Plex see #1703).
4. If `queue_delay_ms` is normal but `elapsed_ms` is large, look at provider
   calls, not the queue.

Receipt timestamps are currently emitted by the Plex, Jellyfin, Emby and Kodi
receivers. Plex, Jellyfin and Emby pass the timestamp into the Now Playing
card and progress writer; the task accepts the same fields for any future
receiver.

## Jellyfin: more than one server

The receiver URL names the Floppy user, not the server. A user may connect
several Jellyfin servers (`JellyfinAccount`, one row each), so the processor
reads `ServerId` from the payload (the current template sends it) and matches it
to a connection (`integrations.webhooks.jellyfin.attribute_connection`):

- one connection: every event is that server's, so old URLs and templates keep
  working;
- several connections: an event whose `ServerId` matches none is ambiguous. It
  writes no collection ownership, link, or instant push, and logs a warning.
  Playback and watch events still apply to the user, because history is
  deduplicated per user.

Collection ownership and detail-page links are keyed per connection; the oldest
connection keeps the unscoped keys its rows were stored under. Instant pushes
are debounced per connection. Scheduled push and pull tasks, health checks and
Playback Reporting cursors all take an `account_id`; Playback Reporting row
identities are prefixed with the connection's `identity_scope` so equal rowids
on two servers never collide.
