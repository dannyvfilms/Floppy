# Floppy tracking client guide

What a third-party client (Kodi, a scrobbler, or a Nuvio client, should Nuvio
ever ship one) needs to implement two-way tracking against Floppy, without
reading Floppy's source.

The runnable half of this document is
`src/api/tests/test_nuvio_conformance.py`. Every numbered step below has a test
there; the assertions are the contract. If this page and that file disagree,
the file is right.

```bash
SECRET=test-only scripts/test.sh api.tests.test_nuvio_conformance
```

## Contract artifacts

| Artifact | Path |
|---|---|
| OpenAPI (verified subset) | `src/api/contracts/openapi.yaml` |
| AsyncAPI (webhook channels) | `src/api/contracts/asyncapi.json` |
| JSON-LD context | `src/api/contracts/context.jsonld` |
| Scope contract | `docs/architecture/api-scopes.md` |

Each operation in the OpenAPI document carries `x-required-scope`, so the scope
to request is published rather than guessed.

## 1. Connect

### Preferred: OAuth device flow

A public client should use Floppy's OAuth device flow instead of asking the
user to copy a long-lived token.

First introduce your app once per Floppy server and keep the returned
`client_id`. The name is shown to the user, who sees it marked "Unverified".
Limit: 10 requests a minute, name up to 60 characters. A registration that no
one ever signed in with is deleted after a day; if the device endpoint answers
`invalid_client`, register again.

```http
POST /oauth/register

client_name=Nuvio on Living Room TV
```

The reply is `201` with `client_id`, `client_name`, `grant_types` and
`token_endpoint_auth_method` (`none`).

Discover the endpoints and supported scopes from:

```
GET /.well-known/oauth-authorization-server
GET /oauth/scopes
```

Request a device code:

```http
POST /oauth/device/authorization

client_id=flp_oauth_...
scope=scrobble:write progress:read progress:write watchlist:read watchlist:write catalog:read sync:read
```

Show the returned `verification_uri_complete` (or `verification_uri` plus
`user_code`) to the user. Poll the token endpoint no faster than the returned
`interval`:

```http
POST /oauth/token

client_id=flp_oauth_...
grant_type=urn:ietf:params:oauth:grant-type:device_code
device_code=flp_device_...
```

Before approval, the token endpoint returns `authorization_pending`. Polling
too quickly returns `slow_down`. After approval it returns a one-hour bearer
access token and a rotating refresh token.

Refresh with:

```http
POST /oauth/token

client_id=flp_oauth_...
grant_type=refresh_token
refresh_token=flp_refresh_...
```

A successful refresh returns a new access token **and a new refresh token**.
Replace the old refresh token atomically; reusing a rotated token is treated as
possible replay and revokes that rotation family. A refresh request may retain
or narrow its scopes, but cannot broaden the user's original grant.

The user can review and revoke grants under **Settings → Connected
Applications**. A client may also call `POST /oauth/revoke` with its
`client_id` and access or refresh token.

Send the access token as:

```
Authorization: Bearer flp_xxx
```

### Manual-token fallback

For clients that do not implement the device flow, the user can still create a
token in **Settings → Integrations → App tokens**, name it after the device, and
paste it into the client. The secret is shown once.

Manual tokens may be sent as:

```
Authorization: Bearer flp_xxx
Authorization: Token flp_xxx
X-API-Key: flp_xxx
```

The default tracking preset carries exactly what a tracking client needs:

```
scrobble:write  progress:read  progress:write
watchlist:read  watchlist:write  catalog:read  sync:read
```

It cannot reach lists, music, podcasts, imports, exports, user settings, or
metadata writes. Request only the additional permissions your client actually
needs.

Then call `GET /api/v1/sync/connections/` and keep each `origin_key`. You need
it in step 5, and without it your position can never be recorded.

## 2. Initial merge

Floppy merges non-conflicting state and preserves conflicting local values for
review. It never silently overwrites a user's existing library.

