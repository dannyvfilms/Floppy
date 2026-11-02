import asyncio
import os
import socket
from unittest import TestCase, mock

import aiohttp
import requests

from config.test_network import (
    UnexpectedExternalNetworkAccessError,
    install_test_network_guard,
    test_network_enabled,
    test_url_is_local,
)


class TestNetworkIsolationTests(TestCase):
    def setUp(self):
        # Exercise the offline policy even in an explicitly network-enabled
        # full run, then restore the caller's requests transport and opt-in.
        self.enterContext(
            mock.patch.dict(os.environ, {"FLOPPY_TEST_ALLOW_NETWORK": "0"})
        )
        self.enterContext(
            mock.patch(
                "requests.sessions.Session.request", requests.sessions.Session.request
            )
        )
        install_test_network_guard()

    def test_loopback_urls_are_allowed_by_policy(self):
        for url in (
            "http://127.0.0.1:8000/health/",
            "http://localhost:8080/",
            "http://[::1]:8000/",
        ):
            with self.subTest(url=url):
                self.assertTrue(test_url_is_local(url))

    def test_public_urls_are_not_local(self):
        self.assertFalse(test_url_is_local("https://api.themoviedb.org/3/movie/1"))
        self.assertFalse(test_url_is_local("https://musicbrainz.org/ws/2"))

    def test_external_requests_fail_before_network_io(self):
        with self.assertRaisesRegex(
            UnexpectedExternalNetworkAccessError,
            "External HTTP is disabled for ordinary tests",
        ) as error:
            requests.get("https://example.com/provider-fixture", timeout=30)

        self.assertIsInstance(error.exception, requests.ConnectionError)

    def test_explicit_network_run_is_detected(self):
        with mock.patch.dict(os.environ, {"FLOPPY_TEST_ALLOW_NETWORK": "1"}):
            self.assertTrue(test_network_enabled())

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(test_network_enabled())

    def test_external_dns_is_blocked(self):
        with self.assertRaisesRegex(socket.gaierror, "socket.getaddrinfo"):
            socket.getaddrinfo("example.com", 443)
        with self.assertRaises(socket.gaierror):
            socket.gethostbyname("example.com")
        with self.assertRaises(socket.gaierror):
            socket.gethostbyaddr("192.0.2.1")
        with self.assertRaises(socket.gaierror):
            socket.getnameinfo(("192.0.2.1", 443), 0)

    def test_external_tcp_and_udp_are_blocked(self):
        for family, address in (
            (socket.AF_INET, ("192.0.2.1", 443)),
            (socket.AF_INET6, ("2001:db8::1", 443, 0, 0)),
        ):
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                with (
                    self.subTest(family=family, kind=kind),
                    socket.socket(family, kind) as sock,
                ):
                    with self.assertRaises(UnexpectedExternalNetworkAccessError):
                        sock.connect(address)
                    if kind == socket.SOCK_DGRAM:
                        with self.assertRaises(UnexpectedExternalNetworkAccessError):
                            sock.sendto(b"offline", address)
                        with self.assertRaises(UnexpectedExternalNetworkAccessError):
                            sock.sendmsg([b"offline"], [], 0, address)

    def test_ip_literal_resolution_stays_local_and_preserves_url_validation(self):
        addresses = socket.getaddrinfo("169.254.169.254", 80, type=socket.SOCK_STREAM)
        self.assertTrue(addresses)
        self.assertTrue(all(info[4][0] == "169.254.169.254" for info in addresses))

        from integrations.safe_fetch import SelfHostedUrlError, validate_self_hosted_url

        with self.assertRaises(SelfHostedUrlError) as error:
            validate_self_hosted_url("http://169.254.169.254/")
        self.assertEqual(error.exception.reason_code, "forbidden_address")

    def test_aiohttp_is_blocked_before_connecting(self):
        async def fetch():
            async with aiohttp.ClientSession() as session:
                await session.get(
                    "http://192.0.2.1/", timeout=aiohttp.ClientTimeout(total=1)
                )

        with self.assertRaises(aiohttp.ClientConnectorError) as error:
            asyncio.run(fetch())
        self.assertIsInstance(
            error.exception.os_error, UnexpectedExternalNetworkAccessError
        )

    def test_loopback_tcp_and_unix_sockets_still_work(self):
        with socket.socket() as server, socket.socket() as client:
            server.bind(("127.0.0.1", 0))
            server.listen()
            client.settimeout(1)
            client.connect(server.getsockname())
            peer, _ = server.accept()
            peer.close()
        left, right = socket.socketpair()
        with left, right:
            left.sendall(b"local")
            self.assertEqual(right.recv(5), b"local")

    def test_network_opt_in_does_not_install_guards(self):
        with (
            mock.patch.dict(os.environ, {"FLOPPY_TEST_ALLOW_NETWORK": "1"}),
            mock.patch("config.test_network.sys.addaudithook") as add_hook,
            mock.patch("requests.sessions.Session.request") as request,
        ):
            install_test_network_guard()
            add_hook.assert_not_called()
            self.assertIs(requests.sessions.Session.request, request)
