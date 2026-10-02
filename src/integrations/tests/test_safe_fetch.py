"""The outbound boundary for user-configured URLs."""

import ipaddress
import socket
from unittest.mock import Mock, patch

import requests
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
            SHUT_RDWR=socket.SHUT_RDWR,
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

    def test_shared_address_space_is_not_public(self):
        for address in ("100.64.0.1", "100.100.100.200", "100.127.255.254"):
            with self.subTest(address=address), public(address):
                self.assert_refused("https://evil.example/", "forbidden_address")

    def test_public_ipv6_address_is_allowed(self):
        with public("2606:4700:4700::1111"):
            self.assertIsNotNone(validate_url("https://example.com/manifest.json"))

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
        session.get.return_value.close.assert_called_once()

    def test_stream_failure_closes_the_response(self):
        response = self.response()
        response.iter_content.side_effect = safe_fetch.requests.ConnectionError(
            "stream failed"
        )
        session = Mock(get=Mock(return_value=response))
        with (
            public("93.184.216.34"),
            self.assertRaises(safe_fetch.requests.ConnectionError),
        ):
            fetch("https://example.com/m.json", session=session)
        response.close.assert_called_once()

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
        session.get.return_value.close.assert_called_once()

    def test_an_undeclared_oversize_response_is_refused_while_streaming(self):
        """A server that lies about its size must not exhaust memory."""
        chunks = (b"x" * 8192 for _ in range(safe_fetch.MAX_BYTES // 8192 + 2))
        session = Mock(get=Mock(return_value=self.response(chunks=chunks)))

        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "response_too_large")
        session.get.return_value.close.assert_called_once()

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


def _response(status, location=None):
    response = Mock(status_code=status, headers={"Location": location} if location else {})
    return response


class SelfHostedPolicyTests(TestCase):
    """Home servers stay reachable; metadata endpoints and host hops do not."""

    def test_home_network_addresses_are_allowed(self):
        """Loopback, LAN, Docker and Tailscale are where these servers live."""
        for address in ("127.0.0.1", "192.168.1.10", "172.18.0.4", "100.101.2.3", "::1"):
            with self.subTest(address=address), public(address):
                safe_fetch.validate_self_hosted_url("http://radarr.home:7878")

    def test_an_unresolvable_host_is_left_to_the_request(self):
        """The connection then fails with the error users already see today."""
        with patch.object(
            safe_fetch.socket, "getaddrinfo", side_effect=safe_fetch.socket.gaierror
        ):
            safe_fetch.validate_self_hosted_url("http://nowhere.invalid")

    def test_metadata_and_link_local_addresses_are_refused(self):
        for address in (
            "169.254.169.254",
            "::ffff:169.254.169.254",
            "fe80::1",
            "fd00:ec2::254",
            "100.100.100.200",
            "224.0.0.1",
        ):
            with self.subTest(address=address), public(address):
                with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
                    safe_fetch.validate_self_hosted_url("http://metadata.example/")
                self.assertEqual(caught.exception.reason_code, "forbidden_address")

    def test_an_unparsable_address_is_a_policy_refusal(self):
        """Callers catch requests errors, so a bad bracketed host must not escape as ValueError."""
        with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
            safe_fetch.validate_self_hosted_url("http://[bad")
        self.assertEqual(caught.exception.reason_code, "unparsable_url")

    def test_refusal_is_a_requests_error_without_the_url(self):
        """Existing ``except requests.RequestException`` handlers catch it."""
        import requests

        with public("169.254.169.254"), self.assertRaises(
            requests.RequestException
        ) as caught:
            safe_fetch.send_to_self_hosted(Mock(), "http://host.example/?apikey=s3cret")
        self.assertNotIn("s3cret", str(caught.exception))

    def test_non_http_schemes_are_refused(self):
        with self.assertRaises(safe_fetch.SelfHostedUrlError):
            safe_fetch.validate_self_hosted_url("file:///etc/passwd")

    def test_same_host_redirect_is_followed_with_headers(self):
        """Moving from http to https on the same server is the common reverse-proxy case."""
        send = Mock(
            side_effect=[
                _response(301, "https://radarr.home/api/v3/movie"),
                _response(200),
            ],
        )
        with public("192.168.1.10"):
            response = safe_fetch.send_to_self_hosted(
                send, "http://radarr.home/api/v3/movie", headers={"X-Api-Key": "k"}
            )

        self.assertEqual(response.status_code, 200)
        second = send.call_args_list[1]
        self.assertEqual(second.args[0], "https://radarr.home/api/v3/movie")
        self.assertEqual(second.kwargs["headers"], {"X-Api-Key": "k"})
        self.assertFalse(second.kwargs["allow_redirects"])

    def test_redirect_to_another_host_is_not_followed(self):
        """Following it would hand the API key to a different server."""
        send = Mock(return_value=_response(302, "http://169.254.169.254/latest"))
        with public("192.168.1.10"), self.assertRaises(
            safe_fetch.SelfHostedUrlError
        ) as caught:
            safe_fetch.send_to_self_hosted(
                send, "http://radarr.home/", headers={"X-Api-Key": "k"}
            )

        self.assertEqual(caught.exception.reason_code, "cross_host_redirect")
        send.assert_called_once()


class _Clock:
    """A controllable monotonic clock for deadline schedules."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class PinnedTransportTests(TestCase):
    """The connection dials the address validation saw; nothing else."""

    def test_wire_url_uses_the_validated_address_and_keeps_the_host_header(self):
        """DNS is consulted once, at validation; the dial target is its answer."""
        session = Mock(get=Mock(return_value=self._response()))
        with public("93.184.216.34"):
            fetch("https://example.com/m.json?q=1", session=session)

        args = session.get.call_args
        self.assertEqual(args.args[0], "https://93.184.216.34/m.json?q=1")
        self.assertEqual(args.kwargs["headers"]["Host"], "example.com")

    def test_international_hostname_uses_one_ascii_identity(self):
        hostname = "xn--wgv71a119e.jp"
        session = Mock(get=Mock(return_value=self._response()))
        with (
            patch.object(
                safe_fetch,
                "resolve_public_addresses",
                return_value=[ipaddress.ip_address("93.184.216.34")],
            ) as resolve,
            patch.object(safe_fetch, "_pinned_session", return_value=session) as transport,
        ):
            fetch("https://日本語.jp/feed")
        resolve.assert_called_once_with(hostname)
        self.assertEqual(transport.call_args.args[1], hostname)
        self.assertEqual(session.get.call_args.kwargs["headers"]["Host"], hostname)

    def test_explicit_port_is_preserved_in_host_header(self):
        for url, host in (
            ("http://example.com:443/feed", "example.com:443"),
            ("https://example.com:80/feed", "example.com:80"),
            ("https://[2606:4700:4700::1111]:443/feed", "[2606:4700:4700::1111]:443"),
        ):
            with self.subTest(url=url), public("93.184.216.34"):
                session = Mock(get=Mock(return_value=self._response()))
                fetch(url, session=session)
                self.assertEqual(session.get.call_args.kwargs["headers"]["Host"], host)

    def test_ipv6_addresses_are_bracketed_on_the_wire_and_in_the_host_header(self):
        session = Mock(get=Mock(return_value=self._response()))
        with public("2606:4700:4700::1111"):
            fetch("https://example.com/m.json", session=session)

        args = session.get.call_args
        self.assertEqual(args.args[0], "https://[2606:4700:4700::1111]/m.json")
        self.assertEqual(args.kwargs["headers"]["Host"], "example.com")

    def test_explicit_default_ports_stay_on_the_wire_url(self):
        session = Mock(get=Mock(return_value=self._response()))
        with public("93.184.216.34"):
            fetch("https://example.com:443/m.json", session=session)
        self.assertEqual(
            session.get.call_args.args[0], "https://93.184.216.34:443/m.json"
        )

    def test_each_redirect_hop_dials_that_hop_validated_address(self):
        redirect = self._response(
            status=302, headers={"Location": "https://other.example/m.json"}
        )
        ok = self._response()
        session = Mock(get=Mock(side_effect=[redirect, ok]))
        with patch.object(
            safe_fetch,
            "resolve_public_addresses",
            side_effect=[
                [ipaddress.ip_address("93.184.216.34")],
                [ipaddress.ip_address("93.184.216.35")],
            ],
        ):
            fetch("https://example.com/m.json", session=session)

        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(
            urls,
            ["https://93.184.216.34/m.json", "https://93.184.216.35/m.json"],
        )
        hosts = [call.kwargs["headers"]["Host"] for call in session.get.call_args_list]
        self.assertEqual(hosts, ["example.com", "other.example"])

    def _response(self, *, status=200, headers=None, chunks=(b"{}",)):
        stub = Mock()
        stub.status_code = status
        stub.headers = headers or {}
        stub.is_redirect = status in (301, 302, 303, 307, 308)
        stub.is_permanent_redirect = status in (301, 308)
        stub.iter_content = Mock(return_value=iter(chunks))
        stub.close = Mock()
        return stub

    def test_pinned_session_mounts_tls_identity_adapter_and_ignores_the_environment(
        self,
    ):
        session = safe_fetch._pinned_session(
            ipaddress.ip_address("93.184.216.34"), "example.com", "https"
        )
        self.addCleanup(session.close)
        self.assertFalse(session.trust_env)
        adapter = session.get_adapter("https://93.184.216.34/m.json")
        self.assertIsInstance(adapter, safe_fetch.PinnedTLSAdapter)
        # TLS identity stays on the original hostname: the certificate is
        # verified against it and it is sent as SNI, while the socket dials
        # the validated address.
        pool_kwargs = adapter.poolmanager.connection_pool_kw
        self.assertEqual(pool_kwargs["assert_hostname"], "example.com")
        self.assertEqual(pool_kwargs["server_hostname"], "example.com")

    def test_environment_proxies_cannot_route_the_fetch(self):
        """A proxy would resolve the hostname itself, bypassing validation."""
        with patch.dict(
            "os.environ",
            {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9"},
        ):
            session = safe_fetch._pinned_session(
                ipaddress.ip_address("93.184.216.34"), "example.com", "https"
            )
            self.addCleanup(session.close)
            settings = session.merge_environment_settings(
                "https://93.184.216.34/m.json", {}, False, True, None
            )
        self.assertEqual(settings["proxies"], {})

    def test_the_socket_dials_the_validated_address(self):
        """On the real transport stack: the dialed tuple is the validated
        address and port, and the Host header on the wire is the origin.
        Driven through ``session.send`` on a socketpair — no network leaves
        the process, and the test network guard stays in place for every
        ordinary ``Session.request`` path.
        """
        import socket as socket_module
        import threading

        server, client = socket_module.socketpair()
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        request_bytes = []

        def serve():
            import contextlib

            data = server.recv(65536)
            if not data:
                return
            request_bytes.append(data)
            with contextlib.suppress(OSError):
                server.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 2\r\n"
                    b"Connection: close\r\n\r\nok"
                )

        dialed = []

        def fake_create_connection(address, *args, **kwargs):
            dialed.append(address)
            return client

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with (
                public("93.184.216.34"),
                patch(
                    "urllib3.util.connection.create_connection",
                    side_effect=fake_create_connection,
                ),
            ):
                parsed, addresses = safe_fetch._validate_target(
                    "http://example.com/m.json"
                )
                wire_url = safe_fetch._pinned_url(parsed, addresses[0])
                session = safe_fetch._pinned_session(
                    addresses[0],
                    "example.com",
                    "http",
                    deadline=safe_fetch.time.monotonic() + 5,
                )
                self.addCleanup(session.close)
                prepared = session.prepare_request(
                    requests.Request(
                        "GET",
                        wire_url,
                        headers={"Host": "example.com", "User-Agent": "Floppy"},
                    )
                )
                response = session.send(prepared, timeout=(5, 10), stream=True)
                body = safe_fetch._read_bounded(response)
                response.close()
                adapter = session.get_adapter(wire_url)
                guards = list(adapter._deadline_sockets)
                self.assertEqual(len(guards), 1)
                session.close()
                for timer, duplicate in guards:
                    self.assertFalse(timer.is_alive())
                    self.assertEqual(duplicate.fileno(), -1)
        finally:
            thread.join(timeout=5)

        self.assertEqual(dialed, [("93.184.216.34", 80)])
        self.assertEqual(body, b"ok")
        self.assertIn(b"Host: example.com\r\n", request_bytes[0])


class SocketDeadlineTests(TestCase):
    def _assert_deadline_interrupts(self, phase):
        import contextlib
        import socket
        import threading
        import time

        server, client = socket.socketpair()
        finished = threading.Event()

        def serve():
            with server, contextlib.suppress(OSError):
                server.recv(65536)
                if phase == "body":
                    server.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
                elif phase == "headers":
                    server.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                else:
                    # A TLS handshake record whose contents arrive slowly.
                    server.sendall(b"\x16\x03\x03\x00\x64")
                for _ in range(50):
                    if finished.wait(0.03):
                        break
                    server.sendall(b"x")

        def send_direct(session, url, **kwargs):
            # Bypass only Django's external-network guard, preserving the
            # real Requests/urllib3/TLS stack over this in-process socket.
            prepared = session.prepare_request(
                requests.Request("GET", url, headers=kwargs.pop("headers"))
            )
            return session.send(prepared, **kwargs)

        thread = threading.Thread(target=serve)
        thread.start()
        started = time.monotonic()
        try:
            with (
                public("93.184.216.34"),
                patch("urllib3.util.connection.create_connection", return_value=client),
                patch.object(requests.Session, "get", new=send_direct),
                self.assertRaises(UnsafeUrlError) as caught,
            ):
                scheme = "https" if phase == "tls" else "http"
                fetch(f"{scheme}://example.com/", total_timeout=0.15)
            self.assertEqual(caught.exception.reason_code, "deadline_exceeded")
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            finished.set()
            client.close()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_deadline_interrupts_a_buffered_body(self):
        self._assert_deadline_interrupts("body")

    def test_deadline_interrupts_buffered_headers(self):
        self._assert_deadline_interrupts("headers")

    def test_deadline_interrupts_tls_negotiation(self):
        self._assert_deadline_interrupts("tls")


class DeadlineTests(TestCase):
    """One wall-clock budget covers validation, hops and the body."""

    def setUp(self):
        self.clock = _Clock()
        patcher = patch.object(safe_fetch, "time", Mock(monotonic=self.clock.monotonic))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _response(self, *, status=200, headers=None, chunks=(b"{}",)):
        stub = Mock()
        stub.status_code = status
        stub.headers = headers or {}
        stub.is_redirect = status in (301, 302, 303, 307, 308)
        stub.is_permanent_redirect = status in (301, 308)
        stub.iter_content = Mock(return_value=iter(chunks))
        stub.close = Mock()
        return stub

    def test_socket_timeouts_are_clamped_to_the_remaining_budget(self):
        session = Mock(get=Mock(return_value=self._response()))
        with public("93.184.216.34"):
            fetch("https://example.com/m.json", session=session, total_timeout=7)
        self.assertEqual(session.get.call_args.kwargs["timeout"], (5, 7))

        session2 = Mock(get=Mock(return_value=self._response()))
        with public("93.184.216.34"):
            fetch("https://example.com/m.json", session=session2, total_timeout=3)
        self.assertEqual(session2.get.call_args.kwargs["timeout"], (3, 3))

    def test_budget_exhausted_before_a_hop_is_refused(self):
        """The redirect hop itself consumed the whole budget; the next hop
        is refused before any request is made.
        """

        def redirect_and_burn(*args, **kwargs):
            self.clock.now += 11
            return self._response(
                status=302, headers={"Location": "https://example.com/next"}
            )

        session = Mock(get=Mock(side_effect=redirect_and_burn))
        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session, total_timeout=10)

        self.assertEqual(caught.exception.reason_code, "deadline_exceeded")
        self.assertEqual(session.get.call_count, 1)

    def test_slow_drip_body_stops_at_the_deadline(self):
        """A stream that never trips a single read timeout still ends."""

        def chunks():
            yield b"aaaa"
            self.clock.now += 6
            yield b"bbbb"
            self.clock.now += 6
            yield b"cccc"

        session = Mock(get=Mock(return_value=self._response(chunks=chunks())))
        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session, total_timeout=10)

        self.assertEqual(caught.exception.reason_code, "deadline_exceeded")
        session.get.return_value.close.assert_called_once()

    def test_compressed_expansion_is_bounded_by_decoded_bytes(self):
        """iter_content yields decoded data; a gzip bomb is refused by its
        expanded size even when the declared length is tiny.
        """

        def chunks():
            for _ in range(safe_fetch.MAX_BYTES // 8192 + 2):
                yield b"x" * 8192

        response = self._response(
            headers={"Content-Encoding": "gzip", "Content-Length": "100"},
            chunks=chunks(),
        )
        session = Mock(get=Mock(return_value=response))
        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_a_garbage_content_length_is_ignored_and_streaming_still_bounds(self):
        response = self._response(
            headers={"Content-Length": "later"},
            chunks=(b"x" * 8192 for _ in range(safe_fetch.MAX_BYTES // 8192 + 2)),
        )
        session = Mock(get=Mock(return_value=response))
        with public("93.184.216.34"), self.assertRaises(UnsafeUrlError) as caught:
            fetch("https://example.com/m.json", session=session)

        self.assertEqual(caught.exception.reason_code, "response_too_large")

    def test_owned_sessions_are_closed_when_the_fetch_completes(self):
        owned = Mock(get=Mock(return_value=self._response()))
        with (
            public("93.184.216.34"),
            patch.object(safe_fetch, "_pinned_session", return_value=owned),
        ):
            _response, _body = fetch("https://example.com/m.json")
        owned.get.return_value.close.assert_called_once()
        owned.close.assert_called_once()
