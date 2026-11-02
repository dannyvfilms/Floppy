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
worker. A 200 means **queued**, not **processed**.

## Asynchronous: the worker

`integrations.tasks.process_webhook` runs on the dedicated `interactive` queue
at the highest priority (see `CELERY_TASK_ROUTES`). That queue is separate from
imports and backfills, which is what keeps normal webhook latency in the
sub-second to low-seconds range.

Each attempt is bounded:

- soft time limit `120s`, hard time limit `150s`
- `ProviderAPIError` and network errors retry up to 3 times with exponential
  backoff and jitter; malformed payloads fail immediately

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
```

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

## Ordering

Webhooks are queued, so an older event can be processed after a newer one. The
receipt timestamp is carried into the worker and used in two places:

- `app.live_playback.apply_playback_event` drops a card update whose receipt
  time is older than the card's last update, so a delayed `media.play` cannot
  replace the card left by a later `media.scrobble`.
- `api.fork_views_playback.upsert_playback_progress` drops a progress write
  whose receipt time is older than the stored row, so the delayed play cannot
  reset a completed scrobble to 0% / not completed.

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
   - a missing `webhook_finished` means the attempt died or timed out
   - `webhook_slow_queue` at WARNING marks anything past 10 seconds
3. An `outcome=unmatched` line is an identity problem, not a latency problem
   (for Plex see #1703).
4. If `queue_delay_ms` is normal but `elapsed_ms` is large, look at provider
   calls, not the queue.

Receipt timestamps are currently emitted by the Plex, Jellyfin, Emby and Kodi
receivers. Plex, Jellyfin and Emby pass the timestamp into the Now Playing
card and progress writer; the task accepts the same fields for any future
receiver.
