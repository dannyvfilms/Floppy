"""The outbound boundary for user-configured remote URLs.

Add-on manifests are fetched from an address the *user* supplies, which is a
different problem from fetching provider artwork. Artwork uses an allowlist
(`app.image_cache.is_approved_url`); an add-on host cannot be known in advance,
so this validates the destination instead of recognising it.

What it enforces:

- http/https only, no credentials, no non-standard port
- the hostname is resolved and **every** resolved address is checked, because
  a public name that resolves to 127.0.0.1 is the whole SSRF trick and an
  IP-literal check does not catch it
- loopback, private, link-local, reserved, multicast and unspecified ranges
  are refused, which covers the cloud metadata endpoints at 169.254.169.254
  and fd00:ec2::254
- redirects are followed manually and re-validated at every hop, because a
  permitted host may redirect to a forbidden one
- response size and time are bounded, and the body is read in chunks so an
  endless stream cannot exhaust memory
- only an explicit header allowlist is sent, so no credential is forwarded

**Residual risk:** OS resolver timeouts are the only bound on
``getaddrinfo``. After connection, a deadline timer shuts down the socket,
including during TLS negotiation or buffered header/body reads. Connection
pinning prevents a different DNS answer from changing the destination between
validation and connect. Cancellation is subject to OS thread scheduling.
"""

import ipaddress
import math
import logging
import socket
import threading
import time
import weakref
from contextlib import suppress
from urllib.parse import urlparse, urlunsplit

import requests
from urllib3.connection import HTTPConnection, HTTPSConnection

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 3
MAX_BYTES = 1024 * 1024
# Larger self-hosted library pages require a separate bounded budget.
SELF_HOSTED_MAX_BYTES = 32 * 1024 * 1024
SELF_HOSTED_TOTAL_TIMEOUT = 60
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
# Shared elapsed-time budget. Socket inactivity timeouts alone cannot stop
# buffered slow-drip reads, so the owned transport also cancels the socket.
TOTAL_TIMEOUT = 30
CHUNK_SIZE = 8192

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, None}

# Sent outward. Anything not named here never leaves Floppy, so a cookie,
# an Authorization header or an internal trace id cannot be forwarded to a
# host the user typed in.
REQUEST_HEADER_ALLOWLIST = ("Accept", "Accept-Encoding", "User-Agent")

LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
LOCAL_NAMES = {"localhost", "localhost.localdomain"}

# Stable reason codes. Surfaced to the user and logged; never a raw URL.
REASON_UNRESOLVABLE_HOST = "unresolvable_host"
REASON_FORBIDDEN_ADDRESS = "forbidden_address"
REASON_MISSING_URL = "missing_url"
REASON_UNPARSABLE_URL = "unparsable_url"
REASON_FORBIDDEN_SCHEME = "forbidden_scheme"
REASON_CREDENTIALS_IN_URL = "credentials_in_url"
REASON_FORBIDDEN_PORT = "forbidden_port"
REASON_MISSING_HOST = "missing_host"
REASON_RESPONSE_TOO_LARGE = "response_too_large"
REASON_INVALID_REDIRECT = "invalid_redirect"
REASON_TOO_MANY_REDIRECTS = "too_many_redirects"
REASON_DEADLINE_EXCEEDED = "deadline_exceeded"


class UnsafeUrlError(Exception):
    """Raised when a URL may not be fetched, with a stable reason code."""

    def __init__(self, reason_code, message):
        """Store the reason code alongside the message."""
        super().__init__(message)
        self.reason_code = reason_code


