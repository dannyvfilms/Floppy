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
| Shared address space (`100.64.0.0/10`) refused | It is not globally routable and includes a cloud metadata destination |
| Loopback, private, link-local, reserved, multicast, unspecified refused | Covers cloud metadata at `169.254.169.254` and `fd00:ec2::254` |
| Mixed public/private answers refused entirely | Which address a later connection picks is not controllable here |
| The socket dials the address validation resolved | **DNS is consulted once, at validation; a hostile server cannot answer differently between validation and connect (connection pinning)** |
| Redirects followed manually, re-validated per hop | A permitted host may redirect to a forbidden one |
| Redirect count bounded | Loops terminate |
| Size bounded by *decoded* content, checked while streaming | A gzip bomb and a server that omits or lies about `Content-Length` must not exhaust memory |
| One connected-socket deadline shared across hops | Shuts down the socket during buffered reads or TLS; inactivity timeouts alone are insufficient |
| Header allowlist | No cookie, `Authorization`, or trace id is forwarded to a user-typed host |
| `trust_env=False` on the pinned session | Proxy variables cannot route the fetch through a host that was never validated |

Failures raise `UnsafeUrlError` with a stable `reason_code`. Log and display the
code, never the raw URL: a configured URL can itself carry a secret.

## How pinning works

`safe_fetch` validates each hop, then builds the wire URL with the validated
address as its host (bracketed for IPv6) and sends an explicit `Host` header
carrying the original hostname. `PinnedTLSAdapter` mounts
`assert_hostname`/`server_hostname` (urllib3 2.7) equal to the original
hostname on HTTPS pools, so the certificate is verified against the origin
name and that name is sent as SNI while the socket dials the address. The
address literal is not re-resolved through DNS, which is what closes the
rebinding window. The pinned session runs with `trust_env=False`, so proxy
environment variables and netrc cannot redirect the dial. When several
addresses validate, the first is pinned deterministically (no failover
across addresses within one fetch).

The elapsed-time budget (`TOTAL_TIMEOUT`, 30s; per-call `total_timeout`)
clamps connect/read timeouts before each request. After connecting, the
adapter duplicates the socket handle and starts a timer for the remaining
budget. At expiry it calls `shutdown` on the shared connection, interrupting
buffered header/body reads and TLS negotiation even when a peer keeps
sending bytes. The duplicate survives TLS wrapping the original socket.
Session cleanup cancels and joins each timer and closes its handle. Each
connected hop uses one temporary timer thread and socket handle (at most four
per fetch, all released when the fetch ends);
expiry is subject to OS scheduling, not a real-time guarantee.

This replaced an insufficient between-chunks check: a real socketpair with
a 50 ms budget and 100 ms inactivity timeout took about 690 ms to raise.
`SocketDeadlineTests` now exercises slow headers, body and TLS through the
actual Requests/urllib3 stack. Injected test sessions own their cancellation.
The `getaddrinfo` call remains bounded only by OS resolver timeouts.

Failures raise `UnsafeUrlError` with a stable `reason_code`
(`deadline_exceeded` for a budget exhaustion). Log and display the code,
never the raw URL: a configured URL can itself carry a secret.

## Residual risk

The DNS-rebinding window between validation and connect is closed by
pinning. What remains: `getaddrinfo`, OS cancellation scheduling (above), and a
compromised OS resolver is outside any application boundary. Do not describe
Floppy as SSRF-proof. Describe these controls, these gaps, and the tests in
`integrations.tests.test_safe_fetch` (`PinnedTransportTests` proves which
tuple the socket dials and what the Host header says, on the real transport
stack over a socketpair).

## Using it

```python
from integrations.safe_fetch import UnsafeUrlError, safe_fetch

try:
    response, body = safe_fetch(url)
except UnsafeUrlError as error:
    # error.reason_code is stable and safe to show
    ...
```

The returned response is closed after its bounded body is consumed, including
on read failures or size refusals. Inspect its status and headers, and use the
returned `body` bytes rather than trying to stream it again.

Do not add another outbound path for user-configured URLs. If this boundary
lacks something you need, extend it here so every caller gets the fix.

## Self-hosted servers

Radarr, Sonarr, Seerr, Mylar3, Audiobookshelf, Koito, KOReader, Storyteller,
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
from redirecting a key elsewhere. This path is **not pinned**: the request
re-resolves the hostname, so the DNS-rebinding window the public path closed
still applies here — a user's own resolver is inside their trust boundary, and
their own API keys ride these requests. Tests:
`integrations.tests.test_safe_fetch.SelfHostedPolicyTests`.

```python
from integrations.safe_fetch import send_to_self_hosted

response = send_to_self_hosted(requests.get, url, headers=..., timeout=20)
```

Pass the module's own `requests.get` (or `partial(requests.request, method)`)
so tests that patch it keep working.

International domain names are normalized through Requests before resolution, so
DNS validation, the Host header and TLS verification use the same ASCII name.
Explicit allowed ports are retained in the Host header as well as the dial URL.
