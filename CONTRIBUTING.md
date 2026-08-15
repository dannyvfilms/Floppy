# Contributing to Floppy

Floppy is a self-hosted media tracking platform forked from [FuzzyGrim/Yamtrack](https://github.com/FuzzyGrim/Yamtrack). We welcome contributions from developers and AI-assisted workflows alike.

Our bar is practical: **make changes clean, minimal, safe, and well-understood.** This guide provides clear instructions to help contributors build, test, and ship high-leverage pull requests that land quickly.

---

## Quick Reference

| Area | Requirement | Command / Reference |
|---|---|---|
| **Branch Target** | Always target `latest` (never `upstream` or `release`) | `git checkout -b feat/my-feature latest` |
| **PR Template** | Mandatory; do not delete or strip sections | [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) |
| **Python Tooling** | Python 3.12 + `uv` | `uv sync --locked` |
| **Tailwind CSS** | Pinned repo CLI output to `src/static/css/main.css` | `npx @tailwindcss/cli -i ./src/static/css/input.css -o ./src/static/css/main.css` |
| **Fast Tests** | Targeted test runner | `SECRET=test-only scripts/test.sh <dotted.path>` |
| **Lint / Style** | Ruff (line length 88, migrations excluded) | `uv run --no-sync ruff check src` |

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
- **Credential Storage & Secrets**: Never commit tokens, passwords, or API keys. Store secrets in environment variables or use encrypted database fields (`SecretBox` for external provider credentials).
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
Every pull request **must use [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)**. Do not delete, bypass, or strip template sections.

The template requires:
1. **Summary & Linked Issues**: Describe what changed and why. Always link related issues in relationship fields (`Fixes #123`, `Refs #456`).
2. **Post-Mortem / Root Cause**: For bug fixes, provide a concise post-mortem explaining what caused the defect and how the fix prevents recurrence.
3. **AI Assistance & Workflows**: If an AI coding agent or tool generated or shaped the code:
   - **Disclose the specific model**: Name the exact underlying model identifier (e.g., `claude-3-7-sonnet`, `gemini-2.5-pro`, `gpt-5.1-codex`).
   - **Disclose workflows used**: State tools and review workflows utilized (e.g., gstack QA, Ponytail review, OpenSpec, manual testing).
   > Note: A generic tool wrapper name alone ("Cursor", "Claude Code", "Copilot") is **insufficient**. You must state the underlying model.
4. **Validation**: List exact commands executed and resulting outcomes.
5. **Screenshots**: Required for all UI, CSS, template, and visual layout changes (before/after for bug fixes, after for new UI).
6. **Engineering & Security Checklist**: Confirm adherence to single-source-of-truth, domain boundaries, security rules, and living documentation updates.

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
| **Upstream Sync (`upstream` → `latest`)** | Migration sync gate + `scripts/replay_upgrade_matrix.sh` |

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

### What Gets Closed Without Review
- PRs targeting `upstream` or `release`.
- PRs that delete or ignore the PR template.
- PRs with blank, vague, or generic descriptions ("fixes stuff", "update").
- UI modifications without screenshots.
- Undisclosed or ambiguously disclosed AI PRs (stating only "Copilot" or "Claude" without the model).
- PRs bundling massive unrelated formatting or lint cleanup with feature changes.
- PRs introducing unpatterned UI paradigms without justification.
