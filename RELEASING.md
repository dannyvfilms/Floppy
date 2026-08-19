# Releasing Floppy

This document is the maintainer runbook for Floppy container releases.

The release workflow has one stable publication path. A branch update is not a release.

## Container channels

| Git event | Container result |
|---|---|
| Pull request | Build and smoke-test only. Nothing is published. |
| Push or merge to `latest` | Publish the moving `:dev` channel. |
| Push or merge to `release` | Build and smoke-test only. Stable tags do not move. |
| Manual workflow dispatch | Validation only. Nothing is published. |
| `vX.Y.Z` tag at the exact `release` HEAD | Publish `:latest`, `:release`, `:X.Y.Z`, `:X.Y`, and `:X`. |

The same approved tags are published to the legacy `yamtrack` package during the rename grace period. Do not add a second publication path for that package.

## Why this contract exists

`latest` is the integration branch. It changes often and is not the stable release line. Its container is therefore `:dev`.

`release` is the stable candidate branch. Moving that branch prepares or reconciles release state, but it does not publish a stable image.

`:latest` is Docker's default channel and is treated as stable. It moves only when a maintainer creates a version tag from the verified `release` HEAD.

Pull requests never authenticate to GHCR and never publish registry tags. This preserves the behavior established by #782 and merged PR #793. The stable/default and development channel split follows #797.

## Current release-line reconciliation

The currently published stable release is `v26.8.13` at commit `bc11aab42b29abfa4b8fe14f450ee33c890dd2a8`.

The historical `release` branch diverged before that tag. It also has one release-only funding commit. The funding file is byte-for-byte identical in `v26.8.13`, so there is no unique release-tree content to recover.

Do **not** force-reset `release` to the tag. Reconcile it with a merge so both histories remain reachable. The reconciled application tree must match `v26.8.13`; only release-policy workflow/documentation changes may differ.

Reconciliation is not a new release. Because a `release` branch push does not publish, aligning the branch to the existing `v26.8.13` state cannot move stable container tags.

## Create a future stable release

1. Prepare and validate the intended release on `latest`.
2. Open a PR from the intended release state into `release`.
3. Run the required application, migration, Docker, security, and upgrade-path QA. Merge only when the release candidate is accepted.
4. Confirm the exact `release` HEAD that will ship.
5. In GitHub Releases, create a new tag named exactly `vX.Y.Z` and target **the current `release` HEAD**. Do not create the stable tag from `latest`, another branch, or an older release commit.
6. Publish the GitHub Release. The Docker workflow verifies that the tag resolves to the exact current `release` HEAD before registry login.
7. After smoke and multi-architecture build succeed, the workflow automatically publishes:
   - `ghcr.io/dannyvfilms/floppy:latest`
   - `ghcr.io/dannyvfilms/floppy:release`
   - `ghcr.io/dannyvfilms/floppy:X.Y.Z`
   - `ghcr.io/dannyvfilms/floppy:X.Y`
   - `ghcr.io/dannyvfilms/floppy:X`
   - the same approved aliases to the legacy package during the rename grace period.
8. Verify the tag workflow and the published image before announcing the release.

No separate registry command is required. Do not run a manual workflow to publish stable images.

## Failure behavior

The workflow fails before registry login if:

- the tag does not match `vX.Y.Z`;
- the tag points anywhere other than the exact current `release` HEAD.

A direct push to `release` cannot publish stable tags. A manual workflow dispatch cannot publish stable tags. A pull request cannot publish any registry tag.

If a release was tagged from the wrong commit, do not move or reuse that version tag. Correct the release state and create a new version according to the project versioning policy.

## Development images

Every accepted push to `latest` continues to build, smoke-test, and publish `:dev`. This is the opt-in moving integration channel.

Do not use `:dev` in the default self-hosting instructions. Users who follow the normal install path should remain on stable `:latest` unless they deliberately choose the development channel.

## Related history

- #782 — PR builds were writing public `pr-N` package versions.
- #793 — stopped PR publication while preserving multi-architecture build coverage.
- #797 — separated the stable/default channel from the moving integration channel.

These controls are one contract. Do not change tag generation, registry login conditions, or `push:` behavior independently without re-validating all three event classes: PR, development branch, and stable release tag.
