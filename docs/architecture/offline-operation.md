# Offline and air-gapped operation

## Support contract

Floppy treats metadata that reached its database successfully as usable local data. A provider outage, blocked provider, failed refresh, failed task queue, or expired freshness window must not remove that data.

This contract covers three states:

1. **Provider unavailable:** The Floppy server and database work, but one or more metadata providers do not.
2. **Provider access disabled:** The operator runs Floppy in offline or restricted network mode.
3. **Floppy server unavailable:** The installed PWA cannot reach the Floppy server.

The first two states keep the user's locally stored library and metadata available. The third state shows a public offline status page. It does not expose private account data from the browser cache.

Private data access while the Floppy server itself is down remains a separate phase. It requires an encrypted client database, scoped device credentials, queued writes, conflict handling, and device-revocation cleanup. Floppy must not approximate that feature by caching authenticated HTML.

## Data that remains available

Floppy has two durable local sources:

- `Item` stores normalized metadata that the application uses for lists, history, imports, exports, search, and API records.
- `MetadataSnapshot` stores the complete last-known-good provider payload and its refresh state.

The complete snapshot can contain information that does not fit the normalized `Item` fields, such as recommendations, people, studios, external identifiers, provider details, seasons, and other related data.

A refresh state is stored separately from the payload. A failed or blocked refresh can therefore record the failure without replacing the last usable payload.

### Identity variants

A snapshot key includes:

- Provider source.
- Media type.
- Provider media identifier.
- Language.
- Season numbers.
- Episode number.
- Edition identifier.

The key is a SHA-256 digest of those normalized values. It does not contain a request URL, query string, token, credential, or response body.

## Metadata read modes

Set `FLOPPY_METADATA_READ_MODE` on every web and worker process.

| Mode | Behavior |
| --- | --- |
| `local-first` | Return a fresh local snapshot immediately. Return a stale local snapshot immediately and follow the configured refresh behavior. Use the provider only when no local copy exists, the local copy is incomplete, or the caller requests a refresh. This is the default. |
| `network-first` | Attempt a provider refresh when the local copy is stale. Return the local copy when the provider fails. |
| `local-only` | Never call a provider for metadata reads. Return local data or a clear no-local-copy error. |

Example:

```env
FLOPPY_METADATA_READ_MODE=local-first
```

A manual or scheduled refresh uses an explicit refresh flag. It bypasses the freshness check. A manual blocking refresh also bypasses the automatic failure retry delay, but it does not remove the existing local payload if the refresh fails.

## Refresh modes

Set `FLOPPY_METADATA_REFRESH_MODE`.

| Mode | Behavior |
| --- | --- |
| `background` | Return stale local data immediately and queue one refresh. This is the default. |
| `blocking` | Wait for a provider refresh when the data is stale or incomplete. Return local data if the refresh fails. |
| `manual` | Return stale local data without starting an automatic refresh. Explicit API, web, or task refreshes still work. |

Example for a desktop build that must remain responsive:

```env
FLOPPY_METADATA_READ_MODE=local-first
FLOPPY_METADATA_REFRESH_MODE=background
```

Example for an isolated installation that never contacts providers:

```env
FLOPPY_NETWORK_MODE=offline
FLOPPY_METADATA_READ_MODE=local-only
FLOPPY_METADATA_REFRESH_MODE=manual
```

### Refresh leases

A queued refresh obtains a lease for one snapshot identity. Another automatic request does not queue the same refresh while that lease is active.

Configure the lease:

```env
FLOPPY_METADATA_REFRESH_LEASE_SECONDS=120
```

If the task queue is unavailable, Floppy records the queue failure and still returns the local payload.

### Failure retry delay

Automatic refreshes wait after a failed provider or queue attempt. This prevents repeated provider calls and repeated task failures during an outage.

```env
FLOPPY_METADATA_FAILURE_RETRY_SECONDS=300
```

The delay does not block an explicit blocking refresh requested by a user or API client.

## Freshness controls

The default freshness window is one day:

```env
FLOPPY_METADATA_FRESH_SECONDS=86400
```

Provider and provider/media-type overrides use exact identifiers:

```env
FLOPPY_METADATA_FRESH_OVERRIDES=tmdb=21600,tmdb/tv=3600,openlibrary=604800
```

Resolution order:

1. `provider/media_type`.
2. `provider`.
3. `*`.
4. `FLOPPY_METADATA_FRESH_SECONDS`.

