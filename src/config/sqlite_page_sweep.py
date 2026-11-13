"""Whole-database structural sweep in physical page order.

``PRAGMA quick_check`` walks each b-tree in key order. After churn that order
bears no relation to file order, so on storage where a random read costs a
seek every page is a separate round trip (a 5.2 GB database took 1.9 h, almost
all of it I/O wait). This sweep reads every page exactly once, in file order,
and rebuilds the page graph in memory (a few bytes per page):

* page 1 header, page size, header page count vs. the file;
* every b-tree page: type, cell count, cell-pointer array and content area
  bounds, freeblock start, fragmentation counter, every cell pointer in range;
* every interior child pointer: in range, not the page itself, referenced at
  most once, and pointing at a b-tree page of the same family;
* every schema root: a b-tree page of the right family, referenced once;
* the freelist trunk chain: bounds, leaf counts, total equals the header, no
  page both free and in a tree;
* b-tree-typed pages nobody references ("never used" orphans).

It does NOT parse cells, so it cannot see overflow-chain damage, record format
errors, key ordering or index/table disagreement. ``quick_check`` covers the
first three and remains the (slower) deep tier; no tool here checks the last.
"""

from __future__ import annotations

import os
import sqlite3
import struct
import time
from array import array
from pathlib import Path

_BTREE = {2: "i", 5: "t", 10: "i", 13: "t"}  # type byte -> key family
_INTERIOR = {2, 5}
_CHUNK_PAGES = 2048
_MAX_PROBLEMS = 20
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _varint(blob, position: int) -> tuple[int, int]:
    value = 0
    for step in range(8):
        byte = blob[position + step]
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:  # noqa: PLR2004
            return value, position + step + 1
    return (value << 8) | blob[position + 8], position + 9


def _overflow(kind_byte: int, payload: int, usable: int) -> int:
    """Bytes held locally for a cell, or -1 when it has no overflow chain."""
    maximum = usable - 35 if kind_byte == 13 else (usable - 12) * 64 // 255 - 23  # noqa: PLR2004
    if payload <= maximum:
        return -1
    minimum = (usable - 12) * 32 // 255 - 23
    local = minimum + (payload - minimum) % (usable - 4)
    return local if local <= maximum else minimum


_TABLE_INTERIOR = 5
_FREE = 2
_FIRST = 2  # page 1 is the schema root; nothing may point at it


