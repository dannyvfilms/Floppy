"""Tests for the deployment readiness checks and the command that reports them.

These live beside the code they cover: the checks are in ``app``, so their tests
are too. The read-only database inspection lives in ``config`` and is exercised
here as well, through the checks that call it, which is where its behaviour
actually matters to an operator.

CI names the applications it runs one by one rather than discovering them, so a
new application is invisible to it until someone adds the name. ``config`` and
``api`` were missing for exactly that reason until issue #811 added them on
2026-08-16. Check that list before assuming a new test directory runs.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import redirect_stdout, suppress
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from app import preflight
from app.preflight import FAIL, OK, SKIPPED, WARN

_CMD = "app.management.commands.floppy_preflight."


def _make_database(path: Path, *, with_orphan: bool = False) -> None:
    """Create a small SQLite database, optionally with a broken relationship."""
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE parent(id INTEGER PRIMARY KEY);
        CREATE TABLE child(
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES parent(id)
        );
        INSERT INTO parent VALUES (1);
        INSERT INTO child VALUES (1, 1);
        """
    )
    if with_orphan:
        # Foreign keys are off by default, which is how a real database arrives
        # in this state.
        connection.execute("INSERT INTO child VALUES (2, 404)")
    connection.commit()
    connection.close()


class _TempDatabase:
    """Provide a temporary data directory and database path for a test."""

    def __enter__(self):
        self._temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._temp.name)
        self.db_path = self.data_dir / "db.sqlite3"
        return self

    def __exit__(self, *exc_info):
        self._temp.cleanup()
        return False

    def settings(self, **extra):
        """Return override_settings pointed at this directory."""
        return override_settings(
            FLOPPY_DATA_DIR=self.data_dir,
            FLOPPY_DB_PATH=self.db_path,
            LOG_DIR=str(self.data_dir),
            USING_SQLITE_DATABASE=True,
            **extra,
        )


class PathsCheckTests(SimpleTestCase):
    def test_reports_the_configured_directories_when_they_are_usable(self):
        with _TempDatabase() as temp, temp.settings():
            result = preflight.check_paths()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["data_dir"], str(temp.data_dir))
        self.assertEqual(result.facts["database_path"], str(temp.db_path))

    def test_passes_before_the_database_file_exists(self):
        """A first start has no database yet. That is not a fault."""
        with _TempDatabase() as temp, temp.settings():
            self.assertFalse(temp.db_path.exists())
            result = preflight.check_paths()

        self.assertEqual(result.status, OK)

    def test_fails_when_a_directory_sits_where_the_database_belongs(self):
        """Docker creates a directory for a bind mount whose source is missing."""
        with _TempDatabase() as temp:
            temp.db_path.mkdir()
            with temp.settings():
                result = preflight.check_paths()

        self.assertEqual(result.status, FAIL)
        self.assertIn("is a directory", result.summary)
        self.assertIn("[HOST]", result.fix)

    def test_fails_when_the_data_directory_cannot_be_written_to(self):
        with _TempDatabase() as temp, temp.settings():
            with mock.patch.object(
                preflight, "_probe_writable", return_value="Read-only file system"
            ):
                result = preflight.check_paths()

        self.assertEqual(result.status, FAIL)
        self.assertIn("not writable", result.summary)
        self.assertTrue(result.fix.startswith(preflight.HOST))

    def test_advice_suits_the_environment_floppy_runs_in(self):
        """PUID and compose files mean nothing to a source or desktop install.

        Floppy ships as a container, as a source install and as a packaged
        application. Advice that assumes the container is wrong in two of the
        three, so the wording follows the environment.
        """
        for containerised, expected, forbidden in (
            (True, "PUID", "the user that runs Floppy"),
            (False, "the user that runs Floppy", "PUID"),
        ):
            with self.subTest(container=containerised):
                with _TempDatabase() as temp, temp.settings():
                    with mock.patch.object(
                        preflight, "in_container", return_value=containerised
                    ), mock.patch.object(
                        preflight,
                        "_probe_writable",
                        return_value="Read-only file system",
                    ):
                        result = preflight.check_paths()

                self.assertIn(expected, result.fix)
                self.assertNotIn(forbidden, result.fix)

    def test_fails_on_a_full_disk_even_though_the_permissions_allow_writing(self):
        """os.access reports permission bits, so a full volume looks writable."""
        usage = mock.Mock(free=1024)
        with _TempDatabase() as temp, temp.settings():
            with mock.patch.object(preflight.shutil, "disk_usage", return_value=usage):
                result = preflight.check_paths()

        self.assertEqual(result.status, FAIL)
        self.assertIn("free", result.summary)
        self.assertIn("[HOST]", result.fix)