Invalid selectors or values fail closed at the metadata boundary. Floppy does not reinterpret a URL, host suffix, or partial provider name as a provider identifier.

A freshness window controls when Floppy may refresh. It does not delete the payload.

## Persistence controls

Set `FLOPPY_METADATA_PERSIST_MODE`.

| Mode | Behavior |
| --- | --- |
| `all` | Persist every successful metadata payload that passes the safety limits. This is the default. |
| `tracked` | Persist complete provider payloads only when a matching `Item` exists. Imported and tracked Item data is still durable. |
| `off` | Do not create or update complete snapshots. Normalized Item data remains local, but provider-only details are not guaranteed after a cache loss. |

Recommended setting:

```env
FLOPPY_METADATA_PERSIST_MODE=all
```

`off` reduces storage, but it weakens the offline guarantee. It is not suitable when complete local metadata is required.

### Payload merge mode

Set `FLOPPY_METADATA_MERGE_MODE`.

| Mode | Behavior |
| --- | --- |
| `preserve` | A successful refresh updates known values but does not replace a non-empty stored value with an empty placeholder. This is the default. |
| `replace` | A successful provider refresh replaces the previous provider payload. |

```env
FLOPPY_METADATA_MERGE_MODE=preserve
```

Import and local Item updates always preserve provider-only snapshot fields. For example, editing a local title must not remove stored recommendations or cast data.

## Imports and local edits

Every Item save that changes metadata synchronizes its durable local snapshot.

This covers:

- Imports.
- API-created tracked items.
- Manual metadata changes.
- Image changes.
- Provider refreshes that update normalized fields.
- Scheduled metadata backfills.

An import does not need to wait for a provider before its stored title, image, synopsis, genres, identifiers, progress limits, and other Item fields become available.

A provider refresh writes the complete snapshot atomically. After that succeeds, Floppy updates the matching normalized Item fields immediately. The secondary page fragment is no longer the only path that persists refreshed metadata.

## Refresh outcomes

### Refresh succeeds

1. Floppy receives a provider payload.
2. It converts the payload to JSON-safe data.
3. It removes secret-shaped fields.
4. It applies the configured last-known-good merge rule.
5. It writes the complete snapshot atomically.
6. It clears the previous failure state.
7. It updates matching Item metadata.
8. It returns the refreshed payload.

### Refresh fails

1. Floppy keeps the existing payload unchanged.
2. It records a safe failure code, attempt time, failure time, and consecutive failure count.
3. It returns the local payload.
4. It marks the response as stale and failed.

Logs and API state do not contain the provider URL, query string, token, request body, response body, or raw exception message.

### Provider access is blocked

Floppy records a blocked state and returns the local payload. It does not attempt a socket connection.

### No local copy exists

Floppy may call the provider when policy allows it. In `local-only` mode, or when provider access is blocked, it returns a clear no-local-copy error. It does not invent metadata.

## Payload safety and storage limits

Before Floppy stores a complete payload, it:

- Converts supported Python values to JSON.
- Removes `_floppy_cache` state from the payload.
- Removes keys that look like passwords, secrets, cookies, authorization headers, signatures, API keys, access tokens, or refresh tokens.
- Limits nested depth.
- Limits the number of values.
- Limits the encoded byte size.

Configure the byte limit:

```env
FLOPPY_METADATA_MAX_PAYLOAD_BYTES=2097152
```

The accepted range is 1 KiB to 100 MiB. A rejected payload can still be returned for the current request when it came from a successful provider call, but Floppy marks it as `live-not-persisted`. It does not replace the prior snapshot.

## Retention

Tracked Item snapshots are retained because they support locally stored user data.

Untracked snapshots can be retained forever or removed after a configured period:

```env
FLOPPY_METADATA_RETENTION_DAYS=0
```

`0` means no age-based deletion. A positive number applies only to snapshots that no longer match an Item.

The `Prune metadata snapshots` task deletes records in bounded batches. It does not delete a snapshot that still matches a durable Item.

## Response state

Metadata returned through the shared service contains `_floppy_cache`. The authenticated cache API returns the same information as a separate `cache` object.

Important fields:

