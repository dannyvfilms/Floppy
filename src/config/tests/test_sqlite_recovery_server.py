"""Tests for the SQLite recovery page (issue #731 follow-up)."""

import json
import os
import re
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config import sqlite_recovery_server as recovery
from config.sqlite_integrity import check_database_integrity, write_startup_status


class RecoveryPageTests(SimpleTestCase):
    def test_admission_diagnosis_is_shown_without_recovery_choices(self):
        page = recovery.render_page(
            None,
            interactive=True,
            status={
                "status": "blocked",
                "error_class": "startup_admission",
                "error_message": "Run sqlite_startup --prepare-migrations <offline>",
            },
        )
        self.assertIn("sqlite_startup --prepare-migrations &lt;offline&gt;", page)
        self.assertIn("Stop all application containers", page)
        self.assertNotIn("<form", page)

    def setUp(self):
        super().setUp()
        self.env_patcher = mock.patch.dict(os.environ, {"FLOPPY_SQLITE_AUTO_REPAIR": "false"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        super().tearDown()

    def create_incident(self, tmp_dir, *, rows=3, with_titles=True):
        """Create a database whose episodes point at a season that is gone."""
        db_path = str(Path(tmp_dir) / "db.sqlite3")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE app_item (
                id INTEGER PRIMARY KEY,
                title TEXT,
                season_number INTEGER
            );
            CREATE TABLE app_season (id INTEGER PRIMARY KEY);
            CREATE TABLE app_episode (
                id INTEGER PRIMARY KEY,
                related_season_id INTEGER NOT NULL REFERENCES app_season(id),
                item_id INTEGER REFERENCES app_item(id)
            );
            INSERT INTO app_season VALUES (500);
            """
        )
        for index in range(1, rows + 1):
            title = "Breaking Bad" if index % 2 else "The Wire"
            conn.execute(
                "INSERT INTO app_item VALUES (?, ?, ?)",
                (index, title, 1),
            )
            conn.execute(
                "INSERT INTO app_episode VALUES (?, 500, ?)",
                (index, index if with_titles else None),
            )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM app_season WHERE id = 500")
        conn.commit()
        conn.close()
        return db_path

    def block_startup(self, db_path):
        """Run the checker so that it writes a blocked report."""
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            check_database_integrity(db_path)
        return json.loads(Path(f"{db_path}.integrity.json").read_text())

    def serve(self, db_path):
        """Start the handler on a free port and return its base URL."""
        recovery._Handler.db_path = db_path
        server = ThreadingHTTPServer(("127.0.0.1", 0), recovery._Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def post(self, url, fields=None):
        """Send a form post to the recovery page."""
        data = urllib.parse.urlencode(fields or {}).encode()
        request = urllib.request.Request(url, data=data)  # noqa: S310
        return urllib.request.urlopen(request)  # noqa: S310

    def test_health_always_fails_so_the_container_stays_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            for path in ("/health/", "/health"):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"{base}{path}")  # noqa: S310
                # A success here would report the container as healthy while
                # Floppy cannot serve a single request.
                self.assertEqual(ctx.exception.code, 503)

    def test_timeout_page_can_retry_without_a_container_restart(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            sqlite3.connect(db_path).close()
            write_startup_status(
                db_path,
                status="timeout",
                phase="quick_check",
                started_at="2026-08-20T01:49:43+00:00",
                elapsed_seconds=600,
                error_class="timeout",
                error_message="scan exceeded 600s",
                progress_callbacks=22,
                phase_started_at="2026-08-20T01:39:43+00:00",
                last_progress_at="2026-08-20T01:49:00+00:00",
                version="test",
                commit_sha="test",
            )
            base = self.serve(db_path)

            with urllib.request.urlopen(f"{base}/") as response:  # noqa: S310
                page = response.read().decode()
            self.assertIn("Retry startup check", page)
            self.assertIn("action='/retry'", page)
            self.assertIn("No recent SQLite progress observed", page)
            self.assertIn("Progress rate", page)

            with self.post(f"{base}/retry") as response:
                body = response.read().decode()
            self.assertIn("Floppy is retrying", body)

            decision = json.loads(
                Path(f"{db_path}.integrity.decision").read_text(),
            )
            self.assertEqual(decision, {"action": "retry"})

    def test_page_names_the_affected_titles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir, rows=6)
            report = self.block_startup(db_path)

            titles = {entry["title"] for entry in report["affected"]}
            self.assertEqual(titles, {"Breaking Bad", "The Wire"})
            self.assertEqual(
                sum(entry["count"] for entry in report["affected"]),
                6,
            )
            self.assertEqual(report["affected_unidentified"], 0)

            base = self.serve(db_path)
            with urllib.request.urlopen(f"{base}/") as response:  # noqa: S310
                page = response.read().decode()
            self.assertIn("Your data is safe", page)
            self.assertIn("Breaking Bad, Season 1", page)
            self.assertIn("The Wire, Season 1", page)

    def test_rows_without_a_usable_title_are_reported_honestly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir, rows=4, with_titles=False)
            report = self.block_startup(db_path)

            # Never invent a title for a row we cannot identify.
            self.assertEqual(report["affected"], [])
            self.assertEqual(report["affected_unidentified"], 4)
            base = self.serve(db_path)
            with urllib.request.urlopen(f"{base}/") as response:  # noqa: S310
                page = response.read().decode()
            self.assertIn("cannot identify", page)

    def test_accept_writes_a_choice_carrying_the_incident_identity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            base = self.serve(db_path)

            self.post(f"{base}/accept").read()

            decision = json.loads(
                Path(f"{db_path}.integrity.decision").read_text(),
            )
            self.assertEqual(decision["action"], "accept")
            self.assertEqual(decision["fingerprint"], report["fingerprint"])
            self.assertEqual(decision["token"], report["incident_token"])

    def test_quarantine_with_wrong_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(f"{base}/quarantine", {"token": "wrong"})
            self.assertEqual(ctx.exception.code, 403)
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_episode").fetchone()[0],
                3,
            )
            conn.close()

    def test_quarantine_without_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            base = self.serve(db_path)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post(f"{base}/quarantine")
            self.assertEqual(ctx.exception.code, 403)
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

            page = recovery.render_page(report, interactive=True)
            self.assertIn("name='token' required", page)
            self.assertIn("Approval code", page)

    def test_recovery_server_sends_no_cache_headers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            with urllib.request.urlopen(f"{base}/") as response:  # noqa: S310
                self.assertEqual(response.status, 200)
                self.assertIn("no-store", response.headers.get("Cache-Control", ""))
                self.assertIn("no-cache", response.headers.get("Pragma", ""))

    def test_quarantine_with_the_code_records_the_choice(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            base = self.serve(db_path)

            response = self.post(
                f"{base}/quarantine",
                {"token": report["incident_token"]},
            )
            self.assertEqual(response.status, 200)
            body = response.read().decode()
            self.assertIn("Floppy has your choice.", body)
            # The app needs minutes to migrate and start. A timed reload would
            # land on a connection error and read as a failed repair.
            self.assertNotIn("http-equiv='refresh'", body)

            decision = json.loads(
                Path(f"{db_path}.integrity.decision").read_text(),
            )
            self.assertEqual(decision["action"], "quarantine")
            self.assertEqual(decision["fingerprint"], report["fingerprint"])

    def test_the_page_is_written_beside_the_database_and_is_readable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)

            with mock.patch("sys.stderr"):
                page_path = recovery.write_page(
                    db_path,
                    json.loads(Path(f"{db_path}.integrity.json").read_text()),
                )

            self.assertTrue(page_path.is_file())
            # The person who runs Floppy must be able to open this file.
            self.assertEqual(page_path.stat().st_mode & 0o777, 0o644)
            page = page_path.read_text()
            self.assertIn("Your data is safe", page)
            # The written copy cannot act, so it must not offer buttons.
            self.assertNotIn("<form", page)

    def test_a_choice_for_a_different_incident_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)

            Path(f"{db_path}.integrity.decision").write_text(
                json.dumps(
                    {
                        "action": "quarantine",
                        "fingerprint": "0" * 64,
                        "token": report["incident_token"],
                    },
                ),
            )
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_episode").fetchone()[0],
                3,
            )
            conn.close()
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

    def test_a_choice_with_an_old_code_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)

            Path(f"{db_path}.integrity.decision").write_text(
                json.dumps(
                    {
                        "action": "quarantine",
                        "fingerprint": report["fingerprint"],
                        "token": "0" * 32,
                    },
                ),
            )
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_episode").fetchone()[0],
                3,
            )
            conn.close()

    def test_a_malformed_choice_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            Path(f"{db_path}.integrity.decision").write_text("not json")

            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_episode").fetchone()[0],
                3,
            )
            conn.close()

    def test_a_valid_choice_starts_floppy_without_changing_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)

            Path(f"{db_path}.integrity.decision").write_text(
                json.dumps(
                    {
                        "action": "accept",
                        "fingerprint": report["fingerprint"],
                        "token": report["incident_token"],
                    },
                ),
            )
            with mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_episode").fetchone()[0],
                3,
            )
            conn.close()
            # The choice is used once and then removed.
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

    def test_a_missing_report_still_produces_a_readable_page(self):
        page = recovery.render_page(None, interactive=True)
        self.assertIn("Your data is safe", page)
        self.assertNotIn("<form", page)

    def test_a_timeout_status_overrides_the_generic_no_report_page(self):
        status = {
            "database": "/data/db.sqlite3",
            "elapsed_seconds": 601.0,
            "phase": "foreign_key_check",
            "read_bytes": 882_638_848,
            "status": "timeout",
            "version": "1.2.3",
            "commit_sha": "abc1234",
        }
        status["error_message"] = "no read or CPU progress for 180s"
        page = recovery.render_page(None, interactive=True, status=status)
        self.assertIn("stopped making progress", page)
        self.assertIn("no read or CPU progress for 180s", page)
        self.assertIn("foreign_key_check", page)
        self.assertIn("601s", page)
        self.assertIn("842MB", page)
        self.assertIn("version=1.2.3", page)
        self.assertIn("commit=abc1234", page)
        self.assertIn("floppy_preflight", page)
        # The old timeout-path claim that data is definitely safe must not
        # survive: the scan never finished, so that is not something Floppy
        # actually knows.
        self.assertNotIn("Your data is safe", page)
        self.assertIn("database result is unknown", page)

    def test_a_timeout_status_takes_the_stable_container_name(self):
        status = {"database": "/data/db.sqlite3", "status": "timeout"}
        with mock.patch.dict(os.environ, {"HOST_CONTAINERNAME": "Yamtrack"}):
            page = recovery.render_page(None, interactive=True, status=status)
        self.assertIn("docker exec Yamtrack python manage.py floppy_preflight", page)

    def test_a_non_timeout_status_does_not_change_the_normal_blocked_page(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            status = {"database": db_path, "status": "ok"}
            page = recovery.render_page(report, interactive=True, status=status)
            self.assertIn("Your data is safe. Floppy paused before migrations.", page)
            self.assertNotIn("stopped making progress", page)

    def test_offline_and_live_pages_render_the_same_timeout_diagnosis(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            sqlite3.connect(db_path).close()
            status = {
                "database": db_path,
                "elapsed_seconds": 600.0,
                "phase": "quick_check",
                "status": "timeout",
            }
            live_page = recovery.render_page(None, interactive=True, status=status)
            offline_page = recovery.render_page(None, interactive=False, status=status)
            self.assertIn("stopped making progress", live_page)
            self.assertIn("stopped making progress", offline_page)
            self.assertIn("quick_check", live_page)
            self.assertIn("quick_check", offline_page)

    def test_the_page_loads_no_external_resource(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            page = recovery.render_page(report, interactive=True)
            # The page also opens from disk, where a subresource request cannot
            # resolve. Styles, scripts and images stay inline. A link is
            # different: the person clicks it, so the page requests nothing.
            self.assertNotIn("@import", page)
            fetched = re.findall(r"src='([^']*)'", page)
            fetched += re.findall(r"<link[^>]*href='([^']*)'", page)
            self.assertTrue(fetched, "expected the page to carry its own icon")
            for reference in fetched:
                self.assertTrue(
                    reference.startswith("data:"),
                    f"{reference[:40]} is requested when the page opens",
                )

    def test_the_page_never_shows_the_approval_code(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            token = report["incident_token"]
            self.assertTrue(token)
            for interactive in (True, False):
                page = recovery.render_page(report, interactive=interactive)
                # The code proves that the person read the report file. If the
                # page shows it, the code proves only that they opened a page
                # that anyone on the network can open.
                self.assertNotIn(token, page)
                self.assertNotIn(f"quarantine:{token}", page)

    def test_the_page_offers_places_to_get_help(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            report = self.block_startup(db_path)
            for candidate in (report, None):
                page = recovery.render_page(candidate, interactive=True)
                self.assertIn("github.com/dannyvfilms/Floppy/issues", page)
                self.assertIn("github.com/dannyvfilms/Floppy/wiki", page)
                self.assertIn("discord.gg/uFgha7Kb6n", page)

    def test_a_cross_site_form_cannot_make_the_choice(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            request = urllib.request.Request(  # noqa: S310
                f"{base}/accept",
                data=b"",
                headers={"Sec-Fetch-Site": "cross-site"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)  # noqa: S310
            self.assertEqual(ctx.exception.code, 403)
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

    def test_an_oversized_body_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            request = urllib.request.Request(  # noqa: S310
                f"{base}/quarantine",
                data=b"token=" + b"a" * 9000,
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)  # noqa: S310
            self.assertEqual(ctx.exception.code, 400)
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

    def test_a_busy_port_does_not_stop_the_page_from_being_written(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)

            with (
                mock.patch.object(
                    recovery,
                    "ThreadingHTTPServer",
                    side_effect=OSError("address already in use"),
                ),
                mock.patch("sys.stderr"),
            ):
                recovery.serve(db_path)

            page_path = Path(tmp_dir) / "floppy-recovery.html"
            self.assertTrue(page_path.is_file())
            self.assertIn("Your data is safe", page_path.read_text())

    def test_a_damaged_value_does_not_stop_the_page(self):
        # The page exists because the database is damaged. SQLite gives an
        # INTEGER column integer affinity only for values that look numeric,
        # so a damaged season number can be text.
        report = {
            "total_conflicts": "many",
            "can_quarantine": True,
            "affected": [{"title": "Breaking Bad", "season": "S1", "count": "x"}],
            "affected_other_titles": None,
            "affected_unidentified": "?",
        }
        page = recovery.render_page(report, interactive=True)
        self.assertIn("Breaking Bad, Season S1", page)
        self.assertIn("0 entries", page)

    def test_a_lookalike_host_cannot_make_the_choice(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)
            host = base.split("//", 1)[1]

            request = urllib.request.Request(  # noqa: S310
                f"{base}/accept",
                data=b"",
                headers={"Origin": f"http://not{host}"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)  # noqa: S310
            self.assertEqual(ctx.exception.code, 403)
            self.assertFalse(Path(f"{db_path}.integrity.decision").exists())

    def test_backup_download_is_closed_unless_the_operator_opens_it(self):
        """The page has no sign-in, so the database must not be the default."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base}/backup")  # noqa: S310
            self.assertEqual(ctx.exception.code, 404)
            page = urllib.request.urlopen(f"{base}/").read().decode()  # noqa: S310
            self.assertNotIn("href='/backup'", page)
            self.assertIn("FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD", page)

    @mock.patch.dict(os.environ, {
        "FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD": "true",
        "FLOPPY_SQLITE_BACKUP_TOKEN": "test-only-download-token-32-characters",
    })
    def test_backup_download_serves_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            for fields in [{}, {"token": "wrong"}]:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.post(f"{base}/backup", fields)
                self.assertEqual(denied.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(f"{base}/backup")  # noqa: S310
            self.assertEqual(denied.exception.code, 404)
            page = urllib.request.urlopen(base).read().decode()  # noqa: S310
            self.assertNotIn(os.environ["FLOPPY_SQLITE_BACKUP_TOKEN"], page)
            with self.post(f"{base}/backup", {
                "token": os.environ["FLOPPY_SQLITE_BACKUP_TOKEN"],
            }) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get("Content-Type"), "application/x-sqlite3")
                self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
                body = response.read()
                self.assertGreater(len(body), 0)
                # Verify downloaded content is valid sqlite file
                backup_dest = Path(tmp_dir) / "downloaded.sqlite3"
                backup_dest.write_bytes(body)
                conn = sqlite3.connect(backup_dest)
                result = conn.execute("PRAGMA quick_check").fetchone()
                self.assertEqual(result[0], "ok")
                conn.close()

    @mock.patch.dict(os.environ, {"FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD": "true"})
    def test_download_requires_a_separate_strong_token_and_same_origin(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)
            for token in ["", "short", "test-only-download-token-32-characters"]:
                with mock.patch.dict(os.environ, {"FLOPPY_SQLITE_BACKUP_TOKEN": token}):
                    headers = {"Origin": "https://outside.example"} if len(token) >= 32 else {}
                    request = urllib.request.Request(  # noqa: S310 - loopback test server
                        f"{base}/backup",
                        data=urllib.parse.urlencode({"token": token}).encode(),
                        headers=headers,
                    )
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(request)  # noqa: S310
                    self.assertEqual(denied.exception.code, 403)

    def test_corrupt_status_renders_physical_corruption_card(self):
        report = {
            "status": "corrupt",
            "unsafe_reasons": ["Physical corruption detected: quick_check returned 'malformed'"],
            "can_quarantine": False,
        }
        page = recovery.render_page(report, interactive=True)
        self.assertIn("Floppy's database file is damaged.", page)
        self.assertIn("Physical corruption detected", page)
        self.assertIn("sqlite-recovery", page)
        # #1053: a CSV export cannot replace this file, and sqlite-recovery/
        # only ever holds relationship-repair backups, not this failure mode.
        self.assertIn("database snapshot", page)
        self.assertIn("CSV export", page)
        self.assertNotIn("<form", page)

    def test_the_page_carries_the_floppy_mark_and_icon(self):
        """No static file server runs here, so both must be inlined."""
        page = recovery.render_page(None, interactive=False)
        self.assertIn("rel='icon'", page)
        self.assertIn("data:image/png;base64,", page)
        self.assertIn("class='masthead'", page)
        self.assertNotIn("{% static", page)

    @mock.patch.dict(os.environ, {"FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD": "true"})
    def test_no_control_nests_inside_a_link(self):
        """A button inside a link is announced twice by a screen reader."""
        report = {"total_conflicts": 2, "can_quarantine": True, "affected": []}
        page = recovery.render_page(report, interactive=True)
        self.assertIsNone(re.search(r"<a\b[^>]*>\s*<button", page))


class RestoreSnapshotTests(SimpleTestCase):
    """Issue #1053: restore the newest verified snapshot from the damaged-file page."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.snapshots = self.root / "backups" / "database"
        self.data.mkdir()
        self.snapshots.mkdir(parents=True)
        self.db_path = str(self.data / "db.sqlite3")
        env = mock.patch.dict(os.environ, {"BACKUP_DIR": str(self.root / "backups")})
        env.start()
        self.addCleanup(env.stop)

    def make_db(self, path, marker):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (marker,))
        conn.commit()
        conn.close()

    def make_snapshot(self, name, marker, mtime):
        path = self.snapshots / name
        self.make_db(path, marker)
        os.utime(path, (mtime, mtime))
        return path

    def damage_live_database(self):
        from config.sqlite_integrity import _write_incident_report

        Path(self.db_path).write_bytes(b"this is not a database" * 500)
        Path(f"{self.db_path}-wal").write_bytes(b"stale wal")
        Path(f"{self.db_path}-shm").write_bytes(b"stale shm")
        report = {
            "groups": [], "samples": [], "total_conflicts": 0,
            "fingerprint": "f" * 8, "can_quarantine": False,
            "unsafe_reasons": ["Physical corruption detected: test"],
        }
        _write_incident_report(self.db_path, report, status="corrupt")

    def marker(self, path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT v FROM t").fetchone()[0]
        finally:
            conn.close()

    def serve(self):
        recovery._Handler.db_path = self.db_path
        server = ThreadingHTTPServer(("127.0.0.1", 0), recovery._Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def post(self, base, fields):
        request = urllib.request.Request(  # noqa: S310
            f"{base}/restore", data=urllib.parse.urlencode(fields).encode()
        )
        return urllib.request.urlopen(request)  # noqa: S310

    def leftovers(self):
        return [p.name for p in self.data.iterdir() if p.name.startswith(".")]

    def test_snapshots_are_listed_newest_first_and_skip_staging_files_and_links(self):
        self.make_snapshot("db-old.sqlite3", "old", 1_000)
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.make_snapshot(".db-staging.sqlite3", "tmp", 3_000)
        (self.snapshots / "link.sqlite3").symlink_to(self.snapshots / "db-new.sqlite3")
        (self.snapshots / "notes.txt").write_text("x")
        names = [item["name"] for item in recovery.list_snapshots()]
        self.assertEqual(names, ["db-new.sqlite3", "db-old.sqlite3"])

    def test_page_offers_restore_only_when_a_snapshot_exists(self):
        report = {"status": "corrupt", "unsafe_reasons": ["x"]}
        self.assertNotIn("/restore", recovery.render_page(report, interactive=True))
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        page = recovery.render_page(report, interactive=True)
        self.assertIn("action='/restore'", page)
        self.assertIn("Saved copies", page)
        self.assertIn("newest", page)
        self.assertIn("Repair it", page)
        self.assertNotIn("&mdash;", page)
        self.assertNotIn("\u2014", page)

    def test_restore_replaces_database_and_moves_damaged_files_aside(self):
        self.make_snapshot("db-new.sqlite3", "restored", 2_000)
        self.damage_live_database()
        aside = recovery.restore_snapshot(self.db_path, "db-new.sqlite3")
        self.assertEqual(self.marker(self.db_path), "restored")
        # A stale WAL beside the restored file would be replayed into it.
        self.assertFalse(Path(f"{self.db_path}-wal").exists())
        self.assertFalse(Path(f"{self.db_path}-shm").exists())
        self.assertEqual(
            sorted(p.name for p in aside.iterdir()),
            ["db.sqlite3", "db.sqlite3-shm", "db.sqlite3-wal"],
        )
        self.assertFalse(Path(f"{self.db_path}.integrity.json").exists())
        self.assertTrue((self.snapshots / "db-new.sqlite3").exists())
        self.assertEqual(self.leftovers(), [])

    def test_unknown_or_path_like_names_are_refused_and_nothing_changes(self):
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.damage_live_database()
        before = Path(self.db_path).read_bytes()
        outside = self.root / "outside.sqlite3"
        self.make_db(outside, "outside")
        for name in ("missing.sqlite3", "../../outside.sqlite3", str(outside), ""):
            with self.subTest(name=name), self.assertRaises(recovery.RestoreError):
                recovery.restore_snapshot(self.db_path, name)
        self.assertEqual(Path(self.db_path).read_bytes(), before)

    def test_a_damaged_snapshot_is_refused_and_live_files_stay(self):
        (self.snapshots / "db-bad.sqlite3").write_bytes(b"garbage" * 1000)
        self.damage_live_database()
        before = Path(self.db_path).read_bytes()
        with self.assertRaises(recovery.RestoreError):
            recovery.restore_snapshot(self.db_path, "db-bad.sqlite3")
        self.assertEqual(Path(self.db_path).read_bytes(), before)
        self.assertTrue(Path(f"{self.db_path}-wal").exists())

    def test_a_failed_swap_puts_the_damaged_files_back(self):
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.damage_live_database()
        before = Path(self.db_path).read_bytes()
        real_replace = Path.replace

        def fail_on_install(path, target):
            if path.name.startswith(".db.sqlite3.restore-"):
                raise OSError("disk went away")
            return real_replace(path, target)

        with mock.patch.object(Path, "replace", fail_on_install), \
                self.assertRaises(recovery.RestoreError):
            recovery.restore_snapshot(self.db_path, "db-new.sqlite3")
        self.assertEqual(Path(self.db_path).read_bytes(), before)
        self.assertEqual(Path(f"{self.db_path}-wal").read_bytes(), b"stale wal")
        self.assertEqual(self.leftovers(), [])

    def test_post_restores_and_asks_startup_to_check_again(self):
        self.make_snapshot("db-old.sqlite3", "old", 1_000)
        self.make_snapshot("db-new.sqlite3", "newest", 2_000)
        self.damage_live_database()
        base = self.serve()
        with self.post(base, {"snapshot": "db-new.sqlite3"}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.marker(self.db_path), "newest")
        self.assertEqual(
            json.loads(Path(f"{self.db_path}.integrity.decision").read_text()),
            {"action": "retry"},
        )

    def test_post_is_refused_when_the_database_is_not_marked_damaged(self):
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.make_db(self.db_path, "live")
        base = self.serve()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(base, {"snapshot": "db-new.sqlite3"})
        self.assertEqual(ctx.exception.code, 409)
        self.assertEqual(self.marker(self.db_path), "live")

    def test_post_from_another_site_is_refused(self):
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.damage_live_database()
        base = self.serve()
        request = urllib.request.Request(  # noqa: S310
            f"{base}/restore",
            data=urllib.parse.urlencode({"snapshot": "db-new.sqlite3"}).encode(),
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)  # noqa: S310
        self.assertEqual(ctx.exception.code, 403)
        self.assertTrue(Path(f"{self.db_path}-wal").exists())

    def test_post_with_a_bad_snapshot_shows_why_and_changes_nothing(self):
        (self.snapshots / "db-bad.sqlite3").write_bytes(b"garbage" * 1000)
        self.damage_live_database()
        base = self.serve()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(base, {"snapshot": "db-bad.sqlite3"})
        self.assertEqual(ctx.exception.code, 409)
        body = ctx.exception.read().decode()
        self.assertIn("The repair did not work.", body)
        self.assertIn("None of the 1 saved copies", body)
        # The page carries a report that names the step, error and files.
        self.assertIn("Floppy restore failure report", body)
        self.assertIn("failed step: check the saved copy", body)
        self.assertIn("db-bad.sqlite3", body)
        self.assertIn("free space beside database", body)
        self.assertNotIn("\u2014", body)
        self.assertFalse(Path(f"{self.db_path}.integrity.decision").exists())

    def test_failed_restore_report_names_the_step_and_errno(self):
        self.make_snapshot("db-new.sqlite3", "new", 2_000)
        self.damage_live_database()
        real_replace = Path.replace

        def fail_on_install(path, target):
            if path.name.startswith(".db.sqlite3.restore-"):
                raise OSError(28, "No space left on device")
            return real_replace(path, target)

        with mock.patch.object(Path, "replace", fail_on_install), \
                self.assertRaises(recovery.RestoreError) as ctx:
            recovery.restore_snapshot(self.db_path, "db-new.sqlite3")
        report = ctx.exception.report
        self.assertIn("failed step: swap in the saved copy", report)
        self.assertIn("errno: 28", report)
        self.assertIn("1. db-new.sqlite3", report)
        self.assertIn("db.sqlite3  ", report)

    def test_page_without_snapshots_explains_and_has_no_button(self):
        page = recovery.render_page(
            {"status": "corrupt", "unsafe_reasons": ["x"]}, interactive=True
        )
        self.assertIn("No saved copies were found", page)
        self.assertNotIn("<form", page)

    def test_checking_copies_never_creates_files_beside_them(self):
        """A WAL-mode snapshot must verify without a -shm in a read-only folder."""
        path = self.snapshots / "db-wal.sqlite3"
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('wal')")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        for extra in ("-wal", "-shm"):
            Path(f"{path}{extra}").unlink(missing_ok=True)
        self.damage_live_database()
        Path(f"{self.db_path}-shm").unlink()
        before = sorted(p.name for p in self.snapshots.iterdir())
        recovery.restore_latest(self.db_path)
        self.assertEqual(sorted(p.name for p in self.snapshots.iterdir()), before)

    def test_restore_tries_older_copies_when_the_newest_is_bad(self):
        (self.snapshots / "db-newest-bad.sqlite3").write_bytes(b"garbage" * 1000)
        os.utime(self.snapshots / "db-newest-bad.sqlite3", (3_000, 3_000))
        self.make_snapshot("db-older.sqlite3", "older", 2_000)
        self.make_snapshot("db-oldest.sqlite3", "oldest", 1_000)
        self.damage_live_database()
        name, _aside = recovery.restore_latest(self.db_path)
        self.assertEqual(name, "db-older.sqlite3")
        self.assertEqual(self.marker(self.db_path), "older")

    def test_post_falls_back_to_an_older_copy(self):
        (self.snapshots / "db-newest-bad.sqlite3").write_bytes(b"garbage" * 1000)
        os.utime(self.snapshots / "db-newest-bad.sqlite3", (3_000, 3_000))
        self.make_snapshot("db-older.sqlite3", "older", 2_000)
        self.damage_live_database()
        base = self.serve()
        with self.post(base, {}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.marker(self.db_path), "older")

    def test_when_every_copy_fails_the_report_lists_each_attempt_and_the_context(self):
        for index, name in enumerate(("db-a.sqlite3", "db-b.sqlite3")):
            path = self.snapshots / name
            path.write_bytes(b"garbage" * 1000)
            os.utime(path, (2_000 - index, 2_000 - index))
        self.damage_live_database()
        before = Path(self.db_path).read_bytes()
        with mock.patch.dict(
            os.environ, {"VERSION": "26.10.1", "DB_SNAPSHOT_ENABLED": "true"}
        ), self.assertRaises(recovery.RestoreError) as ctx:
            recovery.restore_latest(self.db_path)
        report = ctx.exception.report
        self.assertEqual(Path(self.db_path).read_bytes(), before)
        for needle in (
            "restore attempts (2)",
            "1. db-a.sqlite3",
            "2. db-b.sqlite3",
            "failed step: check the saved copy",
            "incident reasons:",
            "startup status:",
            "database filesystem:",
            "backup filesystem:",
            "free space beside database:",
            "damaged file header (first 16 bytes):",
            "damaged file quick_check",
            "floppy: 26.10.1",
            "DB_SNAPSHOT_ENABLED=true",
            "sqlite:",
            "mode=",
            "db.sqlite3-wal",
            "snapshot folder",
            "container log",
        ):
            self.assertIn(needle, report)

    def test_no_copies_gives_a_report_instead_of_a_button(self):
        self.damage_live_database()
        with self.assertRaises(recovery.RestoreError) as ctx:
            recovery.restore_latest(self.db_path)
        self.assertIn("no saved copies", str(ctx.exception))
        self.assertIn("restore attempts (0)", ctx.exception.report)

    def test_secrets_are_not_put_in_the_report(self):
        self.damage_live_database()
        with mock.patch.dict(
            os.environ, {"FLOPPY_SQLITE_BACKUP_TOKEN": "s3cret-token-value", "SECRET": "k"}
        ), self.assertRaises(recovery.RestoreError) as ctx:
            recovery.restore_latest(self.db_path)
        self.assertNotIn("s3cret-token-value", ctx.exception.report)


class SnapshotDefaultsTests(SimpleTestCase):
    """Issue #1053: the nightly snapshots the repair depends on must be on."""

    def test_snapshots_are_enabled_by_default_with_retention(self):
        from django.conf import settings

        env_off = os.environ.get("DB_SNAPSHOT_ENABLED", "").lower() in {"0", "false"}
        if not env_off:
            self.assertTrue(settings.DB_SNAPSHOT_ENABLED)
        self.assertGreaterEqual(settings.DB_SNAPSHOT_RETENTION_COUNT, 3)

    def test_the_snapshot_task_is_always_scheduled(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["write_database_snapshot"]
        self.assertEqual(entry["task"], "Write database snapshot")

    def test_the_default_install_files_do_not_turn_snapshots_off(self):
        root = Path(__file__).resolve().parents[3]
        for name in ("docker-compose.yml", "docker-compose.postgres.yml", ".env.example"):
            path = root / name
            if path.exists():
                self.assertNotRegex(
                    path.read_text(), r"DB_SNAPSHOT_ENABLED\s*[=:]\s*['\"]?(false|0)", name
                )
        compose = (root / "docker-compose.yml").read_text()
        self.assertIn("/floppy/backups", compose)
