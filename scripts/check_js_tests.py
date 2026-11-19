#!/usr/bin/env python3
"""Prove that `npm run test:js` runs every JavaScript test file exactly once.

What must run: every `*.test.mjs` file in the repository that git tracks or
would track (so `node_modules`, build output and other ignored paths are
skipped; a new, not yet committed test file counts).

What does run: the `node --test` commands reached from the root `test:js`
script, following `npm run X` and `npm --prefix DIR run X` into the
package.json they name. Each file or glob after `--test` is expanded from the
directory that command runs in.

The check fails, naming the file, when a test file is run by no command, when
one file is run by two commands, or when a listed file or glob matches
nothing. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "test:js"
SUFFIX = ".test.mjs"
# `--prefix DIR` and `run NAME` are each a flag and one value.
PAIR = 2


def _scripts(package_dir: Path) -> dict[str, str]:
    package = package_dir / "package.json"
    return json.loads(package.read_text()).get("scripts", {})


def _node_test_args(tokens: list[str]) -> list[str] | None:
    """Return the file and glob arguments of a `node --test` command."""
    if not tokens or Path(tokens[0]).name != "node" or "--test" not in tokens:
        return None
    return [token for token in tokens[1:] if not token.startswith("-")]


def _npm_target(tokens: list[str], cwd: Path) -> tuple[Path, str] | None:
    """Return (package dir, script name) for `npm [--prefix DIR] run NAME`."""
    if not tokens or tokens[0] != "npm":
        return None
    rest = tokens[1:]
    package_dir = cwd
    if len(rest) >= PAIR and rest[0] == "--prefix":
        package_dir = (cwd / rest[1]).resolve()
        rest = rest[2:]
    if len(rest) >= PAIR and rest[0] in {"run", "run-script"}:
        return package_dir, rest[1]
    return None


def collect_runs(root: Path, entry: str = ENTRY):
    """Walk the npm scripts from `entry`.

    Returns (runs, problems): runs maps each repository-relative test file to
    the scripts that run it; problems lists listed paths that match nothing.
    """
    runs: dict[str, list[str]] = defaultdict(list)
    problems: list[str] = []
    seen: set[tuple[Path, str]] = set()

    def visit(package_dir: Path, name: str) -> None:
        key = (package_dir, name)
        if key in seen:
            return
        seen.add(key)
        scripts = _scripts(package_dir)
        label = f"{package_dir.relative_to(root).as_posix() or '.'}/package.json {name}"
        if name not in scripts:
            problems.append(f"{label}: script is missing")
            return
        for part in scripts[name].split("&&"):
            tokens = shlex.split(part)
            target = _npm_target(tokens, package_dir)
            if target is not None:
                visit(*target)
                continue
            patterns = _node_test_args(tokens)
            for pattern in patterns or []:
                matches = sorted(package_dir.glob(pattern))
                if not matches:
                    problems.append(f"{label}: {pattern} matches no file")
                for match in matches:
                    path = match.resolve().relative_to(root)
                    runs[path.as_posix()].append(label)

    visit(root, entry)
    return runs, problems


def tracked_tests(root: Path) -> list[str]:
    """Every *.test.mjs git tracks, plus untracked files it does not ignore."""
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(
        line
        for line in output.splitlines()
        if line.endswith(SUFFIX) and (root / line).is_file()
    )


def _where_to_add(path: str) -> str:
    if path.startswith("expo/"):
        return "add it under expo/app/ (test:transport in expo/package.json)"
    return (
        "add it to test:js-logic in package.json "
        "(or test:ui-render if it needs --test-force-exit)"
    )


def check(root: Path, files: list[str] | None = None) -> tuple[bool, list[str]]:
    """Return (passed, report lines)."""
    runs, problems = collect_runs(root)
    files = tracked_tests(root) if files is None else files
    report: list[str] = []
    for path in files:
        labels = runs.get(path, [])
        if not labels:
            report.append(
                f"{path} is not run by `npm run {ENTRY}`: {_where_to_add(path)}"
            )
        elif len(labels) > 1:
            report.append(f"{path} runs {len(labels)} times: {', '.join(labels)}")
    report.extend(problems)
    if report:
        return False, [
            "JavaScript test accounting failed:",
            *(f"  {line}" for line in report),
        ]
    total = sum(len(labels) for labels in runs.values())
    return True, [
        f"JavaScript test accounting: {len(files)} test files, each run once ({total} runs)."
    ]


def main(argv: list[str] | None = None) -> int:
    """Run the check and print its report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    passed, report = check(args.root.resolve())
    print("\n".join(report), file=sys.stdout if passed else sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