| Field | Meaning |
| --- | --- |
| `state` | `current`, `local`, `local-only`, `refreshing`, `stale`, `failed-local-copy`, `blocked-local-copy`, or `live-not-persisted`. |
| `source` | `snapshot`, `item`, or `provider`. |
| `stale` | The local copy is outside its freshness window or lacks data that this route normally needs. |
| `refresh_queued` | Floppy queued a background refresh for this identity. |
| `fetched_at` | The last successful provider fetch time, when available. |
| `last_attempted_at` | The last refresh attempt or queue claim time. |
| `last_failure_at` | The last failed or blocked attempt time. |
| `failure_code` | A bounded type or policy code. It does not include the raw provider error. |
| `consecutive_failures` | The number of consecutive failed or blocked attempts. |
| `policy` | Non-secret effective metadata settings for this identity. |

User interfaces should show one calm status near the affected metadata. They should not display repeated notifications for the same outage. The state must not rely on color alone.

Suggested labels:

- **Saved locally** for a local-only copy.
- **Updating** for an active queued refresh.
- **Update unavailable — showing saved data** for a failed or blocked refresh.
- **Saved data may be out of date** for stale manual mode.

Keep one primary refresh action. Do not hide the local data behind the status message.

## Authenticated metadata cache API

The API is mounted under the existing `/api/v1/` base. A reverse proxy or desktop package can place that base under another application path without changing these route definitions.

### Read effective policy

```http
GET /api/v1/metadata/cache/policy/
X-API-Key: <user token>
```

The response includes:

- Metadata read, refresh, persistence, merge, freshness, retry, lease, size, and retention settings.
- Network mode and the restricted provider allowlist when applicable.
- Supported variant query parameters.
- Supported explicit refresh modes.

### Read guaranteed local metadata

```http
GET /api/v1/metadata/cache/movie/tmdb/550/
X-API-Key: <user token>
```

This GET route never calls a provider. It returns only an Item that the authenticated user tracks.

Optional query parameters:

```text
season_number=1
season_number=2
episode_number=4
language=pt-BR
edition_id=example-edition
```

The response separates the local metadata from cache state:

```json
{
  "metadata": {
    "media_id": "550",
    "source": "tmdb",
    "media_type": "movie",
    "title": "Example"
  },
  "cache": {
    "state": "current",
    "source": "snapshot",
    "stale": false,
    "refresh_queued": false
  }
}
```

### Queue a refresh

```http
POST /api/v1/metadata/cache/movie/tmdb/550/
X-API-Key: <user token>
Content-Type: application/json

{"mode": "queue"}
```

The response returns `202 Accepted` when it queues a refresh. It includes the local metadata so the client does not need to blank the page while it waits.

### Wait for a refresh

```http
POST /api/v1/metadata/cache/movie/tmdb/550/
X-API-Key: <user token>
Content-Type: application/json

{"mode": "wait"}
```

The request attempts the refresh immediately. If it fails and a local copy exists, the response still contains the local copy and its failed or blocked state.

### Ownership

The cache API requires authentication. It returns metadata only when the caller tracks the matching Item. A user cannot use a known snapshot key or provider identifier to read another user's untracked local item.

## Provider network modes

Set `FLOPPY_NETWORK_MODE` on every web and worker process.

| Mode | Behavior |
| --- | --- |
| `online` | Allow all metadata providers. This is the default. |
| `offline` | Block every request that uses the shared metadata-provider HTTP boundary. |
| `restricted` | Allow only exact provider identifiers in `FLOPPY_NETWORK_ALLOWLIST`. |

Example offline configuration:

```env
FLOPPY_NETWORK_MODE=offline
```

Example restricted configuration:

```env
FLOPPY_NETWORK_MODE=restricted
FLOPPY_NETWORK_ALLOWLIST=tmdb,tvdb
```

The allowlist is case-insensitive. It uses exact provider identifiers. It does not accept URLs, host suffixes, or partial matches.

The legacy `YAMTRACK_` names remain accepted when a corresponding `FLOPPY_` setting is not present.

Invalid restrictive configuration fails before the HTTP session runs.

## Direct integrations and imports

The shared provider boundary covers clients that use `app.providers.services.api_request`. Some RSS readers and integration-specific clients make direct HTTP calls outside that boundary.

Strict air-gapped operators must disable integrations that require external services until each direct client uses the same egress policy. Issue #778 tracks that remaining process-wide no-egress work.

This limit does not prevent the local library, imported Item data, complete snapshots, history, lists, collections, statistics built from local data, or the authenticated cache API from working.

