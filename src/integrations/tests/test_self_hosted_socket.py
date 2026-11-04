"""Exercise the self-hosted pinned transport over real loopback sockets."""

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from django.test import SimpleTestCase

from integrations import safe_fetch


class _ServiceHandler(BaseHTTPRequestHandler):
    """Record which Host and authentication headers reach the server."""

    def do_GET(self):
        """Serve a same-origin redirect followed by a JSON response."""
        self.server.observations.append(
            (
                self.path,
                self.headers.get("Host"),
                self.headers.get("X-Api-Key"),
            )
        )

        if self.path == "/first":
            self.send_response(302)
            self.send_header("Location", "/second")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        """Keep the offline regression test quiet."""


class SelfHostedSocketTests(SimpleTestCase):
    """Prove the real HTTP transport cannot re-resolve the origin."""

    def test_real_socket_stays_pinned_across_redirect(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _ServiceHandler,
        )
        server.observations = []

        worker = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        worker.start()

        original_lookup = socket.getaddrinfo
        origin_lookups = []
        port = server.server_address[1]

        def rebinding_lookup(host, *args, **kwargs):
            if host == "rebinding.test":
                origin_lookups.append(host)

                # A second lookup would be capable of returning an
                # attacker-controlled address. Fail before any dial.
                if len(origin_lookups) > 1:
                    msg = "DNS rebinding: origin resolved more than once"
                    raise AssertionError(msg)

                return [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        ("127.0.0.1", 0),
                    )
                ]

            # Numeric-address socket connections remain real.
            return original_lookup(host, *args, **kwargs)

        proxy_environment = {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "http_proxy": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "all_proxy": "http://127.0.0.1:1",
            "NO_PROXY": "",
            "no_proxy": "",
        }

        try:
            with (
                patch.object(
                    socket,
                    "getaddrinfo",
                    side_effect=rebinding_lookup,
                ),
                patch.dict(os.environ, proxy_environment),
            ):
                response = safe_fetch.send_to_self_hosted_pinned(
                    "GET",
                    f"http://rebinding.test:{port}/first",
                    headers={"X-Api-Key": "test-key"},
                    timeout=(3, 3),
                )

            response.raise_for_status()
            self.assertEqual(response.json(), {"ok": True})

            self.assertEqual(
                origin_lookups,
                ["rebinding.test"],
            )

            expected_host = f"rebinding.test:{port}"

            self.assertEqual(
                server.observations,
                [
                    ("/first", expected_host, "test-key"),
                    ("/second", expected_host, "test-key"),
                ],
            )
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()

        self.assertFalse(worker.is_alive())


# A real TLS handshake verifies more than inspecting the adapter configuration.
# Generate an ephemeral certificate locally, never contacting an outside server.


class SelfHostedTLSNameTests(SimpleTestCase):
    def test_tls_verifies_original_hostname_and_sends_sni(self):
        import shutil
        import ssl
        import subprocess
        import tempfile
        from pathlib import Path

        import requests

        openssl = shutil.which("openssl")
        if openssl is None:
            self.skipTest("OpenSSL executable unavailable for offline TLS fixture")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, _format, *_args):
                pass

        class QuietTLSServer(ThreadingHTTPServer):
            def handle_error(self, *_args):
                # A client rejecting the certificate may abort its socket.
                pass

        with tempfile.TemporaryDirectory(prefix="floppy-c07-tls-") as tmp:
            certificate = Path(tmp) / "cert.pem"
            key = Path(tmp) / "key.pem"
            subprocess.run(  # noqa: S603 - fixed local test fixture, no shell
                [
                    openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "ec",
                    "-pkeyopt",
                    "ec_paramgen_curve:P-256",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(certificate),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=other.home",
                    "-addext",
                    "subjectAltName=DNS:other.home",
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )

            server = QuietTLSServer(("127.0.0.1", 0), Handler)
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            # Explicitly exclude TLS 1.0/1.1, including on older Python builds.
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            tls_context.load_cert_chain(certfile=str(certificate), keyfile=str(key))
            seen_names = []
            tls_context.set_servername_callback(
                lambda _socket, server_name, _context: seen_names.append(server_name)
            )
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()

            port = server.server_address[1]
            original_lookup = socket.getaddrinfo

            def service_lookup(host, *args, **kwargs):
                if host in ("other.home", "wrong.home"):
                    return [
                        (
                            socket.AF_INET,
                            socket.SOCK_STREAM,
                            socket.IPPROTO_TCP,
                            "",
                            ("127.0.0.1", 0),
                        )
                    ]
                return original_lookup(host, *args, **kwargs)

            try:
                with patch.object(socket, "getaddrinfo", side_effect=service_lookup):
                    good = safe_fetch.send_to_self_hosted_pinned(
                        "GET",
                        f"https://other.home:{port}/",
                        verify=str(certificate),
                        timeout=2,
                        total_timeout=5,
                    )
                    self.assertEqual(good.content, b"ok")

                    with self.assertRaises(requests.exceptions.SSLError):
                        safe_fetch.send_to_self_hosted_pinned(
                            "GET",
                            f"https://wrong.home:{port}/",
                            verify=str(certificate),
                            timeout=2,
                            total_timeout=5,
                        )
                # Exception wording varies across OpenSSL and urllib3 versions.
                self.assertEqual(seen_names, ["other.home", "wrong.home"])
            finally:
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
            self.assertFalse(worker.is_alive())


class SelfHostedResourceLimitSocketTests(SimpleTestCase):
    def _serve(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        return server, worker

    def test_slow_drip_cannot_hold_pinned_connection_indefinitely(self):
        import time
        from contextlib import suppress

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "200")
                self.end_headers()
                with suppress(BrokenPipeError, ConnectionResetError, OSError):
                    for _ in range(40):
                        self.wfile.write(b"12345")
                        self.wfile.flush()
                        time.sleep(0.04)

            def log_message(self, _format, *_args):
                pass

        server, worker = self._serve(Handler)
        try:
            started = time.monotonic()
            with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
                safe_fetch.send_to_self_hosted_pinned(
                    "GET",
                    f"http://127.0.0.1:{server.server_address[1]}/",
                    timeout=(3, 3),
                    total_timeout=0.2,
                )
            self.assertEqual(caught.exception.reason_code, "deadline_exceeded")
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
        self.assertFalse(worker.is_alive())

    def test_compressed_body_is_limited_after_decompression(self):
        import gzip

        payload = gzip.compress(b"a" * 10000)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format, *_args):
                pass

        server, worker = self._serve(Handler)
        try:
            with self.assertRaises(safe_fetch.SelfHostedUrlError) as caught:
                safe_fetch.send_to_self_hosted_pinned(
                    "GET",
                    f"http://127.0.0.1:{server.server_address[1]}/",
                    total_timeout=5,
                    max_bytes=200,
                )
            self.assertEqual(caught.exception.reason_code, "response_too_large")
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
        self.assertFalse(worker.is_alive())
