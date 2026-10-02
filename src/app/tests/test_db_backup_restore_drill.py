"""Backup → verify → restore → semantic-equivalence drill for the SQLite
snapshot path (`app.tasks_db_backup` / `config.sqlite_integrity`).

The supported backup contract: a verified, atomically-published raw copy of
the live database (`create_live_database_snapshot`), retention that never
removes the newest usable backup, corruption refusal, and a documented
PostgreSQL skip (this path is SQLite-only — a PostgreSQL deployment needs
pg_dump, which Floppy does not orchestrate).

The snapshot writer stages through ``/proc/self/fd`` (Linux-only), matching
the existing convention in ``test_tasks_db_backup``: the writer-dependent
drills skip on other platforms and run fully in CI's Linux containers.
"""

import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from config.sqlite_integrity import create_live_database_snapshot
from integrations.models import CatalogGrant, IntegrationToken
from lists.models import CustomList, CustomListItem
from users.demo import ensure_demo_user  # fixture variety only

requires_proc_fd_backup = skipUnless(
    sys.platform.startswith("linux"),
    "verified-snapshot path requires /proc/self/fd (Linux-only)",
)


def _manage_py() -> Path:
    """Return the repo's manage.py regardless of deployment layout."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "manage.py"
        if candidate.exists():
            return candidate
    raise AssertionError("manage.py not found")


def _table_names(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'django_migrations'"
    ).fetchall()
    return sorted(row[0] for row in rows)


class DatabaseBackupRestoreDrillTests(TestCase):
    """One reference library, backed up and restored through the real path."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="drill", password="drill-pass-1"
        )
        now = timezone.now()
        item = Item.objects.create(
            media_id="drill-movie",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Drill Movie",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=8,
            end_date=now - timedelta(days=2),
        )
        show_item = Item.objects.create(
            media_id="drill-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Drill Show",
        )
        show = TV.objects.create(
            item=show_item, user=self.user, status=Status.IN_PROGRESS.value
        )
        episode_item = Item.objects.create(
            media_id="drill-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Drill Show E1",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=Season.objects.create(
                item=show_item, user=self.user, related_tv=show
            ),
            end_date=now - timedelta(days=1),
        )
        IntegrationToken.generate(user=self.user, name="Drill client")
        CatalogGrant.generate(self.user, "Drill living room")
        media_list = CustomList.objects.create(name="Drill list", owner=self.user)
        CustomListItem.objects.create(custom_list=media_list, item=item)

    def _materialize_reference(self, target: Path) -> None:
        """Materialize the live in-memory test database as a real file.

        This stands in for the deployment's db.sqlite3: the snapshot writer
        operates on files, so the drill first materializes the fixture. A
        logical dump (not ``Connection.backup``) on purpose: the online
        backup API livelocks against the test transaction this runs inside,
        and the thing under test is the *file* snapshot path, not this step.
        """
        destination = sqlite3.connect(target)
        try:
            with destination:
                for statement in connection.connection.iterdump():
                    if statement.strip():
                        destination.execute(statement)
        finally:
            destination.close()

    @requires_proc_fd_backup
    def test_backup_restore_and_semantic_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            reference = tmp / "reference.sqlite3"
            self._materialize_reference(reference)

            # Backup through the supported path.
            dest_dir = tmp / "backups" / "database"
            started = time.perf_counter()
            snapshot = create_live_database_snapshot(
                str(reference), dest_dir, max_keep=3, timeout_seconds=5
            )
            backup_seconds = time.perf_counter() - started
            self.assertIsNotNone(snapshot, "the snapshot writer must succeed")
            self.assertGreater(snapshot.stat().st_size, 0)

            # Independent verification of the archive.
            verify = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            self.assertEqual(
                verify.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )
            verify.close()

            # Restore to a separate, empty destination.
            restore = tmp / "restore.sqlite3"
            started = time.perf_counter()
            shutil.copyfile(snapshot, restore)
            restore_seconds = time.perf_counter() - started

            source_conn = sqlite3.connect(f"file:{reference}?mode=ro", uri=True)
            restore_conn = sqlite3.connect(f"file:{restore}?mode=ro", uri=True)
            try:
                tables = _table_names(source_conn)
                self.assertGreater(len(tables), 10, "fixture should be non-trivial")
                for table in tables:
                    expected = source_conn.execute(
                        f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 -- drill-local table name
                    ).fetchone()[0]
                    actual = restore_conn.execute(
                        f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608 -- drill-local table name
                    ).fetchone()[0]
                    self.assertEqual(
                        actual, expected, f"table {table} diverged after restore"
                    )
                # Spot values the contract cares about: credentials never
                # compared literally in logs, only here inside the fixture.
                self.assertEqual(
                    restore_conn.execute(
                        "SELECT password FROM users_user WHERE username='drill'"
                    ).fetchone(),
                    source_conn.execute(
                        "SELECT password FROM users_user WHERE username='drill'"
                    ).fetchone(),
                )
                self.assertEqual(
                    restore_conn.execute(
                        "SELECT COUNT(*) FROM integrations_cataloggrant"
                    ).fetchone()[0],
                    1,
                )
            finally:
                source_conn.close()
                restore_conn.close()

            # Application readability: Django accepts the restored file as a
            # fully-migrated database.
            env = {
                **__import__("os").environ,
                "SECRET": "test-only",
                "DB_HOST": "",
                "DJANGO_SETTINGS_MODULE": "config.test_settings",
                "FLOPPY_DB_PATH": str(restore),
                "PYTHONPATH": str(_manage_py().parent),
            }
            result = subprocess.run(  # noqa: S603 -- fixed argv, repo-local interpreter
                [
                    sys.executable,
                    str(_manage_py()),
                    "migrate",
                    "--check",
                    "--noinput",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"restored database must pass migrate --check: {result.stderr[-500:]}",
            )

            print(
                "db_drill "
                f"fixture_bytes={reference.stat().st_size} "
                f"snapshot_bytes={snapshot.stat().st_size} "
                f"backup_s={backup_seconds:.2f} restore_s={restore_seconds:.2f} "
                f"tables={len(tables)}"
            )

    @requires_proc_fd_backup
    def test_a_corrupted_source_is_refused_not_archived(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            reference = tmp / "reference.sqlite3"
            self._materialize_reference(reference)
            # A damaged "live" database: garbage after a valid header.
            raw = reference.read_bytes()
            reference.write_bytes(
                raw[: len(raw) // 2] + b"\x00" * (len(raw) - len(raw) // 2)
            )

            snapshot = create_live_database_snapshot(
                str(reference),
                tmp / "backups" / "database",
                max_keep=3,
                timeout_seconds=5,
            )
            self.assertIsNone(snapshot, "a corrupt source must not produce an archive")

    @requires_proc_fd_backup
    def test_retention_never_removes_the_newest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            reference = tmp / "reference.sqlite3"
            self._materialize_reference(reference)
            dest_dir = tmp / "backups" / "database"

            snapshots = []
            for _ in range(5):
                path = create_live_database_snapshot(
                    str(reference), dest_dir, max_keep=3, timeout_seconds=5
                )
                self.assertIsNotNone(path)
                snapshots.append(path)
                time.sleep(0.01)

            remaining = sorted(
                dest_dir.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime
            )
            self.assertLessEqual(len(remaining), 3, "retention bound")
            self.assertTrue(
                snapshots[-1].exists(),
                "the newest snapshot must always survive retention",
            )

    @override_settings()
    def test_postgres_deployments_are_skipped_by_design(self):
        from app.tasks_db_backup import write_database_snapshot

        with override_settings(USING_SQLITE_DATABASE=False, DB_SNAPSHOT_ENABLED=True):
            with override_settings():
                result = write_database_snapshot()
        self.assertEqual(result, {"status": "skipped", "reason": "postgres"})
