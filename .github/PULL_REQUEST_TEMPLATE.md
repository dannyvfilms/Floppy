## Summary
<!-- Start with a plain-language explanation of what changed and why. Add technical details after the main explanation when useful. -->
- Describe what changed and why.
- Link related issues, if any (e.g., `Fixes #123` / `Refs #456`).

## Bug Fix Explanation (Post-Mortem / Root Cause Analysis)
<!-- If fixing a defect: explain what went wrong and how this fix prevents it from happening again. Omit if this is a feature or enhancement. -->

## AI Assistance and Workflows
- **AI model**: <!-- Name the specific model, e.g. claude-3-7-sonnet, gemini-2.5-pro, gpt-5.1-codex, or "None (human authored)". -->
- **Tools and workflows used**: <!-- Examples: gstack QA, Ponytail complexity review, OpenSpec, or manual testing. -->
<!-- Name the model that did the work, not only the application used to access it (for example, Cursor or Claude Code). -->

## Engineering, Security, and UX Checklist
- [ ] **Keep each rule in one place instead of duplicating it** (single source of truth / DRY).
- [ ] **Keep related code together and use consistent names** (bounded contexts / ubiquitous language).
- [ ] **Protect user data, secrets, forms, and external connections** (OWASP / IDOR / SSRF / CSRF).
- [ ] **Make the interface clear, readable, keyboard-friendly, and accessible** (Gestalt / Nielsen / WCAG / a11y).
- [ ] **Keep the API reference and related documentation in sync** (OpenAPI / contract hygiene).
<!-- If a checklist item does not apply, write "Not applicable" in the PR description or Notes section. -->

## Checks Run
- List the commands, tests, screenshots, or manual checks completed and their outcomes.

## Documentation and API Follow-up (Contract Handoff)
- Domain guide update/check: <!-- Result, or "Not applicable". -->
- API reference update/check: <!-- Result, or "Not applicable". -->
- Related contract tests: <!-- Result, or "Not applicable". -->

## Screenshots (When the Interface Changes)
<!-- Required for CSS, template, layout, or other visual changes. Include before and after images for fixes, and an after image for new features. -->

## Human Review and Browser/UI Checks
- [ ] **Human review**: <!-- Pending / Completed with reviewer name -->
- [ ] **Browser/UI checks** (Gstack QA, when applicable): <!-- Pending / Completed with outcome -->

## Upstream Sync Checks (Migration Sync Gate)
<!-- Complete this section only when bringing changes from the upstream project into latest. These checks help confirm that code and database changes can be applied safely. -->
- [ ] Conflicts resolved while preserving upstream changes and Floppy-specific behavior.
- [ ] Database migration conflicts handled safely; released migrations were not rewritten.
- [ ] `uv run --no-sync python src/manage.py makemigrations --merge` run for affected apps.
- [ ] `uv run --no-sync python src/manage.py check_migration_hygiene --strict` passed.
- [ ] `scripts/replay_upgrade_matrix.sh --from-tag <previous_release_tag> --to-ref latest --db sqlite,postgres --with-drift-scenarios` passed.
- [ ] `uv run --no-sync coverage run src/manage.py test app users integrations lists events --parallel` passed.

## Notes and Follow-ups
- Additional context, known limitations, or follow-up work.
