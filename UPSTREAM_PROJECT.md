# Upstream resolution issue governance

> **Authoritative programme issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)
> **Durable decision ledger:** [`UPSTREAM_PORTS.md`](UPSTREAM_PORTS.md)
> **Phase 0 PR:** [#651](https://github.com/dannyvfilms/Floppy/pull/651)
> **Optional mirror:** [GitHub Project #1](https://github.com/users/dannyvfilms/projects/1)

## Purpose

The ledger records durable upstream decisions and evidence. Issue #645 is the authoritative operational index, with #646–#650 as its work-package sub-issues. GitHub issue state, labels, sub-issue relationships, dependency relationships, and linked pull requests show live execution.

Project #1 may mirror this structure later when write access is available, but it is never a gate or a source of truth. A project-field or project-card change cannot replace an issue relationship or ledger update.

## Phase 0 exit

Phase 0 is complete only when all of these conditions are verified:

- PR [#651](https://github.com/dannyvfilms/Floppy/pull/651) is merged.
- Issues [#646](https://github.com/dannyvfilms/Floppy/issues/646) through [#650](https://github.com/dannyvfilms/Floppy/issues/650) are linked as sub-issues of #645.
- Relevant programme issues and pull requests have the labels required below.
- PR [#638](https://github.com/dannyvfilms/Floppy/pull/638) is closed as superseded and links to `UPSTREAM_PORTS.md` as the replacement strategy.

Issue #645 stays open for the full programme. Runtime packages do not begin before the Phase 0 exit is verified unless #645 records a narrow exception.

## Issue relationships

| Item | Relationship | Role | Dependency or status rule |
|---|---|---|---|
| [#645](https://github.com/dannyvfilms/Floppy/issues/645) | Parent programme issue | Authoritative operational index | Remains open until the full programme is complete |
| [#646](https://github.com/dannyvfilms/Floppy/issues/646) | Sub-issue of #645 | Built-image smoke gate | Starts after Phase 0; blocks dependent platform and data packages |
| [#647](https://github.com/dannyvfilms/Floppy/issues/647) | Sub-issue of #645 | uv, lockfile, CI, lint, and Docker | Blocked by #646; no dependency upgrades during conversion |
| [#658](https://github.com/dannyvfilms/Floppy/issues/658) | Sub-issue of #647 | uv dependency source and lock foundation | Blocked by #646; supplies the base for #659 |
| [#659](https://github.com/dannyvfilms/Floppy/issues/659) | Sub-issue of #647 | Locked App Tests and standalone lint workflow | Blocked by #658; supplies the base for #660 |
| [#660](https://github.com/dannyvfilms/Floppy/issues/660) | Sub-issue of #647 | Docker, local tooling, and repository-documentation cutover | Blocked by #659 and #670; completes the no-upgrade codebase conversion |
| [#669](https://github.com/dannyvfilms/Floppy/issues/669) | Sub-issue of #647 | Publish the matching GitHub Wiki commands | Blocked by #660; #647 remains open until this separately authorized follow-up is published |
| [#670](https://github.com/dannyvfilms/Floppy/issues/670) | Sub-issue of #647 | Resolve the fail-closed aiohttp security audit | Blocks #660; keep all three advisories unsuppressed and review the dependency change independently |
| [#648](https://github.com/dannyvfilms/Floppy/issues/648) | Sub-issue of #645 | Datetime/calendar integrity and import-date fixes | Blocked by #646; final runtime semantics precede audit and migrations |
| [#649](https://github.com/dannyvfilms/Floppy/issues/649) | Sub-issue of #645 | MAL, AniList, and Open Library correctness | Blocked by #646; AniList unknown dates coordinate with #648 |
| [#650](https://github.com/dannyvfilms/Floppy/issues/650) | Sub-issue of #645 | Identity audit, repair, and constraints | Blocked by #646 and relevant #648 semantics |
| [#597](https://github.com/dannyvfilms/Floppy/issues/597) | Related coordination issue | Reusable deployment preflight | Relates to #646; not a child unless its scope is explicitly moved into #645 |
| [#639](https://github.com/dannyvfilms/Floppy/issues/639) | Related evidence issue | Cross-provider episode/calendar duplicate regression | Relates to #650; remains independently closeable |
| [#390](https://github.com/dannyvfilms/Floppy/issues/390) | Related evidence issue | Existing CI/Ruff signal | Relates to #647; preserve or deliberately replace its chosen policy |
| [#512](https://github.com/dannyvfilms/Floppy/issues/512) | Related coordination issue | Low-tier performance/startup audit | Receives evidence from #646 and #647; not a child by default |

Closed issues remain evidence rather than active children. Relevant examples include #30, #36, #246, #295, #379, #529, #557, #559, #593, #604, #620, and #623.

## Pull request, label, status, and dependency rules

| Pull request | Programme relationship |
|---|---|
| [#651](https://github.com/dannyvfilms/Floppy/pull/651) | Phase 0 ledger and governance; linked to #645 and required for the Phase 0 exit |
| [#653](https://github.com/dannyvfilms/Floppy/pull/653) | Independent first-run query-budget repair; narrow Phase 0 exception recorded on #645 |
| [#654](https://github.com/dannyvfilms/Floppy/pull/654) | Independent CI pull request; linked to #645 and related to #390, with no code dependency on #651 or #653 |
| [#656](https://github.com/dannyvfilms/Floppy/pull/656) | Built-image smoke gate; bottom layer of the #647 delivery stack |
| [#663](https://github.com/dannyvfilms/Floppy/pull/663) | uv dependency and lock foundation; stacked on #656 |
| [#665](https://github.com/dannyvfilms/Floppy/pull/665) | Locked CI and lint workflows; stacked on #663 |
| [#638](https://github.com/dannyvfilms/Floppy/pull/638) | Superseded merge/cherry-pick strategy; close with a link to the semantic-resolution ledger |

1. Give each active work-package issue exactly one `priority: P0` through `priority: P3` label and the applicable `area:*` labels. Add `bug`, `technical debt`, or `documentation` only when it describes the work.
2. Give implementation pull requests `triage: linked PR` and the area and priority labels of the work they deliver. At Phase 0 exit, verify the relevant labels on #645–#650 and the independent #651, #653, and #654 pull requests.
3. Use sub-issues only for work owned by #645. Use native blocked-by/blocks relationships for sequencing and related links for coordination or evidence; do not turn #597, #639, #390, or #512 into children solely for visibility.
4. Keep an issue open while accepted scope remains. Close a work-package issue only after its merged pull requests and validation evidence are recorded in `UPSTREAM_PORTS.md`; keep #645 open until every programme outcome is terminal.
5. Do not close a concrete bug because a broader package exists. Keep closed historical issues closed and use them as evidence.
6. When a decision changes, update `UPSTREAM_PORTS.md`; issue state and labels are operational metadata, not durable decision evidence.
7. After each upstream review, create or link scoped issues only for accepted Pending work. Do not create execution issues for merge commits, release bumps, generated churn, discarded implementations, or individual dependency-bot commits.

## Pull request topology

Use GitHub's native [stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/stacked-pull-requests), currently a public preview, through GitHub's official `gh stack` extension only for genuine code dependencies. Do not create a stack merely to couple reviews of otherwise independent work.

- Keep every stack in the Floppy repository. The bottom pull request targets `latest`; each higher pull request targets the branch immediately below it. Every layer must satisfy the same branch rules and CI gates.
- Merge bottom-up, either one layer at a time or as a contiguous group starting at the lowest unmerged layer. Use the supported cascading rebase and automatic retargeting when lower layers change or merge.
- Keep stacks short and reviewable: the default maximum is three layers unless a documented dependency requires more.
- The #656 → #663 → #665 → #660 delivery is the recorded temporary four-layer exception: the repository's workflow guard requires CI-only changes to remain separate while each later layer genuinely consumes the earlier uv foundation.
- PRs [#651](https://github.com/dannyvfilms/Floppy/pull/651), [#653](https://github.com/dannyvfilms/Floppy/pull/653), and [#654](https://github.com/dannyvfilms/Floppy/pull/654) remain independent because none has a code dependency on another.
- Candidate stacks are #646 smoke gate -> the dependent #647 uv/Docker adaptation; #648 runtime semantics -> read-only audit -> migrations; and #650 audit -> repair -> constraint. MAL and Open Library fixes remain independent; AniList may stack on the #648 unknown-date layer when it depends on those semantics.
- Each layer still requires the user's separate merge authorization. Never use a stack to merge Yamtrack history, and never merge a contiguous group unless every included layer has been authorized.

## Execution order

1. Merge #651, verify the Phase 0 issue relationships and labels, and close #638 as superseded; keep #645 open.
2. Review #653 and #654 independently under their own authorization and validation gates.
3. Complete #646.
4. Complete #647 in order: #658 lock foundation, #659 locked CI, independently resolve the unsuppressed #670 security blocker, complete the no-upgrade #660 Docker/tooling/repository-documentation cutover, then publish the separately authorized #669 Wiki update. Keep #647 open until #669 is published.
5. Land isolated correctness fixes within #648 and #649, then their larger staged packages.
6. Complete the audit/repair/constraint sequence in #650.
7. Create focused issues for deferred product work only when its ledger trigger fires.
