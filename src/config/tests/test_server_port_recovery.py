"""Regression tests for the public listener used during SQLite recovery."""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config import sqlite_recovery_server as recovery
from config.server_port import ServerPortError


class _FakeServer:
    def serve_forever(self) -> None:
        pass

    def server_close(self) -> None:
        pass


class RecoveryServerPortTests(SimpleTestCase):
    report = {
        "total_conflicts": 1,
        "can_quarantine": False,
        "affected": [],
    }

    def test_explicit_runtime_port_owns_recovery_listener_and_disk_copy(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            with (
                mock.patch.object(
                    recovery,
                    "_read_incident_report",
                    return_value=self.report,
                ),
                mock.patch.object(
                    recovery,
                    "ThreadingHTTPServer",
                    return_value=_FakeServer(),
                ) as server_factory,
                mock.patch("sys.stderr"),
            ):
                recovery.serve(db_path, 9123)

            server_factory.assert_called_once_with(("", 9123), recovery._Handler)
            self.assertEqual(recovery._Handler.server_port, 9123)
            page = (Path(tmp_dir) / "floppy-recovery.html").read_text()
            self.assertIn("port 9123 while the container runs", page)
            self.assertNotIn("port 8000 while the container runs", page)

    def test_direct_recovery_uses_shared_listener_resolver(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            with (
                mock.patch.object(
                    recovery,
                    "resolve_server_port",
                    return_value=9444,
                ) as resolver,
                mock.patch.object(
                    recovery,
                    "_read_incident_report",
                    return_value=self.report,
                ),
                mock.patch.object(
                    recovery,
                    "ThreadingHTTPServer",
                    return_value=_FakeServer(),
                ) as server_factory,
                mock.patch("sys.stderr"),
            ):
                recovery.serve(db_path)

            resolver.assert_called_once_with()
            server_factory.assert_called_once_with(("", 9444), recovery._Handler)

    def test_invalid_explicit_recovery_port_fails_before_bind(self):
        with mock.patch.object(recovery, "ThreadingHTTPServer") as server_factory:
            with self.assertRaises(ServerPortError):
                recovery.serve("db.sqlite3", "8000; echo bad")

        server_factory.assert_not_called()

    def test_packaged_startup_passes_one_resolved_port_into_recovery(self):
        repository_root = Path(__file__).resolve().parents[3]
        runtime_entrypoint = (repository_root / "runtime-entrypoint.sh").read_text()
        entrypoint = (repository_root / "entrypoint.sh").read_text()

        self.assertIn('exec /entrypoint.sh "$server_port"', runtime_entrypoint)
        self.assertIn("RUNTIME_SERVER_PORT=${1:-}", entrypoint)
        self.assertIn(
            'python -m config.sqlite_recovery_server "$DB_FILE" "$RUNTIME_SERVER_PORT"',
            entrypoint,
        )
