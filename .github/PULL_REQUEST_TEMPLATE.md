## Summary
- What changed and why in plain, approachable terms.

## Screenshots
Does this PR change anything a person can see (pages, buttons, colours, layout, text)? If so, please show it:

- Add **before and after screenshots** (or a short screen recording) below. Drag and drop works. For brand-new UI, an after screenshot is enough.
- Cover each view you touched, and the phone layout if it changed.
- **If an AI agent did the work:** include screenshots of the running app, or a link to a published artifact page that shows them. A PR with visible changes and no pictures will be sent back.

Before:

After:

- [ ] No UI change (nothing visible is different, so no screenshots needed)

## AI Assistance
- If an AI assistant (such as Claude, Codex, Copilot) generated or shaped this code, specify the exact model name (e.g. `claude-sonnet-4-6`, `gpt-4o`).
- If no AI assistance was used, delete this section.

## How It Was Tested
- List the test commands you ran and their outcomes (e.g. `scripts/test.sh users.tests.views.test_about` -> Passed).

## Public API & Documentation Handoff
- [ ] Domain terminology is up to date (`python -m app.domain_vocabulary --check`)
- [ ] OpenAPI schema contracts verified (if API endpoints changed)
- [ ] Not applicable (no API or vocabulary changes)

## Human Review & Quality Assurance
- [ ] Code review completed
- [ ] Visual or manual QA verified (e.g. `/gstack-qa` or browser testing)

## Database & Migration Safety (Only if modifying models)
- [ ] No existing or shared migrations were altered or renumbered
- [ ] Migration hygiene passed (`uv run --no-sync python src/manage.py check_migration_hygiene --strict`)
- [ ] Not applicable (no database changes)

## Related Issues
- Link relevant issues and PRs (e.g. `Fixes #123`, `Refs #456`).

