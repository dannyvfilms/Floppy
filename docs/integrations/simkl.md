# SIMKL outbound sync

Floppy can send the movies and episodes you watch to your
[SIMKL](https://simkl.com/) history, with the date you watched each one. It is
one destination on the shared outbound engine described in
[watched-state-sync](../architecture/watched-state-sync.md), built on the same
shared pieces as [WeTrakr](wetrakr.md). This page covers only what is specific
to SIMKL.

```bash
SECRET=test-only scripts/test.sh integrations.tests.test_simkl_push
```

## What is shared, and what is SIMKL's

A new destination is a description plus an adapter. Nothing below is copied per
service:

| Shared (written once) | File |
| --- | --- |
| Device-code login, settings, disconnect, export button, the card's data | `integrations/state/destinations.py` (`PushDestination`) |
| Token refresh once across workers, connection health | `integrations/state/device_client.py` |
| "Send existing library" queuing, undated plays, preview counts | `integrations/state/export.py` |
| TMDB references for movies and episodes | `integrations/state/references.py` |
| Account columns (`DeviceLoginAccount`) and the settings card templates | `integrations/models.py`, `templates/users/components/push_destination_sync.html` |

SIMKL's own part is `simkl_api.py` (endpoints and errors), `state/adapters/simkl.py`
(what a batch looks like), `simkl_views.py` (a few lines naming the destination)
and `tasks/_simkl_export.py`.

## Connecting

SIMKL needs your own app: Settings > Providers > SIMKL > Connection, add the
Client ID (the same app the import uses). The device login needs an app made with
AUTH V2 and **no client secret**. Then Connect SIMKL shows a code; approve it on
simkl.com/pin. Floppy asks for `media:read media:write` and checks the scope it
was granted, because SIMKL quietly downgrades an unknown scope to read-only.

This login is separate from the import connection, which only reads.

Disconnecting revokes the login at SIMKL (either token revokes the whole grant).

## What is sent

Plays only, to `POST /sync/history`, in batches:

- Every episode is sent under `seasons[].episodes[]` with its numbers, never a
  show or a season alone (SIMKL would mark all of its episodes watched), and
  with `skip_auto_watching=yes`.
- Each play keeps its real `watched_at`.
- A play with no date is **left out** unless "Send plays with no date" is on.
  SIMKL has no empty date, so those go out as `1970-01-01T00:00:01Z`, its "I
  don't remember" value, and are never given today's date.
- `not_found` in SIMKL's reply fails that item's delivery with a reason, so it
  shows under Activity instead of counting as sent. A reply Floppy cannot read
  is retried, never counted as delivered.
- Imported history is never sent on its own (it would include what SIMKL itself
  gave Floppy). "Send existing library" sends it once, on request.

Only native TMDB movies and episodes are sent; anime and other sources are not
guessed at.

## Never sent

- Statuses and ratings (not in this change).
- Removals: a removal without an episode named removes the whole title from the
  SIMKL library, so an ordinary delete here is never sent.
- Rewatch sessions: they need `allow_rewatch=yes` and a paid SIMKL plan, and
  plays closer than two days are silently absorbed. A repeat play of the same
  title is therefore a no-op there, not a failure.

## Limits

- 1 write per second and a 20 second per-user write lock: a write made during
  another answers `400 rate_limit` and is retried after 20 seconds.
- Daily quota 500 / 1,000 / 10,000 (Free / Pro / VIP), reset at midnight
  America/New_York. A 429 waits for `Retry-After`, or for that reset.
- Access tokens last 7 days. The refresh token does not rotate, but a refresh
  replaces the access token at once, so refreshes are serialized with a lock.

## Verification status

**Not yet verified against a live SIMKL account.** The device-login and token
endpoints are from SIMKL's AUTH V2 documentation. The shape of `not_found`
entries and of the token response (`expires_in`, `scope`) is partly assumed, so
the code reads them cautiously. Check with a consenting test account: the token
response body, a `not_found` entry for an unknown id, and that a play with
`watched_at` appears with that date.

## Native app

The native app's login key for this device code is `simkl-send`; `simkl` stays
the browser sign-in used by the import. Activity for SIMKL arrives through the
same tracker-activity list as WeTrakr's.