def _address_is_forbidden(address):
    """Return whether one resolved address is outside the public internet."""
    return bool(
        not address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def resolve_public_addresses(hostname):
    """Resolve ``hostname`` and return its addresses, or raise UnsafeUrlError.

    Every resolved address must be public. A name that resolves to one public
    and one private address is refused: which one a later connection picks is
    not something this can control.
    """
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as error:
        msg = f"Could not resolve {hostname}."
        raise UnsafeUrlError(REASON_UNRESOLVABLE_HOST, msg) from error

    addresses = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _address_is_forbidden(address):
            msg = "This address is not on the public internet."
            raise UnsafeUrlError(REASON_FORBIDDEN_ADDRESS, msg)
        addresses.append(address)

    if not addresses:
        msg = f"Could not resolve {hostname} to any address."
        raise UnsafeUrlError(REASON_UNRESOLVABLE_HOST, msg)
    return addresses


def _validate_target(url):
    """Validate one URL and return ``(parsed, addresses)``.

    The addresses are the ones validation actually saw, which is what the
    connection is pinned to. Raises UnsafeUrlError like ``validate_url``.
    """
    if not isinstance(url, str) or not url.strip():
        msg = "A URL is required."
        raise UnsafeUrlError(REASON_MISSING_URL, msg)

    try:
        parsed = urlparse(url.strip())
    except ValueError as error:
        msg = "This URL could not be parsed."
        raise UnsafeUrlError(REASON_UNPARSABLE_URL, msg) from error

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        msg = "Only http and https URLs can be fetched."
        raise UnsafeUrlError(REASON_FORBIDDEN_SCHEME, msg)

    try:
        credentials = parsed.username or parsed.password
        port = parsed.port
    except ValueError as error:
        msg = "This URL could not be parsed."
        raise UnsafeUrlError(REASON_UNPARSABLE_URL, msg) from error

    if credentials:
        msg = "Credentials in the URL are not supported."
        raise UnsafeUrlError(REASON_CREDENTIALS_IN_URL, msg)

    if port not in ALLOWED_PORTS:
        msg = "Only the standard http and https ports can be fetched."
        raise UnsafeUrlError(REASON_FORBIDDEN_PORT, msg)

    # Use Requests' IDNA normalization before both DNS validation and TLS/Host
    # construction. A Unicode Host header cannot be sent by the HTTP transport,
    # and normalizing only after lookup could select a different IDNA identity.
    if parsed.hostname:
        try:
            prepared = requests.PreparedRequest()
            prepared.prepare_url(parsed.geturl(), None)
            parsed = urlparse(prepared.url)
        except requests.RequestException as error:
            msg = "This URL could not be parsed."
            raise UnsafeUrlError(REASON_UNPARSABLE_URL, msg) from error

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        msg = "This URL has no host."
        raise UnsafeUrlError(REASON_MISSING_HOST, msg)

    if hostname in LOCAL_NAMES or hostname.endswith(LOCAL_SUFFIXES):
        msg = "This address is not on the public internet."
        raise UnsafeUrlError(REASON_FORBIDDEN_ADDRESS, msg)

    addresses = resolve_public_addresses(hostname)
    return parsed, addresses


def validate_url(url):
    """Validate one URL and return its parsed form, or raise UnsafeUrlError."""
    return _validate_target(url)[0]


def _address_literal(address):
    """Return the address as it appears inside a URL (bracketed for IPv6)."""
    return (
        f"[{address}]" if isinstance(address, ipaddress.IPv6Address) else str(address)
    )


def _host_header_value(hostname):
    """Return the Host header value for the original hostname."""
    return f"[{hostname}]" if ":" in hostname else hostname


def _pinned_url(parsed, address):
    """Rebuild the URL with the validated address as its host.

    The connection dials this address literally, so DNS is consulted exactly
    once per hop — during validation. The explicit Host header and the
    adapter's TLS settings keep the origin's identity on the wire and in the
    certificate check.
    """
    netloc = _address_literal(address)
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment)
    )


class _DeadlineConnectionMixin:
    """Register the connected socket before HTTP reads or TLS negotiation."""

    def __init__(self, *args, deadline_callback, **kwargs):
        self.deadline_callback = deadline_callback
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        sock = super()._new_conn()
        try:
            self.deadline_callback(sock)
        except Exception:
            sock.close()
            raise
        return sock


