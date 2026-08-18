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
from config.sqlite_integrity import check_database_integrity


class RecoveryPageTests(SimpleTestCase):
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

    @mock.patch.dict(os.environ, {"FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD": "true"})
    def test_backup_download_serves_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = self.create_incident(tmp_dir)
            self.block_startup(db_path)
            base = self.serve(db_path)

            with urllib.request.urlopen(f"{base}/backup") as response:  # noqa: S310
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

    def test_corrupt_status_renders_physical_corruption_card(self):
        report = {
            "status": "corrupt",
            "unsafe_reasons": ["Physical corruption detected: quick_check returned 'malformed'"],
            "can_quarantine": False,
        }
        page = recovery.render_page(report, interactive=True)
        self.assertIn("Floppy cannot read the database file.", page)
        self.assertIn("Physical corruption detected", page)
        self.assertIn("sqlite-recovery", page)
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
