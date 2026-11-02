#!/usr/bin/env python3
# ruff: noqa: T201
"""Fail a pull request that adds a migration without the migrations already on latest.

Two PRs that each add the next migration pass CI on their own and then collide
once both are merged (two migrations with one number, or two leaf nodes). A
migration PR therefore has to contain every migration that has landed on the base
branch since it branched. Pull requests that touch no migration are not affected.

Usage: check_migration_order.py <head-ref> <base-ref>
Exit 0 when the PR is fine, 1 when it must merge the base branch first.
"""

from __future__ import annotations

import re
import subprocess
import sys

MIGRATION_RE = re.compile(r"^src/[^/]+/migrations/\d{4}_[^/]+\.py$")


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _migration_files(output: str) -> list[str]:
    return sorted(line for line in output.splitlines() if MIGRATION_RE.match(line))


def migrations_missing_from_head(
    head: str, base: str, cwd: str | None = None
) -> tuple[list[str], list[str]]:
    """Return (migrations the PR changes, migrations base gained that the PR lacks)."""
    merge_base = _git("merge-base", head, base, cwd=cwd).strip()
    changed_by_pr = _migration_files(
        _git("diff", "--name-only", merge_base, head, cwd=cwd)
    )
    gained_by_base = _migration_files(
        _git("diff", "--name-only", "--diff-filter=AR", merge_base, base, cwd=cwd)
    )
    return changed_by_pr, gained_by_base


def main(argv: list[str]) -> int:
    """Run the check and print what the PR author must do on failure."""
    head, base = argv[1], argv[2]
    changed_by_pr, gained_by_base = migrations_missing_from_head(head, base)
    if not changed_by_pr:
        print("No migrations in this PR; nothing to order.")
        return 0
    if not gained_by_base:
        print("This PR has every migration that is on the base branch.")
        return 0
    print(
        "::error::Another pull request added migrations to the base branch after "
        "this branch was started. Merge the base branch into this branch, point "
        "your migration at the new latest migration, and push so CI runs again."
    )
    print("Migrations on the base branch that this PR does not have:")
    for path in gained_by_base:
        print(f"  {path}")
    print("Migrations this PR changes:")
    for path in changed_by_pr:
        print(f"  {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
