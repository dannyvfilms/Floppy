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

**Residual risk, stated rather than hidden:** validation resolves the name and
the connection resolves it again, so a hostile DNS server can answer
differently in between. Closing that window needs the socket pinned to the
validated address. This does not do that; it narrows the window to a single
resolution and re-checks on every redirect.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 3
MAX_BYTES = 1024 * 1024
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
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



class UnsafeUrlError(Exception):
    """Raised when a URL may not be fetched, with a stable reason code."""

    def __init__(self, reason_code, message):
        """Store the reason code alongside the message."""
        super().__init__(message)
        self.reason_code = reason_code


def _address_is_forbidden(address):
    """Return whether one resolved address is outside the public internet."""
    return bool(
        address.is_private
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


def validate_url(url):
    """Validate one URL and return its parsed form, or raise UnsafeUrlError."""
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

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        msg = "This URL has no host."
        raise UnsafeUrlError(REASON_MISSING_HOST, msg)

    if hostname in LOCAL_NAMES or hostname.endswith(LOCAL_SUFFIXES):
        msg = "This address is not on the public internet."
        raise UnsafeUrlError(REASON_FORBIDDEN_ADDRESS, msg)

    resolve_public_addresses(hostname)
    return parsed


def _read_bounded(response):
    """Read at most MAX_BYTES, refusing anything larger."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        msg = "This response is larger than Floppy will fetch."
        raise UnsafeUrlError(REASON_RESPONSE_TOO_LARGE, msg)

    body = bytearray()
    for chunk in response.iter_content(CHUNK_SIZE):
        body.extend(chunk)
        # Checked while streaming, not afterwards: a server that lies about
        # Content-Length, or omits it, must still not be able to exhaust memory.
        if len(body) > MAX_BYTES:
            msg = "This response is larger than Floppy will fetch."
            raise UnsafeUrlError(REASON_RESPONSE_TOO_LARGE, msg)
    return bytes(body)


def safe_fetch(url, *, headers=None, session=None):
    """Fetch ``url`` through the outbound boundary and return (response, body).

    Raises UnsafeUrlError for anything the boundary refuses, and
    requests.RequestException for a transport failure.
    """
    sender = session or requests
    outbound = {"Accept": "application/json", "User-Agent": "Floppy"}
    for name in REQUEST_HEADER_ALLOWLIST:
        if headers and name in headers:
            outbound[name] = headers[name]

    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        validate_url(current)
        response = sender.get(
            current,
            headers=outbound,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            allow_redirects=False,
            stream=True,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                msg = "This redirect had no destination."
                raise UnsafeUrlError(REASON_INVALID_REDIRECT, msg)
            # Re-validated on the next pass: a permitted host is allowed to
            # redirect, but not to somewhere this boundary would have refused.
            current = requests.compat.urljoin(current, location)
            response.close()
            continue

        return response, _read_bounded(response)

    msg = "This URL redirected too many times."
    raise UnsafeUrlError(REASON_TOO_MANY_REDIRECTS, msg)
