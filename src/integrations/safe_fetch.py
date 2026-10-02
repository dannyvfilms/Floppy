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
import logging
import socket
import threading
import time
from contextlib import suppress
from urllib.parse import urlparse, urlunsplit

import requests
from urllib3.connection import HTTPConnection, HTTPSConnection

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 3
MAX_BYTES = 1024 * 1024
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


def _read_bounded(response, deadline=None):
    """Read at most MAX_BYTES of decoded content, refusing anything larger."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
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
        if len(body) > MAX_BYTES:
            msg = "This response is larger than Floppy will fetch."
            raise UnsafeUrlError(REASON_RESPONSE_TOO_LARGE, msg)
        if deadline is not None and time.monotonic() >= deadline:
            raise _deadline_error()
    if deadline is not None and time.monotonic() >= deadline:
        raise _deadline_error()
    return bytes(body)


def safe_fetch(url, *, headers=None, session=None, total_timeout=None):
    """Fetch ``url`` through the outbound boundary and return (response, body).

    The connection is pinned to the address validation resolved: each hop's
    wire URL uses the validated address literal while the Host header and TLS
    verification keep the original hostname. The elapsed-time budget
    (``total_timeout``, default :data:`TOTAL_TIMEOUT`) cancels connected
    sockets, including buffered reads and TLS. DNS resolution remains
    bounded only by OS resolver settings.

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

            try:
                return response, _read_bounded(response, deadline)
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
        if urlparse(target).hostname != urlparse(current).hostname:
            response.close()
            msg = (
                "The server redirected to a different host. "
                "Enter the address it redirects to instead."
            )
            raise SelfHostedUrlError(REASON_CROSS_HOST_REDIRECT, msg)
        response.close()
        current = target

    msg = "The server redirected too many times."
    raise SelfHostedUrlError(REASON_TOO_MANY_REDIRECTS, msg)