class _DeadlineHTTPConnection(_DeadlineConnectionMixin, HTTPConnection):
    """HTTP connection with deadline cancellation."""


class _DeadlineHTTPSConnection(_DeadlineConnectionMixin, HTTPSConnection):
    """HTTPS connection with cancellation during TLS and subsequent reads."""


class PinnedTLSAdapter(requests.adapters.HTTPAdapter):
    """Transport adapter that dials a pre-validated address.

    ``assert_hostname`` and ``server_hostname`` keep the TLS identity on the
    *original* hostname: the certificate is verified against that name (not
    the address literal being dialed) and it is sent as SNI. Without this,
    pinning an HTTPS URL to its address would either break verification or
    silently disable it. Plain HTTP pools take no TLS kwargs, so the identity
    is only applied when ``tls_identity`` is set.
    """

    def __init__(self, hostname, *, tls_identity=True, deadline=None, **kwargs):
        """Store the origin identity; see the class docstring."""
        self.pinned_hostname = hostname
        self.tls_identity = tls_identity
        self.deadline = deadline
        self._deadline_sockets = []
        super().__init__(**kwargs)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        """Attach cancellation to this fetch's private connection pool."""
        pool = super().get_connection_with_tls_context(request, verify, proxies, cert)
        if self.deadline is not None:
            pool.ConnectionCls = (
                _DeadlineHTTPSConnection
                if self.tls_identity
                else _DeadlineHTTPConnection
            )
            pool.conn_kw["deadline_callback"] = self._watch_socket
        return pool

    def _watch_socket(self, sock):
        # A duplicate retains the same TCP connection even when TLS wraps
        # and detaches the original socket object. shutdown wakes buffered
        # reads and the TLS handshake; close alone would not interrupt them.
        duplicate = sock.dup()

        def abort():
            with suppress(OSError):
                duplicate.shutdown(socket.SHUT_RDWR)

        timer = threading.Timer(max(0, self.deadline - time.monotonic()), abort)
        timer.daemon = True
        try:
            timer.start()
        except RuntimeError:
            duplicate.close()
            raise
        self._deadline_sockets.append((timer, duplicate))

    def close(self):
        """Join cancellation callbacks before releasing their socket handles."""
        for timer, duplicate in self._deadline_sockets:
            timer.cancel()
            timer.join()
            duplicate.close()
        self._deadline_sockets.clear()
        super().close()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        """Install the hostname-identity kwargs on TLS connection pools."""
        if self.tls_identity:
            pool_kwargs.setdefault("assert_hostname", self.pinned_hostname)
            pool_kwargs.setdefault("server_hostname", self.pinned_hostname)
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _pinned_session(address, hostname, scheme, *, deadline=None):
    """Build a one-fetch session that cannot be steered by the environment.

    ``trust_env=False`` so proxy variables (and netrc credentials) cannot
    redirect the fetch through a host that was never validated: a proxy would
    resolve the hostname itself, which is exactly the resolution this
    boundary exists to control.
    """
    session = requests.Session()
    session.trust_env = False
    session.mount(
        f"{scheme}://{_address_literal(address)}",
        PinnedTLSAdapter(hostname, tls_identity=scheme == "https", deadline=deadline),
    )
    return session


def _deadline_error():
    return UnsafeUrlError(
        REASON_DEADLINE_EXCEEDED, "This server took too long to respond."
    )


