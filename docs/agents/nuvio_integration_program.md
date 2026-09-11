# Floppy–Nuvio Integration Programme

**Status:** Reviewed programme plan, reconciled against implementation
**Review date:** 2026-08-15
**Reconciliation date:** 2026-09-08 (delivery log current)
**Floppy baseline:** `17dc7c8e0eaae82603b98bd084abd0131ee6c1c1` (`latest`)
**Prior baseline:** `1bb6999a539679a27502c6514c3fdfec70f17091`
**Programme issue:** #532

This document is the single source of truth for the programme. `docs/plans/floppy-nuvio-unified-program-prd.md` describes a superseded single-PR delivery plan whose PR (#791) was withdrawn; do not implement from it.

## Decision

Build the programme in two release trains.

### Release A — Tracking interoperability

Two-way tracking that preserves existing local data:

- scoped client access;
- saved-library/watchlist membership;
- resume progress;
- exact watched state;
- explicit delete and reset;
- idempotent delivery;
- origin-loop prevention;
- ordered changes;
- reconciliation;
- diagnostics;
- conformance fixtures.

### Release B — Catalogs and shared media features

Start after Release A's server contract is stable:

- Floppy lists and Discover rows as read-only catalogs;
- normalized metadata projections;
- cache provenance and freshness;
- declarative add-on registration;
- portable Collection descriptors;
- optional writable list bindings;
- user metadata preferences and overrides.

Do not combine both trains in one release or one pull request.

## Delivery log

Recorded as work lands, so the ledger below stays a statement about the code
rather than about the plan. Two threads worked this programme in parallel;
"other thread" marks work this document did not drive.

| Item | State | Evidence |
|---|---|---|
| A0 scope enforcement | Done | `api/scopes.py`, `HasScope` global, coverage test over every routed view |
| A1 credential lifecycle | Done | Settings → Integrations → App tokens; `users/tests/views/test_integration_tokens.py` |
| A2 bindings | Done (other thread) | `SyncBinding`, `SyncCheckpoint`, `integrations/state/identity.py` |
| A3 receipts | Done | Binding-scoped receipts, retention task, `test_receipt_retention.py` |
| A4 ordered changes | Done | Watched-state feed (other thread) + `ProgressChange` and `/sync/progress-changes/` |
| A4 checkpoints/retention | Done | `integrations/state/checkpoints.py`, `_change_log.py` compaction |
| A5 watched state | Done (other thread) | `WatchState`, apply algorithm, outbound outbox |
| A6 origin and unresolved | Done (other thread) | `origin_key`, `UnresolvedExternalReference`, `StateConflict` |
| A7 diagnostics | Done | Connection position, lag, failed deliveries, unresolved counts |
| A7 dry-run preview | Blocked | `_reconcile_binding` is still a stub; provider enumeration has not landed, so a preview would preview nothing |
| A8 stabilization | Partial | Per-change gates plus a full app-label sweep and a SQLite upgrade replay from v26.9.3. **Postgres not run: no local server.** Container matrix not run |
| Adoption kit | Done | `docs/integrations/nuvio-client-guide.md` + `api.tests.test_nuvio_conformance` |
| B1 catalog grants | Done | `CatalogGrant`, revocable per-install add-on credential |
| B2 catalogs and meta | Done | `meta` resource, scoped to the user's own library |
| B3 metadata projections | Done | `app/services/metadata_projection.py`, `Item.metadata_refreshed_at` |
| B4 safe fetch | Done | `integrations/safe_fetch.py`, `docs/architecture/outbound-fetch.md` |
| B5 declarative add-ons | Done | `RemoteAddon`, `addon_manifest.py`, `addons.py` |
| B6 collections | Done | `lists/collection_descriptor.py` |
| B7 writable list bindings | Done | `IntegrationToken.writable_list_ids`, `CanWriteBoundList` |
| B8-B9 metadata overrides | **Not done — blocked by design** | See below |

### B9 is blocked, and the blocker is structural

Floppy writes a manual metadata edit onto the `Item` row itself. By the time a
value reaches a reader, "the provider said this" and "a person typed this" are
the same field, and nothing can tell them apart.

So B9 is not a projection problem, it is a write-path problem: custom metadata
has to be stored separately from provider metadata before anything can honour
the rule that a refresh must not overwrite a user's correction. That change
touches the manual-item metadata path across forms, views and the detail
builders, and it needs its own plan.

Until it lands, `metadata_projection` reports `authorship: "unseparated"` rather
than implying a split it cannot make, and **no code should use the projection to
decide whether a refresh may overwrite a field**.

### Corrections found while building

- Declared token scopes were never enforced: `HasScope` existed and no view
  used it. Fixed in A0.
- Scoped tokens could not be created outside a shell. Fixed in A1.
- Receipts were unique per user, so two devices minting the same client event
  id collided. Fixed in A3.
- `SyncCheckpoint` had no writer, so the change log had no safe watermark and
  could never be compacted. Fixed alongside A4.
- Adding the watched-state endpoints left them unmapped, and unmapped means
  denied: the change feed was unreachable by the clients it exists for. Caught
  by the A0 coverage test, fixed the same day.
- The tracking preset lacked `sync:read`, so a default token was denied the
  change feed. Fixed.
- The add-on install URL carried the account token in its path, so revoking it
  broke every integration at once. Fixed in B1.
- Nothing exposed a binding's `origin_key`, so no client could name itself and
  no checkpoint could ever be recorded. Fixed with the A7 diagnostics.

### Known deviations, recorded rather than hidden

- A replayed idempotent response loses datetime microseconds: the stored copy
  is re-encoded with `DjangoJSONEncoder`. Same result, lower precision.
- `403` covers both a dead credential and a missing scope. DRF downgrades
  authentication failures without a challenge, and `api.tests.test_authentication`
  asserts `403` across every protected endpoint, so correcting it to `401` is an
  API break that needs a deliberate decision. The client guide documents the
  workaround.

## Reconciliation ledger

Every capability below was checked against `latest` at the reconciliation baseline. `Implemented` means present with tests. `Partial` means present but short of the contract this programme requires. `Missing` means no production code exists.

### Release A

| Capability | State | Evidence |
|---|---|---|
| Scoped API credential record | Implemented | `IntegrationToken` (`src/integrations/models.py:1208`): digest-only storage, prefix, JSON scopes, expiry, revocation, `flp_` + 32-byte URL-safe secret. Migration `integrations/0024_integrationtoken.py`. |
| Credential authentication | Implemented | `src/api/authentication.py`: `BearerAuthentication`, `ListenBrainzTokenAuthentication`, `APIKeyAuthentication`; legacy `User.token` still accepted. Tests: `src/api/tests/test_fork_integration_tokens.py`. |
| **Scope enforcement** | **Partial — highest-priority gap** | `HasScope` exists in `src/api/authentication.py:98` but **no view declares `required_scope` and no view lists `HasScope` in `permission_classes`**. Scopes are stored and testable at model level only; in practice any valid token reaches every endpoint the user can reach. |
| Credential lifecycle management | Missing | `IntegrationToken.generate` has no view, URL, admin form, or management command. Only `^user/token/regenerate/?$` (legacy account token) is exposed. A user cannot create, list, name, or revoke a scoped token without a shell. |
| Constant-time digest compare | Partial | Lookup is a unique-index equality match on a SHA-256 digest, not a `compare_digest` on a secret. Acceptable in practice; record the reasoning rather than claim the control. |
| Credential last-use tracking | Missing | `last_used_at` is written by nothing (`src/integrations/models.py:1222`). Connection status and revocation triage have no data source. |
| Delivery receipts / idempotency | Implemented | `IntegrationEventReceipt` (`src/integrations/models.py:1277`) with `unique(user, client_event_id)`; `src/integrations/delivery.py` implements same-digest replay and changed-digest conflict. Tests: `src/api/tests/test_fork_delivery_receipts.py`. |
| Receipt coverage | Partial | Wired only into `fork_views_scrobble.py:294` and two paths in `fork_views_playback.py` (`:610`, `:698`). Tracking, list, and collection mutations accept no `Idempotency-Key`. |
| Receipt retention/compaction | Missing | No expiry field, no cleanup task, no metrics. Table grows without bound. |
| Receipt–state atomicity | Partial | `get_or_record_receipt` runs inside a transaction, but only for the two wired endpoints. Verify the fault matrix before claiming the guarantee. |
| Playback progress read/write | Implemented | `^playback/progress/?$`, `^playback/now-playing/?$`, per-media and per-season progress routes (`src/api/fork_urls.py`). Tests: `src/api/tests/test_fork_playback_progress.py`. |
| Scrobble ingest | Implemented | `^scrobble/?$` (`src/api/fork_views_scrobble.py`); start/pause non-durable, completed stop creates history. Baseline tests: `src/api/tests/test_fork_nuvio_baseline.py`. |
| Saved items / watched state / history API | Implemented | `^collection/`, `^history/`, per-episode `watch`/`drop`/`score`, bulk episodes (`src/api/fork_urls.py`); `src/api/tests/test_fork_tracking.py`. |
| Delta sync | Partial | `?updated_since=` on playback progress only (`src/api/fork_views_playback.py:322-565`, backed by `position_updated_at`, migration `app/0142`). Timestamp-ordered, not server-sequenced. No delta on saved items, watched state, or history. |
| Explicit deletes / tombstones | Partial (watched state) | `WatchStateChange.kind` carries an explicit `delete`, and absence is never inferred as one. Saved items and history still have no tombstones. |
| `SyncBinding` (user + external client/profile) | Implemented (watched state) | `integrations.models.SyncBinding`, migration `integrations/0037`. Approval is per-capability *and* per-direction, and both are required before a write. Minted `origin_key` (not derived, so narrowing `instance_key` cannot orphan changes already stamped with it). Profile change forces reapproval. `integrations/0038` maps Jellyfin's existing toggles across without broadening: `push_watched_enabled` defaults on but grants no write direction without a schedule. Tests: `src/integrations/tests/test_state_apply.py`. |
| `SyncCheckpoint` | Partial | `integrations.models.SyncCheckpoint` exists with `(binding, resource, direction)` uniqueness and a `provider_cursor` for native cursors. Not yet advanced by a real reconciliation pass — provider enumeration lands with each adapter. |
| Opaque cursor contract | Missing | No cursor issuance, validation, binding check, or expiry response. |
| Origin derivation / loop prevention | Implemented (watched state) | Every change carries `origin_kind`, `origin_key` and a `correlation_id`. `enqueue_deliveries` skips the binding a change came from, and echo detection correlates a durable delivery's read-back digest rather than a cache timeout. Tests: `src/integrations/tests/test_state_outbound.py`. |
| `UnresolvedExternalReference` | Implemented | `integrations.models.UnresolvedExternalReference`, deduplicated by `(binding, namespace, value, reason_code)` with an occurrence count and no secret-bearing payload. Written when an outbound delivery cannot resolve an item unambiguously. |
| Reconciliation preview / apply | Missing | `src/app/reconcile_state.py` is internal library-state repair, not client reconciliation. No dry run, no categorized diff, no diagnostics surface. |
| Conformance fixtures | Missing | `src/api/tests/test_fork_nuvio_baseline.py` is a five-test regression baseline, not a publishable kit. |
| Published contract artifacts | Implemented | `src/api/contracts/openapi.yaml`, `asyncapi.json`, `context.jsonld`; regeneration and validation commands in `AGENTS.md`. AsyncAPI channels: Plex, Jellyfin, Emby, Jellyseerr, Seerr, Kodi, Stremio subtitles, ListenBrainz. |

### Release B

| Capability | State | Evidence |
|---|---|---|
| Stremio-compatible manifest and catalog | Partial | `stremio-addon/<token>/manifest.json` and the catalog route exist (`src/integrations/urls.py:230-239`), backed by `src/integrations/stremio_catalog.py`. |
| Catalog grant model | Missing | The addon routes authenticate on the **legacy `User.token` in the URL path** (`src/integrations/views.py:4135`, `:4154`). There is no per-resource grant, no independent revocation, and revoking means regenerating the account token that other integrations use. This is the first thing Release B must fix. |
| Catalog `meta` resource | Missing | Manifest and catalog only; no metadata endpoint. |
| Normalized metadata projections | Partial | `src/api/fork_views_metadata.py` and `^metadata/items/<id>/` exist for internal use; no source attribution, freshness, or licence surface in the contract. |
| Declarative remote add-ons | Missing | No manifest schema, registry, safe-fetch boundary, or cache-status surface. |
| Portable Collection descriptors | Missing | `CollectionSourceState` (`src/integrations/models.py:814`) is unrelated internal source state. |
| Optional writable list bindings | Missing | List write endpoints exist (`^lists/...`), but not as scoped external bindings. Smart lists must stay read-only. |
| Metadata preferences and overrides | Partial | `^media/.../provider-preference/?$` exists; not modelled as user-owned overrides held separately from cached provider data. |

### Adoption kit

| Capability | State |
|---|---|
| Verified OpenAPI artifact | Implemented (`src/api/contracts/openapi.yaml`) |
| Auth/capability documentation for external clients | Missing |
| Executable conformance fixtures | Missing |
| NuvioTV compatibility matrix | Missing |
| Nuvio Mobile compatibility matrix | Missing |

### Reconciliation conclusion

The security and delivery foundation landed. The **ordered-change layer did not**, and is now being built: the watched-state synchronization program supplies bindings, per-user commit-ordered sequences, an ordered change feed, explicit deletes, origin derivation and loop prevention, and a durable outbox — for watched state specifically. See `docs/architecture/watched-state-sync.md`.

Still owed after that work: cursors as opaque validated tokens rather than raw sequences; the same layer extended to saved items and history; reconciliation preview/apply; and a publishable conformance kit. Receipt uniqueness is still scoped to `(user, client_event_id)` rather than to the binding — a unique-constraint change on a live idempotency table serving three production endpoints, which needs its own patch and rollback story.

Two findings are corrections rather than gaps, and are pulled forward:

1. Stored-but-unenforced scopes are worse than no scopes, because the credential UI will claim a restriction the server does not apply. Enforce before anything else ships on top.
2. Scoped tokens cannot be created through the product. Until they can, every external client is still told to paste the account token, which is exactly what the catalog routes already do.

## Current issue state

Recheck issue state before each PR. Verified 2026-09-06 against `dannyvfilms/Floppy`.

- #532 open. Programme epic.
- #599 closed. Malformed Cinemeta/Stremio payload handling. Keep as regression baseline.
- #598 closed. Recurring Stremio import visibility.
- #635 closed. Read-only catalog publication — closed with the routes only partially delivered; the grant model was never built. Re-file the remaining work rather than reopening.
- #636 closed as withdrawn. Scoped API credentials — the model landed; enforcement and lifecycle did not. Re-file.
- #429 closed. Bidirectional playback progress. Regression baseline.
- #417 closed. Kodi client API correctness. Regression baseline.
- #619 closed. Provider-prefixed ids. Regression baseline.
- #723 closed. Stremio watched-state correctness and history preservation. Regression baseline.
- #652 closed as not planned. Context only.
- PR #845 merged. AsyncAPI 3.0, schema viewer, delivery receipts.

Do not reopen completed issues to recreate an architecture hierarchy. File one new issue per testable behavior in the backlog below.

## Repository rules

- Target `latest`. Never target `upstream` or `release`.
- Implement each PR on its own branch off `latest`; leave unrelated working-tree changes in the shared checkout untouched, and never `git stash`.
- Prefer the smallest maintainable change and existing patterns.
- Extend existing endpoints and records additively. Do not recreate tokens, receipts, progress, scrobble, tracking, or list APIs.
- Preserve existing API compatibility and the Stremio regression coverage from #619 and #723.
- Validate models, migrations, authentication, permissions, webhooks, tasks, cache behavior, and external APIs.
- Keep the test and lint baseline at zero.
- Include screenshots for UI changes.
- Regenerate domain and OpenAPI artifacts when their contracts change.
- Run migration hygiene and upgrade replay when schema changes require them.

## External dependency

Floppy can publish its server contract on its own schedule.

A complete Nuvio user experience additionally needs one of:

- a Nuvio client that implements the Floppy contract;
- a compatible bridge;
- a supported versioned Nuvio self-host API.

Server readiness and verified end-to-end client compatibility are separate milestones. Publish server readiness when Floppy's own conformance suite passes. Claim TV or Mobile compatibility only after that client passes end-to-end verification at a recorded revision.

## Scope exclusions

- direct access to Nuvio PostgreSQL or Supabase service-role credentials;
- raw Nuvio account passwords;
- title-only authoritative matching;
- executable plugin synchronization;
- stream or debrid functionality in Floppy;
- a second Floppy database or a new microservice;
- unrestricted provider metadata replication;
- a broad identity-platform rewrite;
- full historical rewatch parity in Release A.

Nuvio self-host pairing stays deferred until Nuvio exposes a supported authorization mechanism and a versioned external API.

## Product vocabulary

Use one term for one concept.

| Term | Meaning |
|---|---|
| Saved item | An item the user intends to keep in a library or watchlist |
| Watchlist | A collection of saved screen-media items |
| Watched state | Whether an exact item or episode is completed |
| Progress | A resumable position and optional duration |
| History event | One durable consumption occurrence |
| Rewatch | A new history event for an item watched again |
| List | A Floppy-owned ordered set of items |
| Collection | A Nuvio layout with folders and source references |
| Add-on | A declarative remote HTTP capability; no code runs in Floppy |
| Plugin | Executable extension code |
| Connector | Internal code that translates one external protocol |
| Provider | A metadata or tracking source |
| Binding | An approved relation between one Floppy user and one external client/profile |
| Checkpoint | The last applied position in one resource and direction |
| Receipt | Durable proof of one accepted or rejected client operation |
| Tombstone | Durable proof of an explicit deletion |
| Projection | Normalized metadata derived from an external source |
| Override | An explicit user-owned metadata preference |

## Architecture boundary

Keep the current Floppy application.

```text
Nuvio / Stremio / Kodi / CrossWatch
                |
                v
Existing Floppy API and integration adapters
                |
                v
Small internal integration application boundary
                |
                v
Existing Floppy models and services
```

Share only behavior that must be identical across clients:

- client identity;
- scoped authorization;
- external media references;
- idempotency;
- delivery receipts;
- ordered changes;
- explicit deletes;
- cursor validation;
- checkpoint persistence;
- reconciliation results;
- safe outbound requests;
- cache provenance;
- stable public errors.

Keep source-specific behavior at each adapter:

- Stremio watched-bitfield parsing;
- Stremio `video_id` interpretation;
- Nuvio progress-key normalization;
- provider completion thresholds;
- provider rate limits;
- provider authentication;
- provider list semantics;
- provider metadata licensing;
- Nuvio Collection layout;
- executable plugin behavior.

Do not add:

- a universal provider state machine;
- direct Nuvio table access;
- a general plugin runtime;
- one class that owns every integration;
- one universal last-write-wins rule;
- a title/year fallback for authoritative writes;
- a cache-only event bus.

## Durable records

Reuse current records wherever their semantics fit. Names for new records are proposals.

### IntegrationToken — exists

`src/integrations/models.py:1208`. Keep it as the scoped credential. Owed behavior:

- enforce `scopes` at every mutating and reading endpoint an external client can reach;
- update `last_used_at` with bounded write frequency;
- expose create/list/revoke through the product, showing the secret once;
- keep the legacy account token working during a measured migration period.

Do not introduce a second credential record.

### IntegrationEventReceipt — exists

`src/integrations/models.py:1277`, gateway in `src/integrations/delivery.py`. Contract already held:

```text
same user + event ID + same digest -> prior result
same user + event ID + changed digest -> conflict
new event ID -> new operation
```

Owed behavior: scope the uniqueness to the binding once bindings exist, extend coverage to every external mutation, add retention and bounded compaction, keep aggregate metrics after row deletion.

### SyncBinding — new

Binds one Floppy user to one external instance and profile. Stores client, external instance id, external profile id, approved capabilities, approved directions, status, and created/updated/disabled times. A profile change requires explicit reapproval. Binding identity is what origin derivation, cursors, and receipts scope to; `IntegrationToken.client_identifier` is not a substitute.

### SyncCheckpoint — new

Last applied cursor for one binding, resource, and direction. Advance only after the page commits. Never store it only in cache.

### ProgressChange, SavedItemChange, WatchedStateChange — new

Ordered upserts and explicit deletes on a server sequence. Never order by client time. Keep `PlaybackProgress` and the existing tracking models as the current-state source; the change logs are additive. Never infer a delete from absence.

The existing `?updated_since=` playback filter stays as-is for compatibility. It is not the ordered-change contract and must not be documented as one.

### UnresolvedExternalReference — new

Deduplicates unsupported or ambiguous ids with a reason code and occurrence count. Stores no secret-bearing payload.

### SyncRun — reuse or extend `ImportRun`

`src/integrations/models.py:1145`. Extend only if its semantics fit. Required result counts:

```text
created
updated
deleted
skipped
unresolved
failed
preserved_local
```

### Catalog grant — new, Release B

Per-resource, revocable grant for published catalogs. Replaces the account token currently embedded in the Stremio addon URL path.

## Retention and compaction

### Receipts

- Keep them for at least the documented retry guarantee.
- Use a configurable retention period.
- Measure real retry intervals before fixing a default.
- Delete expired rows in bounded batches.
- Keep aggregate metrics after row deletion.

### Change logs

- Retain changes until every active checkpoint is beyond them.
- Require a new snapshot for a binding that remains inactive past the retention window.
- Compact below the safe watermark.
- Never compact an unapplied tombstone.
- Expose the oldest and newest retained sequence.
- Return a stable cursor-expired response.

### Unresolved items

- Deduplicate repeated unresolved references.
- Increment an occurrence count.
- Permit safe dismissal or manual resolution.
- Keep enough evidence to explain the problem without storing secrets.

## Cursor contract

Use an opaque cursor.

Bind it to:

- resource;
- user or binding;
- sequence;
- schema version;
- optional expiry.

Use either a signed cursor or a random server-backed cursor.

Rules:

- reject malformed cursors;
- reject a cursor for another binding or resource;
- return a stable expiry error;
- document snapshot recovery;
- commit a full page before advancing;
- order by server sequence;
- cap page size and limits.

## State and conflict rules

Use this safe default:

> Preserve local and user-authored state. Apply exact non-destructive changes. Skip and report ambiguity. Require explicit approval for destructive reconciliation.

### Progress

- A repeated event returns the prior result.
- A backward seek is valid only as an explicit progress event under the selected policy.
- An older event cannot silently undo completion.
- Progress does not create history by itself.

### Saved items

- Explicit add creates or preserves saved state.
- Explicit remove affects only the bound saved state.
- Absence from one page does not remove.
- An outage or partial snapshot does not remove.

### Watched state

- Exact movie and episode completion can synchronize.
- Stremio watched-bitfield evidence remains authoritative for Stremio episode completion.
- A current video is not proof of completion.
- External season completion must not invoke manual Floppy fan-out.

### History

- A retry is not a rewatch.
- A rewatch needs a distinct event identity and occurrence time.
- A lower-fidelity source does not replace a better existing date.
- Full rewatch-history parity is outside Release 1.0 unless the upstream contract proves it.

### Identity

- Accept exact verified IDs.
- Mark unsupported IDs unresolved.
- Mark conflicting verified IDs ambiguous.
- Never use title-only matching for a mutation.
- Preserve translation provenance.

### Delete

- Delete is explicit.
- Delete creates a tombstone or ordered delete event.
- An older upsert cannot resurrect a newer delete.
- Re-add needs a new explicit operation.

## API lifecycle

- Keep existing endpoints and shapes compatible.
- Add new behavior through optional fields, optional headers, or new endpoints.
- Publish the verified OpenAPI contract.
- Add contract fixtures.
- Document scopes and error codes.

Before legacy-token removal:

1. measure active use;
2. publish migration guidance;
3. show a user notice;
4. provide named-token creation;
5. permit parallel operation;
6. announce a removal release;
7. remove only after the compatibility period.

## Operational objectives

Measure these before release.

### Correctness

- No acknowledged mutation is lost.
- Replaying one request does not create a second mutation.
- Every explicit delete remains observable until active clients can apply it.
- Full reconciliation converges on supported state.
- No cross-user access is possible.

### Availability

- Provider or cache failure does not erase durable local state.
- User-requested work does not silently fail because Redis is unavailable.
- A failed page does not advance its checkpoint.
- A stale cursor has a snapshot recovery path.

### Performance and storage

Define and measure:

- page size;
- request and response size;
- JSON depth and member count;
- concurrent requests per binding and host;
- retry count;
- timeouts;
- reconciliation batch size;
- database query count;
- receipt and change-log growth.

Do not publish invented latency targets.

### Observability

Track:

- sync result counts;
- duplicate and conflicting receipt rates;
- cursor-expired rate;
- reconciliation drift;
- safe-fetch rejection reason;
- provider timeout and rate-limit count;
- cache hit, stale, and error counts;
- token use and revocation;
- event-log and receipt-table size;
- oldest active checkpoint.

Use low-cardinality labels. Do not use raw IDs or URLs as metric labels.

## Red-team and blue-team audit

This is a design audit. It does not claim that current code contains every listed weakness.

| Attack or failure | Required control | Verification |
|---|---|---|
| Cross-user or cross-profile access | User-scoped queries and approved binding | Two-user, multi-profile tests |
| Scope escalation | Endpoint scope map and explicit fields | Allowed and denied scope tests |
| Token theft or enumeration | Entropy, digest storage, constant-time compare, redaction | Secret and auth tests |
| Revocation race | Strict revocation check and cache invalidation | Revoke-under-load test |
| Replay and concurrent duplicates | Atomic receipt reservation and unique constraint | Timeout and concurrency tests |
| Event-ID reuse with changed payload | Payload digest and conflict response | Conflicting replay test |
| Out-of-order or clock-skewed events | Server sequence and stale-event rules | Reorder matrix |
| Tombstone resurrection | Sequence-aware tombstones | Delete-resurrection test |
| Delete by absence | Explicit delete only | Partial-page and empty-snapshot tests |
| Cursor tampering or cross-binding use | Opaque binding-bound cursor | Cursor abuse matrix |
| Cursor expiry | Stable expiry and snapshot recovery | Long-offline test |
| Oversized, compressed, or deep payload | Body, decoded-size, depth, count, time, rate limits | Boundary fixtures |
| Retry storm | Bounded backoff, jitter, circuit breaker | Fault injection |
| SSRF, rebinding, redirect bypass | Central safe-fetch boundary | Address and redirect matrix |
| Cloud metadata access | Block link-local metadata endpoints | Metadata endpoint tests |
| Credential forwarding | Per-request header allowlist | Capture-server test |
| Configured URL leakage | Encryption, masking, digest cache keys, query redaction | Log, UI, and cache tests |
| Cache poisoning or cross-user leak | Complete cache identity and private namespace | Isolation tests |
| Origin spoofing or infinite echo | Derive origin from credential; skip own-origin changes | Loop simulation |
| Partial transaction | Atomic state and receipt handling | Fault-injection test |
| DB lock amplification | Bounded batches and indexes | SQLite/Postgres load test |
| Migration collision | Audit, dry run, deterministic backfill | Upgrade matrix |
| Unbounded storage | Retention, watermark, compaction, metrics | Storage-growth test |
| Sensitive audit data | Minimal structured reason codes and access control | Log review |
| Remote code execution | Declarative add-ons only; reject plugins | Manifest tests |
| Supply-chain compromise | Lockfiles, pinned actions, CodeQL, dependency review | CI evidence |
| Backup and restore drift | Include new tables in restore drills | Restore test |
| Profile or account deletion | Disable binding and revoke credentials | Deletion tests |
| UI confusion and notification storm | Safe defaults, preview, grouped messages | Usability and large-error tests |

## OWASP review

The release must map controls and tests to OWASP Top 10:2025 and OWASP API Security Top 10:2023.

Required focus:

- access control and object authorization;
- secure configuration;
- dependency and action integrity;
- token and configured-URL protection;
- injection prevention;
- explicit security design;
- authentication lifecycle;
- data and manifest integrity;
- useful redacted logging and alerts;
- safe exceptional-condition handling;
- bounded resource use;
- SSRF prevention;
- versioned API inventory;
- strict validation of upstream APIs.

Do not claim absolute OWASP avoidance. Report the controls, tests, residual risk, and evidence.

## ADHD and AuDHD review

Use a three-step flow:

```text
1. Connect
2. Choose what to share
3. Review and start
```

Save progress between steps.

Use safe defaults:

```text
Progress        Two-way
Saved items     Two-way
Watched status  Two-way
Deletes         Explicit only
Conflicts       Preserve and report
Collections     Off
Add-ons         Off
Metadata        Off
Plugins         Never shared
```

Every important error uses:

```text
What happened
Data status
What you can do
Technical details
```

Acceptance criteria:

- no color-only state;
- one primary action per section;
- persistent important errors;
- grouped error counts;
- no per-item notification storm;
- clear labels;
- details collapsed by default;
- keyboard access and visible focus;
- focus stability after refresh;
- reduced motion;
- restrained live-region announcements;
- affected counts on destructive actions;
- explicit copy controls;
- no secrets in accessible names;
- resumable setup;
- dry-run preview before destructive reconciliation.

## Synthetic 50-role panel conclusion

The review covered Nuvio TV, mobile, desktop, web and TV-platform clients; Supabase/PostgREST, PostgreSQL, RLS, sync and profile engineering; Stremio, Trakt, SIMKL, CrossWatch, Kodi, Plex, Jellyfin, ListenBrainz and Last.fm integration roles; media identity, anime identity, metadata licensing and artwork; SQLite, PostgreSQL, Celery, Redis, SRE, performance, backup and release roles; API security, SSRF, secrets, supply chain, privacy, TV UX, ADHD/AuDHD, screen-reader and community-maintainer roles.

Panel consensus:

- keep Release 1.0 narrow;
- state authority explicitly;
- make retries and deletes predictable;
- never couple directly to Nuvio storage internals;
- provide preview and dry run;
- show cache freshness;
- publish a conformance kit;
- keep setup minimal;
- let future clients use stable public contracts without a Floppy source change.

## Release A backlog

Each item is one branch off `latest` and one reviewable PR. Ordering is a dependency order, not a suggestion.

### A0 — Enforce declared scopes

Correction, not new capability. `HasScope` exists and is used nowhere.

Deliver: `required_scope` on every external-facing API view; `HasScope` in their `permission_classes`; a documented scope map; `last_used_at` updated with a bounded write interval; scope names in the OpenAPI artifact.

Compatibility: legacy `User.token` keeps full access (`request.auth is None`). Tokens minted before this PR carry `DEFAULT_INTEGRATION_SCOPES`; audit that default against the new map before merging so no existing client loses access silently.

Validate: allowed-scope and denied-scope tests per endpoint group; two-user isolation; legacy-token regression; fast suite.

### A1 — Credential lifecycle in the product

Deliver: create/list/revoke named tokens with scope selection and optional expiry; secret shown once; prefix and last-use shown thereafter; settings UI following existing patterns; **no native `<select>`** — use the Alpine dropdown pattern from `users/preferences.html`.

Validate: cross-user access, revocation takes effect immediately, secret never re-readable, secret absent from logs and accessible names, desktop and narrow screenshots, keyboard and focus evidence.

### A2 — Client identity and binding

Deliver: `SyncBinding`, binding approval and revocation, explicit reapproval on profile change, connection status derived from real last-use, and binding resolution from the authenticated credential.

Validate: migrations on SQLite and PostgreSQL, migration hygiene, cross-profile isolation, revocation under load, deleted-profile handling.

### A3 — Extend receipt coverage and retention

Deliver: `Idempotency-Key` on every external mutation; receipt uniqueness scoped to binding; retention setting; bounded compaction task; aggregate metrics retained after deletion.

Validate: concurrent duplicates, conflicting retries, DB timeout before and after commit, storage-growth test.

### A4 — Ordered progress changes

Deliver: `ProgressChange`, server sequence, opaque binding-bound cursor, `SyncCheckpoint`, page limits, snapshot endpoint, cursor-expired response with a documented snapshot-recovery path.

Compatibility: the current progress response and `?updated_since=` stay unchanged.

Validate: reorder matrix, clock skew, cursor tampering and cross-binding use, cursor expiry, interrupted pagination, checkpoint not advanced on a failed page.

### A5 — Saved-item and watched-state changes

Deliver: explicit add/remove, exact watched upsert/delete, snapshots, tombstones, and no delete by absence. Split saved items from watched state if the diff gets large.

Preserve the #723 rules: Stremio watched-bitfield evidence stays authoritative for Stremio episode completion; external season completion must not trigger manual Floppy fan-out; a better existing watch date is never replaced by a lower-fidelity source.

Validate: delete-resurrection, partial-page and empty-snapshot, episode identity, completion and rewatch rules, preservation of better history dates.

### A6 — Origin derivation and unresolved references

Deliver: origin derived from the authenticated binding, own-origin changes skipped in feeds, `UnresolvedExternalReference` recording with deduplication and a user-visible list.

Validate: loop simulation across two bound clients, repeated unresolved ids deduplicate rather than accumulate.

### A7 — Reconciliation and diagnostics

Deliver: dry-run preview, categorized differences (applied, preserved, unresolved, failed), explicit apply for destructive reconciliation, last success and error, grouped counts, feature flag, kill switch.

Default to preserve and report. Applying destructive reconciliation always requires an explicit action with an affected count shown first.

Validate: large-library preview, accessibility of the preview and error surfaces, `/qa`, screenshots.

### A8 — Release A stabilization

Run clean-install, upgrade, large-library, multi-device, multi-profile, offline, restart, timeout, revoked-token, replay, ordering, cursor-expiry, compaction, SQLite, PostgreSQL, performance, security, and rollback gates.

State which Nuvio client or bridge was tested end to end, or state that none was.

## Release B backlog

Start after Release A is stable and its post-mortem is complete. Deliver in this order.

### B1 — Catalog grants

Replace the account token in the Stremio addon URL with a per-resource revocable grant limited to the selected lists and Discover rows. Keep the existing install URL working through a measured deprecation.

Validate: catalog privacy, grant revocation, cross-user access, install-URL migration.

### B2 — Complete the read-only catalog surface

Add the `meta` resource to the existing manifest and catalog routes. Publish selected Floppy lists and Discover rows only. Do not publish streams or mutation routes.

Validate: pagination, empty and unready catalogs, Stremio client compatibility fixtures.

### B3 — Metadata projections

Normalized projections with source attribution, freshness, licence and attribution. Preserve provider restrictions. Keep user overrides separate from cached provider data.

### B4 — Safe fetch and cache transparency

Central safe-fetch boundary with SSRF and rebinding protection, link-local metadata blocking, redirect policy, bounded size and time, per-request header allowlist, last-known-good behavior, and visible cache and error status.

### B5 — Declarative add-on capability discovery

Manifest schema, version negotiation, declared media types, resources, permissions, configuration, validation, health, and conformance fixtures. Declarative HTTP only. Reject executable plugins.

### B6 — Shared declarative installation records

Encrypt configured URLs. Keep per-application enabled state independent. Mask URLs in UI and logs; use digests as cache keys.

### B7 — Portable Collection descriptors

Versioned descriptors carrying layout and source references. Preserve folders, order, ownership, and unknown fields. Exclude credentials and executable plugins. Support preview, round trip, and safe unlink.

### B8 — Optional writable list bindings

Explicit scoped bindings to selected editable Floppy lists, with preview, confirmation, recovery, and conflict reporting. Computed and smart lists stay read-only.

### B9 — Metadata preferences and overrides

User-owned fields kept separate from provider projections. Never silently overwrite imported metadata.

## Adoption kit

The kit is a deliverable of Release A, built alongside A4–A7 and published with A8. It is what a Nuvio maintainer needs to implement a client without reading Floppy's source.

### Contents

- **Contract artifacts.** The verified `src/api/contracts/openapi.yaml`, `asyncapi.json`, and `context.jsonld`, regenerated and validated by the documented commands, published per release with the exact Floppy revision.
- **Authentication guide.** Creating a scoped token, the three accepted header forms (`Authorization: Bearer`, `Authorization: Token`, `X-API-Key`), the scope map, expiry and revocation behavior, and the legacy-token migration path.
- **Capability document.** What each scope grants, which resources support snapshots and ordered changes, page limits, and the cursor contract.
- **Error catalogue.** Worked examples for invalid and revoked credentials, insufficient scope, conflicting retry, cursor expiry, unresolved reference, and rate limiting.
- **Executable conformance fixtures.** Request/response pairs runnable against a live Floppy, covering the flows below. The same fixtures are used by both client targets — a divergent fixture set is a defect in the kit.

### Documented flows

Connect; initial merge; playback progress update; offline retry; incremental pull; reset; reconciliation preview and apply; disconnect.

Each flow states what is preserved, what is overwritten, and what is left unresolved.

### Compatibility matrices

Maintain one matrix per client, each recording the exact tested revision of that client and of Floppy.

- [Nuvio TV](https://github.com/NuvioMedia/NuvioTV)
- [Nuvio Mobile](https://github.com/NuvioMedia/NuvioMobile) — Kotlin Multiplatform. Target the KMP implementation; the former React Native architecture is not the integration surface. Confirm the current architecture at the recorded revision before writing platform guidance.

A matrix row is `verified` only when the fixture passed against a real build of that client. `Server ready` is a separate, earlier claim.

### Feature availability

State plainly which features a user gets through add-ons alone and which require native client adoption:

| Feature | Add-on is enough | Needs native client work |
|---|---|---|
| Browsing Floppy lists and Discover rows | Yes | No |
| Catalog metadata | Yes | No |
| Saved-item sync | No | Yes |
| Watched state sync | No | Yes |
| Resume progress sync | No | Yes |
| Reconciliation | No | Yes |
| Collections | No | Yes |

## QA and release gates

### Per PR

Use the repository risk matrix.

For Python behavior:

- targeted tests;
- Ruff;
- relevant generated contracts;
- fast suite before finish;
- `/review`;
- Codex Security diff scan.

For models and migrations:

- migration hygiene;
- `makemigrations --check`;
- SQLite migration;
- PostgreSQL migration;
- upgrade replay;
- full relevant suite.

For UI:

- desktop screenshot;
- narrow screenshot;
- keyboard and focus evidence;
- loading, success, error and recovery states;
- reduced motion;
- screen-reader names;
- `/qa`.

For APIs:

- regenerate and validate OpenAPI;
- contract tests;
- scope tests;
- two-user tests;
- limit tests;
- error-code tests;
- backward-compatibility fixtures.

### Fault matrix

Test provider failure, Redis failure, worker failure, DB timeout before and after commit, duplicate and conflicting replay, out-of-order events, clock skew, cursor tampering and expiry, partial pages, empty snapshots, deleted profiles, revoked and expired credentials, wrong scope, large libraries, repeated unresolved IDs, upgrade, rollback, and compaction.

### QA finding policy

- Read every finding.
- Fix valid findings caused by the change.
- Add a regression test.
- Re-run affected checks.
- Re-run `/qa`.
- Record the result in the PR.
- Handle pre-existing test or lint failures under the baseline-zero policy.
- Keep a large unrelated repair in a separate commit or PR.

## Rollout and rollback

Use independent feature flags for each capability. Follow repository setting patterns.

Roll out through:

1. tests only;
2. local development;
3. shadow read;
4. dry-run reconciliation;
5. opt-in beta;
6. limited release;
7. default available;
8. default enabled only after evidence.

Rollback must stop new work, preserve acknowledged state, keep existing routes operational, disable background tasks, retain diagnostics, and avoid destructive down-migrations.

## PR and commit standard

Follow repository guidance and the existing PR template.

Each PR includes:

- Summary;
- AI Assistance;
- Validation;
- Contract Handoff;
- Human Review;
- Gstack QA;
- relevant issue relationships;
- screenshots for UI changes;
- migration and rollback details;
- security and accessibility evidence;
- post-mortem or post-implementation notes where applicable.

State the AI assistance actually used for that PR, and the evidence it was reviewed against. Do not carry a disclosure forward from another PR.

Do not include tokens, configured URLs, or private viewing data in screenshots.

## Stop conditions

Stop and request a decision for:

- a destructive migration;
- an existing API break;
- raw Nuvio password storage;
- service-role or direct database access;
- title-only authoritative matching;
- remote plugin execution;
- a new service or second database;
- material scope expansion;
- unresolved metadata license;
- conflict with maintainer direction;
- inability to test a high-risk change;
- a security finding that changes the approved design.

## Review record — 2026-08-15 (historical)

Retained as the record of the original plan review. It describes the plan as written at the prior baseline, before the reconciliation above.

**Plan reviewed:** Floppy–Nuvio Integration Programme  
**Baseline:** `1bb6999a539679a27502c6514c3fdfec70f17091`  
**Manual source-based review date:** 2026-08-15

| Review | Status | Result |
|---|---|---|
| Office-hours equivalent | Complete | First wedge reduced to tracking interoperability |
| CEO/product equivalent | Complete | Two release trains; no all-at-once programme |
| Design equivalent | Complete | Three-step setup, progressive disclosure, clear states |
| Engineering equivalent | Complete | Added binding, checkpoints, receipts, retention, compaction and cursor rules |
| Developer-experience equivalent | Complete | Added OpenAPI, manifest schema, examples and conformance kit |
| Security design review | Complete | Added red/blue controls and OWASP mapping |
| ADHD/AuDHD review | Complete | Added safe defaults, grouped errors and resumable setup |
| 50-role panel | Complete as synthetic review | Consensus incorporated |
| Native `/office-hours` | Required in implementation worktree | Not run in this environment |
| Native `/autoplan` | Required in implementation worktree | Not run in this environment |
| Native `/cso` | Required in implementation worktree | Not run in this environment |
| Native `/review` | Required per code PR | Not applicable to this planning artifact |
| Native `/qa` | Required for integrated and UI behavior | Not run in this environment |
| Native `/ship` | Required before PR readiness | Not run in this environment |
| Native `/retro` | Required after each release | Not yet applicable |

**Plan status:** `PASS WITH EXECUTION GATES`

The planning-document PR can proceed now.

Production code must wait for the native plan and security gates in a runnable Floppy worktree.
