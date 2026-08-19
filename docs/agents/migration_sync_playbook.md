# Upstream Migration Adaptation Playbook

This playbook is the hard-gate process for implementing an accepted Yamtrack migration outcome in Floppy. It does not merge or rebase the `upstream` mirror into `latest`.

## Branch model

- `upstream` remains an exact mirror of `FuzzyGrim/Yamtrack:dev`. Never commit to it or target it with a PR.
- `latest` is Floppy's integration branch. Upstream outcomes reach it through reviewed Floppy branches and PRs.
- `release` remains the versioned release/container publication branch.

[`UPSTREAM_PORTS.md`](../../UPSTREAM_PORTS.md) records whether an upstream outcome is Pending, Ported, Adapted, Superseded, Deferred, or Discarded. An upstream migration is evidence of intent and historical data shape, not a file to retain or cherry-pick.

## Migration policy

- Define the desired final runtime and data semantics before writing a migration.
- Inspect the entire upstream outcome, including later repair migrations and regression tests. Do not replay a known-unsafe intermediate state.
- Audit Floppy's current schema, migration graph, supported release snapshots, and affected rows.
- Generate new Floppy-native migrations against the current graph. Never copy upstream migration names, numbers, dependencies, or deployment-window assumptions.
- Never rewrite a migration present in `origin/latest` or a `v*` release tag. Resolve Floppy-only concurrent leaf nodes with a Floppy merge migration when necessary.
- Make data transforms idempotent where practical, bounded for large tables, and explicit about irreversible operations.
- Never silently delete or guess ambiguous user data. Repair deterministically, export/quarantine ambiguity, or block the constraint.
- Document backup, recovery, reverse-operation, SQLite, and PostgreSQL behaviour in the owning issue and PR.

## Adaptation gate

1. Confirm the accepted ledger row and owning issue.
2. Read the upstream implementation, tests, migration, and every follow-up repair in the outcome group.
3. Specify final semantics and add a regression test or read-only detector that demonstrates the Floppy gap.
4. Add a read-only audit for risky data changes and test it on representative data.
5. Implement runtime semantics before schema enforcement when application code must tolerate old and new rows during rollout.
6. Create the Floppy migration from the current graph with `makemigrations`; review every generated operation and write only the required data transform.
7. Run migration hygiene:
   - `uv run --no-sync python src/manage.py check_migration_hygiene --strict`
8. Replay representative upgrades on both databases, including drift scenarios:
   - `scripts/replay_upgrade_matrix.sh --from-tag <previous_release_tag> --to-ref <branch> --db sqlite,postgres --with-drift-scenarios`
9. Run targeted migration/model/import tests, then the full relevant application suite through `scripts/test.sh`.
10. Record row counts, audit before/after results, database coverage, irreversibility, and recovery evidence in the PR. Do not merge while a gate is red.

## Required drift regression

The PostgreSQL replay retains the issue-class #101 scenario:

1. Migrate to `users.0067_remove_user_tv_sort_valid_and_more`.
2. Drop `boardgame_sort_valid` manually.
3. Apply `users.0068_remove_user_tv_sort_valid_and_more`.
4. Confirm the migration succeeds.

## Troubleshooting

- Multiple Floppy leaf nodes: inspect their operations, then create a merge migration only when the branches are compatible.
- Risky raw constraint/index operations: use the repository's existing idempotent migration wrappers where applicable.
- SQLite passes but PostgreSQL fails: treat the PostgreSQL failure as blocking.
- A later upstream repair contradicts the first migration: implement and test the repaired final state once.
- Audit finds ambiguous or lossy rows: stop schema enforcement and use the owning issue's recovery path.
