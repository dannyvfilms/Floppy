"""Reuse a really-migrated SQLite test database while its inputs are unchanged.

Building the test database replays every migration, which takes minutes and is
the same cost for one targeted test as for the whole suite
(``docs/architecture/test-suite-cost.md``). This module keeps the *result* of a
real replay and restores it on later runs.

A stale template would mean tests running against an old schema and staying
green, so reuse is guarded three ways rather than trusted to the key alone:

1. **The key** is a hash of everything that decides what a replay produces:
   every migration file, the lockfile (third-party migrations and Django
   itself), the settings and runner modules, the SQLite backend, every module
   that registers a ``pre_migrate``/``post_migrate`` receiver, and the Python
   and SQLite versions. Any change is a miss, and a miss is a real replay.
2. **Django still runs ``migrate``** on the restored database. With the same
   graph it applies nothing. If it plans to apply anything, the key was wrong
   and the run fails.
3. **The contents are fingerprinted.** The file name carries a hash of the
   schema and every row as they were when the replay finished. After the
   restore and the no-op ``migrate`` the database must still hash to that
   value, so a damaged file, or a ``post_migrate`` handler that now writes
   something different, also fails the run.

SQLite's backup API copies pages, so a restored database is the replayed one
page for page, including autoincrement counters. Only the in-memory SQLite
test database is handled. PostgreSQL, ``--keepdb`` and
``FLOPPY_TEST_FAST_DB=1`` runs never touch this code.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import os
import sqlite3
import sys
import tempfile
import weakref
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / ".floppy"
PREFIX = "testdb-"
SUFFIX = ".sqlite3"
KEEP_NEWEST = 3

# Files outside the migration folders whose contents change what a replay
# builds or how this module reuses it.
KEY_FILES = (
    "uv.lock",
    "src/config/settings.py",
    "src/config/test_settings.py",
    "src/config/test_runner.py",
    "src/config/test_db_template.py",
    "src/config/sqlite_backend/__init__.py",
    "src/config/sqlite_backend/base.py",
)


class TemplateMismatchError(RuntimeError):
    """A restored template did not match what this checkout would build."""


def requested() -> bool:
    """Whether the environment asks for template reuse."""
    return (
        os.environ.get("FLOPPY_TEST_DB_TEMPLATE") == "1"
        and os.environ.get("FLOPPY_TEST_FAST_DB") != "1"
    )


def receiver_files(root: Path) -> list[Path]:
    """Return first-party files that register a migrate-signal receiver.

    Those handlers write rows after every ``migrate``, so their code decides
    the contents as much as a migration does. Third-party handlers are pinned
    by the lockfile.
    """
    from django.db.models.signals import post_migrate, pre_migrate

    files = set()
    for signal in (pre_migrate, post_migrate):
        for entry in signal.receivers:
            receiver = entry[1]
            if isinstance(receiver, weakref.ReferenceType):
                receiver = receiver()
            try:
                source = inspect.getsourcefile(inspect.unwrap(receiver))
            except TypeError:
                continue
            if source and Path(source).resolve().is_relative_to(root):
                files.add(Path(source).resolve())
    return sorted(files)


def compute_key(root: Path = REPO_ROOT, extra_files=()) -> str:
    """Hash every input that decides the migrated database."""
    paths = {root / name for name in KEY_FILES}
    paths.update(Path(path) for path in extra_files)
    for folder in (root / "src").glob("*/migrations"):
        paths.update(
            path
            for path in folder.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )

    digest = hashlib.sha256()
    for part in (
        f"python={sys.version_info.major}.{sys.version_info.minor}",
        f"sqlite={sqlite3.sqlite_version}",
    ):
        digest.update(part.encode() + b"\0")
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        # A listed file that does not exist is itself part of the key, so
        # adding it later is a miss.
        content = path.read_bytes() if path.is_file() else b"<missing>"
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()[:32]


def current_key() -> str:
    """Return the key for this checkout. Needs Django's apps to be loaded."""
    return compute_key(extra_files=receiver_files(REPO_ROOT))


