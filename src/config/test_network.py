"""Keep ordinary tests offline while modelling a real connection failure."""

from __future__ import annotations

import os
import socket
import sys
from ipaddress import ip_address
from urllib.parse import urlsplit

import requests

_ALLOW_NETWORK_ENV = "FLOPPY_TEST_ALLOW_NETWORK"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_GUARD_MARKER = "__floppy_test_network_guard__"
_ORIGINAL_REQUEST = requests.sessions.Session.request
_socket_guard_installed = False


class UnexpectedExternalNetworkAccessError(requests.ConnectionError):
    """Report blocked external HTTP as the connection failure production handles."""


def test_network_enabled() -> bool:
    """Return whether this test process explicitly allows external networking."""
    return os.environ.get(_ALLOW_NETWORK_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def test_url_is_local(url: object) -> bool:
    """Return whether an HTTP URL targets a loopback host."""
    hostname = urlsplit(str(url)).hostname
    return bool(hostname and hostname.lower() in _LOCAL_HOSTS)


def _guarded_request(session, method, url, *args, **kwargs):
    if test_url_is_local(url):
        return _ORIGINAL_REQUEST(session, method, url, *args, **kwargs)

    hostname = urlsplit(str(url)).hostname or "<unknown>"
    message = (
        "External HTTP is disabled for ordinary tests: "
        f"{str(method).upper()} {hostname}. Mock the provider boundary or mark "
        "the test with the network tag and run scripts/test.sh --network."
    )
    raise UnexpectedExternalNetworkAccessError(message)


def _guard_socket_event(event, args):
    """Block external DNS and sockets, including clients other than requests."""
    if event in {"socket.connect", "socket.sendto", "socket.sendmsg"}:
        sock, address = args
        # Unix sockets (including multiprocessing pipes) stay available.
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return
        host = address[0]
    elif event == "socket.getnameinfo":
        host = args[0][0]
    elif event in {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
    }:
        host = args[0]
    else:
        return

    if test_network_enabled() or host is None:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if host == "localhost":
        return
    try:
        address = ip_address(host)
        # getaddrinfo parses an IP literal locally. URL validators still need
        # its real address; outbound connect/send events remain blocked.
        if address.is_loopback or event == "socket.getaddrinfo":
            return
    except ValueError:
        pass
    message = (
        f"External network is disabled for ordinary tests: {event}. "
        "Mock the provider boundary or mark the test with the network tag "
        "and run scripts/test.sh --network."
    )
    if event.startswith("socket.get"):
        # URL validators handle an unresolvable host before reaching a mocked
        # HTTP transport. Preserve that DNS failure contract without I/O.
        raise socket.gaierror(socket.EAI_NONAME, message)
    raise UnexpectedExternalNetworkAccessError(message)


def install_test_network_guard() -> None:
    """Install HTTP and socket guards once unless this is a network run."""
    global _socket_guard_installed  # noqa: PLW0603

    if test_network_enabled():
        return

    if not _socket_guard_installed:
        sys.addaudithook(_guard_socket_event)
        _socket_guard_installed = True

    current = requests.sessions.Session.request
    if getattr(current, _GUARD_MARKER, False):
        return

    setattr(_guarded_request, _GUARD_MARKER, True)
    requests.sessions.Session.request = _guarded_request