## PWA behavior

The service worker derives the application root from its registration scope. The same files support:

- `https://floppy.example/`
- `https://floppy.example/floppy/`

The manifest uses relative URLs for its identity, scope, start page, icons, and shortcuts.

### Browser cache boundary

The service worker may cache only:

- The public offline status page.
- Same-origin files under the application's static-file path.
- The public manifest and icons.

It does not cache:

- Authenticated HTML.
- Navigation responses.
- API responses.
- HTMX fragments.
- Write requests.
- Cross-origin responses.
- Opaque responses.

This rule prevents one account from reading another account's rendered data through a shared browser cache.

### Floppy server unavailable

When navigation cannot reach the Floppy server, the installed PWA shows a self-contained public status page with one action: **Try again**.

The page supports keyboard focus, narrow screens, zoom, dark mode, reduced motion, and a restrictive Content Security Policy. It does not auto-refresh or create notification noise.

## FloppyDesktop and other app builds

The implementation uses Django, the existing database, the existing task queue, and standard browser APIs. It does not require a cloud service, CDN, browser extension, or desktop-only data path.

A packaged build must pass the same settings to all of these processes:

- Web process.
- Interactive worker.
- Background worker.
- Scheduled task process.

Recommended desktop defaults:

```env
FLOPPY_METADATA_READ_MODE=local-first
FLOPPY_METADATA_REFRESH_MODE=background
FLOPPY_METADATA_PERSIST_MODE=all
FLOPPY_METADATA_MERGE_MODE=preserve
FLOPPY_METADATA_FRESH_SECONDS=86400
FLOPPY_METADATA_FAILURE_RETRY_SECONDS=300
FLOPPY_METADATA_REFRESH_LEASE_SECONDS=120
FLOPPY_METADATA_RETENTION_DAYS=0
```

A downstream release must validate:

- Database migration `0155_metadata_snapshot`.
- Application origin and service-worker scope.
- Static paths in development and packaged builds.
- API base-path resolution.
- Environment propagation to every worker.
- Upgrade from the earlier `floppy-v2` browser cache.
- Existing database upgrade with pre-snapshot Items.
- Import while providers are offline.
- Queue unavailable and provider unavailable states.
- Logout and account switching.
- Root and nested application paths.

## Operator inspection and recovery

When Django admin is enabled, `MetadataSnapshot` has a dedicated operational view. It shows identity, state, origin, timestamps, failure count, and payload size.

The admin form:

- Does not show the stored payload.
- Does not permit new snapshot creation.
- Does not permit field edits.
- Allows an authorized operator to remove a corrupt or unwanted record.

Removing a snapshot does not remove the normalized Item. The next local read can rebuild a local snapshot from that Item. A later provider refresh can rebuild the complete snapshot.

## Security invariants

- A denied shared-provider request makes zero HTTP calls.
- A failed, blocked, rejected, or unqueued refresh does not replace a usable payload.
- Snapshot identity contains no request URL or credential.
- Secret-shaped payload keys are removed before persistence.
- Payload size, depth, and value count are bounded.
- Snapshot writes are atomic.
- Background refreshes use an identity lease.
- Automatic failures use a retry delay.
- Explicit refreshes do not silently become automatic stale reads.
- The authenticated cache API enforces tracked-item ownership.
- The service worker never stores private dynamic responses.
- Logs and cache state do not include provider response bodies or raw secrets.

## Validation checklist

### Database and migration

- Run migrations on a new database.
- Upgrade a database with existing Items.
- Confirm existing Items remain readable before a provider call.
- Confirm a local snapshot is created on the next metadata read or Item metadata save.
- Confirm migration rollback removes only the snapshot table.

### Local-first reads

- Read a fresh snapshot and confirm zero provider calls.
- Read a stale snapshot in background mode and confirm the local payload returns before the task finishes.
- Read a stale snapshot in manual mode and confirm no task starts.
- Read in local-only and offline network modes and confirm zero provider calls.

### Refresh and failure

- Complete a successful blocking refresh.
- Fail a blocking refresh and confirm the old payload is unchanged.
- Return a partial provider payload and confirm stored non-empty fields remain.
- Stop the task broker and confirm the local payload still returns.
- Trigger several requests and confirm only one background task holds the active lease.
- Confirm an explicit blocking refresh bypasses automatic retry delay.

### Import and local edit

