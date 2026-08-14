# QA handoff — Floppy API grounding contracts

Written 2026-08-14 for the QA agent taking over. Everything you need is here;
you should not need to reconstruct history.

## Repo and branch layout

| What | Where |
|---|---|
| Main checkout | `/home/ryan/code/Floppy` (branch `feat/591-pin-zxing`, untouched) |
| This work | `/home/ryan/code/floppy-jsonld` (branch `feat/jsonld-domain-context`) |
| Base of this branch | `origin/codex/openapi-grounding-contracts` @ `6a667843` = PR #742 head |
| Upstream target | `latest` |

`feat/jsonld-domain-context` is **stacked on PR #742**. It cannot target
`latest` directly, because it imports `src/app/domain_vocabulary.py`, which
#742 introduces. Review it as a stacked PR with base
`codex/openapi-grounding-contracts`.

Test env: run `uv sync` in the worktree first. Test command is
`SECRET=test-only scripts/test.sh` (the `SECRET` prefix is mandatory; without
it settings refuse to load).

## Background: what shipped before you

### PR #742 — verified API grounding contracts (already reviewed, conflicts resolved)

Publishes a committed 41-operation OpenAPI subset, a generated domain
vocabulary, an offline API docs page, MCP hardening, and drift-gate tests.

- Conflicts against `latest` were resolved by merging `origin/latest`
  (`8a26dcd0`). The merge was textually clean, zero conflicted files. Pushed as
  `6a667843`. GitHub now reports `MERGEABLE`.
- Full review evidence, including a drift-gate mutation proof and measured
  token costs, is at
  `~/.gstack/projects/dannyvfilms-Floppy/ryan-pr-742-conflicts-review-test-outcome-20260814-1500.md`.
  **Read that file before re-reviewing #742** so you do not repeat work.
- Known non-issue: `app.tests.test_data_paths.DataPathSettingsTests.test_generated_secret_uses_the_configured_data_directory`
  fails **locally only**. python-decouple walks up out of any worktree nested
  under `/home/ryan/code/Floppy` and finds that repo's `.env`, which sets
  `SECRET`, so the probe never generates `secret_key`. CI clones fresh and
  passes. Not caused by either PR. Do not "fix" it as part of this work.

### The governing design

`~/.gstack/projects/dannyvfilms-Floppy/ryan-fix-boosted-nav-entrance-guard-self-match-design-20260813-152535.md`
(status APPROVED). Workstreams: W0 spike, W1 trustworthy OpenAPI, W2 JSON-LD,
W3 AsyncAPI, W4 handoff surfaces. #742 delivered W0 + W1 + focused W4.

Constraints that still bind and that QA should check against:

- Zero new **runtime** dependencies. Test-only deps must stay out of the image
  (`Dockerfile` runs `uv sync --no-default-groups`).
- Release-gating tests must live under `src/app/tests/`, because
  `.github/workflows/app-tests.yml` runs `test app users integrations lists
  events` and **omits the `api` label**. A gate under `src/api/tests/` does not
  protect PRs.
- Do not edit `.github/workflows/**` — CI fails PRs that touch it.
- Baseline Zero: ruff, lint and tests stay at zero failures.
- `/api/docs/` must make zero external network requests and must not trigger
  schema generation.

## What this branch (W2 — JSON-LD) adds

Two commits:

- `39a79d31` — generate the context from the vocabulary
- `1c6dc98c` — serve it and expose it to MCP

Changes:

| File | Change |
|---|---|
| `src/app/domain_vocabulary.py` | `render_jsonld_context()`, `class_name()`, `property_name()`, `CONTEXT_PATH`, namespace constants; `main()` now writes/checks both artifacts; relationship labels validated unique |
| `src/api/contracts/context.jsonld` | **new** generated artifact (JSON-LD 1.1) |
| `src/api/contract_views.py` | `jsonld_context` view — `application/ld+json`, byte-derived ETag, 1h public cache |
| `src/config/urls.py` | route `api/context.jsonld`, name `jsonld-context` |
| `mcp_server/floppy_mcp/client.py` | `fetch_public_contract()` — unauthenticated fetch for public contract paths outside `/api/v1/` |
| `mcp_server/floppy_mcp/server.py` | optional `floppy://domain-context` resource |
| `src/templates/users/about.html` | "Domain Context (JSON-LD)" link |
| `src/templates/api/docs.html` | domain-context entry on the offline index |
| `src/app/tests/test_api_contracts.py` | `JSONLDContextTests` — 8 gates |
| `src/users/tests/views/test_about.py` | expects the new link; still asserts AsyncAPI absent |
| `pyproject.toml` / `uv.lock` | `pyld==2.0.4` in the **test** group only |

Design decisions worth knowing before you judge the code:

- The context reads **only** `key`, `relationships`, `schema_org`. Definitions,
  aliases and bounded contexts stay prose. This is revised premise P2: one
  vocabulary, separately maintained contracts, no projection engine. A test
  asserts prose fields never appear in the artifact.
- Class terms are PascalCase from the key (`media_type` → `MediaType`);
  property terms are camelCase from the relationship label. Where a
  `schema_org` mapping exists the class expands to the schema.org IRI
  (`Item` → `https://schema.org/CreativeWork`); otherwise it stays in
  `https://github.com/dannyvfilms/Floppy/ns#`.
- The MCP resource is **optional by construction**. No tool reads it. A test
  asserts that when the context 404s, the resource returns a structured error
  *and* a normal `search_media` call still succeeds.

### Verification already done (do not redo)