def _clamped_timeouts(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_error()
    return (min(CONNECT_TIMEOUT, remaining), min(READ_TIMEOUT, remaining))


def _read_bounded(response, deadline=None, max_bytes=MAX_BYTES):
    """Read at most max_bytes of decoded content, refusing anything larger."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        msg = "This response is larger than Floppy will fetch."
        raise UnsafeUrlError(REASON_RESPONSE_TOO_LARGE, msg)

    body = bytearray()
    for chunk in response.iter_content(CHUNK_SIZE):
        # iter_content yields *decoded* bytes, so a compressed response is
        # bounded by what it expands to, not by its transfer size.
        body.extend(chunk)
        # Checked while streaming, not afterwards: a server that lies about
        # Content-Length, or omits it, must still not be able to exhaust
        # memory. Requests may perform many socket reads before yielding a
        # chunk, so this check cannot impose a hard wall-clock deadline.
        if len(body) > max_bytes:
            msg = "This response is larger than Floppy will fetch."
            raise UnsafeUrlError(REASON_RESPONSE_TOO_LARGE, msg)
        if deadline is not None and time.monotonic() >= deadline:
            raise _deadline_error()
    if deadline is not None and time.monotonic() >= deadline:
        raise _deadline_error()
    return bytes(body)


def safe_fetch(
    url, *, headers=None, session=None, total_timeout=None, max_bytes=MAX_BYTES
):
    """Fetch ``url`` through the outbound boundary and return (response, body).

    The connection is pinned to the address validation resolved: each hop's
    wire URL uses the validated address literal while the Host header and TLS
    verification keep the original hostname. The elapsed-time budget
    (``total_timeout``, default :data:`TOTAL_TIMEOUT`) cancels connected
    sockets, including buffered reads and TLS. DNS resolution remains
    bounded only by OS resolver settings.

    ``max_bytes`` caps the decoded body; podcast feeds use a larger bounded
    budget than add-on manifests.

    ``session`` overrides the transport (used by tests) and is responsible
    for its own cancellation; the pinned session
    built otherwise never trusts the environment, so proxy variables cannot
    route the fetch somewhere unvalidated.

    Raises UnsafeUrlError for anything the boundary refuses, and
    requests.RequestException for a transport failure.
    """
    outbound = {"Accept": "application/json", "User-Agent": "Floppy"}
    for name in REQUEST_HEADER_ALLOWLIST:
        if headers and name in headers:
            outbound[name] = headers[name]

    deadline = time.monotonic() + (
        TOTAL_TIMEOUT if total_timeout is None else total_timeout
    )
    owned_sessions = []
    current = url
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            parsed, addresses = _validate_target(current)
            address = addresses[0]
            hostname = (parsed.hostname or "").lower().rstrip(".")
            hop_headers = dict(outbound)
            hop_headers["Host"] = _host_header_value(hostname)
            if parsed.port is not None:
                hop_headers["Host"] += f":{parsed.port}"
            timeout = _clamped_timeouts(deadline)

            if session is None:
                sender = _pinned_session(
                    address, hostname, parsed.scheme.lower(), deadline=deadline
                )
                owned_sessions.append(sender)
            else:
                sender = session
            response = sender.get(
                _pinned_url(parsed, address),
                headers=hop_headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )

            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    msg = "This redirect had no destination."
                    raise UnsafeUrlError(REASON_INVALID_REDIRECT, msg)
                # Re-validated on the next pass: a permitted host is allowed to
                # redirect, but not to somewhere this boundary would have refused.
                current = requests.compat.urljoin(current, location)
                continue

            # The response URL is the pinned address; keep the real
            # destination for callers that resolve relative links against it.
            response.logical_url = current
            try:
                return response, _read_bounded(response, deadline, max_bytes)
            finally:
                response.close()
    except requests.RequestException as error:
        if time.monotonic() >= deadline:
            raise _deadline_error() from error
        raise
    finally:
        for owned in owned_sessions:
            owned.close()

    msg = "This URL redirected too many times."
    raise UnsafeUrlError(REASON_TOO_MANY_REDIRECTS, msg)


# --- Self-hosted servers -----------------------------------------------------
#
# Radarr, Jellyfin, Mylar3 and the other self-hosted integrations live on the
# user's own network, so the public-only policy above would refuse the very
# addresses they need. This policy keeps loopback, private and CGNAT (Tailscale)
# addresses working and refuses only what no media server legitimately uses:
# link-local (the cloud metadata endpoint 169.254.169.254), multicast and
# reserved ranges, plus the metadata addresses that sit inside
# otherwise-allowed ranges. Redirects are followed only on the same host, so an
# API key sent in a header is never forwarded to a different server.

SELF_HOSTED_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud, inside CGNAT
        ipaddress.ip_address("168.63.129.16"),  # Azure platform address
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IPv6, inside ULA
    },
)

REASON_CROSS_HOST_REDIRECT = "cross_host_redirect"


class SelfHostedUrlError(UnsafeUrlError, requests.exceptions.InvalidURL):
    """Refused self-hosted destination.

    Also a ``requests`` error, so every integration's existing
    ``except requests.RequestException`` reports it like any other
    unreachable server. The message never contains the URL.
    """


def _self_hosted_address_is_forbidden(address):
    """Return whether no self-hosted media server could live at ``address``."""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return bool(
        address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        # ::1 sits inside the reserved ::/8 block; loopback must stay usable.
        or (address.is_reserved and not address.is_loopback)
        or address in METADATA_ADDRESSES
    )


def validate_self_hosted_url(url):
    """Refuse a self-hosted server URL that points somewhere no server lives.

    A name that does not resolve is let through: the request itself then
    fails with the ordinary connection error the user already sees today.
    """
    try:
        parsed = urlparse(str(url or "").strip())
        hostname = (parsed.hostname or "").rstrip(".")
    except ValueError as error:
        msg = "This server address could not be read."
        raise SelfHostedUrlError(REASON_UNPARSABLE_URL, msg) from error
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        msg = "Only http and https server addresses are supported."
        raise SelfHostedUrlError(REASON_FORBIDDEN_SCHEME, msg)
    if not hostname:
        msg = "This server address has no host."
        raise SelfHostedUrlError(REASON_MISSING_HOST, msg)

    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except ValueError:
            continue
        if _self_hosted_address_is_forbidden(address):
            msg = "This server address is not one Floppy will contact."
            raise SelfHostedUrlError(REASON_FORBIDDEN_ADDRESS, msg)


def send_to_self_hosted(send, url, **kwargs):
    """Send one request to a user's self-hosted server through the policy.

    ``send`` is the ``requests`` callable the caller already used
    (``requests.get``, or ``functools.partial(requests.request, method)``);
    it is passed in so each module's own ``requests`` stays patchable in tests.
    """
    kwargs["allow_redirects"] = False
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        validate_self_hosted_url(current)
        response = send(current, **kwargs)
        if response.status_code not in SELF_HOSTED_REDIRECT_STATUSES:
            return response

        location = response.headers.get("Location")
        if not location:
            return response
        target = requests.compat.urljoin(current, location)
        if urlparse(target).hostname != urlparse(current).hostname or (
            urlparse(current).scheme.lower() == "https"
            and urlparse(target).scheme.lower() != "https"
        ):
            response.close()
            msg = (
                "The server redirected to a different host or an insecure connection. "
                "Enter the address it redirects to instead."
            )
            raise SelfHostedUrlError(REASON_CROSS_HOST_REDIRECT, msg)
        response.close()
        current = target

    msg = "The server redirected too many times."
    raise SelfHostedUrlError(REASON_TOO_MANY_REDIRECTS, msg)

# --- Pinned self-hosted transport (legacy send_to_self_hosted remains intact) ---

REASON_HTTPS_DOWNGRADE = "https_downgrade"
REASON_CROSS_PORT_REDIRECT = "cross_port_redirect"
HTTP_DEFAULT_PORT = 80
HTTPS_DEFAULT_PORT = 443
SELF_HOSTED_SEE_OTHER = 303
SELF_HOSTED_POST_TO_GET = frozenset({301, 302})

def _validated_self_hosted_target(url, *, require_resolution=False):
    """Validate a self-hosted target and retain the resolved addresses.

    Outbound transport callers must require successful DNS resolution.
    The address selected for connection must come from this result.
    """
    try:
        parsed = urlparse(str(url or "").strip())
        hostname = (parsed.hostname or "").rstrip(".")
        credentials_in_url = parsed.username is not None or parsed.password is not None
        port = parsed.port
    except ValueError as error:
        msg = "This server address could not be read."
        raise SelfHostedUrlError(REASON_UNPARSABLE_URL, msg) from error

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        msg = "Only http and https server addresses are supported."
        raise SelfHostedUrlError(REASON_FORBIDDEN_SCHEME, msg)

    if credentials_in_url:
        msg = "Credentials must not be embedded in a server URL."
        raise SelfHostedUrlError(REASON_CREDENTIALS_IN_URL, msg)

    if not hostname:
        msg = "This server address has no host."
        raise SelfHostedUrlError(REASON_MISSING_HOST, msg)

    if port == 0:
        msg = "This server address has an invalid port."
        raise SelfHostedUrlError(REASON_UNPARSABLE_URL, msg)

    # Use the same IDNA-normalized host for DNS, HTTP Host and TLS.
    try:
        prepared = requests.PreparedRequest()
        prepared.prepare_url(parsed.geturl(), None)
        parsed = urlparse(prepared.url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except (requests.RequestException, ValueError, UnicodeError) as error:
        msg = "This server address could not be read."
        raise SelfHostedUrlError(REASON_UNPARSABLE_URL, msg) from error

    try:
        infos = socket.getaddrinfo(
            hostname,
            None,
            proto=socket.IPPROTO_TCP,
        )
    except (socket.gaierror, UnicodeError) as error:
        if require_resolution:
            msg = "This server hostname could not be resolved."
            raise SelfHostedUrlError(REASON_UNRESOLVABLE_HOST, msg) from error
        return parsed, []

    addresses = []

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        except ValueError:
            continue

        if _self_hosted_address_is_forbidden(address):
            msg = "This server address is not one Floppy will contact."
            raise SelfHostedUrlError(REASON_FORBIDDEN_ADDRESS, msg)

        if address not in addresses:
            addresses.append(address)

    if require_resolution and not addresses:
        msg = "This server hostname could not be resolved."
        raise SelfHostedUrlError(REASON_UNRESOLVABLE_HOST, msg)

    return parsed, addresses




class _SelfHostedBoundedRaw:
    """Limit raw and decoded streaming reads without buffering the whole body."""

    def __init__(self, raw, max_bytes, deadline):
        self._raw = raw
        self._max_bytes = max_bytes
        self._read_bytes = 0
        self._deadline = deadline

    def _account(self, chunk):
        self._read_bytes += len(chunk)
        if self._read_bytes > self._max_bytes:
            raise SelfHostedUrlError(
                REASON_RESPONSE_TOO_LARGE, "This server response is too large."
            )
        if time.monotonic() >= self._deadline:
            raise SelfHostedUrlError(
                REASON_DEADLINE_EXCEEDED, "This server took too long to respond."
            )
        return chunk

    def read(self, amt=None, *args, **kwargs):
        # A raw.read() without an amount must never buffer an unlimited body.
        remaining = self._max_bytes - self._read_bytes
        limit = max(1, remaining + 1)
        if amt is None or amt < 0:
            amt = limit
        else:
            amt = min(amt, limit)
        return self._account(self._raw.read(amt, *args, **kwargs))

    def stream(self, amt=CHUNK_SIZE, *args, **kwargs):
        # urllib3's stream returns decoded bytes when decode_content=True.
        # These are the bytes Requests' iter_content() and .content consume.
        if not isinstance(amt, int) or amt <= 0:
            amt = CHUNK_SIZE
        for chunk in self._raw.stream(min(amt, CHUNK_SIZE), *args, **kwargs):
            yield self._account(chunk)

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _self_hosted_timeouts(requested, deadline):
    """Clamp caller timeouts to the common elapsed-time budget."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SelfHostedUrlError(
            REASON_DEADLINE_EXCEEDED, "This server took too long to respond."
        )
    if requested is None:
        requested = (CONNECT_TIMEOUT, READ_TIMEOUT)
    if isinstance(requested, tuple) and len(requested) == 2:
        connect, read = requested
    else:
        connect = read = requested

    def clamp(value, fallback):
        if value is None:
            value = fallback
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Invalid self-hosted timeout.") from error
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid self-hosted timeout.")
        return min(value, remaining)

    return clamp(connect, CONNECT_TIMEOUT), clamp(read, READ_TIMEOUT)


