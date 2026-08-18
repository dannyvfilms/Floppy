# Provider storage and migration safety

Floppy stores metadata from providers that Floppy does not control. Provider text can change length without a Floppy release. Database fields must therefore distinguish between values that have a real application bound and opaque provider payloads that do not.

## Storage rules

- Keep identifiers bounded when the provider contract gives a stable bound or Floppy needs the bound for identity and indexes.
- Do not silently truncate identifiers. Reject or report an invalid identity instead.
- Store opaque artwork URLs and data URIs in text fields when they are not indexed. Signed URLs, CDN parameters, and inline placeholders can exceed Django `URLField`'s 200-character default.
- Keep user-visible names bounded where the application has a deliberate display/storage contract. Validate before persistence if provider data can exceed that contract.
- Do not use database-specific truncation behavior as validation. SQLite and PostgreSQL must accept or reject the same application value intentionally.

## Migration rules

A data migration must not write a value that the schema at that migration state cannot store.

When a value needs more space:

1. make the old data migration safe to replay by skipping storage that cannot hold the new value;
2. widen the field without deleting or rewriting existing values;
3. run the data rewrite after the widening migration;
4. add a regression test for both the bounded and widened migration states.

Migrations `0155` through `0157` use this sequence for the image placeholder. This is important for PostgreSQL because `varchar(n)` rejects oversized values instead of accepting them as SQLite can.

## Runtime behavior

Provider metadata failures should not make an otherwise valid media page unavailable when the data can be stored safely. The studio logo field is therefore text storage rather than a 200-character URL field. The complete provider value is preserved; it is not truncated.

This does not add network access, a cache dependency, or a Docker requirement. The schema is valid for SQLite, PostgreSQL, source installs, containers, and packaged runtimes.

## Recovery and upgrades

These changes do not rewrite or delete existing media records. `ALTER ...` widening changes preserve existing values. Operators should still take normal verified backups before application upgrades.

If a container reports code behavior that does not match the migration source for its reported commit, treat that as a package/image provenance problem. Record the image tag or digest and rebuild or pull the intended image before attempting manual database repair.