class DatabaseCheckTests(SimpleTestCase):
    def test_reports_an_intact_database(self):
        with _TempDatabase() as temp:
            _make_database(temp.db_path)
            with temp.settings():
                result = preflight.check_database()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["engine"], "sqlite")

    def test_reports_a_missing_database_as_ready_for_migrations(self):
        with _TempDatabase() as temp, temp.settings():
            result = preflight.check_database()

        self.assertEqual(result.status, OK)
        self.assertIn("migrations will create one", result.summary)

    def test_fails_on_broken_relationships_and_names_the_table(self):
        with _TempDatabase() as temp:
            _make_database(temp.db_path, with_orphan=True)
            with temp.settings():
                result = preflight.check_database()

        self.assertEqual(result.status, FAIL)
        self.assertIn("child", result.summary)
        self.assertEqual(result.facts["conflicts"], 1)

    def test_fails_on_a_file_that_is_not_a_database(self):
        with _TempDatabase() as temp:
            temp.db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 2000)
            with temp.settings():
                result = preflight.check_database()

        self.assertEqual(result.status, FAIL)
        self.assertIn("cannot be read", result.summary)

    def test_fails_when_the_scan_exceeds_its_bound(self):
        """The bound must end the scan, not merely be recorded."""
        with _TempDatabase() as temp:
            _make_database(temp.db_path)
            with temp.settings():
                with mock.patch.object(
                    preflight,
                    "inspect_database",
                    side_effect=preflight.IntegrityScanTimeoutError("scan exceeded 0.1s"),
                ):
                    result = preflight.check_database(timeout_seconds=0.1)

        self.assertEqual(result.status, FAIL)
        self.assertIn("did not finish in time", result.summary)
        self.assertIn("--timeout", result.fix)

    def test_reports_a_locked_database_clearly_instead_of_stalling(self):
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        with _TempDatabase() as temp:
            _make_database(temp.db_path)
            with temp.settings():
                with mock.patch.object(
                    preflight, "inspect_database", side_effect=error
                ):
                    result = preflight.check_database()

        self.assertEqual(result.status, FAIL)
        self.assertIn("locked", result.summary)

    def test_leaves_no_trace_of_having_looked(self):
        """The whole contract: inspection must not repair, report or back up.

        The startup path writes an incident report, creates a verified backup and
        can delete rows. A diagnostic that did any of that would be unsafe to run
        against a live installation.
        """
        with _TempDatabase() as temp:
            _make_database(temp.db_path, with_orphan=True)
            before = sorted(p.name for p in temp.data_dir.iterdir())
            with temp.settings():
                result = preflight.check_database()
            after = sorted(p.name for p in temp.data_dir.iterdir())

            rows = sqlite3.connect(temp.db_path).execute(
                "SELECT count(*) FROM child"
            ).fetchone()[0]

        self.assertEqual(result.status, FAIL)
        self.assertEqual(before, after, "preflight created or removed a file")
        self.assertEqual(rows, 2, "preflight deleted a row")
        self.assertNotIn(".integrity.json", " ".join(after))


