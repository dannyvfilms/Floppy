# Upstream ports and divergence ledger

> **Status:** Initial baseline accepted
> **Parent issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)
> **Floppy review baseline:** `latest` at `3cefbadfd7a9c092918ce6cb2f728b804cc193bb`
> **Yamtrack review baseline:** `dev` at `85646a36298d61d39544f80eacf541c232c4df7b` (`0.26.1`)
> **Common ancestor:** `88c92c9cfb5b41f807a8e9b82c4dd77f3d7723c4`
> **Reviewed range:** 138 Yamtrack-only commits and 1,703 Floppy-only commits
> **Last upstream review:** 2026-08-11
> **Next comparison:** `85646a36298d61d39544f80eacf541c232c4df7b..upstream/dev`

## Contract

Floppy is a substantial fork, not a lightly modified Yamtrack branch. Git-history convergence would combine incompatible models, migrations, providers, integrations, templates, Docker, CI, and product behaviour.

> Floppy is current with upstream when every reviewed upstream outcome has one recorded decision, concrete evidence, an owner or reconsideration trigger, and a validation path.

The unit of review is an outcome. Related implementation, test, migration-repair, generated, and follow-up commits stay together. A mixed commit is one ledger group with its component outcomes explicitly split.

This programme does not merge or rebase Yamtrack into Floppy, copy upstream migrations into Floppy's migration graph, or trade Floppy capabilities for artificial Git similarity. Issue [#10](https://github.com/dannyvfilms/Floppy/issues/10) remains historical schema-reversibility context; this ledger governs semantic compatibility.

## Decisions

| Decision | Meaning | Required evidence |
|---|---|---|
| **Pending** | Accepted gap, not yet implemented. | Upstream evidence, Floppy gap, priority, and active owner issue. |
| **Ported** | Equivalent behaviour is merged with no material product difference. | Floppy commit/PR plus code or regression-test evidence. |
| **Adapted** | The upstream outcome is merged in Floppy's architecture or with intentional differences. | Floppy commit/PR, code/test evidence, and the difference. |
| **Superseded** | Floppy already provides an equal or stronger result. | Specific Floppy code, test, issue, or commit. |
| **Deferred** | Potentially useful, but not accepted into the current delivery sequence. | A named owner and concrete trigger for reconsideration. |
| **Discarded** | Intentionally not applicable. | A discard code and evidence-backed reason. |

Every canonical upstream commit appears exactly once in the master ledger. “Partially ported” is not a terminal decision; split rows name the decision for each component.

## Discard codes

| Code | Reason |
|---|---|
| **D1** | A wholesale port would regress a stronger Floppy capability. Record the user-facing outcome as Superseded where possible. |
| **D2** | Merge history, generated output, release metadata, or maintenance with no independent product outcome. |
| **D3** | Yamtrack-specific product, platform, repository, or tooling choice. |
| **D4** | Historical or unsafe migration implementation. Port final semantics and create a Floppy-native migration. |
| **D5** | Dependency changes must be re-resolved and tested under Floppy's lockfile, not cherry-picked as bot commits. |
| **D6** | Architecture or path is incompatible with Floppy's current bounded contexts. Port behaviour and tests manually. |
| **D7** | Deliberate Floppy product divergence, with the competing behaviour and owner named. |
| **D8** | Independently implemented in Floppy. Preserve both histories as attribution. |

## Portfolio order

RICE informed the first review using `(reach × impact × confidence) / effort`, with relative 1–10 reach, 0.5–3 impact, and engineer-weeks of effort. Priority is deliberately not a raw score: release safety and data integrity precede smaller UX wins.

