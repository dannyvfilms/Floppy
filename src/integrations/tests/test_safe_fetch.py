"""The outbound boundary for user-configured URLs."""

import ipaddress
from unittest.mock import Mock, patch

from django.test import TestCase

from integrations import safe_fetch
from integrations.safe_fetch import UnsafeUrlError, validate_url
from integrations.safe_fetch import safe_fetch as fetch


def public(*addresses):
    """Patch resolution so a hostname resolves to the given addresses."""
    return patch.object(
        safe_fetch,
        "socket",
        Mock(
            getaddrinfo=Mock(
                return_value=[(0, 0, 0, "", (addr, 0)) for addr in addresses],
            ),
            gaierror=OSError,
        ),
    )


class UrlShapeTests(TestCase):
    """Scheme, credentials, port and host are checked before any lookup."""

    def assert_refused(self, url, reason_code):
        """Assert the URL is refused with a stable reason code."""
        with self.assertRaises(UnsafeUrlError) as caught:
            validate_url(url)
        self.assertEqual(caught.exception.reason_code, reason_code)

    def test_a_public_https_url_is_allowed(self):
        """The ordinary case passes."""
        with public("93.184.216.34"):
            self.assertIsNotNone(validate_url("https://example.com/manifest.json"))

    def test_non_http_schemes_are_refused(self):
        """file:// and gopher:// are not fetchable."""
        self.assert_refused("file:///etc/passwd", "forbidden_scheme")
        self.assert_refused("ftp://example.com/x", "forbidden_scheme")

    def test_credentials_in_the_url_are_refused(self):
        """A URL that carries a password would leak it into logs."""
        self.assert_refused("https://user:pw@example.com/", "credentials_in_url")

    def test_a_non_standard_port_is_refused(self):
        """Port scanning through the fetcher is not a feature."""
        self.assert_refused("https://example.com:2375/", "forbidden_port")

    def test_an_empty_url_is_refused(self):
        """Nothing to fetch is a client error, not a crash."""
        self.assert_refused("", "missing_url")
        self.assert_refused("   ", "missing_url")

    def test_local_names_are_refused_without_resolving(self):
        """Localhost and friends never reach DNS."""
        self.assert_refused("http://localhost/x", "forbidden_address")
        self.assert_refused("http://foo.internal/x", "forbidden_address")
        self.assert_refused("http://printer.lan/x", "forbidden_address")


class ResolutionTests(TestCase):
    """A public name that resolves privately is the SSRF case that matters."""

    def assert_refused(self, url, reason_code):
        """Assert the URL is refused with a stable reason code."""
        with self.assertRaises(UnsafeUrlError) as caught:
            validate_url(url)
        self.assertEqual(caught.exception.reason_code, reason_code)

    def test_a_public_name_resolving_to_loopback_is_refused(self):
        """An IP-literal check would miss this, which is the whole trick."""
        with public("127.0.0.1"):
            self.assert_refused("https://evil.example/", "forbidden_address")

    def test_a_public_name_resolving_to_a_private_range_is_refused(self):
        """Reaching the LAN through a public name is the same attack."""
        for address in ("10.0.0.5", "192.168.1.10", "172.16.0.9"):
            with self.subTest(address=address), public(address):
                self.assert_refused("https://evil.example/", "forbidden_address")

    def test_the_cloud_metadata_endpoint_is_refused(self):
        """169.254.169.254 is link-local, and hands out credentials."""
        with public("169.254.169.254"):
            self.assert_refused("https://evil.example/", "forbidden_address")

    def test_the_ipv6_metadata_endpoint_is_refused(self):
        """The IPv6 route to the same place must close too."""
        with public("fd00:ec2::254"):
            self.assert_refused("https://evil.example/", "forbidden_address")

    def test_a_mixed_answer_is_refused_entirely(self):
        """Which address a later connection picks is not controllable here."""
        with public("93.184.216.34", "127.0.0.1"):
            self.assert_refused("https://evil.example/", "forbidden_address")

    def test_an_unresolvable_host_is_refused(self):
        """A name that does not resolve is a stable, reportable outcome."""
        with patch.object(
            safe_fetch.socket,
            "getaddrinfo",
            side_effect=safe_fetch.socket.gaierror("nope"),
        ):
            self.assert_refused("https://nowhere.example/", "unresolvable_host")

    def test_ipv6_loopback_literal_is_refused(self):
        """The literal path is still covered."""
        self.assertTrue(
            safe_fetch._address_is_forbidden(ipaddress.ip_address("::1")),
        )


