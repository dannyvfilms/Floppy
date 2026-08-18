from unittest import TestCase

from config.sqlite_safety import (
    normalize_sqlite_journal_mode,
    normalize_sqlite_synchronous,
    prepare_sqlite_environment,
    resolve_sqlite_journal_mode,
    sqlite_wal_reset_fix_present,
)


class SQLiteSafetyTests(TestCase):
    """Regression coverage for the SQLite WAL-reset corruption guard."""

    def test_reported_sqlite_3461_falls_back_from_wal(self):
        effective, fallback = resolve_sqlite_journal_mode("WAL", (3, 46, 1))

        self.assertEqual(effective, "DELETE")
        self.assertTrue(fallback)

    def test_fixed_release_boundaries_keep_wal(self):
        fixed_versions = (
            (3, 44, 6),
            (3, 50, 7),
            (3, 51, 3),
            (3, 53, 3),
        )

        for version in fixed_versions:
            with self.subTest(version=version):
                self.assertTrue(sqlite_wal_reset_fix_present(version))
                effective, fallback = resolve_sqlite_journal_mode("wal", version)
                self.assertEqual(effective, "WAL")
                self.assertFalse(fallback)

    def test_affected_release_boundaries_disable_wal(self):
        affected_versions = (
            (3, 44, 5),
            (3, 45, 0),
            (3, 49, 9),
            (3, 50, 6),
            (3, 51, 0),
            (3, 51, 2),
        )

        for version in affected_versions:
            with self.subTest(version=version):
                self.assertFalse(sqlite_wal_reset_fix_present(version))
                effective, fallback = resolve_sqlite_journal_mode("WAL", version)
                self.assertEqual(effective, "DELETE")
                self.assertTrue(fallback)

    def test_non_wal_journal_mode_is_preserved(self):
        effective, fallback = resolve_sqlite_journal_mode(" truncate ", (3, 46, 1))

        self.assertEqual(effective, "TRUNCATE")
        self.assertFalse(fallback)

    def test_journal_mode_rejects_unexpected_sql_grammar(self):
        with self.assertRaisesRegex(ValueError, "Unsupported SQLITE_JOURNAL_MODE"):
            normalize_sqlite_journal_mode("WAL; VACUUM")

    def test_journal_mode_rejects_modes_without_crash_recovery(self):
        for value in ("OFF", "MEMORY"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "Unsupported SQLITE_JOURNAL_MODE",
                ):
                    normalize_sqlite_journal_mode(value)

    def test_synchronous_mode_accepts_names_and_numeric_values(self):
        self.assertEqual(normalize_sqlite_synchronous(" full "), "FULL")
        self.assertEqual(normalize_sqlite_synchronous("2"), "2")

    def test_synchronous_mode_rejects_unexpected_sql_grammar(self):
        with self.assertRaisesRegex(ValueError, "Unsupported SQLITE_SYNCHRONOUS"):
            normalize_sqlite_synchronous("NORMAL; VACUUM")

    def test_synchronous_mode_rejects_off(self):
        for value in ("OFF", "0"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "Unsupported SQLITE_SYNCHRONOUS",
                ):
                    normalize_sqlite_synchronous(value)

    def test_prepare_environment_publishes_safe_effective_values(self):
        values = {
            "DB_HOST": None,
            "SQLITE_JOURNAL_MODE": "wal",
            "SQLITE_SYNCHRONOUS": "normal",
        }
        environment = {}

        def config_reader(key, default=None):
            return values.get(key, default)

        policy = prepare_sqlite_environment(
            config_reader,
            environment,
            version_info=(3, 46, 1),
        )

        self.assertEqual(policy, ("WAL", "DELETE", "FULL", True))
        self.assertEqual(environment["SQLITE_JOURNAL_MODE"], "DELETE")
        self.assertEqual(environment["SQLITE_SYNCHRONOUS"], "FULL")

    def test_prepare_environment_preserves_stronger_synchronous_mode(self):
        values = {
            "DB_HOST": None,
            "SQLITE_JOURNAL_MODE": "WAL",
            "SQLITE_SYNCHRONOUS": "EXTRA",
        }
        environment = {}

        def config_reader(key, default=None):
            return values.get(key, default)

        policy = prepare_sqlite_environment(
            config_reader,
            environment,
            version_info=(3, 46, 1),
        )

        self.assertEqual(policy, ("WAL", "DELETE", "EXTRA", True))
        self.assertEqual(environment["SQLITE_SYNCHRONOUS"], "EXTRA")

    def test_prepare_environment_does_not_touch_postgresql_runtime(self):
        environment = {}

        def config_reader(key, default=None):
            if key == "DB_HOST":
                return "postgres"
            return default

        policy = prepare_sqlite_environment(
            config_reader,
            environment,
            version_info=(3, 46, 1),
        )

        self.assertIsNone(policy)
        self.assertEqual(environment, {})
