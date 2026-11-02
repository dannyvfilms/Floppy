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
