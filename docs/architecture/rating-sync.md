# Rating sync-back

TMDb is the first rating destination. Rating sync uses the watched-state
transactional outbox, worker, sweeper and backoff in
`integrations.state.outbound`; it does not introduce a second delivery queue.

## Explicit edits

`integrations.state.ratings.rating_edit` opts a UI/API writer into outbound
rating delivery. It locks the user's row before reading tracking data, wraps
the edit and enqueue in one transaction, and collects actual score changes.
An error response rolls the transaction back. Imports, provider observations,
ordinary model saves and inherited replay ratings never enter this scope.

Movie, show and episode saves collect changes through scoped signals. Episode
queryset updates emit `episode_scores_changed`, collected by
`record_episode_rating_edits` while a direct writer is in scope. Writers that
bypass model signals must emit this same signal. No HTTP request to a provider runs in the edit request;
the commit callback only kicks the worker. A lost kick leaves a pending intent
for the existing sweeper.

`RatingSyncEdit` retains the latest explicit edit per user/item, including a
clear that deleted an episode's rating-only row. It is not a tracking entry or
a watch. It is recorded even before a destination is connected, so an optional
export can still honor a prior clear.

## Shared provider contract

`enqueue_rating_change(user, item, score)` fans out to bindings that have both
outbound approval and the adapter's `rating.push` capability. A null score is
an explicit removal; zero is a score. Export may restrict fanout to its
requested `client_kind`.

Rating adapters implement `RatingAdapter` alongside, or independently of,
`StateAdapter`: resolve an exact identity, normalize a score, read the personal
rating, and idempotently set or clear it. A `RemoteRating(None)` means known
unrated; a missing remote response means unknown. Retries read first and compare
the normalized score, including a clear, before repeating an uncertain write.
Provider calls are uncached and separate from shared metadata responses.

Deliveries have an operation (`watched` by default for existing rows, or
`rating`) and a nullable rating value. Revision uniqueness, pending coalescing
and the in-flight constraint include the operation. A binding lock allocates
rating revisions. Newer revisions supersede pending old ratings, and an old
in-flight failure cannot retry over a newer edit. Watched-only adapters retain
their existing interface and task names. Rating-only approval does not enable
the watched-state change log.

## TMDb setup and behavior

In **Settings → Integrations → TMDb ratings**, connect your TMDb account by
approving the request on TMDb, then explicitly enable rating sync. Application
API credentials resolve through the existing Metadata settings. Personal TMDb
session IDs are encrypted separately. The callback is bound to the initiating
authenticated browser session, expires with TMDb's request token, verifies the
remote account, and is single-use. Reconnecting disables existing bindings;
sending must be enabled again.

Future direct UI/API rating edits send automatically. Connecting or enabling
sync never exports existing ratings. **Export existing ratings** is a separate
action, runs on the default Celery queue, and may replace or remove existing
TMDb ratings. The export reads items in batches and re-reads each score under
the same user lock as a direct edit. Latest rating edit wins across tracking
entries (`scored_at`, then row ID); legacy scored entries without a timestamp
use `created_at`. Explicit clear records participate in that comparison.

Only native, confirmed TMDb movie, show and episode identities are written.
Custom episode orders, other metadata sources, ambiguous identities and
unsupported items are skipped. Seasons stay local. Scores round to the nearest
half-point, with ties rounded up, and clamp to 0.5–10. Floppy's original score
is unchanged. Clears delete the TMDb rating; deleting tracking history is not a
rating clear. No remote rating is imported. TMDb may remove a rated title from
its watchlist according to the user's TMDb account settings.

Settings show connection health, delivery counts and recent results. Only
credential rejection marks the connection broken. The existing delivery
sweeper re-probes broken accounts when due. Disconnect/disable retires pending
deliveries and prevents future claims; an HTTP call already in flight may
finish. Disconnect also attempts remote session revocation, reporting when it
cannot be confirmed.

## Upgrade and validation

Migration `integrations.0059_rating_sync` adds account/edit records and extends
the outbox without rewriting existing tracking scores or watched intents.
Deploy migrations and restart web/Celery processes together: old processes do
not understand rating deliveries. Back up the database first. Reversing the
migration removes rating-only delivery intents before restoring watched-only
uniqueness, and removes the new account/edit tables. Local tracking ratings and
watched intents survive; remote TMDb ratings are not reversed.

Run `scripts/test.sh integrations.tests.test_rating_sync` for the rating
contract and `integrations.tests.test_state_outbound` for watched regression
coverage. Ordinary tests mock TMDb and never write to a real account.
