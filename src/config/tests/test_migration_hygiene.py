from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from app.management.commands import check_migration_hygiene


class _FakeGraph:
    def __init__(self, leaf_map):
        self._leaf_map = leaf_map

    def leaf_nodes(self, app_label):
        return self._leaf_map.get(app_label, [])


class MigrationHygieneCommandTests(TestCase):
    """Tests for migration hygiene command helpers and smoke behavior."""

    @override_settings(MIGRATION_MODULES={})
    def test_command_passes_with_head_baseline_for_users(self):
        """The command should pass against HEAD baseline for a stable app graph."""
        # Inspect real migrations even when fast test DB setup disables them.
        output = StringIO()

        call_command(
            "check_migration_hygiene",
            base_ref="HEAD",
            apps="users",
            stdout=output,
        )

        self.assertIn("Migration hygiene checks passed", output.getvalue())

    def test_multi_leaf_check_runs_even_when_base_ref_cannot_be_resolved(self):
        """A graph conflict must fail the command even with no resolvable base ref.

        Regression test for the bug where `_resolve_base_ref` raised before the
        multi-leaf check ever ran, so a genuine leaf-node conflict was masked by
        an unrelated "base ref not found" error whenever no upstream-style ref
        (upstream/dev, origin/dev, dev) existed in the checkout.
        """
        output = StringIO()
        fake_graph = _FakeGraph(
            {
                "users": [
                    ("users", "0040_feature_branch_a"),
                    ("users", "0040_feature_branch_b"),
                ],
            }
        )

        class _FakeLoader:
            def __init__(self, *_args, **_kwargs):
                self.graph = fake_graph

        with (
            patch.object(check_migration_hygiene, "MigrationLoader", _FakeLoader),
            self.assertRaises(CommandError) as raised,
        ):
            call_command(
                "check_migration_hygiene",
                base_ref="definitely-not-a-real-ref",
                apps="users",
                stdout=output,
                stderr=StringIO(),
            )

        self.assertIn("Multiple migration leaf nodes detected", str(raised.exception))
        self.assertNotIn("Base ref", str(raised.exception))

    def test_collect_multi_leaf_apps_flags_branch_splits(self):
        """Branch splits should be reported when an app has multiple leaf nodes."""
        graph = _FakeGraph(
            {
                "users": [
                    ("users", "0040_feature_branch_a"),
                    ("users", "0040_feature_branch_b"),
                ],
                "app": [("app", "0093_latest")],
            }
        )

        result = check_migration_hygiene._collect_multi_leaf_apps(
            graph, ["users", "app"]
        )

        self.assertEqual(
            result,
            {
                "users": [
                    "users.0040_feature_branch_a",
                    "users.0040_feature_branch_b",
                ]
            },
        )

    def test_find_risky_operations_detects_raw_schema_ops(self):
        """Raw migrations.AddConstraint should be detected as a risky operation."""
        with TemporaryDirectory() as tmp_dir:
            migration_path = Path(tmp_dir) / "9999_bad_migration.py"
            migration_path.write_text(
                (
                    "from django.db import migrations\n"
                    "\n"
                    "class Migration(migrations.Migration):\n"
                    "    operations = [\n"
                    "        migrations.AddConstraint(\n"
                    "            model_name='user',\n"
                    "            constraint=None,\n"
                    "        ),\n"
                    "        AddConstraintIfNotExists(\n"
                    "            model_name='user',\n"
                    "            constraint=None,\n"
                    "        ),\n"
                    "    ]\n"
                ),
                encoding="utf-8",
            )

            violations = check_migration_hygiene._find_risky_operations(
                migration_path,
                "src/users/migrations/9999_bad_migration.py",
            )

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].operation, "AddConstraint")
        self.assertEqual(violations[0].line_number, 5)