def _send_pinned_self_hosted(method, parsed, address, *, deadline, max_bytes, **kwargs):
    """Send using the validated IP while retaining the origin's HTTP/TLS name."""
    request_kwargs = dict(kwargs)
    if request_kwargs.pop("proxies", None):
        raise SelfHostedUrlError(
            REASON_FORBIDDEN_ADDRESS, "Proxies are not supported for this request."
        )
    requested_timeout = request_kwargs.pop("timeout", None)
    streaming = bool(request_kwargs.pop("stream", False))
    request_kwargs["allow_redirects"] = False

    hostname = (parsed.hostname or "").lower().rstrip(".")
    headers = dict(request_kwargs.pop("headers", None) or {})
    headers = {key: value for key, value in headers.items() if key.lower() != "host"}
    headers["Host"] = _host_header_value(hostname)
    if parsed.port is not None:
        headers["Host"] += f":{parsed.port}"

    session = _pinned_session(address, hostname, parsed.scheme.lower(), deadline=deadline)
    response = None
    try:
        response = session.request(
            method.upper(),
            _pinned_url(parsed, address),
            headers=headers,
            timeout=_self_hosted_timeouts(requested_timeout, deadline),
            stream=True,
            **request_kwargs,
        )

        # Avoid an unlimited body read, including gzip decompression.
        if response.status_code not in SELF_HOSTED_REDIRECT_STATUSES:
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise SelfHostedUrlError(
                    REASON_RESPONSE_TOO_LARGE, "This server response is too large."
                )
            response.raw = _SelfHostedBoundedRaw(response.raw, max_bytes, deadline)

        if response.status_code in SELF_HOSTED_REDIRECT_STATUSES or streaming:
            # Redirects only need headers. Streams retain the session until
            # their caller closes the response; GC also releases abandoned ones.
            finalizer = weakref.finalize(response, session.close)
            original_close = response.close

            def close_owned_response():
                try:
                    original_close()
                finally:
                    finalizer()

            response.close = close_owned_response
            return response

        try:
            body = _read_bounded(response, deadline=deadline, max_bytes=max_bytes)
        except UnsafeUrlError as error:
            raise SelfHostedUrlError(error.reason_code, str(error)) from error
        response._content = body
        response._content_consumed = True
        response.close()
        session.close()
        return response
    except Exception as error:
        if response is not None:
            response.close()
        session.close()
        if isinstance(error, requests.RequestException) and time.monotonic() >= deadline:
            raise SelfHostedUrlError(
                REASON_DEADLINE_EXCEEDED, "This server took too long to respond."
            ) from error
        raise


