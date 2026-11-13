"""The placeholder server that holds the public port during snapshot and migrations."""

import http.client
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from django.test import SimpleTestCase

SRC = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class StartupServerTests(SimpleTestCase):
    """A proxy must get a prompt, retryable answer instead of a connect timeout."""

    def setUp(self):
        self.port = _free_port()
        self.process = subprocess.Popen(  # noqa: S603 - fixed interpreter and module
            [sys.executable, "-m", "config.startup_server", str(self.port)],
            cwd=SRC,
            env={**os.environ, "PYTHONPATH": str(SRC)},
        )
        self.addCleanup(self._stop)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
            except OSError:
                time.sleep(0.1)
            else:
                return
        self.fail("startup server never listened")

    def _stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)

    def _request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_every_path_gets_a_fast_retryable_503(self):
        for method, path in (("GET", "/"), ("GET", "/health/"), ("POST", "/api/v1/x"), ("HEAD", "/")):
            with self.subTest(method=method, path=path):
                response, body = self._request(method, path)
                self.assertEqual(response.status, 503)
                self.assertEqual(response.getheader("Retry-After"), "5")
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                if method == "HEAD":
                    self.assertEqual(body, b"")
                else:
                    self.assertIn(b"Floppy is starting", body)

    def test_sigterm_releases_the_port_for_the_next_listener(self):
        self.process.send_signal(signal.SIGTERM)
        self.assertEqual(self.process.wait(timeout=10), 0)
        with socket.socket() as sock:
            # Real listeners (gunicorn) set SO_REUSEADDR; without it the readiness
            # probe's TIME_WAIT connection can make this bind fail spuriously.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
