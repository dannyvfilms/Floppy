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

## Self-hosted servers

Radarr, Sonarr, Mylar3, Audiobookshelf, Koito, KOReader, Storyteller,
Jellyfin, Emby, Kodi and gPodder talk to a server the user runs, usually on
their own network. The public-only policy above would refuse exactly those
addresses, so these clients send through `send_to_self_hosted` instead.

| Control | Why |
|---|---|
| http/https only | `file://` reads the disk |
| Loopback, private and CGNAT (Tailscale) addresses **allowed** | That is where a home server lives |
| Link-local refused, including `169.254.169.254` and `::ffff:169.254.169.254` | Cloud metadata hands out credentials |
| `fd00:ec2::254` and `100.100.100.200` refused | Metadata endpoints inside otherwise-allowed ranges |
| Multicast and reserved refused (IPv6 loopback excepted) | No server lives there |
| Redirects followed only on the same host, re-validated per hop | An API key in a header must not reach another server |
| A name that does not resolve is passed through | The request then fails with the ordinary connection error |

Refusals raise `SelfHostedUrlError`, which is also a `requests` error, so each
client's existing error handling reports it; its message never contains the
URL. Ports are not restricted, because these servers run on their own ports.

This does not stop a user from pointing Floppy at another service on their own
network. It stops the address from reaching cloud metadata and stops a server
from redirecting a key elsewhere. The same DNS-rebinding window described above
applies. Tests: `integrations.tests.test_safe_fetch.SelfHostedPolicyTests`.

```python
from integrations.safe_fetch import send_to_self_hosted

response = send_to_self_hosted(requests.get, url, headers=..., timeout=20)
```

Pass the module's own `requests.get` (or `partial(requests.request, method)`)
so tests that patch it keep working.