def _checked_self_hosted_redirect(current_url, location):
    """Validate a redirect without allowing its origin or port to pivot."""
    if not isinstance(location, str) or not location.strip():
        msg = "The server returned a redirect without a destination."
        raise SelfHostedUrlError(REASON_INVALID_REDIRECT, msg)

    try:
        target_url = requests.compat.urljoin(current_url, location)
        prepared = requests.PreparedRequest()
        prepared.prepare_url(target_url, None)
        target_url = prepared.url

        previous = urlparse(current_url)
        target = urlparse(target_url)

        previous_port = previous.port
        target_port = target.port
    except (ValueError, requests.RequestException) as error:
        msg = "The server returned an invalid redirect."
        raise SelfHostedUrlError(REASON_INVALID_REDIRECT, msg) from error

    if target.scheme.lower() not in ALLOWED_SCHEMES:
        msg = "The redirect uses an unsupported protocol."
        raise SelfHostedUrlError(REASON_FORBIDDEN_SCHEME, msg)

    if target.username is not None or target.password is not None:
        msg = "Redirect destinations may not embed credentials."
        raise SelfHostedUrlError(REASON_CREDENTIALS_IN_URL, msg)

    previous_host = (previous.hostname or "").lower().rstrip(".")
    target_host = (target.hostname or "").lower().rstrip(".")

    if not target_host or previous_host != target_host:
        msg = "An integration redirect may not change hostname."
        raise SelfHostedUrlError(REASON_CROSS_HOST_REDIRECT, msg)

    if previous.scheme.lower() == "https" and target.scheme.lower() == "http":
        msg = "An integration redirect may not downgrade HTTPS."
        raise SelfHostedUrlError(REASON_HTTPS_DOWNGRADE, msg)

    if previous_port is None:
        previous_port = (
            HTTPS_DEFAULT_PORT
            if previous.scheme.lower() == "https"
            else HTTP_DEFAULT_PORT
        )

    if target_port is None:
        target_port = (
            HTTPS_DEFAULT_PORT
            if target.scheme.lower() == "https"
            else HTTP_DEFAULT_PORT
        )

    normal_https_upgrade = (
        previous.scheme.lower() == "http"
        and target.scheme.lower() == "https"
        and previous_port == HTTP_DEFAULT_PORT
        and target_port == HTTPS_DEFAULT_PORT
    )

    if previous_port != target_port and not normal_https_upgrade:
        msg = "An integration redirect may not change to another service port."
        raise SelfHostedUrlError(REASON_CROSS_PORT_REDIRECT, msg)

    return target_url




