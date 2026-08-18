# SQLite runtime safety

Floppy uses SQLite when `DB_HOST` is not set. SQLite is a local database and does not need a network service.

## WAL-reset corruption guard

SQLite documents a WAL-reset bug that can corrupt a database when all of these conditions occur:

1. the database uses WAL journal mode;
2. two or more connections are open in separate threads or processes; and
3. writes and checkpoints occur at the same time.

This can match a Floppy installation that runs web and background workers while imports write media state.

SQLite reports the bug in releases from 3.7.0 through 3.51.2. The fix is in 3.51.3 and later. SQLite also supplies fixed backports in 3.44.6 and 3.50.7.

Source: [SQLite WAL documentation — WAL-reset bug](https://www.sqlite.org/wal.html#the_wal_reset_bug).

## Floppy behavior

Floppy checks the SQLite library used by Python before Django or Celery opens the database.

- If `SQLITE_JOURNAL_MODE` is `WAL` and the SQLite runtime has the fix, Floppy keeps WAL mode.
- If `SQLITE_JOURNAL_MODE` is `WAL` and the runtime is affected, Floppy uses `DELETE` journal mode and writes a startup warning.
- If an operator selected another supported journal mode, Floppy keeps that mode.
- PostgreSQL installations are not changed.

The guard uses the linked Python SQLite runtime. It does not assume a Docker image, Linux distribution, package manager, or network connection.

To see the SQLite library used by Python:

```bash
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

## Performance

WAL normally gives better write concurrency, so Floppy keeps it on fixed SQLite releases. The rollback journal is a temporary safety fallback for affected releases. A write-heavy installation can have more lock contention while the fallback is active.

Upgrade the SQLite library used by Python to a fixed release to restore WAL automatically. Do not force WAL on an affected runtime to recover performance; that restores the corruption condition.

## Configuration validation

Floppy accepts these SQLite journal modes:

- `DELETE`
- `TRUNCATE`
- `PERSIST`
- `MEMORY`
- `WAL`
- `OFF`

Floppy accepts these `SQLITE_SYNCHRONOUS` values:

- `OFF` or `0`
- `NORMAL` or `1`
- `FULL` or `2`
- `EXTRA` or `3`

Unexpected values are rejected before they can become SQLite PRAGMA grammar.

## Recovery scope

This guard prevents the known WAL-reset condition. It does not replace the startup integrity check, verified backups, or SQLite recovery tools. Those controls remain separate because an existing database can already contain damage from an older run, storage failure, or another cause.

No schema migration is required for this change.