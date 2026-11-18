"""Guard: the small value helpers that kept being rewritten have one home.

Each name below used to be written again in module after module, and the
copies drifted. A new top-level function with one of these names, outside
its home, fails here with the module to import from. Only top-level
functions are checked; methods and nested functions are not.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

SRC = Path(__file__).resolve().parents[2]

HELPERS = "app/helpers.py"
OAUTH = "integrations/oauth_models.py"

# name -> (home, what to import from it)
HOMES = {
    "coerce_int": (HELPERS, "coerce_int"),
    "_coerce_int": (HELPERS, "coerce_int"),
    "coerce_list": (HELPERS, "coerce_list"),
    "_coerce_list": (HELPERS, "coerce_list"),
    "wants_json": (HELPERS, "wants_json"),
    "_wants_json": (HELPERS, "wants_json"),
    "minutes_to_hm": (HELPERS, "minutes_to_hm"),
    "format_minutes": (HELPERS, "minutes_to_hm"),
    "_minutes_display": (HELPERS, "minutes_to_hm"),
    "seconds_to_clock": (HELPERS, "seconds_to_clock"),
    "no_store": (OAUTH, "no_store"),
    "_no_store": (OAUTH, "no_store"),
}

# Names whose copies each did a different job. They have no shared home; a
# new one should say in its name what it returns.
NAME_IT = {
    "_now": "_now_iso, _now_to_minute, _utc_now_whole_seconds, _epoch_seconds",
    "_parse_date": (
        "_parse_tvdb_datetime, _parse_feed_datetime, _parse_clz_date, "
        "_parse_year_first_date, _date_param"
    ),
}


def _source_files():
    for path in sorted(SRC.rglob("*.py")):
        parts = path.relative_to(SRC).parts
        if "tests" in parts or "migrations" in parts:
            continue
        yield path


def find_misplaced_helpers(files=None):
    """Return one message per top-level helper copy outside its home."""
    problems = []
    for path in files if files is not None else _source_files():
        relative = path.relative_to(SRC).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in HOMES:
                home, name = HOMES[node.name]
                if relative != home:
                    problems.append(
                        f"{relative}:{node.lineno} defines {node.name}(). "
                        f"Import {name} from {home} instead "
                        f"(see docs/architecture/code-map.md, Helper homes).",
                    )
            elif node.name in NAME_IT:
                problems.append(
                    f"{relative}:{node.lineno} defines {node.name}(). Copies of "
                    f"this name each did something different; name it for what "
                    f"it returns, like {NAME_IT[node.name]}.",
                )
    return problems


class HelperHomesTests(SimpleTestCase):
    def test_no_copies_outside_their_home(self):
        problems = find_misplaced_helpers()
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_every_home_defines_its_helper(self):
        for home, name in set(HOMES.values()):
            with self.subTest(home=home, name=name):
                tree = ast.parse((SRC / home).read_text(encoding="utf-8"))
                defined = {
                    node.name
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                }
                self.assertIn(name, defined)