Start from `cursor=0`, which is always valid. Read `oldest_sequence` and
`newest_sequence` from any feed response to know what the server still holds.

### Pull-only clients: register and take a snapshot

A client that only reads (Kodi's Umbrella add-on) registers itself with
`POST /api/v1/sync/connections/` and `{"instance_key": "<stable random id>",
"label": "<optional>"}`. The token needs `sync:write` on top of the tracking
preset (the token form has a "Pull-sync client" preset), because registering
turns the account's change log on. It is idempotent: the same key returns the
same binding (`201` the first time, `200` after), its `origin_key`, and
`resnapshot_required` (true until a snapshot is pinned). The binding holds
`watched.pull` only, so it never queues a delivery and is never reconciled.
An account holds at most 10 pull connections (`409 connection_limit`).

Registration never overrides the owner. A connection that is off, needs
reapproval or is paused returns `409 {"code": "connection_inactive",
"reason": "disabled" | "needs_reapproval" | "kill_switch"}` and stays as it is:
stop and tell the user. Only `reason: "missing"` means register again.

To fill a local cache without replaying history, page through
`GET /api/v1/sync/watched-state/?connection=<origin_key>` (`limit` 1-1000,
default 500). `connection` is required (`400 connection_required`). It returns
watched movies and episodes only. Pass each response's `next_cursor` as
`cursor` and the first page's `resume_cursor` back as `resume_cursor`; stop
when `has_more` is false. The first page pins `resume_cursor` as the
connection's checkpoint. When the last page is applied, continue with
`GET /api/v1/sync/changes/?connection=<origin_key>&cursor=<resume_cursor>`.
Rows that changed while you paged may arrive twice, never zero times.

Errors on the snapshot and the named feed:

| Response | Meaning | Do |
|---|---|---|
| `409 connection_inactive` (`reason`) | Not registered, not a pull connection, off, paused, or Floppy is not recording changes | Register again only for `missing`; otherwise stop |
| `409 cursor_expired` | Cursor compacted, the log was off or state was repaired since your snapshot, or no snapshot is pinned (`reason` may be `resnapshot_required` or `projection_incomplete`) | Take a fresh snapshot |
| `503 projection_incomplete` + `Retry-After` | Floppy is still rebuilding this account's watched state | Wait, then snapshot |
| `400 invalid_resume_cursor` | `resume_cursor` is above what the server pinned | Restart the snapshot |

Every snapshot and feed row carries both `watched_at` and `last_watched_at`
(same value), plus `numbering` (`"provider"` or `"custom"`) and
`episode_order_id`. A `custom` row uses the user's personal episode order, so
its season and episode numbers do not match the show's provider numbering:
skip it rather than guess. A named pull feed requires a pinned snapshot; the
unnamed feed is unchanged. `limit` on the change feed must be a positive
integer; values above its cap are clamped.

## 3. Playback updates

| Purpose | Call |
|---|---|
| Resume position | `PUT /api/v1/playback/progress/` |
| Playback events | `POST /api/v1/scrobble/` |
| Watched state | `PUT /api/v1/media/{type}/{source}/{id}/watched-state/` |

Progress does not create history. Completion applies to the identified movie or
episode only, and a retry never becomes a rewatch.

### When the user marks something watched by hand

Send the same `stop` you send for a finished title, with `"manual": true`
and no position:

```http
POST /api/v1/scrobble/

{"action": "stop", "media_type": "movie", "ids": {"imdb": "tt0133093", "tmdb": "603"},
 "title": "The Matrix", "completed": true, "manual": true,
 "client_event_id": "mark-1b6e..."}
```

| Situation | Result |
|---|---|
| Title Floppy has never seen | Created and Completed, one watch |
| Title planned or in progress | That entry becomes Completed, no second row |
| Title already watched | Nothing changes. It is agreement, not a rewatch |
| Same `client_event_id` again | The first result, no second mutation |
| `stop` without `manual` | A play. A second viewing is a rewatch |

An episode is marked the same way, with `season_number` and `episode_number`.
`manual` must be a boolean (`400` otherwise) and is ignored on `start` and
`pause`. Add `played_at` when the client knows when the user watched it;
otherwise Floppy uses the time of the request.

**Unmark is not sent.** There is no call that reverses a mark without deciding
what to do with the user's history, so a client should leave Floppy as it is
when the user unmarks. Floppy's own unmark keeps past plays.

**Do not use `PUT .../watched-state/` for this.** It records the watched
state in Floppy's sync ledger only. It adds no library entry and does not turn
a Planning entry into Completed, so the title would not look watched in Floppy.

## 4. Offline retries

Send `client_event_id` (or the `Idempotency-Key` header) on every mutation.

| Situation | Result |
|---|---|
| Same id, same payload | The prior result, no second mutation |
| Same id, different payload | `409` with `idempotency_conflict` |
| New id | A new operation |

Receipts are scoped to your connection, so a per-install counter starting at
`1` on a second device is not a collision.

Retention is `INTEGRATION_RECEIPT_RETENTION_DAYS` (default 14). A retry after
that window is treated as a new operation, so back off within it.

**One known deviation:** a replayed response is the same result, but its
`updated_at` is re-encoded to millisecond precision where the original had
microseconds. Compare semantic fields, not bytes.

## 5. Incremental pulls

| Feed | Path |
|---|---|
| Watched state | `GET /api/v1/sync/changes/` |
| Resume progress | `GET /api/v1/sync/progress-changes/` |

Both take `cursor` and `limit`, and both return `results`, `next_cursor`,
`has_more`, `oldest_sequence` and `newest_sequence`. The cursor is exclusive
and is a server sequence, not a timestamp.

Always pass `connection=<origin_key>`. Asking for changes after N is your proof
that you applied everything through N: it records your checkpoint, and it is
what allows Floppy to compact the log. **A client that never names itself pins
the change log open forever.**

Apply a page fully before pulling the next one. Never advance your own cursor
past a page you failed to apply.

Deletes arrive as entries with `kind: "delete"`. Absence from a page is never a
delete.

### Reading Floppy state into a client

A client that shows Floppy's resume positions and watched flags (for example a
"Continue Watching" row) needs three things from each feed row.