| Package | Owner | Priority | Exit condition |
|---|---|---|---|
| Phase 0 — decision contract | [#645](https://github.com/dannyvfilms/Floppy/issues/645), PR [#651](https://github.com/dannyvfilms/Floppy/pull/651) | P0 | This ledger and governance policy are merged; #646–#650 are sub-issues of #645; relevant issue/PR labels are applied; #638 is closed as superseded with a ledger link; #645 remains open for the full programme. |
| Phase 1 — built-image smoke gate | [#646](https://github.com/dannyvfilms/Floppy/issues/646) | P0 | The publishable image starts, becomes healthy, serves core surfaces, validates MCP, and restarts on persistent data. |
| Phase 2 — uv and reproducible build | [#647](https://github.com/dannyvfilms/Floppy/issues/647) | P0 | One locked app/MCP dependency graph drives CI and Docker, the unsuppressed audit blocker in [#670](https://github.com/dannyvfilms/Floppy/issues/670) is resolved independently, and the matching Wiki update in [#669](https://github.com/dannyvfilms/Floppy/issues/669) is published. |
| Phase 3 — datetime/calendar integrity | [#648](https://github.com/dannyvfilms/Floppy/issues/648) | P0 | Final UTC-safe semantics, audit, Floppy migrations, and SQLite/PostgreSQL upgrade validation. |
| Phase 4 — provider correctness | [#649](https://github.com/dannyvfilms/Floppy/issues/649) | P1 | Offline fixtures prove paging, unknown-count, and request-identity behaviour. |
| Phase 5 — identity constraints | [#650](https://github.com/dannyvfilms/Floppy/issues/650) | P1 | Invalid episode identity is audited and repaired before a non-null constraint. |
| Phase 6 — product polish | [#645](https://github.com/dannyvfilms/Floppy/issues/645) | P2/P3 | Deferred outcomes receive focused issues only after safety and integrity baselines are stable. |

The narrow first-run query-budget repair in PR [#653](https://github.com/dannyvfilms/Floppy/pull/653) is an explicit Phase 0 exception recorded on #645. It restores the existing test signal; it does not implement an upstream runtime outcome.

## Master outcome ledger

The **Canonical upstream SHA(s)** column is the machine-audited inventory for `88c92c9..85646a36`.

| # | Canonical upstream SHA(s) | Outcome | Decision | Floppy evidence, owner, and trigger | Package |
|---:|---|---|---|---|---|
| 1 | `0c5a104d` | TV/season completion excludes unreleased episodes | **Pending** | `src/app/models/tv.py` has completion logic but no future-release regression; [#648](https://github.com/dannyvfilms/Floppy/issues/648) owns final semantics. | P0 / Phase 3 |
| 2 | `f2ae691d` `f4b4c275` `1f48680b` | Persistent messages for automatic TV/season changes | **Deferred** | No persistent-message model/retention contract. #645 reconsiders after #648 automation is stable and privacy/retention are specified. | P3 / Phase 6 |
| 3 | `3eb0472a` | Anime webhook match through TVDB episode IDs | **Adapted** | `src/integrations/webhooks/base.py` and `src/integrations/tests/test_webhooks_jellyfin.py`; Floppy commit `d5503a53` resolves episode IDs within its broader provider-link model. | Done |
| 4 | `2fda336b` | AniBridge anime webhook mappings | **Adapted** | `src/integrations/webhooks/anime_mappings.py`, `src/integrations/tests/test_anime_mappings.py`, commit `687ad572`; Floppy uses AniBridge v3 and episode ranges. | Done |
| 5 | `de13d59d` `2ab4139e` `2b6f9b6d` `5f31e483` `55cff962` `2e6bb4b6` | Planning/upcoming home rows, presentation, and hide controls | **Superseded** | `src/users/home_screen.py`, `src/users/tests/views/test_home_screen.py`, commit `98c5b72d`; Floppy has a three-mode planned display and richer row pipeline. | Done |
| 6 | `17492329` | Upstream integration-test locator repair | **Discarded (D2/D3)** | The locator repairs Yamtrack's replaced UI test surface and has no independent Floppy behaviour. | — |
| 7 | `bddcc3eb` `bec01e94` | Safari status-date validation and clearing | **Superseded** | `src/app/forms.py`, `src/static/js/mediaStatusDateHandler.js`, `src/app/tests/test_forms.py`, commit `a4134b55`; dates are optional and clear-state is explicit. | Done |
| 8 | `5c58d614` `71e291f9` `b500eca4` `45e116ac` | April dependency updates | **Deferred (D5)** | [#647](https://github.com/dannyvfilms/Floppy/issues/647) re-resolves each risk group after lockfile parity; no bot SHA is cherry-picked. | P1 / Phase 2 |
| 9 | `4ec98e53` | fakeredis compatibility with requests-ratelimiter | **Ported** | `pyproject.toml`, `src/app/providers/services.py`, commit `711b056e`; fake and real Redis expose compatible connection pools. | Done |
| 10 | `29f948b2` | Gunicorn tests on Windows | **Discarded (D3)** | Floppy's documented source/container gates do not promise native Windows Gunicorn operation; reconsider only if Windows becomes a supported runtime target. | — |
| 11 | `82a1f301` | Detect and repair falsely reopened completed shows | **Pending** | [#650](https://github.com/dannyvfilms/Floppy/issues/650) owns a data-characteristic audit; Yamtrack's release-window migration is rejected under D4. | P1 / Phase 5 |
| 12 | `69b904c3` `fb96b270` | Steam overwrite | **Ported / Deferred** | Core in-place update is in `src/integrations/imports/steam.py`, tests, and commit `a4a399ae`. #645 reconsiders history-aware bulk updates and accurate updated counts after Phase 5 importer audits. | Done / P2 Phase 6 |
| 13 | `4e842803` | Publish a separate API image | **Discarded (D3/D6)** | Floppy ships the API and MCP in its main image; a Yamtrack feature-branch image channel would split the supported runtime. | — |
| 14 | `30c26d87` `6114a181` `0b06b2f2` `06108561` | Upstream merge commits | **Discarded (D2)** | Merge ancestry has no independent outcome. | — |
| 15 | `d419e4b1` `c5078d3b` `4614504e` | Obfuscate unseen episode images and titles | **Adapted** | `src/templates/app/components/episode_row.html`, `src/users/models.py`, commit `55fafca9`; Floppy also provides an inline toggle. | Done |
| 16 | `8ad8ce49` | Configurable session age | **Adapted** | `src/config/settings.py`, `src/users/models.py`, `src/app/tests/test_middleware.py`, commit `5da0847c`; Floppy adds a user preference over the environment default. | Done |
| 17 | `f812a046` | Uppercase all metadata titles | **Deferred** | #645 owns the product decision; reconsider only with an approved typography contract and screenshot review across detail/search/list surfaces. | P3 / Phase 6 |
| 18 | `c26ef0b7` | Episode-watch dropdown shortcuts | **Superseded / Deferred** | Current/air-date/clear outcomes are covered by `src/templates/app/components/fill_track_episode*.html` and commit `8356d4cc`. #645 reconsiders a runtime-offset dropdown after #648 defines time semantics. | Done / P3 Phase 6 |
| 19 | `81afac88` `8cb000d7` `c1e32d71` | Expanded date/statistics formats | **Adapted** | `src/users/models.py`, `src/app/statistics_aggregator.py`, preference/statistics tests, commits `fe4de371` and `070cfc8e`; Floppy also supports time formats. | Done |
| 20 | `c17b5791` `a62f8997` | Yamtrack worktree/editor setup | **Discarded (D3)** | Contributor-local tooling is not a semantic upstream outcome. | — |
| 21 | `3d01a885` | Configured public origin for OAuth/webhook URLs | **Adapted** | `src/app/helpers.py`, `src/app/templatetags/app_tags.py`, and `src/integrations/views.py` prefer configured origins and fall back to the request; commit `711b056e`. | Done |
| 22 | `fe51e8fb` `b1b233b7` | Public media lists and private-profile UI | **Superseded** | `src/lists/models.py`, `src/lists/views_list_browse.py`, and `src/lists/tests/test_views.py`; Floppy has list visibility, slugs, public profiles, RSS/JSON, smart lists, and recommendations. | Done |
| 23 | `724a66df` `02b5a797` | Validate public-list filters and ownership | **Superseded** | `src/lists/views.py`, owner-scoped list managers, and `src/lists/tests/test_views.py` cover owner-derived public filtering and mutation ownership. | Done |
| 24 | `78aee8e8` `01063df4` `6505c734` `3105332c` `a158d5b1` `b67eb6fe` `105eda65` `2fdd7077` `5e48f0d3` `0f4330e2` `72a2a186` `ecd86524` `e1b6f189` `96db5489` | Yamtrack documentation stack, theme, deploy, and development docs | **Discarded (D3)** | Floppy maintains README/wiki/agent docs and its own test command; Zensical/versioned-doc deployment needs an independent docs-platform decision. | — |
| 25 | `32ec33d3` `00a2467d` | Hardcover default endpoint and token validation | **Adapted** | `src/app/providers/hardcover.py`, provider tests, and commit `b64669f9`; Floppy uses its own credential guidance and validation flow. | Done |
| 26 | `669a0699` `871815a7` | Hardcover query cap without splitting words | **Ported** | `src/app/providers/hardcover.py`, `src/app/tests/providers/test_hardcover_search_regressions.py`, commits `1135a9a3` and `104fd53a`. | Done |
| 27 | `3d952d92` | Goodreads provider errors become import warnings | **Ported** | `src/integrations/imports/goodreads.py`, `src/integrations/tests/imports/test_goodreads.py`, commit `c4b82d16`. | Done |
| 28 | `894337fe` | Refresh a missing item image on details | **Ported** | `src/app/helpers.py`, `src/app/views.py`, `src/app/tests/views/test_media_details.py`, and commit `acad4b3a`; broader metadata backfill remains separate. | Done |
| 29 | `a055a8a5` | Auto-login option | **Adapted** | `src/config/settings.py`, `src/app/middleware.py`, `src/app/tests/test_middleware.py`, commit `5da0847c`; Floppy uses `FLOPPY_AUTO_LOGIN_USERNAME` with legacy fallback. | Done |
| 30 | `1b402440` | Configurable week start | **Ported** | `src/users/models.py`, `src/app/stats_activity.py`, preference/statistics tests, commit `79e48cd3`. | Done |
| 31 | `e6765fa6` `36a3d0d8` `0774d483` `298042ae` `c32a39cc` | uv project/lockfile, pre-commit, and Docker baseline | **Pending** | PRs [#663](https://github.com/dannyvfilms/Floppy/pull/663) and [#665](https://github.com/dannyvfilms/Floppy/pull/665) prepare the shared app/MCP lock and locked CI; [#660](https://github.com/dannyvfilms/Floppy/issues/660) owns the Docker, tooling, and repository-documentation cutover without dependency upgrades, followed by the separately authorized Wiki publication in [#669](https://github.com/dannyvfilms/Floppy/issues/669). The new fail-closed audit detects three unsuppressed `aiohttp==3.14.1` advisories (`PYSEC-2026-3545`, `PYSEC-2026-3546`, `PYSEC-2026-3547`); [#670](https://github.com/dannyvfilms/Floppy/issues/670) owns that independent blocker. `mcp_server` retains its upstream-compatible `setuptools>=68` isolated build-backend range as the sole non-runtime lock exception. | P0 / Phase 2 |
| 32 | `40d21a2c` `03005197` `be956ce9` | Ongoing-season progress semantics | **Discarded (D7)** | `src/app/models/tv.py`, `src/app/tests/models/test_season.py`, commit `e8549215`, and issue #327 deliberately use furthest-episode plus rewatch-safe semantics. | — |
| 33 | `088404ef` `3290c5e4` | Jellyfin MarkPlayed/MarkUnplayed events and preference copy | **Adapted** | `src/integrations/webhooks/jellyfin.py`, `src/integrations/tests/test_webhooks_jellyfin.py`, commit `3c57029d`, issue #409. | Done |
| 34 | `bd0b4f5b` | Require `Episode.item` | **Pending** | [#650](https://github.com/dannyvfilms/Floppy/issues/650) must audit, reconstruct, export/quarantine ambiguity, then add a Floppy-native constraint. | P1 / Phase 5 |
| 35 | `d6cbd46c` | Integration settings tabs | **Deferred** | #645 reconsiders when the integrations page receives an approved information-architecture pass; no reliability outcome depends on it. | P3 / Phase 6 |
| 36 | `41b080b8` | Clarify Redis URL when Docker service names collide | **Superseded** | `README.md` direct-container instructions name `floppy-redis` and set `redis://floppy-redis:6379`; Compose uses its scoped `redis` service. | Done |
| 37 | `881cc198` `0ec6aefa` `e51eedfa` `f6b2eb37` | Yamtrack stale/pending-answer automation | **Discarded (D3)** | Repository triage policy is not runtime parity; adopt only through a separate governance decision. | — |
| 38 | `69454ff6` | AniList nested airing-schedule pages and unknown episode totals | **Pending** | `src/events/calendar/anime.py` paginates the outer media page only and skips unknown totals; `src/events/tests/calendar/test_anime.py` lacks nested-page and unknown-total regressions. [#649](https://github.com/dannyvfilms/Floppy/issues/649) owns the fixtures and port. | P1 / Phase 4 |
| 39 | `1c449bf5` | Provider network errors without response objects | **Adapted** | `src/app/providers/services.py`, `src/app/tests/providers/test_services.py`, commit `e6d7d502`; Floppy also has bounded retry/rate-limit fallback. | Done |
| 40 | `156c6f6f` | Abbreviated Open Library publication dates | **Superseded** | `src/app/providers/openlibrary.py` and `src/app/tests/providers/test_metadata.py` cover full, month/year, year-only, prefixed, and malformed values. | Done |
| 41 | `2348f0c1` `c7872dda` `f8763f53` | Split webhook processing and TV IMDb/TVDB/TMDB fallbacks | **Adapted** | `src/integrations/webhooks/base.py` and webhook tests implement provider-link resolution; commit `d5503a53`, issue #420. | Done |
| 42 | `c23f0e6c` | Require TV→season→episode CSV row order | **Superseded** | `src/integrations/imports/helpers.py::_ordered_media_types` enforces dependency order after parsing, so Floppy imports do not depend on CSV row order. | Done |
| 43 | `ee036367` `868d6dde` `4ee294a0` `cd1cd613` `f78dc270` `cf2a36a4` `a7569e1c` `5593d28e` `8b344829` `b89ae6fc` `f2c0c5fc` `69bae87d` `8b8054ba` `f5c4e59a` | Later dependency, Actions, and interpreter updates | **Deferred (D5)** | #647 re-resolves by risk group only after uv parity; Python remains 3.12 during package-manager conversion. | P1 / Phase 2 |
| 44 | `dc7271e2` | Open Library User-Agent | **Pending** | `src/app/providers/openlibrary.py` has no project identity on all sync/async requests; [#649](https://github.com/dannyvfilms/Floppy/issues/649) owns a Floppy-specific header and tests. | P1 / Phase 4 |
| 45 | `2f577bd8` `c8dcc838` `85646a36` | Yamtrack release-version metadata | **Discarded (D2/D3)** | Floppy versions and publishes independently. | — |
| 46 | `32f47fed` | Time-to-beat on game details | **Superseded** | `src/app/services/game_lengths.py`, `src/app/tests/test_game_lengths.py`, columns/templates, commit `6cb0f508`; Floppy also sorts and filters by it. | Done |
| 47 | `8aaea2d7` | MyAnimeList search offset pagination | **Pending** | `src/app/providers/mal.py` omits page offset; [#649](https://github.com/dannyvfilms/Floppy/issues/649) owns the regression fixture and fix. | P1 / Phase 4 |
| 48 | `1c48c27c` | Deduplicate repeated/multi-season top-rated statistics | **Superseded** | `src/app/statistics_aggregator.py`, statistics tests, commits `5f15e27e`, `137a1cf4`, and `c73e6445`. | Done |
| 49 | `6d68cfc7` | Quote Codecov threshold value | **Pending** | `.github/codecov.yml` still uses numeric `5.0`; [#647](https://github.com/dannyvfilms/Floppy/issues/647) owns the isolated tooling validation. | P1 / Phase 2 |
| 50 | `60a40362` | Normalize Trakt/SIMKL editable dates to UTC minutes | **Superseded** | `src/app/forms.py` uses second-capable `datetime-local` inputs (`step="1"`), while `src/integrations/imports/trakt.py` and `simkl.py` preserve timezone-aware API timestamps. Floppy intentionally keeps editable second precision, so truncation would regress fidelity. | Done |
| 51 | `7bb3a6fb` | Exclude undated episodes from released progress | **Pending** | `src/events/calendar/tv.py` produces unknown episode dates while `src/events/calendar/selectors.py` still interprets year-1/year-9999 sentinels. [#648](https://github.com/dannyvfilms/Floppy/issues/648) owns one explicit unknown/unreleased contract and dashboard regression. | P0 / Phase 3 |
| 52 | `6a240cc2` | Media-details section-tab redesign | **Deferred** | #645 reconsiders only through an approved detail-page design pass; current Floppy details expose additional media/integration surfaces. | P3 / Phase 6 |
| 53 | `3494dee9` | Imported episode activity uses watch/end date | **Pending** | Implemented for review in `src/integrations/imports/yamtrack.py` with a regression in `src/integrations/tests/imports/test_yamtrack.py`: `progressed_at → end_date → import time`, preserving timezone-aware parsing and `progressed_at` precedence. [#648](https://github.com/dannyvfilms/Floppy/issues/648) remains the owner until merge. | P0 / Phase 3 |
| 54 | `4cb1ea02` | Global change journal | **Deferred** | Playback History is not equivalent. #645 reconsiders after a product decision on scope, retention, pagination, and privacy. | P3 / Phase 6 |
| 55 | `157765e4` | Replace statistics timeline with two badges | **Discarded (D1/D7)** | `src/app/statistics_views.py`, `src/templates/app/statistics.html`, and `src/app/tests/views/test_statistics.py` prove Floppy's richer timeline, comparison, hours, and badge surfaces; badge ideas may be proposed independently without removing them. | — |
| 56 | `95800c91` | SQLite concurrent-write settings | **Superseded** | `src/config/settings.py`, `src/app/db_retry.py`, `src/app/tests/test_sqlite_settings.py`, commits `0684be9b`, `fc8c3b15`, and `0d3c088a`; Floppy adds lock/corruption handling. | Done |
| 57 | `7a5edac0` `e67dbb9d` `7cce302f` `3ee9ad8a` `83cdea8c` `83d7315f` | Local-time modal prefill, in-place HTMX edit, and no-date episode option | **Superseded** | `src/templates/app/components/fill_track_episode*.html`, date picker JS, track-modal tests, commits `a9bd662e`, `9f05f8d5`, and `8356d4cc`. | Done |
| 58 | `66cbf007` | Skip unsupported Goodreads shelves and map DNF | **Deferred** | #645 opens a scoped importer issue after P0/P1 packages; trigger is Phase 6 scheduling or a new user report. | P2 / Phase 6 |
| 59 | `4082a5f7` | Goodreads decimal ratings | **Superseded (D8)** | `src/integrations/imports/goodreads.py`, its tests, Floppy issue #379, and commits `1a56080e`/`652704a8`. | Done |
| 60 | `2af59c29` | Search media notes | **Deferred** | #645 creates a focused issue when Phase 6 starts; preserve existing title/media-ID matching and add `notes` with a query test. | P2 / Phase 6 |
| 61 | `6cb84976` | Apply upstream template linter output | **Discarded (D2)** | Mechanical output has no standalone behaviour; lint Floppy sources under its own configuration. | — |
| 62 | `9063ad43` | Season poster fallback and existing-row backfill | **Superseded / Deferred** | Common creation paths already fall back in `src/app/models/tv.py`. #645 reconsiders manual-provider gaps and a one-time placeholder audit in Phase 6. | Done / P2 Phase 6 |
| 63 | `8ac59d33` `1b9568b4` | Generated Tailwind sync and lint ignore | **Discarded (D2/D3)** | Regenerate from Floppy sources only when its input changes; do not import upstream generated CSS/config. | — |
| 64 | `368fc461` | Built-image smoke gate and standalone Ruff workflow | **Pending / Pending** | PR [#656](https://github.com/dannyvfilms/Floppy/pull/656) prepares image startup/MCP/restart checks; PR [#665](https://github.com/dannyvfilms/Floppy/pull/665) prepares locked standalone Ruff execution. Both remain Pending until merge and recorded validation. | P0 / Phases 1–2 |
| 65 | `a69e828e` | Yamtrack Pylint argument-limit configuration | **Discarded (D3)** | Floppy's lint contract is Ruff/djlint/pre-commit; importing Yamtrack's Pylint tuning would create an unused policy. | — |
| 66 | `28685442` | Align Docker builder/runtime Python versions | **Pending** | [#660](https://github.com/dannyvfilms/Floppy/issues/660) owns identical Python 3.12/Alpine 3.21 builder and runtime bases and validates them through #646. | P0 / Phase 2 |
| 67 | `791d800c` | Overflow-safe unknown-date sentinels | **Pending** | [#648](https://github.com/dannyvfilms/Floppy/issues/648) owns safe helpers and extreme-offset tests. | P0 / Phase 3 |
| 68 | `e2ed720d` | Repair timezone shift/SQLite overflow in date truncation | **Discarded (D4)** | Floppy never landed Yamtrack's faulty truncation migration, so there is no Floppy-created timezone shift or overflow to repair. Current importers preserve precision and current forms edit it safely. | — |

## Review and delivery rules

1. Update this ledger before opening implementation for a newly reviewed upstream batch.
2. Preserve the `upstream` branch as an exact mirror; never merge or rebase it into `latest`.
3. Port tests aggressively, but reimplement models and migrations against Floppy's current bounded contexts and migration graph.
4. Do not combine uv conversion with dependency upgrades, and do not treat dependency-bot SHAs as port units.
5. Never silently delete user data. Audit, deterministically repair, export, or quarantine before enforcing constraints.
6. Keep closed historical issues closed; use them as evidence without changing their status.
7. Preserve upstream issue/PR/commit/author attribution and explain intentional differences in adapted PRs.
8. Require a failing Floppy regression test for a gap, or concrete repository evidence for supersession.
9. Record the new upstream baseline only after every commit in the incremental range has a decision.
10. Automation may group commits and draft evidence; it must not choose terminal decisions, merge, migrate data, publish, or close user issues.

Every upstream-derived PR must identify the ledger outcome, upstream provenance, port/adaptation method, intentional differences, regression tests, database/migration effect, and relevant performance evidence. Docker changes must pass #646; data migrations must run on representative SQLite and PostgreSQL upgrades.

## Maintaining this ledger

For each incremental review:

1. Fetch Yamtrack `dev` without editing the mirror branch.
2. Compare the stored baseline with `upstream/dev`.
3. Group commits into coherent outcomes and verify issue/PR/code history in both repositories.
4. Add each new canonical SHA exactly once, with a decision and evidence or owner/trigger.
5. Create or link scoped issues only for accepted Pending work.
6. Update the stored baseline after the range has zero unclassified commits.

The parent issue [#645](https://github.com/dannyvfilms/Floppy/issues/645) is the authoritative operational programme index and remains open for the full programme. Issue status, labels, and relationships are operational; this file is the durable decision record.
