# Xbox Integration (OpenXBL)

Reference for the Xbox game importer: how a user connects it, how many OpenXBL
requests a sync costs, what data is stored and logged on each side, and exactly
what disconnecting does and does not do.

Xbox Live has no public API. Floppy talks to **OpenXBL** (`https://xbl.io`), a
third-party gateway, using a per-user API key the user pastes in. There is no
OAuth flow and no instance-wide key: every user brings their own.

Code: `src/integrations/xbox_api.py` (client),
`src/integrations/imports/xbox.py` (importer),
`src/integrations/views.py:1912` (connect) and `:1949` (disconnect),
`src/integrations/models.py:768` (`XboxAccount`).

External facts below were checked against xbl.io on 2026-08-12 and are quoted;
OpenXBL can change them without notice.

## Setup

1. The user signs in at [xbl.io](https://xbl.io) with their Microsoft account.
   OpenXBL also requires phone verification before it issues a key
   ("Sign up at xbl.io, verify your phone number, and grab your key from the
   dashboard" — [xbl.io/getting-started](https://xbl.io/getting-started)).
2. They copy the API key from the OpenXBL dashboard.
3. In Floppy: **Settings → Import → Xbox**, paste the key, press **Connect Xbox**
   (`POST /import/xbox/connect`).

What connect does, in order (`xbox_connect` in `src/integrations/views.py:1912`):

- Calls `GET /api/v2/account` immediately to validate the key. A bad key fails
  here with a message, and nothing is stored.
- Stores an `XboxAccount` row: the key Fernet-encrypted, plus the returned
  `xuid` and `gamertag`, with `connection_broken=False`.
- Starts an import right away, using whatever frequency/time/mode the shared
  import modal has selected — one-off `Import from Xbox`, or a recurring
  `Import from Xbox (Recurring)` schedule at the chosen time
  (`_start_xbox_import` in `src/integrations/views.py:1893`).

Recurring schedules support `daily` or `2days` only, defaulting to 04:00 local
(`XBOX_RECURRING_FREQUENCIES` in `src/integrations/views.py:1761`).

Import modes: only `new` and `overwrite` are meaningful. Xbox reports a *played*
library, so `watchlist` and `update_collection` have nothing to act on and are
rejected up front rather than silently treated as `new`
(`SUPPORTED_MODES` in `src/integrations/imports/xbox.py:40`).

### What "owned" means here

Xbox exposes no purchase library. Floppy approximates it with the union of
`titleHistory` and the per-player achievement list — everything the account has
launched. Non-game titles (Netflix, Twitch, the Store) are dropped before any
IGDB lookup, and not every title publishes `MinutesPlayed`, so some games import
with unknown playtime rather than zero.

## Rate limits and request budget

### OpenXBL's limits (per API key)

From [xbl.io/pricing](https://xbl.io/pricing):

| Plan | Price | Rate limit |
| --- | --- | --- |
| Free | $0/forever | 150 requests/hour |
| Small | $5/month | 500 requests/hour |
| Medium | $15/month | 2,500 requests/hour |
| Large | $35/month | 5,000 requests/hour |
| Enterprise | Custom | Custom |

Exceeding the limit returns HTTP 429; OpenXBL also returns rate-limit detail in
response headers (`X-RateLimit-Remaining`).

### What one sync actually costs

Per import (`XboxImporter.import_data` in `src/integrations/imports/xbox.py:192`):

- 0 requests to resolve the XUID — it is stored at connect time. Only a blank
  `xuid` costs one `GET /account`.
- 2 requests for the library: `GET /achievements/player/{xuid}` and
  `GET /player/titleHistory/{xuid}`.
- `ceil(titles / 100)` requests for playtime: `POST /player/stats` batched at
  `STATS_BATCH_SIZE = 100` (`src/integrations/xbox_api.py:35`).

A 300-game library is **5 OpenXBL requests per sync**, plus 1 at connect. Even a
daily schedule on a large library sits far under the free tier's 150/hour. The
free plan is the right recommendation; nothing in Floppy's usage justifies a
paid tier.

The slow, expensive part of an Xbox import is IGDB, not OpenXBL: each unmatched
title costs up to three IGDB searches
(`_search_names` in `src/integrations/imports/xbox.py:88`) against a
3 req/sec budget.

### Floppy's own throttle

`https://xbl.io/api` is mounted with `LimiterAdapter(per_hour=120)`
(`src/app/providers/services.py:295`) — deliberate
headroom under the free tier's 150 so connect calls and retries can't tip a user
over. Two caveats worth knowing before trusting it as a guarantee:

- **It is per process, not per key.** The per-host adapters are in-memory, one
  bucket per worker process (`src/app/providers/services.py:245`).
  Multiple Celery workers each carry their own 120/hour allowance, so the local
  ceiling does not strictly bound one key's hourly usage.
- **It is per host, not per user.** All users' xbl.io traffic shares that single
  bucket, while OpenXBL counts per key. On a busy multi-user instance the local
  limiter can throttle imports whose keys still have quota to spare.

Given the real request volume above, neither caveat bites in practice.

### When a 429 does happen

`api_request` retries up to 3 times, sleeping `Retry-After + 3s` clamped to
1–60 seconds (5s when the header is absent or unparseable)
(`src/app/providers/services.py:499`). If it still
fails, the importer marks the account broken with *"OpenXBL rate limit exceeded.
Please try again later."*

Note the user-visible consequence: `is_connected` is `api_key AND NOT
connection_broken`, so a transient rate-limit failure flips the Xbox badge to
**Disconnected** and surfaces the error in the modal even though the key is
fine. The stored key is untouched, the recurring schedule is not disabled, and
the next successful sync clears both flags
(`_mark_synced` in `src/integrations/imports/xbox.py:305`) — so it self-heals
on the next run without user action.

## Privacy and request-log retention

### What Floppy stores

`XboxAccount` in `src/integrations/models.py:768` holds:

| Field | Contents |
| --- | --- |
| `api_key` | The OpenXBL key, Fernet-encrypted |
| `xuid`, `gamertag` | From `GET /account` at connect time |
| `last_sync_at` | Last successful sync |
| `connection_broken`, `last_error_message` | Failure state shown in the import modal |

The Fernet key is derived from Django's `SECRET_KEY`
(SHA-256 → urlsafe base64, `src/integrations/imports/helpers.py:534`).
**Rotating `SECRET` makes every stored key undecryptable**: the next sync fails
with "Stored credentials could not be decrypted…", marks the account broken, and
the user must paste the key again. It does not corrupt anything else.

### What leaves the instance

- To OpenXBL: the API key in the `X-Authorization` header, and the XUID in the
  request path.
- To IGDB: title names only, for matching. No Xbox identifiers, no XUID.

### Keeping the key out of logs and the UI

`last_error_message` is rendered on the import page and persisted until the next
successful sync, so what lands there is constructed rather than stringified:

- HTTP failures are mapped to a message chosen from the **status code alone**
  (`_http_error_message` in `src/integrations/xbox_api.py:78`) — the raw
  `HTTPError` string would embed the request URL and response body.
- Anything unexpected is reduced to `TypeName(status=…)` by `exception_summary`.
- Whatever remains is run through `redact_secrets` and capped at 500 characters
  (`_safe_message` in `src/integrations/imports/xbox.py:80`).

One limitation to be aware of when changing this code: `redact_secrets` matches
parameter names like `api_key` and `token`, but **not** `x-authorization`
(`src/app/log_safety.py:18`). The key stays out of
logs because no code path formats a raw exception, request, or header — not
because the scrubber would catch it. Preserve that discipline.

### What OpenXBL stores and logs

From [xbl.io/agreement](https://xbl.io/agreement) (Terms of Service & Privacy
Policy):

- Stores "Xbox Live profile information (gamertag, XUID, avatar)", "Email and
  phone number for account verification", and "Payment information (processed
  securely by Stripe)".
- **"Request logs are retained for billing and debugging purposes."** No
  retention period is published. "Request logs" is listed as a feature on every
  plan including Free, and the logs are visible in the OpenXBL console.
- "We do not sell your personal data."
- "You may request deletion of your account and associated data at any time" —
  by contacting OpenXBL support.
- "Your API keys are for your use only and should not be shared"; sharing or
  reselling access and circumventing rate limits are prohibited.

Because the title and stats endpoints are keyed by XUID in the path, OpenXBL's
request logs necessarily record which XUID was queried and when — i.e. a user's
sync schedule and library-fetch cadence are visible to OpenXBL for as long as it
keeps those logs. Floppy cannot shorten or delete them; only OpenXBL can.

There is no way to point the integration at a different gateway:
`XBOX_API_BASE_URL` in `src/integrations/xbox_api.py:28` is a constant, not a
setting. Self-hosting Floppy does not avoid the third party here.

## Disconnect behavior

`POST /import/xbox/disconnect` (`xbox_disconnect` in `src/integrations/views.py:1949`)
does exactly two things:

1. Deletes every `PeriodicTask` named `Import from Xbox (Recurring)` whose
   `kwargs` carry this user's `user_id` — matched on the exact id, tolerant of
   JSON quoting/spacing (`_plex_watchlist_task_filter` in `src/integrations/views.py:137`).
   Other users' Xbox schedules are untouched.
2. Deletes the user's `XboxAccount` row, and with it the encrypted key, XUID,
   gamertag, and sync state.

It explicitly does **not**:

- Delete imported games, playtime, history, or `Item` metadata. Everything
  already imported stays in the library and keeps its "Imported from Xbox" note.
- Revoke, delete, or notify anything at OpenXBL. The key remains valid on
  xbl.io. A user who wants it dead must regenerate or delete it in the OpenXBL
  console — worth saying out loud in any user-facing copy, since "Disconnect"
  reads like it revokes access.
- Cancel an import already queued or running. A queued sync that starts after
  the row is gone fails with "Connect Xbox before importing", and one already in
  flight fails when it tries to write its result — in both cases there is no
  account row left to record the failure on, only the import history entry.

### Reconnecting

Connect again with the same or a new key. `update_or_create` refreshes the key,
XUID, and gamertag and clears `connection_broken` / `last_error_message`, so a
broken connection is repaired by reconnecting rather than needing a reset.

Re-importing does **not** resurrect games the user deleted in Floppy: Xbox keeps
reporting a title forever once launched, so deleted media is checked and skipped
on every run (`src/integrations/imports/xbox.py:380`).

### Rotating the key at OpenXBL

Regenerating the key on xbl.io does not tell Floppy. The stored key starts
returning 401/402, the account is marked broken with "Invalid or expired OpenXBL
API key. Reconnect your Xbox account.", and the schedule keeps firing and
failing until the user pastes the new key.

### Deleting a Floppy user

`XboxAccount.user` is a `OneToOneField(on_delete=CASCADE)`, so the account row
goes with the user. The recurring `PeriodicTask` does **not** — it holds
`user_id` in `kwargs`, not as a foreign key, and no delete-time cleanup exists.
An orphaned schedule keeps firing and raises `User.DoesNotExist` in
`import_media` (`src/integrations/tasks/_media_imports.py:67`) each time. It is
only cleared when a new schedule tries to claim the same name
(`_reclaim_xbox_schedule_name` in `src/integrations/views.py:1786`). Disconnect
before deleting a user, or remove the task in the beat admin.