| Field | Why a client needs it |
|---|---|
| `media_type`, `media_id`, `source` | Which title. For an episode, `media_id` is the **show's** id |
| `season_number`, `episode_number` | Which episode. `null` for a movie. Without these, two episodes of one show are indistinguishable |
| `ids` | Provider ids (`tmdb`, `imdb`, `tvdb`) to match against the client's own catalogue. An episode carries its show's ids |
| `position_seconds`, `duration_seconds`, `completed` | Progress feed only. Absolute seconds, so a client does not have to guess from a percentage |
| `watched`, `play_count`, `watched_at` | Watched-state feed only |
| `origin_key` | Progress feed only. Skip rows whose `origin_key` is your own connection's: they are your echo |

Rules for applying them:

- A progress row with `completed: true` is not a resume position. Show the item
  as watched (or advance to the next episode), never as resumable.
- A progress row with `kind: "delete"` clears the resume position. It does not
  mean the item is unwatched.
- Progress and watched state are separate feeds. Applying a position never
  creates a play, and a watched flag never invents a position.
- On a first connection, read `newest_sequence` from the feed (`0` if it is null), then page the
  snapshot at `GET /api/v1/playback/progress/` (`?completed=false` for resume
  candidates), then pull the feed from the sequence you read first. Rows may
  repeat across the two reads; applying the same row twice is harmless.

## 6. Resets and expired cursors

If your cursor falls below what the server retains, you get:

```json
{
  "code": "cursor_expired",
  "detail": "This cursor is older than the retained change log...",
  "oldest_sequence": 4211,
  "newest_sequence": 9020
}
```

with status `409`. Read the current snapshot and resume from there. Floppy
returns this rather than serving the remaining tail, which would look like a
successful catch-up while silently dropping everything in between.

