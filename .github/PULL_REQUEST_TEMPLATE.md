## Summary
- Describe what changed and why.
- Link related issues in relationship fields (e.g., `Fixes #123` / `Refs #456`).

## Post-Mortem / Root Cause Analysis (Bug Fixes)
<!-- If fixing a defect: what caused the issue, what broke, and how this fix prevents recurrence? (Omit if feature/enhancement) -->

## AI Assistance & Workflows
- **AI Model**: <!-- Specific model identifier, e.g. claude-3-7-sonnet, gemini-2.5-pro, gpt-5.1-codex, or "None (human authored)" -->
- **Workflows & Tools**: <!-- Workflows used, e.g. gstack QA, Ponytail complexity audit, OpenSpec, manual testing -->
*(Note: A tool/subscription wrapper name alone like "Cursor" or "Claude Code" is insufficient — name the exact underlying model.)*

## Engineering, Security & UX Checklist
- [ ] **Single Source of Truth & Simplicity**: Reused existing models/helpers where possible; avoided speculative abstractions.
- [ ] **Domain Boundaries & Vocabulary**: Respected bounded domain contexts (`app`, `users`, `lists`, `integrations`, `events`) and ubiquitous language.
- [ ] **Security (OWASP Avoidance)**: Verified tenancy/IDOR scoping (`user=request.user`), ORM injection safety, SSRF validation on external fetch, SecretBox credential storage, and CSRF tokens.
- [ ] **UI/UX & Accessibility**: Checked Gestalt visual hierarchy, Nielsen heuristics, WCAG a11y (keyboard/contrast/labels), and cognitive/ADHD scannability.
- [ ] **Living Docs & OpenAPI**: Checked and updated OpenAPI spec, domain vocabulary, or developer docs if payloads/contracts changed.

## Validation
- List commands run and test outcomes.

## Contract & Documentation Handoff
- Domain guide regeneration/check outcome: <!-- result or not applicable -->
- Verified OpenAPI regeneration outcome: <!-- result or not applicable -->
- Contract-test outcome: <!-- result or not applicable -->

## UI Screenshots
<!-- Required for all CSS, template, or visual UI changes (Before/After for fixes, After for new features) -->

## Review & QA Gates
- [ ] **Human Review**: <!-- Pending / Completed with reviewer name -->
- [ ] **Gstack QA / Browser Testing**: <!-- Pending / Completed with outcome -->

## Migration Sync Gate (Required for `upstream` -> `latest` sync PRs)
- [ ] Conflicts resolved with upstream files preserved and fork behavior merged intentionally.
- [ ] Migration conflicts handled per policy (no rewrite of shared/released migrations).
- [ ] `uv run --no-sync python src/manage.py makemigrations --merge` run for affected apps.
- [ ] `uv run --no-sync python src/manage.py check_migration_hygiene --strict` passed.
- [ ] `scripts/replay_upgrade_matrix.sh --from-tag <previous_release_tag> --to-ref latest --db sqlite,postgres --with-drift-scenarios` passed.
- [ ] `uv run --no-sync coverage run src/manage.py test app users integrations lists events --parallel` passed.

## Notes
- Additional context or follow-ups.
