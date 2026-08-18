# SQLite recovery decision lifetime

Floppy checks SQLite storage and relationships before migrations run. A recovery choice must protect data first and must also let startup make progress.

## Keep rows

The **keep rows** choice means: keep the affected rows unchanged and try one startup.

It is not a permanent exception to the integrity check. A later migration can require valid foreign keys even when normal application reads can tolerate the existing rows. If the same relationship incident is still present on the next start, Floppy reopens recovery and asks for a new choice.

When Floppy reopens a previous keep-rows decision:

- it changes no database row;
- it disables automatic orphan removal for that integrity pass;
- it ignores a persistent recovery-action environment value for that pass;
- it writes a new incident-scoped approval token;
- it returns to the recovery page before migrations run.

This prevents a failed startup from turning into an unapproved delete on the next restart.

## Remove orphaned child rows

Removal remains a separate explicit recovery action when the affected tables are safe to address. Before any row is removed, Floppy creates and verifies a SQLite backup. It checks the remaining foreign-key state before it commits the change.

A relationship incident that cannot be quarantined safely stays blocked for manual repair.

## Already damaged databases

This recovery flow is for relationship conflicts in a readable SQLite database. It does not repair physical SQLite corruption. A file that fails `PRAGMA quick_check` stays read-only from the recovery path and must be restored or repaired from a separate copy.

## Runtime and packaging

The policy runs in the Python startup path and the shell entrypoint. It does not depend on Redis, provider APIs, or internet access. Container, source, offline, and packaged runtimes should use the same recovery decision semantics.

The startup check is intentionally before Django migrations. This keeps a relationship problem from becoming a migration loop and keeps recovery available when the normal application cannot start.