def fingerprint(raw: sqlite3.Connection) -> str:
    """Hash the schema and every row, in a stable order.

    Values are read through SQLite's ``quote()`` so the hash is of what is
    stored. Django's connection converts dates and booleans on the way out and
    a plain connection does not; both must agree on the same database.
    """
    digest = hashlib.sha256()
    objects = raw.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY rowid"
    ).fetchall()
    for row in objects:
        digest.update(repr(row).encode() + b"\n")
    for kind, name, _table, _sql in objects:
        if kind != "table":
            continue
        digest.update(f"-- {name}\n".encode())
        table = '"' + name.replace('"', '""') + '"'
        columns = [
            '"' + row[1].replace('"', '""') + '"'
            for row in raw.execute(f"PRAGMA table_info({table})")
        ]
        values = ", ".join(f"quote({column})" for column in ["rowid", *columns])
        query = f"SELECT {values} FROM {table} ORDER BY rowid"  # noqa: S608
        for row in raw.execute(query):
            digest.update(repr(row).encode() + b"\n")
    return digest.hexdigest()[:32]


def find(key: str, directory: Path = TEMPLATE_DIR) -> Path | None:
    """Return the saved template for this key, if there is one."""
    matches = sorted(directory.glob(f"{PREFIX}{key}-*{SUFFIX}"))
    return matches[0] if matches else None


def expected_fingerprint(path: Path) -> str:
    """Return the contents hash a template file name promises."""
    return path.name[len(PREFIX) : -len(SUFFIX)].rsplit("-", 1)[1]


def restore(path: Path, database_name: str) -> sqlite3.Connection | None:
    """Copy a template into the shared in-memory database.

    Returns a connection that keeps the in-memory database alive until Django
    has opened its own, or ``None`` when the file cannot be used. A file that
    is damaged is deleted so the next step is an ordinary replay; nothing is
    left half restored, because the in-memory database goes away with the
    connection.
    """
    keeper = sqlite3.connect(database_name, uri=True)
    try:
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            source.backup(keeper)
        finally:
            source.close()
        healthy = keeper.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        if healthy and fingerprint(keeper) == expected_fingerprint(path):
            return keeper
    except sqlite3.Error:
        pass
    keeper.close()
    with contextlib.suppress(OSError):
        path.unlink()
    return None


def save(raw: sqlite3.Connection, key: str, directory: Path = TEMPLATE_DIR) -> Path:
    """Write the migrated database to its template file, atomically."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{PREFIX}{key}-{fingerprint(raw)}{SUFFIX}"
    # A private temporary name, then a rename: a reader never sees a partial
    # file, and two runs building the same key at once each leave a whole one.
    handle, name = tempfile.mkstemp(dir=directory, prefix=".testdb-", suffix=".tmp")
    os.close(handle)
    temporary = Path(name)
    try:
        destination = sqlite3.connect(temporary)
        try:
            raw.backup(destination)
        finally:
            destination.close()
        temporary.replace(target)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    prune(directory, keep=target)
    return target


def prune(directory: Path = TEMPLATE_DIR, keep: Path | None = None) -> None:
    """Keep only the newest few templates."""

    def modified(path):
        # Another run may delete a file between the listing and the stat.
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    templates = sorted(directory.glob(f"{PREFIX}*{SUFFIX}"), key=modified, reverse=True)
    for path in templates[KEEP_NEWEST:]:
        if path != keep:
            with contextlib.suppress(OSError):
                path.unlink()


if __name__ == "__main__":
    # Print the key, for CI's cache step. Run as
    # ``python src/config/test_db_template.py``. Python puts this folder first
    # on the path, where ``celery.py`` would shadow the real package; swap it
    # for ``src``.
    sys.path[0] = str(REPO_ROOT / "src")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.test_settings")
    import django

    django.setup()
    sys.stdout.write(current_key() + "\n")
