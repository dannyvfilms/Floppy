# Contributing to Floppy

Floppy is a self-hosted media tracking platform forked from [FuzzyGrim/Yamtrack](https://github.com/FuzzyGrim/Yamtrack). We welcome contributions from developers and AI-assisted workflows alike.

Our bar is practical: **make changes clean, minimal, safe, and well-understood.** This guide provides clear instructions to help contributors build, test, and ship high-leverage pull requests that land quickly.

---

## Quick Reference

| Area | Requirement | Command / Reference |
|---|---|---|
| **Branch Target** | Always target `latest` (never `upstream` or `release`) | `git checkout -b feat/my-feature latest` |
| **PR Template** | Use every section; write in plain language first | [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) |
| **Python Tooling** | Python 3.12 + `uv` | `uv sync --locked` |
| **Tailwind CSS** | Pinned repo CLI output to `src/static/css/main.css` | `npx @tailwindcss/cli -i ./src/static/css/input.css -o ./src/static/css/main.css` |
| **Fast Tests** | Targeted test runner | `SECRET=test-only scripts/test.sh <dotted.path>` |
| **Faster Tests** | Skip the 141s migration replay while iterating (not for migration changes) | `FLOPPY_TEST_FAST_DB=1 SECRET=test-only scripts/test.sh <dotted.path>` |
| **Lint / Style** | Ruff (line length 88, migrations excluded) | `uv run --no-sync ruff check src` |

## Local development

Running Floppy from source for development:

```bash
git clone https://github.com/dannyvfilms/Floppy.git
cd Floppy
docker run -d --name redis -p 127.0.0.1:6379:6379 --restart unless-stopped redis:8-alpine
uv sync --locked
```

Django/manage.py commands require `SECRET`. Create a `.env` with at least `SECRET`, `DEBUG=True`, and whichever metadata API keys you need (names are listed in [Environment variables](docs/deployment.md#environment-variables)), then:

```bash
uv run --no-sync python src/manage.py migrate
uv run --no-sync python src/manage.py createsuperuser
uv run --no-sync python src/manage.py runserver
```

Celery and Tailwind run in separate terminals:

```bash
PYTHONPATH=src uv run --no-sync celery -A config worker --queues interactive --hostname celery-interactive@%h --loglevel DEBUG
PYTHONPATH=src uv run --no-sync celery -A config worker --queues celery --beat --scheduler django --hostname celery@%h --loglevel DEBUG
```

```bash
npx @tailwindcss/cli -i ./src/static/css/input.css -o ./src/static/css/main.css --watch
```

Visit `http://localhost:8000`. For a shared demo login, set `DEMO_ACCOUNT_ENABLED=True` before the first start; provisioning is otherwise off by default.

`pyproject.toml` and `uv.lock` are the dependency source of truth for the app
and bundled MCP workspace. Use uv 0.12.3 and keep the lockfile in sync; the
removed requirements files are not maintained in parallel. The MCP package's
`setuptools>=68` isolated build-backend range is the only build-time resolver
exception to the runtime lock and is intentionally not pinned as an application
dependency.

---

## 1. Core Engineering & Quality Standards

Every contribution should maintain and elevate our codebase baseline.

### Single Source of Truth & Zero Duplication
- **Eliminate duplicate logic**: Keep a single source of truth for every business rule, model query, and view helper.
- **Reuse existing components**: Before adding a new helper, filter, or UI element, inspect the codebase. Reuse established templates, model methods, and provider adapters rather than copy-pasting similar blocks across apps.
- **Reference**: For foundational principles, see [Don't Repeat Yourself (DRY)](https://en.wikipedia.org/wiki/Don%27t_repeat_yourself).

### Explicit Domain Boundaries & Consistent Vocabulary
- **Separation by bounded context**: Floppy organizes code into distinct domain areas:
  - `app`: Core media entities, metadata providers, and detail views.
  - `users`: User authentication, account management, and profile preferences.
  - `lists`: Collections, custom watchlists, and smart filters.
  - `integrations`: Third-party synchronization, webhooks, and background sync adapters.
  - `events`: Activity history and release calendar schedules.
- **Ubiquitous language**: Use consistent names across database models, API routes, template variables, and documentation. Consult the [Domain Vocabulary Guide](docs/agents/domain_model.md).
- **Domain logic placement**: Keep business rules and state transitions inside models and dedicated domain services, not scattered across view controllers or template filters.

### Security by Design & Vulnerability Avoidance
Security is critical. Every change touching authentication, user data, or network integrations must prevent common security risks (including the OWASP Top 10):
- **Injection Safety**: Use Django ORM parameterized queries. Never construct raw SQL queries with string formatting or pass unsanitized input to shell commands.
- **Access Control & Tenancy (IDOR Prevention)**: Always scope database queries to the authenticated user (`MediaItem.objects.filter(user=request.user, ...)`). Never assume an identifier in a URL or request body belongs to the active session.
- **Credential Storage & Secrets**: Never commit private tokens, passwords, or API keys. Use environment variables or the existing Fernet credential helpers (`encrypt` / `decrypt` in `integrations/imports/helpers.py`). Their key derives from the instance signing key; not all stored credentials are encrypted. Preserve that key with database backups.
- **Server-Side Request Forgery (SSRF)**: Validate and restrict URLs when fetching third-party provider metadata or processing webhook destinations.
- **XSS & CSRF Prevention**: Rely on Django template auto-escaping. Never mark user-supplied data as `|safe`. Include `{% csrf_token %}` on all state-modifying POST/PUT forms.

### Human-Centered UI/UX & Cognitive Accessibility
User interfaces in Floppy should be intuitive, accessible, and fatigue-free:
- **Gestalt Principles**: Group related elements logically using consistent proximity, visual similarity, and clear alignment.
- **Nielsen Usability Heuristics**:
  - Keep system status visible (loading states, success banners, clear progress feedback).
  - Prevent errors before they happen with safe input validation and destructive action confirmations.
  - Prioritize recognition over recall with clear labels and intuitive navigation.
- **Accessibility (a11y)**: Write semantic HTML5, provide explicit form labels, maintain WCAG AA color contrast, and verify keyboard navigation and touch target sizes.
- **Cognitive & ADHD/AuDHD Ergonomics**: Structure pages with clear visual hierarchy, scannable headings, and concise copy. Avoid dense walls of text, unnecessary modal interruptions, or visual clutter.

### Simplified Technical English (ASD-STE100)
- Write documentation, commit descriptions, and PR explanations in clear, direct English.
- Use short sentences, active verbs, and specific nouns.
- State instructions directly: say what the system does, why it does it, and what actions are required.

---

## 2. Modern Workflows, Tooling & Learnings

Modern development workflows accelerate review cycles and guard against complexity. We encourage contributors to use specialized workflows:

| Tool / Workflow | Role in Development | Resource |
|---|---|---|
| **gstack** | Fast headless browser QA, visual regression checks, design audits, and pre-landing PR inspection | [gstack.lol](https://gstack.lol/) / [garrytan/gstack](https://github.com/garrytan/gstack) |
| **Ponytail** | Complexity auditor and anti-bloat discipline — removes unnecessary abstractions, deletes unused helpers, and keeps changes lean | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail/pulls?page=4&q=is%3Apr+is%3Aopen) / [GitHub](https://github.com/DietrichGebert/ponytail) |
| **OpenSpec** | Spec-driven requirement refinement and intent verification before writing code | [openspec.dev](https://openspec.dev/) |

### Workflow Execution Rule
- **Review to Implementation**: Once requirements are refined and review gates (design, architecture, and security) are verified, proceed directly to implementation without pausing for redundant review loops.

### Compound Knowledge & Learnings
When you discover a non-obvious database nuance, integration quirk, or operational edge case, record it inline in code comments or update project documentation. Shared knowledge makes the repository and future contributors faster over time.

---

## 3. Living Documentation & API Contract Hygiene

Documentation in Floppy is a **first-class product surface**, not an afterthought. When changing functionality, actively consider and update all affected documentation surfaces in the same PR.

### OpenAPI Specification & API Contracts
Floppy maintains an OpenAPI schema contract verified by automated test suites.
- When you add, modify, or deprecate API endpoints or serializers, regenerate and validate the OpenAPI schema:
  ```bash
  SECRET=test-only uv run --no-sync python src/manage.py spectacular --custom-settings api.schema_contract.STATIC_SPECTACULAR_SETTINGS --fail-on-warn --validate --file src/api/contracts/openapi.yaml
  ```
- Run the contract tests:
  ```bash
  SECRET=test-only scripts/test.sh users.tests.views.test_about app.tests.test_api_contracts app.tests.test_domain_vocabulary
  ```

### Domain Vocabulary & Developer Documentation
- **Domain vocabulary guide**: When introducing or altering core entity concepts, update and verify the guide:
  ```bash
  PYTHONPATH=src uv run --no-sync python -m app.domain_vocabulary
  PYTHONPATH=src uv run --no-sync python -m app.domain_vocabulary --check
  ```
- **Architecture & Agent Docs**: Consult and update specialized playbooks under `docs/architecture/` and `docs/agents/` (e.g., `media_type_integration.md`, `music_integration.md`, `pocketcasts_workflow.md`).
- **Wiki**: User-facing documentation lives in `wiki/`. When updating features that alter user workflows, propose matching wiki updates.

> [!IMPORTANT]
> **Active Consideration of Stale Surfaces**: If your code change invalidates existing documentation, configuration examples, or API payloads, updating those surfaces is part of your Definition of Done.

---

## 4. Pull Request Requirements & AI Assistance

### Mandatory PR Template
Every pull request **must use [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)**. Keep its sections so reviewers can quickly find the summary, explanation, checks, and follow-ups.

The template requires:
1. **Summary & Linked Issues**: Start with a plain-language explanation of what changed and why. Put technical details after that when useful. Always link related issues in relationship fields (`Fixes #123`, `Refs #456`).
2. **Bug Fix Explanation** *(post-mortem / root cause analysis)*: For bug fixes, explain what went wrong and how the fix prevents it from happening again.
3. **AI Assistance & Workflows**: If an AI coding agent or tool generated or shaped the code:
   - **Disclose the specific model**: Name the exact underlying model identifier (e.g., `claude-3-7-sonnet`, `gemini-2.5-pro`, `gpt-5.1-codex`).
   - **Disclose workflows used**: State tools and review workflows utilized (e.g., gstack QA, Ponytail review, OpenSpec, manual testing).
   > Note: A generic tool wrapper name alone ("Cursor", "Claude Code", "Copilot") is **insufficient**. You must state the underlying model.
4. **Checks Run**: List the exact commands, tests, screenshots, or manual checks completed and their outcomes.
5. **Screenshots**: Required for all UI, CSS, template, and visual layout changes (before/after for bug fixes, after for new UI). A short screen recording is fine too. If an AI agent did the work, include screenshots of the running app or a link to a published artifact page showing them. If nothing visible changed, tick "No UI change" in the template.
6. **Engineering, Security, and UX Checklist**: Confirm the plain-language checklist items in the template. The technical terms in parentheses provide context; reviewers should not need to know them in advance.

---

## 5. Validation Matrix

Match validation depth to risk. Always run targeted tests before opening a PR:

| Change Type | Minimum Validation Required |
|---|---|
| **Copy / Labels / Static Docs** | Review formatting, links, and STE clarity |
| **CSS / Spacing / Template Layout** | Visual screenshots + `uv run --no-sync ruff check src` |
| **Python View / Business Logic** | `uv run --no-sync ruff check src` + targeted test (`scripts/test.sh <dotted.label>`) |
| **API Endpoints / Serialization** | Targeted test + Spectacular OpenAPI regeneration + Contract tests |
| **Database Models / Migrations** | `uv run --no-sync python src/manage.py check_migration_hygiene --strict` + full test suite |
| **Upstream outcome port** | Classify in [UPSTREAM_PORTS.md](UPSTREAM_PORTS.md), adapt against the current graph, and run the migration sync gate + `scripts/replay_upgrade_matrix.sh` |

`upstream` is an exact upstream mirror. Do not merge or rebase it into `latest`;
port the accepted behavior through Floppy's existing boundaries. Keep targeted
regressions and fix confirmed baseline failures. Record a large or risky repair
that cannot safely be completed instead of silently treating it as green.

The [release checklist](docs/releasing.md) defines the complete offline,
browser/slow, MCP, dependency, migration, upgrade and built-image gates. A PR
run and a published artifact are separate evidence. Record what ran at the
actual source tree; do not reuse an older green run as a new commit's result.

---

## 6. What Gets Merged vs. Closed Without Review

### Fast Path to Merge
- Clean, focused PR targeting `latest`.
- Completed PR template with clear Problem, Solution, Issue links, and Validation.
- Post-mortem included for bug fixes.
- Specific AI model and workflow disclosure (if applicable).
- Screenshots included for all UI modifications.
- All tests, lint checks, and contract tests passing.
- Living documentation and OpenAPI spec updated to match code changes.

**UI consistency:** New UI must match existing patterns in the app — spacing, card styles, chip styles, color tokens, layout conventions. If your change introduces a visual pattern that doesn't appear anywhere else in the app, flag it explicitly in the PR description and justify it. Unexplained novel UI is a reason to close a PR.

**Colour and theming:** Colour goes through the `--color-*` tokens, never a raw palette utility and never Tailwind's `dark:` variant, which reads the OS instead of the user's chosen theme. There are six theme states to hold, not two. See [docs/architecture/theming.md](docs/architecture/theming.md); `src/app/tests/test_theme_tokens.py` enforces the two rules that are easiest to break.

**Logging:** Call `logger.info("...", value)` as usual. A process-wide log record factory redacts credentials before any handler writes them, so you do not need a wrapper or a manual sanitizer. Two things still need care: a rule matches the *name* of a value, so give secrets a name that ends in `token`, `secret`, `password`, `api_key` or similar, and never log a raw response body or a full URL — use `safe_url()`. See [docs/architecture/log-redaction.md](docs/architecture/log-redaction.md); `src/app/tests/test_log_safety.py` enforces the rules that are easiest to break.

**Lint cleanup:** Keep the zero-failure baseline. Confirm whether a discovered
failure predates the change, then fix it in a separate cleanup commit and,
where practical, a separate PR. A large or risky repair may need a documented
exception; state why and track the remaining work. Keep unrelated cleanup
separate from behavior changes so each patch remains reviewable.

---

## What Gets Closed Without Review

- PRs targeting `upstream` or `release`
- PRs with no description
- PRs with no problem/solution statement
- UI changes with no screenshots
- PRs that introduce UI patterns with no precedent elsewhere in the app and no explanation
- PRs where lint/style cleanup is bundled with behavior changes
- AI-assisted PRs that disclose only a tool/subscription name ("Claude Code", "Copilot") without naming the specific model
- PRs where commit count suggests the history was never organized (17 commits for a single UI feature is a signal)
