# Release preparation and publication

This is the maintainer checklist for a controlled release, not authorization to
merge, tag, push an image or deploy. Keep validation PRs in draft until the
maintainer explicitly approves changing that state: owner auto-merge can merge
a ready PR and trigger publication.

## Source and quality gates

Use `latest` for integration; `release` and `v*` tags are publication paths.
`upstream` remains an exact mirror, never an integration merge source. Accepted
upstream outcomes and schema adaptations belong in [UPSTREAM_PORTS.md](../UPSTREAM_PORTS.md).
Do not rewrite published migrations or historical release tags.

Freeze a specific source commit with all intended implementation, tests and
documentation committed. Exclude local reports, private archives, databases,
backups and credentials. A build containing uncommitted edits does not verify
its recorded SHA. Record the commit/tree, run links and image digests; a PR's
synthetic merge commit may differ from its head SHA, so compare trees too.

The current publication workflow requires both built-image smoke and reusable
quality to succeed. Quality includes:

- Complete offline application/config tests, including normal slow/browser
  regressions; live-provider tests and explicitly opt-in workloads stay separate.
- MCP and script tests, Ruff, lock consistency and dependency advisories.
- Strict migration hygiene and missing-migration checks.
- Representative `v26.9.24` SQLite/PostgreSQL upgrade replay with retained user
  data and drift cases. This is not a guarantee for every historical version.

Use the repository runners described in [CONTRIBUTING.md](../CONTRIBUTING.md).
Report skips and failures accurately; fix confirmed failures without dropping
coverage or weakening a security gate. PR builds skip registry login and use
`push: false`. They do not exercise publication-only coverage/upload steps or
prove that registry attestations exist. Non-PR publishing must require both
quality and smoke success; do not bypass a failed or timed-out prerequisite.

## Upgrade notices for the first hardened release

Carry these points into the actual release notes before publication:

- **Breaking Celery message transition:** old pickle jobs can be discarded by
  JSON-only workers while status rows remain pending. Take a verified database,
  key and configuration backup, retain inputs, stop producers/beat, and drain
  all old queues, reserved and scheduled work before replacing workers. Avoid
  mixed versions, Redis flushes and pickle workarounds. Use the canonical
  [transition procedure](security-hardening.md#celery-json-transition), including
  partial-import inspection and supported resubmission.
- Recovery controls require the current password; the authenticator remains
  password recovery rather than login MFA. Startup backup download now uses a
  separate strong token in POST, not GET. See [security guidance](security-hardening.md).
- SQLite snapshots and failure reporting are repaired on Linux/macOS. Persist
  the database, backup path and original signing key, verify restores and keep
  encrypted off-host copies. CSV exports are incomplete recovery artifacts;
  PostgreSQL backup remains operator-managed. See [backup guidance](deployment.md#sqlite-data-paths).
- The historical `v26.10.1` migration graph conflicts on fresh installs and
  ordinary upgrades. Use a revision containing
  `users/0141_merge_search_all_discover_seerr.py`; retain data/key, never fake
  migration records or rewrite that historical tag. See [upgrade limits](install.md#afterwards).
- Authentication/integration boundaries, log/referrer privacy, runtime
  dependencies and container startup have been hardened. Existing public
  images gain none of these changes until rebuilt and actually distributed.
  Redis/cache and household accounts remain trusted boundaries; root startup,
  provider traffic and the documented operational limits remain.

## Publication checklist

1. Obtain explicit maintainer authorization. Merge the approved green candidate
   through the intended path; record the actual resulting publication SHA and
   verify any changed tree. Prepare the next version's release notes above.
2. Rehearse the documented upgrade/restore procedure for the installation's
   baseline. Existing pickle-era operators complete the drain before rollout;
   distribution alone cannot certify their queues or backups.
3. Only after authorization, use the intended release branch/version-tag flow.
   Observe all quality, upgrade and smoke prerequisites on that actual event.
   A green PR does not replace a failed release-event gate.
4. Record the new immutable multi-architecture index and each platform digest.
   Check both `ghcr.io/dannyvfilms/floppy` and the legacy
   `ghcr.io/dannyvfilms/yamtrack` while dual publication remains supported.
5. Retrieve the real SBOM and maximum-mode provenance for the distributed
   platform subjects. Check their digests, source revision and build materials;
   empty or missing objects are a verification failure, not proof of generation.
6. Freshly scan the distributed amd64 and arm64 digests. Record scanner/DB
   freshness, findings and any reviewed applicability exceptions; a clean
   Python audit alone does not cover OS packages or vendored browser code.
7. Pull by digest and verify baked identity, health/login/static responses,
   migrations, representative persistence and startup on both platforms.
   Follow [image verification](deployment.md#verifying-a-published-image-actually-has-a-fix).
8. Publish accurate release notes and upgrade warnings after those checks.
   Record digest/run evidence with the release. Digest pinning fixes bytes;
   unsigned BuildKit metadata does not establish a trusted signer identity.

Publication currently rebuilds after smoke rather than promoting the tested
digest. Post-publication verification therefore matters. If verification fails,
stop promotion and follow the operator's backup/rollback plan; an older image
alone cannot undo migrated data. Do not rewrite old tags to conceal a failure.

## Repository settings requiring maintainer action

Apply these in GitHub Settings only with separate administrative authorization:

- Protect `latest` and `release` through the intended PR path, require branches
  to be current, and require `lint`, `test (3.12)`, `Upgrade (sqlite)`,
  `Upgrade (postgres)`, `migration-order` and `Smoke built image` where those
  checks run. Select their actual GitHub check identities after a successful run.
  Ensure required workflows report a result for documentation-only PRs too;
  path-filtered workflows must not leave required checks permanently pending.
- Restrict `v*` tag creation/update/deletion to release operators. Prevent force
  pushes/deletion on protected branches. Limit administrator bypass to explicit
  emergency use rather than routine unchecked publication.
- Set default Actions permissions to read-only and disable workflow-created PR
  approval. Require full Action commit pins where available; keep workflow
  modifications limited to trusted contributors and maintain the pin updates.
- Keep PR builds read-only and publishing credentials in privileged jobs only.
  Review `AUTO_MERGE_TOKEN` and optional `GHCR_TOKEN` scope, expiry and need;
  retain normal `GITHUB_TOKEN` publication. Never expose those tokens to
  untrusted PR code or include them in build arguments.

No second general audit or heavyweight signing service is required for a
controlled release. Continuous image verification is tracked in
[#1625](https://github.com/dannyvfilms/Floppy/issues/1625), non-lockfile inputs in
[#1626](https://github.com/dannyvfilms/Floppy/issues/1626), backup visibility in
[#1627](https://github.com/dannyvfilms/Floppy/issues/1627), and incremental
maintainability in [#1628](https://github.com/dannyvfilms/Floppy/issues/1628).
These are bounded follow-ups, not claims of independent certification. Sensitive
findings belong in the [private security channel](../SECURITY.md), not public
issues or permanent audit retrospectives.
