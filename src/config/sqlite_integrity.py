from __future__ import annotations

import sqlite3
import sys

_CORRUPTION_HINT = (
    "[entrypoint] The SQLite file may be corrupt (see README: SQLite "
    "network filesystem caveat)"
)
_RELATIONSHIP_HINT = (
    "[entrypoint] Back up the SQLite file, then inspect these relationship "
    "errors before you restart"
)
_BUSY_HINT = (
    "[entrypoint] The SQLite database is busy. Stop other Floppy processes, "
    "then restart"
)
_ALBUM_ARTIST_TABLE = "app_albumartist"


def _check_foreign_keys(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    violations = list(conn.execute("PRAGMA foreign_key_check").fetchall())
    if not violations:
        conn.commit()
        return

    if {violation[0] for violation in violations} == {_ALBUM_ARTIST_TABLE}:
        row_ids = {violation[1] for violation in violations}
        if None not in row_ids:
            row_ids = sorted(row_ids)
            conn.executemany(
                f"DELETE FROM {_ALBUM_ARTIST_TABLE} "  # noqa: S608  # fixed table name
                "WHERE rowid = ?",
                ((row_id,) for row_id in row_ids),
            )
            violations = list(conn.execute("PRAGMA foreign_key_check").fetchall())
            if not violations:
                conn.commit()
                print(  # noqa: T201
                    f"[entrypoint] Removed {len(row_ids)} orphaned album artist "
                    "credit row(s) before migrations",
                    file=sys.stderr,
                )
                return

    conn.rollback()
    for table, row_id, parent, _foreign_key_id in violations:
        print(  # noqa: T201
            "[entrypoint] Database foreign key check failed: "
            f"table={table!r}, row={row_id!r}, parent={parent!r}",
            file=sys.stderr,
        )
    print(_RELATIONSHIP_HINT, file=sys.stderr)  # noqa: T201
    sys.exit(1)


def check_database_integrity(db_path: str) -> None:
    """Check SQLite storage and foreign keys before migrations."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA quick_check").fetchone()
        status = result[0] if result else None
        if status != "ok":
            print(  # noqa: T201
                "[entrypoint] Database integrity check failed: "
                f"quick_check returned {status!r}",
                file=sys.stderr,
            )
            print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
            sys.exit(1)

        _check_foreign_keys(conn)
    except sqlite3.DatabaseError as e:
        print(f"[entrypoint] Database integrity check failed: {e}", file=sys.stderr)  # noqa: T201
        hint = (
            _BUSY_HINT
            if getattr(e, "sqlite_errorcode", None)
            in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            else _CORRUPTION_HINT
        )
        print(hint, file=sys.stderr)  # noqa: T201
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()
