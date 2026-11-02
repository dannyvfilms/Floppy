# Connection health

When an integration account may be marked `connection_broken`, and how it
recovers. The code is `src/integrations/connection_health.py`. This page
explains it; if the two disagree, the module wins.

## The rule

`connection_broken` means one thing: **the provider rejected our
credentials, or we cannot read them.**

| Failure | Sets `connection_broken`? | Records the error? |
|---|---|---|
| 401/403, revoked token, invalid session | Yes | Yes |
| Stored secret cannot be decrypted | Yes | Yes |
| Timeout, refused connection, DNS, TLS | No | Yes |
| 5xx, rate limit | No | Yes |
| A dependency failing (e.g. IGDB matching) | No | Yes |

A non-auth failure leaves the flag as it was. It neither sets it nor clears
it. Only a successful run clears it.

## Recovery

Scheduled work must not skip a broken account forever, because then a flag
set in error never clears (#1267). Each scheduled path therefore does one
of these:

- **Re-probe first.** The Jellyfin push and pull call `healthcheck()`.
  Success clears the flag and the run continues. A rejection re-records it
  and the run skips quietly.
- **Let the run be the probe.** The Koito and Last.fm fan-outs include
  broken accounts once `due_for_probe()` says an hour has passed since
  their last failure. MDBList and the importers simply run.

The UI still tells a person to reconnect while the flag is set. Reconnecting
remains the fix for a key that really was revoked.

## Why

**#1267.** One Jellyfin library page timed out. The push set
`connection_broken`, and both the push and the pull checked `is_connected`
before the only lines that could clear it. The account stayed
"disconnected" until someone re-saved the form. Radarr, Sonarr, Xbox, PSN
and Storyteller also went "disconnected" on timeouts or 5xx responses.
Koito, Last.fm and MDBList were never re-probed.

## Recording a failure

```python
from integrations import connection_health
from integrations.imports.helpers import ConnectionAuthError

try:
    ...
except MediaImportError as error:
    connection_health.record_failure(
        account,
        error,
        auth=isinstance(error, ConnectionAuthError),
    )
    raise
```

- Clients raise `ConnectionAuthError`, or their own `*AuthError`, only for
  rejected credentials.
- When an error is wrapped, `caused_by(exc, AuthError)` finds the auth
  error anywhere in the cause chain.
- `record_success(account, extra_fields=[...])` clears the flag and the
  error.

## Adding an integration

1. Keep auth errors distinct from everything else in the client.
2. Record failures through `record_failure(auth=...)`, not by writing
   `connection_broken` directly.
3. Gate scheduled work on "has credentials" (plus `due_for_probe()` for
   frequent polls), not on `is_connected`.

`integrations.tests.test_connection_health_contract` fails when a new file
sets `connection_broken = True` directly. The few reviewed exceptions, each
auth-only, are listed there with a reason.
