#!/usr/bin/env python3
"""Check that the UI component register and the source map agree with the code.

Run from anywhere: ``python3 scripts/check_ui_docs.py``. It checks, with no
dependencies beyond the standard library:

* every ``### ID — Title`` entry in docs/ui/component-register.md has exactly one
  ``- Status:`` line that starts with a term from the vocabulary in the register;
* every backticked repository path in the register exists (globs must match);
* docs/ui/source-map.md has one ``## ID`` section per register entry, with the same
  ``Status:`` line, and no unknown IDs;
* every source file the map covers is listed exactly once and every listed path exists.

It cannot judge whether a status is true; ``scripts/ui_migration_metrics.py`` and the
"How to verify a status" section of the register describe how to do that.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "docs/ui/component-register.md"
SOURCE_MAP = ROOT / "docs/ui/source-map.md"

VOCABULARY = (
    "Legacy",
    "Partial / coexisting",
    "Web Migrated",
    "Deferred (blocker)",
    "Existing (no UI work needed)",
)

# Roots whose every file must appear once in the source map.
COVERED_ROOTS = (
    ("src/templates", {".html", ".txt"}),
    ("src/static/js", {".js", ".mjs"}),
    ("src/static/css", {".css"}),
    ("src/static/ui", {".js", ".css"}),
    ("frontend", {".js", ".jsx", ".css"}),
)
EXTRA_COVERED = ("scripts/build_ui.mjs",)

PATH_PREFIXES = ("src/", "frontend/", "scripts/", "docs/")


def register_entries(text: str) -> dict[str, str]:
    """Return ``{ID: entry body}`` for every ``### ID —`` heading."""
    parts = re.split(r"^### ([A-Z][A-Z0-9_-]*) — .*$", text, flags=re.M)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def status_lines(body: str) -> list[str]:
    return re.findall(r"^- Status: (.*)$", body, re.M)


def leading_status(line: str) -> str | None:
    match = re.match(r"`([^`]+)`", line)
    return match.group(1) if match and match.group(1) in VOCABULARY else None


def backticked_paths(text: str) -> set[str]:
    found = set()
    for token in re.findall(r"`([^`\n]+)`", text):
        token = token.strip()
        if token.startswith(PATH_PREFIXES) and " " not in token:
            found.add(token.split(":")[0] if re.search(r":\d+$", token) else token)
    return found


def path_exists(path: str) -> bool:
    if "*" in path:
        return any(ROOT.glob(path))
    return (ROOT / path).exists()


NATIVE_TERMS = {"DOM", "Primitives", "Ready", "Web-only", "n/a"}


def main() -> int:
    problems: list[str] = []
    register = REGISTER.read_text()
    source_map = SOURCE_MAP.read_text()
    entries = register_entries(register)

    statuses: dict[str, str] = {}
    for entry_id, body in entries.items():
        lines = status_lines(body)
        if len(lines) != 1:
            problems.append(f"register {entry_id}: expected one '- Status:' line, found {len(lines)}")
            continue
        term = leading_status(lines[0])
        if term is None:
            problems.append(f"register {entry_id}: Status must start with a vocabulary term in backticks")
        else:
            statuses[entry_id] = term
            if term in {"Partial / coexisting", "Web Migrated"}:
                native = re.findall(r"^- Native readiness: `([^`]+)`", body, re.M)
                if len(native) != 1 or native[0] not in NATIVE_TERMS:
                    problems.append(
                        f"register {entry_id}: expected one '- Native readiness:' line starting with "
                        f"one of {sorted(NATIVE_TERMS)} in backticks, found {native}",
                    )

    for path in sorted(backticked_paths(register)):
        if not path_exists(path):
            problems.append(f"register: path does not exist: {path}")

    sections = re.split(r"^## ([A-Z][A-Z0-9_-]*)$", source_map, flags=re.M)
    map_sections = {sections[i]: sections[i + 1] for i in range(1, len(sections), 2)}
    for entry_id in sorted(set(map_sections) - set(entries)):
        problems.append(f"source map: unknown ID {entry_id}")
    for entry_id in sorted(set(entries) - set(map_sections)):
        problems.append(f"source map: missing section for {entry_id}")
    for entry_id, body in map_sections.items():
        if entry_id not in statuses:
            continue
        found = re.findall(r"^Status: `([^`]+)`", body, re.M)
        if found != [statuses[entry_id]]:
            problems.append(
                f"source map {entry_id}: Status {found} does not match register {statuses[entry_id]!r}",
            )

    # A bullet owns the paths in its leading run of backticked paths
    # (``- `a`, `b` (note)``); later backticks in the note are only prose.
    listed: list[str] = []
    for line in re.findall(r"^- (`[^\n]+)$", source_map, re.M):
        lead = re.match(r"((?:`[^`]+`(?:, | and )?)+)", line)
        for pattern in re.findall(r"`([^`]+)`", lead.group(1) if lead else ""):
            if not pattern.startswith(PATH_PREFIXES):
                continue
            matches = [str(p.relative_to(ROOT)) for p in ROOT.glob(pattern)] if "*" in pattern else [pattern]
            if not matches or not all(path_exists(m) for m in matches):
                problems.append(f"source map: path does not exist: {pattern}")
            listed.extend(matches)

    expected = {
        str(p.relative_to(ROOT))
        for root, suffixes in COVERED_ROOTS
        for p in (ROOT / root).rglob("*")
        if p.is_file() and p.suffix in suffixes
    } | set(EXTRA_COVERED)
    for path in sorted(expected - set(listed)):
        problems.append(f"source map: file not mapped: {path}")
    counts = Counter(p for p in listed if p in expected)
    for path, count in sorted(counts.items()):
        if count > 1:
            problems.append(f"source map: file mapped {count} times: {path}")

    if problems:
        print("\n".join(problems))
        print(f"{len(problems)} problem(s)")
        return 1
    by_status = Counter(statuses.values())
    summary = ", ".join(f"{term}: {by_status[term]}" for term in VOCABULARY)
    print(f"{len(entries)} register entries ({summary}); {len(expected)} source files mapped; no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
