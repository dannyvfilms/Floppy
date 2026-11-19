"""The saved migrated test database is reused only when it is provably current."""

import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock, skipIf

from django.db.migrations.recorder import MigrationRecorder
from django.db.models.signals import pre_migrate
from django.test import SimpleTestCase, TestCase
from django.test.runner import DiscoverRunner

from config import test_db_template
from config.test_runner import ResilientDiscoverRunner


class TempDirMixin:
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)


class ComputeKeyTests(TempDirMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        for name in test_db_template.KEY_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        self.migrations = self.root / "src" / "app" / "migrations"
        self.migrations.mkdir(parents=True)
        (self.migrations / "0001_initial.py").write_text("operations = []\n")

    def key(self, **kwargs):
        return test_db_template.compute_key(self.root, **kwargs)

    def test_unchanged_inputs_give_the_same_key(self):
        self.assertEqual(self.key(), self.key())

    def test_one_changed_byte_in_a_migration_changes_the_key(self):
        before = self.key()
        (self.migrations / "0001_initial.py").write_text("operations = []#\n")
        self.assertNotEqual(before, self.key())

    def test_a_new_migration_changes_the_key(self):
        before = self.key()
        (self.migrations / "0002_more.py").write_text("")
        self.assertNotEqual(before, self.key())

    def test_a_renamed_migration_changes_the_key(self):
        before = self.key()
        (self.migrations / "0001_initial.py").rename(self.migrations / "0001_first.py")
        self.assertNotEqual(before, self.key())

    def test_each_listed_file_changes_the_key(self):
        for name in test_db_template.KEY_FILES:
            with self.subTest(name=name):
                before = self.key()
                (self.root / name).write_text(name + " changed")
                self.assertNotEqual(before, self.key())

    def test_a_signal_receiver_file_changes_the_key(self):
        handler = self.root / "src" / "app" / "signals.py"
        handler.write_text("one")
        before = self.key(extra_files=[handler])
        handler.write_text("two")
        self.assertNotEqual(before, self.key(extra_files=[handler]))

    def test_python_and_sqlite_versions_change_the_key(self):
        before = self.key()
        with mock.patch.object(sqlite3, "sqlite_version", "0.0.0"):
            self.assertNotEqual(before, self.key())
        with mock.patch.object(
            test_db_template.sys, "version_info", SimpleNamespace(major=3, minor=99)
        ):
            self.assertNotEqual(before, self.key())

    def test_compiled_files_do_not_change_the_key(self):
        before = self.key()
        cache = self.migrations / "__pycache__"
        cache.mkdir()
        (cache / "0001_initial.cpython-312.pyc").write_bytes(b"x")
        self.assertEqual(before, self.key())

    def test_the_real_key_covers_the_demo_user_receiver(self):
        files = test_db_template.receiver_files(test_db_template.REPO_ROOT)
        self.assertIn(test_db_template.REPO_ROOT / "src/users/signals.py", files)


def _migrated_database():
    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE thing (id integer PRIMARY KEY AUTOINCREMENT, name text)")
    raw.executemany("INSERT INTO thing (name) VALUES (?)", [("a",), ("b",)])
    raw.commit()
    return raw


class SaveAndRestoreTests(TempDirMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.source = _migrated_database()
        self.addCleanup(self.source.close)
        self.name = f"file:tpl_{uuid.uuid4().hex}?mode=memory&cache=shared"

    def test_a_restored_database_matches_the_saved_one(self):
        path = test_db_template.save(self.source, "k1", self.root)
        self.assertEqual(test_db_template.find("k1", self.root), path)
        self.assertIsNone(test_db_template.find("k2", self.root))

        keeper = test_db_template.restore(path, self.name)
        self.addCleanup(keeper.close)
        self.assertEqual(
            test_db_template.fingerprint(keeper),
            test_db_template.fingerprint(self.source),
        )
        # The autoincrement counter comes across, so new rows get the same ids.
        keeper.execute("INSERT INTO thing (name) VALUES ('c')")
        self.assertEqual(keeper.execute("SELECT max(id) FROM thing").fetchone()[0], 3)
        self.assertEqual(list(self.root.glob(".testdb-*")), [])

    def test_a_truncated_file_is_deleted_and_not_used(self):
        path = test_db_template.save(self.source, "k1", self.root)
        path.write_bytes(path.read_bytes()[:5000])

        self.assertIsNone(test_db_template.restore(path, self.name))
        self.assertFalse(path.exists())
        # Nothing was left behind in the database the tests would use.
        check = sqlite3.connect(self.name, uri=True)
        self.addCleanup(check.close)
        self.assertEqual(check.execute("SELECT * FROM sqlite_master").fetchall(), [])

    def test_a_file_whose_contents_do_not_match_its_name_is_not_used(self):
        path = test_db_template.save(self.source, "k1", self.root)
        edited = sqlite3.connect(path)
        edited.execute("DELETE FROM thing WHERE name = 'b'")
        edited.commit()
        edited.close()

        self.assertIsNone(test_db_template.restore(path, self.name))
        self.assertFalse(path.exists())

    def test_the_fingerprint_ignores_how_a_connection_converts_values(self):
        # Django's connection parses declared types; a plain one does not.
        path = self.root / "typed.sqlite3"
        plain = sqlite3.connect(path)
        plain.execute("CREATE TABLE seen (id integer PRIMARY KEY, at datetime)")
        plain.execute("INSERT INTO seen (at) VALUES ('2026-01-02 03:04:05')")
        plain.commit()
        self.addCleanup(plain.close)
        typed = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.addCleanup(typed.close)
        # The converter registry is process-global; undo the change afterwards.
        patched = mock.patch.dict(
            sqlite3.converters, {"DATETIME": lambda value: ("parsed", value)}
        )
        patched.start()
        self.addCleanup(patched.stop)

        self.assertNotEqual(
            plain.execute("SELECT at FROM seen").fetchall(),
            typed.execute("SELECT at FROM seen").fetchall(),
        )
        self.assertEqual(
            test_db_template.fingerprint(plain), test_db_template.fingerprint(typed)
        )

    def test_a_row_change_changes_the_fingerprint(self):
        before = test_db_template.fingerprint(self.source)
        self.source.execute("UPDATE thing SET name = 'z' WHERE id = 2")
        self.assertNotEqual(before, test_db_template.fingerprint(self.source))

    def test_a_schema_change_changes_the_fingerprint(self):
        before = test_db_template.fingerprint(self.source)
        self.source.execute("CREATE INDEX thing_name ON thing (name)")
        self.assertNotEqual(before, test_db_template.fingerprint(self.source))

    def test_only_the_newest_templates_are_kept(self):
        for index in range(test_db_template.KEEP_NEWEST + 2):
            path = test_db_template.save(self.source, f"k{index}", self.root)
            os.utime(path, (index, index))
        newest = test_db_template.save(self.source, "newest", self.root)

        kept = sorted(self.root.glob("testdb-*.sqlite3"))
        self.assertEqual(len(kept), test_db_template.KEEP_NEWEST)
        self.assertIn(newest, kept)


class RequestedTests(SimpleTestCase):
    def test_off_unless_asked_for(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(test_db_template.requested())
        with mock.patch.dict(os.environ, {"FLOPPY_TEST_DB_TEMPLATE": "1"}, clear=True):
            self.assertTrue(test_db_template.requested())

    def test_the_models_only_schema_is_never_saved_as_a_template(self):
        env = {"FLOPPY_TEST_DB_TEMPLATE": "1", "FLOPPY_TEST_FAST_DB": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(test_db_template.requested())


class RunnerSetupTests(TempDirMixin, SimpleTestCase):
    """Drive ``setup_databases`` with Django's own setup replaced by a stub."""

    def setUp(self):
        super().setUp()
        self.database = _migrated_database()
        self.addCleanup(self.database.close)
        self.fingerprint = test_db_template.fingerprint(self.database)
        self.template = self.root / f"testdb-key-{self.fingerprint}.sqlite3"
        self.template.write_bytes(b"")
        self.keeper = mock.Mock()
        self.plan = []

        connection = mock.MagicMock()
        connection.connection = self.database
        patches = [
            mock.patch.object(
                ResilientDiscoverRunner, "_template_applies", return_value=True
            ),
            mock.patch("config.test_runner.connections", {"default": connection}),
            mock.patch.object(test_db_template, "current_key", return_value="key"),
            mock.patch.object(DiscoverRunner, "setup_databases", self.django_setup),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.runner = ResilientDiscoverRunner(verbosity=0)

    def django_setup(self, **kwargs):
        pre_migrate.send(sender=self, plan=self.plan)
        return ["old config"]

    def run_setup(self, *, found, restored=True):
        keeper = self.keeper if restored else None
        with (
            mock.patch.object(
                test_db_template, "find", return_value=self.template if found else None
            ),
            mock.patch.object(test_db_template, "restore", return_value=keeper),
            mock.patch.object(test_db_template, "save") as save,
        ):
            save.return_value = self.template
            return self.runner.setup_databases(), save

    def test_a_miss_replays_and_saves(self):
        result, save = self.run_setup(found=False)
        self.assertEqual(result, ["old config"])
        save.assert_called_once_with(self.database, "key")

    def test_a_damaged_template_falls_back_to_a_replay_and_saves(self):
        self.plan = [(mock.Mock(), False)]
        result, save = self.run_setup(found=True, restored=False)
        self.assertEqual(result, ["old config"])
        save.assert_called_once_with(self.database, "key")

    def test_a_hit_is_used_when_migrate_applies_nothing(self):
        result, save = self.run_setup(found=True)
        self.assertEqual(result, ["old config"])
        save.assert_not_called()
        self.keeper.close.assert_called_once()
        self.assertTrue(self.template.exists())

    def test_a_hit_fails_the_run_when_migrate_applies_something(self):
        self.plan = [("app.0002_more", False)]
        with self.assertRaisesMessage(
            test_db_template.TemplateMismatchError, "app.0002_more"
        ):
            self.run_setup(found=True)
        self.assertFalse(self.template.exists())

    def test_a_hit_fails_the_run_when_the_contents_changed(self):
        self.database.execute("INSERT INTO thing (name) VALUES ('late')")
        with self.assertRaisesMessage(
            test_db_template.TemplateMismatchError, "contents changed"
        ):
            self.run_setup(found=True)
        self.assertFalse(self.template.exists())


class TemplateAppliesTests(SimpleTestCase):
    def applies(self, env, aliases=None, **runner_kwargs):
        runner = ResilientDiscoverRunner(verbosity=0, **runner_kwargs)
        # The positive cases must hold whatever mode the surrounding run is in.
        with mock.patch.dict(os.environ, {"FLOPPY_TEST_FAST_DB": "0", **env}):
            return runner._template_applies(aliases)

    def test_applies_to_the_in_memory_sqlite_database(self):
        self.assertTrue(self.applies({"FLOPPY_TEST_DB_TEMPLATE": "1"}, {"default"}))

    def test_does_not_apply_when_off_or_not_building_the_default_database(self):
        self.assertFalse(self.applies({"FLOPPY_TEST_DB_TEMPLATE": "0"}, {"default"}))
        self.assertFalse(self.applies({"FLOPPY_TEST_DB_TEMPLATE": "1"}, set()))
        self.assertFalse(
            self.applies({"FLOPPY_TEST_DB_TEMPLATE": "1"}, {"default"}, keepdb=True)
        )


@skipIf(os.environ.get("FLOPPY_TEST_FAST_DB") == "1", "Requires migration replay")
class MigratedDatabaseTests(TestCase):
    """Uses the database, so running this module builds or restores it.

    CI's template job runs this module to produce the saved database.
    """

    def test_the_test_database_records_real_migrations(self):
        applied = MigrationRecorder.Migration.objects
        for app in ("app", "users", "integrations", "lists", "events"):
            with self.subTest(app=app):
                self.assertTrue(applied.filter(app=app).exists())