class MigrationsCheckTests(SimpleTestCase):
    def test_skips_itself_when_the_database_is_unavailable(self):
        """Planning needs a connection, so the database result decides this."""
        result = preflight.check_migrations(database_ok=False)

        self.assertEqual(result.status, SKIPPED)
        self.assertIn("database is unavailable", result.summary)

    def test_looking_at_a_first_start_does_not_create_the_database(self):
        """Found by QA. Asking about migrations used to build what it asked about.

        Connecting to a SQLite path that does not exist creates the file, and
        reading the migration state then creates a table inside it. A run
        against a fresh installation left a 4 KB database behind, which is a
        write, and this command promises not to make any.
        """
        with _TempDatabase() as temp, temp.settings():
            with mock.patch.object(preflight, "MigrationExecutor") as executor:
                result = preflight.check_migrations(database_ok=True)

            executor.assert_not_called()
            self.assertFalse(
                temp.db_path.exists(), "the check created the database file"
            )

        self.assertEqual(result.status, SKIPPED)

    def test_reports_no_pending_migrations(self):
        executor = mock.Mock()
        executor.migration_plan.return_value = []
        with mock.patch.object(preflight, "MigrationExecutor", return_value=executor):
            result = preflight.check_migrations(database_ok=True)

        self.assertEqual(result.status, OK)

    def test_fails_and_names_the_first_pending_migration(self):
        migration = mock.Mock(app_label="app")
        migration.name = "0042_add_thing"
        executor = mock.Mock()
        executor.migration_plan.return_value = [(migration, False)]
        with mock.patch.object(preflight, "MigrationExecutor", return_value=executor):
            result = preflight.check_migrations(database_ok=True)

        self.assertEqual(result.status, FAIL)
        self.assertIn("1 migration(s) pending", result.summary)
        self.assertIn("app.0042_add_thing", result.cause)


