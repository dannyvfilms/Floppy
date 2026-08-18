# SQLite relationship recovery

Floppy checks SQLite storage and relationships before Django migrations run. Recovery must protect user data first and must leave the database in a state that SQLite can validate during migrations.

## Why keep-and-start was retired

A broken foreign key can be tolerated by some normal reads, but Django checks SQLite constraints when a schema migration finishes. Starting with the same invalid relationship can therefore pass Floppy's preflight and then fail inside `migrate`.

For that reason, a blocked relationship incident no longer offers **keep everything and start Floppy**. A legacy `accept` choice is treated as retired. Floppy changes no row and returns to recovery instead of entering another migration loop.

## Repair the relationship, not every child row

Foreign-key failures do not all have the same ownership meaning. Recovery uses the table schema and a small allowlist of derived relationship tables to choose the least destructive valid repair.

### Nullable references

When the broken foreign key column is nullable, Floppy clears only that reference. It preserves the child row and its user-owned state.

For example, `Music.album` and `Music.track` are optional catalog references. If an album or track row is missing, recovery sets the invalid `album_id` or `track_id` to `NULL` instead of deleting the Music tracking row.

### Derived relationship rows

Some rows exist only to connect two catalog records. `AlbumArtist` is one example. If its required album parent is gone, the relationship row has no independent user state. Floppy may remove that derived row automatically after it creates and verifies a backup.

### Required-parent user-state rows

A row such as `AlbumTracker` carries user state and cannot remain valid when its required album parent is missing. Floppy does not remove that row automatically. It pauses and asks for an incident-scoped repair choice.

If the operator chooses repair:

1. Floppy acquires a SQLite write lock.
2. It verifies that the incident fingerprint still matches the live database.
3. It creates a consistent backup and runs `PRAGMA quick_check` on that backup.
4. It applies the least destructive repairs.
5. It runs `PRAGMA foreign_key_check` again.
6. It commits only when the required repair has converged to a clean foreign-key state.

The removed live row remains available in the verified recovery backup.

## Partial safe repair

A single database can contain several relationship classes at once. Floppy may first clear nullable references and remove known derived rows while preserving required-parent user-state rows.

If conflicts remain, Floppy writes a new bounded incident report with a new fingerprint and approval token. A choice made for the pre-repair incident cannot apply to the new database state.

This also matters for counts: `PRAGMA foreign_key_check` counts broken relationships, not unique rows. One Music row with both a missing album and a missing track contributes two relationship failures. The recovery page therefore describes **broken relationships** and does not claim that the displayed count is the number of rows that will be removed.

## Safety limits

Automatic recovery is disabled when Floppy cannot prove the affected table layout is safe to modify. Examples include an affected trigger, a shadowed SQLite row identifier, a `WITHOUT ROWID` shape that prevents stable row targeting, or a foreign key shape that the repair planner cannot classify safely.

In those cases Floppy changes nothing and requires a backup restore or manual repair.

Physical SQLite corruption is a separate failure class. A file that fails `PRAGMA quick_check` stays read-only from this relationship-recovery path and must be restored or repaired from a separate copy.

## Runtime and packaging

The recovery policy runs before Django migrations and does not depend on Redis, Celery, provider APIs, or internet access. The same Python policy is called from the shell entrypoint, so containers, source installs, offline systems, and future packaged runtimes can use the same relationship rules.

The recovery page also runs before Django. Its styles, scripts, and icon are self-contained so it remains usable while the normal application is unavailable and when the written copy is opened directly from disk.

## Performance

The integrity scan remains bounded and grouped. Repair uses set-based `UPDATE` and `DELETE` statements per relationship group rather than one write per reported row. Backup creation is streamed through SQLite's backup API and is required before a recovery write.

For a large incident, the number shown in the report can be much larger than the number of affected rows because one row can violate more than one foreign key. Recovery plans and logs therefore report actual reference clears and row removals separately.

## Incident history

- #731 exposed the original SQLite relationship-conflict boot loop and recovery-page need.
- #780 added bounded integrity reporting, verified backups, and quarantine support.
- #870 limited the lifetime of a keep-rows choice so it could not become a permanent bypass.
- #810 then proved that the keep-rows action itself was not migration-safe and that mixed Music relationships need ownership-aware repair.

The current policy keeps the useful backup, fingerprint, bounded-report, and recovery-page controls from that work while replacing generalized child-row deletion with relationship-specific repair.
