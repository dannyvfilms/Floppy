"""Keep ordinary tests offline while modelling a real connection failure."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import requests

_ALLOW_NETWORK_ENV = "FLOPPY_TEST_ALLOW_NETWORK"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_GUARD_MARKER = "__floppy_test_network_guard__"
_ORIGINAL_REQUEST = requests.sessions.Session.request


class UnexpectedExternalNetworkAccessError(requests.ConnectionError):
    """Report blocked external HTTP as the connection failure production handles."""


def test_network_enabled() -> bool:
    """Return whether this test process explicitly allows external HTTP."""
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


def install_test_network_guard() -> None:
    """Install the requests guard once unless this is an explicit network run."""
    if test_network_enabled():
        return

    current = requests.sessions.Session.request
    if getattr(current, _GUARD_MARKER, False):
        return

    setattr(_guarded_request, _GUARD_MARKER, True)
    requests.sessions.Session.request = _guarded_request