class RedisCheckTests(SimpleTestCase):
    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="redis://cache:6379/0",
        CELERY_RESULT_BACKEND="redis://cache:6379/0",
    )
    def test_five_settings_that_name_one_server_are_pinged_once(self):
        client = mock.Mock()
        client.config_get.return_value = {"maxmemory": "256mb"}
        with mock.patch.object(preflight.redis, "from_url", return_value=client) as f:
            result = preflight.check_redis()

        self.assertEqual(result.status, OK)
        self.assertEqual(f.call_count, 1, "one server must not be pinged five times")
        self.assertIn("serving 5 role(s)", result.summary)

    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="redis://broker:6379/0",
        CELERY_RESULT_BACKEND="redis://results:6379/0",
    )
    def test_separate_servers_are_each_checked(self):
        client = mock.Mock()
        client.config_get.return_value = {"maxmemory": "256mb"}
        with mock.patch.object(preflight.redis, "from_url", return_value=client) as f:
            result = preflight.check_redis()

        self.assertEqual(result.status, OK)
        self.assertEqual(f.call_count, 3)

    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="redis://broker:6379/0",
        CELERY_RESULT_BACKEND="redis://broker:6379/0",
    )
    def test_a_failure_names_the_roles_the_unreachable_server_carries(self):
        """A dead broker must not hide behind a healthy cache."""

        def connect(url, **_kwargs):
            client = mock.Mock()
            if "broker" in url:
                client.ping.side_effect = preflight.redis.ConnectionError(
                    "Error 111 connecting to broker:6379. Connection refused."
                )
            client.config_get.return_value = {"maxmemory": "256mb"}
            return client

        with mock.patch.object(preflight.redis, "from_url", side_effect=connect):
            result = preflight.check_redis()

        self.assertEqual(result.status, FAIL)
        self.assertIn("broker", result.summary)
        self.assertIn("celery broker", result.summary)

    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="redis://cache:6379/0",
        CELERY_RESULT_BACKEND="redis://cache:6379/0",
    )
    def test_warns_when_redis_has_no_memory_ceiling(self):
        """Unbounded Redis is a hazard, not a reason to refuse to start."""
        client = mock.Mock()
        client.config_get.return_value = {"maxmemory": "0"}
        with mock.patch.object(preflight.redis, "from_url", return_value=client):
            result = preflight.check_redis()

        self.assertEqual(result.status, WARN)
        self.assertFalse(result.failed, "a warning must not stop a start")
        self.assertIn("memory ceiling", result.cause)

    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="amqp://guest:guest@rabbitmq:5672//",
        CELERY_RESULT_BACKEND="db+postgresql://user:pw@db/floppy",
    )
    def test_a_broker_this_check_cannot_speak_to_is_left_alone(self):
        """Found by QA. A healthy RabbitMQ stack was reported as broken Redis.

        Celery accepts brokers with no Redis client. Passing those to
        ``redis.from_url`` produced "cannot reach amqp://..." and told the
        operator to check a Redis service that was never involved.
        """
        client = mock.Mock()
        client.config_get.return_value = {"maxmemory": "256mb"}
        with mock.patch.object(preflight.redis, "from_url", return_value=client) as f:
            result = preflight.check_redis()

        self.assertEqual(result.status, OK)
        self.assertEqual(f.call_count, 1)
        for url, _kwargs in [(c.args[0], c.kwargs) for c in f.call_args_list]:
            self.assertTrue(url.startswith("redis://"))

    @override_settings(
        REDIS_URL="redis://cache:6379/0",
        REDIS_CACHE_URL="redis://cache:6379/0",
        REDIS_ADMIN_URL="redis://cache:6379/0",
        CELERY_BROKER_URL="redis://cache:6379/0",
        CELERY_RESULT_BACKEND="redis://cache:6379/0",
    )
    def test_a_refused_password_is_not_reported_as_an_unreachable_server(self):
        """Found by QA. The server answered, so "is it running" is the wrong hint."""
        client = mock.Mock()
        client.ping.side_effect = preflight.redis.AuthenticationError("WRONGPASS")
        with mock.patch.object(preflight.redis, "from_url", return_value=client):
            result = preflight.check_redis()

        self.assertEqual(result.status, FAIL)
        self.assertIn("refused the credentials", result.summary)
        self.assertIn("password", result.fix)
        self.assertNotIn("is running", result.fix)

    @override_settings(
        REDIS_URL="redis://:hunter2@cache:6379/0",
        REDIS_CACHE_URL="redis://:hunter2@cache:6379/0",
        REDIS_ADMIN_URL="redis://:hunter2@cache:6379/0",
        CELERY_BROKER_URL="redis://:hunter2@cache:6379/0",
        CELERY_RESULT_BACKEND="redis://:hunter2@cache:6379/0",
    )
    def test_no_password_survives_the_failure_path(self):
        """Client libraries quote the connection string in their errors."""
        client = mock.Mock()
        client.ping.side_effect = preflight.redis.ConnectionError(
            "Error connecting to redis://:hunter2@cache:6379/0. Refused."
        )
        with mock.patch.object(preflight.redis, "from_url", return_value=client):
            result = preflight.check_redis()

        self.assertEqual(result.status, FAIL)
        rendered = json.dumps(result.as_dict())
        self.assertNotIn("hunter2", rendered)


