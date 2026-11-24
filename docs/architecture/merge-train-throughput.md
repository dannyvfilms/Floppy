# Merge train throughput: parallel refreshes, serial migrations

`latest` stays strict: lint, test (3.12) and migration-order from GitHub Actions
are required, and a branch must be up to date to merge. GitHub's merge queue needs
an organization, so the train (`scripts/merge_train.py`, run by
`.github/workflows/merge-train.yml`) is the queue.

The train does one thing: it merges `latest` into an approved PR's branch
(GitHub's "Update branch"). That restarts the PR's own CI, and GitHub's native
auto-merge lands it when it is green and still up to date. The train never opens
PRs, creates branches, merges anything or touches `latest`. Every PR merges as
itself, with its own commits, author and checks.

## Who is in the queue

Any open, non-draft PR targeting `latest` with native auto-merge on. Owner or
contributor, fork or not, makes no difference. A fork whose author turned off
"Allow edits from maintainers", or one GitHub refuses to let the token update
(HTTP 403), can't be refreshed. That fork is reported as a manual handoff, and
everything else keeps moving. The job summary quotes GitHub's reason for a
refusal. A refused PR is retried on every run, because a refusal changes nothing
on the branch.

Skipped, with the reason in the job summary: real merge conflicts, failed
required checks, required checks hung for hours or never started, a green PR
GitHub hasn't merged within 30 minutes (some other rule is holding it), and PRs
whose state the API couldn't report this run (retried next run).

## Two lanes

**Normal lane.** PRs that don't touch migrations. Up to `MERGE_TRAIN_DEPTH`
(repository variable, default 3, `1` gives the old one-at-a-time train) of them
can be up to date and testing at once. A PR that is already up to date and
running or green never blocks the others. Free slots are filled in this order:

1. PRs already green on an older `latest`, earliest green first. A PR approved
   more than two hours ago counts as ready from its approval time, so it can't
   starve.
2. Other approved PRs, oldest approval first.
3. PRs whose required check failed before `latest` moved get one refresh per new
   `latest`.

**Migration lane.** Any PR whose diff against `latest` adds, deletes or renames
anything under `src/*/migrations/` goes here. This includes rename sources, a
diff too large for the compare API to list (300 files), and a PR whose diff the
API couldn't return. One migration PR is refreshed at a time, oldest approval
first, as before. It must pass migration-order (duplicate numbers per app, graph
check with `latest` merged in) against the `latest` it merges into. A migration
PR in flight doesn't block the normal lane.

## Why this is safe with strict on

Strict mode means no stale green result can merge. When any PR lands, every
other in-flight PR is behind again and blocked. The next train run (woken by
the push to `latest`) refreshes it against the new `latest`, and it has to pass
again. Two migration PRs that each passed alone can't both land, because the
second must retest after the first and migration-order then sees the clash.

## What it costs and what it buys

With strict on, at most one PR can merge per full CI run on a given `latest`.
Each merge makes the rest retest. Running several refreshes at once doesn't
raise that ceiling. What it removes is idle time:

- the next PR is already testing when the current one lands,
- a PR that turns red after its refresh no longer costs a whole serial slot,
- no single PR (in flight, red, stuck or a refused fork) can hold every other
  PR in place.

The price is CI minutes. Of the PRs refreshed together, only the first to go
green merges; the others' runs are discarded and they refresh again. With depth
`d`, up to `d - 1` runs per merge are thrown away. Lower `MERGE_TRAIN_DEPTH`
if runner minutes matter more than latency.

## Wakeups

The train runs on a push to `latest`, on PR events (opened, edited,
auto-merge on/off, ready/draft, synchronize, reopened, closed), when App
Tests, Lint or Migration Order finish on a PR, on a 15-minute schedule as a
safety net, and by hand (dry run by default). CI events for heads that aren't
a current approved PR are ignored. One run is pending at a time.

## Rebuilding UI bundles during a refresh

The React bundles in `src/static/ui/` are committed and content-hashed, so two
frontend PRs often conflict there even when their source merges cleanly, and a
clean merge can still leave stale bundles. With the repository variable
`MERGE_TRAIN_REBUILD_UI` set to `true`, the train fixes this for an
owner-authored, same-repository, non-draft PR with auto-merge on, when the PR
changed UI build inputs (`frontend/`, `src/static/ui/`, `package.json`,
`package-lock.json`, `scripts/build_ui.mjs`, `.npmrc`) and either `latest`
changed them too or the merge conflicts. Everything else, including forks and
every non-UI refresh, keeps the API update and never installs Node. Unset the
variable to roll back.

Three separated steps, so no privileged token runs PR code:

1. **Plan** (`merge-train` job, as before): picks the PRs, respects lanes and
   depth, posts a hidden "started" comment and lists them in the `ui_refresh`
   output instead of calling the API. Dry runs only print.
2. **Build** (`ui-build` job): read-only token, no secrets, no stored
   credentials. Merges the exact head and `latest` SHAs. A conflict is tolerated
   only if every unmerged path (including deleted and renamed ones) is under
   `src/static/ui/`; any other conflict, migrations included, stays manual. It
   then deletes the output directory and runs `npm ci --ignore-scripts`,
   `npm run build:ui` and `npm run check:ui` on Node 22, and fails if the build
   changed any source file.
3. **Publish** (`ui-publish` job, has the token): treats the build output as
   data. It checks file names, types, sizes and checksums, that the PR is still
   open, owner-authored, same-repository with auto-merge on and its head unchanged
   and that `latest` has not moved, then redoes the merge itself and requires the
   same merged non-generated tree as the build. Only then does it write the files
   into `src/static/ui/` and push one merge commit (parents: PR head, `latest`)
   with a plain push, which GitHub refuses if the branch moved, so newer agent
   work is never overwritten. Nothing from the artifact is executed.

The ordinary required checks then run on that commit, and the branch still has to
be up to date to merge. No branches or PRs are created and nothing is merged or
bypassed.

A failed or unavailable rebuild posts a "failed" comment with the reason for that
head and `latest` pair. The PR then falls back to the plain API behaviour (a
conflicting PR is parked as before), so each pair is tried once and one PR's
failure never holds up the others. A refresh still running after 30 minutes
counts as failed. Only the owner's comments are read.