class FetchTests(TestCase):
    """Redirects, size and headers are bounded at fetch time."""

    def response(self, *, status=200, headers=None, chunks=(b"{}",)):
        """Build a stub response."""
        stub = Mock()
        stub.status_code = status
        stub.headers = headers or {}
        stub.is_redirect = status in (301, 302, 303, 307, 308)
        stub.is_permanent_redirect = status in (301, 308)
        stub.iter_content = Mock(return_value=iter(chunks))
        stub.close = Mock()
        return stub

    def test_a_plain_fetch_returns_the_body(self):
        """The ordinary case works."""
        session = Mock(get=Mock(return_value=self.response(chunks=(b'{"ok":1}',))))
        with public("93.184.216.34"):
            _, body = fetch("https://example.com/m.json", session=session)

        self.assertEqual(body, b'{"ok":1}')

    def test_only_allowlisted_headers_are_sent(self):
        """No cookie or Authorization header may reach a user-typed host."""
        session = Mock(get=Mock(return_value=self.response()))
        with public("93.184.216.34"):
            fetch(
                "https://example.com/m.json",
                headers={"Authorization": "Bearer secret", "Cookie": "sid=1"},
                session=session,
            )

        sent = session.get.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", sent)
        self.assertNotIn("Cookie", sent)

    def test_a_declared_oversize_response_is_refused(self):
        """Content-Length is checked before the body is read."""
        session = Mock(
            get=Mock(
                return_value=self.response(
                    headers={"Content-Length": str(safe_fetch.MAX_BYTES + 1)},
                ),
            ),
        )
        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_an_undeclared_oversize_response_is_refused_while_streaming(self):
        """A server that lies about its size must not exhaust memory."""
        chunks = (b"x" * 8192 for _ in range(safe_fetch.MAX_BYTES // 8192 + 2))
        session = Mock(get=Mock(return_value=self.response(chunks=chunks)))

        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_a_redirect_to_a_forbidden_host_is_refused(self):
        """A permitted host may redirect, but not to somewhere refused."""
        redirect = self.response(
            status=302,
            headers={"Location": "http://169.254.169.254/latest/meta-data/"},
        )
        session = Mock(get=Mock(return_value=redirect))

        with patch.object(
            safe_fetch,
            "resolve_public_addresses",
            side_effect=[
                [ipaddress.ip_address("93.184.216.34")],
                UnsafeUrlError("forbidden_address", "no"),
            ],
        ), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "forbidden_address")

    def test_a_redirect_loop_is_bounded(self):
        """An endless redirect chain terminates."""
        redirect = self.response(
            status=302,
            headers={"Location": "https://example.com/again"},
        )
        session = Mock(get=Mock(return_value=redirect))

        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "too_many_redirects")

    def test_a_redirect_without_a_destination_is_refused(self):
        """A 302 with no Location is malformed, not a silent success."""
        session = Mock(get=Mock(return_value=self.response(status=302)))

        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "invalid_redirect")

    def test_the_request_is_time_bounded(self):
        """A slow host cannot hold a worker open indefinitely."""
        session = Mock(get=Mock(return_value=self.response()))
        with public("93.184.216.34"):
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(
            session.get.call_args.kwargs["timeout"],
            (safe_fetch.CONNECT_TIMEOUT, safe_fetch.READ_TIMEOUT),
        )

    def test_redirects_are_not_followed_by_the_transport(self):
        """Following them here is what makes per-hop validation possible."""
        session = Mock(get=Mock(return_value=self.response()))
        with public("93.184.216.34"):
            fetch("https://example.com/m.json", session=session)

        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
