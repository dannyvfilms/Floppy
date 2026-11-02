# Consumption batches

`POST /api/v1/consumptions/batch/` plans or applies many consumption creates (for example a
historical backfill) without a long write transaction. Scope: `watchlist:write`; reading an
operation needs `watchlist:read`. Up to `CONSUMPTION_BATCH_MAX_ITEMS` (100) items per request.

## Workflow

1. **Dry-run** (default, `execute` omitted or `false`). Nothing is written. Each item is
   `{client_ref, media_type, source, media_id, status, start_date, end_date, progress, ...}`
   (the same fields as `POST /api/v1/media/{media_type}/`). The response is `200` with a
   result per item: `would_create`, `would_append`, `skip`, `ambiguous`, `invalid`
   (`errors` names the fields), `unavailable` (provider unreachable) or `not_found`.
   `existing` lists the item's current consumptions so the caller decides what counts as a duplicate.
2. **Equivalence is the caller's**, never a server window. Add
   `skip_if_existing: {"status": "Completed", "overlaps": true}` to an item to skip it when an
   existing entry has that status and dates intersecting the requested range.
3. **Execute** with `{"execute": true, "operation_id": "<your id, max 64>", "items": [...]}`.
   Returns `202 {operation_id, task_id}`; poll `GET /api/v1/consumptions/batch/{operation_id}/`
   (per-item `pending`, `running`, `created`, `skipped`, `failed`, `interrupted`, plus `consumption_id`).
   `/api/v1/tasks/{task_id}` reports the Celery task itself.

## Guarantees

- Each item is its own short transaction (consumption and its result row commit together), so a
  failing item never undoes the others and SQLite's writer lock is released between items.
- `(user, operation_id, client_ref)` is the idempotency key. Resubmitting an operation only runs
  unfinished items; reusing an `operation_id` with different item content is `409 idempotency_conflict`.
  An item stuck `running` for 15 minutes (worker died) is reported `interrupted` and is retried on resubmit;
  it cannot have created a consumption.
- Values are stored exactly as sent (`progress_source: "request"`). Nothing is filled from HLTB.
- v1 takes provider ids only (no title resolution), and not manual, video or episode items.

Code: `api/consumption_create.py` (shared create/plan), `api/consumption_batch.py`,
`api/fork_views_consumption_batch.py`. Tests: `api.tests.test_fork_consumption_batch`.