def send_to_self_hosted_pinned(
    method, url, *, total_timeout=SELF_HOSTED_TOTAL_TIMEOUT,
    max_bytes=SELF_HOSTED_MAX_BYTES, **kwargs
):
    """Use one validated IP through a same-host redirect chain.

    The elapsed-time budget includes all hops and buffered body reads,
    with socket cancellation after DNS resolution. OS DNS resolver calls
    remain subject to OS timeouts. All bodies, including streamed bodies
    read through Requests' iter_content()/content or raw read/stream, have
    a decoded-byte budget by default. Use max_bytes for larger legitimate
    payloads; streaming callers must still close responses.
    """
    if (
        not isinstance(total_timeout, (int, float))
        or not math.isfinite(total_timeout)
        or total_timeout <= 0
    ):
        raise ValueError("total_timeout must be a positive finite number")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    deadline = time.monotonic() + total_timeout
    parsed, addresses = _validated_self_hosted_target(url, require_resolution=True)
    if time.monotonic() >= deadline:
        raise SelfHostedUrlError(
            REASON_DEADLINE_EXCEEDED, "This server took too long to respond."
        )

    pinned_address = addresses[0]
    current_url = parsed.geturl()
    current_method = method.upper()
    request_kwargs = dict(kwargs)
    request_kwargs["allow_redirects"] = False

    for _hop in range(MAX_REDIRECTS + 1):
        response = _send_pinned_self_hosted(
            current_method, parsed, pinned_address,
            deadline=deadline, max_bytes=max_bytes, **request_kwargs
        )
        if response.status_code not in SELF_HOSTED_REDIRECT_STATUSES:
            return response

        try:
            next_url = _checked_self_hosted_redirect(
                current_url, response.headers.get("Location")
            )
        finally:
            response.close()

        if (
            response.status_code == SELF_HOSTED_SEE_OTHER and current_method != "HEAD"
        ) or (
            response.status_code in SELF_HOSTED_POST_TO_GET and current_method == "POST"
        ):
            current_method = "GET"
            for key in ("data", "json", "files"):
                request_kwargs.pop(key, None)
        request_kwargs.pop("params", None)
        current_url = next_url
        parsed = urlparse(current_url)

    raise SelfHostedUrlError(
        REASON_TOO_MANY_REDIRECTS, "The self-hosted server redirected too many times."
    )