- Import an item while providers are unavailable.
- Confirm its local metadata is immediately available.
- Edit a local field and confirm provider-only snapshot data remains.
- Refresh successfully and confirm normalized Item fields update immediately.

### API

- Call the policy route with and without authentication.
- Read local metadata with zero provider calls.
- Confirm another user receives `404` for an unowned Item.
- Queue a refresh and confirm the response still contains local metadata.
- Wait for a failed refresh and confirm the response still contains local metadata.
- Test language, season, episode, and edition variants.
- Test the API at `/` and under a nested application path.

### Storage safety

- Submit a secret-shaped key and confirm it is not persisted.
- Submit an oversized, over-deep, and over-count payload.
- Confirm each rejection keeps the previous payload.
- Prune expired untracked snapshots and confirm tracked snapshots remain.

### PWA and accessibility

- Install at `/` and `/floppy/`.
- Load the app once while the server is available.
- Stop the Floppy server.
- Confirm the public offline page appears.
- Confirm **Try again** receives visible keyboard focus.
- Inspect Cache Storage and confirm no authenticated document or API response exists.
- Test 320 px and 375 px widths, 200% zoom, keyboard-only input, dark mode, and reduced motion.
- Confirm stale, failed, blocked, and refreshing states do not rely on color alone.
- Confirm repeated failures do not create repeated notification noise.

## Recovery

### Restore provider access

1. Set `FLOPPY_NETWORK_MODE=online` or update the restricted allowlist.
2. Restart every web and worker process.
3. Call the cache policy API and confirm the effective settings.
4. Request a blocking refresh for one known tracked item.
5. Confirm the cache state becomes `current`.
6. Re-enable scheduled refresh work only after configuration errors are clear.

### Recover one bad snapshot

1. Identify the snapshot by source, media type, media ID, and variant.
2. Remove it through the admin or Django shell.
3. Read the Item locally to rebuild normalized metadata.
4. Request a provider refresh when network policy permits it.

### Disable complete snapshot persistence

Set:

```env
FLOPPY_METADATA_PERSIST_MODE=off
```

This is reversible, but complete provider-only metadata will no longer be guaranteed after transient provider caches expire. Keep `all` for the strongest offline behavior.

## Post-mortem

### What happened

Floppy stored normalized Item metadata, but detail and API paths often contacted a provider before they read those fields. A provider outage could therefore delay or break a page for data that already existed locally.

Complete provider responses also lived mainly in transient cache backends. A successful detail response could be available in Redis but not yet persisted to Item until a later secondary fragment ran. Imports and scheduled refreshes followed different persistence paths.

The first service worker correctly avoided private dynamic caching, but it used root-only paths and had no application fallback when the Floppy server was unavailable.

### Why it happened

Local Item fields, transient provider caches, complete metadata payloads, refresh tasks, imports, API responses, PWA installation, and downstream packaging did not share one explicit state contract.

The code could answer “did the provider call work?” but could not answer consistently:

- What is the last usable local payload?
- Is it fresh?
- Is a refresh running?
- Did the last attempt fail or get blocked?
- Should this caller wait, queue, or use local data?
- Can an API or packaged app inspect that state safely?

### Controls added

- A durable complete metadata snapshot with separate payload and refresh state.
- One shared local-first read boundary for web, API, worker, and downstream callers.
- Configurable read, refresh, persistence, merge, freshness, retry, lease, size, and retention rules.
- Immediate Item synchronization after provider success.
- Import and local-edit synchronization into durable snapshots.
- Last-known-good merge behavior.
- Atomic writes and bounded safe payload storage.
- Authenticated local-read and explicit-refresh API routes.
- Refresh status suitable for accessible, low-noise interfaces.
- A dedicated safe admin view.
- Base-path-safe PWA installation and a public offline shell.
- Tests for zero-call local reads, failed refresh retention, partial refresh merging, queue failure, ownership, and configuration validation.

### Remaining work

- Route every direct RSS and integration client through a defined process-wide egress policy.
- Add encrypted private-data storage and a conflict-safe write outbox for use while the Floppy server is unavailable.
- Complete the FloppyDesktop packaging, migration, base-path, and upgrade matrix.
- Add product UI indicators using the response-state labels in this document.
- Add a scheduled deployment default for snapshot pruning when finite retention is enabled.

Track these items in #778 and attach narrower follow-up issues where ownership or release timing differs.