def _chains(blob, base: int, pointers, kind_byte: int, usable: int) -> list:
    """(first overflow page, page count) for every cell that spills."""
    found = []
    for pointer in pointers:
        position = base + pointer + (4 if kind_byte == 2 else 0)  # noqa: PLR2004
        payload, position = _varint(blob, position)
        if kind_byte == 13:  # noqa: PLR2004
            _, position = _varint(blob, position)
        local = _overflow(kind_byte, payload, usable)
        if local >= 0:
            first = struct.unpack_from(">I", blob, position + local)[0]
            found.append((first, -(-(payload - local) // (usable - 4))))
    return found


class SweepUnavailableError(Exception):
    """No consistent page source (needs ``sqlite_dbpage`` or an empty WAL)."""


class SweepExpiredError(Exception):
    """The deadline passed; nothing was concluded."""


def _chunks(db_path: str, page_size: int, page_count: int, conn):
    """Yield ``(first_pgno, bytes)`` for consecutive pages, in file order."""
    try:
        conn.execute("SELECT 1 FROM sqlite_dbpage LIMIT 0")
        use_dbpage = True
    except sqlite3.OperationalError:
        use_dbpage = False
    if use_dbpage:  # pager view: WAL-aware, one read snapshot
        for first in range(1, page_count + 1, _CHUNK_PAGES):
            last = min(first + _CHUNK_PAGES - 1, page_count)
            rows = conn.execute(
                "SELECT data FROM sqlite_dbpage WHERE pgno BETWEEN ? AND ? "
                "ORDER BY pgno",
                [first, last],
            ).fetchall()
            yield first, b"".join(r[0] for r in rows)
        return
    wal = Path(f"{db_path}-wal")
    if wal.exists() and wal.stat().st_size:
        msg = "pages may live in the WAL and sqlite_dbpage is not compiled in"
        raise SweepUnavailableError(msg)
    with Path(db_path).open("rb", buffering=0) as handle:
        for first in range(1, page_count + 1, _CHUNK_PAGES):
            handle.seek((first - 1) * page_size)
            yield first, handle.read(_CHUNK_PAGES * page_size)


def sweep(db_path: str, deadline: float | None = None) -> dict:
    """Return ``{"pages": n, "problems": [...]}``; raises on expiry/unavailable."""
    conn = sqlite3.connect(
        f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, timeout=5
    )
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA mmap_size=0")
        conn.execute("BEGIN")  # one snapshot for the whole sweep
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        reserved = (
            struct.unpack_from(
                ">B",
                conn.execute("SELECT data FROM sqlite_dbpage WHERE pgno=1").fetchone()[
                    0
                ],
                20,
            )[0]
            if _has_dbpage(conn)
            else _raw_reserved(db_path)
        )
        usable = page_size - reserved
        roots = conn.execute(
            "SELECT type, rootpage FROM sqlite_schema WHERE rootpage > 0"
        ).fetchall()
        free_total = conn.execute("PRAGMA freelist_count").fetchone()[0]
        autovacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        trunk = _first_trunk(conn, db_path)
        problems: list[str] = []
        kind = bytearray(page_count + 1)  # 0 none, else the b-tree type byte
        ref = bytearray(page_count + 1)  # 1 = child/root ref, 2 = freelist
        children: list[tuple[int, int]] = []  # (parent, child) for kind checks
        following = array(
            "I", bytes(4 * (page_count + 1))
        )  # first word of non-tree pages
        chains: list[tuple[int, int, int]] = []  # (cell page, first overflow, pages)

        def bad(message: str) -> None:
            if len(problems) < _MAX_PROBLEMS:
                problems.append(message)

        freed = 0
        while trunk and freed <= free_total and len(problems) < _MAX_PROBLEMS:
            if not _FIRST <= trunk <= page_count or ref[trunk]:
                bad(f"freelist trunk {trunk} is invalid or in use")
                break
            ref[trunk] = _FREE
            freed += 1
            data = _page(conn, db_path, trunk, page_size)
            next_trunk, leaves = struct.unpack_from(">II", data, 0)
            if leaves > usable // 4 - 2:
                bad(f"freelist trunk {trunk}: {leaves} leaves exceed capacity")
                break
            for leaf in struct.unpack_from(f">{leaves}I", data, 8):
                if not _FIRST <= leaf <= page_count or ref[leaf]:
                    bad(f"freelist leaf {leaf} is invalid or in use")
                else:
                    ref[leaf] = _FREE
                    freed += 1
            trunk = next_trunk
        if freed != free_total and len(problems) < _MAX_PROBLEMS:
            bad(f"freelist holds {freed} pages, header says {free_total}")

        ptrmap_step = usable // 5 + 1 if autovacuum else 0
        seen = 0
        for first, blob in _chunks(db_path, page_size, page_count, conn):
            if deadline is not None and time.monotonic() > deadline:
                raise SweepExpiredError
            count = len(blob) // page_size
            if first + count - 1 < min(page_count, first + _CHUNK_PAGES - 1):
                bad(f"file ends at page {first + count - 1}, header says {page_count}")
            for index in range(count):
                pgno = first + index
                base = index * page_size
                offset = base + (100 if pgno == 1 else 0)
                if ref[pgno] == _FREE or (
                    ptrmap_step and (pgno - 2) % ptrmap_step == 0
                ):
                    continue  # pointer-map page: arbitrary content
                kind_byte = blob[offset]
                if kind_byte not in _BTREE:
                    if pgno == 1:
                        bad("page 1 is not a b-tree page")
                    following[pgno] = struct.unpack_from(">I", blob, base)[0]
                    continue
                kind[pgno] = kind_byte
                header = 12 if kind_byte in _INTERIOR else 8
                cells = struct.unpack_from(">H", blob, offset + 3)[0]
                start = struct.unpack_from(">H", blob, offset + 5)[0] or 65536
                free_block = struct.unpack_from(">H", blob, offset + 1)[0]
                fragments = blob[offset + 7]
                array_end = offset - base + header + 2 * cells
                if (
                    array_end > start
                    or start > usable
                    or fragments > 60  # noqa: PLR2004
                    or (free_block and not (start <= free_block <= usable - 4))
                ):
                    bad(f"page {pgno}: invalid b-tree page header")
                    continue
                if cells:
                    pointers = struct.unpack_from(f">{cells}H", blob, offset + header)
                    if min(pointers) < start or max(pointers) > usable - 4:
                        bad(f"page {pgno}: cell pointer outside the content area")
                        continue
                    if kind_byte in _INTERIOR:
                        children.extend(
                            (pgno, struct.unpack_from(">I", blob, base + pointer)[0])
                            for pointer in pointers
                        )
                    if kind_byte != _TABLE_INTERIOR:
                        try:
                            self_chains = _chains(
                                blob, base, pointers, kind_byte, usable
                            )
                        except (IndexError, struct.error):
                            bad(f"page {pgno}: cell runs past the page")
                            continue
                        chains.extend((pgno, *item) for item in self_chains)
                if kind_byte in _INTERIOR:
                    children.append(
                        (pgno, struct.unpack_from(">I", blob, offset + 8)[0])
                    )
            seen += count
        if seen != page_count:
            bad(f"read {seen} pages, header says {page_count}")

        def reference(parent: int | None, child: int, family: str | None) -> None:
            where = f"page {parent}" if parent else "schema"
            if not _FIRST <= child <= page_count or child == parent:
                bad(f"{where}: reference to invalid page {child}")
            elif ref[child]:
                bad(f"page {child}: referenced twice (second from {where})")
            elif kind[child] not in _BTREE:
                bad(f"{where}: child {child} is not a b-tree page")
            else:
                ref[child] = 1
                if family and _BTREE[kind[child]] != family:
                    bad(f"{where}: child {child} has the wrong b-tree family")

        kind_of_parent = {}
        for parent, _child in children:
            kind_of_parent.setdefault(parent, _BTREE[kind[parent]])
        ref[1] = 1
        for object_type, root in roots:
            if not 1 <= root <= page_count or kind[root] not in _BTREE:
                bad(f"schema root {root} is not a b-tree page")
            elif root != 1:
                if ref[root]:
                    bad(f"root {root} referenced twice")
                ref[root] = 1
                if object_type == "index" and _BTREE[kind[root]] != "i":
                    bad(f"root {root} has the wrong b-tree family")
        for parent, child in children:
            reference(parent, child, kind_of_parent[parent])

        for owner, first, pages in chains:
            page = first
            for step in range(pages):
                if not _FIRST <= page <= page_count or kind[page] or ref[page]:
                    bad(f"page {owner}: overflow chain broken at page {page}")
                    break
                ref[page] = 3
                page = following[page]
                if step == pages - 1 and page:
                    bad(f"page {owner}: overflow chain longer than its payload")

        if not autovacuum:  # pointer-map pages would look unreferenced
            lock_byte = (1 << 30) // page_size + 1
            orphans = [
                p for p in range(1, page_count + 1) if not ref[p] and p != lock_byte
            ]
            for pgno in orphans[:5]:
                bad(f"page {pgno}: never used")
        return {"pages": page_count, "problems": problems}
    finally:
        conn.close()


def _has_dbpage(conn) -> bool:
    try:
        conn.execute("SELECT 1 FROM sqlite_dbpage LIMIT 0")
    except sqlite3.OperationalError:
        return False
    return True


def _raw_reserved(db_path: str) -> int:
    with Path(db_path).open("rb") as handle:
        header = handle.read(100)
    if header[:16] != _SQLITE_MAGIC:
        msg = "not a SQLite database"
        raise sqlite3.DatabaseError(msg)
    return header[20]


def _first_trunk(conn, db_path: str) -> int:
    if _has_dbpage(conn):
        header = conn.execute("SELECT data FROM sqlite_dbpage WHERE pgno=1").fetchone()[
            0
        ]
    else:
        with Path(db_path).open("rb") as handle:
            header = handle.read(100)
    return struct.unpack_from(">I", header, 32)[0]


def _page(conn, db_path: str, pgno: int, page_size: int) -> bytes:
    if _has_dbpage(conn):
        return conn.execute(
            "SELECT data FROM sqlite_dbpage WHERE pgno=?", [pgno]
        ).fetchone()[0]
    fd = os.open(db_path, os.O_RDONLY)
    try:
        return os.pread(fd, page_size, (pgno - 1) * page_size)
    finally:
        os.close(fd)