- `app.tests.test_api_contracts` + `test_domain_vocabulary` + `users.tests.views.test_about`: **54/54 OK**
- `mcp_server/tests`: **58/58 passed**
- `ruff check src mcp_server/floppy_mcp mcp_server/tests`: **All checks passed**
- Drift-gate mutation proof: changing `floppy:consumption` → `floppy:MUTATED`
  in the committed context failed `test_committed_context_matches_the_vocabulary_renderer`
  and `test_pyld_expands_the_context_to_absolute_iris`; restoring made them green.
  **The gate is load-bearing.**
- PyLD expansion verified to produce absolute IRIs.

## What is NOT done — your work starts here

### 1. Full-suite confirmation

A full `SECRET=test-only scripts/test.sh` run was started on this branch but its
result is not recorded here. Re-run it and report. Expect ~3630 tests and the
one known environmental `test_data_paths` failure described above. Any *other*
failure is real.

### 2. Browser QA of the new surfaces

Not done at all for this branch. Needed:

- `/api/context.jsonld` — returns 200, `application/ld+json`, correct bytes,
  ETag revalidation gives 304, HEAD works. Unit tests cover this; confirm in a
  browser against a running instance.
- `/api/docs/` — the new "Domain context (JSON-LD)" entry renders, the link
  resolves, and the page still makes **zero external requests**. Check the
  network log explicitly.
- Settings → About — the new link renders with the right label and icon
  a11y attributes (`aria-hidden="true"`, `focusable="false"`), and the group
  still reads as one capability.
- Re-check 320px and 375px layouts, keyboard focus and skip link, dark mode,
  and reduced motion on `/api/docs/`, since a row was added.
- Confirm `/floppy` subpath rendering still produces correct URLs.

### 3. Package-size gate

The design requires recording artifact bytes and a before/after container image
comparison, failing at 1 MiB or 0.1% growth, whichever is smaller. The new
`context.jsonld` is small (~700 bytes) but the gate has not been run for this
branch. PyLD must **not** appear in the image — verify with a clean Podman/Docker
build that `uv sync --no-default-groups` excluded it.

### 4. Open the PR

Not opened yet. Base must be `codex/openapi-grounding-contracts`, not `latest`.

## W3 — AsyncAPI, parked

A drafted `channel_registry.py` is at `/tmp/claude-1000/w3-park/channel_registry.py`.
It is **not committed, not tested, and not reviewed** — treat it as a sketch.

Verified facts it encodes, which you can trust because they were traced in
source:

- Seven inbound message routes reaching six `WEBHOOK_PROCESSORS`:
  `webhook/plex/<token>`, `webhook/jellyfin/<token>`, `webhook/emby/<token>`,
  `webhook/jellyseerr/<token>`, `webhook/seerr/global/`, `webhook/kodi/<token>`,
  and `stremio-addon/<token>/subtitles/<type>/<id>.json` (a GET subtitles
  request used as a throttled playback-start signal — **not** a webhook).
- ListenBrainz has a separate inbound surface at
  `/apis/listenbrainz/1/submit-listens`, handled synchronously, not via
  `process_webhook`.
- Three Celery queues: `celery` (background, default priority 5), `interactive`
  (priority 0), `discover`. Priorities from `CELERY_TASK_ROUTES` in
  `src/config/settings.py:1331-1389`.
- `celery_queue_plan()` in `src/config/runtime_profile.py:372` has three
  branches but only **two are reachable**: `minimal` → one combined worker on
  `celery,interactive,discover`; `constrained` and `standard` → background
  worker on `celery,discover` plus an isolated `interactive` worker. The
  three-worker branch is dead code for the current tier set. **Do not document
  a three-worker split as real.**

Still required before W3 can ship, per the design:

- Pin the official AsyncAPI 3.0 JSON Schema as a test fixture **outside `src/`**
  and validate with the already-installed `jsonschema` (4.26.0). No `npx`, no
  runtime dependency, no workflow change. Fetching that schema needs the
  maintainer's go-ahead.
- Celery messages must declare `application/x-python-serialize` and must **not**
  claim a portable JSON payload schema; logical task arguments go in
  `x-floppy-*` metadata only.
- Exclude polling importers, Apprise destinations and base classes. A large or
  inaccurate AsyncAPI document is worse than none (design premise P7).
- Invert `assertNotContains(response, "AsyncAPI")` in
  `src/users/tests/views/test_about.py` only when the artifact actually ships.

## Standing decision you should not silently reverse

The grounding evaluation **failed** its preregistered gate: treatment medians
were Q1 `0`, Q2 `1`, Q3 `1` against a required `2`
(`docs/agents/evals/grounding_questions.md:502`). W2 and W3 were both recorded
`DEFER` on that evidence.

The maintainer has since explicitly chosen to build W2 and W3 anyway. That is a
deliberate scope override, not an oversight, and it is why this branch exists.
Record it honestly in any PR body: the formats ship because the maintainer asked
for them, **not** because the evaluation justified them. Do not restate the
failed evaluation as a success.

## Open review questions carried over from #742

These were raised and left open. They apply to the stack, not just #742.

1. `src/api/contract_views.py` reads contracts at **module import**, so a
   missing artifact fails app startup rather than returning the 404 the design's
   failure-mode table promised. This branch follows the same pattern for
   `context.jsonld`, which doubles the blast radius. Worth a decision.
2. `src/api/schema_contract.py:786-811` depends on drf-spectacular **private
   API** (`GENERATOR_STATS._error_cache`, `._warn_cache`, `patched_settings`).
   Pinned at `drf-spectacular==0.29.0`, so it will not break silently, but the
   next upgrade can break the gate. The risk is not commented anywhere.
3. `mcp_server/floppy_mcp/server.py` treats a lookup HTTP 500 as "absent" when
   `source == "manual"` and proceeds to write. Deliberate and tested
   (`mcp_server/tests/test_tools.py:127`, commit `27cc61c4`), but the adjacent
   comment explains only the 404 case. Documentation gap.
