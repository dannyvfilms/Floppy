import sqlite3

from django.test import SimpleTestCase

from config.sqlite_integrity import _inspect_foreign_keys
from config.sqlite_repair import apply_repair_plan, build_repair_plan


class SqliteRepairPlannerTests(SimpleTestCase):
    """The generic repair executor must preserve relationship semantics."""

    def test_self_referential_nullable_fk_clears_only_the_broken_reference(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                PRAGMA foreign_keys=OFF;
                CREATE TABLE node (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES node(id)
                );
                INSERT INTO node VALUES (1, NULL);
                INSERT INTO node VALUES (2, 1);
                INSERT INTO node VALUES (3, 99);
                """
            )
            incident = _inspect_foreign_keys(conn)
            self.assertEqual(incident["total_conflicts"], 1)

            plan = build_repair_plan(conn, incident)
            self.assertTrue(plan["can_repair"])
            self.assertEqual(plan["groups"][0]["action"], "clear_reference")

            result = apply_repair_plan(conn, plan, include_required=False)

            self.assertEqual(result["references_cleared"], 1)
            self.assertEqual(
                conn.execute("SELECT parent_id FROM node WHERE id = 2").fetchone()[0],
                1,
            )
            self.assertIsNone(
                conn.execute("SELECT parent_id FROM node WHERE id = 3").fetchone()[0]
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()
