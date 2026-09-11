# Floppy tracking client guide

What a third-party client (Nuvio TV, Nuvio Mobile, Kodi, a scrobbler) needs to
implement two-way tracking against Floppy, without reading Floppy's source.

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

The user creates a token in **Settings → Integrations → App tokens**, names it
after the device, and pastes it into the client. The secret is shown once.

Send it any of three ways:

```
Authorization: Bearer flp_xxx
Authorization: Token flp_xxx
X-API-Key: flp_xxx
```

A token minted with the default preset carries exactly what a tracking client
needs:

```
scrobble:write  progress:read  progress:write
watchlist:read  watchlist:write  catalog:read  sync:read
```

It cannot reach lists, music, podcasts, imports, exports, user settings, or
metadata writes. Ask the user to tick extra permissions if you need them; do not
ask for a broader token "just in case".

Then call `GET /api/v1/sync/connections/` and keep each `origin_key`. You need
it in step 5, and without it your position can never be recorded.

## 2. Initial merge

Floppy merges non-conflicting state and preserves conflicting local values for
review. It never silently overwrites a user's existing library.

Start from `cursor=0`, which is always valid. Read `oldest_sequence` and
`newest_sequence` from any feed response to know what the server still holds.

## 3. Playback updates

| Purpose | Call |
|---|---|
| Resume position | `PUT /api/v1/playback/progress/` |
| Playback events | `POST /api/v1/scrobble/` |
| Watched state | `PUT /api/v1/media/{type}/{source}/{id}/watched-state/` |

Progress does not create history. Completion applies to the identified movie or
episode only, and a retry never becomes a rewatch.

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
| Saved-item sync | No | Yes |
| Watched state sync | No | Yes |
| Resume progress sync | No | Yes |
| Reconciliation | No | Yes |

The Stremio-compatible add-on covers the first two through a revocable install
credential. Everything else needs a client that speaks this API.

## Compatibility matrices

`server ready` means Floppy's own conformance suite passes. It is not a claim
about any client. A client row becomes `verified` only after that build passed
the suite end to end.

### Nuvio TV — https://github.com/NuvioMedia/NuvioTV

| Floppy revision | Client revision | Result | Date |
|---|---|---|---|
| — | — | Not yet tested | — |

### Nuvio Mobile — https://github.com/NuvioMedia/NuvioMobile

Kotlin Multiplatform. Target the KMP implementation; the former React Native
architecture is not the integration surface. Confirm the architecture at the
revision you test before writing platform guidance.

| Floppy revision | Client revision | Result | Date |
|---|---|---|---|
| — | — | Not yet tested | — |

Both matrices use the same fixtures. A divergent fixture set between the two
targets is a defect in this kit, not a platform difference.