class CommandTests(TestCase):
    """Command-level behaviour.

    These need a real database: two of them let the migration check run for
    real rather than mocking it, which is the point of those two tests.
    """

    def _run(self, *args):
        """Run the command, returning its output and exit code."""
        out = StringIO()
        code = 0
        try:
            call_command("floppy_preflight", *args, stdout=out, stderr=StringIO())
        except SystemExit as exit_signal:
            code = exit_signal.code
        return out.getvalue(), code

    def _passing(self):
        return [
            preflight.CheckResult(name="paths", status=OK, summary="fine"),
            preflight.CheckResult(name="config", status=OK, summary="fine"),
            preflight.CheckResult(name="database", status=OK, summary="fine"),
            preflight.CheckResult(name="migrations", status=OK, summary="fine"),
            preflight.CheckResult(name="redis", status=OK, summary="fine"),
        ]

    def test_exits_zero_and_lists_every_check_when_all_pass(self):
        """Showing what ran matters: "it never checked Redis" is itself a finding."""
        with mock.patch(_CMD + "run_checks", return_value=self._passing()):
            output, code = self._run()

        self.assertEqual(code, 0)
        for name in ("paths", "config", "database", "migrations", "redis"):
            self.assertIn(name, output)
        self.assertIn("preflight: ok", output)

    def test_exits_one_and_names_the_failing_check(self):
        results = self._passing()
        results[2] = preflight.CheckResult(
            name="database",
            status=FAIL,
            summary="unreadable",
            cause="file is not a database",
            fix="[HOST] restore a backup",
        )
        with mock.patch(_CMD + "run_checks", return_value=results):
            output, code = self._run()

        self.assertEqual(code, 1)
        self.assertIn("preflight: failed (database)", output)
        self.assertIn("cause:", output)
        self.assertIn("fix:", output)

    def test_a_warning_alone_does_not_change_the_exit_code(self):
        results = self._passing()
        results[4] = preflight.CheckResult(
            name="redis", status=WARN, summary="reachable", cause="no ceiling"
        )
        with mock.patch(_CMD + "run_checks", return_value=results):
            output, code = self._run()

        self.assertEqual(code, 0)
        self.assertIn("with warnings", output)

    def test_json_output_is_one_object_and_nothing_else(self):
        with mock.patch(_CMD + "run_checks", return_value=self._passing()):
            output, code = self._run("--json")

        payload = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"], preflight.REPORT_VERSION)
        self.assertEqual(len(payload["checks"]), 5)

    def test_json_stays_valid_when_the_checks_themselves_fail(self):
        """A supervisor must never get an empty stdout and a traceback."""
        with mock.patch(
            _CMD + "run_checks", side_effect=RuntimeError("settings exploded")
        ):
            output, code = self._run("--json")

        payload = json.loads(output)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("settings exploded", payload["checks"][0]["cause"])

    def test_no_redis_reports_a_skip_rather_than_a_silent_pass(self):
        output, code = self._run("--no-redis", "--timeout", "30")

        self.assertIn("redis", output)
        self.assertIn("skip", output)

    def test_auto_migrate_applies_migrations_and_rechecks(self):
        results = self._passing()
        results[3] = preflight.CheckResult(
            name="migrations", status=FAIL, summary="1 migration(s) pending"
        )
        applied = preflight.CheckResult(
            name="migrations", status=OK, summary="none pending"
        )
        with mock.patch(_CMD + "run_checks", return_value=results), \
             mock.patch(
                 _CMD + "call_command"
             ) as migrate, \
             mock.patch(
                 _CMD + "check_migrations",
                 return_value=applied,
             ):
            output, code = self._run("--auto-migrate")

        self.assertEqual(code, 0)
        migrate.assert_called_once()
        self.assertEqual(migrate.call_args.args, ("migrate", "--noinput"))
        self.assertIn("preflight: ok", output)

    def test_auto_migrate_keeps_json_clean_by_capturing_migrate_output(self):
        """Migrate writes progress to stdout, which would corrupt the report."""
        results = self._passing()
        results[3] = preflight.CheckResult(
            name="migrations", status=FAIL, summary="1 migration(s) pending"
        )
        applied = preflight.CheckResult(
            name="migrations", status=OK, summary="none pending"
        )
        with mock.patch(_CMD + "run_checks", return_value=results), \
             mock.patch(
                 _CMD + "call_command"
             ) as migrate, \
             mock.patch(
                 _CMD + "check_migrations",
                 return_value=applied,
             ):
            output, _code = self._run("--auto-migrate", "--json")

        json.loads(output)
        self.assertIn("stdout", migrate.call_args.kwargs)
        self.assertIn("stderr", migrate.call_args.kwargs)

    def test_json_survives_a_real_migration_run(self):
        """Found by QA. The mocked test above cannot catch this.

        Passing ``stdout`` to ``call_command`` rebinds only the stream the
        command writes to. A data migration that calls ``print`` writes past it
        to the real standard output, and ``lists.0004`` does exactly that. One
        stray line before the report is enough to make it unparseable, so this
        runs migrate for real rather than mocking it away.
        """
        results = self._passing()
        results[3] = preflight.CheckResult(
            name="migrations", status=FAIL, summary="1 migration(s) pending"
        )
        applied = preflight.CheckResult(
            name="migrations", status=OK, summary="none pending"
        )
        noisy = "  populate_list_item_id: 0 items processed (done)"

        def print_then_migrate(*_args, **_kwargs):
            print(noisy)  # reproduces the migration's own output

        # The report and the stray line share one stream in real use, which is
        # what makes them collide. Capturing the process stream rather than
        # handing the command a private one is what reproduces that.
        buffer = StringIO()
        with mock.patch(_CMD + "run_checks", return_value=results), \
             mock.patch(_CMD + "call_command", side_effect=print_then_migrate), \
             mock.patch(_CMD + "check_migrations", return_value=applied), \
             redirect_stdout(buffer):
            with suppress(SystemExit):  # the report is what matters here
                call_command("floppy_preflight", "--auto-migrate", "--json")

        output = buffer.getvalue()
        self.assertNotIn(noisy, output)
        json.loads(output)

    def test_a_failed_migration_keeps_the_rest_of_the_report(self):
        """Found by QA. One failure used to erase four working answers.

        A migration can fail for reasons this command cannot fix, such as an
        inconsistent history. Reporting only that discards the paths, settings,
        database and Redis results the operator already has, which are what they
        need to work out whether the migration is the only problem.
        """
        results = self._passing()
        results[3] = preflight.CheckResult(
            name="migrations", status=FAIL, summary="1 migration(s) pending"
        )
        broken = Exception("Migration app.0109 is applied before its dependency")

        with mock.patch(_CMD + "run_checks", return_value=results), \
             mock.patch(_CMD + "call_command", side_effect=broken):
            output, code = self._run("--auto-migrate", "--json")

        payload = json.loads(output)
        names = [check["name"] for check in payload["checks"]]

        self.assertEqual(code, 1)
        self.assertEqual(names, ["paths", "config", "database", "migrations", "redis"])
        migrations = payload["checks"][3]
        self.assertEqual(migrations["status"], FAIL)
        self.assertIn("applied before its dependency", migrations["cause"])

    def test_auto_migrate_builds_the_database_on_a_first_start(self):
        """A first start reports "skipped", which still means there is work."""
        results = self._passing()
        results[3] = preflight.CheckResult(
            name="migrations",
            status=SKIPPED,
            summary="not checked; every migration runs when the database is created",
        )
        applied = preflight.CheckResult(
            name="migrations", status=OK, summary="none pending"
        )
        with mock.patch(_CMD + "run_checks", return_value=results), \
             mock.patch(_CMD + "call_command") as migrate, \
             mock.patch(_CMD + "check_migrations", return_value=applied):
            _output, code = self._run("--auto-migrate")

        self.assertEqual(code, 0)
        migrate.assert_called_once()

    def test_does_not_migrate_when_nothing_is_pending(self):
        with mock.patch(_CMD + "run_checks", return_value=self._passing()), \
             mock.patch(
                 _CMD + "call_command"
             ) as migrate:
            _output, code = self._run("--auto-migrate")

        self.assertEqual(code, 0)
        migrate.assert_not_called()

    def test_every_fix_says_where_to_run_it(self):
        """A chown run inside the container fails; an env edit there is lost."""
        scopes = (preflight.HOST, preflight.CONFIG, preflight.FLOPPY)
        with _TempDatabase() as temp:
            temp.db_path.mkdir()
            with temp.settings():
                results = [preflight.check_paths()]
        results.append(preflight.check_migrations(database_ok=True))

        for result in results:
            if result.fix:
                with self.subTest(check=result.name):
                    self.assertTrue(
                        result.fix.startswith(scopes),
                        f"{result.name} fix does not name where to run it",
                    )
