# The outbound fetch boundary

Where Floppy fetches a URL a **user** supplied — an add-on manifest, a remote
capability descriptor — it goes through `src/integrations/safe_fetch.py`.

This is a different problem from fetching provider artwork. Artwork hosts are
known in advance, so `app.image_cache.is_approved_url` uses an allowlist. An
add-on host cannot be known in advance, so this validates the destination
instead of recognising it.

## What it enforces

| Control | Why |
|---|---|
| http/https only | `file://` reads the disk |
| No credentials in the URL | They end up in logs and error messages |
| Standard ports only | Otherwise the fetcher is a port scanner |
| Every resolved address must be public | **A public name resolving to `127.0.0.1` is the SSRF trick; an IP-literal check does not catch it** |
| Loopback, private, link-local, reserved, multicast, unspecified refused | Covers cloud metadata at `169.254.169.254` and `fd00:ec2::254` |
| Mixed public/private answers refused entirely | Which address a later connection picks is not controllable here |
| Redirects followed manually, re-validated per hop | A permitted host may redirect to a forbidden one |
| Redirect count bounded | Loops terminate |
| Size bounded, checked while streaming | A server that omits or lies about `Content-Length` must not exhaust memory |
| Time bounded | A slow host must not hold a worker open |
| Header allowlist | No cookie, `Authorization`, or trace id is forwarded to a user-typed host |

Failures raise `UnsafeUrlError` with a stable `reason_code`. Log and display the
code, never the raw URL: a configured URL can itself carry a secret.

## Residual risk

Validation resolves the hostname and the connection resolves it again, so a
hostile DNS server can answer differently in between. Closing that window
requires pinning the socket to the validated address, which this does not do.
It narrows the window to a single resolution and re-checks every redirect hop.

Do not describe Floppy as SSRF-proof. Describe these controls, this gap, and
the tests in `integrations.tests.test_safe_fetch`.

## Using it

```python
from integrations.safe_fetch import UnsafeUrlError, safe_fetch

try:
    response, body = safe_fetch(url)
except UnsafeUrlError as error:
    # error.reason_code is stable and safe to show
    ...
```

Do not add another outbound path for user-configured URLs. If this boundary
lacks something you need, extend it here so every caller gets the fix.