Change-log retention is `WATCH_STATE_CHANGE_RETENTION_DAYS` (default 30), and
compaction never crosses a live connection's checkpoint.

## 7. Reconciliation and diagnostics

`GET /api/v1/sync/connections/` reports, per connection:

`status`, `directions`, `capabilities`, `unavailable_capabilities`,
`last_reconciled_at`, `last_error_message`, `pending_deliveries`,
`failed_deliveries`, `open_conflicts`, `unresolved_references`, and
`checkpoints` (with `last_sequence` and `behind_by`).

Surface `failed_deliveries` and `behind_by` in your UI. A connection that shows
"connected" while sitting thousands of changes behind is the failure users
actually hit, and no status field shows it.

Conflicts: `GET /api/v1/sync/conflicts/` and
`POST /api/v1/sync/conflicts/{id}/resolve/`. Destructive reconciliation always
requires an explicit user action.

## 8. Disconnect

The user revokes the token in Settings. Revocation and expiry take effect on the
next request.

**Disconnecting never deletes tracking data.** Do not offer "disconnect and
erase" as one action.

## NuvioTV's Floppy tracker

**Status: not released.** Nuvio does not officially support Floppy. This is an
unmerged proposal ([NuvioMedia/NuvioTV#3811](https://github.com/NuvioMedia/NuvioTV/pull/3811))
awaiting maintainer approval ([#2935](https://github.com/NuvioMedia/NuvioTV/issues/2935))
and device testing. Nuvio Mobile has no Floppy client.

The proposed NuvioTV tracker (Settings, Trackers, Floppy) is scrobble-only. The
user enters their server address and the app token; NuvioTV checks it with
`GET /api/v1/sync/connections/` and sends playback to `POST /api/v1/scrobble/`.

NuvioTV only knows how far through a title it is, as a percentage, never in
seconds. So every event carries `progress_percent` (0 to 100), and a stop also
sends an explicit `completed` flag. Floppy multiplies the percentage by the
title's length (the event's `duration_seconds` if sent, else the runtime it
holds) to get the position, so a seek shows on the Now Playing card at the next
event and a stop leaves a resume point. If it does not know the length, the card
shows the percentage itself. `position_seconds`, when a client has it, always
wins over `progress_percent`.

| NuvioTV event | Sent to Floppy | Result in Floppy |
|---|---|---|
| Playback starts or pauses | `start` / `pause`, `progress_percent` | Now Playing card at that position |
| Stop at 80% or more | `stop`, `progress_percent`, `completed: true` | Completed, one play, resume point stored |
| Stop from 1% to 80% | `stop`, `progress_percent`, `completed: false` | In Progress, never Completed, resume point stored |
| Stop under 1% | Not sent | Nothing (a skim) |

It identifies a title by `imdb`, `tmdb` or `tvdb` as strings, plus `anidb` for
anime. An event with none of them, an episode with no season and episode number,
or an episode numbered by TVDB order is not sent, because Floppy never matches by
title.

The proposed tracker does not send a manual **Mark Watched** yet. It is not
playback, so the table above does not cover it. A client that adds it sends the
manual stop described in step 3; the exact bodies are in
`src/api/tests/test_nuviotv_manual_mark.py`.

What it does not do: send seconds (it has none), read history or lists back, or send ratings. The Nuvio and Floppy sides of those
are separate changes.

The exact bodies it sends are the fixtures in
`src/api/tests/test_nuviotv_scrobble_contract.py`:

```bash
SECRET=test-only scripts/test.sh api.tests.test_nuviotv_scrobble_contract
```

## Library source (reading saved titles)

NuvioTV lists a provider under Sources, Library Source only if its client can
read the user's saved titles. The server side of that already exists: Floppy's
saved titles are the entries with status Planning, and a client reads them with
the credential it was given.

```
GET /api/v1/media/?status=planning&limit=50&offset=0
GET /api/v1/media/movie/?status=planning
GET /api/v1/media/tv/?status=planning
```

The default tracking token carries `watchlist:read`, so no extra scope is
needed. Each row's `item` has `source`, `media_id` and `media_type`; `item.ids`
adds `imdb` and `tvdb` when Floppy has resolved them. For `source: "tmdb"`,
`media_id` is the TMDB id. Follow `pagination.next` until it is `null`.

What a client should do with what it gets:

- Place only titles whose `source` it can map (`tmdb` for movies and TV).
  Anything else (games, books, music, MAL anime) is a title it cannot place;
  skip it and say so rather than guessing by title.
- Treat it as a full read. There is no change feed for saved titles (the
  `sync/changes` feed carries watched state only), so re-read the list rather
  than expecting deltas.
- Do not merge it with Floppy custom lists or Discover rows. They are separate
  endpoints and separate capabilities.

The read is pinned by `api.tests.test_nuvio_library_source`:

```bash
SECRET=test-only scripts/test.sh api.tests.test_nuvio_library_source
```

The NuvioTV side (binding a library provider so Floppy appears in the Library
Source list) is client work and is not part of this server contract.

## Errors

| Status | Meaning | What to do |
|---|---|---|
| `400` | Malformed request | Fix the request; do not retry unchanged |
| `403` | Credential missing, invalid, revoked, expired, **or** lacking the scope | See below |
| `404` | Unknown or unresolvable item | Record as unresolved; do not retry |
| `409` | `idempotency_conflict` or `cursor_expired` | See steps 4 and 6 |

**Known limitation.** Floppy returns `403` for both "your credential is dead"
and "your credential lacks this scope", so status alone cannot tell them apart.
DRF downgrades authentication failures to `403` unless the authenticator sends a
challenge, and Floppy's authentication matrix asserts `403` across every
protected endpoint, so changing it is an API break that has not been made.

Until it is: on a `403`, re-check the credential against a low-scope endpoint
such as `GET /api/v1/sync/connections/`. If that also returns `403`, the
credential is dead and the user should reconnect. If it succeeds, the original
call needed a scope the token does not carry.

## What add-ons cannot do

| Feature | Add-on is enough | Needs native client work |
|---|---|---|
| Browsing Floppy lists and Discover rows | Yes | No |
| Catalog metadata | Yes | No |
| Saved-item sync | No | Yes (read: see Library source) |
| Watched state sync | No | Yes |
| Resume progress sync | No | Yes |
| Reconciliation | No | Yes |

The Stremio-compatible add-on covers the first two through a revocable install
credential. Everything else needs a client that speaks this API.

One direction is the exception. The add-on also declares Stremio's `player` and
`library` resources, so a Stremio client **reports playback into Floppy** —
positions, durations, and watched flags — with no client work at all. The table
above describes the other direction, Floppy's state reaching a client, and that
is still native-client work. A Stremio client therefore writes history and
resume positions without speaking this API, but cannot read them back.

## Compatibility matrices

`server ready` means Floppy's own conformance suite passes. It is not a claim
about any client. A client row becomes `verified` only after that build passed
the suite end to end.

### Nuvio TV — https://github.com/NuvioMedia/NuvioTV

| Floppy revision | Client revision | Result | Date |
|---|---|---|---|
| `efbb545` | dannyvfilms/NuvioTV `13f4bb3` (unmerged fork branch, proposed upstream as NuvioTV#3811) | Scrobble only. Client code ran against a live Floppy (connection check, start, early stop, finished stop) and the JVM unit tests pass. Not `verified`: the Android build was not compiled and nothing ran on a device. | 2026-10-01 |

### Nuvio Mobile — https://github.com/NuvioMedia/NuvioMobile

Kotlin Multiplatform. Target the KMP implementation; the former React Native
architecture is not the integration surface. Confirm the architecture at the
revision you test before writing platform guidance.

| Floppy revision | Client revision | Result | Date |
|---|---|---|---|
| — | — | Not yet tested | — |

Both matrices use the same fixtures. A divergent fixture set between the two
targets is a defect in this kit, not a platform difference.
